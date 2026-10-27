"""The full Iron Will command menu, laid out like MPC-BE's right-click menu (File, Play/Pause, Repeat, Zoom,
Video Frame, Pan&Scan, Navigate, Favorites, Shaders, Audio, Subtitles, Volume, After Playback, View, ...), with
only what Iron Will can really do. Defined once as a plain model, then rendered three ways: the right-click menu,
the window's title-bar (system) menu, and the optional menu bar (File / View / Play / Navigate / Favorites / Help)."""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from ..settings import DATA_DIR


@dataclass
class Item:
    label: str
    action: object = None
    shortcut: str = ""
    checked: object = None   # None = not checkable
    enabled: bool = True
    children: list = field(default=None)


SEP = None
SPEEDS = [0.5, 0.75, 0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.25, 1.35, 1.5, 1.75, 2.0]
ASPECTS = [("Default", "no"), ("16:9", "16:9"), ("4:3", "4:3"), ("21:9", "2.33:1"), ("2.35:1", "2.35:1"),
           ("1.85:1", "1.85:1"), ("1:1", "1:1")]


def _get(mpv, name, default=None):
    try:
        value = mpv._get_property(name)
        return default if value is None else value
    except Exception:
        return default


def _set(mpv, name, value):
    try:
        mpv._set_property(name, value)
    except Exception:
        pass


def track_label(t):
    """MPC-BE style: 'English, Crunchyroll Dub (AAC, 48.0 kHz, 2.0 chn)'."""
    lang = (t.get("lang") or "").strip()
    head = ", ".join(x for x in (lang.capitalize() if len(lang) > 3 else lang.upper(), t.get("title") or "") if x)
    tech = [(t.get("codec") or "").upper()]
    if t.get("demux-samplerate"):
        tech.append(f"{t['demux-samplerate'] / 1000:.1f} kHz")
    if t.get("demux-channel-count"):
        tech.append(f"{t['demux-channel-count']} chn")
    if t.get("default"):
        tech.append("default")
    if t.get("forced"):
        tech.append("forced")
    tech = ", ".join(x for x in tech if x)
    return f"{head or 'Track ' + str(t['id'])} ({tech})" if tech else (head or f"Track {t['id']}")


def sections(win):
    """Every menu, by name, reflecting the player's current state."""
    e, m, cfg = win.engine, win.engine.mpv, win.cfg
    loaded = bool(e.path)
    keys = win.shortcut_text
    run = win.run_command

    def tracks(kind, allow_off):
        ts = e.tracks(kind)
        sel = next((t["id"] for t in ts if t.get("selected")), None)
        out = [Item("Off", lambda: e.select_track(kind, None), checked=sel is None)] if allow_off else []
        out += [Item(track_label(t), lambda i=t["id"]: e.select_track(kind, i), checked=t["id"] == sel) for t in ts]
        return out or [Item("None in this file", enabled=False)]

    # File -----------------------------------------------------------------------------------------------
    recent = win.recent_files()
    file_menu = [
        Item("Open File…", win.open_dialog, keys("open")),
        Item("Open Folder…", win.open_folder_dialog),
        Item("Recent Files", enabled=bool(recent), children=[
            Item(Path(p).name, lambda p=p: win.open_path(p)) for p in recent] + [
            SEP, Item("Clear list", win.clear_recent)]),
        Item("Close", win.stop, enabled=loaded),
        SEP,
        Item("Save Image…", win.save_frame, keys("screenshot"), enabled=loaded),
        Item("Save Thumbnails…", win.save_thumbnails, enabled=loaded),
        Item("Open Screenshots Folder", lambda: _open_folder(cfg["shot_dir"])),
        SEP,
        Item("Load Subtitle…", win._add_subs, enabled=loaded),
        Item("Load External Audio…", win.add_audio_file, enabled=loaded),
        SEP,
        Item("Properties", win.show_properties, keys("properties"), enabled=loaded),
        Item("Find Duplicates…", win.open_duplicates, keys("duplicates")),
        SEP,
        Item("Exit", win.close, keys("exit")),
    ]

    # Repeat, zoom, frame, pan & scan --------------------------------------------------------------------------
    repeat = [
        Item("Forever", lambda: run("repeat_toggle"), checked=cfg["loop_file"] == "inf"),
        SEP,
        Item("A-B (Reset)", lambda: run("ab_clear"), enabled=win.loop["a"] is not None or win.loop["b"] is not None),
        Item("A-B (Mark A)", lambda: run("ab_a"), checked=win.loop["a"] is not None, enabled=loaded),
        Item("A-B (Mark B)", lambda: run("ab_b"), checked=win.loop["b"] is not None, enabled=loaded),
        Item("Save A-B Clip (fast, exact copy)", lambda: win.save_loop_clip(precise=False),
             enabled=loaded and (win.loop["a"] is not None or win.loop["b"] is not None)),
        Item("Save A-B Clip (frame-accurate, re-encode)", lambda: win.save_loop_clip(precise=True),
             enabled=loaded and (win.loop["a"] is not None or win.loop["b"] is not None)),
    ]
    zoom = [
        Item("50%", lambda: win.fit_to_video(0.5), keys("zoom_50"), enabled=loaded),
        Item("100%", lambda: win.fit_to_video(1.0), keys("zoom_100"), enabled=loaded),
        Item("200%", lambda: win.fit_to_video(2.0), keys("zoom_200"), enabled=loaded),
        Item("Auto Fit", lambda: win.fit_to_video(None), keys("zoom_auto"), enabled=loaded),
    ]
    frame_mode = win.video_frame_mode()
    aspect = str(_get(m, "video-aspect-override", "no"))
    video_frame = [
        Item("Half Size", lambda: win.set_video_frame("half"), checked=frame_mode == "half"),
        Item("Normal Size", lambda: win.set_video_frame("normal"), checked=frame_mode == "normal"),
        Item("Double Size", lambda: win.set_video_frame("double"), checked=frame_mode == "double"),
        Item("Stretch To Window", lambda: win.set_video_frame("stretch"), checked=frame_mode == "stretch"),
        Item("Touch Window From Inside", lambda: win.set_video_frame("inside"), checked=frame_mode == "inside"),
        Item("Touch Window From Outside", lambda: win.set_video_frame("outside"), checked=frame_mode == "outside"),
        SEP,
        Item("Keep Aspect Ratio", lambda: win.set_prefs({"keepaspect": not cfg["keepaspect"]}),
             checked=cfg["keepaspect"]),
        Item("Override Aspect Ratio", children=[
            Item(lbl, lambda v=val: e.set_aspect(v), checked=aspect == val or (val == "no" and aspect in ("no", "-1")))
            for lbl, val in ASPECTS]),
    ]
    pan = [
        Item("Increase Size", lambda: run("zoom_in")),
        Item("Decrease Size", lambda: run("zoom_out")),
        Item("Increase Width", lambda: win.scale_axis("x", 0.05)),
        Item("Decrease Width", lambda: win.scale_axis("x", -0.05)),
        Item("Increase Height", lambda: win.scale_axis("y", 0.05)),
        Item("Decrease Height", lambda: win.scale_axis("y", -0.05)),
        SEP,
        Item("Move Right", lambda: run("pan_right")),
        Item("Move Left", lambda: run("pan_left")),
        Item("Move Up", lambda: run("pan_up")),
        Item("Move Down", lambda: run("pan_down")),
        Item("Center", lambda: (_set(m, "video-pan-x", 0), _set(m, "video-pan-y", 0))),
        SEP,
        Item("Rotate Clockwise", lambda: win.rotate(90)),
        Item("Rotate Counterclockwise", lambda: win.rotate(-90)),
        Item("Flip Horizontally", lambda: m.command("vf", "toggle", "hflip")),
        SEP,
        Item("Reset", win.reset_view),
    ]
    for group in (video_frame, pan):
        for it in group:
            if it is not None and it.children is None:
                it.enabled = it.enabled and loaded

    # Navigate, favorites -------------------------------------------------------------------------------------
    chapters = _get(m, "chapter-list", []) if loaded else []
    current_chapter = _get(m, "chapter", -1)
    navigate = [
        Item("Previous", lambda: win.play_neighbor(-1), keys("prev"), enabled=loaded),
        Item("Next", lambda: win.play_neighbor(1), keys("next"), enabled=loaded),
        Item("Go To…", win.go_to_time, keys("goto"), enabled=loaded),
        Item("Jump To…", enabled=bool(chapters), children=[
            Item(f"{c.get('title') or f'Chapter {i + 1}'}   {_fmt(c.get('time', 0))}",
                 lambda i=i: _set(m, "chapter", i), checked=i == current_chapter)
            for i, c in enumerate(chapters)] or [Item("No chapters", enabled=False)]),
    ]
    favs = cfg.values.get("favorites", [])
    favorites = [
        Item("Add to Favorites", win.add_favorite, enabled=loaded),
        Item("Remove", enabled=bool(favs), children=[
            Item(f["name"], lambda i=i: win.remove_favorite(i)) for i, f in enumerate(favs)] or [
            Item("Nothing saved", enabled=False)]),
    ]
    if favs:
        favorites += [SEP] + [Item(f"{f['name']}   {_fmt(f.get('pos', 0))}", lambda f=f: win.open_favorite(f))
                              for f in favs]

    # Shaders, audio, subtitles, volume ---------------------------------------------------------------------
    shaders = [
        Item("Enable Shaders", lambda: win.set_prefs({"shaders_on": not cfg["shaders_on"]}),
             checked=cfg["shaders_on"], enabled=bool(cfg.values.get("shaders"))),
        Item("Select Shaders…", lambda: win.open_options("shaders")),
    ]
    audio = tracks("audio", False) + [
        SEP,
        Item("Load External Audio…", win.add_audio_file, enabled=loaded),
        Item(f"Delay +{cfg['audio_delay_step']} ms", lambda: win.nudge_delay("audio-delay", cfg["audio_delay_step"] / 1000, "Audio delay"), keys("audio_delay_up"), enabled=loaded),
        Item(f"Delay -{cfg['audio_delay_step']} ms", lambda: win.nudge_delay("audio-delay", -cfg["audio_delay_step"] / 1000, "Audio delay"), keys("audio_delay_down"), enabled=loaded),
        Item("Reset Delay", lambda: _set(m, "audio-delay", 0), enabled=loaded),
        SEP,
        Item("Even Out Loud and Quiet Scenes", lambda: win.set_prefs({"normalize": not cfg["normalize"]}),
             checked=cfg["normalize"]),
        Item("Night Mode", lambda: win.set_prefs({"night_mode": not cfg["night_mode"]}), checked=cfg["night_mode"]),
    ]
    subs_on = bool(_get(m, "sid", False))
    subtitles = [
        Item("Enable", lambda: run("sub_toggle"), checked=subs_on, enabled=loaded and bool(e.tracks("sub"))),
        SEP,
    ] + tracks("sub", True) + [
        SEP,
        Item("Load External Subtitle…", win._add_subs, enabled=loaded),
        Item("Find Subtitles Online", lambda: win.find_foreign_subs(online=True), enabled=loaded),
        Item("Make Subtitles from the Audio (offline, slow)", lambda: win.find_foreign_subs(online=False), enabled=loaded),
        Item("Advanced", enabled=loaded, children=[
            Item(f"Delay +{cfg['sub_delay_step']} ms", lambda: win.nudge_delay("sub-delay", cfg["sub_delay_step"] / 1000, "Subtitle delay"), keys("sub_delay_up")),
            Item(f"Delay -{cfg['sub_delay_step']} ms", lambda: win.nudge_delay("sub-delay", -cfg["sub_delay_step"] / 1000, "Subtitle delay"), keys("sub_delay_down")),
            Item("Reset Delay", lambda: _set(m, "sub-delay", 0)),
            SEP,
            Item("Bigger", lambda: win.nudge_delay("sub-scale", 0.1, "Subtitle size", "{:.1f}x", 0.3, 4)),
            Item("Smaller", lambda: win.nudge_delay("sub-scale", -0.1, "Subtitle size", "{:.1f}x", 0.3, 4)),
            Item("Move Up", lambda: win.nudge_delay("sub-pos", -5, None, lo=0, hi=150)),
            Item("Move Down", lambda: win.nudge_delay("sub-pos", 5, None, lo=0, hi=150)),
        ]),
    ]
    volume = [
        Item("Up", lambda: win.nudge_volume(cfg["volume_step"]), keys("vol_up")),
        Item("Down", lambda: win.nudge_volume(-cfg["volume_step"]), keys("vol_down")),
        Item("Mute", e.toggle_mute, keys("mute"), checked=bool(_get(m, "mute", False))),
    ]
    speed = float(_get(m, "speed", 1.0))
    step = int(cfg["speed_step"])
    playback_speed = [
        Item(f"Increase Rate  (+{step}%)", lambda: win.step_speed(1), keys("speed_up"), enabled=loaded),
        Item(f"Decrease Rate  (-{step}%)", lambda: win.step_speed(-1), keys("speed_down"), enabled=loaded),
        Item("Reset Rate  (100%)", lambda: win.set_speed(1.0), keys("speed_reset"), enabled=loaded and abs(speed - 1) > 1e-6),
        SEP,
    ] + [Item(f"{s * 100:.0f}%" + ("  (normal)" if s == 1.0 else ""), lambda s=s: win.set_speed(s),
              checked=abs(s - speed) < 1e-6, enabled=loaded) for s in SPEEDS]

    # After playback (MPC-BE: "Once" choices apply to this file only; "Every time" is saved) ------------------
    once, every = win.after_once, cfg["after_playback"]
    after = [
        Item("────  Once  ────", enabled=False),
        Item("Exit", lambda: win.set_after_once("exit"), checked=once == "exit"),
        Item("Stand By", lambda: win.set_after_once("standby"), checked=once == "standby"),
        Item("Hibernate", lambda: win.set_after_once("hibernate"), checked=once == "hibernate"),
        Item("Shutdown", lambda: win.set_after_once("shutdown"), checked=once == "shutdown"),
        Item("Log Off", lambda: win.set_after_once("logoff"), checked=once == "logoff"),
        Item("Lock", lambda: win.set_after_once("lock"), checked=once == "lock"),
        Item("Do Nothing", lambda: win.set_after_once("nothing"), checked=once == "nothing"),
        Item("────  Every time  ────", enabled=False),
        Item("Exit", lambda: win.set_prefs({"after_playback": "exit"}), checked=every == "exit"),
        Item("Close File", lambda: win.set_prefs({"after_playback": "close"}), checked=every == "close"),
        Item("Play Next in the Folder", lambda: win.set_prefs({"after_playback": "next"}), checked=every == "next"),
        Item("Play Next in the Folder (Looped)", lambda: win.set_prefs({"after_playback": "next_loop"}),
             checked=every == "next_loop"),
        Item("Do Nothing", lambda: win.set_prefs({"after_playback": "nothing"}), checked=every == "nothing"),
    ]

    # View ------------------------------------------------------------------------------------------------
    on_top = cfg["on_top"]
    transparency = [Item("Solid (100%)" if pct == 100 else f"{pct}%", lambda p=pct: win.set_opacity(p),
                         keys(f"opacity_{pct}"), checked=win.opacity == pct)
                    for pct in (100, 90, 80, 70, 60, 50, 40, 30, 20, 10)]
    view = [
        Item("On Top", children=[
            Item("Never", lambda: win.set_prefs({"on_top": "never"}), checked=on_top == "never"),
            Item("Always", lambda: win.set_prefs({"on_top": "always"}), checked=on_top == "always"),
            Item("While Playing", lambda: win.set_prefs({"on_top": "playing"}), checked=on_top == "playing"),
        ]),
        Item("Transparency", children=transparency),
        SEP,
        Item("Hide Menu", lambda: win.set_prefs({"show_menubar": not cfg["show_menubar"]}), keys("menubar"),
             checked=not cfg["show_menubar"]),
        Item("Border", lambda: win.set_prefs({"borderless": not cfg["borderless"]}), keys("border"),
             checked=not cfg["borderless"]),
        Item("Statistics", win.toggle_stats, keys("stats"), checked=win.stats_on, enabled=loaded),
        SEP,
        Item("Full Screen", win.toggle_fullscreen, keys("fullscreen"), checked=win.isFullScreen()),
        Item("Mini View", win.toggle_mini, keys("mini"), checked=win.mini_geometry is not None),
        SEP,
        Item("Presets", children=[
            Item("Minimal  (no border or menu bar)", lambda: win.apply_view_preset("minimal")),
            Item("Compact  (Movies & TV look)", lambda: win.apply_view_preset("compact")),
            Item("Normal  (border and menu bar)", lambda: win.apply_view_preset("normal")),
        ]),
    ]
    renderer = [
        Item("Display Stats", win.toggle_stats, keys("stats"), checked=win.stats_on, enabled=loaded),
        Item("Hardware Decoding", lambda: win.set_prefs({"hwdec": "no" if cfg["hwdec"] != "no" else "auto-safe"}),
             checked=cfg["hwdec"] != "no"),
        Item("Remove Color Banding", lambda: win.set_prefs({"deband": not cfg["deband"]}), checked=cfg["deband"]),
        Item("Deinterlace", lambda: win.set_prefs({"deinterlace": "no" if cfg["deinterlace"] == "yes" else "yes"}),
             checked=cfg["deinterlace"] == "yes"),
        SEP,
        Item("Reset Picture Settings", lambda: win.set_prefs(
            {k: 0 for k in ("brightness", "contrast", "saturation", "gamma", "hue")})),
    ]

    return {
        "file": file_menu, "repeat": repeat, "zoom": zoom, "video_frame": video_frame, "pan": pan,
        "navigate": navigate, "favorites": favorites, "shaders": shaders, "audio": audio, "subtitles": subtitles,
        "volume": volume, "speed": playback_speed, "after": after, "view": view, "renderer": renderer,
        "transparency": transparency,
        "play_pause": Item("Play/Pause", win.play_pause, keys("play_pause"), checked=loaded and not win.paused,
                           enabled=loaded),
        "stop": Item("Stop", win.stop, enabled=loaded),
        "fullscreen": Item("Full Screen", win.toggle_fullscreen, keys("fullscreen"), checked=win.isFullScreen()),
        "properties": Item("Properties", win.show_properties, keys("properties"), enabled=loaded),
        "options": Item("Options…", lambda: win.open_options(), keys("options")),
        "exit": Item("Exit", win.close, keys("exit")),
    }


def build(win):
    """The right-click / title-bar menu, in MPC-BE's order."""
    s = sections(win)
    return [
        Item("File", children=s["file"]),
        SEP,
        s["play_pause"], s["stop"],
        Item("Repeat", children=s["repeat"]),
        SEP,
        s["fullscreen"],
        Item("Zoom", children=s["zoom"]),
        SEP,
        Item("Video Frame", children=s["video_frame"]),
        Item("Pan&Scan", children=s["pan"]),
        SEP,
        Item("Navigate", children=s["navigate"]),
        Item("Favorites", children=s["favorites"]),
        SEP,
        Item("Shaders", children=s["shaders"]),
        SEP,
        Item("Audio", children=s["audio"]),
        Item("Subtitles", children=s["subtitles"]),
        Item("Playback Rate", children=s["speed"]),
        SEP,
        Item("Volume", children=s["volume"]),
        Item("After Playback", children=s["after"]),
        SEP,
        Item("View", children=s["view"]),
        Item("Transparency", children=s["transparency"]),
        SEP,
        Item("Renderer Settings", children=s["renderer"]),
        SEP,
        s["properties"], s["options"],
        SEP,
        s["exit"],
    ]


def menubar_menus(win):
    """MPC-BE's menu bar: File / View / Play / Navigate / Favorites / Help."""
    s = sections(win)
    return [
        ("File", s["file"]),
        ("View", s["view"] + [SEP, Item("Renderer Settings", children=s["renderer"]), SEP, s["properties"],
                              s["options"]]),
        ("Play", [s["play_pause"], s["stop"], Item("Repeat", children=s["repeat"]), SEP, s["fullscreen"],
                  Item("Zoom", children=s["zoom"]), Item("Video Frame", children=s["video_frame"]),
                  Item("Pan&Scan", children=s["pan"]), SEP, Item("Audio", children=s["audio"]),
                  Item("Subtitles", children=s["subtitles"]), Item("Playback Rate", children=s["speed"]),
                  Item("Volume", children=s["volume"]), SEP, Item("Shaders", children=s["shaders"]),
                  Item("After Playback", children=s["after"])]),
        ("Navigate", s["navigate"]),
        ("Favorites", s["favorites"]),
        ("Help", [Item("Keyboard Shortcuts…", lambda: win.open_options("keys")),
                  Item("Mouse Buttons…", lambda: win.open_options("mouse")),
                  SEP,
                  Item("Open Settings Folder", lambda: _open_folder(DATA_DIR)),
                  Item("About Iron Will Media Player", win.show_about)]),
    ]


def _fmt(sec):
    s = max(0, int(sec or 0))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _open_folder(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


# Qt rendering (right-click menu) -------------------------------------------------------------------------
def fill_qt(menu, items, make_menu):
    for it in items:
        if it is SEP:
            menu.addSeparator()
        elif it.children is not None:
            sub = make_menu(menu, it.label)
            fill_qt(sub, it.children, make_menu)
            sub.setEnabled(it.enabled)
            menu.addMenu(sub)
        else:
            label = f"{it.label}\t{it.shortcut}" if it.shortcut else it.label
            a = menu.addAction(label)
            a.setEnabled(it.enabled)
            if it.checked is not None:
                a.setCheckable(True)
                a.setChecked(bool(it.checked))
            if it.action:
                a.triggered.connect(lambda _c=False, f=it.action: f())


# Native rendering (title-bar menu) -----------------------------------------------------------------------
user32 = ctypes.windll.user32
user32.GetSystemMenu.restype = wintypes.HMENU
user32.GetSystemMenu.argtypes = [wintypes.HWND, wintypes.BOOL]
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.GetMenuItemCount.argtypes = [wintypes.HMENU]
user32.DeleteMenu.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
MF_STRING, MF_GRAYED, MF_CHECKED, MF_POPUP, MF_SEPARATOR, MF_BYPOSITION = 0, 0x1, 0x8, 0x10, 0x800, 0x400
WM_SYSCOMMAND, WM_INITMENU = 0x0112, 0x0116
FIRST_ID = 0x1000  # system-menu command ids must stay below 0xF000 and use multiples of 16


class SystemMenu:
    """Keeps an "Iron Will" submenu at the bottom of the window's title-bar menu, rebuilt each time it opens."""

    def __init__(self, win):
        self.win = win
        self.commands = {}
        self.installed = False

    def _hmenu(self):
        return user32.GetSystemMenu(int(self.win.winId()), False)

    def _fill(self, hmenu, items):
        for it in items:
            if it is SEP:
                user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
                continue
            flags = MF_STRING | (0 if it.enabled else MF_GRAYED) | (MF_CHECKED if it.checked else 0)
            label = it.label.replace("&", "&&") + (f"\t{it.shortcut}" if it.shortcut else "")
            if it.children is not None:
                sub = user32.CreatePopupMenu()
                self._fill(sub, it.children)
                user32.AppendMenuW(hmenu, flags | MF_POPUP, sub, label)
            else:
                cid = FIRST_ID + 16 * len(self.commands)
                self.commands[cid] = it.action
                user32.AppendMenuW(hmenu, flags, cid, label)

    def rebuild(self):
        hmenu = self._hmenu()
        if not hmenu:
            return
        if self.installed:  # drop the old separator + "Iron Will" popup (DeleteMenu frees the submenu too)
            n = user32.GetMenuItemCount(hmenu)
            user32.DeleteMenu(hmenu, n - 1, MF_BYPOSITION)
            user32.DeleteMenu(hmenu, n - 2, MF_BYPOSITION)
        self.commands = {}
        root = user32.CreatePopupMenu()
        self._fill(root, build(self.win))
        user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(hmenu, MF_POPUP, root, "Iron Will")
        self.installed = True

    def handle(self, msg):
        """Call from nativeEvent. Returns True when the message was ours."""
        if msg.message == WM_INITMENU and msg.wParam and msg.wParam == (self._hmenu() or 0):
            self.rebuild()
        elif msg.message == WM_SYSCOMMAND:
            fn = self.commands.get(msg.wParam & 0xFFF0)
            if fn:
                fn()
                return True
        return False
