"""Head-to-head: the same checks for every player on the torture-test files.

Each player is driven through its remote-control interface, muted and with no visible window:
  mpv      standalone mpv.exe, JSON IPC (same engine as Iron Will, none of its settings)
  vlc      vlc.exe, HTTP interface
  mpcbe    an isolated copy of portable MPC-BE (web interface on, muted), so the user's own copy is untouched

Per file: time until playing, three timed seeks (25/50/75 %, one at 50 % under a minute) checked against where
the player says it is, then a jump to 2 s before the end and whether it reaches the end. Run Iron Will itself with
torture_test.py; this writes compare.md next to report.md.

    python tools/compare_players.py [folder] [mpv,vlc,mpcbe]
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from torture_test import DEFAULT_DIR, NO_WINDOW, VLC, expected, key, media_files  # noqa: E402

MPV = Path(os.environ.get("IW_MPV", r"E:\_Misc\Mpv\mpv-x86_64-20260610-git-304426c\mpv.exe"))
MPCBE = Path(os.environ.get("IW_MPCBE", r"E:\IronWillMediaPlayerRepo\PlayerCopies\MPC-BE\mpc-be64.exe"))
OPEN_TIMEOUT, SEEK_TIMEOUT, END_TIMEOUT = 20, 15, 20


class Mpv:
    name = "mpv"

    def start(self, f):
        self.pipe_name = rf"\\.\pipe\iw_compare_{os.getpid()}"
        self.proc = subprocess.Popen([str(MPV), "--vo=null", "--ao=null", "--mute=yes", "--keep-open=yes",
                                     "--no-config", "--really-quiet", f"--input-ipc-server={self.pipe_name}", str(f)],
                                    creationflags=NO_WINDOW)
        deadline = time.perf_counter() + 5
        while True:
            try:
                self.pipe = open(self.pipe_name, "r+b", buffering=0)
                return
            except OSError:
                if time.perf_counter() > deadline or self.proc.poll() is not None:
                    raise
                time.sleep(0.05)

    def _get(self, prop):
        self.pipe.write((json.dumps({"command": ["get_property", prop], "request_id": 1}) + "\n").encode())
        while True:
            line = b""
            while not line.endswith(b"\n"):
                line += self.pipe.read(1)
            msg = json.loads(line)
            if msg.get("request_id") == 1:
                return msg.get("data")

    def state(self):
        if self.proc.poll() is not None:
            return None, None, False, True
        pos, dur = self._get("time-pos"), self._get("duration")
        return pos, dur, pos is not None and not self._get("seeking"), bool(self._get("eof-reached"))

    def seek(self, t):
        self.pipe.write((json.dumps({"command": ["seek", t, "absolute"]}) + "\n").encode())

    def close(self):
        try:
            self.pipe.close()
        except Exception:
            pass
        self.proc.kill()
        self.proc.wait()


class Vlc:
    name = "vlc"
    url = "http://127.0.0.1:18090/requests/status.json"

    def start(self, f):
        # A clip under a second ends before VLC's web interface answers; repeating it keeps it on long enough for
        # the check to see it play (it still ends on its own afterwards)
        from ironwill.dupes.fingerprint import probe
        try:
            self.known = probe(f)["duration"]
        except Exception:
            self.known = 0
        repeat = ["--input-repeat=10"] if 0 < self.known < 2 else []
        self.proc = subprocess.Popen([str(VLC), *repeat, "--intf", "dummy", "--dummy-quiet", "--extraintf", "http",
                                      "--http-host", "127.0.0.1", "--http-port", "18090", "--http-password", "iw",
                                      "--vout", "dummy", "--aout", "adummy", "--no-one-instance",
                                      "--no-qt-error-dialogs", "--no-video-title-show", str(f)],
                                     creationflags=NO_WINDOW)
        self.opener = urllib.request.build_opener(urllib.request.HTTPBasicAuthHandler(
            _pw(self.url, "", "iw")))
        self.played = False

    def _status(self, query=""):
        with self.opener.open(self.url + query, timeout=3) as r:
            return json.loads(r.read())

    def state(self):
        if self.proc.poll() is not None:
            return None, None, False, True
        try:
            s = self._status()
        except Exception:
            return None, None, False, False
        length = s.get("length") or 0
        if not length and s.get("state") == "playing" and 0 < self.known < 2:
            length = self.known  # VLC gives the length in whole seconds: 0 for a clip under one
        pos = (s.get("position") or 0) * length if length else None  # "time" is whole seconds; position is a fraction
        playing = s.get("state") == "playing"
        self.played = self.played or playing
        # At the end VLC drops to "stopped" with length and position reset to 0, so "stopped after it played" is the
        # end (ChatGPT's deep check, 2026-10-28)
        return pos, length or None, playing, s.get("state") == "stopped" and self.played

    def seek(self, t):
        self._status(f"?command=seek&val={int(t)}")

    def close(self):
        self.proc.kill()
        self.proc.wait()


class MpcBe:
    name = "mpcbe"
    base = "http://127.0.0.1:13579"

    def start(self, f):
        self.proc = subprocess.Popen([str(MPCBE), str(f), "/play", "/minimized", "/nofocus", "/new"])

    def _vars(self):
        with urllib.request.urlopen(self.base + "/variables.html", timeout=3) as r:
            html = r.read().decode("utf-8", "replace")
        import re
        return {m[0]: m[1] for m in re.findall(r'<p id="(\w+)">([^<]*)</p>', html)}

    def state(self):
        if self.proc.poll() is not None:
            return None, None, False, True
        try:
            v = self._vars()
        except Exception:
            return None, None, False, False
        pos, dur, st = int(v.get("position", 0)) / 1000, int(v.get("duration", 0)) / 1000, int(v.get("state", -1))
        # At the end MPC-BE goes straight on to the next file in the folder: a different length means it finished
        name = v.get("file", "")
        self.first = getattr(self, "first", None) or (name if dur else None)
        if self.first and name and name != self.first:
            return None, None, False, True
        return (pos if dur else None), (dur or None), st == 2, st == 0 and dur > 0

    def seek(self, t):
        h, rem = divmod(t, 3600)
        mnt, s = divmod(rem, 60)
        urllib.request.urlopen(f"{self.base}/command.html?wm_command=-1&position={int(h)}:{int(mnt):02}:{s:06.3f}",
                               timeout=3).read()

    def close(self):
        self.proc.kill()
        self.proc.wait()


def _pw(url, user, password):
    mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    mgr.add_password(None, url, user, password)
    return mgr


def wait_for(player, test, timeout):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        st = player.state()
        if test(*st):
            return st
        if st[3] and st[0] is None:  # gone or ended before it ever played
            return None
        time.sleep(0.1)
    return None


def check(player, f):
    r = {"opened": False, "seek": None, "seek_s": [], "reached_end": False, "error": ""}
    t0 = time.perf_counter()
    try:
        player.start(f)
        st = wait_for(player, lambda pos, dur, playing, ended: playing and dur, OPEN_TIMEOUT)
        if st:
            r["opened"], r["seconds_to_picture"] = True, round(time.perf_counter() - t0, 2)
            dur = st[1]
            if dur > 4:
                r["seek"] = True
                for frac in ((0.25, 0.5, 0.75) if dur >= 60 else (0.5,)):
                    target = dur * frac
                    t1 = time.perf_counter()
                    player.seek(target)
                    st = wait_for(player, lambda pos, d, playing, ended: pos is not None and abs(pos - target) < 1.5
                                  and playing, SEEK_TIMEOUT)
                    r["seek_s"].append(round(time.perf_counter() - t1, 2) if st else None)
                    if not st:
                        r["seek"] = False
                player.seek(max(0.0, dur - 2))
            r["reached_end"] = bool(wait_for(player, lambda pos, d, playing, ended: ended
                                             or (pos is not None and d and pos >= d - 0.6), END_TIMEOUT))
        else:
            # A broken file passes if the player gave up (or kept running without hanging the machine).
            r["gave_up"] = True
    except Exception as e:  # the player crashed or its remote control died
        r["error"] = f"{type(e).__name__}: {e}"[:120]
    finally:
        try:
            player.close()
        except Exception:
            pass
    return r


PLAYERS = {"mpv": (Mpv, MPV), "vlc": (Vlc, VLC), "mpcbe": (MpcBe, MPCBE)}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    names = sys.argv[2].split(",") if len(sys.argv) > 2 else list(PLAYERS)
    files = media_files(folder)
    saved = folder / "compare.json"  # re-running some players keeps the others' results
    results = json.loads(saved.read_text(encoding="utf-8")) if saved.exists() else {}
    for name in names:
        cls, exe = PLAYERS[name]
        if not exe.exists():
            print(f"{name}: not found at {exe}, skipping")
            continue
        results[name] = {}
        for f in files:
            r = check(cls(), f)
            results[name][key(folder, f)] = r
            print(f"  {name:6} {key(folder, f)[:60]:60} opened={r['opened']} seek={r['seek']} "
                  f"end={r['reached_end']} {r['error']}", flush=True)
    (folder / "compare.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    report(folder, files, results)


def passed(expect, r):
    if expect == "play":
        return r.get("opened") and r.get("seek") is not False and r.get("reached_end") and not r.get("error")
    # Broken on purpose: the player must give up or finish cleanly. Still "playing" with no end means it hung
    # (MPC-BE on corrupt_middle.mkv: Windows lists it Not Responding).
    return not r.get("error") and (r.get("gave_up") or r.get("reached_end"))


def report(folder, files, results):
    names = list(results)
    head = "| File | Expect | " + " | ".join(f"{n} | {n} seek s" for n in names) + " |\n"
    head += "|---|---|" + "---|---|" * len(names) + "\n"
    rows, score = [], {n: 0 for n in names}
    for f in files:
        k, expect = key(folder, f), expected(folder, f)
        cells = []
        for n in names:
            r = results[n].get(k, {})
            ok = passed(expect, r)
            score[n] += bool(ok)
            cells += ["✅" if ok else "❌", "/".join(str(s) for s in r.get("seek_s", []))]
        rows.append(f"| {k[:70]} | {expect} | " + " | ".join(cells) + " |")
    text = (f"# Player comparison, {time.strftime('%Y-%m-%d %H:%M')}\n\n"
            + " · ".join(f"{n} {score[n]}/{len(files)}" for n in names) + "\n\n"
            "Same checks as Iron Will in report.md: open, seek 25/50/75 % (the player must say it is within 1.5 s of "
            "the target), reach the end.\n\n" + head + "\n".join(rows) + "\n")
    (folder / "compare.md").write_text(text, encoding="utf-8")
    print(text.split("\n\n")[1])


if __name__ == "__main__":
    main()
