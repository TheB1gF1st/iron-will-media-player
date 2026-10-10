<p align="center"><img src="ironwill/assets/icon-1024.png" width="160" alt="Iron Will Media Player icon"></p>

# Iron Will Media Player

**I will play anything.** A Windows media player with the clean, fading look of Microsoft *Movies & TV* on the
surface and the depth of MPC-BE underneath, built on [mpv](https://mpv.io) so it plays virtually every video and audio
format there is.

## Download

**[⬇ Download the latest release](https://github.com/TheB1gF1st/iron-will-media-player/releases/latest)**: a
ready-to-run zip for Windows 10/11 (64-bit). No installer and no Python needed: unzip it anywhere and double-click
**Iron Will.exe**. mpv and FFmpeg are included.

## Highlights

**The look**
- Movies & TV-style controls that fade in over the video on a soft gradient and fade away while you watch (paused too)
- Three views: **Compact** (clean), **Normal** (menu bar) and **Minimal** (no border at all, drag the video to move it,
  edges to resize, a corner ✕ and a drop-down close button at the top)
- Every button flashes red when clicked; choose your own title colour

**Playback**
- Plays anything mpv/FFmpeg can (MKV, MP4, AVI, HEVC, AV1, …) with hardware decoding
- **Next / previous file follows File Explorer's sort** (name, date, size…), not just A-Z, with optional looping
- **"Welcome back" card:** continue where you left off or start over
- **Preferred audio language** (e.g. always English, even when a file defaults to Japanese), with a title-based fallback
  for badly tagged files; subtitles start off until you want them
- **A-B loop** markers on the timeline: draggable, toggle per marker, remembered per file
- Playback rate in 5% steps (configurable) from the bottom bar, the menu or Ctrl+↑/↓
- Click-and-hold: right third fast-forwards, left third rewinds

**Power-user depth**
- An **MPC-BE-style Options window** (21 pages): scalers, debanding, HDR tone mapping, shaders, audio output and
  normalisation, subtitle styling, custom keys, cache, decoders, and any extra mpv option
- **MPC-BE-style mouse bindings**: every button and wheel direction × Normal / Ctrl / Shift / right-button-held
- **Import your MPC-BE settings** (languages, mouse setup, subtitle style, …) in one click
- MPC-BE-style right-click and title-bar menus: Video Frame, Pan&Scan, Zoom, After Playback (incl. shutdown), Favorites,
  Recent files, Properties (Shift+F10)

**Find Duplicates** (Ctrl+D)
- Finds copies of the same video even when they were re-encoded, resized, **mirrored**, **cut into clips** or given an
  **added intro**, using perceptual fingerprints along the whole video plus a frame-exact check
- **Side-by-side compare** with synced playback and an automatically measured time offset
- Extra copies go to the **Recycle Bin**, never deleted permanently

## Requirements

- Windows 10 or 11 (64-bit)
- Python 3.12+ with the packages in `requirements.txt`
- **libmpv**: `libmpv-2.dll` from an mpv Windows build (e.g. the
  [shinchiro builds](https://github.com/shinchiro/mpv-winbuild-cmake/releases), the `mpv-dev-x86_64-…` archive).
  Put it in this folder or an `mpv` subfolder.
- **FFmpeg** (only for Find Duplicates): put `ffmpeg.exe` and `ffprobe.exe` in an `ffmpeg` subfolder or on your PATH.

## Running from source

```bat
pip install -r requirements.txt
pythonw IronWill.pyw
```

Optional extras:

```bat
:: a real IronWill.exe launcher with the app icon (uses the C# compiler built into Windows)
python tools\build_launcher.py
:: register Iron Will with Windows so it shows up in "Open with" and Default apps (current user only)
python tools\register_windows.py
```

If your Python isn't at the default location, put the path to `pythonw.exe` in a file called `python-path.txt` next to
`IronWill.exe`.

To build the ready-to-run release yourself: `pip install pyinstaller`, set the libmpv and FFmpeg paths at the top of
`tools/build_release.py`, then run `python tools\build_release.py 1.0.0`.

## Keyboard basics

| Key | Action | Key | Action |
|---|---|---|---|
| Space / K | Play / pause | F / F11 | Full screen |
| ← / → | Jump back / forward | Shift+← / → | Back / forward button jump |
| ↑ / ↓ | Volume | M | Mute |
| Ctrl+↑ / ↓ / R | Faster / slower / normal speed | Ctrl+G | Go to a time |
| PgUp / PgDn | Previous / next file | Ctrl+B | Border on / off |
| Shift+S | Save current frame | Shift+F10 | Properties |
| O | Options | Ctrl+D | Find Duplicates |

All shortcuts and mouse buttons can be changed in **Options → Player → Keys / Mouse**.

## Project layout

```
IronWill.pyw            entry point
ironwill/engine.py      mpv wrapper (Qt signals)
ironwill/video_view.py  mpv render API -> OpenGL widget (lets the controls float over the video)
ironwill/ui/            main window, menus, options, properties
ironwill/dupes/         duplicate finder (fingerprints, matching, compare window)
ironwill/settings.py    every option, defined once
tools/                  icon, launcher and Windows registration helpers
```

## License

GPL-3.0. See [LICENSE](LICENSE). Iron Will is built on mpv, Qt for Python (PySide6), NumPy and FFmpeg; each keeps its
own license.
