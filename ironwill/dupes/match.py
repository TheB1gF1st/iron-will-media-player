"""Finding duplicates among fingerprints.

1. Candidates: every hash is split into four 16-bit bands; two videos become a candidate pair when they share
   enough bands. Bands that show up in lots of files (black frames, common logos) are ignored. This avoids
   comparing every video with every other one.
2. Offset: for a candidate pair, every close hash match votes for "B is N seconds ahead of A"; the winning vote is
   the offset (an added intro, a trimmed start...).
3. Score: walking A's timeline shifted by that offset, how many of A's moments have a matching moment in B.
   Only the overlapping stretch counts, so a short clip of a longer video still scores high, and the overlap
   tells whether it's the same video or a clip of it.
"""
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

MATCH_BITS = 10       # two frames "look the same" within this many differing bits (of 64)
WINDOW = 2.5          # seconds of keyframe jitter allowed between copies
MIN_SAMPLES = 6       # need at least this many comparable moments to judge


@dataclass
class PairResult:
    a: int
    b: int
    similarity: float     # 0..1 share of overlapping moments that match
    offset: float         # seconds: B's timeline = A's timeline + offset
    overlap: float        # seconds of overlap
    flipped: bool
    kind: str             # "same" or "clip"


def _usable(fp):
    return len(fp.hashes) >= MIN_SAMPLES and not fp.error


def candidate_pairs(fps, min_shared=3, common_limit=0.05):
    index = defaultdict(set)
    for i, fp in enumerate(fps):
        if not _usable(fp):
            continue
        for hashes in (fp.hashes, fp.flips):
            good = hashes[~fp.flat]
            for band in range(4):
                keys = ((good >> np.uint64(16 * band)) & np.uint64(0xFFFF)).astype(np.uint32)
                for k in np.unique(keys):
                    index[(band, int(k))].add(i)
    limit = max(3, int(len(fps) * common_limit))
    shared = defaultdict(int)
    for members in index.values():
        if len(members) < 2 or len(members) > limit:
            continue
        ms = sorted(members)
        for x in range(len(ms)):
            for y in range(x + 1, len(ms)):
                shared[(ms[x], ms[y])] += 1
    return [pair for pair, n in shared.items() if n >= min_shared]


def _score(fa, fb, hb, offset):
    """Share of A's (non-flat) moments, shifted by offset, that have a matching frame in B.

    Only moments where B actually has a sample nearby are judged: keyframes land in different places in
    different encodes, and a stream-copied file may have one only every 5-10 s, so "no frame to compare"
    must not count as "different"."""
    ta = fa.times + offset
    inside = (ta >= fb.times[0] - WINDOW) & (ta <= fb.times[-1] + WINDOW) & ~fa.flat
    if inside.sum() < MIN_SAMPLES:
        return 0.0, 0.0
    lo = np.searchsorted(fb.times, ta[inside] - WINDOW)
    hi = np.searchsorted(fb.times, ta[inside] + WINDOW, side="right")
    ha = fa.hashes[inside]
    judged = matched = 0
    for h, l, r in zip(ha, lo, hi):
        if r <= l:
            continue
        judged += 1
        if int(np.bitwise_count(hb[l:r] ^ h).min()) <= MATCH_BITS:
            matched += 1
    if judged < MIN_SAMPLES:
        return 0.0, 0.0
    t_in = fa.times[inside]
    return matched / judged, float(t_in[-1] - t_in[0])


def compare(fa, fb):
    """Best (similarity, offset, overlap, flipped) for two fingerprints."""
    best = (0.0, 0.0, 0.0, False)
    a_good = ~fa.flat
    for flipped, hb in ((False, fb.hashes), (True, fb.flips)):
        d = np.bitwise_count(fa.hashes[a_good][:, None] ^ hb[None, :])
        ia, ib = np.nonzero(d <= MATCH_BITS)
        if len(ia) < 3:
            continue
        dts = fb.times[ib] - fa.times[a_good][ia]
        # Vote in 1-second bins (with neighbours) for the offset.
        bins = np.round(dts).astype(int)
        values, counts = np.unique(bins, return_counts=True)
        smoothed = counts + np.array([counts[(values == v - 1) | (values == v + 1)].sum() for v in values])
        for v in values[np.argsort(-smoothed)[:3]]:  # try the top few offsets
            near = np.abs(dts - v) <= 1.5
            offset = float(np.median(dts[near]))
            sim, overlap = _score(fa, fb, hb, offset)
            if sim > best[0]:
                best = (sim, offset, overlap, flipped)
    return best


SURE_YES = 0.9     # keyframe score this high: a duplicate without further checks
SURE_NO = 0.3      # this low: not a duplicate
VERIFY_POINTS = 16


def verify(fa, fb, offset, overlap, flipped, points=VERIFY_POINTS):
    """Precise check for pairs the quick keyframe pass isn't sure about: grab frames at exactly the same moments
    (A's time, and A's time + offset in B) from both files and compare them."""
    from concurrent.futures import ThreadPoolExecutor
    from .fingerprint import frame_hash_at
    start = max(0.0, float(fa.times[0]), float(fb.times[0]) - offset) + 1.0
    end = min(fa.duration, fb.duration - offset) - 1.0
    if end - start < 5:
        return 0.0
    moments = np.linspace(start, end, points)
    with ThreadPoolExecutor(max_workers=4) as pool:
        ha = list(pool.map(lambda t: frame_hash_at(fa.path, t), moments))
        hb = list(pool.map(lambda t: frame_hash_at(fb.path, t + offset, flip=flipped), moments))
    judged = matched = 0
    for (x, flat_a), (y, flat_b) in zip(ha, hb):
        if x is None or y is None or (flat_a and flat_b):
            continue
        judged += 1
        if int(np.bitwise_count(np.uint64(x) ^ np.uint64(y))) <= MATCH_BITS:
            matched += 1
    return matched / judged if judged >= points // 2 else 0.0


def find_duplicates(fps, threshold=0.8, partial_clips=True, min_clip_ratio=0.1, progress=None, stop=None, store=None):
    """Returns a list of PairResult for pairs at or above `threshold` similarity."""
    pairs = candidate_pairs(fps)
    results = []
    for n, (i, j) in enumerate(pairs):
        if stop is not None and stop.is_set():
            break
        if progress:
            progress(n + 1, len(pairs))
        a, b = (i, j) if fps[i].duration <= fps[j].duration else (j, i)  # A = the shorter one
        fa, fb = fps[a], fps[b]
        sim, offset, overlap, flipped = compare(fa, fb)
        if SURE_NO <= sim < SURE_YES:
            known = store.verified(fa, fb, offset, flipped) if store else None
            if known is None:
                known = verify(fa, fb, offset, overlap, flipped)
                if store:
                    store.save_verified(fa, fb, offset, flipped, known)
            sim = max(sim, known)
        if sim < threshold:
            continue
        short = max(1.0, min(fa.duration, fb.duration))
        long_ = max(1.0, max(fa.duration, fb.duration))
        covers_short = overlap >= 0.6 * short
        if not covers_short:
            continue
        same_length = short / long_ >= 0.85
        if not same_length and not partial_clips:
            continue
        if not same_length and short / long_ < min_clip_ratio:
            continue
        results.append(PairResult(a, b, sim, offset, overlap, flipped, "same" if same_length else "clip"))
    return results


def group(results, count):
    """Union pairs into groups of duplicates."""
    parent = list(range(count))

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for r in results:
        parent[root(r.a)] = root(r.b)
    groups = defaultdict(list)
    for r in results:
        groups[root(r.a)].append(r)
    return list(groups.values())


QUALITY_ORDER = ["duration", "resolution", "fps", "vbitrate", "abitrate", "size"]


def best_copy(fps, members, order=QUALITY_ORDER):
    """Which file to keep: VDF-style priority (longest, then sharpest, smoothest, best bitrate, biggest).
    Lengths within 10% count as equal, so an added intro or a few extra seconds don't beat a sharper copy."""
    longest = max(fps[i].duration for i in members)
    members = [i for i in members if fps[i].duration >= 0.9 * longest] or members

    def key(i):
        fp = fps[i]
        vals = {"duration": 0, "resolution": fp.resolution, "fps": round(fp.fps),
                "vbitrate": fp.vbitrate, "abitrate": fp.abitrate, "size": fp.size}
        return tuple(vals[k] for k in order)
    return max(members, key=key)
