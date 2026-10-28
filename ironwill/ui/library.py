"""File > Library: the videos in your library folders as a grid of thumbnails, newest first, with search.

Thumbnails are one frame from 10 % into each video, made with the bundled FFmpeg in the background and cached in
the data folder, so the second visit is instant. Double-click plays (resume works as usual)."""
import hashlib
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout)

from .. import playlist
from ..settings import DATA_DIR
from .widgets import themed

THUMBS = DATA_DIR / "thumbs"
VIDEO_EXTS = {e for e in playlist.MEDIA_EXTS if e not in {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav",
                                                           ".wma", ".ape", ".alac", ".mka", ".dts", ".ac3"}}


def scan(folders):
    files = []
    for folder in folders:
        try:
            files += [p for p in Path(folder).rglob("*") if p.suffix.lower() in VIDEO_EXTS and p.is_file()]
        except OSError:
            continue
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def thumb_path(f):
    st = f.stat()
    return THUMBS / (hashlib.sha1(f"{f}|{st.st_size}|{st.st_mtime}".encode()).hexdigest() + ".jpg")


def make_thumb(ffmpeg, f, duration=None):
    out = thumb_path(f)
    if out.exists():
        return out
    THUMBS.mkdir(parents=True, exist_ok=True)
    try:
        if duration is None:
            from ..dupes.fingerprint import probe
            duration = probe(f).get("duration") or 0
        at = max(1.0, duration * 0.1)
        subprocess.run([ffmpeg, "-v", "quiet", "-y", "-ss", f"{at:.1f}", "-i", str(f), "-frames:v", "1",
                        "-vf", "scale=320:-2", str(out)], timeout=30, creationflags=0x08000000)
    except Exception:
        pass
    return out if out.exists() else None


class Library(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Library")
        self.resize(1100, 720)
        folders = [x.strip() for x in win.cfg["library_folders"].split(";") if x.strip()]
        self.search = QLineEdit(placeholderText="Search your library…")
        self.search.textChanged.connect(self._filter)
        self.info = QLabel()
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setIconSize(QSize(240, 135))
        self.grid.setGridSize(QSize(262, 190))
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setWordWrap(True)
        self.grid.setUniformItemSizes(True)
        self.grid.itemActivated.connect(self._play)
        folders_btn = QPushButton("Library Folders…")
        folders_btn.clicked.connect(lambda: (self.accept(), win.open_options("library")))
        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(folders_btn)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.info)
        lay.addWidget(self.grid)
        self.setStyleSheet(themed("QListWidget { background: #141414; color: #e8e8e8; border: none; }"
                                  "QListWidget::item:selected { background: rgba(232,17,35,0.30); }"
                                  "QDialog { background: #1b1b1b; color: #e8e8e8; }"
                                  "QLineEdit { background: #262626; color: white; padding: 6px; border-radius: 4px; }"))
        if not folders:
            self.info.setText("Add your movie and show folders: Library Folders… (or Options > Library)")
            return
        self.info.setText("Reading your library…")
        self.items = {}
        self.blank = QPixmap(240, 135)
        self.blank.fill(Qt.GlobalColor.black)
        done = threading.Event()
        found = []
        threading.Thread(target=lambda: (found.extend(scan(folders)), done.set()), daemon=True).start()

        def ready():
            if not done.is_set():
                QTimer.singleShot(150, ready)
                return
            self._show(found)
        ready()

    def _show(self, files):
        self.info.setText(f"{len(files)} videos")
        resume = self.win.resume
        for f in files:
            it = QListWidgetItem(QIcon(self.blank), f.stem)
            it.setData(Qt.ItemDataRole.UserRole, str(f))
            try:
                rec = resume.data.get(resume._key(f)) or {}
                if rec.get("pos") and rec.get("dur"):
                    it.setText(f"{f.stem}\n{int(100 * rec['pos'] / rec['dur'])}% watched")
            except Exception:
                pass
            it.setToolTip(str(f))
            self.grid.addItem(it)
            self.items[str(f)] = it
        from ..dupes.fingerprint import find_tool
        ffmpeg = find_tool("ffmpeg")
        if not ffmpeg:
            return
        made = []

        def work():  # thumbnails in the background, newest first
            for f in files:
                if not self.isVisible() and made:
                    return
                made.append((str(f), make_thumb(ffmpeg, f)))
        threading.Thread(target=work, daemon=True).start()

        def apply():
            while made:
                key, path = made.pop(0)
                if path and key in self.items:
                    self.items[key].setIcon(QIcon(QPixmap(str(path))))
            if self.isVisible():
                QTimer.singleShot(300, apply)
        apply()

    def _filter(self, text):
        words = text.lower().split()
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            it.setHidden(not all(w in it.text().lower() for w in words))

    def _play(self, item):
        self.win.open_path(item.data(Qt.ItemDataRole.UserRole))
        self.accept()
