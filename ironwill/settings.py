"""Settings model for the Options window: every option is declared once here (label, default, range, and the
mpv option it drives). The dialog builds its pages from this schema, Config saves the values as JSON, and
apply_to_mpv pushes them into the running player."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "IronWillMediaPlayer"
CONFIG_FILE = DATA_DIR / "settings.json"


@dataclass
class S:
    key: str
    label: str
    default: object
    choices: list = None          # [(value, label)] -> combo box
    mpv: object = None            # mpv option name, or tuple of alternative names (newest first)
    lo: float = 0
    hi: float = 100
    step: float = 1
    suffix: str = ""
    kind: str = ""                # "", "color", "font", "folder", "text", "device", "multiline"
    tip: str = ""
    to_mpv: object = None         # callable converting the stored value to what mpv expects
    zero_text: str = ""           # number settings: what to show instead of 0 (e.g. "Never forget")


@dataclass
class Page:
    id: str
    title: str
    parent: str = None
    groups: list = field(default_factory=list)   # [(group title, [S, ...])]
    special: str = ""                             # "keys", "shaders" or "about" for custom pages
    note: str = ""


# Language choice -> (codes mpv matches against track language tags, words to look for in track titles).
LANGUAGES = {
    "": ("", ""),
    "en": ("eng,en,english", r"\b(english|eng)\b|\benglish dub"),
    "ja": ("jpn,ja,japanese", r"\b(japanese|jpn|jap)\b|日本語"),
    "es": ("spa,es,spanish", r"\b(spanish|español|espanol|castellano|latino|spa)\b"),
    "fr": ("fre,fra,fr,french", r"\b(french|français|francais|fre|fra)\b"),
    "de": ("ger,deu,de,german", r"\b(german|deutsch|ger|deu)\b"),
    "it": ("ita,it,italian", r"\b(italian|italiano|ita)\b"),
    "pt": ("por,pt,portuguese", r"\b(portuguese|português|portugues|por)\b"),
    "ru": ("rus,ru,russian", r"\b(russian|русский|rus)\b"),
    "ko": ("kor,ko,korean", r"\b(korean|kor)\b|한국어"),
    "zh": ("chi,zho,zh,chinese", r"\b(chinese|mandarin|cantonese|chi|zho)\b|中文"),
    "hi": ("hin,hi,hindi", r"\b(hindi|hin)\b"),
    "ar": ("ara,ar,arabic", r"\b(arabic|ara)\b"),
}
LANG_CHOICES = [("", "File's default (no preference)"), ("en", "English"), ("ja", "Japanese"), ("es", "Spanish"),
                ("fr", "French"), ("de", "German"), ("it", "Italian"), ("pt", "Portuguese"), ("ru", "Russian"),
                ("ko", "Korean"), ("zh", "Chinese"), ("hi", "Hindi"), ("ar", "Arabic")]

YES_NO = lambda v: "yes" if v else "no"
MIB = lambda v: f"{int(v)}MiB"

PAGES = [
    Page("player", "Player", groups=[
        ("History", [
            S("resume", "When I reopen a file I've watched", "ask",
              [("ask", "Ask: continue or start over"), ("always", "Continue automatically"),
               ("never", "Always start from the beginning")],
              tip="Only when you open a file yourself. Moving to the next / previous file in a folder always starts it from the beginning."),
            S("resume_days", "Forget where I left off after", 7, lo=0, hi=9999, suffix=" days", zero_text="Never forget",
              tip="Type any number of days. Set it to 0 to never forget."),
            S("after_playback", "When a file ends", "next",
              [("next", "Play the next file in the folder"), ("next_loop", "Play the next file (start over after the last)"),
               ("nothing", "Do nothing"), ("rewind", "Go back to the start and pause"), ("close", "Close the file"),
               ("close_minimize", "Close the file and minimize"), ("exit", "Exit Iron Will")]),
            S("remember_volume", "Remember the volume between sessions", True),
            S("remember_mute", "Remember mute between sessions", False),
            S("history_max", "Remember where I left off in up to", 500, lo=10, hi=5000, step=10, suffix=" files"),
            S("fav_position", "Favorites reopen at the saved time", True),
            S("remember_tracks", "Remember the audio and subtitle tracks I pick for each file", True,
              tip="MPC-BE: Player > Remember selected audio and subtitle tracks"),
            S("recent_count", "Recent files to remember", 20, lo=0, hi=100, zero_text="Don't keep a history",
              tip="How many files File > Recent shows. 0 turns the history off and clears it."),
        ]),
        ("Opening files", [
            S("allow_multiple", "Allow multiple Iron Will windows (each video opens in its own window)", True,
              tip="Checked: every video you open gets its own window. Unchecked: new videos play in the window "
                  "that's already open. Takes effect the next time Iron Will starts."),
            S("next_on_error", "If a file won't open, skip to the next one in the folder", True),
            S("paste_url", "Open URL fills in a link from the clipboard", True),
            S("keep_speed", "Keep the playback speed when the next file opens", False,
              tip="Off: every file starts at normal speed (MPC-BE's default)"),
            S("auto_fit", "When a video opens, resize the window", "off",
              [("off", "No, keep the window as it is"), ("video", "To the video's own size (shrunk to fit the screen)"),
               ("50", "To fit within 50% of the screen"), ("75", "To fit within 75% of the screen")],
              tip="Only in a normal window, not full screen, maximized or mini view"),
        ]),
        ("Title", [
            S("title_mode", "Title shows", "file", [("file", "File name"), ("media", "Media title (from tags)")]),
        ]),
        ("Seeking", [
            S("skip_back", "Back button jumps", 10, lo=1, hi=600, suffix=" s"),
            S("skip_fwd", "Forward button jumps", 30, lo=1, hi=600, suffix=" s"),
            S("arrow_step", "Left / Right arrow keys jump", 10, lo=1, hi=600, suffix=" s"),
            S("small_step", "Ctrl + Left / Right jump", 1, lo=1, hi=600, suffix=" s"),
            S("volume_step", "Up / Down and wheel volume step", 5, lo=1, hi=25, suffix=" %"),
        ]),
    ]),
    Page("interface", "Interface", "player", groups=[
        ("Controls", [
            S("hide_delay", "Hide controls after", 2.5, lo=1, hi=15, step=0.5, suffix=" s"),
            S("show_chevrons", "Show previous / next arrows at the sides", True),
            S("title_color", "Title color (the video name above the timeline)", "#FFFFFF", kind="color"),
            S("controls_gap", "Controls distance from the bottom edge", 24, lo=0, hi=96, step=2, suffix=" px",
              tip="Raise or lower the seek bar and buttons. 24 px is about a quarter inch on most screens."),
            S("show_menubar", "Show the menu bar (File, View, Play, Navigate, Favorites, Help)", False),
            S("taskbar", "Show progress and play / next buttons on the taskbar button", True),
            S("global_media_keys", "Media keys work even when Iron Will isn't the active window", False),
            S("toast", "Show on-screen messages (volume, speed…)", True),
        ]),
        ("Seek bar", [
            S("seek_tooltip", "Show the time while hovering over the seek bar", True),
            S("seek_preview", "Show a picture preview while hovering over the seek bar", False,
              tip="MPC-BE: Smart seek. Uses FFmpeg to grab the frame under the mouse."),
            S("seek_preview_size", "Preview width", 240, lo=120, hi=480, step=20, suffix=" px"),
        ]),
        ("Time display", [
            S("time_right", "The time on the right shows", "remaining",
              [("remaining", "Time remaining"), ("total", "Total length")]),
            S("show_ms", "Show milliseconds", False),
            S("show_zero_hours", "Show hours even under an hour (0:05:12 instead of 5:12)", True),
            S("chapter_marks", "Show chapter marks on the seek bar", True),
        ]),
        ("On-screen messages", [
            S("osd_size", "Size", 16, lo=8, hi=48, suffix=" pt"),
            S("osd_filename", "Show the file name when a file opens", False),
            S("osd_clock", "Show the clock in full screen", False),
        ]),
    ]),
    Page("keys", "Keys", "player", special="keys",
         note="Click a shortcut and press the new keys. Clear a box to remove a shortcut."),
    Page("mouse", "Mouse", "player", special="mouse", groups=[
        ("Extras", [
            S("easy_move", "Drag the video to move the window", True),
            S("longpress", "Click and hold: right third fast-forwards, left third rewinds", True),
            S("longpress_delay", "Hold for", 300, lo=100, hi=2000, step=50, suffix=" ms"),
            S("longpress_speed", "Fast-forward / rewind speed", 3.0, lo=1.25, hi=8, step=0.25, suffix="x"),
        ]),
    ], note="What each mouse button does over the video. 'Right button held' means: hold the right button, "
            "then click or scroll. Empty slots fall back to the Normal column."),
    Page("window", "Window", "player", groups=[
        ("Size and position", [
            S("remember_geometry", "Remember window size and position", True),
            S("keep_awake", "Keep the PC awake (no screensaver or sleep)", "visible",
              [("visible", "While Iron Will is on screen (not minimized)"), ("playing", "Only while a video is playing"),
               ("never", "Never: use Windows' normal timers")]),
            S("on_top", "Keep the player on top of other windows", "never",
              [("never", "Never"), ("always", "Always"), ("playing", "While playing")]),
            S("borderless", "Borderless window (no title bar or frame)", False,
              tip="Drag the video to move it, drag its edges to resize. Ctrl+B or the title-bar menu toggles it."),
            S("startup_size", "Window size when Iron Will starts", "remember",
              [("remember", "Same as last time"), ("specified", "This size")]),
            S("startup_w", "Width", 1280, lo=320, hi=7680, step=10, suffix=" px"),
            S("startup_h", "Height", 760, lo=200, hi=4320, step=10, suffix=" px"),
            S("reset_after_close", "Go back to the startup size after closing a file", False),
            S("snap_edges", "Snap to screen edges when moving the window", False),
            S("limit_proportions", "Keep the window's shape matching the video when resizing", False),
            S("pause_minimized", "Pause when minimized", False),
            S("hide_cursor_window", "Hide the mouse pointer with the controls in a window too (not just full screen)",
              True),
            S("tray_icon", "Show an icon in the notification area (minimizing hides to it)", False),
        ]),
        ("Transparency", [
            S("opacity", "Window transparency for new windows", 100, lo=10, hi=100, step=5, suffix=" %",
              tip="100% = solid. Change it per window from View > Transparency or Ctrl+Shift+Up / Down "
                  "(Ctrl+Shift+1 to 0 jump straight to 10% to 100%, like Glass2K)."),
            S("opacity_hover_solid", "Turn solid while the mouse is over the window", False),
        ]),
        ("Mini view", [
            S("mini_size", "Mini view size", "medium",
              [("small", "Small (400 × 225)"), ("medium", "Medium (560 × 315)"), ("large", "Large (720 × 405)")]),
        ]),
    ]),
    Page("playback", "Playback", groups=[
        ("Playback", [
            S("volume_max", "Maximum volume (boost)", 150, mpv="volume-max", lo=100, hi=300, step=10, suffix=" %"),
            S("loop_file", "Repeat", "no", [("no", "Off"), ("inf", "Repeat this file forever"), ("1", "Play twice"),
                                             ("2", "Play 3 times"), ("4", "Play 5 times"), ("9", "Play 10 times")],
              mpv="loop-file"),
            S("pitch", "Keep voices natural when speeding up", True, mpv="audio-pitch-correction", to_mpv=YES_NO),
            S("speed_step", "Increase / Decrease Rate step", 5, lo=1, hi=50, suffix=" %",
              tip="How much each speed up / slow down changes the speed (MPC-BE: Options > Playback > Speed step)"),
        ]),
        ("Next / previous file in a folder", [
            S("folder_order", "Play files in this order", "explorer",
              [("explorer", "Same as File Explorer (follows the folder's sort)"), ("name", "Name, A to Z"),
               ("name_desc", "Name, Z to A"), ("modified_new", "Date modified, newest first"),
               ("modified_old", "Date modified, oldest first"), ("created_new", "Date created, newest first"),
               ("created_old", "Date created, oldest first"), ("size_small", "Size, smallest first"),
               ("size_large", "Size, largest first"), ("shuffle", "Shuffle (random order)")],
              tip="'Same as File Explorer' reads the sort of the folder's Explorer window when it's open and "
                  "remembers it for when it isn't"),
            S("folder_order_default", "For folders Explorer hasn't shown yet", "name",
              [("name", "Name, A to Z"), ("name_desc", "Name, Z to A"), ("modified_new", "Date modified, newest first"),
               ("modified_old", "Date modified, oldest first"), ("created_new", "Date created, newest first"),
               ("created_old", "Date created, oldest first"), ("size_small", "Size, smallest first"),
               ("size_large", "Size, largest first")]),
        ]),
        ("Seeking", [
            S("hr_seek", "Precise seeking", "default",
              [("default", "Default (precise for jumps, fast while dragging)"), ("yes", "Always precise"),
               ("no", "Fast (keyframes only)")], mpv="hr-seek"),
        ]),
    ]),
    Page("cache", "Cache", "playback", groups=[
        ("Read-ahead cache", [
            S("cache", "Cache", "auto", [("auto", "Auto (network files only)"), ("yes", "Always"), ("no", "Off")],
              mpv="cache"),
            S("cache_fwd", "Forward buffer size", 150, mpv="demuxer-max-bytes", lo=16, hi=4096, step=16,
              suffix=" MiB", to_mpv=MIB),
            S("cache_back", "Backward buffer size", 50, mpv="demuxer-max-back-bytes", lo=0, hi=2048, step=16,
              suffix=" MiB", to_mpv=MIB),
            S("readahead", "Read ahead at least", 1, mpv="demuxer-readahead-secs", lo=0, hi=600, suffix=" s"),
        ]),
    ]),
    Page("screenshots", "Screenshots", "playback", groups=[
        ("Save current frame", [
            S("shot_dir", "Folder", str(Path.home() / "Pictures" / "Iron Will"), kind="folder"),
            S("shot_format", "Format", "png", [("png", "PNG (lossless)"), ("jpg", "JPEG"), ("webp", "WebP")],
              mpv="screenshot-format"),
            S("shot_jpeg_q", "JPEG quality", 92, mpv="screenshot-jpeg-quality", lo=10, hi=100),
            S("shot_subs", "Include subtitles in the picture", False),
            S("thumb_cols", "Thumbnail sheet: columns", 4, lo=1, hi=10),
            S("thumb_rows", "Thumbnail sheet: rows", 4, lo=1, hi=10),
            S("thumb_width", "Thumbnail sheet: width", 1024, lo=320, hi=4096, step=32, suffix=" px"),
            S("shot_template", "File name pattern", "%F %wH.%wM.%wS", mpv="screenshot-template", kind="text",
              tip="%F = file name, %wH/%wM/%wS = time in the video, %n = counter"),
        ]),
    ]),
    Page("video", "Video", groups=[
        ("Decoding", [
            S("hwdec", "Hardware decoding", "auto-safe",
              [("auto-safe", "Auto (recommended)"), ("auto", "Auto (any method)"), ("auto-copy", "Auto copy-back"),
               ("d3d11va-copy", "Direct3D 11 (copy-back)"), ("dxva2-copy", "DXVA2 (copy-back)"),
               ("nvdec-copy", "NVIDIA NVDEC (copy-back)"), ("no", "Off (software only)")], mpv="hwdec"),
        ]),
        ("Framing", [
            S("video_frame", "Default video frame", "inside",
              [("inside", "Touch window from inside (whole picture, bars if needed)"),
               ("outside", "Touch window from outside (fills the window, crops edges)"),
               ("stretch", "Stretch to window"), ("normal", "Normal size"), ("half", "Half size"),
               ("double", "Double size")],
              tip="MPC-BE: Playback > Default video frame. The View > Video Frame menu changes it too."),
            S("keepaspect", "Keep the original aspect ratio", True, mpv="keepaspect", to_mpv=YES_NO),
            S("unscaled", "Scaling", "no", [("no", "Fit to window"), ("downscale-big", "Only shrink, never enlarge"),
                                            ("yes", "Original pixel size")], mpv="video-unscaled"),
            S("panscan", "Crop to fill wide screens (pan & scan)", 0.0, mpv="panscan", lo=0, hi=1, step=0.05),
            S("aspect_override", "Aspect ratio", "no",
              [("no", "From the file"), ("4:3", "4:3"), ("16:9", "16:9"), ("1.85:1", "1.85:1"), ("2.35:1", "2.35:1"),
               ("2.39:1", "2.39:1"), ("21:9", "21:9")], mpv="video-aspect-override",
              tip="MPC-BE: Playback > aspect ratio override. Use it for files with wrong aspect information."),
            S("monitor_aspect", "Monitor pixel aspect (1 = square pixels)", 1.0, mpv="monitorpixelaspect", lo=0.5, hi=2,
              step=0.01, tip="MPC-BE: compensate for a monitor whose pixels aren't square"),
            S("stereo3d", "3D video", "off",
              [("off", "Show as is"), ("sbsl", "Side-by-side: left eye only"), ("abl", "Top-bottom: top eye only"),
               ("sbs_anaglyph", "Side-by-side to red/cyan anaglyph"), ("ab_anaglyph", "Top-bottom to red/cyan anaglyph")]),
            S("audio_display", "When playing audio only, show", "embedded-first",
              [("embedded-first", "The album art in the file, else cover.jpg"),
               ("external-first", "cover.jpg in the folder, else the album art"), ("no", "Nothing")],
              mpv="audio-display"),
        ]),
    ]),
    Page("quality", "Quality & Scaling", "video", groups=[
        ("Scalers", [
            S("scale", "Upscaling", "spline36",
              [("bilinear", "Bilinear (fastest)"), ("spline36", "Spline36 (balanced)"), ("lanczos", "Lanczos (sharp)"),
               ("ewa_lanczos", "EWA Lanczos (high quality)"), ("ewa_lanczossharp", "EWA Lanczos Sharp (best)")],
              mpv="scale"),
            S("dscale", "Downscaling", "hermite",
              [("bilinear", "Bilinear"), ("hermite", "Hermite"), ("mitchell", "Mitchell"),
               ("catmull_rom", "Catmull-Rom (sharp)")], mpv="dscale"),
            S("cscale", "Color upscaling", "spline36",
              [("bilinear", "Bilinear"), ("spline36", "Spline36"), ("lanczos", "Lanczos"),
               ("ewa_lanczos", "EWA Lanczos")], mpv="cscale"),
            S("correct_down", "Correct downscaling", True, mpv="correct-downscaling", to_mpv=YES_NO),
            S("linear_down", "Linear-light downscaling", True, mpv="linear-downscaling", to_mpv=YES_NO),
            S("sigmoid_up", "Sigmoid upscaling (less ringing)", True, mpv="sigmoid-upscaling", to_mpv=YES_NO),
        ]),
        ("Clean-up", [
            S("deband", "Remove color banding (debanding)", False, mpv="deband", to_mpv=YES_NO),
            S("deband_iter", "Debanding strength", 1, mpv="deband-iterations", lo=1, hi=8),
            S("dither", "Dithering", "auto", [("auto", "Auto"), ("8", "8-bit"), ("10", "10-bit"), ("no", "Off")],
              mpv="dither-depth"),
        ]),
    ]),
    Page("color", "Color Correction", "video", groups=[
        ("Picture", [
            S("brightness", "Brightness", 0, mpv="brightness", lo=-100, hi=100),
            S("contrast", "Contrast", 0, mpv="contrast", lo=-100, hi=100),
            S("saturation", "Saturation", 0, mpv="saturation", lo=-100, hi=100),
            S("gamma", "Gamma", 0, mpv="gamma", lo=-100, hi=100),
            S("hue", "Hue", 0, mpv="hue", lo=-100, hi=100),
        ]),
        ("HDR on SDR screens", [
            S("tone_mapping", "Tone mapping", "auto",
              [("auto", "Auto"), ("bt.2390", "BT.2390"), ("spline", "Spline"), ("hable", "Hable (filmic)"),
               ("mobius", "Mobius"), ("reinhard", "Reinhard"), ("clip", "Clip")], mpv="tone-mapping"),
            S("icc_auto", "Use the monitor's color profile (color management)", False, mpv="icc-profile-auto",
              to_mpv=YES_NO),
            S("output_levels", "Output levels", "auto",
              [("auto", "Auto"), ("full", "Full range (0-255, PC)"), ("limited", "Limited range (16-235, TV)")],
              mpv="video-output-levels"),
            S("hdr_peak", "Measure HDR brightness per scene", "auto", [("auto", "Auto"), ("yes", "On"), ("no", "Off")],
              mpv="hdr-compute-peak"),
        ]),
    ]),
    Page("framesync", "Frame Sync", "video", groups=[
        ("Smoothness", [
            S("video_sync", "Sync video to", "audio",
              [("audio", "Audio (default)"), ("display-resample", "Display refresh (smoother)"),
               ("display-tempo", "Display refresh (adjust audio speed)")], mpv="video-sync"),
            S("interpolation", "Motion interpolation (needs 'Display refresh')", False, mpv="interpolation",
              to_mpv=YES_NO),
            S("tscale", "Interpolation filter", "oversample",
              [("oversample", "Oversample (sharp)"), ("linear", "Linear"), ("catmull_rom", "Catmull-Rom"),
               ("mitchell", "Mitchell (smooth)")], mpv="tscale"),
            S("framedrop", "Drop frames when the PC falls behind", "vo",
              [("vo", "At output (default)"), ("decoder+vo", "Decoder and output"), ("no", "Never")],
              mpv="framedrop"),
            S("deinterlace", "Deinterlace", "no", [("no", "Off"), ("yes", "On")], mpv="deinterlace"),
        ]),
    ]),
    Page("fullscreen", "Fullscreen", "video", groups=[
        ("Full screen", [
            S("start_fullscreen", "Start files in full screen", False),
            S("exit_fs_at_end", "Leave full screen when the folder finishes", True),
            S("fs_monitor", "Go full screen on", "current",
              [("current", "The monitor the window is on"), ("primary", "The primary monitor"),
               ("1", "Monitor 1"), ("2", "Monitor 2"), ("3", "Monitor 3")]),
            S("exit_fs_focus", "Leave full screen when Iron Will loses focus", False),
            S("fs_controls", "Show the controls in full screen when the mouse moves", True),
            S("fs_refresh", "Match the monitor's refresh rate to the video in full screen", False,
              tip="MPC-BE: Auto-change full-screen monitor mode. 24 fps films switch the screen to 24/48/120 Hz "
                  "if it supports it, and it switches back when you leave full screen."),
        ]),
    ]),
    Page("audio", "Audio", groups=[
        ("Output", [
            S("audio_device", "Speakers / headphones", "auto", kind="device", mpv="audio-device"),
            S("audio_channels", "Channels", "auto-safe",
              [("auto-safe", "Auto (recommended)"), ("stereo", "Stereo"), ("5.1", "5.1 surround"),
               ("7.1", "7.1 surround"), ("auto", "Auto (any layout)")], mpv="audio-channels"),
            S("audio_exclusive", "Exclusive mode (bit-perfect, other apps muted)", False, mpv="audio-exclusive",
              to_mpv=YES_NO),
            S("spdif", "Pass-through to receiver (S/PDIF / HDMI)", "",
              [("", "Off"), ("ac3,dts", "Dolby Digital + DTS"), ("ac3,dts,eac3", "+ Dolby Digital Plus"),
               ("ac3,dts,eac3,truehd,dts-hd", "+ TrueHD and DTS-HD")], mpv="audio-spdif"),
        ]),
        ("Tracks", [
            S("prefer_external_audio", "Prefer audio files over the audio inside the video", False),
            S("audio_lang", "Preferred audio language", "en", LANG_CHOICES, mpv="alang",
              to_mpv=lambda v: LANGUAGES.get(v, ("", ""))[0],
              tip="Every file starts in this language when it has a track for it"),
            S("audio_file_auto", "Load matching external audio files", "no",
              [("no", "No"), ("exact", "Exact name match"), ("fuzzy", "Similar names")], mpv="audio-file-auto"),
            S("audio_delay", "Audio delay", 0, mpv="audio-delay", lo=-5000, hi=5000, step=10, suffix=" ms",
              to_mpv=lambda v: v / 1000.0),
            S("audio_delay_step", "Audio delay step (+ / - keys)", 10, lo=1, hi=1000, suffix=" ms"),
            S("audio_paths", "Also look for audio files in these subfolders", "audio", kind="text",
              mpv="audio-file-paths", to_mpv=lambda v: [x.strip() for x in v.replace(",", ";").split(";") if x.strip()],
              tip="Separate folders with ;"),
        ]),
    ]),
    Page("soundproc", "Sound Processing", "audio", groups=[
        ("Processing", [
            S("normalize", "Even out loud and quiet scenes (normalize)", False),
            S("night_mode", "Night mode (compress loud explosions)", False),
            S("downmix_norm", "Normalize volume when downmixing surround to stereo", False,
              mpv="audio-normalize-downmix", to_mpv=YES_NO),
            S("balance", "Balance (left - / right +)", 0, lo=-100, hi=100, step=5),
            S("gain", "Gain (extra loudness)", 0.0, lo=0, hi=20, step=0.5, suffix=" dB"),
            S("norm_strength", "Normalize: target level", 75, lo=10, hi=100, step=5, suffix=" %",
              tip="How loud the normalized sound aims to be (MPC-BE: Normalize level)"),
        ]),
    ]),
    Page("subtitles", "Subtitles", groups=[
        ("Choosing subtitles", [
            S("sub_lang", "Preferred subtitle language", "en", LANG_CHOICES, mpv="slang",
              to_mpv=lambda v: LANGUAGES.get(v, ("", ""))[0],
              tip="Used when you turn subtitles on, or when they turn on automatically"),
            S("sub_auto", "Load matching subtitle files", "fuzzy",
              [("no", "No"), ("exact", "Exact name match"), ("fuzzy", "Similar names"), ("all", "All in folder")],
              mpv="sub-auto"),
            # Off by default: files open with no subtitle track; picking one from the subtitles button turns it on.
            S("subs_auto", "Turn subtitles on automatically when a file opens", False, mpv="sid",
              to_mpv=lambda v: "auto" if v else "no"),
            S("sub_paths", "Also look for subtitles in these subfolders", "subs;subtitles", kind="text",
              mpv="sub-file-paths", to_mpv=lambda v: [x.strip() for x in v.replace(",", ";").split(";") if x.strip()],
              tip="Separate folders with ;"),
            S("prefer_external_subs", "Prefer subtitle files over subtitles inside the video", True),
            S("ignore_embedded_subs", "Ignore subtitles inside the video", False),
            S("forced_subs", "Show only forced subtitles (signs and foreign speech)", False,
              mpv="sub-forced-events-only", to_mpv=YES_NO),
            S("sub_reload", "Reload a subtitle file when it changes on disk", False),
            S("sub_codepage", "Text encoding for subtitle files", "auto",
              [("auto", "Detect automatically"), ("utf-8", "Unicode (UTF-8)"), ("cp1252", "Western (Windows-1252)"),
               ("cp1251", "Cyrillic (Windows-1251)"), ("cp1250", "Central European (Windows-1250)"),
               ("cp1253", "Greek (Windows-1253)"), ("cp1254", "Turkish (Windows-1254)"), ("cp1256", "Arabic (Windows-1256)"),
               ("cp932", "Japanese (Shift-JIS)"), ("cp936", "Chinese Simplified (GBK)"),
               ("cp950", "Chinese Traditional (Big5)"), ("cp949", "Korean")], mpv="sub-codepage"),
            S("sub_delay_step", "Subtitle delay step (F1 / F2)", 500, lo=10, hi=5000, step=10, suffix=" ms"),
        ]),
    ]),
    Page("subrender", "Rendering", "subtitles", groups=[
        ("Placement", [
            S("sub_pos", "Vertical position", 100, mpv="sub-pos", lo=0, hi=150, suffix=" %"),
            S("sub_scale", "Size multiplier", 1.0, mpv="sub-scale", lo=0.3, hi=4, step=0.1),
            S("sub_margin", "Bottom margin", 22, mpv="sub-margin-y", lo=0, hi=300, suffix=" px"),
        ]),
        ("Styled (ASS) subtitles", [
            S("ass_override", "Apply my style to styled subtitles", "scale",
              [("no", "Never"), ("scale", "Only scale them"), ("yes", "Partly"), ("force", "Always (force)"),
               ("strip", "Strip all styling")], mpv="sub-ass-override"),
            S("blend_subs", "Draw subtitles", "no",
              [("no", "Sharp, at screen resolution"), ("video", "Into the video picture"), ("yes", "Blend (smoother)")],
              mpv="blend-subtitles"),
            S("sub_fix_timing", "Fix tiny gaps between lines", False, mpv="sub-fix-timing", to_mpv=YES_NO),
        ]),
    ]),
    Page("substyle", "Default Style", "subtitles", groups=[
        ("Text", [
            S("sub_font", "Font", "Segoe UI Semibold", kind="font", mpv="sub-font"),
            S("sub_font_size", "Size", 46, mpv="sub-font-size", lo=10, hi=150),
            S("sub_bold", "Bold", False, mpv="sub-bold", to_mpv=YES_NO),
            S("sub_color", "Text color", "#FFFFFF", kind="color", mpv="sub-color"),
        ]),
        ("Outline and shadow", [
            S("sub_outline_color", "Outline color", "#000000", kind="color",
              mpv=("sub-outline-color", "sub-border-color")),
            S("sub_outline_size", "Outline thickness", 2.5, mpv=("sub-outline-size", "sub-border-size"), lo=0, hi=10,
              step=0.5),
            S("sub_shadow", "Shadow distance", 1.0, mpv="sub-shadow-offset", lo=0, hi=10, step=0.5),
            S("sub_back_color", "Background box color", "#00000000", kind="color", mpv="sub-back-color",
              tip="Fully transparent by default; pick a color to get a box behind the text"),
        ]),
    ]),
    Page("decoders", "Decoders", groups=[
        ("Video decoder", [
            S("vd_threads", "Decoder threads (0 = automatic)", 0, mpv="vd-lavc-threads", lo=0, hi=64),
            S("hwdec_codecs", "Use hardware decoding for", "all",
              [("all", "All formats"), ("h264,hevc,av1,vp9", "H.264, HEVC, AV1, VP9"), ("h264,hevc", "H.264 and HEVC")],
              mpv="hwdec-codecs"),
            S("skiploop", "Skip loop filter (faster, slightly softer)", "default",
              [("default", "Never"), ("nonref", "Non-reference frames"), ("all", "Always")],
              mpv="vd-lavc-skiploopfilter"),
            S("vd_fast", "Fast decoding shortcuts (may reduce quality)", False, mpv="vd-lavc-fast", to_mpv=YES_NO),
        ]),
    ], note="Iron Will uses FFmpeg's built-in decoders through mpv: no codec packs needed."),
    Page("shaders", "Shaders", special="shaders", groups=[("Shaders", [S("shaders_on", "Use the shaders below", True)])],
         note="GLSL shaders run on every frame (e.g. FSRCNNX, Anime4K, adaptive sharpen). Order matters: top runs first."),
    Page("duplicates", "Duplicate Finder", special="dupes",
         note="Finds copies of the same video even when they were re-encoded, resized, mirrored, cut short or given an "
              "added intro, then lets you compare any two side by side, synced, before sending extras to the "
              "Recycle Bin."),
    Page("formats", "File Types", special="formats",
         note="Lets Windows open these files with Iron Will. Windows only allows you to pick the default player, so "
              "Default Apps opens at Iron Will's page for the final click."),
    Page("misc", "Miscellaneous", special="about", groups=[
        ("Advanced", [
            S("custom_opts", "Extra mpv options (one per line: name=value)", "", kind="multiline"),
            S("network_timeout", "Network timeout", 60, mpv="network-timeout", lo=5, hi=600, suffix=" s"),
            S("user_agent", "Network user agent", "", mpv="user-agent", kind="text",
              tip="Leave empty for mpv's default"),
            S("log_file", "Write a debug log file", False),
            S("priority", "Process priority", "normal",
              [("normal", "Normal"), ("above", "Above normal"), ("high", "High"), ("below", "Below normal")]),
        ]),
    ]),
]

ALL = {s.key: s for p in PAGES for _g, items in p.groups for s in items}

# Mouse bindings: gesture -> [normal, ctrl, shift, right-button-held] command ids (MPC-BE's model).
MOUSE_COMMANDS = [
    ("none", "—"), ("play_pause", "Play / pause"), ("stop", "Stop"), ("fullscreen", "Full screen"),
    ("mini", "Mini view"), ("menu", "Show menu"), ("volume_up", "Volume up"), ("volume_down", "Volume down"),
    ("mute", "Mute"), ("seek_back", "Jump back (arrow step)"), ("seek_fwd", "Jump forward (arrow step)"),
    ("skip_back", "Back button jump"), ("skip_fwd", "Forward button jump"), ("frame_prev", "Previous frame"),
    ("frame_next", "Next frame"), ("prev_file", "Previous file"), ("next_file", "Next file"),
    ("speed_down", "Slow down"), ("speed_up", "Speed up"), ("speed_reset", "Normal speed"),
    ("repeat_toggle", "Repeat forever on/off"), ("ab_a", "A-B loop: mark A"), ("ab_b", "A-B loop: mark B"),
    ("ab_clear", "A-B loop: clear"), ("zoom_in", "Zoom in"), ("zoom_out", "Zoom out"),
    ("view_reset", "Reset zoom and position"), ("pan_left", "Move picture left"), ("pan_right", "Move picture right"),
    ("pan_up", "Move picture up"), ("pan_down", "Move picture down"), ("sub_toggle", "Subtitles on/off"),
    ("sub_next", "Next subtitle track"), ("audio_next", "Next audio track"), ("screenshot", "Save current frame"),
    ("options", "Options"),
]
GESTURES = [
    ("left_click", "Left click"), ("left_dbl", "Left double-click"), ("middle", "Middle click"),
    ("x1", "Back side button"), ("x2", "Forward side button"), ("wheel_up", "Wheel up"),
    ("wheel_down", "Wheel down"), ("wheel_left", "Wheel tilt left"), ("wheel_right", "Wheel tilt right"),
]
DEFAULT_MOUSE = {
    "left_click": ["play_pause", "none", "none", "none"], "left_dbl": ["fullscreen", "none", "none", "none"],
    "middle": ["mute", "none", "none", "none"], "x1": ["prev_file", "none", "none", "none"],
    "x2": ["next_file", "none", "none", "none"], "wheel_up": ["volume_up", "none", "none", "zoom_in"],
    "wheel_down": ["volume_down", "none", "none", "zoom_out"], "wheel_left": ["seek_back", "none", "none", "none"],
    "wheel_right": ["seek_fwd", "none", "none", "none"],
}


def defaults():
    d = {k: s.default for k, s in ALL.items()}
    d.update(keys={}, shaders=[], mouse={g: list(v) for g, v in DEFAULT_MOUSE.items()})
    return d


class Config:
    def __init__(self):
        self.values = defaults()
        try:
            saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            mouse = {**self.values["mouse"], **saved.pop("mouse", {})}  # new gestures keep their defaults
            # Older settings files: carry their choices over to the options that replaced them.
            if "always_on_top" in saved and "on_top" not in saved:
                saved["on_top"] = "always" if saved["always_on_top"] else "never"
            if saved.get("single_instance") and "allow_multiple" not in saved:
                saved["allow_multiple"] = False
            if saved.get("auto_next") is False and "after_playback" not in saved:
                saved["after_playback"] = "nothing"
            self.values.update(saved)
            self.values["mouse"] = mouse
        except (OSError, ValueError):
            pass

    def __getitem__(self, key):
        return self.values.get(key, ALL[key].default if key in ALL else None)

    def save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self.values, indent=1), encoding="utf-8")


def _audio_filter_chain(v):
    chain = []
    if v.get("normalize"):
        peak = max(0.1, min(1.0, v.get("norm_strength", 75) / 100 + 0.15))
        chain.append(f"lavfi=[dynaudnorm=f=250:g=31:p={peak:.2f}]")
    if v.get("gain"):
        chain.append(f"lavfi=[volume={float(v['gain']):g}dB]")
    if v.get("night_mode"):
        chain.append("lavfi=[acompressor=threshold=0.08:ratio=6:attack=20:release=250:makeup=2]")
    if v.get("balance"):
        chain.append(f"lavfi=[stereotools=balance_out={max(-1.0, min(1.0, v['balance'] / 100.0)):.2f}]")
    return ",".join(chain)


def apply_to_mpv(player, values, only=None):
    """Push settings into a running mpv. Returns a list of (label, error) for anything mpv refused."""
    failed = []
    available = set(player._get_property("options") or [])  # player[...] reads options/, not properties
    for key, s in ALL.items():
        if not s.mpv or (only is not None and key not in only):
            continue
        names = s.mpv if isinstance(s.mpv, tuple) else (s.mpv,)
        name = next((n for n in names if n in available), names[0])
        value = values.get(key, s.default)
        value = s.to_mpv(value) if s.to_mpv else value
        if isinstance(value, float) and value.is_integer() and s.step >= 1:
            value = int(value)
        try:
            player[name] = value
        except Exception as exc:  # mpv rejects unknown values or options it can't change while playing
            failed.append((s.label, str(exc).split("\n")[0][:120]))
    if only is None or {"normalize", "night_mode", "balance", "gain", "norm_strength"} & set(only):
        try:
            player["af"] = _audio_filter_chain(values)
        except Exception as exc:
            failed.append(("Sound processing", str(exc)[:120]))
    if only is None or "stereo3d" in only:
        modes = {"sbsl": "sbsl:ml", "abl": "abl:ml", "sbs_anaglyph": "sbsl:arcd", "ab_anaglyph": "abl:arcd"}
        try:
            mode = modes.get(values.get("stereo3d", "off"))
            player.command("vf", "remove", "@stereo")
            if mode:
                player.command("vf", "add", f"@stereo:lavfi=[stereo3d={mode}]")
        except Exception as exc:
            failed.append(("3D video", str(exc)[:120]))
    if only is None or {"shaders", "shaders_on"} & set(only):
        try:
            player.command("change-list", "glsl-shaders", "clr", "")
            for path in values.get("shaders", []) if values.get("shaders_on", True) else []:
                player.command("change-list", "glsl-shaders", "append", path)
        except Exception as exc:
            failed.append(("Shaders", str(exc)[:120]))
    if only is None or "log_file" in only:
        try:
            player["log-file"] = str(DATA_DIR / "mpv-log.txt") if values.get("log_file") else ""
        except Exception:
            pass
    if only is None or "custom_opts" in only:
        for line in (values.get("custom_opts") or "").splitlines():
            line = line.strip().lstrip("-")
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, val = (part.strip() for part in line.split("=", 1))
            try:
                player[name] = val
            except Exception as exc:
                failed.append((f"Extra option {name}", str(exc)[:120]))
    return failed
