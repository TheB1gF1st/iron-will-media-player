"""Small building blocks for the Movies & TV look: icon buttons, the seek bar, the volume flyout,
dark menus and the on-screen toast."""
import time

from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, Signal, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen, QFontMetrics
from PySide6.QtWidgets import (QAbstractButton, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMenu,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

ACCENT = QColor("#E81123")
LOOP = QColor("#FFC23D")  # A-B loop markers: amber, so they never blend into the red progress line


class Glyph:
    PLAY, PAUSE = "\uE768", "\uE769"
    VOL0, VOL1, VOL2, VOL3, MUTE = "\uE992", "\uE993", "\uE994", "\uE995", "\uE74F"
    SUBS = "\uED1E"
    BACK10, FWD30 = "\uED3C", "\uED3D"
    FULL, WINDOW = "\uE740", "\uE73F"
    MINI = "\uE8A7"
    MORE = "\uE712"
    LEFT, RIGHT = "\uE76B", "\uE76C"
    OPEN = "\uE8E5"
    MINIMIZE, MAXIMIZE, RESTORE, CLOSE = "\uE921", "\uE922", "\uE923", "\uE8BB"
    UP, DOWN = "\uE70E", "\uE70D"


def icon_font(size):
    family = "Segoe Fluent Icons" if "Segoe Fluent Icons" in QFontDatabase.families() else "Segoe MDL2 Assets"
    f = QFont(family)
    f.setPixelSize(size)
    return f


def ui_font(size, weight=QFont.Weight.Normal):
    f = QFont("Segoe UI Variable Text" if "Segoe UI Variable Text" in QFontDatabase.families() else "Segoe UI")
    f.setPixelSize(size)
    f.setWeight(weight)
    return f


def fmt_time(seconds):
    s = max(0, int(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


class IconButton(QAbstractButton):
    """Flat glyph button with a soft square hover highlight, like the Movies & TV transport bar."""

    def __init__(self, glyph, tip="", size=20, box=44, parent=None, hover=None):
        super().__init__(parent)
        self.glyph, self.glyph_size = glyph, size
        self.hover = hover or QColor(255, 255, 255, 38)
        self.setToolTip(tip)
        self.setFixedSize(box, box)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Every click flashes the icon red for a moment, so you can see the press registered.
        self.flashing = False
        self.pressed.connect(self._flash)

    def _flash(self):
        self.flashing = True
        self.update()
        QTimer.singleShot(220, self._unflash)

    def _unflash(self):
        self.flashing = False
        self.update()

    def set_glyph(self, glyph):
        self.glyph = glyph
        self.update()

    def set_skip(self, seconds, back):
        """Skip buttons: the font has ready-made 10 s back / 30 s forward icons; other values are drawn."""
        seconds = int(seconds)
        if (back and seconds == 10) or (not back and seconds == 30):
            self.skip = None
            self.glyph = Glyph.BACK10 if back else Glyph.FWD30
        else:
            self.skip = (seconds, back)
        self.update()

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isDown():
            p.fillRect(self.rect(), QColor(255, 255, 255, 22))
        elif self.underMouse():
            p.fillRect(self.rect(), self.hover)
        color = QColor(255, 255, 255, 255 if self.isEnabled() else 90)
        if self.flashing:
            color = QColor(ACCENT)
        if getattr(self, "skip", None):
            seconds, back = self.skip
            r = QRectF(0, 0, 22, 22)
            r.moveCenter(QRectF(self.rect()).center())
            p.setPen(QPen(color, 1.4))
            # Open circle with a small arrowhead at the top, mirrored for "back".
            start = 110 if back else 70
            span = 320 if back else -320
            p.drawArc(r, start * 16, span * 16)
            tip = QPointF(r.center().x() + (-3 if back else 3), r.top())
            d = -1 if back else 1
            p.drawLine(tip, tip + QPointF(-4 * d, -3.5))
            p.drawLine(tip, tip + QPointF(-4 * d, 3.5))
            p.setFont(ui_font(9 if seconds < 100 else 7, QFont.Weight.DemiBold))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, str(seconds))
            return
        p.setPen(color)
        p.setFont(icon_font(self.glyph_size))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.glyph)


class SeekBar(QWidget):
    """Thin red progress line with a ring thumb. Grows on hover and shows the time under the cursor."""
    seek_requested = Signal(float, bool)  # seconds, exact
    loop_clear_requested = Signal()
    loop_hint = Signal()
    loop_moved = Signal(float, float)  # new A, B in seconds (-1 = not set) while a tick is dragged

    def __init__(self, parent=None):
        super().__init__(parent)
        self.duration, self.position = 0.0, 0.0
        self.hover_x, self.dragging = None, False
        self.loop = {"a": None, "b": None}  # A-B loop markers in seconds
        self.last_click = None  # (x, time) of the previous timeline click, for "same spot again clears the loop"
        self.marker_drag = None  # set while a loop tick is held
        self.setFixedHeight(48)  # top 26 px hold the hover time bubble
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_duration(self, d):
        self.duration = d
        self.update()

    def set_loop_marker(self, which, seconds):
        self.loop[which] = seconds if seconds is not None and seconds >= 0 else None
        self.update()

    def set_position(self, p):
        if not self.dragging:
            self.position = p
            self.update()

    def _track(self):
        return QRectF(9, self.height() - 11, self.width() - 18, 0)

    def _value_at(self, x):
        t = self._track()
        frac = min(1.0, max(0.0, (x - t.left()) / max(1.0, t.width())))
        return frac * self.duration

    def _marker_at(self, x):
        """Which loop marker ("a"/"b") is under x, if any."""
        t = self._track()
        best = None
        for which, sec in self.loop.items():
            if sec is not None and self.duration > 0:
                mx = t.left() + t.width() * min(1.0, max(0.0, sec / self.duration))
                if abs(mx - x) <= 7 and (best is None or abs(mx - x) < best[1]):
                    best = (which, abs(mx - x))
        return best[0] if best else None

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.duration > 0:
            x = e.position().x()
            marker = self._marker_at(x)
            if marker is not None:
                # Press on a tick: a plain click jumps to it; dragging slides the loop (Shift: just this marker).
                self.marker_drag = {"which": marker, "x": x, "orig": dict(self.loop), "moved": False,
                                    "single": bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)}
                return
            # Clicks only jump; the A-B loop stays. Clicking the same spot again within 2 s clears it.
            now = time.monotonic()
            has_loop = self.loop["a"] is not None or self.loop["b"] is not None
            if has_loop and self.last_click and abs(x - self.last_click[0]) <= 8 and now - self.last_click[1] < 2.0:
                self.loop_clear_requested.emit()
                self.last_click = None
            else:
                self.last_click = (x, now)
                if has_loop:
                    self.loop_hint.emit()
            self.dragging = True
            self.position = self._value_at(x)
            self.seek_requested.emit(self.position, False)
            self.update()

    def mouseMoveEvent(self, e):
        self.hover_x = e.position().x()
        d = self.marker_drag
        if d:
            dx = self.hover_x - d["x"]
            if abs(dx) > 4:
                d["moved"] = True
            if d["moved"]:
                self._drag_markers(d, dx * self.duration / max(1.0, self._track().width()))
        elif self.dragging:
            self.position = self._value_at(self.hover_x)
            self.seek_requested.emit(self.position, False)
        else:
            on_marker = self._marker_at(self.hover_x) is not None
            self.setCursor(Qt.CursorShape.SizeHorCursor if on_marker else Qt.CursorShape.PointingHandCursor)
        self.update()

    def _drag_markers(self, d, delta):
        orig, which = d["orig"], d["which"]
        if d["single"] or orig["a"] is None or orig["b"] is None:
            new = dict(orig)
            lo, hi = 0.0, self.duration
            other = orig["b" if which == "a" else "a"]
            if other is not None:  # a marker can slide up to the other one, but never past it
                lo, hi = (lo, other - 0.5) if which == "a" else (other + 0.5, hi)
            new[which] = min(hi, max(lo, orig[which] + delta))
        else:
            # Both together, same distance apart, kept inside the timeline.
            lo, hi = min(orig["a"], orig["b"]), max(orig["a"], orig["b"])
            delta = min(max(delta, -lo), self.duration - hi)
            new = {"a": orig["a"] + delta, "b": orig["b"] + delta}
        self.loop = new
        self.loop_moved.emit(-1.0 if new["a"] is None else new["a"], -1.0 if new["b"] is None else new["b"])

    def mouseReleaseEvent(self, e):
        d = self.marker_drag
        if d:
            self.marker_drag = None
            if not d["moved"]:  # a plain click on a tick jumps to it
                self.position = self.loop[d["which"]]
                self.seek_requested.emit(self.position, True)
                self.update()
            return
        if self.dragging:
            self.dragging = False
            self.seek_requested.emit(self._value_at(e.position().x()), True)

    def leaveEvent(self, _e):
        self.hover_x = None
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self._track()
        y = t.top()
        hot = self.hover_x is not None or self.dragging
        thick = 4 if hot else 2
        frac = self.position / self.duration if self.duration > 0 else 0
        px = t.left() + t.width() * frac
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 95))
        p.drawRoundedRect(QRectF(t.left(), y - thick / 2, t.width(), thick), thick / 2, thick / 2)
        p.setBrush(ACCENT)
        p.drawRoundedRect(QRectF(t.left(), y - thick / 2, px - t.left(), thick), thick / 2, thick / 2)
        # A-B loop: amber ticks labeled A / B, with the looped stretch shaded when both are set.
        if self.duration > 0 and (self.loop["a"] is not None or self.loop["b"] is not None):
            def x_of(sec):
                return t.left() + t.width() * min(1.0, max(0.0, sec / self.duration))
            a, b = self.loop["a"], self.loop["b"]
            if a is not None and b is not None:
                lo, hi = sorted((x_of(a), x_of(b)))
                p.setBrush(QColor(LOOP.red(), LOOP.green(), LOOP.blue(), 70))
                p.drawRect(QRectF(lo, y - 5, hi - lo, 10))
            p.setFont(ui_font(13, QFont.Weight.Bold))
            for name, sec in (("A", a), ("B", b)):
                if sec is None:
                    continue
                mx = x_of(sec)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(LOOP)
                p.drawRoundedRect(QRectF(mx - 1.5, y - 11, 3, 18), 1.5, 1.5)
                p.setPen(LOOP)
                p.drawText(QRectF(mx - 10, y - 29, 20, 17), Qt.AlignmentFlag.AlignCenter, name)
            p.setPen(Qt.PenStyle.NoPen)
        # Ring thumb (red ring, dark center), as in Movies & TV.
        r = 8 if hot else 7
        p.setBrush(QColor(20, 20, 20, 200))
        p.setPen(QPen(ACCENT, 2.5))
        p.drawEllipse(QPointF(px, y), r, r)
        # Time bubble above the cursor while hovering.
        if self.hover_x is not None and self.duration > 0:
            label = fmt_time(self._value_at(self.hover_x))
            p.setFont(ui_font(12, QFont.Weight.DemiBold))
            w = QFontMetrics(p.font()).horizontalAdvance(label) + 16
            x = min(max(self.hover_x - w / 2, 0), self.width() - w)
            box = QRectF(x, 0, w, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(20, 20, 20, 220))
            p.drawRoundedRect(box, 5, 5)
            p.setPen(QColor("white"))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, label)


class CloseOrb(QAbstractButton):
    """Round ✕ that drops down at the top centre when the mouse is in the top quarter of the window."""
    SIZE = 52

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip("Close Iron Will")

    def enterEvent(self, e):
        self.update()

    def leaveEvent(self, e):
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(0.8)  # 80% opaque, so the video shows through a little
        hot = self.underMouse()
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.setBrush(QColor(196, 43, 28) if hot else QColor(18, 18, 20))
        p.setPen(QPen(QColor(255, 255, 255, 230 if hot else 150), 1.6))
        p.drawEllipse(r)
        p.setPen(QPen(QColor("white"), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        c, k = r.center(), r.width() * 0.2
        p.drawLine(QPointF(c.x() - k, c.y() - k), QPointF(c.x() + k, c.y() + k))
        p.drawLine(QPointF(c.x() - k, c.y() + k), QPointF(c.x() + k, c.y() - k))


class SpeedControl(QWidget):
    """▾ 100% ▴ on the bottom bar: the arrows step the speed, clicking the number opens a list, the wheel steps."""
    step = Signal(int)      # +1 faster, -1 slower
    pick = Signal(object)   # the number was clicked (anchor widget)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.down = IconButton(Glyph.DOWN, "Slower (Ctrl+Down)", 12, 0)
        self.up = IconButton(Glyph.UP, "Faster (Ctrl+Up)", 12, 0)
        self.value = QPushButton("100%")
        self.value.setToolTip("Playback speed: click for a list, scroll to change")
        self.value.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.value.setCursor(Qt.CursorShape.PointingHandCursor)
        self.value.setFont(ui_font(14, QFont.Weight.DemiBold))
        self.value.setFixedSize(56, 44)
        for b in (self.down, self.up):
            b.setFixedSize(30, 44)
        lay.addWidget(self.down)
        lay.addWidget(self.value)
        lay.addWidget(self.up)
        self.down.clicked.connect(lambda: self.step.emit(-1))
        self.up.clicked.connect(lambda: self.step.emit(1))
        self.value.clicked.connect(lambda: self.pick.emit(self.value))
        self.value.pressed.connect(self._flash)
        self.flashing = False
        self.speed = 1.0
        self.set_speed(1.0)

    def _flash(self):
        self.flashing = True
        self.set_speed(self.speed)
        QTimer.singleShot(220, lambda: (setattr(self, "flashing", False), self.set_speed(self.speed)))

    def set_speed(self, speed):
        self.speed = speed
        pct = round(speed * 100)
        self.value.setText(f"{pct}%")
        # Off normal speed the number turns red, so it's obvious the video isn't at 100%; a click flashes it bright red.
        color = ACCENT.name() if self.flashing else "white" if pct == 100 else "#FF4D5B"
        self.value.setStyleSheet(f"QPushButton {{ color: {color}; background: transparent; border: none; }}"
                                 "QPushButton:hover { background: rgba(255,255,255,38); }")

    def wheelEvent(self, e):
        self.step.emit(1 if e.angleDelta().y() > 0 else -1)
        e.accept()


class VolumeFlyout(QFrame):
    """Pop-up volume slider shown above the speaker button."""
    volume_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(300, 56)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        self.mute_btn = IconButton(Glyph.VOL3, "Mute", 18, 38)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 150)
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.value_label = QLabel("100")
        self.value_label.setFixedWidth(34)
        self.value_label.setFont(ui_font(14))
        self.value_label.setStyleSheet("color: white;")
        lay.addWidget(self.mute_btn)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.value_label)
        self.slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{ height: 4px; background: rgba(255,255,255,90); border-radius: 2px; }}
            QSlider::sub-page:horizontal {{ background: {ACCENT.name()}; border-radius: 2px; }}
            QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -6px 0; border-radius: 8px;
                background: #1b1b1b; border: 2px solid {ACCENT.name()}; }}""")
        self.slider.valueChanged.connect(self._changed)

    def _changed(self, v):
        self.value_label.setText(str(v))
        self.volume_changed.emit(v)

    def set_volume(self, v, muted):
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(v)))
        self.slider.blockSignals(False)
        self.value_label.setText(str(int(round(v))))
        self.mute_btn.set_glyph(volume_glyph(v, muted))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(32, 32, 32, 245))
        p.setPen(QPen(QColor(255, 255, 255, 30), 1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)


def volume_glyph(v, muted):
    if muted or v <= 0:
        return Glyph.MUTE
    return Glyph.VOL1 if v < 34 else Glyph.VOL2 if v < 67 else Glyph.VOL3


MENU_STYLE = """
QMenu { background: rgba(32,32,32,248); border: 1px solid rgba(255,255,255,30); border-radius: 8px;
        padding: 6px; color: white; font-family: 'Segoe UI'; font-size: 14px; }
QMenu::item { padding: 8px 36px 8px 14px; border-radius: 4px; }
QMenu::item:selected { background: rgba(255,255,255,26); }
QMenu::item:disabled { color: rgba(255,255,255,90); }
QMenu::separator { height: 1px; background: rgba(255,255,255,30); margin: 5px 8px; }
QMenu::indicator { width: 14px; height: 14px; left: 8px; }
QMenu::right-arrow { width: 10px; height: 10px; right: 10px; }
"""


def dark_menu(parent, title=""):
    m = QMenu(title, parent)
    m.setWindowFlags(m.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
    m.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    m.setStyleSheet(MENU_STYLE)
    return m


class ResumePrompt(QFrame):
    """'You left off at 0:12:34' card with Start over / Continue, shown over a paused first frame."""
    chosen = Signal(bool)  # True = continue

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(420, 170)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(6)
        title = QLabel("Welcome back")
        title.setFont(ui_font(20, QFont.Weight.DemiBold))
        self.detail = QLabel("")
        self.detail.setFont(ui_font(14))
        title.setStyleSheet("color: white; background: transparent;")
        self.detail.setStyleSheet("color: rgba(255,255,255,190); background: transparent;")
        lay.addWidget(title)
        lay.addWidget(self.detail)
        lay.addStretch(1)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        self.over = QPushButton("Start over")
        self.cont = QPushButton("Continue")
        for b, style in ((self.over, "background: rgba(255,255,255,26); border: 1px solid rgba(255,255,255,60);"),
                         (self.cont, "background: #E81123; border: none;")):
            b.setFixedSize(130, 40)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            b.setFont(ui_font(14, QFont.Weight.DemiBold))
            b.setStyleSheet(f"QPushButton {{ color: white; border-radius: 20px; {style} }}"
                            "QPushButton:hover { background: #F0303F; }" if b is self.cont else
                            f"QPushButton {{ color: white; border-radius: 20px; {style} }}"
                            "QPushButton:hover { background: rgba(255,255,255,46); }")
            row.addWidget(b)
        lay.addLayout(row)
        self.over.clicked.connect(lambda: self.chosen.emit(False))
        self.cont.clicked.connect(lambda: self.chosen.emit(True))
        self.hide()

    def ask(self, position, duration):
        total = f" of {fmt_time(duration)}" if duration else ""
        self.detail.setText(f"You left off at {fmt_time(position)}{total}.\nPick up where you stopped?")
        par = self.parentWidget()
        self.move((par.width() - self.width()) // 2, (par.height() - self.height()) // 2)
        self.show()
        self.raise_()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(22, 22, 24, 236))
        p.setPen(QPen(QColor(255, 255, 255, 34), 1))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ACCENT)
        p.drawRoundedRect(QRectF(0, 18, 4, self.height() - 36), 2, 2)


class Toast(QLabel):
    """Brief centered message ("Volume 60", "Speed 1.5x") that fades out by itself."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setFont(ui_font(16, QFont.Weight.DemiBold))
        self.setStyleSheet("color: white; background: rgba(20,20,20,200); border-radius: 10px; padding: 8px 18px;")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.effect)
        self.anim = QPropertyAnimation(self.effect, b"opacity", self)
        self.anim.setDuration(350)
        self.timer = QTimer(self, singleShot=True, interval=1100)
        self.timer.timeout.connect(self._fade)
        self.hide()

    enabled = True

    def show_message(self, text):
        if not self.enabled:
            return
        self.setText(text)
        self.adjustSize()
        par = self.parentWidget()
        self.move((par.width() - self.width()) // 2, int(par.height() * 0.12))
        self.anim.stop()
        self.effect.setOpacity(1.0)
        self.show()
        self.raise_()
        self.timer.start()

    def _fade(self):
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self.anim.start()
