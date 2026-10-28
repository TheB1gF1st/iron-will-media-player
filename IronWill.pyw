"""Iron Will Media Player - start here.  Usage: IronWill.pyw [file]"""
import locale
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QIcon, QSurfaceFormat
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

INSTANCE_NAME = "IronWillMediaPlayer.SingleInstance"


def give_native_code_a_valid_stdout_stderr():
    """Without a console (the packaged Iron Will.exe, or pythonw) the C runtime's stdout/stderr aren't valid. When
    native code like libmpv's DVD reader writes a message there, the Universal CRT can treat it as an invalid
    parameter and kill the process on the spot (0xC0000409 in ucrtbase.dll). Point them at NUL instead.
    Set IW_NO_STDIO_FIX=1 to skip this (QA: to confirm the crash comes back without it), and IW_STDIO_FIX_LOG=<file>
    to write down what it did (QA: proof that it ran).

    Three layers have to be fixed, because each one remembers "no console" on its own:
      1. the C stdio streams (stdin/stdout/stderr FILE*): with no console they're stamped fd -2 at startup and a
         write to them is the invalid-parameter crash. Only freopen() re-stamps them; dup2 underneath doesn't.
      2. the C file descriptors 0/1/2 (dup2 onto NUL), for code that write()s to the numbers directly.
      3. the Win32 standard handles (SetStdHandle), for code that calls GetStdHandle."""
    import os
    import ctypes
    import msvcrt
    notes = []
    # What the process really has, for the QA log: console window, the UCRT's stdio fds (-2 = "no console"),
    # and the Win32 standard handles. Python's sys.stdout alone can't tell (a launcher may pass its own pipes).
    no_console_fd = no_console_window = False
    try:
        k32 = ctypes.windll.kernel32
        k32.GetConsoleWindow.restype = ctypes.c_void_p
        k32.GetStdHandle.restype = ctypes.c_void_p
        ucrt = ctypes.CDLL("ucrtbase")
        ucrt.__acrt_iob_func.restype, ucrt.__acrt_iob_func.argtypes = ctypes.c_void_p, [ctypes.c_uint]
        ucrt._fileno.argtypes = [ctypes.c_void_p]
        fds = [ucrt._fileno(ucrt.__acrt_iob_func(i)) for i in (0, 1, 2)]
        no_console_fd = any(fd < 0 for fd in fds)
        no_console_window = not k32.GetConsoleWindow()
        handles = [k32.GetStdHandle(ctypes.c_ulong(s & 0xFFFFFFFF)) for s in (-10, -11, -12)]
        notes.append(f"console window: {'yes' if k32.GetConsoleWindow() else 'no'}; ucrt stdio fds: {fds}; "
                     f"win32 std handles: {[hex(h) if h else None for h in handles]}; "
                     f"sys.stdout/err None: {sys.stdout is None}/{sys.stderr is None}")
    except Exception as exc:
        notes.append(f"probe error: {exc!r}")
    # QA (2026-10-28): with no console window the ISO crashed even when a launcher passed valid stdio pipes, and
    # the repair fixed it either way. So: no console window = always repair.
    needed = no_console_window or no_console_fd or sys.stdout is None or sys.stderr is None
    if os.environ.get("IW_NO_STDIO_FIX"):
        notes.append("fix skipped: IW_NO_STDIO_FIX set")
    elif not (needed or os.environ.get("IW_FORCE_STDIO_FIX")):
        notes.append("fix skipped: stdio already valid")
    else:
        notes.append("fix running" + (" (forced by IW_FORCE_STDIO_FIX)" if not needed else ""))
        # 1. stdio streams in the Universal CRT (what libmpv and Python use), and in old msvcrt.dll if it's loaded
        try:
            ucrt = ctypes.CDLL("ucrtbase")
            ucrt.__acrt_iob_func.restype, ucrt.__acrt_iob_func.argtypes = ctypes.c_void_p, [ctypes.c_uint]
            ucrt.freopen.restype = ctypes.c_void_p
            ucrt.freopen.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p]
            for i, mode in ((0, b"r"), (1, b"w"), (2, b"w")):
                ok = ucrt.freopen(b"NUL", mode, ucrt.__acrt_iob_func(i))
                notes.append(f"ucrt freopen std{i}: {'ok' if ok else 'FAILED'}")
        except Exception as exc:
            notes.append(f"ucrt freopen error: {exc!r}")
        try:
            k32 = ctypes.windll.kernel32
            k32.GetModuleHandleW.restype = ctypes.c_void_p
            if k32.GetModuleHandleW("msvcrt.dll"):  # only touch it if something actually uses it
                old = ctypes.CDLL("msvcrt")
                old.__iob_func.restype = ctypes.c_void_p
                old.freopen.restype = ctypes.c_void_p
                old.freopen.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p]
                base = old.__iob_func()
                for i, mode in ((0, b"r"), (1, b"w"), (2, b"w")):
                    ok = old.freopen(b"NUL", mode, ctypes.c_void_p(base + i * 48))  # sizeof(FILE) = 48 on x64
                    notes.append(f"msvcrt freopen std{i}: {'ok' if ok else 'FAILED'}")
        except Exception as exc:
            notes.append(f"msvcrt freopen error: {exc!r}")
        # 2. file descriptors 0/1/2  3. Win32 standard handles
        try:
            null_fd = os.open(os.devnull, os.O_RDWR)
            for fd in (0, 1, 2):
                os.dup2(null_fd, fd)
            handle = msvcrt.get_osfhandle(null_fd)
            for std in (-10, -11, -12):  # STD_INPUT / STD_OUTPUT / STD_ERROR_HANDLE
                ctypes.windll.kernel32.SetStdHandle(ctypes.c_ulong(std & 0xFFFFFFFF), ctypes.c_void_p(handle))
            notes.append("fds 0-2 + Win32 std handles -> NUL: ok")
        except Exception as exc:
            notes.append(f"fd/handle error: {exc!r}")
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
    log_path = os.environ.get("IW_STDIO_FIX_LOG")
    if log_path:
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"pid {os.getpid()}: " + "; ".join(notes) + "\n")
        except Exception:
            pass


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
    give_native_code_a_valid_stdout_stderr()  # before libmpv or anything native loads
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
