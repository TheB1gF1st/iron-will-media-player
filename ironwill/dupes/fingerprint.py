"""Video fingerprints for the duplicate finder.

FFmpeg decodes only the keyframes (fast even without a dedicated GPU), shrinks each to 32x32 grey, and every frame
becomes a 64-bit perceptual hash (pHash: the low frequencies of a DCT, so re-encodes, resizes and bitrate changes
barely move it). A mirrored hash is kept too, to catch flipped copies. Flat frames (black, white, fades) say nothing
about which video they belong to, so they're marked and ignored when matching.

A fingerprint is the *timeline* of those hashes, so two videos can be compared moment by moment and the time offset
between them (an added intro, a trimmed start) can be measured instead of guessed."""
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..paths import APP_DIR

FRAME = 32
MIN_GAP = 1.0          # keep at most one sample per second
FLAT_STD = 6.0         # frames this uniform are skipped when matching
CREATE_NO_WINDOW = 0x08000000
FFMPEG_DIRS = [APP_DIR / "ffmpeg", APP_DIR, Path(r"E:\_Misc\FFMpeg8.1.2EssentialsBuild\bin")]


BELOW_NORMAL_PRIORITY = 0x00004000
SETTINGS = {"ffmpeg_dir": "", "low_priority": True, "hwaccel": "none", "min_gap": MIN_GAP}


def configure(cfg):
    """Pick up the Duplicate Finder settings from Options before a scan."""
    SETTINGS.update(ffmpeg_dir=cfg["dupe_ffmpeg_dir"] or "", low_priority=bool(cfg["dupe_low_priority"]),
                    hwaccel=cfg["dupe_hwaccel"] or "none", min_gap=float(cfg["dupe_sample_gap"] or MIN_GAP))


def _flags():
    return CREATE_NO_WINDOW | (BELOW_NORMAL_PRIORITY if SETTINGS["low_priority"] else 0)


def find_tool(name):
    custom = SETTINGS.get("ffmpeg_dir")
    if custom and (Path(custom) / f"{name}.exe").exists():
        return str(Path(custom) / f"{name}.exe")
    for d in FFMPEG_DIRS:
        if (d / f"{name}.exe").exists():
            return str(d / f"{name}.exe")
    return shutil.which(name)


def _dct_matrix(n):
    k = np.arange(n)
    m = np.cos(np.pi * (2 * k[None, :] + 1) * k[:, None] / (2 * n)) * np.sqrt(2 / n)
    m[0] /= np.sqrt(2)
    return m


_DCT = _dct_matrix(FRAME)
_BITS = (1 << np.arange(64, dtype=np.uint64)).astype(np.uint64)


def phash(frames):
    """frames: (n, 32, 32) float -> (n,) uint64 pHash."""
    d = _DCT @ frames @ _DCT.T
    low = d[:, :8, :8].reshape(len(frames), 64)
    med = np.median(low[:, 1:], axis=1, keepdims=True)  # skip the DC term when picking the threshold
    bits = (low > med).astype(np.uint64)
    return (bits * _BITS).sum(axis=1).astype(np.uint64)


@dataclass
class Fingerprint:
    path: str
    size: int = 0
    mtime: float = 0.0
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    vbitrate: int = 0
    abitrate: int = 0
    vcodec: str = ""
    times: np.ndarray = field(default_factory=lambda: np.zeros(0, np.float32))
    hashes: np.ndarray = field(default_factory=lambda: np.zeros(0, np.uint64))
    flips: np.ndarray = field(default_factory=lambda: np.zeros(0, np.uint64))
    flat: np.ndarray = field(default_factory=lambda: np.zeros(0, bool))
    error: str = ""

    @property
    def resolution(self):
        return self.width * self.height


def probe(path):
    """Basic facts about a video from ffprobe."""
    exe = find_tool("ffprobe")
    out = subprocess.run([exe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         creationflags=_flags(), timeout=120)
    info = json.loads(out.stdout or "{}")
    fmt = info.get("format", {})
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"
              and not s.get("disposition", {}).get("attached_pic")), {})
    a = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), {})
    num, _, den = (v.get("avg_frame_rate") or "0/1").partition("/")
    fps = float(num) / float(den) if den and float(den) else 0.0
    return {
        "duration": float(fmt.get("duration") or v.get("duration") or 0),
        "width": int(v.get("width") or 0), "height": int(v.get("height") or 0), "fps": round(fps, 3),
        "vbitrate": int(v.get("bit_rate") or 0) or int(fmt.get("bit_rate") or 0),
        "abitrate": int(a.get("bit_rate") or 0), "vcodec": v.get("codec_name") or "",
        "has_video": bool(v),
    }


def fingerprint(path, stop=None):
    """Build the fingerprint for one file. `stop` is an optional threading.Event to abort."""
    p = Path(path)
    st = p.stat()
    fp = Fingerprint(str(p), st.st_size, st.st_mtime)
    try:
        info = probe(p)
    except Exception as exc:
        fp.error = f"ffprobe failed: {exc}"
        return fp
    if not info.pop("has_video"):
        fp.error = "no video stream"
        return fp
    for k, v in info.items():
        setattr(fp, k, v)

    # Keyframes only, scaled to 32x32 grey; showinfo prints each frame's timestamp on stderr.
    hw = [] if SETTINGS["hwaccel"] in ("", "none") else ["-hwaccel", SETTINGS["hwaccel"]]
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "info", *hw, "-skip_frame", "nokey", "-i", str(p),
           "-an", "-sn", "-dn", "-vf", f"scale={FRAME}:{FRAME}:flags=area,format=gray,showinfo",
           "-fps_mode", "passthrough", "-f", "rawvideo", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_flags())
    stderr_lines = []

    def read_stderr():
        for line in proc.stderr:
            stderr_lines.append(line)

    import threading
    t = threading.Thread(target=read_stderr, daemon=True)
    t.start()
    chunks = []
    size = FRAME * FRAME
    while True:
        if stop is not None and stop.is_set():
            proc.kill()
            fp.error = "stopped"
            return fp
        buf = proc.stdout.read(size * 64)
        if not buf:
            break
        chunks.append(buf)
    proc.wait()
    t.join(timeout=5)
    raw = b"".join(chunks)
    n = len(raw) // size
    times = [float(m.group(1)) for line in stderr_lines
             for m in [re.search(rb"pts_time:\s*([0-9.]+)", line)] if m]
    n = min(n, len(times))
    if n == 0:
        fp.error = "couldn't read any frames"
        return fp
    frames = np.frombuffer(raw[: n * size], np.uint8).reshape(n, FRAME, FRAME).astype(np.float32)
    times = np.array(times[:n], np.float32)

    # At most one sample per second (some files have keyframes every few frames).
    keep, last = [], -1e9
    for i, tt in enumerate(times):
        if tt - last >= SETTINGS["min_gap"]:
            keep.append(i)
            last = tt
    frames, times = frames[keep], times[keep]
    fp.times = times
    fp.hashes = phash(frames)
    fp.flips = phash(frames[:, :, ::-1].copy())
    fp.flat = frames.reshape(len(frames), -1).std(axis=1) < FLAT_STD
    if not fp.duration and len(times):
        fp.duration = float(times[-1])
    return fp


def frame_hash_at(path, t, flip=False):
    """pHash of the frame at exactly `t` seconds (accurate seek: decodes from the previous keyframe to t)."""
    vf = f"scale={FRAME}:{FRAME}:flags=area,format=gray" + (",hflip" if flip else "")
    out = subprocess.run([find_tool("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.3f}",
                          "-i", str(path), "-an", "-sn", "-frames:v", "1", "-vf", vf, "-f", "rawvideo", "pipe:1"],
                         capture_output=True, creationflags=_flags(), timeout=60)
    raw = out.stdout[: FRAME * FRAME]
    if len(raw) < FRAME * FRAME:
        return None, True
    frame = np.frombuffer(raw, np.uint8).reshape(1, FRAME, FRAME).astype(np.float32)
    return int(phash(frame)[0]), float(frame.std()) < FLAT_STD


def to_blob(fp):
    return {"times": fp.times.astype(np.float32).tobytes(), "hashes": fp.hashes.astype(np.uint64).tobytes(),
            "flips": fp.flips.astype(np.uint64).tobytes(), "flat": np.packbits(fp.flat).tobytes(),
            "count": int(len(fp.times))}


def from_blob(fp, blob):
    n = blob["count"]
    fp.times = np.frombuffer(blob["times"], np.float32)[:n]
    fp.hashes = np.frombuffer(blob["hashes"], np.uint64)[:n]
    fp.flips = np.frombuffer(blob["flips"], np.uint64)[:n]
    fp.flat = np.unpackbits(np.frombuffer(blob["flat"], np.uint8))[:n].astype(bool)
    return fp


def os_size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return 0
