"""Builds the ready-to-run release zip: PyInstaller bundle + libmpv-2.dll + FFmpeg + licence notes.

    E:\\PythonMedia\\python.exe tools\\build_release.py [version]

Output: E:\\IronWillMediaPlayerRepo\\Release\\Iron-Will-Media-Player-<version>-win64.zip"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT.parent / "Release"
LIBMPV = Path(r"E:\MPV\libmpv-2.dll")
FFMPEG_DIR = Path(r"E:\_Misc\FFMpeg8.1.2EssentialsBuild")
VERSION = sys.argv[1] if len(sys.argv) > 1 else "1.0.0"

THIRD_PARTY = """Iron Will Media Player bundles these programs, each under its own licence:

- mpv / libmpv (libmpv-2.dll): GPL-2.0-or-later. https://mpv.io  (Windows build: shinchiro/mpv-winbuild-cmake)
- FFmpeg (ffmpeg\\ffmpeg.exe, ffmpeg\\ffprobe.exe): GPL-3.0, "essentials" build. https://ffmpeg.org
  (see ffmpeg\\LICENSE). Used only by Find Duplicates.
- Qt for Python (PySide6): LGPL-3.0. https://www.qt.io/qt-for-python
- Python: PSF License. https://python.org
- NumPy: BSD-3-Clause. pywin32: PSF License.

Iron Will itself is GPL-3.0 (see LICENSE). Source code: https://github.com/TheB1gF1st/iron-will-media-player
"""


def main():
    dist, work = OUT / "dist", OUT / "build"
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(dist),
                    "--workpath", str(work), str(ROOT / "tools" / "iron_will.spec")], check=True)
    app = dist / "Iron Will Media Player"
    shutil.copy2(LIBMPV, app / "libmpv-2.dll")
    (app / "ffmpeg").mkdir(exist_ok=True)
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        shutil.copy2(FFMPEG_DIR / "bin" / name, app / "ffmpeg" / name)
    if (FFMPEG_DIR / "LICENSE").exists():
        shutil.copy2(FFMPEG_DIR / "LICENSE", app / "ffmpeg" / "LICENSE")
    shutil.copy2(ROOT / "LICENSE", app / "LICENSE.txt")
    (app / "THIRD-PARTY-NOTICES.txt").write_text(THIRD_PARTY, encoding="utf-8")
    (app / "README.txt").write_text(
        f"Iron Will Media Player {VERSION}\n\nDouble-click 'Iron Will.exe' to start. No installation needed: keep this "
        "folder anywhere (e.g. Documents or C:\\Program Files) and pin Iron Will.exe to Start or the taskbar.\n\n"
        "To make it your default player: right-click any video > Open with > Choose another app > More apps > "
        "Look for another app on this PC > pick 'Iron Will.exe' and tick 'Always'.\n\n"
        "Settings live in %APPDATA%\\IronWillMediaPlayer.\n", encoding="utf-8")
    zip_base = OUT / f"Iron-Will-Media-Player-{VERSION}-win64"
    archive = shutil.make_archive(str(zip_base), "zip", root_dir=dist, base_dir=app.name)
    print("built", archive, f"({Path(archive).stat().st_size / 1024 ** 2:.0f} MB)")


if __name__ == "__main__":
    main()
