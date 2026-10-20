"""Runs a duplicate scan in the background: find the videos, fingerprint the ones not already saved (several at
a time), then match them. Reports progress through Qt signals so the window stays responsive."""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .. import playlist
from . import match
from .fingerprint import fingerprint
from .store import Store

AUDIO_ONLY = {".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wma", ".ape", ".alac", ".mka", ".dts",
              ".ac3"}
VIDEO_EXTS = playlist.MEDIA_EXTS - AUDIO_ONLY


@dataclass
class Member:
    fp: object
    similarity: float = 1.0   # vs the suggested keeper
    offset: float = 0.0       # seconds: this file's timeline = keeper's timeline + offset
    flipped: bool = False
    kind: str = "keep"        # "keep", "same" or "clip"


@dataclass
class Group:
    members: list = field(default_factory=list)   # keeper first


def collect(folders, subfolders=True, min_mb=1):
    seen, out = set(), []
    for folder in folders:
        folder = Path(folder)
        if not folder.exists():
            continue
        walker = os.walk(folder) if subfolders else [(str(folder), [], os.listdir(folder))]
        for root, _dirs, names in walker:
            for name in names:
                p = Path(root) / name
                if p.suffix.lower() in VIDEO_EXTS and str(p).lower() not in seen:
                    try:
                        if p.stat().st_size >= min_mb * 1024 * 1024:
                            seen.add(str(p).lower())
                            out.append(p)
                    except OSError:
                        pass
    return out


def build_groups(fps, pairs):
    """Turn duplicate pairs into groups, keeper first, with each copy's similarity and offset vs the keeper."""
    groups = []
    for g in match.group(pairs, len(fps)):
        ids = sorted({x for r in g for x in (r.a, r.b)})
        keep = match.best_copy(fps, ids)
        # Offsets relative to the keeper, walking the pair graph outwards from it.
        edges = {}
        for r in g:
            edges.setdefault(r.a, []).append((r.b, r.offset, r))
            edges.setdefault(r.b, []).append((r.a, -r.offset, r))
        info, todo = {keep: (0.0, 1.0, False, "keep")}, [keep]
        while todo:
            cur = todo.pop()
            base = info[cur][0]
            for nxt, off, r in edges.get(cur, []):
                if nxt not in info:
                    # pair offset: B = A + offset. Going from cur to nxt adds `off` (sign already set above).
                    info[nxt] = (base + off, r.similarity, r.flipped != info[cur][2], r.kind)
                    todo.append(nxt)
        members = [Member(fps[i], *info[i][1:2], offset=info[i][0], flipped=info[i][2], kind=info[i][3])
                   for i in sorted(ids, key=lambda i: (i != keep, fps[i].path.lower()))]
        groups.append(Group(members))
    groups.sort(key=lambda g: -sum(m.fp.size for m in g.members[1:]))  # most space to free first
    return groups


class Scanner(QObject):
    progress = Signal(str, int, int, str)   # phase, done, total, detail
    finished = Signal(list, str)            # groups, summary

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stop_event = threading.Event()
        self.thread = None

    def start(self, folders, threshold=0.8, subfolders=True, partial_clips=True, mirrored=True, workers=3, min_mb=1):
        self.stop_event.clear()
        self.min_mb = min_mb
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       args=(folders, threshold, subfolders, partial_clips, mirrored, workers))
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def _run(self, folders, threshold, subfolders, partial_clips, mirrored, workers):
        t0 = time.time()
        store = Store()
        self.progress.emit("Finding videos…", 0, 0, "")
        files = collect(folders, subfolders, getattr(self, "min_mb", 1))
        fps, todo = [], []
        for p in files:
            try:
                st = p.stat()
            except OSError:
                continue
            saved = store.get(p, st.st_size, st.st_mtime)
            (fps.append(saved) if saved else todo.append(p))
        reused = len(fps)
        done = 0
        if todo:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(fingerprint, p, self.stop_event): p for p in todo}
                for fut in as_completed(futures):
                    if self.stop_event.is_set():
                        break
                    done += 1
                    try:
                        fp = fut.result()
                    except Exception as exc:
                        self.progress.emit("Reading videos", done, len(todo), f"skipped {futures[fut].name}: {exc}")
                        continue
                    if fp.error != "stopped":
                        store.put(fp)
                        fps.append(fp)
                    self.progress.emit("Reading videos", done, len(todo), futures[fut].name)
        if self.stop_event.is_set():
            self.finished.emit([], "Scan stopped. Videos read so far are saved, so the next scan picks up from here.")
            return
        fps = [fp for fp in fps if not fp.error]
        ignored = store.not_dupes()
        pairs = match.find_duplicates(fps, threshold=threshold, partial_clips=partial_clips,
                                      progress=lambda n, total: self.progress.emit("Comparing likely matches", n, total,
                                                                                 ""),
                                      stop=self.stop_event, store=store)
        pairs = [r for r in pairs if (mirrored or not r.flipped)
                 and tuple(sorted((fps[r.a].path.lower(), fps[r.b].path.lower()))) not in ignored]
        groups = build_groups(fps, pairs)
        extra = sum(m.fp.size for g in groups for m in g.members[1:])
        minutes = (time.time() - t0) / 60
        self.finished.emit(groups, f"{len(files)} videos ({reused} remembered from earlier scans) · "
                                   f"{len(groups)} groups of duplicates · {extra / 1024 ** 3:.2f} GB in extra copies · "
                                   f"{minutes:.1f} min")
