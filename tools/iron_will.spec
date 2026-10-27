# PyInstaller recipe for the ready-to-run release (no Python needed on the user's PC).
#   E:\PythonMedia\python.exe tools\build_release.py
# builds "Iron Will Media Player\" with Iron Will.exe, then adds libmpv-2.dll and FFmpeg next to it.
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent
# The offline foreign-dialogue translator (MIT). Its speech model is downloaded on first use, not bundled.
fw_datas, fw_bins, fw_hidden = [], [], []
for pkg in ("faster_whisper", "ctranslate2", "tokenizers", "onnxruntime", "av"):
    d, b, h = collect_all(pkg)
    fw_datas += d; fw_bins += b; fw_hidden += h

a = Analysis(
    [str(ROOT / "IronWill.pyw")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "ironwill" / "assets"), "ironwill/assets")] + fw_datas,
    binaries=fw_bins,
    hiddenimports=["mpv", "win32com.client", "pythoncom", "pywintypes"] + fw_hidden,
    excludes=["tkinter", "matplotlib", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtCharts", "PySide6.QtDataVisualization",
              "PySide6.QtMultimedia", "PySide6.QtPdf", "PySide6.QtDesigner", "PySide6.QtBluetooth"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Iron Will",
    icon=str(ROOT / "ironwill" / "assets" / "iron-will.ico"),
    console=False,
    # Written by build_release.py: Windows shows its FileDescription in "Open with" ("Iron Will Media Player")
    version=os.environ.get("IW_VERSION_FILE"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="Iron Will Media Player")
