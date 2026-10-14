"""Read an MPC-BE settings file (mpc-be64.ini) and translate what has an Iron Will / mpv equivalent.
Read-only: the MPC-BE file is never modified."""
import configparser
import os
from pathlib import Path

CANDIDATES = [
    Path(os.environ.get("APPDATA", "")) / "MPC-BE" / "mpc-be64.ini",
    Path(os.environ.get("APPDATA", "")) / "MPC-BE" / "mpc-be.ini",
    Path(r"C:\Program Files\MPC-BE x64\mpc-be64.ini"),
    Path(r"C:\Program Files\MPC-BE\mpc-be64.ini"),
]

# MPC-BE command ids (src/apps/mplayerc/resource.h) -> Iron Will mouse commands.
MPC_COMMANDS = {
    0: "none", 889: "play_pause", 890: "stop", 830: "fullscreen", 831: "fullscreen", 827: "mini",
    949: "menu", 950: "menu", 907: "volume_up", 908: "volume_down", 909: "mute",
    899: "seek_back", 901: "seek_back", 903: "seek_back", 900: "seek_fwd", 902: "seek_fwd", 904: "seek_fwd",
    892: "frame_prev", 891: "frame_next", 921: "prev_file", 922: "next_file",
    894: "speed_down", 895: "speed_up", 896: "speed_reset", 967: "repeat_toggle",
    1202: "ab_a", 1203: "ab_b", 862: "zoom_in", 863: "zoom_out", 861: "view_reset", 876: "view_reset",
    868: "pan_left", 869: "pan_right", 870: "pan_up", 871: "pan_down",
    956: "sub_toggle", 954: "sub_next", 952: "audio_next", 806: "screenshot", 815: "options",
}
# MPC-BE ini key -> Iron Will gesture. Values are "normal;ctrl;shift;right-button-held".
MPC_GESTURES = {"ButtonLeft": "left_click", "ButtonLeftDblClick": "left_dbl", "ButtonMiddle": "middle",
                "ButtonX1": "x1", "ButtonX2": "x2", "WheelUp": "wheel_up", "WheelDown": "wheel_down",
                "WheelLeft": "wheel_left", "WheelRight": "wheel_right"}


def find_ini():
    return next((p for p in CANDIDATES if p.exists()), None)


def _bgr(value, alpha=None):
    """MPC stores colors as 0xBBGGRR; mpv wants #RRGGBB (or #AARRGGBB)."""
    v = int(value, 16) if isinstance(value, str) else int(value)
    r, g, b = v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF
    return f"#{alpha:02X}{r:02X}{g:02X}{b:02X}" if alpha is not None else f"#{r:02X}{g:02X}{b:02X}"


def _langs(order):
    """'eng' -> 'eng,en' so both 3- and 2-letter tags match."""
    two = {"eng": "en", "jpn": "ja", "spa": "es", "fre": "fr", "fra": "fr", "ger": "de", "deu": "de",
           "ita": "it", "por": "pt", "rus": "ru", "kor": "ko", "chi": "zh", "zho": "zh"}
    out = []
    for code in (c.strip() for c in order.replace(";", ",").split(",") if c.strip()):
        out.append(code)
        if code.lower() in two:
            out.append(two[code.lower()])
    return ",".join(dict.fromkeys(out))


def _choice(order):
    """'eng;jpn' -> 'en': the first language Iron Will has a choice for."""
    from .settings import LANGUAGES
    for code in (c.strip().lower() for c in order.replace(";", ",").split(",") if c.strip()):
        for key, (codes, _pattern) in LANGUAGES.items():
            if key and code in codes.split(","):
                return key
    return None


def _mouse_slots(value, unknown):
    slots = []
    for part in (str(value).split(";") + ["0"] * 4)[:4]:
        cid = int(part or 0)
        if cid not in MPC_COMMANDS:
            unknown.add(cid)
        slots.append(MPC_COMMANDS.get(cid, "none"))
    return slots


def read(path):
    """Returns (changes, notes): changes maps Iron Will setting keys to values; notes explain each one."""
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    cp.read(path, encoding="utf-8-sig")
    s = cp["Settings"] if cp.has_section("Settings") else {}
    a = cp["Audio"] if cp.has_section("Audio") else {}
    m = cp["Mouse"] if cp.has_section("Mouse") else {}
    v = cp["Video"] if cp.has_section("Video") else {}
    changes, notes = {}, []

    def put(key, value, note):
        changes[key] = value
        notes.append(note)

    if s.get("AudiosLanguageOrder"):
        if _choice(s["AudiosLanguageOrder"]) is not None:
            put("audio_lang", _choice(s["AudiosLanguageOrder"]), f"Preferred audio language: {s['AudiosLanguageOrder']}")
    if s.get("SubtitlesLanguageOrder"):
        if _choice(s["SubtitlesLanguageOrder"]) is not None:
            put("sub_lang", _choice(s["SubtitlesLanguageOrder"]),
                f"Preferred subtitle language: {s['SubtitlesLanguageOrder']}")
    if "EnableSubtitles" in s:
        on = s["EnableSubtitles"] == "1"
        put("subs_auto", on, f"Subtitles on automatically: {'yes' if on else 'no'}")
    if "AutoloadAudio" in s:
        put("audio_file_auto", "fuzzy" if s["AutoloadAudio"] == "1" else "no", "Auto-load external audio files")
    if s.get("SpeedStep", "").isdigit() and int(s["SpeedStep"]) > 0:
        put("speed_step", int(s["SpeedStep"]), f"Speed step: {s['SpeedStep']}%")
    if "VolumeStep" in s:
        put("volume_step", int(s["VolumeStep"]), f"Volume step: {s['VolumeStep']}%")
    if "JumpDistM" in s:
        secs = max(1, round(int(s["JumpDistM"]) / 1000))
        put("arrow_step", secs, f"Arrow-key jump: {secs} s (MPC-BE medium jump)")
    if "LaunchFullScreen" in s:
        put("start_fullscreen", s["LaunchFullScreen"] == "1", "Start in full screen")
    if "ExitFullscreenAtTheEnd" in s:
        put("exit_fs_at_end", s["ExitFullscreenAtTheEnd"] == "1", "Leave full screen at the end")
    if "OnTop" in s:
        mode = {"0": "never", "1": "always", "2": "playing", "3": "playing"}.get(s["OnTop"], "never")
        put("on_top", mode, f"On top: {mode}")
    if "Loop" in s:
        put("loop_file", "inf" if s["Loop"] == "1" else "no", "Repeat")
    if s.get("SnapShotExt"):
        fmt = {".jpg": "jpg", ".jpeg": "jpg", ".png": "png", ".webp": "webp"}.get(s["SnapShotExt"].lower())
        if fmt:
            put("shot_format", fmt, f"Screenshot format: {fmt.upper()}")
    if "SnapShotSubtitles" in s:
        put("shot_subs", s["SnapShotSubtitles"] == "1", "Subtitles in screenshots")
    if "TitleBarText" in s:
        put("title_mode", "media" if s["TitleBarText"] == "2" else "file", "Title text")
    if "RememberSelectedTracks" in s:
        on = s["RememberSelectedTracks"] == "1"
        put("remember_tracks", on, f"Remember picked audio/subtitle tracks: {'yes' if on else 'no'}")
    if s.get("RecentFilesNumber", "").isdigit():
        n = int(s["RecentFilesNumber"]) if s.get("KeepHistory", "1") == "1" else 0
        put("recent_count", n, f"Recent files: {n}")
    if "SpeedNotReset" in s:
        put("keep_speed", s["SpeedNotReset"] == "1", "Keep speed for the next file: "
            + ("yes" if s["SpeedNotReset"] == "1" else "no"))
    if s.get("JumpDistS", "").isdigit():
        secs = max(1, round(int(s["JumpDistS"]) / 1000))
        put("small_step", secs, f"Ctrl+arrow jump: {secs} s (MPC-BE short jump)")
    frame = {"0": "half", "1": "normal", "2": "double", "3": "stretch", "4": "inside", "5": "outside"}.get(
        s.get("DefaultVideoFrame", ""))
    if frame:
        put("video_frame", frame, f"Default video frame: {frame}")
    if s.get("KeepAspectRatio") == "0":
        put("keepaspect", True, "Keep aspect ratio: left ON (MPC-BE had it off, which stretches 4:3 video to fill "
                                "a wide window)")
    if "RemainingTime" in s:
        put("time_right", "remaining" if s["RemainingTime"] == "1" else "total",
            "Right-hand time: " + ("remaining" if s["RemainingTime"] == "1" else "total length"))
    for ini_key, ours, label in (("ShowMilliseconds", "show_ms", "Show milliseconds"),
                                 ("SnapToDesktopEdges", "snap_edges", "Snap to screen edges"),
                                 ("LimitWindowProportions", "limit_proportions", "Keep window proportions"),
                                 ("PauseMinimizedVideo", "pause_minimized", "Pause when minimized"),
                                 ("TrayIcon", "tray_icon", "Notification-area icon"),
                                 ("ExitFullscreenAtFocusLost", "exit_fs_focus", "Leave full screen on focus loss")):
        if ini_key in s:
            put(ours, s[ini_key] == "1", f"{label}: {'on' if s[ini_key] == '1' else 'off'}")
    if s.get("SubDelayInterval", "").isdigit():
        put("sub_delay_step", int(s["SubDelayInterval"]), f"Subtitle delay step: {s['SubDelayInterval']} ms")
    if s.get("Priority", "").isdigit():
        pr = {32: "normal", 0x8000: "above", 128: "high", 0x4000: "below"}.get(int(s["Priority"]))
        if pr:
            put("priority", pr, f"Process priority: {pr}")
    if s.get("FullScreenMonitor"):
        put("fs_monitor", "current" if s["FullScreenMonitor"].lower() == "current" else "primary",
            f"Full-screen monitor: {s['FullScreenMonitor']}")

    def folders(value):  # ".;.\subtitles;.\*subs" -> "subtitles;*subs"
        return ";".join(p.lstrip(".\\/") for p in value.split(";") if p.strip(" .\\/"))
    if s.get("SubtitlePaths"):
        put("sub_paths", folders(s["SubtitlePaths"]), f"Subtitle folders: {folders(s['SubtitlePaths'])}")
    if s.get("AudioPaths"):
        put("audio_paths", folders(s["AudioPaths"]), f"Audio folders: {folders(s['AudioPaths'])}")
    if a.get("Balance", "").lstrip("-").isdigit() and int(a["Balance"]):
        put("balance", int(a["Balance"]), f"Balance: {a['Balance']}")
    def flag(ini, ours, label, section=s, invert=False):
        if ini in section:
            on = (section[ini] == "1") != invert
            put(ours, on, f"{label}: {'on' if on else 'off'}")

    # After playback (MPC-BE keeps these as separate switches; the last one that's set wins)
    after = None
    if s.get("SearchInDirAfterPlayBack") == "1":
        after = "next_loop" if s.get("SearchInDirAfterPlayBackLooped") == "1" else "next"
    for ini, ours in (("Rewind", "rewind"), ("CloseFileAfterPlayBack", "close"),
                      ("CloseFileAfterPlayBackAndMinimize", "close_minimize"), ("ExitAfterPlayBack", "exit")):
        if s.get(ini) == "1":
            after = ours
    if after:
        put("after_playback", after, f"When a file ends: {after}")
    if s.get("Loop") == "1" and s.get("LoopNum", "").isdigit():
        n = int(s["LoopNum"])
        repeat = {2: "1", 3: "2", 5: "4", 10: "9"}.get(n, "inf")
        put("loop_file", repeat, f"Repeat: {'forever' if repeat == 'inf' else f'{n} times'}")
    if s.get("MultipleInstances", "").isdigit():
        put("allow_multiple", s["MultipleInstances"] != "1", "Multiple windows: "
            + ("no (same player)" if s["MultipleInstances"] == "1" else "yes"))
    if "FastSeek" in s:
        put("hr_seek", "no" if s["FastSeek"] == "1" else "default", "Seeking: "
            + ("fast (keyframes)" if s["FastSeek"] == "1" else "precise"))
    if s.get("RememberFilePos") == "0":
        put("resume", "never", "Remember position: off")
    flag("RememberWindowPos", "remember_geometry", "Remember window position")
    flag("ForcedSubtitles", "forced_subs", "Forced subtitles only")
    flag("DisableInternalSubtitles", "ignore_embedded_subs", "Ignore embedded subtitles")
    flag("PrioritizeExternalSubtitles", "prefer_external_subs", "Prefer subtitle files")
    flag("PrioritizeExternalAudio", "prefer_external_audio", "Prefer audio files")
    flag("AutoReloadExtSubtitles", "sub_reload", "Reload changed subtitle files")
    flag("FavRememberPos", "fav_position", "Favorites remember the time")
    flag("PasteClipboardURL", "paste_url", "Open URL uses the clipboard")
    flag("UseTimeTooltip", "seek_tooltip", "Seek bar time tooltip")
    flag("UseSmartSeek", "seek_preview", "Seek bar picture preview")
    flag("ShowZeroHours", "show_zero_hours", "Show zero hours")
    flag("ResetWindowAfterClosingFile", "reset_after_close", "Reset window after closing a file")
    flag("HideWindowedMousePointer", "hide_cursor_window", "Hide the pointer in a window")
    flag("FullScreenCtrls", "fs_controls", "Controls in full screen")
    flag("UseWin7TaskBar", "taskbar", "Taskbar progress and buttons")
    flag("UseGlobalMedia", "global_media_keys", "Global media keys")
    cp_code = s.get("SubtitleDefaultCodePage", "")
    if s.get("SubtitleAutoDetectCodePage") == "1" or cp_code in ("", "0"):
        put("sub_codepage", "auto", "Subtitle encoding: automatic")
    elif cp_code in ("1250", "1251", "1252", "1253", "1254", "1256", "932", "936", "950", "949", "65001"):
        put("sub_codepage", "utf-8" if cp_code == "65001" else f"cp{cp_code}", f"Subtitle encoding: code page {cp_code}")
    ax, ay = s.get("AspectRatioX", "0"), s.get("AspectRatioY", "0")
    if ax.isdigit() and ay.isdigit() and int(ax) and int(ay):
        ratio = f"{int(ax)}:{int(ay)}"
        known = {"4:3": "4:3", "16:9": "16:9", "185:100": "1.85:1", "235:100": "2.35:1", "239:100": "2.39:1",
                 "21:9": "21:9"}
        if ratio in known:
            put("aspect_override", known[ratio], f"Aspect ratio override: {known[ratio]}")
    stereo = {"0": "off", "1": "off", "2": "sbsl", "3": "abl"}.get(s.get("Stereo3DMode", "0"))
    if stereo and stereo != "off":
        put("stereo3d", stereo, f"3D video: {stereo}")
    if s.get("AudioWindowMode") in ("0", "2"):
        put("audio_display", "no" if s["AudioWindowMode"] == "0" else "embedded-first", "Audio-only display")
    if s.get("HistoryEntriesMax", "").isdigit():
        put("history_max", max(10, int(s["HistoryEntriesMax"])), f"Position history: {s['HistoryEntriesMax']} files")
    if s.get("NetworkTimeout", "").isdigit():
        put("network_timeout", int(s["NetworkTimeout"]), f"Network timeout: {s['NetworkTimeout']} s")
    if s.get("UserAgent") and s["UserAgent"] != "Mozilla/5.0":
        put("user_agent", s["UserAgent"], "Network user agent")
    if s.get("WindowModeStartup") == "1" and ";" in s.get("SpecifiedWindowSize", ""):
        w_, h_ = s["SpecifiedWindowSize"].split(";")[:2]
        if w_.isdigit() and h_.isdigit():
            put("startup_size", "specified", f"Startup window size: {w_} x {h_}")
            put("startup_w", int(w_), "")
            put("startup_h", int(h_), "")
    for ini, ours in (("ThumbCols", "thumb_cols"), ("ThumbRows", "thumb_rows"), ("ThumbWidth", "thumb_width")):
        if s.get(ini, "").isdigit():
            put(ours, int(s[ini]), f"Thumbnail sheet {ours.split('_')[1]}: {s[ini]}")
    if s.get("SnapShotPath"):
        put("shot_dir", s["SnapShotPath"].rstrip("\\"), f"Screenshot folder: {s['SnapShotPath']}")
    fs_res = cp["Settings\\FullscreenRes"] if cp.has_section("Settings\\FullscreenRes") else {}
    if fs_res.get("Enable") == "1" and fs_res.get("ApplyDefault") == "1":
        put("fs_refresh", True, "Match refresh rate in full screen: on")
    video = cp["Video"] if cp.has_section("Video") else {}
    flag("ColorManagement", "icc_auto", "Color management", section=video)
    if video.get("EVROutputRange") in ("0", "1"):
        put("output_levels", "full" if video["EVROutputRange"] == "0" else "limited", "Output levels")
    if a.get("Gain"):
        try:
            put("gain", max(0.0, round(float(a["Gain"]), 1)), f"Gain: {a['Gain']} dB")
        except ValueError:
            pass
    if a.get("NormLevel", "").isdigit():
        put("norm_strength", int(a["NormLevel"]), f"Normalize level: {a['NormLevel']}%")
    pls = cp["Playlist"] if cp.has_section("Playlist") else {}
    if pls.get("Shuffle") == "1":
        put("folder_order", "shuffle", "Folder order: shuffle")
    flag("NextOnError", "next_on_error", "Skip files that won't open", section=pls)

    osd = cp["OSD"] if cp.has_section("OSD") else {}
    flag("LocalTime", "osd_clock", "Clock in full screen", section=osd)
    if osd.get("Size", "").isdigit():
        put("osd_size", int(osd["Size"]), f"On-screen message size: {osd['Size']}")
    if "FileName" in osd:
        put("osd_filename", osd["FileName"] == "1", "Show file name on open: " + ("on" if osd["FileName"] == "1" else "off"))
    if "ShowOSD" in osd:
        put("toast", osd["ShowOSD"] == "1", "On-screen messages: " + ("on" if osd["ShowOSD"] == "1" else "off"))

    # Subtitle default style: l;t;r;b margins;type;?;border;?;shadow;?;colors(4);alphas(4);charset;font;size;...;weight
    style = s.get("SPDefaultStyle", "")
    parts = style.split(";")
    if len(parts) >= 25:
        try:
            border = float(parts[6])
            shadow = float(parts[8])
            text_c, outline_c = _bgr(parts[10]), _bgr(parts[12])
            font, size, weight = parts[19], float(parts[20]), int(parts[24])
            mpv_size = round(size * 2.5)  # MPC sizes are for a 288-line script; mpv's are for 720 lines
            put("sub_font", font, f"Subtitle font: {font}")
            put("sub_font_size", mpv_size, f"Subtitle size: {size:g} (MPC-BE) → {mpv_size} (Iron Will)")
            put("sub_bold", weight >= 600, f"Subtitle bold: {'yes' if weight >= 600 else 'no'}")
            put("sub_color", text_c, f"Subtitle color: {text_c}")
            put("sub_outline_color", outline_c, f"Subtitle outline color: {outline_c}")
            put("sub_outline_size", round(border * 1.5, 1), f"Subtitle outline: {border:g}")
            put("sub_shadow", round(shadow * 0.75, 1), f"Subtitle shadow: {shadow:g}")
        except (ValueError, IndexError):
            notes.append("Subtitle style: couldn't read it, skipped")

    for key in ("ColorBrightness", "ColorContrast", "ColorSaturation", "ColorHue"):
        if key in v:
            ours = key.replace("Color", "").lower()
            put(ours, int(float(v[key])), f"{ours.capitalize()}: {v[key]}")

    if m:
        from .settings import DEFAULT_MOUSE, GESTURES, MOUSE_COMMANDS
        names, gesture_names = dict(MOUSE_COMMANDS), dict(GESTURES)
        unknown, mouse = set(), {g: list(v) for g, v in DEFAULT_MOUSE.items()}
        for key, gesture in MPC_GESTURES.items():
            if key in m:
                mouse[gesture] = _mouse_slots(m[key], unknown)
                parts = [f"{col}: {names[c]}" for col, c in zip(("", "Ctrl", "Shift", "Right held"), mouse[gesture])
                         if c != "none"]
                notes.append(f"Mouse {gesture_names[gesture]} → " + (", ".join(parts).replace(": ", "", 1)
                                                                     if parts else "nothing"))
        changes["mouse"] = mouse
        if unknown - {0}:
            notes.append(f"Mouse commands with no Iron Will equivalent were left empty: {sorted(unknown)}")
    if "EasyMove" in m:
        put("easy_move", m["EasyMove"] == "1", "Drag the video to move the window: "
            + ("on" if m["EasyMove"] == "1" else "off"))
    if "LongPressLeftSpeed" in m:
        on = m["LongPressLeftSpeed"] == "1"
        put("longpress", on, "Hold left button to fast-forward: " + ("on" if on else "off"))
        if m.get("LongPressLeftSpeedDelay"):
            put("longpress_delay", int(m["LongPressLeftSpeedDelay"]), f"  …after {m['LongPressLeftSpeedDelay']} ms")
        if m.get("LongPressLeftSpeedRate"):
            put("longpress_speed", float(m["LongPressLeftSpeedRate"]), f"  …at {m['LongPressLeftSpeedRate']}x speed")

    if a.get("AutoVolumeControl") == "1":
        put("normalize", True, "Volume normalization: on")
    else:
        put("normalize", False, "Volume normalization: off")

    skipped = ["Video renderer, EVR and filter settings (DirectShow-only; mpv handles this itself)",
               "HLSL shaders (MPC-BE uses DirectX shaders; Iron Will uses GLSL shaders)",
               "Keyboard shortcuts (none were customized)" if not cp.has_section("Commands2")
               else "Custom keyboard shortcuts (different command system; set them under Player > Keys)"]
    return changes, notes, skipped
