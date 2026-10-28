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
# Speech models by quality: (Whisper size, download size). Each is downloaded the first time it's needed. The small
# one also does the language detection for every quality, because detecting is most of the listening.
QUALITY = {"good": ("small", "460 MB"), "better": ("medium", "1.5 GB"), "best": ("large-v3", "3 GB")}
# Rough scan time per minute of video. Finding the other-language speech costs the same for every quality (~0.15);
# writing only the foreign scenes adds little, writing every line adds a lot. Measured: X-Men: First Class
# (132 min), foreign lines with Best = 26 min.
SCAN_SPEED = {"forced": {"good": 0.16, "better": 0.18, "best": 0.2},
              "full": {"good": 0.3, "better": 0.4, "best": 0.55}}


def model_dirs(size):
    return [APP_DIR / "models" / f"whisper-{size}", DATA_DIR / "models" / f"whisper-{size}",
            Path(rf"E:\_Misc\Zip files and installers\whisper-{size}")]  # last one: the author's dev copy
FFMPEG_DIRS = [APP_DIR / "ffmpeg", APP_DIR, Path(r"E:\_Misc\FFMpeg8.1.2EssentialsBuild\bin")]


class SubsError(Exception):
    pass


class BurnedIn(SubsError):
    """The foreign dialogue is already subtitled in the picture itself."""


def out_path(video, lang, forced=True):
    """<name>.en.forced.srt for the foreign lines only, <name>.en.srt for full subtitles."""
    return Path(video).with_suffix(f".{lang}.forced.srt" if forced else f".{lang}.srt")


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
    title = re.sub(r"[._\-\s]+", " ", name).strip().lower()
    title = re.sub(r"^\d{1,3} ", "", title)  # "06 X-Men_ Apocalypse": a collection's numbering, not the title
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


def _core(text):
    """The words that make a title, minus articles and years."""
    return set(re.findall(r"[a-z0-9]+", str(text).lower())) - {"the", "a", "an"} - {
        w for w in re.findall(r"\d{4}", str(text)) if 1900 <= int(w) <= 2100}


def same_title(a, title, season=None):
    """Is this search result (OpenSubtitles attributes) for the same title as the file? A title search returns
    other films with the title's words in them ("Daredevil" finds "Daredevil Drivers"), so the listed title must
    be the same title, not just contain it."""
    words = _core(title)
    if a.get("moviehash_match") or not words:
        return True
    fd = a.get("feature_details") or {}
    listed = fd.get("parent_title") if season else fd.get("title")
    if listed:
        return _core(listed) == words
    return words <= _core(fd.get("movie_name") or a.get("release") or "")


def find_online(video, lang="en", api_key="", username="", password="", full=False):
    """Download a foreign-parts-only subtitle for this video (full=True: complete subtitles instead). Returns
    (path, downloads_left_today) or raises SubsError. Searching is free; only the download counts against the
    daily limit."""
    key = api_key or APP_API_KEY
    if not key:
        raise SubsError("No OpenSubtitles API key yet (Options > Subtitles)")
    title, season, episode = guess_title(video)
    base = {"languages": lang, "foreign_parts_only": "exclude" if full else "only"}
    results = _search(key, {**base, "moviehash": movie_hash(video)})
    if not results and title:
        results = _search(key, {**base, "query": title, "season_number": season, "episode_number": episode})
    cam = re.compile(r"(?i)\b(hd)?(cam|ts|telesync|tc|hdts|r5|scr|screener)\b")
    files = [(a.get("moviehash_match", False), not cam.search(str(a.get("release") or "")),
              a.get("download_count", 0), f["file_id"])
             for a in (r.get("attributes", {}) for r in results)
             if bool(a.get("foreign_parts_only")) != full and same_title(a, title, season)
             for f in a.get("files", [])[:1]]
    if not files:
        raise SubsError("No subtitles found online for this one" if full
                        else "No foreign-dialogue subtitles found online for this one")
    # An exact file match first, then real releases (Blu-ray, web) over cinema camera copies, which are often cut
    # differently and miss lines, then the most downloaded
    token = None
    if username and password:
        token = _request(f"{API}/login", key, body={"username": username, "password": password}).get("token")
    for *_, file_id in sorted(files, reverse=True)[:2]:
        got = _request(f"{API}/download", key, token, body={"file_id": file_id})
        if not got.get("link"):
            raise SubsError(got.get("message") or "Download limit reached for today")
        req = urllib.request.Request(got["link"], headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as r:
            text = r.read()
        if full or len(CUE.findall(text.decode("utf-8", "replace"))) < 400:
            break  # a "foreign parts" file with hundreds of lines is really a full subtitle mislabelled
    else:
        raise SubsError("No foreign-dialogue subtitles found online for this one")
    dest = out_path(video, lang, forced=not full)
    dest.write_bytes(text)
    try:
        align_to_audio(video, dest)
    except Exception:
        pass  # a subtitle a little off is still better than none
    if not full:
        drop_if_burned_in(video, dest)
    return dest, got.get("remaining")


# Timing -------------------------------------------------------------------------------------------------------
CUE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def _secs(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def align_to_audio(video, srt):
    """Downloaded subtitles are often timed for a different cut of the video (another release, a longer studio
    intro): a second or two off, sometimes minutes. Shift the whole file so its lines start where speech starts in
    this copy, rewrite it, and return the shift applied (0 if no shift is clearly right)."""
    ffmpeg = _find(FFMPEG_DIRS, "ffmpeg.exe")
    text = Path(srt).read_text(encoding="utf-8", errors="replace")
    cues = [_secs(*m.groups()[:4]) for m in CUE.finditer(text)]
    if not ffmpeg or not cues:
        return 0.0
    best = _wide_shift(ffmpeg, video, cues)
    if abs(best) < 0.15:
        return 0.0

    def moved(m):
        g = m.groups()
        return f"{_ts(max(0.0, _secs(*g[:4]) + best))} --> {_ts(max(0.0, _secs(*g[4:]) + best))}"
    Path(srt).write_text(CUE.sub(moved, text), encoding="utf-8")
    return best


def _speech_onsets(ffmpeg, video, sr=16000, block_minutes=10):
    """Where speech starts in the whole soundtrack (seconds). Read and checked 10 minutes at a time, so a long movie
    never sits in memory whole (a 2.5-hour film would be ~600 MB as one piece)."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    import numpy as np

    proc = subprocess.Popen([str(ffmpeg), "-v", "error", "-nostdin", "-i", str(video), "-map", "0:a:0", "-ac", "1",
                             "-ar", str(sr), "-f", "s16le", "-"], stdout=subprocess.PIPE,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    onsets, offset, size = [], 0, sr * 60 * block_minutes * 2  # bytes: 16-bit samples
    try:
        while True:
            raw = proc.stdout.read(size)
            if not raw:
                break
            block = np.frombuffer(raw[:len(raw) // 2 * 2], np.int16).astype(np.float32) / 32768.0
            onsets += [(offset + t["start"]) / sr for t in
                       get_speech_timestamps(block, VadOptions(min_silence_duration_ms=150, speech_pad_ms=0))]
            offset += len(block)
    finally:
        proc.stdout.close()
        proc.wait()
    return np.array(onsets)


def _wide_shift(ffmpeg, video, cues, search=600.0):
    """The shift (seconds) that best lines the cue starts up with speech starts, over the whole soundtrack."""
    import numpy as np

    onsets = _speech_onsets(ffmpeg, video)
    if not len(onsets):
        return 0.0
    cue_starts = np.array(cues)

    def score(shift):  # each cue earns up to 0.4 for starting within 0.4 s of a speech start
        at = cue_starts + shift
        i = np.clip(np.searchsorted(onsets, at), 1, len(onsets) - 1)
        near = np.minimum(np.abs(at - onsets[i - 1]), np.abs(at - onsets[i]))
        return float(np.clip(0.4 - near, 0, None).sum())
    # Every shift within +/- 10 minutes, then a finer look around the winner. Dialogue starts all the time in a busy
    # scene, so a shift only counts when it clearly beats both "no shift" and the best shift somewhere else.
    scores = {i / 4: score(i / 4) for i in range(int(-search * 4), int(search * 4) + 1)}
    coarse = max(scores, key=scores.get)
    runner_up = max((v for k, v in scores.items() if abs(k - coarse) > 2), default=0.0)
    best = max((coarse + i / 20 for i in range(-10, 11)), key=score)
    clear = score(best) >= max(0.15 * len(cues), 1.5 * score(0.0), 1.3 * runner_up)
    return best if clear else 0.0


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


def model_installed(quality="good"):
    return _find(model_dirs(QUALITY[quality][0]), "model.bin") is not None and _find(model_dirs("small"), "model.bin")


def scan_minutes(video, quality="good", kinds=("forced",)):
    """About how long a scan takes, in minutes (for the choice shown before scanning)."""
    try:
        out = subprocess.run([str(_find(FFMPEG_DIRS, "ffmpeg.exe")), "-hide_banner", "-i", str(video)],
                             capture_output=True, text=True, errors="replace",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stderr
        h, m, s = re.search(r"Duration: (\d+):(\d+):(\d+)", out).groups()
        length = int(h) * 60 + int(m) + int(s) / 60
    except Exception:
        length = 120
    return max(1, round(length * SCAN_SPEED["full" if "full" in kinds else "forced"][quality] / 5) * 5)


def _model(size, say):
    found = _find(model_dirs(size), "model.bin")
    if found:
        return found.parent
    from faster_whisper.utils import download_model
    home = model_dirs(size)[1]
    say(0.0, f"Downloading the {size} speech model (one time)…")
    try:
        download_model(size, output_dir=str(home))
    except Exception as e:
        raise SubsError(f"Couldn't download the speech model ({e})") from None
    return home


def _ts(t):
    h, m, s = int(t // 3600), int(t % 3600 // 60), t % 60
    return f"{h:02d}:{m:02d}:{int(s):02d},{int(s % 1 * 1000):03d}"


def scan_audio(video, lang="en", progress=None, cancelled=lambda: False, kinds=("forced",), quality="good"):
    """Write subtitles from the audio. kinds: "forced" = only the speech that isn't in `lang`, translated;
    "full" = all the dialogue (the foreign parts translated). quality picks the speech model (QUALITY).
    progress(fraction, message) is called along the way. Returns {kind: (path, line_count)}.

    Two passes: the small model labels each stretch of speech with its language (fast), then whole scenes are
    translated at once with the chosen model. A whole scene keeps the context ("by pig farmers... and tailors"),
    which short pieces lose."""
    import numpy as np
    from faster_whisper import WhisperModel
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    say = progress or (lambda *_: None)
    ffmpeg = _find(FFMPEG_DIRS, "ffmpeg.exe")
    if not ffmpeg:
        raise SubsError("FFmpeg is missing from the Iron Will folder")
    detector_dir = _model("small", say)
    writer_dir = _model(QUALITY.get(quality, QUALITY["good"])[0], say)
    say(0.0, "Reading the audio…")
    sr = 16000
    raw = subprocess.run([str(ffmpeg), "-v", "error", "-nostdin", "-i", str(video), "-map", "0:a:0", "-ac", "1",
                          "-ar", str(sr), "-f", "s16le", "-"], capture_output=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    if not raw:
        raise SubsError("Couldn't read the audio")
    audio = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    threads = os.cpu_count()
    detector = WhisperModel(str(detector_dir), device="cpu", compute_type="int8", cpu_threads=threads)
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

    # Pass 1: which language is each piece in? (None = the preferred language, or unsure)
    labels = []
    for i, (a, b) in enumerate(chunks):
        if cancelled():
            raise SubsError("Stopped")
        if i % 10 == 0:
            say(0.5 * i / max(1, len(chunks)), f"Listening to the dialogue… {50 * i // max(1, len(chunks))}%")
        if b - a < sr * 0.8:
            labels.append(labels[-1] if labels else None)  # too short to tell: same as the line before
            continue
        found, prob, _ = detector.detect_language(audio[a:b])
        labels.append(None if found == lang or prob < 0.6 else found)  # unsure: a made-up language or noise
    del detector

    # Scenes: neighbouring pieces in the same language, up to ~4 minutes each
    scenes = []
    for (a, b), label in zip(chunks, labels):
        if label is None and "full" not in kinds:
            continue
        last = scenes[-1] if scenes else None
        if last and last[2] == label and a - last[1] < sr * 15 and b - last[0] < sr * 240:
            last[1] = b
        else:
            scenes.append([a, b, label])

    # Pass 2: write each scene with the chosen model
    writer = WhisperModel(str(writer_dir), device="cpu", compute_type="int8", cpu_threads=threads)
    foreign, full = [], []
    for i, (a, b, label) in enumerate(scenes):
        if cancelled():
            raise SubsError("Stopped")
        say(0.5 + 0.5 * i / max(1, len(scenes)), f"Writing the subtitles… {50 + 50 * i // max(1, len(scenes))}%")
        clip = audio[max(0, a - sr // 2):b + sr // 2]
        offset = max(0, a - sr // 2) / sr
        if label is None:
            segs, _ = writer.transcribe(clip, language=lang, beam_size=5, vad_filter=True)
        else:  # Whisper translates into English only; other preferred languages get the speech as spoken
            segs, _ = writer.transcribe(clip, task="translate" if lang == "en" else "transcribe", language=label,
                                        beam_size=5, vad_filter=True)
        lines = [(offset + g.start, offset + g.end, g.text.strip()) for g in segs if g.text.strip()]
        full += lines
        if label is not None:
            foreign += lines
    results = {}
    for kind, lines in (("forced", foreign), ("full", full)):
        if kind not in kinds or not lines:
            continue
        dest = out_path(video, lang, forced=kind == "forced")
        with open(dest, "w", encoding="utf-8") as f:
            for n, (s, e, t) in enumerate(lines, 1):
                f.write(f"{n}\n{_ts(s)} --> {_ts(e)}\n{t}\n\n")
        results[kind] = (dest, len(lines))
    if not results:
        raise SubsError("No foreign-language speech found (made-up languages need the online search)")
    if "forced" in results:
        try:
            drop_if_burned_in(video, results["forced"][0])
        except BurnedIn:
            del results["forced"]
            if not results:
                raise
    return results


# Burned-in check --------------------------------------------------------------------------------------------
BURN_W, BURN_H = 480, 270


def _gray_frame(ffmpeg, video, t):
    out = subprocess.run([str(ffmpeg), "-v", "error", "-nostdin", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
                          "-vf", f"scale={BURN_W}:{BURN_H},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    import numpy as np
    return np.frombuffer(out, np.uint8).reshape(BURN_H, BURN_W) if len(out) == BURN_W * BURN_H else None


def _text_score(img):
    """Sharp, bright strokes along the best few rows of the subtitle area: a line of white letters gives dozens to
    hundreds even when it's short ("Where is it?"), a picture without text a handful."""
    import numpy as np
    if img is None:
        return 0
    band = img[int(BURN_H * 0.72):int(BURN_H * 0.97), int(BURN_W * 0.05):int(BURN_W * 0.95)].astype(np.int16)
    bright = band > 190
    edges = (np.abs(np.diff(band, axis=1)) > 50) & (bright[:, :-1] | bright[:, 1:])
    return int(np.convolve(edges.sum(axis=1), np.ones(3), "same").max())  # letters are several rows tall


def burned_in(video, srt, samples=12):
    """Are this subtitle file's lines already written into the picture? Some releases burn the foreign-dialogue
    subtitles in, and a downloaded copy on top would show every line twice. Compares the subtitle area while a
    line should be showing with moments nearby where no line is: text in most of the first and not the second
    means burned in. Tested: Daredevil S1 E4, 5, 7, 8, 10 (burned in) vs four X-Men / Die Hard films (not)."""
    import numpy as np
    ffmpeg = _find(FFMPEG_DIRS, "ffmpeg.exe")
    text = Path(srt).read_text(encoding="utf-8", errors="replace")
    cues = [(_secs(*m.groups()[:4]), _secs(*m.groups()[4:])) for m in CUE.finditer(text)]
    cues = [c for c in cues if c[1] - c[0] >= 1.2]  # long enough to land a frame inside
    if not ffmpeg or len(cues) < 4:
        return False
    pick = [cues[i] for i in np.linspace(0, len(cues) - 1, min(samples, len(cues))).astype(int)]
    starts, ends = np.array([c[0] for c in cues]), np.array([c[1] for c in cues])
    controls = []
    for a, b in pick:  # nearby, so same scene and lighting, but at least 4 s from any line
        t = next((t for t in (a - 8, b + 8, a - 15, b + 15)
                  if t > 0 and not np.any((starts - 4 < t) & (ends + 4 > t))), None)
        if t is not None:
            controls.append(t)
    inside = [_text_score(_gray_frame(ffmpeg, video, (a + b) / 2)) for a, b in pick]
    outside = [_text_score(_gray_frame(ffmpeg, video, t)) for t in controls]
    # Measured: burned-in Daredevil lines 32-433, clean films almost always under 12 (one stray 96 in 12)
    floor = max(30, 3 * float(np.median(outside)) if outside else 30)
    return sum(s > floor for s in inside) >= 0.6 * len(inside)


def drop_if_burned_in(video, srt):
    """Delete the subtitle file and raise BurnedIn when the video already shows those lines."""
    try:
        burned = burned_in(video, srt)
    except Exception:
        return  # can't tell: keep the subtitles
    if burned:
        Path(srt).unlink(missing_ok=True)
        raise BurnedIn("The foreign dialogue is already subtitled in this video's picture")
