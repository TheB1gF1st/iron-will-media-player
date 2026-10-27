"""Subtitles for only the lines spoken in another language ("forced" subtitles), saved next to the video as
<name>.<lang>.forced.srt so the player shows them even with subtitles off.

Two ways to get them:
  find_online()  asks OpenSubtitles for a "foreign parts only" file. Needed for made-up languages (Kahndaqi,
                 Dothraki, Klingon...), which no speech model can translate.
  scan_audio()   listens to the audio offline with faster-whisper and translates only the speech that isn't in
                 the chosen language. Works for real languages, needs no internet, takes ~10 min a movie.
Both are our own code (stdlib + MIT-licensed faster-whisper), nothing GPL."""
import json
import os
import re
import struct
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from .paths import APP_DIR
from .settings import DATA_DIR

API = "https://api.opensubtitles.com/api/v1"
USER_AGENT = "IronWillMediaPlayer v1.1"
# The developer key belongs to the app (one key for every user). Users can add their own free account in Options
# for more downloads a day.
_KEY_FILE = APP_DIR / "opensubs.key"  # kept out of the repo (.gitignore); build_release.py ships it with the app
APP_API_KEY = _KEY_FILE.read_text(encoding="utf-8").strip() if _KEY_FILE.exists() else ""
MODEL_HOME = DATA_DIR / "models" / "whisper-small"  # downloaded here the first time it's needed (~460 MB)
MODEL_DIRS = [APP_DIR / "models" / "whisper-small", MODEL_HOME,
              Path(r"E:\_Misc\Zip files and installers\whisper-small")]  # last one: the author's dev copy
FFMPEG_DIRS = [APP_DIR / "ffmpeg", APP_DIR, Path(r"E:\_Misc\FFMpeg8.1.2EssentialsBuild\bin")]


class SubsError(Exception):
    pass


def out_path(video, lang):
    return Path(video).with_suffix(f".{lang}.forced.srt")


# Online ------------------------------------------------------------------------------------------------------
def movie_hash(path):
    """OpenSubtitles' file hash: size + the 64-bit sums of the first and last 64 KB."""
    size = os.path.getsize(path)
    h = size
    with open(path, "rb") as f:
        for offset in (0, max(0, size - 65536)):
            f.seek(offset)
            chunk = f.read(65536)
            chunk += b"\0" * (-len(chunk) % 8)
            for (v,) in struct.iter_unpack("<Q", chunk):
                h = (h + v) & 0xFFFFFFFFFFFFFFFF
    return f"{h:016x}"


def guess_title(path):
    """'Game.of.Thrones.S01E03.1080p...' -> ('game of thrones', 1, 3); 'Black Adam (2022)' -> ('black adam', None, None)"""
    name = Path(path).stem
    m = re.search(r"[sS](\d{1,2})[ ._-]*[eE](\d{1,3})|(\d{1,2})x(\d{2})", name)
    season = episode = None
    if m:
        season, episode = int(m.group(1) or m.group(3)), int(m.group(2) or m.group(4))
        name = name[:m.start()]
    name = re.split(r"[\(\[]?(19|20)\d{2}[\)\]]?|1080p|720p|2160p|4k|bluray|web", name, flags=re.I)[0]
    title = re.sub(r"[._\-]+", " ", name).strip().lower()
    if not title and season:  # "S01E03.mkv" inside a "Game of Thrones/Season 1" folder
        parent = Path(path).parent
        title = (parent.parent.name if re.match(r"(?i)season|s\d", parent.name) else parent.name).lower()
    return title, season, episode


def _request(url, key, token=None, body=None):
    headers = {"Api-Key": key, "User-Agent": USER_AGENT, "Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode()).get("message", "")
        except Exception:
            msg = ""
        raise SubsError(msg or f"OpenSubtitles said {e.code}") from None
    except OSError as e:
        raise SubsError(f"Couldn't reach OpenSubtitles ({e})") from None


def _search(key, params):
    q = urllib.parse.urlencode(sorted((k, v) for k, v in params.items() if v not in (None, "")))
    return _request(f"{API}/subtitles?{q}", key).get("data", [])


def find_online(video, lang="en", api_key="", username="", password=""):
    """Download a foreign-parts-only subtitle for this video. Returns (path, downloads_left_today) or raises
    SubsError. Searching is free; only the download counts against the daily limit."""
    key = api_key or APP_API_KEY
    if not key:
        raise SubsError("No OpenSubtitles API key yet (Options > Subtitles)")
    title, season, episode = guess_title(video)
    base = {"languages": lang, "foreign_parts_only": "only"}
    results = _search(key, {**base, "moviehash": movie_hash(video)})
    if not results and title:
        results = _search(key, {**base, "query": title, "season_number": season, "episode_number": episode})
    files = [(a.get("moviehash_match", False), a.get("download_count", 0), f["file_id"])
             for a in (r.get("attributes", {}) for r in results) if a.get("foreign_parts_only")
             for f in a.get("files", [])[:1]]
    if not files:
        raise SubsError("No foreign-dialogue subtitles found online for this one")
    file_id = max(files)[2]  # an exact file match first, then the most downloaded
    token = None
    if username and password:
        token = _request(f"{API}/login", key, body={"username": username, "password": password}).get("token")
    got = _request(f"{API}/download", key, token, body={"file_id": file_id})
    if not got.get("link"):
        raise SubsError(got.get("message") or "Download limit reached for today")
    req = urllib.request.Request(got["link"], headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        text = r.read()
    dest = out_path(video, lang)
    dest.write_bytes(text)
    try:
        align_to_audio(video, dest)
    except Exception:
        pass  # a subtitle a little off is still better than none
    return dest, got.get("remaining")


# Timing -------------------------------------------------------------------------------------------------------
CUE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def _secs(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def align_to_audio(video, srt, search=5.0):
    """Downloaded subtitles are often timed for a slightly different cut of the video (another release, an intro
    trimmed off). Line each cue's start up with where speech actually starts in this file, try every shift within
    +/- `search` seconds, and rewrite the file with the best one. Returns the shift applied (0 if unsure)."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    import numpy as np

    ffmpeg = _find(FFMPEG_DIRS, "ffmpeg.exe")
    text = Path(srt).read_text(encoding="utf-8", errors="replace")
    cues = [_secs(*m.groups()[:4]) for m in CUE.finditer(text)]
    if not ffmpeg or not cues:
        return 0.0
    sr, pad = 16000, search + 1
    onsets = []
    for start in cues:  # only decode the audio around each cue, not the whole video
        a = max(0.0, start - pad)
        raw = subprocess.run([str(ffmpeg), "-v", "error", "-nostdin", "-ss", f"{a:.2f}", "-t", f"{2 * pad:.2f}",
                              "-i", str(video), "-map", "0:a:0", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                             capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
        onsets.append([t["start"] / sr + a for t in
                       get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=150, speech_pad_ms=0))])

    def score(shift):  # how many cues start within 0.4 s of a speech start (closer counts more)
        return sum(max((0.4 - abs(c + shift - x) for x in xs), default=0) if xs else 0 for c, xs in zip(cues, onsets))
    shifts = [i / 20 for i in range(int(-search * 20), int(search * 20) + 1)]
    scores = {sh: score(sh) for sh in shifts}
    best = max(scores, key=scores.get)
    # Speech starts all the time in a busy scene, so only move when one shift clearly beats leaving it alone.
    if abs(best) < 0.15 or scores[best] < max(1.5 * scores[0.0], 0.1 * len(cues)):
        return 0.0

    def moved(m):
        g = m.groups()
        return f"{_ts(max(0.0, _secs(*g[:4]) + best))} --> {_ts(max(0.0, _secs(*g[4:]) + best))}"
    Path(srt).write_text(CUE.sub(moved, text), encoding="utf-8")
    return best


# Offline -----------------------------------------------------------------------------------------------------
def _find(dirs, name):
    for d in dirs:
        if (Path(d) / name).exists():
            return Path(d) / name
    return None


def whisper_available():
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def model_installed():
    return _find(MODEL_DIRS, "model.bin") is not None


def _ts(t):
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int(s % 1 * 1000):03d}"


def scan_audio(video, lang="en", progress=None, cancelled=lambda: False):
    """Translate only the speech that isn't in `lang`. progress(fraction, message) is called along the way.
    Returns (path, line_count)."""
    import numpy as np
    from faster_whisper import WhisperModel
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    say = progress or (lambda *_: None)
    ffmpeg = _find(FFMPEG_DIRS, "ffmpeg.exe")
    if not ffmpeg:
        raise SubsError("FFmpeg is missing from the Iron Will folder")
    model_bin = _find(MODEL_DIRS, "model.bin")
    if not model_bin:
        from faster_whisper.utils import download_model
        say(0.0, "Downloading the translator model (one time, ~460 MB)…")
        try:
            download_model("small", output_dir=str(MODEL_HOME))
        except Exception as e:
            raise SubsError(f"Couldn't download the translator model ({e})") from None
        model_bin = MODEL_HOME / "model.bin"
    say(0.0, "Reading the audio…")
    sr = 16000
    raw = subprocess.run([str(ffmpeg), "-v", "error", "-nostdin", "-i", str(video), "-map", "0:a:0", "-ac", "1",
                          "-ar", str(sr), "-f", "s16le", "-"], capture_output=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    if not raw:
        raise SubsError("Couldn't read the audio")
    audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    model = WhisperModel(str(model_bin.parent), device="cpu", compute_type="int8", cpu_threads=os.cpu_count())
    chunks, cur = [], None  # speech merged into pieces of up to 8 s, so a language switch isn't averaged away
    for s in get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=700, speech_pad_ms=200)):
        if cur and s["start"] - cur[1] < sr * 1.5 and s["end"] - cur[0] < sr * 8:
            cur[1] = s["end"]
        else:
            if cur:
                chunks.append(cur)
            cur = [s["start"], s["end"]]
    if cur:
        chunks.append(cur)
    lines = []
    for i, (a, b) in enumerate(chunks):
        if cancelled():
            raise SubsError("Stopped")
        if i % 10 == 0:
            say(i / max(1, len(chunks)), f"Listening for other languages… {i * 100 // max(1, len(chunks))}%")
        clip = audio[a:b]
        if len(clip) < sr * 0.8:
            continue
        found, prob, _ = model.detect_language(clip)
        if found == lang or prob < 0.6:  # unsure = probably a made-up language or noise: leave it alone
            continue
        segs, _ = model.transcribe(clip, task="translate", language=found, beam_size=5, vad_filter=False)
        lines += [(a / sr + g.start, a / sr + g.end, g.text.strip()) for g in segs if g.text.strip()]
    if not lines:
        raise SubsError("No foreign-language speech found (made-up languages need the online search)")
    dest = out_path(video, lang)
    with open(dest, "w", encoding="utf-8") as f:
        for n, (s, e, t) in enumerate(lines, 1):
            f.write(f"{n}\n{_ts(s)} --> {_ts(e)}\n{t}\n\n")
    return dest, len(lines)
