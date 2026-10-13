r"""Full-screen refresh-rate matching (MPC-BE: Auto-change full-screen monitor mode). Switches the monitor to a refresh
rate that's a whole multiple of the video's frame rate (24 fps -> 24/48/120/144 Hz), temporarily (CDS_FULLSCREEN),
and puts it back when full screen ends."""
import ctypes
from ctypes import wintypes

u32 = ctypes.windll.user32
ENUM_CURRENT_SETTINGS = -1
CDS_FULLSCREEN = 0x4
DM_DISPLAYFREQUENCY = 0x400000
_changed = set()  # devices we switched


class DEVMODEW(ctypes.Structure):
    _fields_ = [("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD),
                ("dmDriverVersion", wintypes.WORD), ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD),
                ("dmFields", wintypes.DWORD), ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
                ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
                ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
                ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short), ("dmFormName", wintypes.WCHAR * 32),
                ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD),
                ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD),
                ("dmDisplayFrequency", wintypes.DWORD), ("dmICMMethod", wintypes.DWORD),
                ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD), ("dmDitherType", wintypes.DWORD),
                ("dmReserved1", wintypes.DWORD), ("dmReserved2", wintypes.DWORD),
                ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD)]


def _mode(device, index):
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    return dm if u32.EnumDisplaySettingsW(device, index, ctypes.byref(dm)) else None


def current_hz(device):
    dm = _mode(device, ENUM_CURRENT_SETTINGS)
    return dm.dmDisplayFrequency if dm else 0


def match(device, fps):
    """Switch `device` (e.g. \\\\.\\DISPLAY1) to the best refresh rate for `fps`. Returns True if it changed."""
    cur = _mode(device, ENUM_CURRENT_SETTINGS)
    if not cur or fps < 10:
        return False
    target = round(fps)  # 23.976 -> 24, 29.97 -> 30, 59.94 -> 60
    if cur.dmDisplayFrequency % target == 0:
        return False  # already a whole multiple: nothing to gain
    rates, i = set(), 0
    while (dm := _mode(device, i)) is not None:
        if (dm.dmPelsWidth, dm.dmPelsHeight, dm.dmBitsPerPel) == (cur.dmPelsWidth, cur.dmPelsHeight, cur.dmBitsPerPel):
            rates.add(dm.dmDisplayFrequency)
        i += 1
    good = sorted(r for r in rates if r >= target and r % target == 0)
    if not good:
        return False
    cur.dmDisplayFrequency = good[-1]  # the highest multiple keeps motion as smooth as possible
    cur.dmFields = DM_DISPLAYFREQUENCY
    if u32.ChangeDisplaySettingsExW(device, ctypes.byref(cur), None, CDS_FULLSCREEN, None) == 0:
        _changed.add(device)
        return True
    return False


def restore():
    """Put every monitor we changed back to its normal mode."""
    for device in list(_changed):
        u32.ChangeDisplaySettingsExW(device, None, None, 0, None)
        _changed.discard(device)


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]


def device_for_window(hwnd):
    """The GDI device name (like \\\\.\\DISPLAY1) of the monitor a window is on."""
    u32.MonitorFromWindow.restype = ctypes.c_void_p
    mon = u32.MonitorFromWindow(ctypes.c_void_p(hwnd), 2)  # MONITOR_DEFAULTTONEAREST
    info = MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(MONITORINFOEXW)
    return info.szDevice if u32.GetMonitorInfoW(ctypes.c_void_p(mon), ctypes.byref(info)) else ""
