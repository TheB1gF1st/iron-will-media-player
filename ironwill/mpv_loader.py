"""Finds libmpv before `import mpv` runs. Looks next to the app first, then in E:\\MPV."""
import os
import sys
from pathlib import Path

from .paths import APP_DIR

SEARCH = [APP_DIR, APP_DIR / "mpv", Path(r"E:\MPV")]  # bundled copy first; E:\MPV is the author's dev setup
DLL_NAMES = ("libmpv-2.dll", "mpv-2.dll", "mpv-1.dll")


def load():
    # DVD images crashed Iron Will whenever it ran without a console (the packaged exe, pythonw): 0xC0000409,
    # invalid parameter in ucrtbase. The crash dump (2026-10-28) points into libmpv's built-in libdvdread right at
    # "Attempting to retrieve all CSS keys", the up-front crack-every-key pass it runs when opening a disc.
    # DVDREAD_NOKEYS skips that pass (encrypted discs still get each title's key when the title opens), and
    # DVDCSS_VERBOSE=0 stops libdvdcss printing to a stderr that doesn't exist. Set before libmpv loads so its
    # getenv() sees them; a value the user set themselves wins.
    os.environ.setdefault("DVDREAD_NOKEYS", "1")
    os.environ.setdefault("DVDCSS_VERBOSE", "0")
    for folder in SEARCH:
        if any((folder / name).exists() for name in DLL_NAMES):
            os.add_dll_directory(str(folder))
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
            break
    import mpv  # noqa: F401  (raises a clear error if libmpv still isn't found)
    return mpv
