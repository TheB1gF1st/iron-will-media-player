"""Remembers how far you got in each file, so reopening it can offer "Continue" or "Start over"."""
import json
import time

from .settings import DATA_DIR

STORE = DATA_DIR / "positions.json"
MIN_POS = 10      # don't offer to resume a file you barely started
END_MARGIN = 20   # within this many seconds of the end counts as finished
MAX_ENTRIES = 500


class ResumeStore:
    def __init__(self):
        try:
            self.data = json.loads(STORE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.last_write = 0.0

    @staticmethod
    def _key(path):
        return str(path).lower()

    def get(self, path, max_days=0):
        """Saved position in seconds, or None if there's nothing worth resuming.
        max_days > 0: a position older than that many days is forgotten."""
        entry = self.data.get(self._key(path))
        if not entry:
            return None
        if max_days and time.time() - entry.get("t", 0) > max_days * 86400:
            self.forget(path)
            return None
        pos, dur = entry.get("pos", 0), entry.get("dur", 0)
        if pos < MIN_POS or (dur and pos > dur - END_MARGIN):
            return None
        return pos

    def update(self, path, pos, dur, force=False):
        if not path or pos is None:
            return
        self.data[self._key(path)] = {"pos": round(pos, 1), "dur": round(dur or 0, 1), "t": int(time.time())}
        if force or time.time() - self.last_write > 5:
            self.save()

    def forget(self, path):
        if self.data.pop(self._key(path), None) is not None:
            self.save()

    def save(self):
        if len(self.data) > MAX_ENTRIES:  # keep the most recently watched
            keep = sorted(self.data.items(), key=lambda kv: kv[1].get("t", 0), reverse=True)[:MAX_ENTRIES]
            self.data = dict(keep)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data), encoding="utf-8")
        tmp.replace(STORE)
        self.last_write = time.time()
