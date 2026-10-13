"""Taskbar button extras through ITaskbarList3 with plain ctypes (no comtypes): a progress bar on the button and
previous / play-pause / next buttons in its thumbnail preview, like MPC-BE's "Use Windows 7+ taskbar features"."""
import ctypes
from ctypes import wintypes

ole32 = ctypes.windll.ole32
CLSID_TaskbarList = "{56FDF344-FD6D-11d0-958A-006097C9A090}"
IID_ITaskbarList3 = "{EA1AFB91-9E28-4B86-90E9-9E9F8A5EEFAF}"
THB_ICON, THB_TOOLTIP, THB_FLAGS = 0x2, 0x4, 0x8


class GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16), ("d", ctypes.c_ubyte * 8)]


class THUMBBUTTON(ctypes.Structure):
    _fields_ = [("dwMask", ctypes.c_uint32), ("iId", ctypes.c_uint32), ("iBitmap", ctypes.c_uint32),
                ("hIcon", ctypes.c_void_p), ("szTip", ctypes.c_wchar * 260), ("dwFlags", ctypes.c_uint32)]


def _guid(text):
    g = GUID()
    ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
    return g


def _glyph_icon(char, size=32):
    """A white Segoe Fluent / MDL2 glyph as an HICON, so the buttons match the player's controls."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QImage, QPainter
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    f = QFont("Segoe Fluent Icons")
    f.setPixelSize(int(size * 0.62))
    if not f.exactMatch():
        f = QFont("Segoe MDL2 Assets")
        f.setPixelSize(int(size * 0.62))
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, char)
    p.end()
    if hasattr(img, "toHICON"):  # Qt 6 on Windows
        try:
            return int(img.toHICON())
        except Exception:
            pass
    return _hicon_from_image(img)


def _hicon_from_image(img):
    """QImage (ARGB32) -> HICON through CreateIconIndirect."""
    gdi, u32 = ctypes.windll.gdi32, ctypes.windll.user32
    w, h = img.width(), img.height()

    class BITMAPV5HEADER(ctypes.Structure):
        _fields_ = [("size", ctypes.c_uint32), ("w", ctypes.c_int32), ("h", ctypes.c_int32), ("planes", ctypes.c_uint16),
                    ("bits", ctypes.c_uint16), ("comp", ctypes.c_uint32), ("sizeimg", ctypes.c_uint32),
                    ("xppm", ctypes.c_int32), ("yppm", ctypes.c_int32), ("used", ctypes.c_uint32),
                    ("important", ctypes.c_uint32), ("rmask", ctypes.c_uint32), ("gmask", ctypes.c_uint32),
                    ("bmask", ctypes.c_uint32), ("amask", ctypes.c_uint32), ("cstype", ctypes.c_uint32),
                    ("endpoints", ctypes.c_byte * 36), ("gr", ctypes.c_uint32), ("gg", ctypes.c_uint32),
                    ("gb", ctypes.c_uint32), ("intent", ctypes.c_uint32), ("profdata", ctypes.c_uint32),
                    ("profsize", ctypes.c_uint32), ("res", ctypes.c_uint32)]

    class ICONINFO(ctypes.Structure):
        _fields_ = [("fIcon", wintypes.BOOL), ("x", wintypes.DWORD), ("y", wintypes.DWORD),
                    ("mask", ctypes.c_void_p), ("color", ctypes.c_void_p)]
    hdr = BITMAPV5HEADER(size=ctypes.sizeof(BITMAPV5HEADER), w=w, h=-h, planes=1, bits=32, comp=3,
                         rmask=0x00FF0000, gmask=0x0000FF00, bmask=0x000000FF, amask=0xFF000000)
    bits = ctypes.c_void_p()
    gdi.CreateDIBSection.restype = ctypes.c_void_p
    color = gdi.CreateDIBSection(None, ctypes.byref(hdr), 0, ctypes.byref(bits), None, 0)
    ptr = img.constBits()
    ctypes.memmove(bits, int(ptr) if not hasattr(ptr, "tobytes") else ptr.tobytes(), w * h * 4) \
        if isinstance(ptr, int) else ctypes.memmove(bits, bytes(ptr), w * h * 4)
    gdi.CreateBitmap.restype = ctypes.c_void_p
    mask = gdi.CreateBitmap(w, h, 1, 1, None)
    info = ICONINFO(True, 0, 0, mask, color)
    u32.CreateIconIndirect.restype = ctypes.c_void_p
    return u32.CreateIconIndirect(ctypes.byref(info))


class TaskbarList:
    def __init__(self):
        ole32.CoInitialize(None)
        ptr = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(ctypes.byref(_guid(CLSID_TaskbarList)), None, 1,
                                    ctypes.byref(_guid(IID_ITaskbarList3)), ctypes.byref(ptr))
        if hr != 0 or not ptr:
            raise OSError(f"ITaskbarList3 unavailable ({hr:#x})")
        self.ptr = ptr
        self.vtbl = ctypes.cast(ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        self._call(3, [])  # HrInit
        self.icons = {}

    def _call(self, index, argtypes, *args):
        fn = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)(self.vtbl[index])
        return fn(self.ptr, *args)

    def set_value(self, hwnd, done, total):  # SetProgressValue
        self._call(9, [ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_ulonglong], hwnd, done, total)

    def set_state(self, hwnd, state):  # SetProgressState: 0 none, 2 normal, 4 error, 8 paused
        self._call(10, [ctypes.c_void_p, ctypes.c_int], hwnd, state)

    def _icon(self, char):
        if char not in self.icons:
            self.icons[char] = _glyph_icon(char)
        return self.icons[char]

    def _buttons(self, paused):
        arr = (THUMBBUTTON * 3)()
        for i, (bid, char, tip) in enumerate(((101, "", "Previous"),
                                             (102, "" if paused else "", "Play" if paused else "Pause"),
                                             (103, "", "Next"))):
            arr[i].dwMask, arr[i].iId, arr[i].hIcon, arr[i].szTip = THB_ICON | THB_TOOLTIP | THB_FLAGS, bid, \
                self._icon(char), tip
        return arr

    def add_buttons(self, hwnd):  # ThumbBarAddButtons (only once per window)
        arr = self._buttons(True)
        return self._call(15, [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p], hwnd, 3, ctypes.byref(arr)) == 0

    def set_play_glyph(self, hwnd, paused):  # ThumbBarUpdateButtons
        arr = self._buttons(paused)
        self._call(16, [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p], hwnd, 3, ctypes.byref(arr))


_instance = None


def get():
    global _instance
    if _instance is None:
        _instance = TaskbarList()
    return _instance
