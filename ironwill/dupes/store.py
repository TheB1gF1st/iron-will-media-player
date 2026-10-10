"""Remembers fingerprints between scans (SQLite in the settings folder), so a second scan only reads new or
changed files, and remembers pairs you've marked "not duplicates" so they never come back."""
import sqlite3
import threading

from ..settings import DATA_DIR
from .fingerprint import Fingerprint, from_blob, to_blob

DB = DATA_DIR / "duplicates.sqlite"
FIELDS = ["size", "mtime", "duration", "width", "height", "fps", "vbitrate", "abitrate", "vcodec", "error"]


class Store:
    def __init__(self, path=DB):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY COLLATE NOCASE, size INT, mtime REAL,
                duration REAL, width INT, height INT, fps REAL, vbitrate INT, abitrate INT, vcodec TEXT, error TEXT,
                count INT, times BLOB, hashes BLOB, flips BLOB, flat BLOB);
            CREATE TABLE IF NOT EXISTS not_dupes (a TEXT COLLATE NOCASE, b TEXT COLLATE NOCASE, PRIMARY KEY (a, b));
            CREATE TABLE IF NOT EXISTS verified (key TEXT PRIMARY KEY, similarity REAL);
        """)

    def get(self, path, size, mtime):
        """The saved fingerprint if the file hasn't changed since it was scanned."""
        with self.lock:
            row = self.db.execute(f"SELECT {', '.join(FIELDS)}, count, times, hashes, flips, flat FROM files "
                                  "WHERE path = ?", (str(path),)).fetchone()
        if not row or row[0] != size or abs(row[1] - mtime) > 1:
            return None
        fp = Fingerprint(str(path), **dict(zip(FIELDS, row[:len(FIELDS)])))
        blob = dict(zip(["count", "times", "hashes", "flips", "flat"], row[len(FIELDS):]))
        return from_blob(fp, blob) if blob["count"] else fp

    def put(self, fp):
        blob = to_blob(fp)
        with self.lock:
            self.db.execute(f"INSERT OR REPLACE INTO files (path, {', '.join(FIELDS)}, count, times, hashes, flips, "
                            f"flat) VALUES ({', '.join('?' * (len(FIELDS) + 6))})",
                            [fp.path] + [getattr(fp, f) for f in FIELDS] +
                            [blob["count"], blob["times"], blob["hashes"], blob["flips"], blob["flat"]])
            self.db.commit()

    def forget(self, path):
        with self.lock:
            self.db.execute("DELETE FROM files WHERE path = ?", (str(path),))
            self.db.commit()

    def mark_not_dupes(self, a, b):
        a, b = sorted((str(a), str(b)), key=str.lower)
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO not_dupes VALUES (?, ?)", (a, b))
            self.db.commit()

    def not_dupes(self):
        with self.lock:
            return {(a.lower(), b.lower()) for a, b in self.db.execute("SELECT a, b FROM not_dupes")}

    # Results of the precise frame-by-frame check, so re-scans don't redo it (keyed on both files' size + date).
    @staticmethod
    def _pair_key(fa, fb, offset, flipped):
        return f"{fa.path.lower()}|{fa.size}|{int(fa.mtime)}|{fb.path.lower()}|{fb.size}|{int(fb.mtime)}|" \
               f"{round(offset)}|{int(flipped)}"

    def verified(self, fa, fb, offset, flipped):
        with self.lock:
            row = self.db.execute("SELECT similarity FROM verified WHERE key = ?",
                                  (self._pair_key(fa, fb, offset, flipped),)).fetchone()
        return row[0] if row else None

    def save_verified(self, fa, fb, offset, flipped, similarity):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO verified VALUES (?, ?)",
                            (self._pair_key(fa, fb, offset, flipped), similarity))
            self.db.commit()

    def clear(self):
        with self.lock:
            self.db.execute("DELETE FROM files")
            self.db.commit()
