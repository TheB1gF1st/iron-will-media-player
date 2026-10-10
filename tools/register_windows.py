"""Registers Iron Will Media Player with Windows as a video player (current user only, no admin needed):
an "Iron Will" file type with the app icon, an entry in every video type's "Open with" list, and a Default Apps
entry. Windows only lets *you* pick defaults, so this opens Settings at Iron Will's page for the final click.

    E:\\PythonMedia\\python.exe tools\\register_windows.py            register + open Settings
    E:\\PythonMedia\\python.exe tools\\register_windows.py --remove   undo everything this added
"""
import ctypes
import os
import sys
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "IronWill.exe"  # native launcher (tools/build_launcher.py): Windows lists real programs, not scripts
ICON = ROOT / "ironwill" / "assets" / "iron-will.ico"
APP_NAME = "Iron Will Media Player"
PROGID = "IronWill.Video"
CAPS = r"Software\IronWill\MediaPlayer\Capabilities"
VIDEO_EXTS = [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".flv", ".ts", ".m2ts", ".mts", ".mpg",
              ".mpeg", ".vob", ".ogv", ".3gp", ".3g2", ".divx", ".rmvb", ".rm", ".asf", ".f4v", ".mxf", ".ogm", ".qt",
              ".mk3d", ".m2v", ".mp2v", ".mpe", ".mpv2", ".wtv", ".dvr-ms", ".y4m", ".hevc", ".avc", ".264", ".265"]
OLD_APP_KEYS = [r"Software\Classes\Applications\IronWill.pyw", r"Software\Classes\Applications\Run Iron Will.cmd"]
HKCU = winreg.HKEY_CURRENT_USER


def set_value(path, name, value):
    with winreg.CreateKeyEx(HKCU, path, 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def delete_tree(path):
    try:
        with winreg.OpenKey(HKCU, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    delete_tree(path + "\\" + winreg.EnumKey(k, 0))
                except OSError:
                    break
        winreg.DeleteKey(HKCU, path)
    except FileNotFoundError:
        pass


def delete_value(path, name):
    try:
        with winreg.OpenKey(HKCU, path, 0, winreg.KEY_WRITE) as k:
            winreg.DeleteValue(k, name)
    except FileNotFoundError:
        pass


def refresh_shell():
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED


def register():
    if not EXE.exists():
        sys.exit("IronWill.exe is missing: run tools\\build_launcher.py first")
    for old in OLD_APP_KEYS:  # earlier script-based entries ("Run Iron Will" with no icon)
        delete_tree(old)
    command = f'"{EXE}" "%1"'
    cls = rf"Software\Classes\{PROGID}"
    set_value(cls, "", "Video (Iron Will)")
    set_value(cls, "FriendlyTypeName", "Video")
    set_value(cls + r"\DefaultIcon", "", f'"{ICON}",0')
    set_value(cls + r"\shell", "", "open")
    set_value(cls + r"\shell\open", "", "Play with Iron Will")
    set_value(cls + r"\shell\open", "FriendlyAppName", APP_NAME)
    set_value(cls + r"\shell\open\command", "", command)
    app = r"Software\Classes\Applications\IronWill.exe"
    set_value(app, "FriendlyAppName", APP_NAME)
    set_value(app + r"\DefaultIcon", "", f'"{EXE}",0')
    set_value(app + r"\shell\open\command", "", command)
    for ext in VIDEO_EXTS:
        set_value(app + r"\SupportedTypes", ext, "")

    set_value(CAPS, "ApplicationName", APP_NAME)
    set_value(CAPS, "ApplicationDescription", "I will play anything: a Movies & TV look with MPC-BE depth, built on mpv.")
    set_value(CAPS, "ApplicationIcon", f'"{EXE}",0')
    for ext in VIDEO_EXTS:
        set_value(CAPS + r"\FileAssociations", ext, PROGID)
        set_value(rf"Software\Classes\{ext}\OpenWithProgids", PROGID, "")
    set_value(r"Software\RegisteredApplications", APP_NAME, CAPS)
    refresh_shell()
    print(f"Registered {APP_NAME} for {len(VIDEO_EXTS)} video types.")


def remove():
    delete_tree(rf"Software\Classes\{PROGID}")
    delete_tree(r"Software\Classes\Applications\IronWill.exe")
    for old in OLD_APP_KEYS:
        delete_tree(old)
    delete_tree(r"Software\IronWill")
    delete_value(r"Software\RegisteredApplications", APP_NAME)
    for ext in VIDEO_EXTS:
        delete_value(rf"Software\Classes\{ext}\OpenWithProgids", PROGID)
    refresh_shell()
    print(f"Removed {APP_NAME}'s Windows registration. (Pick another default player in Settings > Default apps.)")


if __name__ == "__main__":
    if "--remove" in sys.argv:
        remove()
    else:
        register()
        if "--no-settings" not in sys.argv:
            os.startfile("ms-settings:defaultapps?registeredAppUser=" + APP_NAME.replace(" ", "%20"))
