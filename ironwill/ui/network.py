"""File > Open from Network: browse media servers (Plex, NAS, Windows Media sharing, another PC running Iron Will)
and play from them. Folders open in place; Back goes up a level."""
import threading

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout

from .. import dlna


class NetworkBrowser(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Open from Network")
        self.resize(560, 520)
        self.stack = []  # [(control_url, object_id, title)] from the server down to the open folder
        self.where = QLabel("Looking for media servers on your network…")
        self.list = QListWidget()
        self.list.itemActivated.connect(self._open)
        self.back = QPushButton("Back")
        self.back.clicked.connect(self._up)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._servers)
        buttons = QHBoxLayout()
        buttons.addWidget(self.back)
        buttons.addStretch()
        buttons.addWidget(refresh)
        lay = QVBoxLayout(self)
        lay.addWidget(self.where)
        lay.addWidget(self.list)
        lay.addLayout(buttons)
        self._servers()

    def _run(self, work, done):
        """Network calls can take seconds: run them off the UI thread, then show the result."""
        box = {}

        def go():
            try:
                box["ok"] = work()
            except Exception as e:  # unreachable server, malformed reply
                box["err"] = str(e)
        t = threading.Thread(target=go, daemon=True)
        t.start()

        def check():
            if t.is_alive():
                QTimer.singleShot(150, check)
            elif "err" in box:
                self.where.setText(f"Couldn't read that ({box['err'][:80]})")
            else:
                done(box["ok"])
        check()

    def _fill(self, rows):
        self.list.clear()
        for kind, title, ref in rows:
            it = QListWidgetItem(("📁  " if kind in ("folder", "server") else "▶  ") + title)
            it.setData(Qt.ItemDataRole.UserRole, (kind, title, ref))
            self.list.addItem(it)
        self.back.setEnabled(bool(self.stack))

    def _servers(self):
        self.stack = []
        self.where.setText("Looking for media servers on your network…")
        self.list.clear()

        def done(found):
            self.where.setText(f"{len(found)} media server(s) found" if found else
                               "No media servers found (Plex, NAS or Windows media sharing must be on)")
            self._fill([("server", name, ctrl) for name, ctrl in found])
        self._run(dlna.find_servers, done)

    def _show_folder(self):
        ctrl, oid, _title = self.stack[-1]
        self.where.setText(" › ".join(t for _c, _o, t in self.stack))
        self._run(lambda: dlna.browse(ctrl, oid), self._fill)

    def _open(self, item):
        kind, title, ref = item.data(Qt.ItemDataRole.UserRole)
        if kind == "server":
            self.stack = [(ref, "0", title)]
            self._show_folder()
        elif kind == "folder":
            self.stack.append((self.stack[-1][0], ref, title))
            self._show_folder()
        else:
            self.win.open_network_url(ref, title)
            self.accept()

    def _up(self):
        if len(self.stack) > 1:
            self.stack.pop()
            self._show_folder()
        else:
            self._servers()
