"""Compiles tools/launcher/IronWill.cs into IronWill.exe (next to IronWill.pyw) with the app icon embedded,
using the C# compiler that ships with Windows (.NET Framework 4).

    E:\\PythonMedia\\python.exe tools\\build_launcher.py"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSC = Path(r"C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe")
OUT = ROOT / "IronWill.exe"

subprocess.run([str(CSC), "/nologo", "/target:winexe", "/optimize+", "/reference:System.Windows.Forms.dll",
                f"/win32icon:{ROOT / 'ironwill' / 'assets' / 'iron-will.ico'}", f"/out:{OUT}",
                str(ROOT / "tools" / "launcher" / "IronWill.cs")], check=True)
print("built", OUT)
