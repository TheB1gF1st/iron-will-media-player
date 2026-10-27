<p align="center"><img src="ironwill/assets/icon-1024.png" width="160" alt="Iron Will Media Player icon"></p>

# Iron Will Media Player

**I will play anything.** A Windows media player with the clean, fading look of Microsoft *Movies & TV* on the
surface and the depth of MPC-BE underneath, built on [mpv](https://mpv.io) so it plays virtually every video and audio
format there is.

## Download

**[⬇ Download the latest release](https://github.com/TheB1gF1st/iron-will-media-player/releases/latest)**: a
ready-to-run zip for Windows 10/11 (64-bit). No installer and no Python needed: unzip it anywhere and double-click
**Iron Will.exe**. mpv and FFmpeg are included.

Tip: before unzipping, right-click the zip > Properties > tick **Unblock** > OK. Otherwise Windows asks
"Are you sure you want to run this software?" the first time (the app isn't code-signed yet).

## Support

Iron Will is free and always will be. If it's made your movie nights better, you can buy me a coffee on
**[Ko-fi ♥](https://ko-fi.com/ironwillmedia)**. It helps keep the updates coming.

## Screenshots

<p align="center"><img src="docs/screenshots/player.jpg" width="900" alt="Iron Will playing a video with its clean Movies & TV style controls"></p>

| | |
|---|---|
| <img src="docs/screenshots/ab-loop-clip.jpg" alt="A-B loop marked on the timeline with the Save A-B Clip menu"><br>**A-B loop + save the loop as its own clip** | <img src="docs/screenshots/menu.jpg" alt="Right-click menu"><br>**MPC-BE-depth right-click menu** |
| <img src="docs/screenshots/options-mouse.jpg" alt="Options window, mouse page"><br>**Options: every mouse button, your way** | <img src="docs/screenshots/duplicate-finder.jpg" alt="Duplicate Finder results"><br>**Built-in Duplicate Finder** |
| <img src="docs/screenshots/compare.jpg" alt="Side-by-side duplicate compare"><br>**Side-by-side compare of duplicates** | |

<sub>Demo video: "Spooky Stories with Aleera!", an original AI-animated short by I Will Media.</sub>

<details>
<summary><b>All menus &amp; settings (38 more screenshots)</b></summary>

<img src="docs/screenshots/all/01.jpg" width="49%"> <img src="docs/screenshots/all/02.jpg" width="49%"> <img src="docs/screenshots/all/03.jpg" width="49%"> <img src="docs/screenshots/all/04.jpg" width="49%"> <img src="docs/screenshots/all/05.jpg" width="49%"> <img src="docs/screenshots/all/06.jpg" width="49%"> <img src="docs/screenshots/all/07.jpg" width="49%"> <img src="docs/screenshots/all/08.jpg" width="49%"> <img src="docs/screenshots/all/09.jpg" width="49%"> <img src="docs/screenshots/all/10.jpg" width="49%"> <img src="docs/screenshots/all/11.jpg" width="49%"> <img src="docs/screenshots/all/12.jpg" width="49%"> <img src="docs/screenshots/all/13.jpg" width="49%"> <img src="docs/screenshots/all/14.jpg" width="49%"> <img src="docs/screenshots/all/15.jpg" width="49%"> <img src="docs/screenshots/all/16.jpg" width="49%"> <img src="docs/screenshots/all/17.jpg" width="49%"> <img src="docs/screenshots/all/18.jpg" width="49%"> <img src="docs/screenshots/all/19.jpg" width="49%"> <img src="docs/screenshots/all/20.jpg" width="49%"> <img src="docs/screenshots/all/21.jpg" width="49%"> <img src="docs/screenshots/all/22.jpg" width="49%"> <img src="docs/screenshots/all/23.jpg" width="49%"> <img src="docs/screenshots/all/24.jpg" width="49%"> <img src="docs/screenshots/all/25.jpg" width="49%"> <img src="docs/screenshots/all/26.jpg" width="49%"> <img src="docs/screenshots/all/27.jpg" width="49%"> <img src="docs/screenshots/all/28.jpg" width="49%"> <img src="docs/screenshots/all/29.jpg" width="49%"> <img src="docs/screenshots/all/30.jpg" width="49%"> <img src="docs/screenshots/all/31.jpg" width="49%"> <img src="docs/screenshots/all/32.jpg" width="49%"> <img src="docs/screenshots/all/33.jpg" width="49%"> <img src="docs/screenshots/all/34.jpg" width="49%"> <img src="docs/screenshots/all/35.jpg" width="49%"> <img src="docs/screenshots/all/36.jpg" width="49%"> <img src="docs/screenshots/all/37.jpg" width="49%"> <img src="docs/screenshots/all/38.jpg" width="49%">

</details>


## Highlights

**The look**
- Movies & TV-style controls that fade in over the video on a soft gradient and fade away while you watch (paused too)
- Three views: **Compact** (clean), **Normal** (menu bar) and **Minimal** (no border at all, drag the video to move it,
  edges to resize, a corner ✕ and a drop-down close button at the top)
- Every button flashes red when clicked; choose your own title colour

**Playback**
- Plays anything mpv/FFmpeg can (MKV, MP4, AVI, HEVC, AV1, …) with hardware decoding
- **Next / previous file follows File Explorer's sort** (name, date, size…), not just A-Z, with optional looping
- **"Welcome back" card:** continue where you left off or start over (only for files you open yourself; next / previous and auto-play always start from the beginning, and positions are forgotten after 7 days by default, adjustable to any number of days)
- **Preferred audio language** (e.g. always English, even when a file defaults to Japanese), with a title-based fallback
  for badly tagged files; subtitles start off until you want them
- **Foreign dialogue always subtitled:** lines spoken in another language (Dothraki, Kahndaqi, Klingon, or a real
  language) show automatically even with subtitles off. Iron Will finds a "forced" subtitle file online
  (OpenSubtitles, foreign parts only), or translates real languages offline with Whisper (model downloads on first use)
  and lines downloaded subtitles up with your copy's audio automatically
- **A-B loop** markers on the timeline: draggable, toggle per marker, remembered per file, and **saved as their own
  video clip** from a right-click on the seek bar (fast copy or frame-accurate)
- **Window transparency** like Glass2K, built in: View → Transparency, Ctrl+Shift+↑/↓, or Ctrl+Shift+1…0
- Seek-bar **picture preview**, chapter marks, and a full-screen clock
- Playback rate in 5% steps (configurable) from the bottom bar, the menu or Ctrl+↑/↓
- Click-and-hold: right third fast-forwards, left third rewinds

**Power-user depth**
- An **MPC-BE-style Options window** (22 pages) with MPC-BE's options: default video frame, aspect override, scalers,
  debanding, HDR tone mapping, color management, shaders, refresh-rate matching in full screen, audio output,
  balance, gain and normalisation, subtitle styling, encodings and folders, remembered tracks, startup window size,
  snap to edges, pause when minimized, tray icon, global media keys, taskbar progress and buttons, file types,
  custom keys, cache, decoders, and any extra mpv option
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

To build the ready-to-run release yourself: `pip install pyinstaller faster-whisper`, point the build at your copies
of libmpv and FFmpeg, then run it (the recipe is `tools/iron_will.spec`):

```
set IW_LIBMPV=C:\path\to\libmpv-2.dll
set IW_FFMPEG_DIR=C:\path\to\ffmpeg-build
python tools\build_release.py
```

`IW_FFMPEG_DIR` is the folder that has `bin\ffmpeg.exe` and `bin\ffprobe.exe`. The online subtitle search needs an
OpenSubtitles API key in a file called `opensubs.key` next to `IronWill.pyw` (kept out of the repository); without
it, making subtitles from the audio still works.

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
| Ctrl+← / → | Small jump | Ctrl+U | Open URL |
| F1 / F2 | Subtitle delay − / + | − / + | Audio delay − / + |
| Ctrl+Shift+↑ / ↓ | More solid / more transparent | Ctrl+Shift+1…0 | Transparency 10%…100% |

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
