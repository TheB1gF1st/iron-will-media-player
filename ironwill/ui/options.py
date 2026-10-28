"""Options window: MPC-BE layout (page tree on the left, grouped settings on the right, OK / Cancel / Apply,
per-page Default) in Iron Will's dark style. Pages are generated from ironwill.settings.PAGES."""
import os
from pathlib import Path

from PySide6.QtCore import QEvent, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox,
                               QFileDialog, QFontComboBox, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
                               QHeaderView, QKeySequenceEdit, QLabel, QLineEdit, QListWidget, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import import_mpcbe
from ..settings import ALL, DATA_DIR, DEFAULT_MOUSE, GESTURES, MOUSE_COMMANDS, PAGES, apply_to_mpv, defaults

from .widgets import themed

STYLE = """
QDialog { background: #171717; }
QWidget { color: #EDEDED; font-family: 'Segoe UI'; font-size: 13px; }
QTreeWidget { background: #111; border: 1px solid #2A2A2A; border-radius: 8px; padding: 6px; font-size: 15px;
              outline: none; }
QTreeWidget::item { padding: 3px 4px; border-radius: 4px; }
QTreeWidget::branch { background: transparent; }
QTreeWidget::item:selected { background: rgba(232,17,35,0.22); color: white; }
QTreeWidget::item:hover:!selected { background: rgba(255,255,255,0.06); }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
QGroupBox { border: 1px solid #2C2C2C; border-radius: 8px; margin-top: 14px; padding: 14px 12px 10px 12px;
            background: #1D1D1D; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: #FF4D5B; font-weight: 600; }
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit, QFontComboBox, QPlainTextEdit, QKeySequenceEdit {
    background: #262626; border: 1px solid #3A3A3A; border-radius: 5px; padding: 4px 8px; min-height: 20px; }
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover { border-color: #555; }
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus, QPlainTextEdit:focus { border-color: #E81123; }
QComboBox QAbstractItemView { background: #262626; border: 1px solid #3A3A3A; selection-background-color: #4A1A1F; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 18px; height: 18px; border-radius: 4px; border: 1px solid #5A5A5A; background: #222; }
QCheckBox::indicator:checked { background: #E81123; border-color: #E81123;
    image: url(none); }
QPushButton { background: #2A2A2A; border: 1px solid #3C3C3C; border-radius: 5px; padding: 6px 16px; }
QPushButton:hover { background: #333; }
QPushButton:disabled { color: #666; }
QPushButton#primary { background: #E81123; border-color: #E81123; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #F0303F; }
QPushButton#apply[pending="true"] { font-weight: 700; color: white; border: 1px solid #E81123;
    background: rgba(232,17,35,0.16); }
QPushButton#apply[pending="true"]:hover { background: rgba(232,17,35,0.30); }
QPushButton#apply[flash="true"], QPushButton#apply[flash="true"]:disabled { background: #E81123;
    border-color: #E81123; color: white; font-weight: 700; }
QLabel#status[ok="true"] { color: #8FD19E; }
QSlider::groove:horizontal { height: 4px; background: #3A3A3A; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #E81123; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; height: 14px; margin: -6px 0; border-radius: 7px; background: #1b1b1b;
    border: 2px solid #E81123; }
QTableWidget, QListWidget { background: #1D1D1D; border: 1px solid #2C2C2C; border-radius: 6px;
    gridline-color: #2A2A2A; }
QHeaderView::section { background: #232323; color: #BBB; border: none; padding: 6px; }
QListWidget::item { padding: 6px; }
QListWidget::item:selected { background: rgba(232,17,35,0.25); }
QLabel#header { font-size: 20px; font-weight: 300; color: white; padding: 2px 0 6px 2px; }
QLabel#note { color: #9A9A9A; }
QLabel#status { color: #FFB4BA; }
QScrollBar:vertical { background: transparent; width: 10px; }
QScrollBar::handle:vertical { background: #3A3A3A; border-radius: 5px; min-height: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""


class ColorButton(QPushButton):
    changed = Signal()

    def __init__(self, value):
        super().__init__()
        self.setFixedSize(90, 28)
        self.clicked.connect(self._pick)
        self.set_value(value)

    def set_value(self, value):
        self.value = value
        self.changed.emit()
        c = QColor(value)
        if len(value) == 9:  # #AARRGGBB
            c = QColor(int(value[3:5], 16), int(value[5:7], 16), int(value[7:9], 16), int(value[1:3], 16))
        label = "None" if c.alpha() == 0 else c.name().upper()
        fg = "black" if c.lightness() > 140 and c.alpha() > 0 else "white"
        bg = f"rgba({c.red()},{c.green()},{c.blue()},{c.alpha()})"
        self.setText(label)
        self.setStyleSheet(f"QPushButton {{ background: {bg}; color: {fg}; border: 1px solid #555; }}")

    def _pick(self):
        cur = QColor(self.value[:1] + self.value[3:] if len(self.value) == 9 else self.value)
        if len(self.value) == 9:
            cur.setAlpha(int(self.value[1:3], 16))
        c = QColorDialog.getColor(cur, self, "Pick a color", QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if c.isValid():
            self.set_value(f"#{c.alpha():02X}{c.red():02X}{c.green():02X}{c.blue():02X}" if c.alpha() < 255
                           else c.name().upper())


class OptionsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.win, self.cfg, self.engine = window, window.cfg, window.engine
        self.setWindowTitle("Options")
        self.setStyleSheet(themed(STYLE))
        self.resize(980, 720)
        self.fields = {}  # key -> (getter, setter)
        self.page_keys = {}  # page id -> [keys]

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 12)
        body = QHBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setFixedWidth(230)
        self.tree.setIndentation(16)
        self.tree.setRootIsDecorated(False)
        self.stack = QStackedWidget()
        body.addWidget(self.tree)
        right = QVBoxLayout()
        self.header = QLabel()
        self.header.setObjectName("header")
        accent = QFrame()
        accent.setFixedHeight(3)
        accent.setStyleSheet(themed("background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #E81123, stop:1 transparent);"
                                    " border-radius: 1px;"))
        right.addWidget(self.header)
        right.addWidget(accent)
        right.addWidget(self.stack, 1)
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        items = {}
        for page in PAGES:
            item = QTreeWidgetItem([page.title])
            item.setData(0, Qt.ItemDataRole.UserRole, self.stack.count())
            (items[page.parent].addChild(item) if page.parent else self.tree.addTopLevelItem(item))
            items[page.id] = item
            self.stack.addWidget(self._build_page(page))
        self.tree.expandAll()
        self.tree.currentItemChanged.connect(self._show_page)
        self.tree_items = items
        self.tree.setCurrentItem(items["player"])

        buttons = QHBoxLayout()
        self.default_btn = QPushButton("Default")
        self.default_btn.setToolTip("Reset the settings on this page")
        self.default_btn.clicked.connect(self._page_defaults)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        ok, cancel, self.apply_btn = QPushButton("OK"), QPushButton("Cancel"), QPushButton("Apply")
        ok.setObjectName("primary")
        ok.setDefault(True)
        ok.clicked.connect(self._ok)
        cancel.clicked.connect(self.reject)
        self.apply_btn.clicked.connect(self._apply)
        buttons.addWidget(self.default_btn)
        buttons.addWidget(self.status, 1)
        for b in (ok, cancel, self.apply_btn):
            b.setMinimumWidth(96)
            buttons.addWidget(b)
        root.addLayout(buttons)
        self.apply_btn.setObjectName("apply")
        self._load(self.cfg.values)
        # Apply lights up while there are unsaved changes. The baseline is what the widgets show after loading,
        # so fonts or numbers that Qt normalizes slightly don't count as changes.
        self.baseline = self._collect()
        self._watch_changes()
        self._refresh_dirty()
        # The mouse wheel never changes a setting: over a drop-down, number box or slider it just scrolls the page,
        # so running the wheel down the list can't flip values by accident. Open a drop-down to pick with it.
        for cls in (QComboBox, QSpinBox, QDoubleSpinBox, QSlider):
            for w in self.findChildren(cls):
                w.installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Type.Wheel and isinstance(obj, (QComboBox, QSpinBox, QDoubleSpinBox, QSlider)):
            p = obj.parentWidget()
            while p is not None and not isinstance(p, QScrollArea):
                p = p.parentWidget()
            if p is not None:
                QApplication.sendEvent(p.verticalScrollBar(), e)
            return True
        return super().eventFilter(obj, e)

    def _watch_changes(self):
        hooks = [(QCheckBox, "toggled"), (QComboBox, "currentIndexChanged"), (QSpinBox, "valueChanged"),
                 (QDoubleSpinBox, "valueChanged"), (QLineEdit, "textChanged"), (QPlainTextEdit, "textChanged"),
                 (QKeySequenceEdit, "keySequenceChanged"), (ColorButton, "changed")]
        for cls, sig in hooks:
            for w in self.findChildren(cls):
                getattr(w, sig).connect(self._refresh_dirty)
        for lst in self.findChildren(QListWidget):
            for sig in ("rowsInserted", "rowsRemoved", "rowsMoved"):
                getattr(lst.model(), sig).connect(self._refresh_dirty)

    def _refresh_dirty(self, *_):
        if not hasattr(self, "baseline"):
            return
        dirty = self._collect() != self.baseline
        self.apply_btn.setEnabled(dirty)
        self._set_look(self.apply_btn, "pending", dirty)
        if dirty and self.status.text() == "Saved ✓":
            self.status.setText("")

    @staticmethod
    def _set_look(btn, prop, on):
        btn.setProperty(prop, on)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    # Page building ---------------------------------------------------------------------------------------
    def _build_page(self, page):
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(4, 4, 10, 4)
        if page.note:
            note = QLabel(page.note)
            note.setObjectName("note")
            note.setWordWrap(True)
            lay.addWidget(note)
        keys = []
        if page.special == "mouse":
            lay.addWidget(self._mouse_page())
            keys.append("mouse")
        for title, items in page.groups:
            box = QGroupBox(title)
            form = QFormLayout(box)
            form.setHorizontalSpacing(18)
            form.setVerticalSpacing(10)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            for s in items:
                widget, label = self._field(s)
                widget.setToolTip(s.tip)
                if label:
                    lbl = QLabel(s.label)
                    lbl.setToolTip(s.tip)
                    form.addRow(lbl, widget)
                else:
                    form.addRow(widget)
                keys.append(s.key)
            lay.addWidget(box)
        if page.special == "keys":
            lay.addWidget(self._keys_page(), 1)
            keys.append("keys")
        elif page.special == "shaders":
            lay.addWidget(self._shaders_page(), 1)
            keys.append("shaders")
        elif page.special == "dupes":
            open_btn = QPushButton("Open Find Duplicates…")
            open_btn.setObjectName("primary")
            open_btn.setFixedWidth(240)
            open_btn.clicked.connect(lambda: (self.accept(), self.win.open_duplicates()))
            lay.addWidget(open_btn)
            hint = QLabel("Also in the right-click menu: File > Find Duplicates…  (Ctrl+D)")
            hint.setObjectName("note")
            lay.addWidget(hint)
            tools = QHBoxLayout()
            for text, fn in (("Test FFmpeg", self._test_ffmpeg), ("Clear saved fingerprints…", self._clear_fingerprints)):
                b = QPushButton(text)
                b.clicked.connect(fn)
                tools.addWidget(b)
            tools.addStretch(1)
            lay.addLayout(tools)
            self.ffmpeg_info = QLabel("")
            self.ffmpeg_info.setObjectName("note")
            self.ffmpeg_info.setWordWrap(True)
            self.ffmpeg_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lay.addWidget(self.ffmpeg_info)
        elif page.special == "about":
            lay.addWidget(self._about_box())
        elif page.special == "formats":
            lay.addWidget(self._formats_box())
        lay.addStretch(1)
        self.page_keys[page.id] = keys
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        scroll.setProperty("title", page.title)
        scroll.setProperty("page_id", page.id)
        return scroll

    def _field(self, s):
        """Returns (widget, needs_label) and registers getter/setter for s.key."""
        k = s.key
        if isinstance(s.default, bool):
            w = QCheckBox(s.label)
            self.fields[k] = (w.isChecked, w.setChecked)
            return w, False
        if s.kind == "device":
            w = QComboBox()
            try:
                devices = self.engine.mpv._get_property("audio-device-list") or []
            except Exception:
                devices = []
            for d in devices or [{"name": "auto", "description": "Autoselect device"}]:
                w.addItem(d.get("description") or d["name"], d["name"])
            self.fields[k] = (lambda w=w: w.currentData(), lambda v, w=w: w.setCurrentIndex(max(0, w.findData(v))))
            return w, True
        if s.choices:
            w = QComboBox()
            for value, label in s.choices:
                w.addItem(label, value)
            self.fields[k] = (lambda w=w: w.currentData(),
                              lambda v, w=w: w.setCurrentIndex(max(0, w.findData(v))))
            return w, True
        if s.kind == "font":
            w = QFontComboBox()
            self.fields[k] = (lambda w=w: w.currentFont().family(),
                              lambda v, w=w: w.setCurrentText(v))
            return w, True
        if s.kind == "color":
            w = ColorButton(s.default)
            self.fields[k] = (lambda w=w: w.value, lambda v, w=w: w.set_value(v))
            return w, True
        if s.kind == "folder":
            w = QWidget()
            row = QHBoxLayout(w)
            row.setContentsMargins(0, 0, 0, 0)
            edit, browse = QLineEdit(), QPushButton("Browse…")
            browse.clicked.connect(lambda: (lambda p: p and edit.setText(p))(
                QFileDialog.getExistingDirectory(self, "Choose folder", edit.text())))
            row.addWidget(edit, 1)
            row.addWidget(browse)
            self.fields[k] = (edit.text, edit.setText)
            return w, True
        if s.kind == "file":
            w = QWidget()
            row = QHBoxLayout(w)
            row.setContentsMargins(0, 0, 0, 0)
            edit, browse = QLineEdit(), QPushButton("Browse…")
            browse.clicked.connect(lambda: (lambda p: p and edit.setText(p))(
                QFileDialog.getOpenFileName(self, "Choose a picture", edit.text(),
                                            "Pictures (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")[0]))
            row.addWidget(edit, 1)
            row.addWidget(browse)
            self.fields[k] = (edit.text, edit.setText)
            return w, True
        if s.kind == "multiline":
            w = QPlainTextEdit()
            w.setPlaceholderText("# examples\ndeband-grain=0\nsub-gauss=0.5")
            w.setFixedHeight(110)
            self.fields[k] = (w.toPlainText, w.setPlainText)
            box = QWidget()
            v = QVBoxLayout(box)
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(QLabel(s.label))
            v.addWidget(w)
            return box, False
        if s.kind == "text":
            w = QLineEdit()
            w.setPlaceholderText(s.tip)
            if k.endswith("_pass"):
                w.setEchoMode(QLineEdit.EchoMode.Password)  # dots, not the password
            self.fields[k] = (w.text, w.setText)
            return w, True
        # Numbers: -100..100 picture controls get a slider; everything else a spin box.
        is_int = isinstance(s.default, int) and float(s.step).is_integer()
        spin = QSpinBox() if is_int else QDoubleSpinBox()
        spin.setRange(int(s.lo) if is_int else s.lo, int(s.hi) if is_int else s.hi)
        spin.setSingleStep(int(s.step) if is_int else s.step)
        if not is_int:
            spin.setDecimals(2 if s.step < 0.1 else 1)
        spin.setSuffix(s.suffix)
        if s.zero_text and s.lo == 0:
            spin.setSpecialValueText(s.zero_text)  # shown instead of "0 days" etc.
        spin.setMinimumWidth(110)
        if s.lo == -100 and s.hi == 100:
            w = QWidget()
            row = QHBoxLayout(w)
            row.setContentsMargins(0, 0, 0, 0)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-100, 100)
            slider.valueChanged.connect(spin.setValue)
            spin.valueChanged.connect(slider.setValue)
            row.addWidget(slider, 1)
            row.addWidget(spin)
            self.fields[k] = (spin.value, spin.setValue)
            return w, True
        self.fields[k] = (spin.value, spin.setValue)
        return spin, True

    def _keys_page(self):
        acts = self.win.action_table()
        t = QTableWidget(len(acts), 3)
        t.setHorizontalHeaderLabels(["Action", "Shortcut", "Also works"])
        t.verticalHeader().hide()
        t.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        t.setColumnWidth(1, 190)
        t.setMinimumHeight(420)
        self.key_edits = {}
        for row, (aid, text, defaults_) in enumerate(acts):
            t.setItem(row, 0, QTableWidgetItem(text))
            edit = QKeySequenceEdit()
            t.setCellWidget(row, 1, edit)
            extra = QTableWidgetItem(", ".join(defaults_[1:]))
            extra.setForeground(QColor("#8A8A8A"))
            t.setItem(row, 2, extra)
            self.key_edits[aid] = (edit, defaults_)
            t.setRowHeight(row, 36)

        def get():
            out = {}
            for aid, (edit, defs) in self.key_edits.items():
                seq = edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
                if seq != (defs[0] if defs else ""):
                    out[aid] = seq
            return out

        def set_(mapping):
            for aid, (edit, defs) in self.key_edits.items():
                edit.setKeySequence(QKeySequence(mapping.get(aid, defs[0] if defs else "")))

        self.fields["keys"] = (get, set_)
        return t

    def _mouse_page(self):
        cols = ["Normal", "Ctrl", "Shift", "Right button held"]
        t = QTableWidget(len(GESTURES), len(cols))
        t.setHorizontalHeaderLabels(cols)
        t.setVerticalHeaderLabels([label for _g, label in GESTURES])
        t.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        combos = {}
        for r, (gesture, _label) in enumerate(GESTURES):
            t.setRowHeight(r, 38)
            for c in range(len(cols)):
                box = QComboBox()
                for cid, label in MOUSE_COMMANDS:
                    box.addItem(label, cid)
                t.setCellWidget(r, c, box)
                combos[(gesture, c)] = box
        t.setMinimumHeight(38 * len(GESTURES) + 40)

        def get():
            return {g: [combos[(g, c)].currentData() for c in range(len(cols))] for g, _l in GESTURES}

        def set_(mapping):
            for g, _l in GESTURES:
                slots = (mapping or {}).get(g, DEFAULT_MOUSE[g])
                for c in range(len(cols)):
                    box = combos[(g, c)]
                    box.setCurrentIndex(max(0, box.findData(slots[c] if c < len(slots) else "none")))

        self.fields["mouse"] = (get, set_)
        return t

    def _shaders_page(self):
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lst = QListWidget()
        lst.setMinimumHeight(300)
        col = QVBoxLayout()

        def add():
            files, _ = QFileDialog.getOpenFileNames(self, "Add shaders", str(DATA_DIR / "shaders"),
                                                    "GLSL shaders (*.glsl *.hook);;All files (*)")
            for f in files:
                lst.addItem(f)

        def move(d):
            r = lst.currentRow()
            if 0 <= r + d < lst.count() and r >= 0:
                it = lst.takeItem(r)
                lst.insertItem(r + d, it)
                lst.setCurrentRow(r + d)

        (DATA_DIR / "shaders").mkdir(parents=True, exist_ok=True)
        for text, fn in (("Add…", add), ("Remove", lambda: lst.takeItem(lst.currentRow())),
                         ("Move up", lambda: move(-1)), ("Move down", lambda: move(1)),
                         ("Open shaders folder", lambda: QDesktopServices.openUrl(
                             QUrl.fromLocalFile(str(DATA_DIR / "shaders"))))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            col.addWidget(b)
        col.addStretch(1)
        lay.addWidget(lst, 1)
        lay.addLayout(col)
        self.fields["shaders"] = (lambda: [lst.item(i).text() for i in range(lst.count())],
                                  lambda v: (lst.clear(), lst.addItems(v)))
        return box

    def _formats_box(self):
        from .. import associate
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        groups = (("Video files", associate.VIDEO_EXTS), ("Audio files", associate.AUDIO_EXTS))
        checks = {}
        for title, exts in groups:
            cb = QCheckBox(f"{title}  ({', '.join(e.lstrip('.') for e in exts)})")
            cb.setChecked(any(associate.registered(e) for e in exts) or title == "Video files")
            cb.setStyleSheet("QCheckBox { padding: 4px 0; }")
            checks[title] = cb
            v.addWidget(cb)
        row = QHBoxLayout()
        status = QLabel("")
        status.setObjectName("note")
        status.setWordWrap(True)

        def do_register():
            try:
                associate.register(video=checks["Video files"].isChecked(), audio=checks["Audio files"].isChecked())
            except Exception as exc:
                status.setText(f"Couldn't register: {exc}")
                return
            status.setText("Registered. Now pick Iron Will for each type in Default Apps (opening it for you).")
            associate.open_default_apps()

        def do_remove():
            associate.remove()
            status.setText("Iron Will's file types were removed from Windows.")
        for text, fn in (("Register with Windows", do_register), ("Open Default Apps", associate.open_default_apps),
                         ("Remove registration", do_remove)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        v.addWidget(status)
        return box

    def _test_ffmpeg(self):
        """Show which FFmpeg the scanner will use, its version and the hardware decoders it supports."""
        import subprocess
        from ..dupes import fingerprint as fpmod
        fpmod.SETTINGS["ffmpeg_dir"] = self._collect().get("dupe_ffmpeg_dir", "") or ""
        exe = fpmod.find_tool("ffmpeg")
        if not exe:
            self.ffmpeg_info.setText("FFmpeg wasn't found. Pick the folder that contains ffmpeg.exe above.")
            return
        try:
            ver = subprocess.run([exe, "-hide_banner", "-version"], capture_output=True, text=True, timeout=20,
                                 creationflags=0x08000000).stdout.splitlines()[0]
            hw = subprocess.run([exe, "-hide_banner", "-hwaccels"], capture_output=True, text=True, timeout=20,
                                creationflags=0x08000000).stdout.split()
            hw = [h for h in hw if h not in ("Hardware", "acceleration", "methods:")]
        except Exception as exc:
            self.ffmpeg_info.setText(f"FFmpeg failed to run: {exc}")
            return
        self.ffmpeg_info.setText(f"Using: {exe}\n{ver}\nHardware decoders this FFmpeg supports: "
                                 f"{', '.join(hw) or 'none'} (your PC also needs a matching GPU and driver)")

    def _clear_fingerprints(self):
        if QMessageBox.question(self, "Clear saved fingerprints",
                                "Forget every saved video fingerprint? The next scan will read all videos again "
                                "(slow), but it picks up new settings like the sample spacing.") \
                != QMessageBox.StandardButton.Yes:
            return
        from ..dupes.store import Store
        Store().clear()
        self.ffmpeg_info.setText("Saved fingerprints cleared. The next scan reads every video again.")

    def _about_box(self):
        box = QGroupBox("Tools and information")
        v = QVBoxLayout(box)
        mpv = self.engine.mpv

        def prop(name):
            try:
                return mpv._get_property(name)
            except Exception:
                return None

        decoders = prop("decoder-list") or []
        from .. import __version__, SUPPORT_URL
        info = QLabel(f"Iron Will {__version__}  ·  mpv {str(prop('mpv-version') or '').replace('mpv ', '')}  ·  FFmpeg "
                      f"{prop('ffmpeg-version') or '?'}  ·  {len(decoders)} decoders available")
        info.setObjectName("note")
        info.setWordWrap(True)
        v.addWidget(info)
        row = QHBoxLayout()
        for text, fn in (("Import from MPC-BE…", self._import_mpcbe),
                         ("Open settings folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(DATA_DIR)))),
                         ("Reset everything", self._reset_all)) +                         ((("Support Iron Will ♥", lambda: QDesktopServices.openUrl(QUrl(SUPPORT_URL))),) if SUPPORT_URL else ()):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        v.addLayout(row)
        return box

    # Data flow -------------------------------------------------------------------------------------------
    def _load(self, values):
        for key, (_get, set_) in self.fields.items():
            set_(values.get(key, ALL[key].default if key in ALL else None))

    def _collect(self):
        return {key: get() for key, (get, _set) in self.fields.items()}

    def _apply(self):
        new = self._collect()
        changed = [k for k, v in new.items() if self.cfg.values.get(k) != v]
        self.cfg.values.update(new)
        self.cfg.save()
        failed = apply_to_mpv(self.engine.mpv, self.cfg.values, only=changed) if changed else []
        self.win.apply_settings()
        if failed:
            self.status.setText("Not applied: " + "; ".join(f"{l} ({e})" for l, e in failed[:3]))
        else:
            self.status.setText("Saved ✓" if changed else "")
        self._set_look(self.status, "ok", not failed)
        # Flash solid red, then settle back to the quiet "nothing to apply" state.
        self.baseline = new
        self._set_look(self.apply_btn, "flash", True)
        QTimer.singleShot(350, lambda: (self._set_look(self.apply_btn, "flash", False), self._refresh_dirty()))
        return not failed

    def _ok(self):
        if self._apply():
            self.accept()

    def _page_defaults(self):
        page_id = self.stack.currentWidget().property("page_id")
        d = defaults()
        for key in self.page_keys.get(page_id, []):
            self.fields[key][1](d.get(key))

    def _reset_all(self):
        if QMessageBox.question(self, "Reset everything", "Put every option back to its default?") \
                == QMessageBox.StandardButton.Yes:
            self._load(defaults())
            self.status.setText("Defaults loaded. Press OK or Apply to save.")

    def _import_mpcbe(self):
        path = import_mpcbe.find_ini()
        if not path:
            f, _ = QFileDialog.getOpenFileName(self, "Find mpc-be64.ini", os.environ.get("APPDATA", ""),
                                               "MPC-BE settings (mpc-be*.ini)")
            path = Path(f) if f else None
        if not path:
            return
        changes, notes, skipped = import_mpcbe.read(path)
        msg = ("These MPC-BE settings will be copied:\n\n• " + "\n• ".join(notes) +
               "\n\nNot copied:\n\n• " + "\n• ".join(skipped) +
               "\n\nYour MPC-BE settings file is only read, never changed.")
        box = QMessageBox(QMessageBox.Icon.Question, "Import from MPC-BE", msg,
                          QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel, self)
        box.setStyleSheet(themed(STYLE))
        if box.exec() == QMessageBox.StandardButton.Ok:
            current = self._collect()
            current.update(changes)
            self._load(current)
            self.status.setText(f"Imported {len(changes)} settings from MPC-BE. Press OK or Apply to save.")

    def showEvent(self, e):
        super().showEvent(e)
        try:  # dark title bar, matching the player window
            import ctypes
            val = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 20, ctypes.byref(val), 4)
        except Exception:
            pass

    def select_page(self, page_id):
        if page_id in self.tree_items:
            self.tree.setCurrentItem(self.tree_items[page_id])

    def _show_page(self, item, _prev=None):
        if item:
            self.stack.setCurrentIndex(item.data(0, Qt.ItemDataRole.UserRole))
            self.header.setText(self.stack.currentWidget().property("title"))
