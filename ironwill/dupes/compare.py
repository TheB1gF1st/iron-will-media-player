"""Side-by-side compare: two players that play, pause and seek together. The right one runs `offset` seconds
ahead or behind (measured automatically from the fingerprints, adjustable), so a copy with an added intro still
lines up frame for frame."""
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QRadioButton, QVBoxLayout,
                               QWidget)

from ..engine import PlayerEngine
from ..ui.options import STYLE
from ..ui.widgets import SeekBar, fmt_time
from ..video_view import MpvVideoWidget


def _info(fp):
    bits = [f"{fp.width}×{fp.height}" if fp.width else "", f"{fp.fps:g} fps" if fp.fps else "",
            f"{fp.vbitrate / 1000:,.0f} kbps" if fp.vbitrate else "", fmt_time(fp.duration),
            f"{fp.size / 1024 ** 2:,.0f} MB"]
    return "  ·  ".join(b for b in bits if b)


class Side(QWidget):
    def __init__(self, member, label):
        super().__init__()
        self.member = member
        self.engine = PlayerEngine(self)
        self.video = MpvVideoWidget(self.engine, self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        title = QLabel(f"{label}  {Path(member.fp.path).name}")
        title.setStyleSheet("color: white; font-size: 14px; font-weight: 600;")
        title.setToolTip(member.fp.path)
        info = QLabel(_info(member.fp))
        info.setObjectName("note")
        lay.addWidget(title)
        lay.addWidget(info)
        lay.addWidget(self.video, 1)
        self.engine.mpv["keep-open"] = "yes"
        if member.flipped:
            self.engine.mpv.command("vf", "add", "hflip")  # show mirrored copies the right way round
        # Open only once the video surface exists; opening earlier makes mpv switch the picture off.
        self.video.ready.connect(lambda: self.engine.open(member.fp.path, paused=True))


class CompareWindow(QDialog):
    def __init__(self, parent, left, right):
        super().__init__(parent)
        self.setWindowTitle("Compare - Iron Will")
        self.setStyleSheet(STYLE)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.resize(1500, 720)
        # Right's timeline = left's timeline + offset (both are measured against the group's keeper).
        self.auto_offset = right.offset - left.offset
        self.a, self.b = Side(left, "L"), Side(right, "R")
        root = QVBoxLayout(self)
        players = QHBoxLayout()
        players.addWidget(self.a, 1)
        players.addWidget(self.b, 1)
        root.addLayout(players, 1)

        self.seek = SeekBar()
        self.seek.set_duration(left.fp.duration)
        self.seek.seek_requested.connect(lambda s, exact: self._seek(s))
        root.addWidget(self.seek)

        bar = QHBoxLayout()
        self.play_btn = QPushButton("▶  Play both")
        self.play_btn.setObjectName("primary")
        self.play_btn.clicked.connect(self._toggle)
        bar.addWidget(self.play_btn)
        for text, delta in (("−10 s", -10), ("−1 s", -1), ("+1 s", 1), ("+10 s", 10)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, d=delta: self._seek(self.position + d))
            bar.addWidget(b)
        self.time = QLabel("0:00:00")
        bar.addWidget(self.time)
        bar.addStretch(1)
        bar.addWidget(QLabel("Right side offset"))
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-36000, 36000)
        self.offset.setDecimals(1)
        self.offset.setSingleStep(0.1)
        self.offset.setSuffix(" s")
        self.offset.setValue(self.auto_offset)
        self.offset.setToolTip("How far the right video's timeline is shifted (e.g. +12 s if it has a 12-second intro)")
        self.offset.valueChanged.connect(lambda _v: self._seek(self.position))
        bar.addWidget(self.offset)
        auto = QPushButton("Auto")
        auto.setToolTip(f"Use the measured offset ({self.auto_offset:+.1f} s)")
        auto.clicked.connect(lambda: self.offset.setValue(self.auto_offset))
        bar.addWidget(auto)
        bar.addSpacing(16)
        bar.addWidget(QLabel("Sound from"))
        self.snd_l, self.snd_r = QRadioButton("Left"), QRadioButton("Right")
        self.snd_l.setChecked(True)
        for r in (self.snd_l, self.snd_r):
            r.toggled.connect(self._audio)
            bar.addWidget(r)
        root.addLayout(bar)
        note = QLabel("Both play together. Seek with the bar or the buttons; if the pictures drift apart, nudge the "
                      "offset (0.1 s steps) until they line up.")
        note.setObjectName("note")
        root.addWidget(note)

        self.position = 0.0
        self.playing = False
        self._audio()
        self.a.engine.position_changed.connect(self._on_pos)
        self.sync = QTimer(self, interval=500)
        self.sync.timeout.connect(self._resync)
        self.sync.start()
        QTimer.singleShot(400, lambda: self._seek(max(0.0, -self.offset.value())))

    def _audio(self):
        self.a.engine.mpv.mute = not self.snd_l.isChecked()
        self.b.engine.mpv.mute = self.snd_l.isChecked()

    def _on_pos(self, pos):
        self.position = pos
        self.seek.set_position(pos)
        self.time.setText(f"{fmt_time(pos)}   ·   right at {fmt_time(pos + self.offset.value())}")

    def _seek(self, t):
        t = max(0.0, min(t, self.a.member.fp.duration - 0.2))
        self.position = t
        self.a.engine.seek(t)
        self.b.engine.seek(max(0.0, t + self.offset.value()))

    def _toggle(self):
        self.playing = not self.playing
        for side in (self.a, self.b):
            side.engine.mpv.pause = not self.playing
        self.play_btn.setText("❚❚  Pause both" if self.playing else "▶  Play both")
        if self.playing:
            self._seek(self.position)  # start from the same moment

    def _resync(self):
        """Keep the right player within ~0.15 s of where it should be while playing."""
        if not self.playing:
            return
        try:
            ta = float(self.a.engine.mpv._get_property("time-pos") or 0)
            tb = float(self.b.engine.mpv._get_property("time-pos") or 0)
        except Exception:
            return
        want = ta + self.offset.value()
        if want >= 0 and abs(tb - want) > 0.15:
            self.b.engine.seek(want)

    def closeEvent(self, e):
        self.sync.stop()
        for side in (self.a, self.b):
            side.video.shutdown()
            side.engine.shutdown()
        super().closeEvent(e)
