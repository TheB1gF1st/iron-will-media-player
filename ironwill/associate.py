"""Windows file-type registration (current user only, no admin needed): an "Iron Will" file type with the app icon,
an entry in each type's "Open with" list, and a Default Apps entry. Windows only lets the user pick defaults, so
Settings opens at Iron Will's page for the final click. Used by Options > File Types and tools/register_windows.py."""
import ctypes
import os
import sys
import winreg
from pathlib import Path

from .paths import APP_DIR, FROZEN

# The release says its full name in "Open with"; the source copy on the author's PC is just "Iron Will", with its
# own keys, so the two can be registered side by side without telling each other apart only by their path.
APP_NAME = "Iron Will Media Player" if FROZEN else "Iron Will"
PROGID = "IronWill.Video" if FROZEN else "IronWill.Dev.Video"
PROGID_AUDIO = "IronWill.Audio" if FROZEN else "IronWill.Dev.Audio"
CAPS = r"Software\IronWill\MediaPlayer\Capabilities" if FROZEN else r"Software\IronWill\MediaPlayerDev\Capabilities"
VIDEO_EXTS = [".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".flv", ".ts", ".m2ts", ".mts", ".mpg",
              ".mpeg", ".vob", ".ogv", ".3gp", ".3g2", ".divx", ".rmvb", ".rm", ".asf", ".f4v", ".mxf", ".ogm", ".qt",
              ".mk3d", ".m2v", ".mp2v", ".mpe", ".mpv2", ".wtv", ".dvr-ms", ".y4m", ".hevc", ".avc", ".264", ".265"]
AUDIO_EXTS = [".mp3", ".flac", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".wma", ".ac3", ".eac3", ".dts",
              ".mka", ".ape", ".wv", ".alac", ".aif", ".aiff", ".tta", ".dsf", ".dff", ".mpc", ".amr", ".au", ".mid",
              ".midi"]
OLD_APP_KEYS = [r"Software\Classes\Applications\IronWill.pyw", r"Software\Classes\Applications\Run Iron Will.cmd"]
HKCU = winreg.HKEY_CURRENT_USER


def program():
    """The .exe Windows should start: the release build itself, or the launcher next to the scripts."""
    return Path(sys.executable) if FROZEN else APP_DIR / "IronWill.exe"


def _set(path, name, value):
    with winreg.CreateKeyEx(HKCU, path, 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def _get(path, name):
    try:
        with winreg.OpenKey(HKCU, path) as k:
            return str(winreg.QueryValueEx(k, name)[0])
    except OSError:
        return ""


def _delete_tree(path):
    try:
        with winreg.OpenKey(HKCU, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    _delete_tree(path + "\\" + winreg.EnumKey(k, 0))
                except OSError:
                    break
        winreg.DeleteKey(HKCU, path)
    except FileNotFoundError:
        pass


def _delete_value(path, name):
    try:
        with winreg.OpenKey(HKCU, path, 0, winreg.KEY_WRITE) as k:
            winreg.DeleteValue(k, name)
    except (FileNotFoundError, OSError):
        pass


def _refresh_shell():
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED


def registered(ext):
    try:
        with winreg.OpenKey(HKCU, CAPS + r"\FileAssociations") as k:
            winreg.QueryValueEx(k, ext)
            return True
    except OSError:
        return False


def register(video=True, audio=False):
    exe = program()
    if not exe.exists():
        raise FileNotFoundError(f"{exe} is missing (in the source version, run tools\\build_launcher.py first)")
    icon = APP_DIR / "ironwill" / "assets" / "iron-will.ico"
    icon = f'"{icon}",0' if icon.exists() else f'"{exe}",0'
    for old in OLD_APP_KEYS:
        _delete_tree(old)
    mine = _get(r"Software\Classes\IronWill.Video\shell\open\command", "").lower().startswith(f'"{exe}"'.lower())
    if not FROZEN and mine:
        # Before the split the source copy registered under the release's name and keys: hand them back (only when
        # they still point at this source copy, never when the real release owns them)
        _delete_tree(r"Software\Classes\IronWill.Video")
        _delete_tree(r"Software\Classes\IronWill.Audio")
        _delete_tree(r"Software\IronWill\MediaPlayer")
        _delete_value(r"Software\RegisteredApplications", "Iron Will Media Player")
        for ext in VIDEO_EXTS + AUDIO_EXTS:
            _delete_value(rf"Software\Classes\{ext}\OpenWithProgids", "IronWill.Video")
            _delete_value(rf"Software\Classes\{ext}\OpenWithProgids", "IronWill.Audio")
    command = f'"{exe}" "%1"'
    for progid, label in ((PROGID, "Video"), (PROGID_AUDIO, "Audio")):
        cls = rf"Software\Classes\{progid}"
        _set(cls, "", f"{label} (Iron Will)")
        _set(cls, "FriendlyTypeName", label)
        _set(cls + r"\DefaultIcon", "", icon)
        _set(cls + r"\shell", "", "open")
        _set(cls + r"\shell\open", "", "Play with Iron Will")
        _set(cls + r"\shell\open", "FriendlyAppName", APP_NAME)
        _set(cls + r"\shell\open\command", "", command)
    app = rf"Software\Classes\Applications\{exe.name}"
    _set(app, "FriendlyAppName", APP_NAME)
    _set(app + r"\DefaultIcon", "", icon)
    _set(app + r"\shell\open\command", "", command)
    _set(CAPS, "ApplicationName", APP_NAME)
    _set(CAPS, "ApplicationDescription", "I will play anything: a Movies & TV look with MPC-BE depth, built on mpv.")
    _set(CAPS, "ApplicationIcon", f'"{exe}",0')
    for exts, on, progid in ((VIDEO_EXTS, video, PROGID), (AUDIO_EXTS, audio, PROGID_AUDIO)):
        for ext in exts:
            # No SupportedTypes under Applications: Windows would list the app twice in "Open with" (once from it,
            # once from the file type below), and the second entry has no proper icon
            _delete_value(app + r"\SupportedTypes", ext)
            if on:
                _set(CAPS + r"\FileAssociations", ext, progid)
                _set(rf"Software\Classes\{ext}\OpenWithProgids", progid, "")
            else:
                _delete_value(CAPS + r"\FileAssociations", ext)
                _delete_value(rf"Software\Classes\{ext}\OpenWithProgids", progid)
    _set(r"Software\RegisteredApplications", APP_NAME, CAPS)
    _refresh_shell()


def remove():
    exe = program()
    for key in (rf"Software\Classes\{PROGID}", rf"Software\Classes\{PROGID_AUDIO}",
                rf"Software\Classes\Applications\{exe.name}",
                CAPS.rsplit("\\", 1)[0], *OLD_APP_KEYS):  # not all of Software\IronWill: the player's settings live there
        _delete_tree(key)
    _delete_value(r"Software\RegisteredApplications", APP_NAME)
    for ext in VIDEO_EXTS + AUDIO_EXTS:
        _delete_value(rf"Software\Classes\{ext}\OpenWithProgids", PROGID)
        _delete_value(rf"Software\Classes\{ext}\OpenWithProgids", PROGID_AUDIO)
    _refresh_shell()


def open_default_apps():
    os.startfile("ms-settings:defaultapps?registeredAppUser=" + APP_NAME.replace(" ", "%20"))
