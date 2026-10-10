"""Properties (Shift+F10): everything about the playing file - container, video, audio and subtitle tracks,
chapters - in the Options window's dark style, with a Copy button."""
import datetime
from pathlib import Path

from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QVBoxLayout)

from .menus import track_label
from .options import STYLE
from .widgets import fmt_time


def _size(n):
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.2f} {unit}"
        n /= 1024


class PropertiesDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.setWindowTitle("Properties")
        self.setStyleSheet(STYLE)
        self.resize(720, 560)
        m, path = win.engine.mpv, Path(win.engine.path)

        def get(name, default=None):
            try:
                value = m._get_property(name)
                return default if value is None else value
            except Exception:
                return default

        lines = []

        def section(title):
            lines.append("")
            lines.append(title.upper())

        def row(label, value):
            if value not in (None, "", 0):
                lines.append(f"  {label:<18}{value}")

        lines.append(path.name)
        section("File")
        row("Folder", str(path.parent))
        try:
            st = path.stat()
            row("Size", f"{_size(st.st_size)}  ({st.st_size:,} bytes)")
            row("Modified", datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"))
        except OSError:
            pass
        row("Container", get("file-format"))
        row("Duration", fmt_time(get("duration", 0)))
        bitrate = get("file-size", 0) * 8 / max(1, get("duration", 1)) / 1000
        row("Overall bitrate", f"{bitrate:,.0f} kbps" if bitrate else None)
        row("Title (tags)", get("media-title") if get("media-title") != path.name else None)

        section("Video")
        row("Codec", get("video-format") or get("video-codec"))
        w, h = get("width"), get("height")
        row("Resolution", f"{w} × {h}" if w and h else None)
        dw, dh = get("dwidth"), get("dheight")
        row("Display size", f"{dw} × {dh}" if dw and dh and (dw, dh) != (w, h) else None)
        fps = get("container-fps")
        row("Frame rate", f"{fps:.3f} fps" if fps else None)
        vb = get("video-bitrate")
        row("Bitrate", f"{vb / 1000:,.0f} kbps" if vb else None)
        params = get("video-params", {}) or {}
        row("Pixel format", params.get("pixelformat"))
        row("Colors", ", ".join(x for x in (params.get("colormatrix"), params.get("primaries"), params.get("gamma"))
                                if x) or None)
        row("HDR", "Yes" if params.get("gamma") in ("pq", "hlg") else None)
        hw = get("hwdec-current")
        row("Hardware decoding", hw if hw and hw != "no" else "Off (software)")

        for kind, title in (("audio", "Audio tracks"), ("sub", "Subtitle tracks")):
            tracks = win.engine.tracks(kind)
            section(f"{title} ({len(tracks)})")
            for t in tracks:
                mark = "▶ " if t.get("selected") else "  "
                ext = "  [external file]" if t.get("external") else ""
                lines.append(f"  {mark}{track_label(t)}{ext}")
            if not tracks:
                lines.append("  none")
            ab = get("audio-bitrate") if kind == "audio" else None
            if ab:
                lines.append(f"  Playing at {ab / 1000:,.0f} kbps")

        chapters = get("chapter-list", []) or []
        if chapters:
            section(f"Chapters ({len(chapters)})")
            for i, c in enumerate(chapters):
                lines.append(f"  {fmt_time(c.get('time', 0))}  {c.get('title') or f'Chapter {i + 1}'}")

        text = "\n".join(lines).strip()
        lay = QVBoxLayout(self)
        heading = QLabel(path.stem)
        heading.setObjectName("header")
        heading.setWordWrap(True)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        view.setStyleSheet("QPlainTextEdit { font-family: 'Cascadia Mono', Consolas, monospace; font-size: 13px; }")
        lay.addWidget(heading)
        lay.addWidget(view, 1)
        buttons = QHBoxLayout()
        copy, close = QPushButton("Copy to clipboard"), QPushButton("Close")
        close.setObjectName("primary")
        copy.clicked.connect(lambda: (QApplication.clipboard().setText(text), copy.setText("Copied ✓")))
        close.clicked.connect(self.accept)
        buttons.addWidget(copy)
        buttons.addStretch(1)
        buttons.addWidget(close)
        lay.addLayout(buttons)
