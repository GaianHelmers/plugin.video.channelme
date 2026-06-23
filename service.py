# -*- coding: utf-8 -*-
#
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 GaianHelmers
#
# ChannelMe! - background service
#
# Runs continuously while Kodi is open and manages the channel that is currently
# playing (described by the storage 'playback' block written when a channel is
# started). Three jobs:
#
#   1. Record progress: when an item starts, the show's saved resume pointer is
#      set to the episode ACTUALLY playing - so stopping mid-episode resumes that
#      episode (serial_random only).
#   2. Keep it endless: when playback nears the end of the queue, more items are
#      generated and appended to the live playlist.
#   3. Regenerate on manual jump: if the user skips ahead/back in the playlist
#      (position moves by more than +1), the stale future is trimmed and rebuilt
#      so skipped shows resume from where they were actually last watched, while
#      the show jumped to continues from there.
#
# A positions entry is [title_key, index, file]; the file confirms the item now
# playing is really ours before we touch pointers or the playlist.

import json

import xbmc
import xbmcgui

from resources.lib import scheduler
from resources.lib import storage

# The standalone "Now Playing" video playlist window. Browsing it while we mutate
# the live playlist by JSON-RPC makes the GUI fight our edits, so we step out of
# it before regenerating.
WINDOW_VIDEO_PLAYLIST = 10028

TOPUP_THRESHOLD = 10   # generate more when this few items remain ahead
TOPUP_BATCH = 20
POLL_SECONDS = 5

# Tracks the last owned position so we can spot manual jumps across item starts.
_LAST = {'session': None, 'pos': None}


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------

def _log(message):
    xbmc.log('ChannelMe! ' + message, xbmc.LOGINFO)


def _video_playlist():
    return xbmc.PlayList(xbmc.PLAYLIST_VIDEO)


def _owned_position(playback):
    """Current playlist index if the item playing matches our recorded session,
    else None (so we never write progress / append onto unrelated playback)."""
    positions = playback.get('positions') or []
    pos = _video_playlist().getposition()
    if pos < 0 or pos >= len(positions):
        return None
    try:
        playing = xbmc.Player().getPlayingFile()
    except Exception:
        return None
    expected = positions[pos][2] if len(positions[pos]) >= 3 else None
    if expected and playing and expected != playing:
        return None
    return pos


def _playlist_remove(index):
    """Remove one item from the video playlist by position (reliable by index)."""
    request = {'jsonrpc': '2.0', 'id': 1, 'method': 'Playlist.Remove',
               'params': {'playlistid': xbmc.PLAYLIST_VIDEO, 'position': index}}
    xbmc.executeJSONRPC(json.dumps(request))


def _leave_playlist_window():
    """If the user is sitting in the Now Playing playlist window, step out before we
    rebuild the playlist - editing it underneath the open window conflicts."""
    if xbmcgui.getCurrentWindowId() == WINDOW_VIDEO_PLAYLIST:
        xbmc.executebuiltin('Action(Back)')


# ----------------------------------------------------------------------------
# Jobs
# ----------------------------------------------------------------------------

def record_progress():
    data = storage.load()
    playback = data.get('playback')
    if not playback or playback.get('mode') != 'serial_random':
        return

    pos = _owned_position(playback)
    if pos is None:
        return

    entry = playback['positions'][pos]
    title_key, index = entry[0], entry[1]
    channel_id = playback.get('channel_id')
    if not channel_id:
        return

    pointers = data.setdefault('state', {}).setdefault(channel_id, {}).setdefault('pointers', {})
    if pointers.get(title_key) == index:
        return
    pointers[title_key] = index
    storage.save(data)


def regenerate_after_jump(pos):
    """Rebuild the queue after a manual jump: skipped shows fall back to their last
    watched episode; the jumped-to show continues from the current one."""
    data = storage.load()
    playback = data.get('playback')
    if not playback or playback.get('mode') != 'serial_random':
        return
    positions = playback.get('positions') or []
    if pos < 0 or pos >= len(positions):
        return

    current_key, current_index = positions[pos][0], positions[pos][1]
    channel_id = playback.get('channel_id')

    # Continue every show from where the SURVIVING queue already had it - this is
    # the build state the user sees, so skipping ahead never snaps a show back to
    # episode 1 (which the lagging resume pointer would have caused).
    lookahead = scheduler.cursor_from_positions(positions[:pos + 1])
    # Shows that only appeared in the now-trimmed tail aren't in the surviving
    # prefix; fall back to their last actually-watched episode (resume pointer).
    for key, idx in data.get('state', {}).get(channel_id, {}).get('pointers', {}).items():
        lookahead.setdefault(key, idx)
    lookahead[current_key] = current_index + 1   # current show keeps going

    # Step off the playlist window first, then trim the now-stale future from the
    # live playlist (top-down by position).
    _leave_playlist_window()
    playlist = _video_playlist()
    trimmed = max(0, playlist.size() - 1 - pos)
    for index in range(playlist.size() - 1, pos, -1):
        _playlist_remove(index)

    picks, new_positions, last_key, run = scheduler.build_items(
        playback['titles'], 'serial_random', lookahead, TOPUP_BATCH,
        playback.get('max_consecutive', 2), current_key, 1,
        always=playback.get('consec_always', False))
    for pick in picks:
        playlist.add(pick['file'], scheduler.make_list_item(pick))

    _log('regen @pos {0} ({1}#{2}): trimmed {3}, appended {4}; next={5}'.format(
        pos, current_key, current_index, trimmed, len(picks),
        [p['label'] for p in picks[:4]]))

    playback['positions'] = positions[:pos + 1] + new_positions
    playback['lookahead'] = lookahead
    playback['last_key'] = last_key
    playback['run'] = run
    storage.save(data)


def topup():
    data = storage.load()
    playback = data.get('playback')
    if not playback:
        return

    playlist = _video_playlist()
    pos = playlist.getposition()
    size = playlist.size()
    if size <= 0 or pos < 0 or (size - pos) > TOPUP_THRESHOLD:
        return
    if _owned_position(playback) is None:
        return

    picks, positions, last_key, run = scheduler.build_items(
        playback['titles'], playback['mode'], playback.get('lookahead', {}), TOPUP_BATCH,
        playback.get('max_consecutive', 2), playback.get('last_key'), playback.get('run', 0),
        always=playback.get('consec_always', False))
    if not picks:
        return

    for pick in picks:
        playlist.add(pick['file'], scheduler.make_list_item(pick))
    playback['positions'].extend(positions)
    playback['last_key'] = last_key
    playback['run'] = run
    storage.save(data)


def detect_jump():
    """Spot a manual jump (position not advancing by exactly +1) and regenerate."""
    data = storage.load()
    playback = data.get('playback')
    if not playback:
        return

    pos = _owned_position(playback)
    if pos is None:
        return

    session = playback.get('session')
    if _LAST['session'] != session:        # fresh channel start - just anchor
        _LAST['session'] = session
        _LAST['pos'] = pos
        return

    previous = _LAST['pos']
    jumped = previous is not None and pos != previous + 1
    _LAST['pos'] = pos
    if jumped and playback.get('mode') == 'serial_random':
        _log('jump detected: pos {0} -> {1}; regenerating'.format(previous, pos))
        regenerate_after_jump(pos)


# ----------------------------------------------------------------------------
# Player + main loop
# ----------------------------------------------------------------------------

class ChannelPlayer(xbmc.Player):
    def onAVStarted(self):
        record_progress()
        detect_jump()
        topup()


def main():
    xbmc.log('ChannelMe! service started', xbmc.LOGINFO)
    monitor = xbmc.Monitor()
    player = ChannelPlayer()       # kept alive for the service lifetime
    while not monitor.abortRequested():
        if xbmc.Player().isPlayingVideo():
            topup()
        if monitor.waitForAbort(POLL_SECONDS):
            break
    del player


if __name__ == '__main__':
    main()
