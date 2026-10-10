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
                           QRadialGradient)
from PySide6.QtWidgets import (QFileDialog, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QVBoxLayout, QWidget, QApplication, QPushButton)

from .. import playlist
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
    "size_small": "prop:System.Size;", "size_large": "prop:-System.Size;",
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

    def resizeEvent(self, e):
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
        if geo is not None and self.cfg["remember_geometry"]:
            self.restoreGeometry(geo)
        else:
            self.resize(1280, 760)
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
        if scale is None:  # Auto Fit: as big as fits in 75% of the screen, keeping the video's shape
            scale = min(area.width() * 0.75 * ratio / w, area.height() * 0.75 * ratio / h)
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
        if bytes(event_type) == b"windows_generic_MSG" and self.sysmenu:
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if self.sysmenu.handle(msg):
                return True, 0
        return super().nativeEvent(event_type, message)

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
        self.bar.title.setStyleSheet(f"color: {c['title_color'] or '#FFFFFF'};")
        if self.mini_geometry is None:
            self._set_topmost(self._topmost_wanted())
        self.menuBar().setVisible(bool(c["show_menubar"]) and not self.isFullScreen())
        self._layout()
        self._update_neighbors()
        self._sync_ab()  # repeat on/off changes what an A-only marker does
        self._sync_border()

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

    def _set_topmost(self, on):
        flag = -1 if on else -2  # HWND_TOPMOST / HWND_NOTOPMOST
        ctypes.windll.user32.SetWindowPos(int(self.winId()), flag, 0, 0, 0, 0, 0x0001 | 0x0002)

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
        return [p for p in (self.settings.value("recent", []) or []) if Path(p).exists()][:15]

    def _add_recent(self, path):
        items = [str(path)] + [p for p in (self.settings.value("recent", []) or []) if p.lower() != str(path).lower()]
        self.settings.setValue("recent", items[:20])

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
        c, m = self.cfg, self.engine.mpv
        zoom = float(m._get_property("video-zoom") or 0)
        if c["unscaled"] == "yes":
            return "half" if zoom <= -0.99 else "double" if zoom >= 0.99 else "normal"
        if not c["keepaspect"]:
            return "stretch"
        return "outside" if float(c["panscan"]) >= 0.99 else "inside"

    def set_video_frame(self, mode):
        """MPC-BE's Video Frame modes, mapped to mpv's scaling options."""
        prefs = {"inside": {"keepaspect": True, "unscaled": "no", "panscan": 0.0},
                 "outside": {"keepaspect": True, "unscaled": "no", "panscan": 1.0},
                 "stretch": {"keepaspect": False, "unscaled": "no", "panscan": 0.0},
                 "normal": {"keepaspect": True, "unscaled": "yes", "panscan": 0.0},
                 "half": {"keepaspect": True, "unscaled": "yes", "panscan": 0.0},
                 "double": {"keepaspect": True, "unscaled": "yes", "panscan": 0.0}}[mode]
        self.set_prefs(prefs)
        self.engine.mpv._set_property("video-zoom", {"half": -1.0, "double": 1.0}.get(mode, 0.0))

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
        if fav.get("pos"):
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

    def open_path(self, path):
        path = Path(path)
        if path.suffix.lower() in SUB_EXTS and self.engine.path:
            self.engine.mpv.command("sub-add", str(path), "select")
            self.toast.show_message(f"Subtitles: {path.name}")
            return
        self.settings.setValue("last_dir", str(path.parent))
        self.folder_sort(path.parent)  # read Explorer's sort for this folder now, while it's likely open
        self._add_recent(path)
        self._remember_position(force=True)  # the file we're leaving
        self.prompt.hide()
        self.loaded_ok = False
        saved = self.resume.get(path)
        mode = self.cfg["resume"]
        mode = {True: "ask", False: "never"}.get(mode, mode)  # settings saved before the ask option existed
        if saved and mode == "ask":
            self.engine.open(path, paused=True)  # first frame behind the card
            self.pending_resume = saved
            self.prompt.ask(saved, self.resume.data[self.resume._key(path)].get("dur", 0))
        elif saved and mode == "always":
            self.engine.open(path, start=saved)
            self.toast.show_message(f"Continuing from {fmt_time(saved)}")
        else:
            self.engine.open(path)
        self._keep_awake(not self.engine.mpv.pause)  # opening while already playing doesn't fire a pause change
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
        if not path:
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
            self.open_path(nxt)
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
        self.bar.elapsed.setText(fmt_time(pos))
        self.bar.remaining.setText(fmt_time(self.duration - pos))
        self._remember_position()

    def _on_duration(self, d):
        self.duration = d
        self.bar.seek.set_duration(d)
        self.bar.remaining.setText(fmt_time(d - self.position))

    @staticmethod
    def _keep_awake(on):
        """While a video plays, stop Windows from starting the screensaver or sleeping. mpv only does this for
        windows it creates itself; Iron Will draws mpv into its own window, so it has to ask Windows directly."""
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED if on else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags))

    def _on_pause(self, paused):
        self.paused = paused
        self._keep_awake(bool(self.engine.path) and not paused)
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

    def _on_loaded(self, path):
        self.loaded_ok = path == self.engine.path
        self._update_neighbors()
        if self.loaded_ok:
            self._enforce_languages()

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
                self.engine.select_track(kind, want["id"])
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
            QTimer.singleShot(400, lambda: self.open_path(nxt))
        elif every == "exit":
            QTimer.singleShot(400, self.close)
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
            self.showFullScreen()
            self.bar.full.set_glyph(Glyph.WINDOW)

    def exit_fullscreen(self):
        if self.isFullScreen():
            self.showMaximized() if self.was_maximized else self.showNormal()
            self.menuBar().setVisible(bool(self.cfg["show_menubar"]))
            self.bar.full.set_glyph(Glyph.FULL)
            self.caption.hide()
            self._sync_border()  # the border setting may have changed while in full screen

    def toggle_mini(self):
        hwnd = int(self.winId())
        HWND_TOPMOST, HWND_NOTOPMOST, SWP_NOMOVE_NOSIZE = -1, -2, 0x0001 | 0x0002
        user32 = ctypes.windll.user32
        if self.mini_geometry is None:
            if self.isFullScreen():
                self.exit_fullscreen()
            self.mini_geometry = self.saveGeometry()
            self.showNormal()
            area = self.screen().availableGeometry()
            w, h = {"small": (400, 225), "large": (720, 405)}.get(self.cfg["mini_size"], (560, 315))
            self.setGeometry(area.right() - w - 24, area.bottom() - h - 24, w, h)
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE_NOSIZE)
            self.bar.title.hide()
            self._layout()
        else:
            user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE_NOSIZE)
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
        try:  # dark title bar on Windows 10/11
            val = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 20, ctypes.byref(val), 4)
        except Exception:
            pass
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
