"""MainWindow: the Movies & TV-style surface. Video fills the window; the controls float over it on a soft
gradient, fade away while you watch, and come back the moment the mouse moves."""
import ctypes
import ctypes.wintypes
import os
import re
import sys
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QRectF, QSettings, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import (QAction, QColor, QCursor, QFont, QKeySequence, QLinearGradient, QPainter, QPainterPath, QPixmap,
                           QGuiApplication, QRadialGradient)
from PySide6.QtWidgets import (QFileDialog, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QVBoxLayout, QWidget, QApplication, QPushButton)

from .. import display, playlist, taskbar
from ..engine import PlayerEngine
from ..settings import LANGUAGES, Config, apply_to_mpv
from ..video_view import MpvVideoWidget
from ..resume import ResumeStore
from .widgets import (CloseOrb, Glyph, IconButton, ResumePrompt, SeekBar, SpeedControl, Toast, VolumeFlyout, dark_menu, fmt_time, ui_font,
                      volume_glyph)

ASSETS = Path(__file__).resolve().parent.parent / "assets"
FOLDER_ORDERS = {  # Explorer sort strings for the fixed choices in Options
    "name": "prop:System.ItemNameDisplay;", "name_desc": "prop:-System.ItemNameDisplay;",
    "modified_old": "prop:System.DateModified;", "modified_new": "prop:-System.DateModified;",
    "created_old": "prop:System.DateCreated;", "created_new": "prop:-System.DateCreated;",
    "size_small": "prop:System.Size;", "size_large": "prop:-System.Size;", "shuffle": "shuffle",
}
SUB_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".idx", ".sup"}
HIDE_AFTER_MS = 2500
SPEEDS = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]
ASPECTS = [("Default", "no"), ("16:9", "16:9"), ("4:3", "4:3"), ("21:9", "2.33:1"), ("1:1", "1:1")]
DEBUG = bool(os.environ.get("IW_DEBUG"))


def log(*args):
    if DEBUG:
        print(*args, file=sys.stderr, flush=True)


FILE_FILTER = ("Media files (" + " ".join("*" + e for e in sorted(playlist.MEDIA_EXTS)) + ");;All files (*)")


class BottomBar(QWidget):
    """Title, seek bar, times and the transport row, painted over a dark fade."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 0, 22, 24)  # _layout() applies the bottom gap from Options > Interface
        lay.setSpacing(0)
        lay.addStretch(1)

        self.title = QLabel("")
        self.title.setFont(ui_font(32, QFont.Weight.Light))
        self.title.setStyleSheet("color: white;")
        lay.addWidget(self.title)
        lay.addSpacing(2)

        self.seek = SeekBar()
        lay.addWidget(self.seek)

        times = QHBoxLayout()
        times.setContentsMargins(2, 2, 2, 0)
        self.elapsed, self.remaining = QLabel("0:00:00"), QLabel("0:00:00")
        for lbl in (self.elapsed, self.remaining):
            lbl.setFont(ui_font(15))
            lbl.setStyleSheet("color: white;")
        times.addWidget(self.elapsed)
        times.addStretch(1)
        times.addWidget(self.remaining)
        lay.addLayout(times)
        lay.addSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.volume = IconButton(Glyph.VOL3, "Volume")
        self.subs = IconButton(Glyph.SUBS, "Subtitles and audio")
        self.speed = SpeedControl()
        self.back = IconButton(Glyph.BACK10, "Back 10 seconds (Left)")
        self.play = IconButton(Glyph.PLAY, "Play (Space)", 22, 48)
        self.fwd = IconButton(Glyph.FWD30, "Forward 30 seconds (Shift+Right)")
        self.mini = IconButton(Glyph.MINI, "Mini view (always on top)")
        self.full = IconButton(Glyph.FULL, "Full screen (F)")
        self.more = IconButton(Glyph.MORE, "More options")
        left, center, right = QHBoxLayout(), QHBoxLayout(), QHBoxLayout()
        for w in (self.volume, self.subs, self.speed):
            left.addWidget(w)
        for w in (self.back, self.play, self.fwd):
            center.addWidget(w)
        for w in (self.mini, self.full, self.more):
            right.addWidget(w)
        left.addStretch(1)
        right.insertStretch(0, 1)
        row.addLayout(left, 1)
        row.addLayout(center)
        row.addLayout(right, 1)
        lay.addLayout(row)

    def paintEvent(self, _e):
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0.0, QColor(0, 0, 0, 0))
        g.setColorAt(0.45, QColor(0, 0, 0, 90))
        g.setColorAt(1.0, QColor(0, 0, 0, 185))
        p.fillRect(self.rect(), g)


class CaptionBar(QWidget):
    """Minimize / maximize / close for windows without a title bar (borderless view and full screen).
    A small dark cluster in the top-right corner that fades in only when the mouse heads into that corner."""
    WIDTH, HEIGHT = 156, 36

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.minimize = IconButton(Glyph.MINIMIZE, "Minimize", 11, 0)
        self.restore = IconButton(Glyph.RESTORE, "Exit full screen (Esc)", 11, 0)
        self.close_btn = IconButton(Glyph.CLOSE, "Close", 11, 0, hover=QColor(196, 43, 28))
        for b in (self.minimize, self.restore, self.close_btn):
            b.setFixedSize(52, self.HEIGHT)
            row.addWidget(b)

    def set_mode(self, fullscreen, maximized):
        if fullscreen:
            self.restore.set_glyph(Glyph.RESTORE)
            self.restore.setToolTip("Exit full screen (Esc)")
        else:
            self.restore.set_glyph(Glyph.RESTORE if maximized else Glyph.MAXIMIZE)
            self.restore.setToolTip("Restore" if maximized else "Maximize")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(18, 18, 20, 210))
        path = QPainterPath()
        r = QRectF(self.rect())
        path.addRoundedRect(r.adjusted(0, -12, 12, 0), 10, 10)  # only the bottom-left corner shows rounded
        p.drawPath(path)


class Welcome(QWidget):
    """Shown before anything is opened."""

    def __init__(self, on_open, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        # "I will" brush script from the Iron Will Fitness logo, scaled to the window in resizeEvent.
        self.logo_src = QPixmap(str(ASSETS / "i-will.png"))
        self.default_logo = self.logo_src
        self.logo = QLabel()
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(14)
        # Reads as "I will … media player": the promise that it plays anything.
        sub = QLabel("MEDIA PLAYER")
        f2 = ui_font(22, QFont.Weight.DemiBold)
        f2.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 10)
        sub.setFont(f2)
        btn = QPushButton("  Open a file")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setFont(ui_font(16, QFont.Weight.DemiBold))
        btn.setFixedSize(220, 48)
        btn.setStyleSheet("QPushButton { color: white; background: #E81123; border: none; border-radius: 24px; }"
                          "QPushButton:hover { background: #F0303F; } QPushButton:pressed { background: #C50F1F; }")
        btn.clicked.connect(on_open)
        hint = QLabel("or drop a video anywhere  ·  Ctrl+O")
        hint.setFont(ui_font(14))
        sub.setStyleSheet("color: #E81123;")
        hint.setStyleSheet("color: rgba(255,255,255,140);")
        lay.addWidget(sub, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(40)
        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(14)
        lay.addWidget(hint, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)

    def set_logo(self, path):
        pm = QPixmap(path) if path else QPixmap()
        self.logo_src = pm if not pm.isNull() else self.default_logo
        self.resizeEvent(None)

    def resizeEvent(self, e):
        if e is not None:
            super().resizeEvent(e)
        width = int(min(560, max(220, self.width() * 0.42, 0)))
        width = min(width, int(self.height() * 1.0))
        ratio = self.devicePixelRatioF()
        pm = self.logo_src.scaledToWidth(int(width * ratio), Qt.TransformationMode.SmoothTransformation)
        pm.setDevicePixelRatio(ratio)
        self.logo.setPixmap(pm)

    def paintEvent(self, _e):
        p = QPainter(self)
        g = QRadialGradient(self.width() / 2, self.height() * 0.42, max(self.width(), self.height()) * 0.7)
        g.setColorAt(0.0, QColor(46, 18, 22))
        g.setColorAt(0.55, QColor(16, 14, 16))
        g.setColorAt(1.0, QColor(6, 6, 7))
        p.fillRect(self.rect(), g)


# MPC-BE's Video Frame modes, mapped to mpv's scaling options.
FRAME_PREFS = {"inside": {"keepaspect": True, "unscaled": "no", "panscan": 0.0},
               "outside": {"keepaspect": True, "unscaled": "no", "panscan": 1.0},
               "stretch": {"keepaspect": False, "unscaled": "no", "panscan": 0.0},
               "normal": {"keepaspect": True, "unscaled": "yes", "panscan": 0.0},
               "half": {"keepaspect": True, "unscaled": "yes", "panscan": 0.0},
               "double": {"keepaspect": True, "unscaled": "yes", "panscan": 0.0}}


def set_topmost(hwnd, on):
    """Put a window in (or take it out of) the always-on-top band. The insert-after handle must be passed as a
    pointer: a plain Python -1 goes through ctypes as a 32-bit int, which 64-bit Windows reads as an ordinary
    window handle and silently ignores."""
    after = ctypes.c_void_p(-1 if on else -2)  # HWND_TOPMOST / HWND_NOTOPMOST
    ctypes.windll.user32.SetWindowPos(ctypes.c_void_p(hwnd), after, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)


class MainWindow(QMainWindow):
    def __init__(self, start_file=None):
        super().__init__()
        self.settings = QSettings("IronWill", "IronWillMediaPlayer")
        self.setWindowTitle("Iron Will Media Player")
        self.setMinimumSize(480, 300)
        self.setAcceptDrops(True)
        self.setStyleSheet("QMainWindow { background: black; } QToolTip { color: white; background: #202020;"
                           " border: 1px solid #3a3a3a; padding: 4px; }")
        self.duration = 0.0
        self.position = 0.0
        self.paused = True
        self.mini_geometry = None
        self.was_maximized = False
        self.last_mouse = QPoint()
        self.actions_by_id = {}
        self.sysmenu = None
        self.borderless = False
        self.current_sort = None  # the folder order last used for next / previous
        self.edge_cursor = False
        self.after_once = "nothing"  # After Playback > Once (not saved)
        self.stats_on = False
        # Mouse state for MPC-BE-style bindings, hold-to-fast-forward and drag-to-move.
        self.press_pos = None
        self.right_down = self.right_used = False
        self.boost_speed = None
        self.wheel_acc = [0, 0]
        self.longpress_timer = QTimer(self, singleShot=True)
        self.longpress_timer.timeout.connect(self._start_boost)
        self.press_zone = None    # "back" (left third), "fwd" (right third) or None (middle) for click-and-hold
        self.rewinding = False
        self.rewind_was_paused = False
        self.rewind_timer = QTimer(self, interval=150)
        self.rewind_timer.timeout.connect(self._rewind_tick)

        self.cfg = Config()
        self.tray, self.paused_by_minimize = None, False
        self.opacity = int(self.cfg["opacity"])  # this window's transparency (View > Transparency), in percent
        self.preview_proc, self.preview_want, self.clock = None, None, None
        self.preview_timer = QTimer(self, singleShot=True, interval=180)
        self.preview_timer.timeout.connect(self._grab_preview)
        from PySide6.QtCore import QFileSystemWatcher
        self.sub_watch = QFileSystemWatcher(self)
        self.sub_watch.fileChanged.connect(self._sub_file_changed)
        self.engine = PlayerEngine(self)
        failed = apply_to_mpv(self.engine.mpv, self.cfg.values)
        for label, err in failed:
            log("setting not applied:", label, err)
        stage = QWidget()
        stage.setMouseTracking(True)
        self.setCentralWidget(stage)
        self.stage = stage
        self.video = MpvVideoWidget(self.engine, stage)
        self.welcome = Welcome(self.open_dialog, stage)
        self.bar = BottomBar(stage)
        self.prev_btn = IconButton(Glyph.LEFT, "Previous in folder (PgUp)", 22, 48)
        self.next_btn = IconButton(Glyph.RIGHT, "Next in folder (PgDn)", 22, 48)
        for b in (self.prev_btn, self.next_btn):
            b.setParent(stage)
            b.setFixedSize(44, 88)
        self.caption = CaptionBar(stage)
        self.caption.hide()
        self.caption_fx = QGraphicsOpacityEffect(self.caption)
        self.caption_fx.setOpacity(0.0)
        self.caption.setGraphicsEffect(self.caption_fx)
        self.caption_anim = QVariantAnimation(self, duration=180)
        self.caption_anim.valueChanged.connect(self.caption_fx.setOpacity)
        self.caption_anim.finished.connect(lambda: self.caption_fx.opacity() < 0.05 and self.caption.hide())
        self.caption_timer = QTimer(self, singleShot=True, interval=700)
        self.caption_timer.timeout.connect(lambda: self._fade_caption(False))
        # Round close button that drops down from the top centre when the mouse is in the top quarter.
        self.close_orb = CloseOrb(stage)
        self.close_orb.clicked.connect(self.close)
        self.close_orb.hide()
        self.orb_shown = 0.0  # 0 = tucked away above the window, 1 = fully dropped down
        self.orb_anim = QVariantAnimation(self, duration=200)
        self.orb_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.orb_anim.valueChanged.connect(self._place_orb)
        self.toast = Toast(stage)
        self.resume = ResumeStore()
        self.loaded_ok = False
        self.pending_resume = None
        self.loop = {"a": None, "b": None}  # A-B loop markers (seconds); mpv is told via _sync_ab
        self.prompt = ResumePrompt(stage)
        self.prompt.chosen.connect(self._resume_choice)
        self.flyout = VolumeFlyout(self)

        # Chrome fade (bar + side arrows + full-screen caption buttons) --------------------------------
        self.chrome = [self.bar, self.prev_btn, self.next_btn]  # the caption buttons fade on their own (corner)
        self.effects = {}
        for w in self.chrome:
            eff = QGraphicsOpacityEffect(w)
            eff.setOpacity(1.0)
            w.setGraphicsEffect(eff)
            self.effects[w] = eff
        self.chrome_visible = True
        self.fade = QVariantAnimation(self, duration=260)
        self.fade.valueChanged.connect(lambda v: [e.setOpacity(v) for e in self.effects.values()])
        self.fade.finished.connect(self._fade_done)
        self.hide_timer = QTimer(self, singleShot=True, interval=HIDE_AFTER_MS)
        self.hide_timer.timeout.connect(self.hide_chrome)

        self._wire()
        self._build_actions()
        self._build_menubar()
        QApplication.instance().installEventFilter(self)

        if self.cfg["remember_volume"]:
            self.engine.set_volume(float(self.settings.value("volume", 100)))
        geo = self.settings.value("geometry")
        if self.cfg["startup_size"] == "specified":
            self.resize(int(self.cfg["startup_w"]), int(self.cfg["startup_h"]))
        elif geo is not None and self.cfg["remember_geometry"]:
            self.restoreGeometry(geo)
        else:
            self.resize(1280, 760)
        if self.cfg["remember_mute"]:
            self.engine.mpv.mute = self.settings.value("mute", "false") in (True, "true")
        self._set_loaded(False)
        self.apply_settings()
        if start_file:
            QTimer.singleShot(0, lambda: self.open_path(start_file))

    # Wiring ------------------------------------------------------------------------------------------------
    def _wire(self):
        e, b = self.engine, self.bar
        e.position_changed.connect(self._on_position)
        e.duration_changed.connect(self._on_duration)
        e.pause_changed.connect(self._on_pause)
        e.volume_changed.connect(self._on_volume)
        e.mute_changed.connect(lambda _m: self._on_volume(e.volume))
        e.end_reached.connect(self._on_end)
        e.file_loaded.connect(self._on_loaded)
        e.track_picked.connect(self._save_tracks)
        e.load_failed.connect(self._on_load_failed)
        self.bar.seek.hover_changed.connect(self._seek_hover)
        self.bar.seek.menu_requested.connect(self._seek_menu)

        b.seek.seek_requested.connect(lambda s, exact: e.seek(s, exact))
        b.seek.loop_clear_requested.connect(self._clear_loop_from_timeline)
        b.seek.loop_moved.connect(self._loop_dragged)
        b.seek.loop_hint.connect(lambda: self.toast.show_message("Click the same spot again to clear the A-B loop"))
        b.play.clicked.connect(self.play_pause)
        b.back.clicked.connect(lambda: e.skip(-self.cfg["skip_back"]))
        b.fwd.clicked.connect(lambda: e.skip(self.cfg["skip_fwd"]))
        e.title_changed.connect(self._on_media_title)
        b.full.clicked.connect(self.toggle_fullscreen)
        b.mini.clicked.connect(self.toggle_mini)
        b.volume.clicked.connect(self._show_flyout)
        b.speed.step.connect(self.step_speed)
        b.speed.pick.connect(self._speed_menu)
        e.speed_changed.connect(b.speed.set_speed)
        b.subs.clicked.connect(lambda: self._popup(self._tracks_menu(), b.subs))
        b.more.clicked.connect(lambda: self._popup(self._more_menu(), b.more))
        self.prev_btn.clicked.connect(lambda: self.play_neighbor(-1))
        self.next_btn.clicked.connect(lambda: self.play_neighbor(1))
        self.caption.minimize.clicked.connect(self.showMinimized)
        self.caption.restore.clicked.connect(self._caption_restore)
        self.caption.close_btn.clicked.connect(self.close)
        self.flyout.volume_changed.connect(e.set_volume)
        self.flyout.mute_btn.clicked.connect(e.toggle_mute)
        # mpv may report initial values before these connections exist; sync once so nothing is missed.
        self._on_pause(bool(e.mpv.pause))

    def _build_actions(self):
        def act(aid, text, keys, fn):
            a = QAction(text, self)
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            a.triggered.connect(fn)
            self.addAction(a)
            self.actions_by_id[aid] = (a, keys)
            return a

        e, c = self.engine, self.cfg
        self.act_open = act("open", "Open file(s)…", ["Ctrl+O"], self.open_dialog)
        act("play_pause", "Play / pause", ["Space", "K", "Media Play"], self.play_pause)
        act("seek_back", "Jump back (arrow step)", ["Left", "J"], lambda: e.skip(-c["arrow_step"]))
        act("seek_fwd", "Jump forward (arrow step)", ["Right", "L"], lambda: e.skip(c["arrow_step"]))
        act("skip_back", "Back button jump", ["Shift+Left"], lambda: e.skip(-c["skip_back"]))
        act("skip_fwd", "Forward button jump", ["Shift+Right"], lambda: e.skip(c["skip_fwd"]))
        act("vol_up", "Volume up", ["Up"], lambda: self.nudge_volume(c["volume_step"]))
        act("vol_down", "Volume down", ["Down"], lambda: self.nudge_volume(-c["volume_step"]))
        act("mute", "Mute", ["M"], e.toggle_mute)
        act("fullscreen", "Full screen", ["F", "F11", "Alt+Return"], self.toggle_fullscreen)
        act("exit_fullscreen", "Exit full screen", ["Escape"], self.exit_fullscreen)
        act("mini", "Mini view", ["Ctrl+M"], self.toggle_mini)
        act("border", "Window border on/off", ["Ctrl+B"], lambda: self.set_pref("borderless", not c["borderless"]))
        act("next", "Next file in folder", ["PgDown", "N", "Media Next"], lambda: self.play_neighbor(1))
        act("prev", "Previous file in folder", ["PgUp", "P", "Media Previous"], lambda: self.play_neighbor(-1))
        act("frame_next", "Next frame", ["."], lambda: e.frame_step(True))
        act("frame_prev", "Previous frame", [","], lambda: e.frame_step(False))
        self.act_shot = act("screenshot", "Save current frame", ["Shift+S"], self.save_frame)
        act("speed_up", "Increase rate", ["Ctrl+Up", "]"], lambda: self.step_speed(1))
        act("speed_down", "Decrease rate", ["Ctrl+Down", "["], lambda: self.step_speed(-1))
        act("speed_reset", "Reset rate", ["Ctrl+R", "Backspace"], lambda: self.set_speed(1.0))
        act("goto", "Go to a time", ["Ctrl+G"], self.go_to_time)
        self.act_options = act("options", "Options…", ["O", "Ctrl+,"], self.open_options)
        # MPC-BE's shortcuts for the view and zoom menus
        act("properties", "Properties", ["Shift+F10"], self.show_properties)
        act("duplicates", "Find duplicates", ["Ctrl+D"], self.open_duplicates)
        act("exit", "Exit", ["Alt+X"], self.close)
        act("zoom_50", "Window size 50%", ["Alt+1"], lambda: self.fit_to_video(0.5))
        act("zoom_100", "Window size 100%", ["Alt+2"], lambda: self.fit_to_video(1.0))
        act("zoom_200", "Window size 200%", ["Alt+3"], lambda: self.fit_to_video(2.0))
        act("zoom_auto", "Window size: auto fit", ["Alt+4"], lambda: self.fit_to_video(None))
        act("seek_back_small", "Small jump back", ["Ctrl+Left"], lambda: self.engine.skip(-self.cfg["small_step"]))
        act("open_url", "Open URL…", ["Ctrl+U"], self.open_url)
        act("opacity_up", "More solid", ["Ctrl+Shift+Up"], lambda: self.set_opacity(self.opacity + 10))
        act("opacity_down", "More transparent", ["Ctrl+Shift+Down"], lambda: self.set_opacity(self.opacity - 10))
        for n in range(10):  # Glass2K's hotkeys: Ctrl+Shift+1 = 10% ... Ctrl+Shift+9 = 90%, Ctrl+Shift+0 = solid
            pct = n * 10 or 100
            act(f"opacity_{pct}", f"Transparency {pct}%", [f"Ctrl+Shift+{n}"], lambda _c=False, p=pct: self.set_opacity(p))
        act("seek_fwd_small", "Small jump forward", ["Ctrl+Right"], lambda: self.engine.skip(self.cfg["small_step"]))
        act("sub_delay_down", "Subtitle delay -", ["F1"],
            lambda: self.nudge_delay("sub-delay", -self.cfg["sub_delay_step"] / 1000, "Subtitle delay"))
        act("sub_delay_up", "Subtitle delay +", ["F2"],
            lambda: self.nudge_delay("sub-delay", self.cfg["sub_delay_step"] / 1000, "Subtitle delay"))
        act("audio_delay_down", "Audio delay -", ["-"],
            lambda: self.nudge_delay("audio-delay", -self.cfg["audio_delay_step"] / 1000, "Audio delay"))
        act("audio_delay_up", "Audio delay +", ["+", "="],
            lambda: self.nudge_delay("audio-delay", self.cfg["audio_delay_step"] / 1000, "Audio delay"))
        act("menubar", "Show / hide the menu bar", ["Ctrl+0"], lambda: self.set_pref("show_menubar", not c["show_menubar"]))
        act("stats", "Statistics overlay", ["Ctrl+4", "Ctrl+J"], self.toggle_stats)

    def shortcut_text(self, aid):
        """Current primary shortcut for an action, for showing beside menu items."""
        pair = self.actions_by_id.get(aid)
        if not pair or not pair[0].shortcuts():
            return ""
        return pair[0].shortcuts()[0].toString(QKeySequence.SequenceFormat.NativeText)

    def stop(self):
        if not self.engine.path:
            return
        self._keep_awake(False)
        self._remember_position(force=True)
        self.engine.mpv.command("stop")
        self.engine.path = ""
        self.exit_fullscreen()
        self.setWindowTitle("Iron Will Media Player")
        self._set_loaded(False)
        self.video.update()
        if self.cfg["reset_after_close"] and not (self.isFullScreen() or self.isMaximized()):
            size = (int(self.cfg["startup_w"]), int(self.cfg["startup_h"])) \
                if self.cfg["startup_size"] == "specified" else (1280, 760)
            self.resize(*size)

    def fit_to_video(self, scale):
        w = self.engine.mpv._get_property("dwidth") if self.engine.path else None
        h = self.engine.mpv._get_property("dheight") if self.engine.path else None
        if not w or not h:
            return
        if self.isFullScreen():
            self.exit_fullscreen()
        if self.isMaximized():
            self.showNormal()
        ratio = self.devicePixelRatioF()
        area = self.screen().availableGeometry()
        if scale is None or isinstance(scale, str):  # Auto Fit: as big as fits in a share of the screen
            share = {"50": 0.5, "video": 1.0}.get(scale, 0.75)
            scale = min(area.width() * share * ratio / w, area.height() * share * ratio / h)
            if scale == "video" or share == 1.0:
                scale = min(1.0, scale)  # the video's own size, shrunk only when it doesn't fit
        cw = min(int(w * scale / ratio), area.width() - 40)
        ch = min(int(h * scale / ratio), area.height() - 80)
        extra = self.menuBar().height() if self.menuBar().isVisible() else 0
        self.resize(cw, ch + extra)

    def full_menu(self, parent):
        from . import menus
        m = dark_menu(parent, "Iron Will")
        menus.fill_qt(m, menus.build(self), dark_menu)
        return m

    def nativeEvent(self, event_type, message):
        # event_type arrives as a QByteArray, which never equals a plain bytes literal: convert first.
        if bytes(event_type) == b"windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if self.sysmenu and self.sysmenu.handle(msg):
                return True, 0
            if msg.message == 0x0312:  # WM_HOTKEY: global media keys
                {1: self.engine.toggle_pause, 2: lambda: self.play_neighbor(1), 3: lambda: self.play_neighbor(-1),
                 4: self.stop}.get(msg.wParam, lambda: None)()
                return True, 0
            if msg.message == 0x0111 and (msg.wParam >> 16) == 0x1800:  # WM_COMMAND / THBN_CLICKED: taskbar buttons
                {101: lambda: self.play_neighbor(-1), 102: self.play_pause, 103: lambda: self.play_neighbor(1)}.get(
                    msg.wParam & 0xFFFF, lambda: None)()
                return True, 0
            if msg.message == 0x0216 and self.cfg["snap_edges"]:  # WM_MOVING
                self._snap_rect(ctypes.wintypes.RECT.from_address(msg.lParam))
            elif msg.message == 0x0214 and self.cfg["limit_proportions"]:  # WM_SIZING
                self._keep_proportions(ctypes.wintypes.RECT.from_address(msg.lParam), msg.wParam)
        return super().nativeEvent(event_type, message)

    def _snap_rect(self, r, gap=16):
        """Pull a window being dragged flush against the edges of its monitor's work area."""
        area = self.screen().availableGeometry()
        k = self.devicePixelRatioF()
        L, T, Rt, B = (int(v * k) for v in (area.left(), area.top(), area.right() + 1, area.bottom() + 1))
        w, h = r.right - r.left, r.bottom - r.top
        if abs(r.left - L) < gap:
            r.left, r.right = L, L + w
        elif abs(r.right - Rt) < gap:
            r.left, r.right = Rt - w, Rt
        if abs(r.top - T) < gap:
            r.top, r.bottom = T, T + h
        elif abs(r.bottom - B) < gap:
            r.top, r.bottom = B - h, B

    def _keep_proportions(self, r, edge):
        """While resizing, keep the video area the same shape as the video (MPC-BE: Limit window proportions)."""
        vw = self.engine.mpv._get_property("dwidth") if self.engine.path else None
        vh = self.engine.mpv._get_property("dheight") if self.engine.path else None
        if not vw or not vh:
            return
        k = self.devicePixelRatioF()
        frame_w = int((self.frameGeometry().width() - self.stage.width()) * k)
        frame_h = int((self.frameGeometry().height() - self.stage.height()) * k)
        w, h = r.right - r.left - frame_w, r.bottom - r.top - frame_h
        if edge in (3, 6):  # top / bottom edge: width follows height
            w = int(h * vw / vh)
            r.right = r.left + w + frame_w
        else:  # sides and corners: height follows width
            h = int(w * vh / vw)
            if edge in (3, 4, 5):  # top edges move the top
                r.top = r.bottom - h - frame_h
            else:
                r.bottom = r.top + h + frame_h

    def action_table(self):
        """(id, label, default keys) for the Options > Keys page."""
        return [(aid, a.text().replace("…", ""), keys) for aid, (a, keys) in self.actions_by_id.items()]

    def open_options(self, page=None):
        from .options import OptionsDialog  # imported lazily: only needed when the window opens
        self.hide_timer.stop()
        dlg = OptionsDialog(self)
        if page:
            dlg.select_page(page)
        dlg.exec()
        self.show_chrome()

    def apply_settings(self):
        """Re-read app-side preferences (mpv-side ones are pushed by settings.apply_to_mpv)."""
        c = self.cfg
        self.hide_timer.setInterval(int(c["hide_delay"] * 1000))
        overrides = c.values.get("keys", {})
        for aid, (a, keys) in self.actions_by_id.items():
            if aid in overrides:
                seq = overrides[aid]
                a.setShortcuts([QKeySequence(seq)] + [QKeySequence(k) for k in keys[1:]] if seq else [])
            else:
                a.setShortcuts([QKeySequence(k) for k in keys])
        self.bar.back.set_skip(c["skip_back"], back=True)
        self.bar.fwd.set_skip(c["skip_fwd"], back=False)
        self.bar.back.setToolTip(f"Back {c['skip_back']} seconds")
        self.bar.fwd.setToolTip(f"Forward {c['skip_fwd']} seconds")
        self.toast.enabled = c["toast"]
        self.toast.set_style(c["osd_font"], c["osd_size"], c["osd_color"] or "#FFFFFF", c["osd_opacity"])
        from . import widgets as _w
        _w.ZERO_HOURS = bool(c["show_zero_hours"])
        self.bar.seek.show_time = bool(c["seek_tooltip"])
        self.resume.max_entries = int(c["history_max"])
        self._update_clock()
        self.welcome.set_logo(c["logo_file"])
        self._register_media_keys(bool(c["global_media_keys"]))
        if not c["taskbar"]:
            self._taskbar_progress(None)
        if not int(c["recent_count"]):
            self.settings.setValue("recent", [])
        self._sync_tray()
        self._set_priority()
        if c["opacity"] != getattr(self, "applied_opacity", c["opacity"]):  # Options changed the default
            self.set_opacity(c["opacity"], announce=False)
        self.applied_opacity = c["opacity"]
        self.setWindowOpacity(1.0 if c["opacity_hover_solid"] and self.underMouse() else self.opacity / 100)
        if c["video_frame"] != getattr(self, "applied_frame", c["video_frame"]):
            # Options changed the default video frame: push the matching scaling options (only on a change, so the
            # separate Keep Aspect Ratio checkbox still works on its own)
            stale = {k: v for k, v in FRAME_PREFS.get(c["video_frame"], FRAME_PREFS["inside"]).items() if c[k] != v}
            c.values.update(stale)
            apply_to_mpv(self.engine.mpv, c.values, only=list(stale))
            self._apply_video_zoom()
        self.applied_frame = c["video_frame"]
        if self.engine.path:
            self._show_times()
        self.bar.title.setStyleSheet(f"color: {c['title_color'] or '#FFFFFF'};")
        if self.mini_geometry is None:
            self._set_topmost(self._topmost_wanted())
        self.menuBar().setVisible(bool(c["show_menubar"]) and not self.isFullScreen())
        self._layout()
        self._update_neighbors()
        self._sync_ab()  # repeat on/off changes what an A-only marker does
        self._sync_border()
        self._update_awake()

    def _sync_border(self):
        """Borderless window, like mpv's Window > Border: same size and place, no title bar or frame."""
        want = bool(self.cfg["borderless"])
        if want == self.borderless or self.isFullScreen():
            return  # full screen is already frameless; exit_fullscreen re-syncs
        self.borderless = want
        if not self.isVisible():  # at startup: just set the flag before the first show
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, want)
            return
        client = self.geometry()  # the video area on screen; keep it exactly where it is
        maximized = self.isMaximized()
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, want)  # Windows recreates the native window
        if maximized:
            self.showMaximized()
        else:
            self.show()
            self.setGeometry(client)
        if self.sysmenu:  # the new native window has a fresh title-bar menu
            self.sysmenu.installed = False
            self.sysmenu.rebuild()
        self._set_topmost(self._topmost_wanted())
        self._dwm_outline()
        self.toast.show_message("Border off  ·  Ctrl+B brings it back" if want else "Border on")

    @staticmethod
    def _edge_shape(edges):
        E, C = Qt.Edge, Qt.CursorShape
        if not edges:
            return None
        if edges in (E.LeftEdge | E.TopEdge, E.RightEdge | E.BottomEdge):
            return C.SizeFDiagCursor
        if edges in (E.RightEdge | E.TopEdge, E.LeftEdge | E.BottomEdge):
            return C.SizeBDiagCursor
        return C.SizeHorCursor if edges & (E.LeftEdge | E.RightEdge) else C.SizeVerCursor

    def _resize_edges(self, global_pos):
        """Which window edges the cursor is on (borderless windows resize from their edges)."""
        if not self.borderless or self.isFullScreen() or self.isMaximized():
            return Qt.Edge(0)
        p, w, h, m = self.mapFromGlobal(global_pos), self.width(), self.height(), 6
        edges = Qt.Edge(0)
        if p.x() <= m:
            edges |= Qt.Edge.LeftEdge
        elif p.x() >= w - m:
            edges |= Qt.Edge.RightEdge
        if p.y() <= m:
            edges |= Qt.Edge.TopEdge
        elif p.y() >= h - m:
            edges |= Qt.Edge.BottomEdge
        return edges

    def set_opacity(self, pct, announce=True):
        """Glass2K-style transparency for this window only (Options sets the starting value for new windows)."""
        self.opacity = max(10, min(100, int(pct)))
        if not (self.cfg["opacity_hover_solid"] and self.underMouse()):
            self.setWindowOpacity(self.opacity / 100)
        if announce:
            self.toast.show_message("Solid" if self.opacity == 100 else f"Transparency {self.opacity}%")

    def enterEvent(self, e):
        super().enterEvent(e)
        if self.cfg["opacity_hover_solid"] and self.opacity < 100:
            self.setWindowOpacity(1.0)

    def leaveEvent(self, e):
        super().leaveEvent(e)
        if self.cfg["opacity_hover_solid"] and self.opacity < 100:
            self.setWindowOpacity(self.opacity / 100)

    # Open URL, failed files, seek preview, clock, subtitle reload -------------------------------------------
    def open_url(self):
        from PySide6.QtWidgets import QInputDialog
        clip = QGuiApplication.clipboard().text().strip() if self.cfg["paste_url"] else ""
        start = clip if "://" in clip else ""
        url, ok = QInputDialog.getText(self, "Open URL", "Address of a video or audio file (http, https, rtsp…):",
                                       text=start)
        url = url.strip()
        if not ok or not url:
            return
        self._remember_position(force=True)
        self.engine.open(url)
        self._set_title(url.rsplit("/", 1)[-1] or url)
        self._set_loaded(True)
        self.show_chrome()

    def _seek_menu(self, pos):
        if not self.engine.path:
            return
        has_loop = self.loop["a"] is not None or self.loop["b"] is not None
        m = dark_menu(self, "A-B")
        m.addAction("Mark A here", lambda: self.run_command("ab_a"))
        m.addAction("Mark B here", lambda: self.run_command("ab_b"))
        if has_loop:
            m.addSeparator()
            m.addAction("Save A-B Clip (fast, exact copy)", lambda: self.save_loop_clip(precise=False))
            m.addAction("Save A-B Clip (frame-accurate, re-encode)", lambda: self.save_loop_clip(precise=True))
            m.addSeparator()
            m.addAction("Clear A-B Loop", lambda: self.run_command("ab_clear"))
        m.exec(pos)

    def save_loop_clip(self, precise=False):
        """Write the A-B section to its own file with FFmpeg. Fast = stream copy (instant, no quality loss, but starts
        on the keyframe at or before A); frame-accurate = re-encode (exact start, takes longer)."""
        from PySide6.QtCore import QProcess
        from ..dupes.fingerprint import find_tool
        src = self.engine.path
        if not src or "://" in src:
            return
        a = self.loop["a"] if self.loop["a"] is not None else 0.0
        b = self.loop["b"] if self.loop["b"] is not None else self.duration
        if b <= a:
            self.toast.show_message("Set A before B first")
            return
        ffmpeg = find_tool("ffmpeg")
        if not ffmpeg:
            self.toast.show_message("FFmpeg wasn't found")
            return
        stamp = lambda t: fmt_time(t).replace(":", ".")
        ext = ".mp4" if precise else Path(src).suffix
        default = Path(src).with_name(f"{Path(src).stem} clip {stamp(a)} - {stamp(b)}{ext}")
        out, _ = QFileDialog.getSaveFileName(self, "Save A-B Clip", str(default),
                                             "Video (*.mp4)" if precise else f"Video (*{ext})")
        if not out:
            return
        if precise:
            args = ["-y", "-v", "error", "-ss", f"{a:.3f}", "-i", src, "-t", f"{b - a:.3f}", "-map", "0:v:0", "-map", "0:a?",
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-b:a", "192k", "-movflags", "+faststart", out]
        else:
            args = ["-y", "-v", "error", "-ss", f"{a:.3f}", "-i", src, "-t", f"{b - a:.3f}", "-map", "0", "-c", "copy",
                    "-avoid_negative_ts", "make_zero", out]
        proc = QProcess(self)
        self.clip_procs = getattr(self, "clip_procs", []) + [proc]

        def done(code, _status):
            self.clip_procs.remove(proc)
            ok = code == 0 and Path(out).exists()
            self.toast.show_message(f"Clip saved: {Path(out).name}" if ok else "Couldn't save the clip")
            if not ok:
                log("clip failed:", bytes(proc.readAllStandardError()).decode(errors="replace")[:500])
        proc.finished.connect(done)
        proc.start(ffmpeg, args)
        self.toast.show_message("Saving clip…" if not precise else "Saving clip (re-encoding, this can take a moment)…")

    def _on_load_failed(self, path):
        self.toast.show_message(f"Couldn't open {Path(path).name}")
        if self.cfg["next_on_error"] and path and "://" not in path:
            QTimer.singleShot(600, lambda: self.play_neighbor(1))

    def _seek_hover(self, seconds, x):
        if not self.cfg["seek_preview"] or seconds < 0 or not self.engine.path:
            self.preview_timer.stop()
            if getattr(self, "preview", None) is not None:
                self.preview.hide()
            return
        self.preview_want = (seconds, x)
        self.preview_timer.start()

    def _grab_preview(self):
        from PySide6.QtCore import QProcess
        from ..dupes.fingerprint import find_tool
        if self.preview_proc is not None or self.preview_want is None:
            return  # one grab at a time; the newest request runs when this one finishes
        seconds, x = self.preview_want
        self.preview_want = None
        ffmpeg = find_tool("ffmpeg")
        if not ffmpeg:
            return
        width = int(self.cfg["seek_preview_size"])
        out = Path(os.environ.get("TEMP", ".")) / f"ironwill-preview-{os.getpid()}.jpg"
        proc = QProcess(self)
        self.preview_proc = proc

        def done(*_):
            self.preview_proc = None
            pix = QPixmap(str(out))
            if not pix.isNull() and self.bar.seek.hover_x is not None:
                self._show_preview(pix, x)
            if self.preview_want is not None:
                self._grab_preview()
        proc.finished.connect(done)
        proc.start(ffmpeg, ["-v", "error", "-y", "-ss", f"{seconds:.2f}", "-i", self.engine.path, "-frames:v", "1",
                            "-vf", f"scale={width}:-2", "-q:v", "4", str(out)])

    def _show_preview(self, pix, x):
        if getattr(self, "preview", None) is None:
            self.preview = QLabel(self.stage)
            self.preview.setStyleSheet("border: 2px solid rgba(255,255,255,170); border-radius: 4px; background: black;")
            self.preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.preview.setPixmap(pix)
        self.preview.adjustSize()
        seek = self.bar.seek
        pos = seek.mapTo(self.stage, QPoint(int(x), 0))
        left = min(max(pos.x() - self.preview.width() // 2, 8), self.stage.width() - self.preview.width() - 8)
        self.preview.move(left, pos.y() - self.preview.height() - 4)
        self.preview.show()
        self.preview.raise_()

    def _update_clock(self):
        want = bool(self.cfg["osd_clock"]) and self.isFullScreen()
        if want and self.clock is None:
            self.clock = QLabel(self.stage)
            self.clock.setStyleSheet("color: rgba(255,255,255,220); background: rgba(20,20,20,150); "
                                     "border-radius: 8px; padding: 4px 12px;")
            self.clock.setFont(QFont(self.cfg["osd_font"], 14, QFont.Weight.DemiBold))
            self.clock.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.clock_timer = QTimer(self, interval=5000)
            self.clock_timer.timeout.connect(self._update_clock)
            self.clock_timer.start()
        if self.clock is not None:
            from datetime import datetime
            self.clock.setText(datetime.now().strftime("%I:%M %p").lstrip("0"))
            self.clock.setVisible(want)
            self._layout()

    def _sub_file_changed(self, path):
        if self.cfg["sub_reload"] and self.engine.path:
            QTimer.singleShot(300, lambda: self.engine.mpv.command("sub-reload"))
            if path not in self.sub_watch.files() and Path(path).exists():
                self.sub_watch.addPath(path)  # editors that replace the file drop it from the watch list

    def _external_tracks(self):
        """Subtitle / audio preferences that mpv has no option for: external vs. embedded tracks."""
        e = self.engine
        subs = e.tracks("sub")
        ext_subs = [t for t in subs if t.get("external")]
        selected = next((t for t in subs if t.get("selected")), None)
        if self.cfg["ignore_embedded_subs"] and selected is not None and not selected.get("external"):
            e.select_track("sub", ext_subs[0]["id"] if ext_subs else None, remember=False)
        elif self.cfg["prefer_external_subs"] and selected is not None and not selected.get("external") and ext_subs:
            e.select_track("sub", ext_subs[0]["id"], remember=False)
        ext_audio = [t for t in e.tracks("audio") if t.get("external")]
        if self.cfg["prefer_external_audio"] and ext_audio:
            e.select_track("audio", ext_audio[0]["id"], remember=False)
        if self.sub_watch.files():
            self.sub_watch.removePaths(self.sub_watch.files())
        if self.cfg["sub_reload"]:
            files = [t.get("external-filename") for t in ext_subs if t.get("external-filename")]
            if files:
                self.sub_watch.addPaths(files)

    # Global media keys, taskbar, thumbnails, refresh rate -----------------------------------------------------
    def _register_media_keys(self, on):
        if not self.isVisible():
            QTimer.singleShot(500, lambda: self._register_media_keys(on))
            return
        u32, hwnd = ctypes.windll.user32, ctypes.c_void_p(int(self.winId()))
        for hid in (1, 2, 3, 4):
            u32.UnregisterHotKey(hwnd, hid)
        self.media_keys_on = False
        if on:  # another app may already own them; RegisterHotKey simply fails then
            vks = {1: 0xB3, 2: 0xB0, 3: 0xB1, 4: 0xB2}  # play/pause, next, previous, stop
            self.media_keys_on = all(u32.RegisterHotKey(hwnd, hid, 0x4000, vk) for hid, vk in vks.items())

    def _taskbar_progress(self, frac):
        try:
            tb = taskbar.get()
            hwnd = int(self.winId())
            if frac is None or not self.engine.path:
                tb.set_state(hwnd, 0)
            else:
                tb.set_state(hwnd, 8 if self.paused else 2)  # TBPF_PAUSED (yellow) / TBPF_NORMAL
                tb.set_value(hwnd, int(frac * 1000), 1000)
                if not getattr(self, "thumb_buttons", False):
                    self.thumb_buttons = tb.add_buttons(hwnd)
                tb.set_play_glyph(hwnd, self.paused)
        except Exception as exc:
            log("taskbar:", exc)

    def save_thumbnails(self):
        """MPC-BE's File > Save Thumbnails: a grid of frames spread through the video, as one picture."""
        from PySide6.QtCore import QProcess
        from ..dupes.fingerprint import find_tool
        src, dur = self.engine.path, self.duration
        ffmpeg = find_tool("ffmpeg")
        if not src or "://" in src or dur <= 0 or not ffmpeg:
            return
        cols, rows, width = int(self.cfg["thumb_cols"]), int(self.cfg["thumb_rows"]), int(self.cfg["thumb_width"])
        n = cols * rows
        default = Path(self.cfg["shot_dir"] or Path(src).parent) / f"{Path(src).stem} thumbnails.jpg"
        out, _ = QFileDialog.getSaveFileName(self, "Save Thumbnails", str(default), "JPEG (*.jpg);;PNG (*.png)")
        if not out:
            return
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        cell = max(16, (width // cols) // 2 * 2)
        args = ["-y", "-v", "error"]
        for i in range(n):
            args += ["-ss", f"{dur * (i + 0.5) / n:.2f}", "-i", src]
        parts = [f"[{i}:v]trim=end_frame=1,setpts=PTS-STARTPTS,scale={cell}:-2,setsar=1[t{i}]" for i in range(n)]
        parts.append("".join(f"[t{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0,tile={cols}x{rows}:padding=4:margin=4")
        args += ["-filter_complex", ";".join(parts), "-frames:v", "1", "-q:v", "3", out]
        proc = QProcess(self)
        self.thumb_proc = proc
        proc.finished.connect(lambda code, _s: self.toast.show_message(
            f"Thumbnails saved: {Path(out).name}" if code == 0 and Path(out).exists() else "Couldn't save thumbnails"))
        proc.start(ffmpeg, args)
        self.toast.show_message("Saving thumbnails…")

    def _match_refresh(self):
        if not self.isFullScreen() or not self.engine.path:
            return
        fps = float(self.engine.mpv._get_property("container-fps") or 0)
        name = display.device_for_window(int(self.winId()))
        if fps and display.match(name, fps):
            self.toast.show_message(f"Screen set to {display.current_hz(name)} Hz for {fps:.3g} fps")

    def _sync_tray(self):
        if self.cfg["tray_icon"] and getattr(self, "tray", None) is None:
            from PySide6.QtWidgets import QSystemTrayIcon
            self.tray = QSystemTrayIcon(QApplication.windowIcon(), self)
            self.tray.setToolTip("Iron Will Media Player")
            menu = dark_menu(self, "Tray")
            menu.addAction("Show Iron Will", self._restore_from_tray)
            menu.addAction("Exit", self.close)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(lambda reason: reason == QSystemTrayIcon.ActivationReason.Trigger
                                        and self._restore_from_tray())
            self.tray.show()
        elif not self.cfg["tray_icon"] and getattr(self, "tray", None) is not None:
            self.tray.hide()
            self.tray.deleteLater()
            self.tray = None

    def _restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _set_priority(self):
        cls = {"normal": 0x20, "above": 0x8000, "high": 0x80, "below": 0x4000}.get(self.cfg["priority"], 0x20)
        try:
            ctypes.windll.kernel32.SetPriorityClass(ctypes.c_void_p(-1), cls)  # -1 = this process (pointer-sized)
        except Exception:
            pass

    def _set_topmost(self, on):
        if not self.isVisible():
            # Asking for winId() before the first show creates the native window early - with a border, even when
            # the view is Minimal - and the half-converted window then won't go full screen. showEvent applies it.
            return
        set_topmost(int(self.winId()), on)

    def _dwm_outline(self):
        """Windows 11 draws a thin outline around every window, which shows as a white frame around full-screen
        and borderless video. Turn it off there; keep the normal outline in the bordered views."""
        if not self.isVisible():
            return
        DWMWA_CORNER, DWMWA_BORDER_COLOR = 33, 34
        frameless = self.isFullScreen() or self.borderless
        color = ctypes.c_uint(0xFFFFFFFE if frameless else 0xFFFFFFFF)  # DWMWA_COLOR_NONE / DEFAULT
        corner = ctypes.c_uint(1 if frameless else 0)  # square corners there, so the video isn't notched
        self.dwm_results = []
        try:
            hwnd = int(self.winId())
            self.dwm_results.append(ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(color), 4))
            self.dwm_results.append(ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_CORNER, ctypes.byref(corner), 4))
        except Exception:
            pass  # Windows 10 has no outline or rounded corners

    def _topmost_wanted(self):
        mode = self.cfg["on_top"]
        return mode == "always" or (mode == "playing" and bool(self.engine.path) and not self.paused)

    # MPC-BE-style menu features -------------------------------------------------------------------------
    def set_prefs(self, changes):
        """Change several settings at once from a menu, save them and apply them."""
        self.cfg.values.update(changes)
        self.cfg.save()
        apply_to_mpv(self.engine.mpv, self.cfg.values, only=list(changes))
        self.apply_settings()

    def folder_sort(self, folder):
        """Which order "next file" follows in this folder: File Explorer's current sort for it if it's open (and
        remembered for later), else the last sort seen for it, else the default from Options."""
        mode = self.cfg["folder_order"]
        key = str(folder).lower()
        sorts = dict(self.settings.value("folder_sorts", {}) or {})
        if mode == "explorer":
            spec = playlist.explorer_sort(folder)
            if spec:
                if sorts.get(key) != spec:
                    sorts[key] = spec
                    self.settings.setValue("folder_sorts", sorts)
            else:
                spec = sorts.get(key) or FOLDER_ORDERS[self.cfg["folder_order_default"]]
        else:
            spec = FOLDER_ORDERS.get(mode, playlist.NAME_SORT)
        self.current_sort = spec
        return spec

    def recent_files(self):
        n = int(self.cfg["recent_count"])
        return [p for p in (self.settings.value("recent", []) or []) if Path(p).exists()][:n] if n else []

    def _add_recent(self, path):
        n = int(self.cfg["recent_count"])
        if not n:
            self.settings.setValue("recent", [])
            return
        items = [str(path)] + [p for p in (self.settings.value("recent", []) or []) if p.lower() != str(path).lower()]
        self.settings.setValue("recent", items[:n])

    def clear_recent(self):
        self.settings.setValue("recent", [])

    def open_folder_dialog(self):
        start = self.settings.value("last_dir", "")
        folder = QFileDialog.getExistingDirectory(self, "Play a folder", start)
        if folder:
            files = playlist.siblings(Path(folder) / "_", self.folder_sort(folder))  # in the folder's order
            files = [f for f in files if f.parent == Path(folder)]
            if files:
                self.open_path(files[0])
            else:
                self.toast.show_message("No videos in that folder")

    def add_audio_file(self):
        start = str(Path(self.engine.path).parent) if self.engine.path else ""
        path, _ = QFileDialog.getOpenFileName(self, "Load external audio", start,
                                              "Audio (*.mka *.ac3 *.eac3 *.dts *.aac *.m4a *.mp3 *.flac *.opus *.ogg "
                                              "*.wav *.thd);;All files (*)")
        if path:
            self.engine.mpv.command("audio-add", path, "select")
            self.toast.show_message(f"Audio: {Path(path).name}")

    def nudge_delay(self, prop, delta, label, fmt="{:+.1f} s", lo=None, hi=None):
        m = self.engine.mpv
        v = float(m._get_property(prop) or 0) + delta
        v = max(lo, v) if lo is not None else v
        v = min(hi, v) if hi is not None else v
        m._set_property(prop, round(v, 3))
        if label:
            self.toast.show_message(f"{label} {fmt.format(v)}")

    def video_frame_mode(self):
        return self.cfg["video_frame"]

    def set_video_frame(self, mode):
        """MPC-BE's Video Frame modes, mapped to mpv's scaling options."""
        prefs = FRAME_PREFS[mode]
        self.applied_frame = mode
        self.set_prefs({**prefs, "video_frame": mode})
        self._apply_video_zoom()

    def _apply_video_zoom(self):
        try:
            self.engine.mpv._set_property("video-zoom", {"half": -1.0, "double": 1.0}.get(self.cfg["video_frame"], 0.0))
        except Exception:
            pass

    def scale_axis(self, axis, delta):
        m = self.engine.mpv
        prop = f"video-scale-{axis}"
        m._set_property(prop, round(max(0.1, float(m._get_property(prop) or 1.0) + delta), 3))

    def rotate(self, degrees):
        m = self.engine.mpv
        m._set_property("video-rotate", (int(m._get_property("video-rotate") or 0) + degrees) % 360)
        self.toast.show_message(f"Rotation {m._get_property('video-rotate')}°")

    def reset_view(self):
        m = self.engine.mpv
        for prop, value in (("video-zoom", 0.0), ("video-pan-x", 0.0), ("video-pan-y", 0.0), ("video-scale-x", 1.0),
                            ("video-scale-y", 1.0), ("video-rotate", 0), ("video-aspect-override", "no")):
            try:
                m._set_property(prop, value)
            except Exception:
                pass
        try:
            m.command("vf", "remove", "hflip")
        except Exception:
            pass
        self.toast.show_message("View reset")

    def add_favorite(self):
        if not self.engine.path:
            return
        favs = list(self.cfg.values.get("favorites", []))
        favs.append({"path": self.engine.path, "pos": round(self.position, 1), "name": Path(self.engine.path).stem})
        self.set_prefs({"favorites": favs})
        self.toast.show_message(f"Added to Favorites at {fmt_time(self.position)}")

    def remove_favorite(self, index):
        favs = list(self.cfg.values.get("favorites", []))
        if 0 <= index < len(favs):
            favs.pop(index)
            self.set_prefs({"favorites": favs})

    def open_favorite(self, fav):
        if not Path(fav["path"]).exists():
            self.toast.show_message("That file isn't there anymore")
            return
        self.open_path(fav["path"])
        if fav.get("pos") and self.cfg["fav_position"]:
            self.prompt.hide()
            self.pending_resume = None
            self.engine.mpv.pause = False
            QTimer.singleShot(300, lambda: self.engine.seek(fav["pos"]))

    def set_after_once(self, action):
        self.after_once = action
        labels = {"exit": "Exit", "standby": "Stand by", "hibernate": "Hibernate", "shutdown": "Shut down",
                  "logoff": "Log off", "lock": "Lock the PC", "nothing": "Do nothing"}
        self.toast.show_message(f"When this video ends: {labels[action]}")

    def _run_after_once(self):
        """One-time action at the end of this video (After Playback > Once). Power actions get a 30 s grace."""
        action, self.after_once = self.after_once, "nothing"
        if action == "exit":
            self.close()
        elif action == "lock":
            ctypes.windll.user32.LockWorkStation()
        elif action in ("standby", "hibernate", "shutdown", "logoff"):
            box = QMessageBox(QMessageBox.Icon.Warning, "Iron Will Media Player",
                              f"The video ended. {action.capitalize()} in 30 seconds…",
                              QMessageBox.StandardButton.Cancel, self)
            box.button(QMessageBox.StandardButton.Cancel).setText("Cancel")
            timer = QTimer(box, singleShot=True, interval=30000)
            timer.timeout.connect(box.accept)
            timer.start()
            if box.exec() == QMessageBox.StandardButton.Cancel and timer.isActive():
                self.toast.show_message("Cancelled")
                return
            if action == "shutdown":
                os.system("shutdown /s /t 0")
            elif action == "logoff":
                ctypes.windll.user32.ExitWindowsEx(0, 0)
            else:  # stand by / hibernate
                ctypes.windll.powrprof.SetSuspendState(action == "hibernate", False, False)

    def toggle_stats(self):
        if not self.engine.path:
            return
        self.engine.mpv.command("script-binding", "stats/display-stats-toggle")
        self.stats_on = not self.stats_on

    def apply_view_preset(self, name):
        presets = {
            # The fading seek bar and controls are part of every view; presets only change the frame.
            "minimal": {"borderless": True, "show_menubar": False},
            "compact": {"borderless": False, "show_menubar": False},
            "normal": {"borderless": False, "show_menubar": True},
        }
        self.set_prefs(presets[name])
        self.toast.show_message(f"View: {name.capitalize()}")

    def show_properties(self):
        if self.engine.path:
            from .properties import PropertiesDialog
            self.hide_timer.stop()
            PropertiesDialog(self).exec()

    def open_duplicates(self):
        from ..dupes.finder import FinderWindow
        if getattr(self, "finder", None) is None:
            self.finder = FinderWindow(self)
            self.finder.finished.connect(lambda _r: setattr(self, "finder", None))
        self.finder.show()
        self.finder.raise_()
        self.finder.activateWindow()

    def show_about(self):
        QMessageBox.about(self, "Iron Will Media Player",
                          "<b>Iron Will Media Player</b><br>I will play anything.<br><br>"
                          f"Built on mpv {str(self.engine.mpv._get_property('mpv-version') or '').replace('mpv ', '')}"
                          " and Qt.")

    def _build_menubar(self):
        """MPC-BE's File / View / Play / Navigate / Favorites / Help bar. Hidden unless View > Hide Menu is off;
        each menu is rebuilt when it opens so checkmarks are always current."""
        from . import menus
        bar = self.menuBar()
        bar.setStyleSheet("QMenuBar { background: #1b1b1b; color: #e8e8e8; font-family: 'Segoe UI'; font-size: 13px;"
                          " padding: 2px 4px; } QMenuBar::item { padding: 4px 10px; border-radius: 4px; }"
                          " QMenuBar::item:selected { background: rgba(255,255,255,26); }")
        for title, _items in menus.menubar_menus(self):
            menu = dark_menu(bar, title)

            def refill(menu=menu, title=title):
                menu.clear()
                items = dict(menus.menubar_menus(self))[title]
                menus.fill_qt(menu, items, dark_menu)

            menu.aboutToShow.connect(refill)
            refill()
            bar.addMenu(menu)
        bar.setVisible(False)

    # Opening files -------------------------------------------------------------------------------------------
    def open_dialog(self):
        start = str(Path(self.engine.path).parent) if self.engine.path else self.settings.value("last_dir", "")
        path, _ = QFileDialog.getOpenFileName(self, "Open media", start, FILE_FILTER)
        if path:
            self.open_path(path)

    def open_path(self, path, browsing=False):
        """browsing=True: reached with next / previous or at the end of a file, so it starts from the beginning
        without the Continue / Start over card (that card is only for files you open yourself)."""
        path = Path(path)
        if path.suffix.lower() in SUB_EXTS and self.engine.path:
            self.engine.mpv.command("sub-add", str(path), "select")
            self.toast.show_message(f"Subtitles: {path.name}")
            return
        self.settings.setValue("last_dir", str(path.parent))
        self.folder_sort(path.parent)  # read Explorer's sort for this folder now, while it's likely open
        self._add_recent(path)
        self._remember_position(force=True)  # the file we're leaving
        if not self.cfg["keep_speed"] and self.engine.path:
            self.engine.set_speed(1.0)
        self.prompt.hide()
        self.loaded_ok = False
        saved = self.resume.get(path, self.cfg["resume_days"])
        mode = self.cfg["resume"]
        mode = {True: "ask", False: "never"}.get(mode, mode)  # settings saved before the ask option existed
        if browsing:
            saved = None
        if saved and mode == "ask":
            self.engine.open(path, paused=True)  # first frame behind the card
            self.pending_resume = saved
            self.prompt.ask(saved, self.resume.data[self.resume._key(path)].get("dur", 0))
        elif saved and mode == "always":
            self.engine.open(path, start=saved)
            self.toast.show_message(f"Continuing from {fmt_time(saved)}")
        else:
            self.engine.open(path)
        self._update_awake()  # opening while already playing doesn't fire a pause change
        self.loop = {"a": None, "b": None}  # A-B markers belong to one file...
        self._sync_ab()
        self._restore_loop(path)  # ...and come back when that file is opened again
        self._set_title(path.stem)
        self._set_loaded(True)
        self.show_chrome()
        if self.cfg["start_fullscreen"] and not self.isFullScreen() and self.mini_geometry is None:
            self.toggle_fullscreen()

    def play_pause(self):
        if self.prompt.isVisible():  # Space / play while the card is up means "Continue"
            self._resume_choice(True)
        else:
            self.engine.toggle_pause()

    def _resume_choice(self, cont):
        self.prompt.hide()
        if cont and self.pending_resume:
            self.engine.seek(self.pending_resume)
        self.pending_resume = None
        self.engine.mpv.pause = False

    def _remember_position(self, force=False):
        if self.engine.path and self.loaded_ok and not self.prompt.isVisible():
            self.resume.update(self.engine.path, self.position, self.duration, force=force)

    def _set_title(self, text):
        self.bar.title.setText(text)
        self.setWindowTitle(f"{text} - Iron Will Media Player")

    def _on_media_title(self, title):
        if self.cfg["title_mode"] == "media" and title and self.engine.path:
            self._set_title(title)

    def _neighbor(self, step, spec):
        """The next / previous file in the folder. With After Playback set to 'Play next in the folder (looped)'
        the folder wraps around: after the last file comes the first, before the first comes the last."""
        path = self.engine.path
        if not path or "://" in path:
            return None
        nxt = playlist.neighbor(path, step, spec)
        if nxt is None and self.cfg["after_playback"] == "next_loop":
            files = playlist.siblings(path, spec)
            if len(files) > 1:
                nxt = files[0] if step > 0 else files[-1]
        return nxt

    def play_neighbor(self, step):
        if not self.engine.path:
            return
        nxt = self._neighbor(step, self.folder_sort(Path(self.engine.path).parent))
        if nxt:
            self.open_path(nxt, browsing=True)
        else:
            self.toast.show_message("End of folder" if step > 0 else "First in folder")

    def _set_loaded(self, loaded):
        self.welcome.setVisible(not loaded)
        self.bar.setVisible(loaded)
        self._update_neighbors()

    def _update_neighbors(self):
        show = self.chrome_visible and self.cfg["show_chevrons"]
        spec = self.current_sort or playlist.NAME_SORT  # cached: checking Explorer on every mouse move is too slow
        self.prev_btn.setVisible(bool(self._neighbor(-1, spec)) and show)
        self.next_btn.setVisible(bool(self._neighbor(1, spec)) and show)

    # Engine callbacks ----------------------------------------------------------------------------------------
    def _on_position(self, pos):
        self.position = pos
        self.bar.seek.set_position(pos)
        self._show_times()
        self._remember_position()
        if self.cfg["taskbar"] and self.duration > 0 and int(pos) != getattr(self, "taskbar_sec", -1):
            self.taskbar_sec = int(pos)
            self._taskbar_progress(pos / self.duration)

    def _on_duration(self, d):
        self.duration = d
        self.bar.seek.set_duration(d)
        self._show_times()

    def _show_times(self):
        ms = bool(self.cfg["show_ms"])
        self.bar.elapsed.setText(fmt_time(self.position, ms))
        if self.cfg["time_right"] == "total":
            self.bar.remaining.setText(fmt_time(self.duration, ms))
        else:
            self.bar.remaining.setText("-" + fmt_time(self.duration - self.position, ms))

    @staticmethod
    def _keep_awake(on):
        """While a video plays, stop Windows from starting the screensaver or sleeping. mpv only does this for
        windows it creates itself; Iron Will draws mpv into its own window, so it has to ask Windows directly."""
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED if on else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags))

    def _update_awake(self):
        """Options > Player > Window > Keep the PC awake: by default whenever Iron Will is on screen (not minimized),
        playing or paused; or only while a video plays; or never."""
        mode = self.cfg["keep_awake"]
        on_screen = self.isVisible() and not self.isMinimized()
        playing = bool(self.engine.path) and not self.paused
        self._keep_awake(on_screen and (mode == "visible" or (mode == "playing" and playing)))

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.Type.WindowStateChange:  # minimized / restored
            self._update_awake()
            if self.isMinimized():
                if self.cfg["pause_minimized"] and self.engine.path and not self.paused:
                    self.engine.mpv.pause = True
                    self.paused_by_minimize = True
                if self.cfg["tray_icon"] and self.tray is not None:
                    QTimer.singleShot(0, self.hide)
            elif getattr(self, "paused_by_minimize", False):
                self.paused_by_minimize = False
                self.engine.mpv.pause = False
        elif e.type() == QEvent.Type.ActivationChange and not self.isActiveWindow():
            if self.cfg["exit_fs_focus"] and self.isFullScreen():
                self.exit_fullscreen()

    def event(self, e):
        # Qt replaces the native window when the OpenGL video surface first appears (and on some view changes).
        # The new window starts without the on-top flag, dark title bar and outline settings, so re-apply them.
        if e.type() == QEvent.Type.WinIdChange and self.isVisible():
            QTimer.singleShot(0, self._reapply_native)
        return super().event(e)

    def _reapply_native(self):
        if not self.isVisible():
            return
        try:
            val = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 20, ctypes.byref(val), 4)
        except Exception:
            pass
        self._dwm_outline()
        if self.mini_geometry is None:
            self._set_topmost(self._topmost_wanted())
        else:
            self._set_topmost(True)  # mini view always floats

    def _on_pause(self, paused):
        self.paused = paused
        self._update_awake()
        self.bar.play.set_glyph(Glyph.PLAY if paused else Glyph.PAUSE)
        self.bar.play.setToolTip("Play (Space)" if paused else "Pause (Space)")
        # Pausing shows the controls, then they fade like they do while playing (mouse movement brings them back).
        self.show_chrome()
        if self.cfg["on_top"] == "playing" and self.mini_geometry is None:
            self._set_topmost(self._topmost_wanted())

    def _on_volume(self, v):
        muted = bool(self.engine.mpv.mute)
        self.bar.volume.set_glyph(volume_glyph(v, muted))
        self.flyout.set_volume(v, muted)
        self.settings.setValue("volume", v)
        self.settings.setValue("mute", muted)

    def _on_loaded(self, path):
        self.loaded_ok = path == self.engine.path
        self._update_neighbors()
        if not self.loaded_ok:
            return
        self._enforce_languages()
        self._external_tracks()
        self._restore_tracks()
        self._apply_video_zoom()
        try:
            chapters = [c.get("time", 0) for c in (self.engine.mpv._get_property("chapter-list") or [])]
        except Exception:
            chapters = []
        self.bar.seek.set_chapters(chapters if self.cfg["chapter_marks"] else [])
        if self.cfg["auto_fit"] != "off" and not (self.isFullScreen() or self.isMaximized() or self.mini_geometry):
            QTimer.singleShot(150, lambda: self.fit_to_video(self.cfg["auto_fit"]))
        if self.cfg["osd_filename"]:
            self.toast.show_message(Path(path).name)

    def _save_tracks(self, kind, track_id):
        if not (self.cfg["remember_tracks"] and self.engine.path and kind in ("audio", "sub")):
            return
        saved = dict(self.settings.value("tracks", {}) or {})
        entry = dict(saved.get(self.engine.path.lower(), {}))
        entry[kind] = track_id if track_id is not None else "no"
        saved[self.engine.path.lower()] = entry
        if len(saved) > 500:
            saved = dict(list(saved.items())[-500:])
        self.settings.setValue("tracks", saved)

    def _restore_tracks(self):
        if not self.cfg["remember_tracks"]:
            return
        entry = (self.settings.value("tracks", {}) or {}).get(self.engine.path.lower())
        for kind, track_id in (entry or {}).items():
            ids = {t["id"] for t in self.engine.tracks(kind)}
            if track_id == "no" and kind == "sub":
                self.engine.select_track(kind, None, remember=False)
            elif track_id in ids:
                self.engine.select_track(kind, track_id, remember=False)

    def _enforce_languages(self):
        """mpv already prefers the chosen language by track tag (alang/slang). This is the backup for files whose
        tracks aren't tagged properly but say "English" (or "Japanese", ...) in the track title."""
        for kind, key in (("audio", "audio_lang"), ("sub", "sub_lang")):
            codes, pattern = LANGUAGES.get(self.cfg[key], ("", ""))
            tracks = self.engine.tracks(kind)
            if not codes or len(tracks) < 2:
                continue
            selected = next((t for t in tracks if t.get("selected")), None)
            if kind == "sub" and selected is None:
                continue  # subtitles are off: leave them off

            def matches(t):
                lang = (t.get("lang") or "").lower()
                return lang in codes.split(",") or bool(re.search(pattern, (t.get("title") or "").lower()))

            if selected is not None and matches(selected):
                continue
            want = next((t for t in tracks if matches(t)), None)
            if want:
                self.engine.select_track(kind, want["id"], remember=False)
                log("language preference: switched", kind, "to track", want["id"])

    def _loop_dragged(self, a, b):
        self.loop = {"a": a if a >= 0 else None, "b": b if b >= 0 else None}
        self._sync_ab()
        self._save_loop()
        parts = [f"{k.upper()} {fmt_time(v)}" for k, v in self.loop.items() if v is not None]
        self.toast.show_message("   ·   ".join(parts))

    # Minimize / maximize / close for borderless and full screen: revealed by the top-right corner -----------
    def _update_caption(self, global_pos):
        if not (self.isFullScreen() or self.borderless):
            if self.caption.isVisible():
                self.caption_anim.stop()
                self.caption.hide()
            return
        p = self.stage.mapFromGlobal(global_pos)
        in_corner = p.x() >= self.stage.width() - 280 and 0 <= p.y() <= 90
        if in_corner:
            self.caption_timer.stop()
            self._fade_caption(True)
        elif self.caption.isVisible() and not self.caption_timer.isActive():
            self.caption_timer.start()

    def _fade_caption(self, show):
        if show:
            self.caption.set_mode(self.isFullScreen(), self.isMaximized())
            if not self.caption.isVisible():
                self.caption.show()
                self.caption.raise_()
        target = 1.0 if show else 0.0
        if self.caption_anim.endValue() == target and self.caption_anim.state() == QVariantAnimation.State.Running:
            return
        if abs(self.caption_fx.opacity() - target) < 0.01 and (show or not self.caption.isVisible()):
            return
        self.caption_anim.stop()
        self.caption_anim.setStartValue(self.caption_fx.opacity())
        self.caption_anim.setEndValue(target)
        self.caption_anim.start()

    def _update_orb(self, global_pos):
        p = self.stage.mapFromGlobal(global_pos)
        inside = 0 <= p.x() <= self.stage.width() and 0 <= p.y() <= self.stage.height()
        self._drop_orb(bool(self.engine.path) and inside and p.y() <= self.stage.height() / 4)

    def _drop_orb(self, show):
        target = 1.0 if show else 0.0
        if self.orb_anim.endValue() == target and self.orb_anim.state() == QVariantAnimation.State.Running:
            return
        if abs(self.orb_shown - target) < 0.01:
            return
        self.orb_anim.stop()
        self.orb_anim.setStartValue(self.orb_shown)
        self.orb_anim.setEndValue(target)
        self.orb_anim.start()

    def _place_orb(self, v):
        self.orb_shown = float(v)
        size = self.close_orb.height()
        y = int(-size + self.orb_shown * (size + 16))  # slides from above the window to 16 px below its top
        self.close_orb.move((self.stage.width() - self.close_orb.width()) // 2, y)
        self.close_orb.setVisible(self.orb_shown > 0.01)
        self.close_orb.raise_()

    def _caption_restore(self):
        if self.isFullScreen():
            self.exit_fullscreen()
        elif self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self.caption.set_mode(self.isFullScreen(), self.isMaximized())

    def _clear_loop_from_timeline(self):
        self.loop = {"a": None, "b": None}
        self._sync_ab()
        self._save_loop()
        self.toast.show_message("A-B loop cleared")

    # A-B loops are remembered per file, so reopening a file brings its loop back ------------------------------
    def _save_loop(self):
        if not self.engine.path:
            return
        loops = dict(self.settings.value("ab_loops", {}) or {})
        key = self.engine.path.lower()
        if self.loop["a"] is None and self.loop["b"] is None:
            loops.pop(key, None)
        else:
            loops[key] = [-1.0 if self.loop["a"] is None else self.loop["a"],
                          -1.0 if self.loop["b"] is None else self.loop["b"]]
        self.settings.setValue("ab_loops", loops)

    def _restore_loop(self, path):
        saved = (dict(self.settings.value("ab_loops", {}) or {})).get(str(path).lower())
        if not saved:
            return
        a, b = (float(x) for x in saved)
        self.loop = {"a": a if a >= 0 else None, "b": b if b >= 0 else None}
        self._sync_ab()
        parts = [f"{k.upper()} {fmt_time(v)}" for k, v in self.loop.items() if v is not None]
        self.toast.show_message("A-B loop restored:  " + "   ·   ".join(parts))

    def _sync_ab(self):
        """Translate the A-B markers into mpv settings.

        Both set: loop A→B.  Only B: crossing B jumps to the very start (this mpv build only loops when both
        points exist, so the start is passed as A).  Only A: mpv isn't told; _on_end handles it (back to A with
        repeat on, otherwise on to the next file with the marker dropped)."""
        a, b = self.loop["a"], self.loop["b"]
        m = self.engine.mpv
        repeat = self.cfg["loop_file"] == "inf"
        a_only = a is not None and b is None
        try:
            m["ab-loop-a"] = (a if a is not None else 0.0) if b is not None else "no"
            m["ab-loop-b"] = b if b is not None else "no"
            # With only A + repeat, the end must reach _on_end; plain loop-file would restart at 0:00 instead.
            m["loop-file"] = "no" if a_only and repeat else self.cfg["loop_file"]
        except Exception as exc:
            log("A-B sync failed:", exc)
        self.bar.seek.set_loop_marker("a", a)
        self.bar.seek.set_loop_marker("b", b)

    def _on_end(self):
        if self.engine.path:
            self.resume.forget(self.engine.path)  # finished: next time it starts fresh
        if self.loop["a"] is not None and self.loop["b"] is None and self.cfg["loop_file"] == "inf":
            self.engine.seek(self.loop["a"])  # only A + repeat: back to A, keep playing
            self.engine.mpv.pause = False
            return
        if self.loop["a"] is not None or self.loop["b"] is not None:
            self.loop = {"a": None, "b": None}  # an A marker without repeat ends with the file
            self._sync_ab()
        if self.cfg["loop_file"] == "inf":
            return
        if self.after_once != "nothing":  # After Playback > Once: exit, shut down, lock...
            QTimer.singleShot(200, self._run_after_once)
            return
        every = self.cfg["after_playback"]
        nxt = None
        if self.engine.path and every in ("next", "next_loop"):
            spec = self.folder_sort(Path(self.engine.path).parent)
            nxt = playlist.neighbor(self.engine.path, 1, spec)
            if nxt is None and every == "next_loop":  # after the last episode, start the folder over
                files = playlist.siblings(self.engine.path, spec)
                nxt = files[0] if files else None
        if nxt:
            QTimer.singleShot(400, lambda: self.open_path(nxt, browsing=True))
        elif every == "exit":
            QTimer.singleShot(400, self.close)
        elif every == "rewind":
            self.engine.seek(0)
            self.engine.mpv.pause = True
            self.show_chrome(stay=True)
        elif every == "close_minimize":
            QTimer.singleShot(400, lambda: (self.stop(), self.showMinimized()))
        elif every == "close":
            QTimer.singleShot(400, self.stop)
        else:
            if self.cfg["exit_fs_at_end"]:
                self.exit_fullscreen()
            self.show_chrome(stay=True)

    # Volume / speed / frame --------------------------------------------------------------------------------
    def nudge_volume(self, delta):
        self.engine.set_volume(self.engine.volume + delta)
        self.toast.show_message(f"Volume {int(round(self.engine.volume))}")

    def set_speed(self, s):
        s = round(min(4.0, max(0.1, s)), 2)
        self.engine.set_speed(s)
        self.toast.show_message(f"Speed {s * 100:.0f}%")

    def step_speed(self, direction):
        """Increase / Decrease Rate: whole steps of the chosen percentage (5% by default: 100, 105, 110...)."""
        step = int(self.cfg["speed_step"])
        cur = round(float(self.engine.mpv.speed or 1.0) * 100)
        # Snap onto the step grid: 103% goes up to 105% or down to 100%.
        nxt = (cur // step + 1) * step if direction > 0 else (-(-cur // step) - 1) * step
        self.set_speed(nxt / 100)

    def _speed_menu(self, anchor):
        from . import menus
        m = dark_menu(self)
        menus.fill_qt(m, menus.sections(self)["speed"], dark_menu)
        self._popup(m, anchor)

    def go_to_time(self):
        """Go To… (Ctrl+G): jump to an exact time, typed as 1:23:45, 23:45 or seconds."""
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Go To", "Time (h:mm:ss, m:ss or seconds):", text=fmt_time(self.position))
        if not ok or not text.strip():
            return
        try:
            secs = 0.0
            for part in text.strip().split(":"):
                secs = secs * 60 + float(part)
        except ValueError:
            self.toast.show_message("That isn't a time")
            return
        self.engine.seek(min(max(0.0, secs), max(0.0, self.duration - 0.5)))

    def save_frame(self):
        if self.engine.path:
            folder = self.engine.screenshot(self.cfg["shot_dir"], self.cfg["shot_subs"])
            self.toast.show_message(f"Frame saved to {folder.name}")

    def _show_flyout(self):
        b = self.bar.volume
        pos = b.mapToGlobal(QPoint(0, -self.flyout.height() - 8))
        self.flyout.set_volume(self.engine.volume, bool(self.engine.mpv.mute))
        self.flyout.move(pos)
        self.flyout.show()

    # Menus ---------------------------------------------------------------------------------------------------
    def _popup(self, menu, anchor):
        self.hide_timer.stop()
        size = menu.sizeHint()
        pt = anchor.mapToGlobal(QPoint(anchor.width() - size.width(), -size.height() - 6))
        if anchor.mapTo(self, QPoint(0, 0)).x() < self.width() / 2:  # left-side buttons open to the right
            pt = anchor.mapToGlobal(QPoint(0, -size.height() - 6))
        menu.exec(pt)
        self.hide_timer.start()

    def _track_items(self, menu, kind, allow_off):
        tracks = self.engine.tracks(kind)
        selected = next((t["id"] for t in tracks if t.get("selected")), None)
        if allow_off:
            a = menu.addAction("Off")
            a.setCheckable(True)
            a.setChecked(selected is None)
            a.triggered.connect(lambda: self.engine.select_track(kind, None))
        for t in tracks:
            bits = [t.get("title") or "", (t.get("lang") or "").upper(), t.get("codec") or ""]
            label = " · ".join(b for b in bits if b) or f"Track {t['id']}"
            a = menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(t["id"] == selected)
            a.triggered.connect(lambda _c=False, i=t["id"]: self.engine.select_track(kind, i))
        if not tracks:
            menu.addAction("None in this file").setEnabled(False)

    def _tracks_menu(self):
        m = dark_menu(self)
        m.addSection("Subtitles")
        self._track_items(m, "sub", True)
        m.addAction("Add subtitle file…", self._add_subs)
        m.addSeparator()
        audio = dark_menu(m, "Audio track")
        self._track_items(audio, "audio", False)
        m.addMenu(audio)
        return m

    def _add_subs(self):
        start = str(Path(self.engine.path).parent) if self.engine.path else ""
        path, _ = QFileDialog.getOpenFileName(self, "Add subtitles", start,
                                              "Subtitles (" + " ".join("*" + e for e in SUB_EXTS) + ")")
        if path:
            self.open_path(path)

    def _more_menu(self):
        m = dark_menu(self)
        m.addAction(self.act_open)
        loaded = bool(self.engine.path)
        speed = dark_menu(m, "Playback speed")
        cur = float(self.engine.mpv.speed or 1.0)
        for s in SPEEDS:
            a = speed.addAction("Normal" if s == 1.0 else f"{s:g}x")
            a.setCheckable(True)
            a.setChecked(abs(s - cur) < 1e-6)
            a.triggered.connect(lambda _c=False, s=s: self.set_speed(s))
        aspect = dark_menu(m, "Aspect ratio")
        cur_a = str(self.engine.mpv["video-aspect-override"])
        for label, val in ASPECTS:
            a = aspect.addAction(label)
            a.setCheckable(True)
            a.setChecked(cur_a == val or (val == "no" and cur_a in ("no", "-1", "")))
            a.triggered.connect(lambda _c=False, v=val, l=label: (self.engine.set_aspect(v),
                                                                    self.toast.show_message(f"Aspect {l}")))
        for sub in (speed, aspect):
            sub.setEnabled(loaded)
            m.addMenu(sub)
        self.act_shot.setEnabled(loaded)
        m.addAction(self.act_shot)
        m.addSeparator()
        m.addAction(self.act_options)
        return m

    # Chrome visibility -----------------------------------------------------------------------------------
    def show_chrome(self, stay=False):
        self.video.unsetCursor()
        if self.isFullScreen() and not self.cfg["fs_controls"] and not stay and not self.paused and self.engine.path:
            self.hide_timer.start()  # full screen without controls: just show the pointer for a moment
            return
        if not self.chrome_visible:
            self.chrome_visible = True
            self.bar.setVisible(bool(self.engine.path))
            self._update_neighbors()
            self._animate(1.0)
        self.hide_timer.stop()
        if not stay:
            self.hide_timer.start()

    def hide_chrome(self):
        log("hide_chrome path=%s paused=%s flyout=%s" % (bool(self.engine.path), self.paused, self.flyout.isVisible()))
        if not self.engine.path or self.flyout.isVisible() or self.prompt.isVisible():
            return
        for w in (self.bar, self.caption):
            if w.isVisible() and w.rect().contains(w.mapFromGlobal(self.cursor().pos())):
                self.hide_timer.start()
                return
        self.chrome_visible = False
        self._animate(0.0)
        self._drop_orb(False)
        if self.isFullScreen() or self.cfg["hide_cursor_window"]:
            self.video.setCursor(Qt.CursorShape.BlankCursor)

    def _animate(self, target):
        self.fade.stop()
        current = next(iter(self.effects.values())).opacity()
        self.fade.setStartValue(current)
        self.fade.setEndValue(target)
        self.fade.start()

    def _fade_done(self):
        if not self.chrome_visible:
            for w in self.chrome:
                w.hide()

    # Window modes ------------------------------------------------------------------------------------------
    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.exit_fullscreen()
        else:
            if self.mini_geometry:
                self.toggle_mini()
            self.was_maximized = self.isMaximized()
            self.menuBar().setVisible(False)  # full screen is just the video
            target = self._fullscreen_screen()
            if target is not None and target is not self.screen():
                if self.was_maximized:
                    self.showNormal()
                self.windowHandle().setScreen(target)
                self.move(target.geometry().topLeft())
            self.showFullScreen()
            self.bar.full.set_glyph(Glyph.WINDOW)
            self._update_clock()
            if self.cfg["fs_refresh"]:
                QTimer.singleShot(200, self._match_refresh)
            self._dwm_outline()

    def _fullscreen_screen(self):
        mode = self.cfg["fs_monitor"]
        screens = QGuiApplication.screens()
        if mode == "primary":
            return QGuiApplication.primaryScreen()
        if mode.isdigit() and int(mode) <= len(screens):
            return screens[int(mode) - 1]
        return None

    def exit_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized() if self.was_maximized else self.showNormal()
            self.menuBar().setVisible(bool(self.cfg["show_menubar"]))
            self.bar.full.set_glyph(Glyph.FULL)
            self._dwm_outline()
            self.caption.hide()
            self._update_clock()
            display.restore()
            self._sync_border()  # the border setting may have changed while in full screen

    def toggle_mini(self):
        hwnd = int(self.winId())
        user32 = ctypes.windll.user32
        if self.mini_geometry is None:
            if self.isFullScreen():
                self.exit_fullscreen()
            self.mini_geometry = self.saveGeometry()
            self.showNormal()
            area = self.screen().availableGeometry()
            w, h = {"small": (400, 225), "large": (720, 405)}.get(self.cfg["mini_size"], (560, 315))
            self.setGeometry(area.right() - w - 24, area.bottom() - h - 24, w, h)
            set_topmost(hwnd, True)
            self.bar.title.hide()
            self._layout()
        else:
            set_topmost(hwnd, False)
            self.restoreGeometry(self.mini_geometry)
            self.mini_geometry = None
            self.bar.title.show()
            self._layout()
            self._set_topmost(self._topmost_wanted())

    # Qt events ---------------------------------------------------------------------------------------------
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout()

    def _layout(self):
        w, h = self.stage.width(), self.stage.height()
        self.video.setGeometry(0, 0, w, h)
        self.welcome.setGeometry(0, 0, w, h)
        # Room for whatever the bar shows (title, seek bar, buttons) plus the fade above it.
        gap = int(self.cfg["controls_gap"])
        self.bar.layout().setContentsMargins(22, 0, 22, gap)
        bar_h = gap + (52 if self.bar.title.isVisibleTo(self.bar) else 0) + (72 if self.bar.seek.isVisibleTo(self.bar) else 0) \
            + (54 if self.bar.play.isVisibleTo(self.bar) else 0) + 20
        self.bar.setGeometry(0, h - bar_h, w, bar_h)
        self.caption.move(w - self.caption.width(), 0)
        if self.clock is not None:
            self.clock.adjustSize()
            self.clock.move(w - self.clock.width() - 24, 18)
        self._place_orb(self.orb_shown)
        self.prompt.move((w - self.prompt.width()) // 2, (h - self.prompt.height()) // 2)
        self.prev_btn.move(6, (h - self.prev_btn.height()) // 2)  # vertically centred on the video
        self.next_btn.move(w - self.next_btn.width() - 6, (h - self.next_btn.height()) // 2)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.Resize and obj is self.stage:
            # The video area can change size without the window resizing (menu bar shown/hidden, border on/off):
            # re-fit the video and controls to it every time, or they'd sit short with a black strip below.
            QTimer.singleShot(0, self._layout)
        if self.borderless and t in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress) and \
                isinstance(obj, QWidget) and obj.window() is self:
            # Borderless: the outer 6 px act as the frame. Show resize arrows there; dragging resizes.
            edges = self._resize_edges(ev.globalPosition().toPoint())
            if t == QEvent.Type.MouseButtonPress and edges and ev.button() == Qt.MouseButton.LeftButton:
                self.windowHandle().startSystemResize(edges)
                return True
            if t == QEvent.Type.MouseMove and not ev.buttons():
                shape = self._edge_shape(edges)
                if shape is not None and not self.edge_cursor:
                    QApplication.setOverrideCursor(shape)
                    self.edge_cursor = True
                elif shape is not None:
                    QApplication.changeOverrideCursor(shape)
                elif self.edge_cursor:
                    QApplication.restoreOverrideCursor()
                    self.edge_cursor = False
        if t == QEvent.Type.MouseMove:
            # Hiding widgets makes Qt send a synthetic move with the cursor standing still; only real
            # movement should bring the controls back.
            pos = ev.globalPosition().toPoint()
            # Drag-to-move is checked on every move the video gets: the same movement reaches the window first,
            # so the "only real movement" check below would otherwise swallow it before the video sees it.
            if obj is self.video and self.press_pos is not None and ev.buttons() & Qt.MouseButton.LeftButton:
                self._maybe_drag_window(pos)
            if pos != self.last_mouse:
                self.last_mouse = pos
                log("mousemove", type(obj).__name__)
                self.show_chrome()
                self._update_caption(pos)
                self._update_orb(pos)
        elif obj is self.video:
            handled = self._video_mouse(t, ev)
            if handled:
                return True
        return super().eventFilter(obj, ev)

    # Mouse over the video (MPC-BE-style bindings) ------------------------------------------------------
    def _slot(self, gesture, ev):
        """Pick the command for a gesture: right-button-held, Ctrl and Shift columns override Normal."""
        slots = self.cfg["mouse"].get(gesture, ["none"] * 4)
        mods = ev.modifiers()
        if self.right_down:
            self.right_used = True  # a combo happened, so releasing the right button won't open the menu
            if slots[3] != "none":
                return slots[3]
        if mods & Qt.KeyboardModifier.ControlModifier and slots[1] != "none":
            return slots[1]
        if mods & Qt.KeyboardModifier.ShiftModifier and slots[2] != "none":
            return slots[2]
        return slots[0]

    def _video_mouse(self, t, ev):
        Btn, E = Qt.MouseButton, QEvent.Type
        if t == E.MouseButtonPress:
            b = ev.button()
            if b == Btn.LeftButton:
                self.press_pos = ev.globalPosition().toPoint()
                third = ev.position().x() / max(1, self.video.width())
                self.press_zone = "back" if third < 1 / 3 else "fwd" if third > 2 / 3 else None
                if self.cfg["longpress"] and self.engine.path and self.press_zone and \
                        (self.press_zone == "back" or not self.paused):
                    self.longpress_timer.start(int(self.cfg["longpress_delay"]))
            elif b == Btn.RightButton:
                self.right_down, self.right_used = True, False
            elif b == Btn.MiddleButton:
                self.run_command(self._slot("middle", ev))
            elif b == Btn.BackButton:
                self.run_command(self._slot("x1", ev))
            elif b == Btn.ForwardButton:
                self.run_command(self._slot("x2", ev))
            return True
        if t == E.MouseButtonRelease:
            b = ev.button()
            if b == Btn.LeftButton:
                self.longpress_timer.stop()
                if self.boost_speed is not None or self.rewinding:  # end of a hold (fast-forward / rewind): not a click
                    self._end_hold()
                elif self.press_pos is not None:
                    self.run_command(self._slot("left_click", ev))
                self.press_pos = None
            elif b == Btn.RightButton:
                self.right_down = False
                if not self.right_used:
                    self.show_context_menu(ev.globalPosition().toPoint())
            return True
        if t == E.MouseButtonDblClick:
            if ev.button() == Btn.LeftButton:
                first, dbl = self._slot("left_click", ev), self._slot("left_dbl", ev)
                if dbl != "none":
                    if first == "play_pause" and not self.prompt.isVisible():
                        self.engine.toggle_pause()  # undo the single click that came first
                    self.run_command(dbl)
                self.press_pos = None  # the release that follows is not another click
                self.longpress_timer.stop()
            elif ev.button() in (Btn.MiddleButton, Btn.BackButton, Btn.ForwardButton):
                return self._video_mouse(E.MouseButtonPress, ev)  # fast repeat presses count as presses
            return True
        if t == E.Wheel:
            d = ev.angleDelta()
            self.wheel_acc[0] += d.y()
            self.wheel_acc[1] += d.x()
            while abs(self.wheel_acc[0]) >= 120:
                step = 120 if self.wheel_acc[0] > 0 else -120
                self.wheel_acc[0] -= step
                self.run_command(self._slot("wheel_up" if step > 0 else "wheel_down", ev))
            while abs(self.wheel_acc[1]) >= 120:
                step = 120 if self.wheel_acc[1] > 0 else -120
                self.wheel_acc[1] -= step
                self.run_command(self._slot("wheel_left" if step > 0 else "wheel_right", ev))
            return True
        return False

    def _maybe_drag_window(self, pos):
        if not self.cfg["easy_move"] or self.isFullScreen() or self.isMaximized():
            return
        if (pos - self.press_pos).manhattanLength() > 8:
            self.longpress_timer.stop()
            if self.boost_speed is not None or self.rewinding:  # held long enough for a hold action, then moved: a drag
                self._end_hold(quiet=True)
            self.press_pos = None  # a drag, not a click
            handle = self.windowHandle()
            if handle:
                handle.startSystemMove()

    def _start_boost(self):
        """Click and hold: right third of the video fast-forwards, left third rewinds."""
        if self.press_pos is None or not self.engine.path or not self.press_zone:
            return
        rate = float(self.cfg["longpress_speed"])
        if self.press_zone == "back":
            # mpv can't play backwards smoothly, so rewind is quick exact jumps back while the video holds still.
            self.rewinding = True
            self.rewind_was_paused = self.paused
            self.rewind_target = self.position
            self.engine.mpv.pause = True
            self.rewind_timer.start()
            self.toast.show_message(f"◀◀  {rate:g}x")
            return
        self.boost_speed = float(self.engine.mpv.speed or 1.0)
        rate = float(self.cfg["longpress_speed"])
        self.engine.set_speed(rate)
        self.toast.show_message(f"▶▶  {rate:g}x")

    def _rewind_tick(self):
        # Step a tracked target back and seek exactly there (relative seeks stack up and overshoot).
        rate = float(self.cfg["longpress_speed"])
        self.rewind_target = max(0.0, self.rewind_target - rate * self.rewind_timer.interval() / 1000)
        self.engine.seek(self.rewind_target)
        if self.rewind_target <= 0.0:
            self._end_hold()
            self.press_pos = None  # the hold ended by itself: letting go now isn't a click

    def _end_hold(self, quiet=False):
        if self.boost_speed is not None:
            self.engine.set_speed(self.boost_speed)
            self.boost_speed = None
            if not quiet:
                self.toast.show_message(f"Speed {float(self.engine.mpv.speed) * 100:.0f}%")
        if self.rewinding:
            self.rewind_timer.stop()
            self.rewinding = False
            self.engine.mpv.pause = self.rewind_was_paused
            if not quiet:
                self.toast.show_message(f"◀◀  {fmt_time(self.position)}")

    def show_context_menu(self, global_pos):
        """Right-click: the full Iron Will menu straight away, like mpv's (the title-bar menu has the same)."""
        from . import menus
        self.hide_timer.stop()
        menu = dark_menu(self)
        menus.fill_qt(menu, menus.build(self), dark_menu)
        menu.exec(global_pos)
        self.hide_timer.start()

    def set_pref(self, key, value):
        """Change one setting from a menu or mouse command, save it and apply it."""
        self.cfg.values[key] = value
        self.cfg.save()
        apply_to_mpv(self.engine.mpv, self.cfg.values, only=[key])
        self.apply_settings()

    def run_command(self, cid):
        e, m, c = self.engine, self.engine.mpv, self.cfg

        def prop(name, default=0.0):
            try:
                v = m._get_property(name)
                return default if v is None else v
            except Exception:
                return default

        def add(name, delta, label=None, fmt="{:+.2f}"):
            v = round(float(prop(name)) + delta, 3)
            m._set_property(name, v)
            if label:
                self.toast.show_message(f"{label} {fmt.format(v)}")

        def ab(which):
            """Each marker is a toggle: first press sets it at the current time, the next press removes it."""
            if not e.path:
                return
            if self.loop[which] is not None:
                self.loop[which] = None
                self.toast.show_message(f"Loop {which.upper()} removed")
            else:
                self.loop[which] = float(prop("time-pos"))
                self.toast.show_message(f"Loop {which.upper()} set at {fmt_time(self.loop[which])}")
            self._sync_ab()
            self._save_loop()

        def ab_clear():
            self.loop = {"a": None, "b": None}
            self._sync_ab()
            self._save_loop()
            self.toast.show_message("A-B loop cleared")

        def sub_toggle():
            if prop("sid", False):
                e.select_track("sub", None)
                self.toast.show_message("Subtitles off")
            elif e.tracks("sub"):
                e.select_track("sub", e.tracks("sub")[0]["id"])
                self.toast.show_message("Subtitles on")

        loaded_only = {"play_pause", "stop", "seek_back", "seek_fwd", "skip_back", "skip_fwd", "frame_prev",
                       "frame_next", "ab_a", "ab_b", "ab_clear", "sub_toggle", "sub_next", "audio_next",
                       "screenshot", "zoom_in", "zoom_out", "view_reset", "pan_left", "pan_right", "pan_up",
                       "pan_down", "speed_up", "speed_down", "speed_reset"}
        if cid in loaded_only and not e.path:
            return
        actions = {
            "none": lambda: None,
            "play_pause": self.play_pause,
            "stop": self.stop,
            "fullscreen": self.toggle_fullscreen,
            "mini": self.toggle_mini,
            "menu": lambda: self.show_context_menu(QCursor.pos()),
            "volume_up": lambda: self.nudge_volume(c["volume_step"]),
            "volume_down": lambda: self.nudge_volume(-c["volume_step"]),
            "mute": e.toggle_mute,
            "seek_back": lambda: e.skip(-c["arrow_step"]),
            "seek_fwd": lambda: e.skip(c["arrow_step"]),
            "skip_back": lambda: e.skip(-c["skip_back"]),
            "skip_fwd": lambda: e.skip(c["skip_fwd"]),
            "frame_prev": lambda: e.frame_step(False),
            "frame_next": lambda: e.frame_step(True),
            "prev_file": lambda: self.play_neighbor(-1),
            "next_file": lambda: self.play_neighbor(1),
            "speed_down": lambda: self.step_speed(-1),
            "speed_up": lambda: self.step_speed(1),
            "speed_reset": lambda: self.set_speed(1.0),
            "repeat_toggle": lambda: (self.set_pref("loop_file", "no" if c["loop_file"] == "inf" else "inf"),
                                      self.toast.show_message("Repeat " + ("on" if c["loop_file"] == "inf"
                                                                           else "off"))),
            "ab_a": lambda: ab("a"),
            "ab_b": lambda: ab("b"),
            "ab_clear": ab_clear,
            "zoom_in": lambda: add("video-zoom", 0.1, "Zoom"),
            "zoom_out": lambda: add("video-zoom", -0.1, "Zoom"),
            "view_reset": lambda: ([m._set_property(p, 0) for p in ("video-zoom", "video-pan-x", "video-pan-y")],
                                   self.toast.show_message("View reset")),
            "pan_left": lambda: add("video-pan-x", -0.02),
            "pan_right": lambda: add("video-pan-x", 0.02),
            "pan_up": lambda: add("video-pan-y", -0.02),
            "pan_down": lambda: add("video-pan-y", 0.02),
            "sub_toggle": sub_toggle,
            "sub_next": lambda: m.command("cycle", "sub"),
            "audio_next": lambda: m.command("cycle", "audio"),
            "screenshot": self.save_frame,
            "options": self.open_options,
        }
        try:
            actions.get(cid, lambda: None)()
        except Exception as exc:
            log("mouse command failed:", cid, exc)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if files:
            self.open_path(files[0])
            self.activateWindow()

    def showEvent(self, e):
        super().showEvent(e)
        self._update_awake()
        try:  # dark title bar on Windows 10/11
            val = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 20, ctypes.byref(val), 4)
        except Exception:
            pass
        self._dwm_outline()
        if self.mini_geometry is None:
            self._set_topmost(self._topmost_wanted())
        if self.sysmenu is None:  # "Iron Will" submenu in the title-bar menu (right-click title bar / Alt+Space)
            from .menus import SystemMenu
            self.sysmenu = SystemMenu(self)
            self.sysmenu.rebuild()
        self._layout()

    def closeEvent(self, e):
        self._keep_awake(False)
        self._remember_position(force=True)
        if self.mini_geometry is not None:
            self.toggle_mini()
        if not self.isFullScreen():
            self.settings.setValue("geometry", self.saveGeometry())
        self.video.shutdown()
        self.engine.shutdown()
        super().closeEvent(e)
