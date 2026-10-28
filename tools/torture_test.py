"""Torture test: plays a folder of awkward files in Iron Will's engine and in VLC, and reports what each one handles.

    python tools\\torture_test.py make  [folder]   build the synthetic test files (FFmpeg)
    python tools\\torture_test.py run   [folder]   play every file in both players, write report.md next to them

Both players run silent and without a window (decoding, seeking and errors are tested; picture quality is not).
Iron Will uses the same libmpv and default settings as the release. Real files can be dropped into the folder too."""
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_DIR = ROOT.parent / "TortureTest"
RELEASE = ROOT.parent / "Release" / "dist" / "Iron Will Media Player"
VLC = Path(os.environ.get("IW_VLC", r"C:\Program Files\VideoLAN\VLC\vlc.exe"))
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# name: (expected outcome, ffmpeg arguments). "play" files must play; "bad" files are broken on purpose, and the
# test is that the player stays up and says so instead of hanging.
V = ["-f", "lavfi", "-i", "testsrc2=s=1280x720:rate=25"]
A = ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
T = ["-t", "8"]
CASES = {
    "h264_aac.mp4": ("play", [*V, *A, *T, "-c:v", "libx264", "-c:a", "aac"]),
    "hevc_10bit_hdr10.mkv": ("play", ["-f", "lavfi", "-i", "testsrc2=s=1920x1080:rate=24", *A, *T, "-c:v", "libx265",
                                      "-pix_fmt", "yuv420p10le", "-color_primaries", "bt2020", "-color_trc",
                                      "smpte2084", "-colorspace", "bt2020nc", "-x265-params", "log-level=error",
                                      "-c:a", "eac3"]),
    "av1_opus.webm": ("play", ["-f", "lavfi", "-i", "testsrc2=s=640x360:rate=24", *A, "-t", "4", "-c:v", "libaom-av1",
                               "-cpu-used", "8", "-crf", "40", "-c:a", "libopus"]),
    "vp9_opus.webm": ("play", [*V, *A, *T, "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8",
                               "-c:a", "libopus"]),
    "mpeg2_ac3.ts": ("play", [*V, *A, *T, "-c:v", "mpeg2video", "-c:a", "ac3"]),
    "mpeg4_mp3.avi": ("play", [*V, *A, *T, "-c:v", "mpeg4", "-vtag", "XVID", "-c:a", "libmp3lame"]),
    "4k_h264.mp4": ("play", ["-f", "lavfi", "-i", "testsrc2=s=3840x2160:rate=30", *A, "-t", "5", "-c:v", "libx264",
                             "-preset", "ultrafast", "-c:a", "aac"]),
    "120fps.mp4": ("play", ["-f", "lavfi", "-i", "testsrc2=s=1280x720:rate=120", *T, "-c:v", "libx264",
                            "-preset", "ultrafast"]),
    "variable_framerate.mkv": ("play", [*V, *T, "-vf", "setpts='PTS+0.02*sin(N/3)/TB'", "-fps_mode", "vfr",
                                        "-c:v", "libx264"]),
    "interlaced.ts": ("play", [*V, *A, *T, "-vf", "tinterlace=interleave_top", "-flags", "+ilme+ildct",
                               "-c:v", "mpeg2video", "-c:a", "ac3"]),
    "odd_size_anamorphic.mkv": ("play", ["-f", "lavfi", "-i", "testsrc2=s=719x403:rate=25", *T, "-vf", "setsar=32/27",
                                         "-c:v", "libx264", "-pix_fmt", "yuv444p"]),
    "rotated_phone.mp4": ("play", ["-display_rotation", "90", *V, *A, *T, "-c:v", "libx264", "-c:a", "aac"]),
    "surround_7.1.mkv": ("play", [*V, "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=48000", *T, "-c:v", "libx264",
                                  "-c:a", "flac", "-af", "pan=7.1|c0=c0|c1=c0|c2=c0|c3=c0|c4=c0|c5=c0|c6=c0|c7=c0"]),
    "audio_flac.flac": ("play", [*A, *T]),
    "audio_opus.opus": ("play", [*A, *T, "-c:a", "libopus"]),
    "fragmented.mp4": ("play", [*V, *A, *T, "-c:v", "libx264", "-c:a", "aac", "-movflags", "frag_keyframe+empty_moov"]),
    "long_3_hours.mkv": ("play", ["-f", "lavfi", "-i", "testsrc2=s=320x180:rate=1", "-t", "10800", "-c:v", "libx264",
                                  "-preset", "ultrafast", "-g", "60"]),
    "unicode_名前_ñ.mkv": ("play", [*V, *T, "-c:v", "libx264"]),
    # Built in post_make(): many tracks, cut and damaged copies, non-media files.
    "30_subtitle_tracks.mkv": ("play", None),
    "6_audio_tracks.mkv": ("play", None),
    "ass_styled_subs.mkv": ("play", None),
    "truncated_half.mp4": ("bad", None),
    "corrupt_middle.mkv": ("bad", None),
    "no_moov.mp4": ("bad", None),
    "empty.mkv": ("bad", None),
    "text_renamed.mp4": ("bad", None),
}
LANGS = ["eng", "spa", "fra", "deu", "ita", "por", "rus", "jpn", "kor", "chi", "ara", "hin", "tur", "pol", "nld",
         "swe", "nor", "dan", "fin", "ces", "hun", "ell", "heb", "tha", "vie", "ind", "ukr", "ron", "bul", "hrv"]


def ffmpeg():
    from ironwill.dupes.fingerprint import find_tool
    return str(find_tool("ffmpeg"))


def make(folder):
    folder.mkdir(parents=True, exist_ok=True)
    ff = ffmpeg()
    for name, (_, args) in CASES.items():
        if args and not (folder / name).exists():
            print("making", name)
            subprocess.run([ff, "-v", "error", "-y", *args, str(folder / name)], check=True, creationflags=NO_WINDOW)
    base = folder / "h264_aac.mp4"
    with tempfile.TemporaryDirectory() as tmp:
        srts = []
        for i, lang in enumerate(LANGS):
            p = Path(tmp) / f"{i}.srt"
            p.write_text("".join(f"{n + 1}\n00:00:0{n},000 --> 00:00:0{n},900\nLine {n + 1} ({lang})\n\n"
                                 for n in range(8)), encoding="utf-8")
            srts.append(p)
        ass = Path(tmp) / "styled.ass"
        ass.write_text("[Script Info]\nScriptType: v4.00+\nPlayResX: 1280\nPlayResY: 720\n\n[V4+ Styles]\n"
                       "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, Bold, Outline, Alignment\n"
                       "Style: Default,Arial,48,&H0000FFFF,&H00000000,1,3,2\n\n[Events]\n"
                       "Format: Layer, Start, End, Style, Text\n"
                       "Dialogue: 0,0:00:00.00,0:00:04.00,Default,{\\an8\\c&H00FF00&}Top, green\n"
                       "Dialogue: 0,0:00:01.00,0:00:07.00,Default,{\\move(100,600,1100,300)\\fad(300,300)}Moving "
                       "and fading\n", encoding="utf-8")
        built = {
            "30_subtitle_tracks.mkv": ["-i", str(base), *sum((["-i", str(s)] for s in srts), []), "-map", "0",
                                       *sum((["-map", str(i + 1)] for i in range(len(srts))), []), "-c", "copy",
                                       *sum(([f"-metadata:s:s:{i}", f"language={l}"] for i, l in enumerate(LANGS)),
                                            [])],
            "6_audio_tracks.mkv": ["-i", str(base), *sum((["-map", "0:a"] for _ in range(6)), []), "-map", "0:v",
                                   "-c", "copy", *sum(([f"-metadata:s:a:{i}", f"language={l}"]
                                                       for i, l in enumerate(LANGS[:6])), [])],
            "ass_styled_subs.mkv": ["-i", str(base), "-i", str(ass), "-map", "0", "-map", "1", "-c", "copy"],
        }
        for name, args in built.items():
            if not (folder / name).exists():
                print("making", name)
                subprocess.run([ff, "-v", "error", "-y", *args, str(folder / name)], check=True,
                               creationflags=NO_WINDOW)
    data = base.read_bytes()
    (folder / "truncated_half.mp4").write_bytes(data[: len(data) // 2])
    mkv = (folder / "6_audio_tracks.mkv").read_bytes()
    third = len(mkv) // 3
    (folder / "corrupt_middle.mkv").write_bytes(mkv[:third] + os.urandom(third) + mkv[2 * third:])
    moov = data.find(b"moov")
    (folder / "no_moov.mp4").write_bytes(data[:moov - 4] if data.find(b"mdat") < moov else data[moov + 4:])
    (folder / "empty.mkv").write_bytes(b"")
    (folder / "text_renamed.mp4").write_text("This is not a video.\n" * 50)
    print("test files in", folder)


def media_files(folder):
    # Subfolders hold real-world files; names repeat across them, so results are keyed by the relative path.
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() not in (".md", ".txt", ".log", ".json", ".py", ".ps1", ".bat", ".csv"))


def key(folder, f):
    return f.relative_to(folder).as_posix()


def expected(folder, f):
    """Made test files say what they are in CASES; for real files ffprobe decides (readable means it must play)."""
    if f.parent == folder and f.name in CASES:
        return CASES[f.name][0]
    from ironwill.dupes.fingerprint import probe
    try:
        return "play" if probe(f)["duration"] > 0 else "bad"
    except Exception:
        return "bad"


# ---------------------------------------------------------------------------------------------------- Iron Will


def iron_will(folder, files):
    os.environ["PATH"] = str(RELEASE) + os.pathsep + os.environ["PATH"]
    import mpv
    from ironwill.settings import ALL, apply_to_mpv

    errors = []
    m = mpv.MPV(vo="null", ao="null", mute=True, hwdec="auto-safe", ytdl=False, keep_open="no",
                input_default_bindings=False, log_handler=lambda lvl, comp, msg: lvl in ("error", "fatal")
                and errors.append(f"{comp}: {msg.strip()}"), loglevel="error")
    apply_to_mpv(m, {k: s.default for k, s in ALL.items()})
    m["vo"], m["ao"] = "null", "null"
    events = {"loaded": threading.Event(), "restart": threading.Event(), "end": threading.Event()}
    end_reason = {}

    @m.event_callback("file-loaded")
    def _loaded(_e):
        events["loaded"].set()

    @m.event_callback("playback-restart")
    def _restart(_e):
        events["restart"].set()

    @m.event_callback("end-file")
    def _end(e):
        d = e.data
        end_reason["reason"] = str(getattr(d, "reason", ""))
        end_reason["error"] = getattr(d, "error", 0)
        events["end"].set()

    def wait(name, timeout):
        return events[name].wait(timeout)

    results = {}
    for f in files:
        for ev in events.values():
            ev.clear()
        errors.clear()
        end_reason.clear()
        r = {"opened": False, "seek": None, "reached_end": False, "seconds_to_picture": None, "errors": []}
        t0 = time.perf_counter()
        m.play(str(f))
        if wait("loaded", 20) and not events["end"].is_set():
            r["opened"] = True
            if wait("restart", 20):
                r["seconds_to_picture"] = round(time.perf_counter() - t0, 2)
            dur = m.duration or 0
            r["duration"] = round(dur, 1)
            tracks = m.track_list or []
            r["tracks"] = {k: sum(1 for t in tracks if t.get("type") == k) for k in ("video", "audio", "sub")}
            if dur > 4:
                r["seek"], r["seek_s"] = True, []
                for frac in ((0.25, 0.5, 0.75) if dur >= 60 else (0.5,)):
                    events["restart"].clear()
                    target = dur * frac
                    t1 = time.perf_counter()
                    m.time_pos = target
                    wait("restart", 15)
                    r["seek_s"].append(round(time.perf_counter() - t1, 2))
                    time.sleep(0.5)
                    pos = m.time_pos
                    if pos is None or abs(pos - target) >= 1.5:
                        r["seek"] = False
                        r["seek_to"] = (round(target, 1), None if pos is None else round(pos, 1))
                    if events["end"].is_set():
                        break
                if not events["end"].is_set() and not m.idle_active:  # a seek sent once it ended lands on the next file
                    m.time_pos = max(0.0, dur - 2)
            # Like the app, mpv keeps the last frame up at the end (keep-open), so "the end" is eof-reached.
            deadline = time.perf_counter() + 20
            while time.perf_counter() < deadline and not m.eof_reached and not events["end"].is_set():
                time.sleep(0.1)
            r["reached_end"] = bool(m.eof_reached) or (events["end"].is_set() and not end_reason.get("error"))
        else:
            wait("end", 5)
        gave_up = events["end"].is_set() or r["reached_end"]
        m.stop()
        idle_by = time.perf_counter() + 10  # a late "file ended" must not land on the next file
        while time.perf_counter() < idle_by and not m.idle_active:
            time.sleep(0.05)
        time.sleep(0.3)
        r["end"] = end_reason.get("reason", "") if gave_up else "timeout"
        r["errors"] = errors[:5]
        results[key(folder, f)] = r
        print(f"  iron will  {key(folder, f)[:60]:60} opened={r['opened']} seek={r['seek']} end={r['reached_end']}")
    m.terminate()
    return results


# ---------------------------------------------------------------------------------------------------------- VLC


def vlc(folder, files):
    results = {}
    if not VLC.exists():
        print("VLC not found (set IW_VLC); skipping it")
        return results
    from ironwill.dupes.fingerprint import probe
    for f in files:
        try:
            start = max(0.0, probe(f)["duration"] - 3)
        except Exception:
            start = 0.0
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "vlc.log"
            # Play from 3 s before the end, so a working file finishes quickly and a broken one shows its errors.
            cmd = [str(VLC), "--intf", "dummy", "--dummy-quiet", "--vout", "dummy", "--aout", "adummy", "--no-audio",
                   "--play-and-exit", "--no-one-instance", "--no-video-title-show", "--no-qt-error-dialogs",
                   "--file-logging", "--logfile", str(log), "--log-verbose", "2", f"--start-time={start:.1f}", str(f)]
            t0 = time.perf_counter()
            try:
                proc = subprocess.run(cmd, timeout=40, creationflags=NO_WINDOW)
                code, hung = proc.returncode, False
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/F", "/IM", "vlc.exe"], capture_output=True, creationflags=NO_WINDOW)
                code, hung = None, True
            took = round(time.perf_counter() - t0, 1)
            text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
        errs = [l.strip() for l in text.splitlines() if re.search(r"\berror\b", l)]
        decoded = bool(re.search(r"(?i)(Received first picture|buffering done|end of stream|EOF reached|"
                                 r"es out.*?Decoder|using (audio|video) decoder)", text))
        fatal = bool(re.search(r"(?i)(no suitable demux|cannot open|could not open|Your input can't be opened|"
                               r"unknown format|no suitable decoder)", text))
        r = {"opened": decoded and not fatal, "hung": hung, "exit": code, "seconds": took, "errors": errs[:5]}
        results[key(folder, f)] = r
        print(f"  vlc        {key(folder, f)[:60]:60} opened={r['opened']} hung={hung} {took}s")
    return results


# ------------------------------------------------------------------------------------------------------- report


def report(folder, iw, vl):
    rows, iw_pass, vl_pass, total = [], 0, 0, 0
    disagree = []
    for f in media_files(folder):
        expect = expected(folder, f)
        a, b = iw.get(key(folder, f), {}), vl.get(key(folder, f), {})
        if expect == "play":
            ok_a = a.get("opened") and a.get("seek") is not False and a.get("reached_end")
            ok_b = b.get("opened") and not b.get("hung")
        else:  # broken on purpose: the player must give up cleanly
            ok_a = a.get("end", "timeout") != "timeout"
            ok_b = bool(b) and not b.get("hung")
        total += 1
        iw_pass += bool(ok_a)
        vl_pass += bool(ok_b)
        if bool(ok_a) != bool(ok_b):
            disagree.append(key(folder, f))
        note = "; ".join(a.get("errors", [])[:2]) if not ok_a else ""
        seeks = "/".join(str(s) for s in a.get("seek_s", []))
        rows.append(f"| {key(folder, f)[:70]} | {expect} | {'✅' if ok_a else '❌'} | {a.get('seconds_to_picture', '')} | "
                    f"{seeks} | {'✅' if ok_b else '❌'} | {b.get('seconds', '')} | {note[:120]} |")
    text = (f"# Torture test, {time.strftime('%Y-%m-%d %H:%M')}\n\n"
            f"Iron Will {iw_pass}/{total} · VLC {vl_pass}/{total}\n\n"
            + (f"Players disagree on {len(disagree)}: " + ", ".join(disagree) + "\n\n" if disagree else "")
            + "\"play\" files must open, seek to the middle and reach the end. \"bad\" files are broken on purpose: "
            "passing means the player gave up cleanly instead of hanging.\n\n"
            "| File | Expect | Iron Will | IW s to picture | IW seek s | VLC | VLC s total | Iron Will errors |\n"
            "|---|---|---|---|---|---|---|---|\n" + "\n".join(rows) + "\n")
    out = folder / "report.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print("report:", out)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    folder = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DIR
    if cmd == "make":
        make(folder)
    else:
        files = media_files(folder)
        print("Iron Will:")
        iw = iron_will(folder, files)
        print("VLC:")
        vl = vlc(folder, files)
        report(folder, iw, vl)


if __name__ == "__main__":
    main()
