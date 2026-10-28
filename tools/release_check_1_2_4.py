"""Iron Will 1.2.4 release check: runs every check in RELEASE-1.2.4-REVIEW.md that doesn't need a TV or camera.

Written by Claude for ChatGPT to READ, judge and RUN herself (her tooling can't create files). Silent: ao/vo null,
offscreen Qt, media read-only, no casting, no camera. Every check prints PASS/FAIL with its evidence; the last line
is a summary, then "ALL DONE" only if the script reached the end.

    E:\\PythonMedia\\python.exe -X utf8 tools\\release_check_1_2_4.py
Log: E:\\IronWillMediaPlayerRepo\\TortureTest\\release-check-1.2.4.log
"""
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
TT = Path(r"E:\IronWillMediaPlayerRepo\TortureTest")
LOG = TT / "release-check-1.2.4.log"
TMP = Path(tempfile.mkdtemp(prefix="iw124_"))
results = []


def emit(*parts):
    line = " ".join(str(p) for p in parts)
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def check(name):
    def wrap(fn):
        def run():
            t0 = time.time()
            try:
                ok, evidence = fn()
            except Exception:
                ok, evidence = False, traceback.format_exc(limit=3).replace("\n", " | ")
            results.append((name, ok))
            emit("PASS" if ok else "FAIL", name, f"({time.time() - t0:.1f}s)", "-", evidence)
        return run
    return wrap


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def pump(app, s):
    t = time.time()
    while time.time() - t < s:
        app.processEvents()
        time.sleep(0.02)


# ---------------------------------------------------------------------------------------------- basics
@check("compileall")
def c_compile():
    r = subprocess.run([sys.executable, "-m", "compileall", "-q", str(ROOT / "ironwill")], capture_output=True, text=True)
    return r.returncode == 0, f"exit {r.returncode} {r.stdout[-200:]}"


@check("version is 1.2.4")
def c_version():
    import ironwill
    return ironwill.__version__ == "1.2.4", ironwill.__version__


@check("F5 every text setting has a text widget kind")
def c_kinds():
    from ironwill.settings import ALL
    bad = [k for k, s in ALL.items() if isinstance(s.default, str) and not s.choices and not getattr(s, "kind", "")]
    return not bad, f"missing kind: {bad}"


# ---------------------------------------------------------------------------------------------- GUI (offscreen)
def gui_checks():
    from PySide6.QtCore import QEvent, Qt, QPoint
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton
    app = QApplication.instance() or QApplication(sys.argv)
    from ironwill.ui.window import MainWindow
    from ironwill.ui.options import OptionsDialog
    w = MainWindow()
    w.engine.mpv["ao"], w.engine.mpv["vo"] = "null", "null"
    w.engine.mpv.mute = True
    w.show()

    @check("F5 Options dialog opens")
    def c_options():
        d = OptionsDialog(w)
        n = len(d.fields)
        d.close()
        return n > 100, f"{n} fields"

    @check("F2 Space pauses from a stray widget, types in a text box")
    def c_space():
        calls = []
        orig = w.play_pause
        w.play_pause = lambda: calls.append(1)
        b = QPushButton("x", w)
        b.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        b.show()
        b.setFocus()
        pump(app, 0.2)
        app.sendEvent(b, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier, " "))
        btn = len(calls)
        e = QLineEdit(w)
        e.show()
        e.setFocus()
        pump(app, 0.2)
        app.sendEvent(e, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier, " "))
        w.play_pause = orig
        b.deleteLater()
        e.deleteLater()
        return btn == 1 and len(calls) == 1 and e.text() == " ", f"button->{btn} pause, textbox text={e.text()!r}"

    @check("F1 controls don't hide while a menu is open")
    def c_menu():
        from ironwill.ui.widgets import dark_menu
        w.open_path(TT / "h264_aac.mp4")
        pump(app, 1.5)
        w.show_chrome()
        m = dark_menu(w)
        m.addAction("a")
        m.popup(w.mapToGlobal(QPoint(50, 50)))
        pump(app, 0.3)
        w.hide_chrome()
        stays = w.chrome_visible
        m.close()
        return stays, f"chrome_visible during menu = {stays}"

    @check("N7 bookmarks add/sort/remove")
    def c_bookmarks():
        key = str(w.engine.path).lower()
        saved = dict(w.cfg.values.get("bookmarks", {}))
        marks = dict(saved)
        marks[key] = [{"pos": 5.0, "name": "b"}, {"pos": 2.0, "name": "a"}]
        w.cfg.values["bookmarks"] = marks
        order = [b["pos"] for b in w.bookmarks()]
        w.remove_bookmark(5.0)
        left = [b["pos"] for b in w.bookmarks()]
        w.cfg.values["bookmarks"] = saved
        w.cfg.save()
        return order == [2.0, 5.0] and left == [2.0], f"sorted {order}, after remove {left}"

    @check("N2 playlist next/prev across folders + leaving the list")
    def c_playlist():
        from ironwill import playlist
        files = [TT / "h264_aac.mp4", TT / "mpeg4_mp3.avi", TT / "vp9_opus.webm"]
        pl = TMP / "t.m3u8"
        playlist.write_m3u(pl, files)
        back = playlist.read_m3u(pl)
        w.open_path(pl)
        w.engine.mpv.pause = True
        pump(app, 1.5)
        seq = [Path(w.engine.path).name]
        for step in (1, 1, 1, -1):
            w.play_neighbor(step)
            w.engine.mpv.pause = True
            pump(app, 1.0)
            seq.append(Path(w.engine.path).name)
        w.open_path(TT / "interlaced.ts")
        pump(app, 1)
        left = w.custom_list is None
        want = ["h264_aac.mp4", "mpeg4_mp3.avi", "vp9_opus.webm", "vp9_opus.webm", "mpeg4_mp3.avi"]
        return back == files and seq == want and left, f"seq {seq}, left list {left}"

    @check("N9 360 auto-on, drag turns view, normal file turns it off")
    def c_360():
        src = TMP / "equirect.mp4"
        from ironwill.dupes.fingerprint import find_tool
        subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=2560x1280:d=5",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)], check=True)
        w.open_path(src)
        pump(app, 2.5)
        on = bool(w.view360)
        w.drag360_from = QPoint(600, 300)
        w._drag_360(QPoint(400, 250))
        pump(app, 0.5)
        yaw = [f["params"].get("yaw") for f in (w.engine.mpv.vf or []) if f.get("label") == "v360"]
        w.open_path(TT / "h264_aac.mp4")
        pump(app, 1.5)
        off = w.view360 is None and not w.engine.mpv.vf
        return on and yaw and float(yaw[0]) != 0 and off, f"auto {on}, yaw {yaw}, off after normal {off}"

    @check("N8 visualizer only on audio-only files, cleared for video")
    def c_viz():
        w.cfg.values["visualizer"] = "spiral"
        w.open_path(TT / "audio_flac.flac")
        pump(app, 2)
        on = bool(w.engine.mpv._get_property("lavfi-complex"))
        w.open_path(TT / "h264_aac.mp4")
        pump(app, 1.5)
        off = not w.engine.mpv._get_property("lavfi-complex")
        return on and off, f"audio file graph set {on}, video file cleared {off}"

    @check("N13 library scans, searches, plays")
    def c_library():
        from ironwill.ui import library
        library.THUMBS = TMP / "thumbs"
        w.cfg.values["library_folders"] = str(TT)
        d = library.Library(w)
        d.show()
        pump(app, 8)
        n = d.grid.count()
        d.search.setText("spider")
        pump(app, 0.3)
        vis = [d.grid.item(i) for i in range(n) if not d.grid.item(i).isHidden()]
        d._play(vis[0])
        pump(app, 1.5)
        w.cfg.values["library_folders"] = ""
        return n > 300 and len(vis) == 1 and "Spider" in w.engine.path, f"{n} videos, search hits {len(vis)}"

    @check("N12 theme recolors stylesheets; default stays Iron Will red")
    def c_theme():
        from PySide6.QtGui import QColor
        from ironwill.ui import widgets
        from ironwill.ui.options import STYLE
        from ironwill.settings import ALL
        keep = widgets.ACCENT
        widgets.ACCENT = QColor("#1E88E5")
        css = widgets.themed(STYLE)
        widgets.ACCENT = keep
        return ("#E81123" not in css and "232,17,35" not in css and ALL["theme_accent"].default == "#E81123",
                f"default {ALL['theme_accent'].default}")

    @check("N11 desktop capture opens (camera not opened)")
    def c_capture():
        w.open_capture("desktop")
        pump(app, 3)
        ok = w.loaded_ok and (w.engine.mpv.video_params or {}).get("w")
        return bool(ok), f"loaded {w.loaded_ok} size {(w.engine.mpv.video_params or {}).get('w')}"

    for fn in (c_options, c_space, c_menu, c_bookmarks, c_playlist, c_360, c_viz, c_library, c_theme, c_capture):
        fn()
    w.engine.mpv.command("stop")
    w.close()


# ---------------------------------------------------------------------------------------------- engine / files
@check("N1 equalizer: every preset builds a chain libmpv accepts")
def c_eq():
    import torture_test as t
    os.environ["PATH"] = str(t.RELEASE) + os.pathsep + os.environ["PATH"]
    import mpv
    from ironwill import settings as s
    m = mpv.MPV(vo="null", ao="null", mute=True)
    m.play(str(TT / "h264_aac.mp4"))
    m.wait_until_playing()
    bad = []
    for key in s.EQ_PRESETS:
        vals = {k: x.default for k, x in s.ALL.items()}
        vals["eq_preset"] = key
        if s.apply_to_mpv(m, vals, only=["eq_preset"]):
            bad.append(key)
    m.terminate()
    return not bad, f"{len(s.EQ_PRESETS)} presets, refused {bad}"


@check("N8 all visualizers render in libmpv")
def c_viz_engine():
    import mpv
    from ironwill.settings import VISUALIZERS
    bad = []
    for k, (_l, g) in VISUALIZERS.items():
        if not g:
            continue
        m = mpv.MPV(vo="null", ao="null", mute=True)
        m["lavfi-complex"] = f"[aid1]asplit[ao][a];{g};[v]format=yuv420p[vo]"
        m.play(str(TT / "audio_flac.flac"))
        time.sleep(1.5)
        if not m.video_params:
            bad.append(k)
        m.terminate()
    return not bad, f"{len(VISUALIZERS) - 1} styles, no picture: {bad}"


@check("N4 convert: all presets, source untouched")
def c_convert():
    from ironwill import convert
    from ironwill.dupes.fingerprint import find_tool
    src = TT / "mpeg4_mp3.avi"
    before = sha(src)
    bad = []
    for k, (_l, ext, _a) in convert.PRESETS.items():
        out = TMP / f"c_{k}{ext}"
        r = subprocess.run([find_tool("ffmpeg"), *convert.ffmpeg_args(src, out, k)], capture_output=True)
        if r.returncode or not out.exists() or out.stat().st_size == 0:
            bad.append(k)
    return not bad and sha(src) == before, f"{len(convert.PRESETS)} presets, failed {bad}, source unchanged {sha(src) == before}"


@check("N3 DVD ISO opens with chapters (your test ISO)")
def c_dvd():
    iso = TT / "IronWill DVD Test.iso"
    if not iso.exists():
        return False, "test ISO missing"
    import mpv
    m = mpv.MPV(vo="null", ao="null", mute=True)
    m["dvd-device"] = str(iso)
    m.play("dvd://")
    t0 = time.time()
    while time.time() - t0 < 15 and not m.duration:
        time.sleep(0.2)
    ch = len(m._get_property("chapter-list") or [])
    m.terminate()
    return ch >= 2, f"chapters {ch}"


@check("N5+N10 share server: discover, browse, ranged + full file match")
def c_dlna():
    from ironwill import dlna
    f = TT / "h264_aac.mp4"
    srv = dlna.Server("Iron Will (release check)")
    srv.set_files([f])
    time.sleep(1)
    found = dlna.find_servers()
    ctrl = next((c for n, c in found if "release check" in n), None)
    items = dlna.browse(ctrl) if ctrl else []
    url = items[0][2] if items else ""
    part = urllib.request.urlopen(urllib.request.Request(url, headers={"Range": "bytes=0-99"})) if url else None
    full = urllib.request.urlopen(url).read() if url else b""
    srv.stop()
    ok = ctrl and part and part.status == 206 and hashlib.sha256(full).hexdigest() == sha(f)
    return bool(ok), f"found {bool(ctrl)}, items {len(items)}, range {part and part.status}, full match {bool(full)}"


@check("N6 renderer discovery runs (no casting)")
def c_renderers():
    from ironwill import cast
    r = cast.find_renderers()
    return True, f"{len(r)} renderer(s): {[n for n, _m, _c in r]}"


@check("F3 subtitle title match: rules + live OpenSubtitles search (search only, no download)")
def c_subs():
    from ironwill import foreign_subs as fs
    rules = [fs.same_title({"feature_details": {"title": "Daredevil Drivers"}}, "daredevil") is False,
             fs.same_title({"feature_details": {"title": "Daredevil"}}, "daredevil") is True,
             fs.same_title({"feature_details": {"title": "X-Men: Apocalypse"}}, "x men apocalypse") is True,
             fs.same_title({"feature_details": {"parent_title": "Marvel's Daredevil"}}, "marvel's daredevil", 1)]
    live = fs._search(fs.APP_API_KEY, {"languages": "en", "foreign_parts_only": "only", "query": "daredevil"})
    kept = [r for r in live if fs.same_title(r.get("attributes", {}), "daredevil")]
    return all(rules) and not kept, f"rules {rules}; live 'daredevil' results {len(live)}, kept {len(kept)}"


@check("F4 burned-in detection on a made video: burned -> True, clean -> False; drop_if_burned_in deletes")
def c_burn():
    from ironwill import foreign_subs as fs
    from ironwill.dupes.fingerprint import find_tool
    ff = find_tool("ffmpeg")
    srt = TMP / "lines.srt"
    srt.write_text("".join(f"{i}\n00:00:{i*4:02d},000 --> 00:00:{i*4+2:02d},500\nWhere is it? Tell me now!\n\n"
                           for i in range(1, 12)), encoding="utf-8")
    base = TMP / "scene.mp4"
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "mandelbrot=s=1280x720:rate=0.3,fps=25", "-t", "50",
                    "-pix_fmt", "yuv420p", str(base)], check=True)
    burned = TMP / "scene_burned.mp4"
    sub_path = str(srt).replace("\\", "/").replace(":", "\\:")
    subprocess.run([ff, "-v", "error", "-y", "-i", str(base), "-vf", f"subtitles='{sub_path}'", "-pix_fmt", "yuv420p",
                    str(burned)], check=True)
    hit, miss = fs.burned_in(burned, srt), fs.burned_in(base, srt)
    copy = TMP / "scene_burned.en.forced.srt"
    copy.write_text(srt.read_text(encoding="utf-8"), encoding="utf-8")
    try:
        fs.drop_if_burned_in(burned, copy)
        dropped = False
    except fs.BurnedIn:
        dropped = not copy.exists()
    return hit and not miss and dropped, f"burned {hit}, clean {miss}, srt deleted on burned {dropped}"


@check("regression: torture test synthetic set (Iron Will)")
def c_torture():
    import torture_test as t
    files = [p for p in sorted(TT.iterdir()) if p.is_file() and p.name in t.CASES]
    res = t.iron_will(TT, files)
    bad = []
    for f in files:
        r = res[t.key(TT, f)]
        if t.CASES[f.name][0] == "play":
            if not (r["opened"] and r["seek"] is not False and r["reached_end"]):
                bad.append(f.name)
        elif r["end"] == "timeout":
            bad.append(f.name)
    return not bad, f"{len(files)} files, failed {bad}"


@check("regression: Duplicate Finder finds the clip among 17 copies + re-encodes/mirror, no false match")
def c_dupes():
    import copy as _copy
    from itertools import combinations
    from ironwill.dupes.fingerprint import fingerprint, find_tool
    from ironwill.dupes.match import find_duplicates
    ff = find_tool("ffmpeg")

    def make(name, *args):
        p = TMP / name
        subprocess.run([ff, "-v", "error", "-y", *args, "-g", "25", "-pix_fmt", "yuv420p", str(p)], check=True)
        return fingerprint(str(p))
    src = make("d_orig.mp4", "-f", "lavfi", "-i", "mandelbrot=s=640x360:rate=0.4,fps=25", "-t", "60")
    orig = str(TMP / "d_orig.mp4")
    clip = make("d_clip.mp4", "-ss", "15", "-i", orig, "-t", "20")
    small = make("d_small.mp4", "-i", orig, "-vf", "scale=320:-2", "-crf", "28")
    mirror = make("d_mirror.mp4", "-i", orig, "-vf", "hflip")
    other = make("d_other.mp4", "-f", "lavfi", "-i", "life=s=640x360:rate=25:mold=10:ratio=0.3", "-t", "40")
    fps = [_copy.copy(src) for _ in range(17)] + [clip, small, mirror, other]
    found = {frozenset((r.a, r.b)) for r in find_duplicates(fps)}
    related = range(20)
    want = {frozenset(p) for p in combinations(related, 2)}
    missing = len(want - found)
    false = [p for p in found if 20 in p]
    return not missing and not false, f"21 files, related pairs found {len(want & found)}/{len(want)}, false {len(false)}"


@check("GUI: every menu builds, About page, fullscreen in/out, Options save persists")
def c_gui_more():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from ironwill.ui.window import MainWindow
    from ironwill.ui.options import OptionsDialog
    from ironwill.ui import menus
    from ironwill.settings import Config
    w = MainWindow()
    w.engine.mpv["ao"], w.engine.mpv["vo"] = "null", "null"
    w.engine.mpv.mute = True
    w.show()
    w.open_path(TT / "h264_aac.mp4")
    pump(app, 1.5)
    count = []

    def walk(items):
        for i in items:
            count.append(i)
            walk(getattr(i, "children", None) or [])
    walk(menus.build(w))
    from ironwill.ui.widgets import dark_menu
    m = dark_menu(w)
    menus.fill_qt(m, menus.build(w), dark_menu)
    w.toggle_fullscreen()
    pump(app, 0.8)
    full = w.isFullScreen()
    w.toggle_fullscreen()
    pump(app, 0.8)
    back = not w.isFullScreen()
    saved_off = w.settings.value("subs_turned_off", [])
    w._save_tracks("sub", None)  # the user turns subtitles off for this file
    remembered = str(w.engine.path).lower() in w._subs_off_files()
    w._save_tracks("sub", 1)  # ...and back on
    forgotten = str(w.engine.path).lower() not in w._subs_off_files()
    w.settings.setValue("subs_turned_off", saved_off)
    d = OptionsDialog(w)
    about = any(getattr(pg, "special", "") == "about" for pg in __import__("ironwill.settings", fromlist=["PAGES"]).PAGES)
    old = w.cfg.values.get("dlna_name", "Iron Will")
    d.fields["dlna_name"][1]("Iron Will RC")
    d._apply()
    saved = Config()["dlna_name"]
    w.cfg.values["dlna_name"] = old
    w.cfg.save()
    d.close()
    w.engine.mpv.command("stop")
    w.close()
    return len(count) > 100 and full and back and about and saved == "Iron Will RC" and remembered and forgotten, (
        f"{len(count)} menu items built, fullscreen {full}/{back}, about page {about}, saved+reloaded {saved!r} "
        f"(restored), subs-off remembered {remembered} / cleared when turned back on {forgotten}")


@check("360: plain 2:1 widescreen movie does NOT trigger, named 360 file does")
def c_360_names():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from ironwill.ui.window import MainWindow
    from ironwill.dupes.fingerprint import find_tool
    w = MainWindow()
    w.engine.mpv["ao"], w.engine.mpv["vo"] = "null", "null"
    w.engine.mpv.mute = True
    out = {}
    for name in ("Some Movie 2160p.mp4", "Show S01E01 360p.mp4", "Holiday 360.mp4"):
        f = TMP / name
        subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=3840x1920:d=3",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(f)], check=True)
        w.open_path(f)
        pump(app, 2)
        out[name] = bool(w.view360)
    w.engine.mpv.command("stop")
    w.close()
    ok = out == {"Some Movie 2160p.mp4": False, "Show S01E01 360p.mp4": False, "Holiday 360.mp4": True}
    return ok, str(out)


def main():
    LOG.write_text(f"START {time.strftime('%Y-%m-%d %H:%M:%S')}\n", encoding="utf-8")
    for fn in (c_compile, c_version, c_kinds):
        fn()
    gui_checks()
    for fn in (c_eq, c_viz_engine, c_convert, c_dvd, c_dlna, c_renderers, c_subs, c_burn, c_torture, c_dupes,
               c_gui_more, c_360_names):
        fn()
    passed = sum(ok for _n, ok in results)
    emit(f"SUMMARY {passed}/{len(results)} passed; failed: {[n for n, ok in results if not ok]}")
    emit("ALL DONE")


if __name__ == "__main__":
    main()
