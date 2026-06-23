# Screenshots

Drop capture images here for the project README (and, optionally, the Kodi add-on
page). Expected filenames, referenced by `../../README.md`:

| File | Suggested shot |
| --- | --- |
| `channel-list.png` | The ChannelMe! channel list (with a few channels + the Add row). |
| `editor-titles.png` | The editor's Titles panel showing the TV / Sets / Movies / Files filters. |
| `play-randomized.png` | The library context menu with **Play Randomized** highlighted. |
| `add-to-channel.png` | The **Add to Channel** picker dialog. |

Recommended size: 1280×720 or 1920×1080 PNG/JPG.

To also surface them on Kodi's add-on page, add `<screenshot>` lines under
`<assets>` in `addon.xml`, e.g.:

```xml
<assets>
  <icon>resources/icon.png</icon>
  <fanart>resources/ChannelMeFullscreenBackground.png</fanart>
  <screenshot>docs/screenshots/channel-list.png</screenshot>
  <screenshot>docs/screenshots/editor-titles.png</screenshot>
</assets>
```
