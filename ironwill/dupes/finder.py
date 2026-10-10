"""Find Duplicates window: pick folders, scan, review groups (best copy first), compare any two side by side,
and send extra copies to the Recycle Bin."""
import datetime
import json
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QListWidget, QMessageBox, QProgressBar, QPushButton, QSpinBox, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout)

from ..ui.options import STYLE
from ..ui.widgets import fmt_time
from .scanner import Scanner
from .store import Store
from .trash import recycle

VDF_SETTINGS = Path(r"E:\_Misc\VDF\Settings.json")
COLS = ["File", "Match", "Length", "Resolution", "FPS", "Bitrate", "Size", "Modified", "Folder"]

EXTRA = STYLE + """
QTreeWidget { background: #161616; border: 1px solid #2C2C2C; border-radius: 6px; alternate-background-color: #1b1b1b; }
QTreeWidget::item { padding: 4px 2px; }
QTreeWidget::item:selected { background: rgba(232,17,35,0.28); }
QProgressBar { background: #222; border: 1px solid #333; border-radius: 4px; height: 10px; text-align: center;
               color: #ddd; }
QProgressBar::chunk { background: #E81123; border-radius: 3px; }
"""


def _size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024


class FinderWindow(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win, self.cfg = win, win.cfg
        self.setWindowTitle("Find Duplicates - Iron Will")
        self.setStyleSheet(EXTRA)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(1280, 800)
        self.groups = []
        self.scanner = Scanner(self)
        self.scanner.progress.connect(self._progress)
        self.scanner.finished.connect(self._finished)

        root = QVBoxLayout(self)
        header = QLabel("Find Duplicates")
        header.setObjectName("header")
        root.addWidget(header)

        # Folders and options -----------------------------------------------------------------------------
        top = QHBoxLayout()
        self.folders = QListWidget()
        self.folders.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.folders.setFixedHeight(110)
        self.folders.addItems(self.cfg.values.get("dupe_folders", []))
        top.addWidget(self.folders, 1)
        fbtns = QVBoxLayout()
        for text, fn in (("Add folder…", self._add_folder), ("Remove", self._remove_folders),
                         ("Import from VDF", self._import_vdf)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            fbtns.addWidget(b)
        fbtns.addStretch(1)
        top.addLayout(fbtns)
        opts = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(QLabel("Similarity at least"))
        self.threshold = QSpinBox()
        self.threshold.setRange(50, 100)
        self.threshold.setSuffix(" %")
        self.threshold.setValue(int(self.cfg.values.get("dupe_threshold", 80)))
        row.addWidget(self.threshold)
        row.addStretch(1)
        opts.addLayout(row)
        self.subfolders = QCheckBox("Include subfolders")
        self.clips = QCheckBox("Find clips cut from longer videos")
        self.mirrored = QCheckBox("Find mirrored (flipped) copies")
        for box, key in ((self.subfolders, "dupe_subfolders"), (self.clips, "dupe_clips"),
                         (self.mirrored, "dupe_mirrored")):
            box.setChecked(bool(self.cfg.values.get(key, True)))
            opts.addWidget(box)
        opts.addStretch(1)
        top.addLayout(opts)
        root.addLayout(top)

        scan_row = QHBoxLayout()
        self.scan_btn = QPushButton("Scan for duplicates")
        self.scan_btn.setObjectName("primary")
        self.scan_btn.clicked.connect(self._scan)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.scanner.stop)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.status = QLabel("Add the folders to check, then Scan. Videos are only read; nothing is changed until "
                             "you choose to recycle copies.")
        self.status.setObjectName("note")
        scan_row.addWidget(self.scan_btn)
        scan_row.addWidget(self.stop_btn)
        scan_row.addWidget(self.bar, 1)
        root.addLayout(scan_row)
        root.addWidget(self.status)

        # Results ----------------------------------------------------------------------------------------------
        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(COLS))
        self.tree.setHeaderLabels(COLS)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, len(COLS)):
            self.tree.header().setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemDoubleClicked.connect(self._play_item)
        self.tree.itemChanged.connect(lambda *_: self._update_counts())
        root.addWidget(self.tree, 1)

        actions = QHBoxLayout()
        for text, fn, tip in (
                ("Compare side by side", self._compare, "Play two copies together, synced (select a group or two files)"),
                ("Check extra copies", self._check_extras, "Tick every copy except the suggested keeper (★)"),
                ("Uncheck all", self._uncheck_all, ""),
                ("Not duplicates", self._not_dupes, "Hide this group for good"),
                ("Open folder", self._open_folder, "")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            actions.addWidget(b)
        actions.addStretch(1)
        self.counts = QLabel("")
        self.counts.setObjectName("note")
        actions.addWidget(self.counts)
        self.recycle_btn = QPushButton("Move checked to Recycle Bin")
        self.recycle_btn.setObjectName("primary")
        self.recycle_btn.clicked.connect(self._recycle)
        actions.addWidget(self.recycle_btn)
        root.addLayout(actions)

    # Folders ----------------------------------------------------------------------------------------------------
    def _folder_list(self):
        return [self.folders.item(i).text() for i in range(self.folders.count())]

    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Add a folder to scan")
        if folder and folder not in self._folder_list():
            self.folders.addItem(str(Path(folder)))

    def _remove_folders(self):
        for item in self.folders.selectedItems():
            self.folders.takeItem(self.folders.row(item))

    def _import_vdf(self):
        try:
            includes = json.loads(VDF_SETTINGS.read_text(encoding="utf-8-sig")).get("Includes", [])
        except (OSError, ValueError):
            path, _ = QFileDialog.getOpenFileName(self, "Find VDF's Settings.json", "", "Settings.json (Settings.json)")
            if not path:
                return
            includes = json.loads(Path(path).read_text(encoding="utf-8-sig")).get("Includes", [])
        added = 0
        for folder in includes:
            if folder not in self._folder_list():
                self.folders.addItem(folder)
                added += 1
        self.status.setText(f"Imported {added} folders from VDF.")

    # Scanning ---------------------------------------------------------------------------------------------------
    def _scan(self):
        folders = self._folder_list()
        if not folders:
            self.status.setText("Add at least one folder first.")
            return
        self.win.set_prefs({"dupe_folders": folders, "dupe_threshold": self.threshold.value(),
                            "dupe_subfolders": self.subfolders.isChecked(), "dupe_clips": self.clips.isChecked(),
                            "dupe_mirrored": self.mirrored.isChecked()})
        self.tree.clear()
        self.scan_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.scanner.start(folders, self.threshold.value() / 100, self.subfolders.isChecked(),
                           self.clips.isChecked(), self.mirrored.isChecked())

    def _progress(self, phase, done, total, detail):
        self.bar.setRange(0, max(total, 0))
        self.bar.setValue(done)
        tail = f": {detail}" if detail else ""
        self.status.setText(f"{phase} {done}/{total}{tail}" if total else phase)

    def _finished(self, groups, summary):
        self.scan_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.groups = groups
        self.status.setText(summary)
        self._fill()

    # Results ----------------------------------------------------------------------------------------------------
    def _fill(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        bold = QFont()
        bold.setBold(True)
        for gi, g in enumerate(self.groups):
            keeper = g.members[0].fp
            extra = sum(m.fp.size for m in g.members[1:])
            head = QTreeWidgetItem([f"Group {gi + 1}  ·  {len(g.members)} copies  ·  {_size(extra)} in extras"])
            head.setFirstColumnSpanned(True)
            head.setFont(0, bold)
            head.setData(0, Qt.ItemDataRole.UserRole, ("group", gi))
            self.tree.addTopLevelItem(head)
            for mi, m in enumerate(g.members):
                fp = m.fp
                p = Path(fp.path)
                if m.kind == "keep":
                    match_text = "★ keep"
                else:
                    bits = [f"{m.similarity:.0%}"]
                    if abs(m.offset) >= 0.5:
                        bits.append(f"{m.offset:+.1f}s")
                    if m.kind == "clip":
                        bits.append("clip")
                    if m.flipped:
                        bits.append("mirrored")
                    match_text = " · ".join(bits)
                mtime = datetime.datetime.fromtimestamp(fp.mtime).strftime("%Y-%m-%d") if fp.mtime else ""
                row = QTreeWidgetItem([p.name, match_text, fmt_time(fp.duration),
                                       f"{fp.width}×{fp.height}" if fp.width else "", f"{fp.fps:g}" if fp.fps else "",
                                       f"{fp.vbitrate / 1000:,.0f} kbps" if fp.vbitrate else "", _size(fp.size), mtime,
                                       str(p.parent)])
                row.setData(0, Qt.ItemDataRole.UserRole, ("file", gi, mi))
                row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                row.setCheckState(0, Qt.CheckState.Unchecked)
                row.setToolTip(0, fp.path)
                if m.kind == "keep":
                    row.setForeground(1, QColor("#8FD19E"))
                head.addChild(row)
            head.setExpanded(True)
        self.tree.blockSignals(False)
        self._update_counts()

    def _checked(self):
        out = []
        for i in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(i)
            for j in range(head.childCount()):
                row = head.child(j)
                if row.checkState(0) == Qt.CheckState.Checked:
                    _, gi, mi = row.data(0, Qt.ItemDataRole.UserRole)
                    out.append((gi, mi, row))
        return out

    def _update_counts(self):
        checked = self._checked()
        total = sum(self.groups[gi].members[mi].fp.size for gi, mi, _ in checked)
        self.counts.setText(f"{len(checked)} checked · {_size(total)}" if checked else "")
        self.recycle_btn.setEnabled(bool(checked))

    def _check_extras(self):
        for i in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(i)
            for j in range(head.childCount()):
                head.child(j).setCheckState(0, Qt.CheckState.Checked if j > 0 else Qt.CheckState.Unchecked)

    def _uncheck_all(self):
        for i in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(i)
            for j in range(head.childCount()):
                head.child(j).setCheckState(0, Qt.CheckState.Unchecked)

    def _selected_group(self):
        item = self.tree.currentItem()
        if not item:
            return None, []
        data = item.data(0, Qt.ItemDataRole.UserRole)
        gi = data[1]
        picks = [it.data(0, Qt.ItemDataRole.UserRole)[2] for it in self.tree.selectedItems()
                 if it.data(0, Qt.ItemDataRole.UserRole)[0] == "file"
                 and it.data(0, Qt.ItemDataRole.UserRole)[1] == gi]
        return gi, picks

    def _compare(self):
        gi, picks = self._selected_group()
        if gi is None:
            self.status.setText("Select a group (or two files in one group) to compare.")
            return
        g = self.groups[gi]
        if len(picks) < 2:
            picks = [0, picks[0] if picks and picks[0] != 0 else 1]
        left, right = g.members[picks[0]], g.members[picks[1]]
        from .compare import CompareWindow
        CompareWindow(self, left, right).show()

    def _not_dupes(self):
        gi, _ = self._selected_group()
        if gi is None:
            return
        store = Store()
        members = self.groups[gi].members
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                store.mark_not_dupes(members[x].fp.path, members[y].fp.path)
        self.groups.pop(gi)
        self._fill()
        self.status.setText("Marked as not duplicates. They won't be shown again.")

    def _open_folder(self):
        item = self.tree.currentItem()
        data = item and item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "file":
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.groups[data[1]].members[data[2]].fp.path).parent)))

    def _play_item(self, item, _col):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data[0] == "file":
            self.win.open_path(self.groups[data[1]].members[data[2]].fp.path)

    def _recycle(self):
        checked = self._checked()
        if not checked:
            return
        whole_groups = [gi for gi in {gi for gi, _, _ in checked}
                        if sum(1 for g2, _, _ in checked if g2 == gi) == len(self.groups[gi].members)]
        total = sum(self.groups[gi].members[mi].fp.size for gi, mi, _ in checked)
        warn = (f"\n\nCareful: every copy in {len(whole_groups)} group(s) is checked, so nothing of those would be "
                f"left outside the Recycle Bin.") if whole_groups else ""
        box = QMessageBox(QMessageBox.Icon.Question, "Move to Recycle Bin",
                          f"Move {len(checked)} file(s) ({_size(total)}) to the Recycle Bin?\n\n"
                          f"You can restore them from the Recycle Bin if you change your mind.{warn}",
                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, self)
        box.setStyleSheet(EXTRA)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return
        paths = [self.groups[gi].members[mi].fp.path for gi, mi, _ in checked]
        playing = (self.win.engine.path or "").lower()
        if playing in [p.lower() for p in paths]:
            self.win.stop()  # Windows can't recycle a file that's open in the player
        ok = recycle(paths)
        store = Store()
        gone = [p for p in paths if not Path(p).exists()]
        for p in gone:
            store.forget(p)
        for gi, mi, _ in sorted(checked, key=lambda x: (-x[0], -x[1])):
            if not Path(self.groups[gi].members[mi].fp.path).exists():
                self.groups[gi].members.pop(mi)
        self.groups = [g for g in self.groups if len(g.members) > 1]
        self._fill()
        self.status.setText(f"Moved {len(gone)} file(s) to the Recycle Bin." +
                            ("" if ok and len(gone) == len(paths) else " Some couldn't be moved (in use or missing)."))

    def closeEvent(self, e):
        self.scanner.stop()
        super().closeEvent(e)
