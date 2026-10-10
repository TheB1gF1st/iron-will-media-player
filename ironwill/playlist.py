"""Folder playlist: the other media files next to the one that's playing, in the folder's order.

The order can follow File Explorer: if the folder is open in an Explorer window, its current sort (name, date
modified, date created, size, type; ascending or descending) is read from that window, so "next" is the file
you see next. Names compare the way Explorer does (Ep 2 before Ep 10) via Windows' own StrCmpLogicalW."""
import ctypes
import functools
from pathlib import Path

MEDIA_EXTS = {
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".flv", ".ts", ".m2ts", ".mts", ".mpg", ".mpeg",
    ".vob", ".ogv", ".3gp", ".divx", ".rmvb", ".asf", ".f4v", ".y4m",
    ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma", ".ape", ".alac", ".mka", ".dts", ".ac3",
}
NAME_SORT = "prop:System.ItemNameDisplay;"

_cmp_logical = ctypes.windll.shlwapi.StrCmpLogicalW
_cmp_logical.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
_cmp_logical.restype = ctypes.c_int


def _name_cmp(a, b):
    return _cmp_logical(a.name, b.name)


def is_media(path):
    return Path(path).suffix.lower() in MEDIA_EXTS


def parse_sort(spec):
    """'prop:-System.DateModified;System.ItemNameDisplay;' -> [('System.DateModified', True), (..., False)]"""
    out = []
    for part in (spec or "").replace("prop:", "").split(";"):
        part = part.strip()
        if part:
            out.append((part.lstrip("+-"), part.startswith("-")))
    return out or [("System.ItemNameDisplay", False)]


def _stat(p):
    try:
        return p.stat()
    except OSError:
        return None


def _key_value(p, prop):
    st = _stat(p)
    if prop in ("System.DateModified", "System.ItemDate", "System.Media.DateEncoded", "System.DateImported"):
        return st.st_mtime if st else 0
    if prop == "System.DateCreated":
        return st.st_ctime if st else 0
    if prop == "System.DateAccessed":
        return st.st_atime if st else 0
    if prop in ("System.Size", "System.TotalFileSize"):
        return st.st_size if st else 0
    if prop in ("System.ItemTypeText", "System.FileExtension", "System.ItemType"):
        return p.suffix.lower()
    return None  # name-like columns: compared with Explorer's logical name order


def sort_files(files, spec=NAME_SORT):
    keys = parse_sort(spec)

    def compare(a, b):
        for prop, desc in keys:
            va, vb = _key_value(a, prop), _key_value(b, prop)
            c = _name_cmp(a, b) if va is None else (va > vb) - (va < vb)
            if c:
                return -c if desc else c
        return _name_cmp(a, b)  # ties: by name, like Explorer

    return sorted(files, key=functools.cmp_to_key(compare))


def explorer_sort(folder):
    """The sort of an open File Explorer window showing `folder`, or None if none is open."""
    try:
        import win32com.client
        shell = win32com.client.Dispatch("Shell.Application")
        target = str(Path(folder)).rstrip("\\").lower()
        for w in shell.Windows():
            try:
                doc = w.Document
                if str(doc.Folder.Self.Path).rstrip("\\").lower() == target:
                    return str(doc.SortColumns) or None
            except Exception:
                continue
    except Exception:
        return None
    return None


def siblings(path, spec=NAME_SORT):
    path = Path(path)
    try:
        files = [p for p in path.parent.iterdir() if p.is_file() and is_media(p)]
    except OSError:
        return [path]
    return sort_files(files, spec)


def neighbor(path, step, spec=NAME_SORT):
    files = siblings(path, spec)
    try:
        i = [str(f).lower() for f in files].index(str(Path(path)).lower())
    except ValueError:
        return None
    j = i + step
    return files[j] if 0 <= j < len(files) else None


def describe(spec):
    """'prop:-System.DateModified;' -> 'Date modified, newest first' (for messages)."""
    prop, desc = parse_sort(spec)[0]
    names = {"System.DateModified": ("Date modified", "newest first", "oldest first"),
             "System.ItemDate": ("Date", "newest first", "oldest first"),
             "System.DateCreated": ("Date created", "newest first", "oldest first"),
             "System.Size": ("Size", "largest first", "smallest first"),
             "System.ItemTypeText": ("Type", "Z to A", "A to Z")}
    label, d, a = names.get(prop, ("Name", "Z to A", "A to Z"))
    return f"{label}, {d if desc else a}"
