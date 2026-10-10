"""Iron Will Media Player - start here.  Usage: IronWill.pyw [file]"""
import locale
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QIcon, QSurfaceFormat
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

INSTANCE_NAME = "IronWillMediaPlayer.SingleInstance"


def hand_off_to_running_player(path):
    """If Iron Will is already open, give it the file (or just bring it forward) and return True."""
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE_NAME)
    if not sock.waitForConnected(300):
        return False
    try:  # let the running window take the foreground (Windows blocks this otherwise)
        import ctypes
        ctypes.windll.user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
    except Exception:
        pass
    sock.write(QByteArray((path or "").encode("utf-8")))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def listen_for_other_launches(win):
    """Double-clicking another video while Iron Will is open plays it here instead of opening a second player."""
    QLocalServer.removeServer(INSTANCE_NAME)  # clear a stale name left by a crash
    server = QLocalServer(win)
    server.listen(INSTANCE_NAME)

    def on_connection():
        conn = server.nextPendingConnection()
        buf = bytearray()

        def finish():  # the other launch disconnects once it has sent the path (possibly empty)
            buf.extend(bytes(conn.readAll()))
            path = buf.decode("utf-8", "replace").strip()
            if path:
                win.open_path(path)
            if win.isMinimized():
                win.showNormal()
            win.raise_()
            win.activateWindow()
            conn.deleteLater()

        conn.readyRead.connect(lambda: buf.extend(bytes(conn.readAll())))
        conn.disconnected.connect(finish)

    server.newConnection.connect(on_connection)
    return server


def main():
    try:  # own taskbar identity, so Windows shows the Iron Will icon instead of Python's
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("IronWill.MediaPlayer")
        # Dark native menus (title-bar menu): uxtheme's SetPreferredAppMode(ForceDark) + FlushMenuThemes,
        # the same undocumented calls mpv and Explorer use on Windows 10 1903+.
        ctypes.windll.uxtheme[135](2)
        ctypes.windll.uxtheme[136]()
    except Exception:
        pass
    fmt = QSurfaceFormat()
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QApplication(sys.argv)
    start_file = sys.argv[1] if len(sys.argv) > 1 else None
    from ironwill.settings import Config
    single = not Config()["allow_multiple"]  # allowed by default: every video gets its own window
    if single and hand_off_to_running_player(start_file):
        return
    app.setApplicationName("Iron Will Media Player")
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "ironwill" / "assets" / "iron-will.ico")))
    locale.setlocale(locale.LC_NUMERIC, "C")  # libmpv needs C number formatting

    from ironwill.ui.window import MainWindow  # imported after QApplication so libmpv loads cleanly
    win = MainWindow(start_file)
    if single:
        win._instance_server = listen_for_other_launches(win)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
