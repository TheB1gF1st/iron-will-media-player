"""Finds libmpv before `import mpv` runs. Looks next to the app first, then in E:\\MPV."""
import os
import sys
from pathlib import Path

APP_DIR = Path(sys.argv[0]).resolve().parent
SEARCH = [APP_DIR, APP_DIR / "mpv", Path(r"E:\MPV")]
DLL_NAMES = ("libmpv-2.dll", "mpv-2.dll", "mpv-1.dll")


def load():
    for folder in SEARCH:
        if any((folder / name).exists() for name in DLL_NAMES):
            os.add_dll_directory(str(folder))
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
            break
    import mpv  # noqa: F401  (raises a clear error if libmpv still isn't found)
    return mpv
