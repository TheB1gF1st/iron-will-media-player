"""Builds the ready-to-run release zip: PyInstaller bundle + libmpv-2.dll + FFmpeg + licence notes.

    E:\\PythonMedia\\python.exe tools\\build_release.py [version]

Output: E:\\IronWillMediaPlayerRepo\\Release\\Iron-Will-Media-Player-<version>-win64.zip"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT.parent / "Release"
LIBMPV = Path(r"E:\MPV\libmpv-2.dll")
FFMPEG_DIR = Path(r"E:\_Misc\FFMpeg8.1.2EssentialsBuild")
VERSION = sys.argv[1] if len(sys.argv) > 1 else __import__("re").search(
    r'__version__ = "(.+?)"', (ROOT / "ironwill" / "__init__.py").read_text()).group(1)

THIRD_PARTY = """Iron Will Media Player bundles these programs, each under its own licence:

- mpv / libmpv (libmpv-2.dll): GPL-2.0-or-later. https://mpv.io  (Windows build: shinchiro/mpv-winbuild-cmake)
- FFmpeg (ffmpeg\\ffmpeg.exe, ffmpeg\\ffprobe.exe): GPL-3.0, "essentials" build. https://ffmpeg.org
  (see ffmpeg\\LICENSE). Used only by Find Duplicates.
- Poiret One font by Denis Masharov (start screen): SIL Open Font License 1.1. Licence text: _internal\\ironwill\\assets\\fonts\\PoiretOne-OFL.txt
- Qt for Python (PySide6): LGPL-3.0. https://www.qt.io/qt-for-python
- Python: PSF License. https://python.org
- NumPy: BSD-3-Clause. pywin32: PSF License.
- faster-whisper, CTranslate2, ONNX Runtime: MIT. Whisper speech model (downloaded on first use): MIT.
- Subtitles found online come from OpenSubtitles.com.

Iron Will itself is GPL-3.0 (see LICENSE). Source code: https://github.com/TheB1gF1st/iron-will-media-player
"""


VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=({v}, 0), prodvers=({v}, 0), mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
          StringStruct('CompanyName', 'TheB1gF1st'),
          StringStruct('FileDescription', 'Iron Will Media Player'),
          StringStruct('FileVersion', '{s}'),
          StringStruct('InternalName', 'Iron Will'),
          StringStruct('OriginalFilename', 'Iron Will.exe'),
          StringStruct('ProductName', 'Iron Will Media Player'),
          StringStruct('ProductVersion', '{s}')])]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])])])
"""


def main():
    dist, work = OUT / "dist", OUT / "build"
    work.mkdir(parents=True, exist_ok=True)
    nums = ", ".join(([p for p in VERSION.split(".") if p.isdigit()] + ["0", "0", "0"])[:3])
    (work / "version_info.txt").write_text(VERSION_INFO.format(v=nums, s=VERSION), encoding="utf-8")
    os.environ["IW_VERSION_FILE"] = str(work / "version_info.txt")
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
    if (ROOT / "opensubs.key").exists():
        shutil.copy2(ROOT / "opensubs.key", app / "opensubs.key")
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
