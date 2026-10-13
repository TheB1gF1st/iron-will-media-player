"""PlayerEngine: the model/view-model layer. Owns the mpv instance and turns its property changes into
Qt signals, so the UI never talks to mpv directly and never touches it from mpv's own threads."""
import os
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import mpv_loader

mpv = mpv_loader.load()

DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "IronWillMediaPlayer"


class PlayerEngine(QObject):
    position_changed = Signal(float)
    duration_changed = Signal(float)
    pause_changed = Signal(bool)
    volume_changed = Signal(float)
    mute_changed = Signal(bool)
    title_changed = Signal(str)
    file_loaded = Signal(str)
    end_reached = Signal()
    tracks_changed = Signal(list)
    speed_changed = Signal(float)
    track_picked = Signal(str, object)  # kind, id (None = off): only for choices the user made
    def __init__(self, parent=None):
        super().__init__(parent)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.path = ""
        self.mpv = mpv.MPV(
            vo="libmpv",
            hwdec="auto-safe",
            keep_open="yes",
            osc=False,
            input_default_bindings=False,
            input_vo_keyboard=False,
            ytdl=False,
            resume_playback=False,  # Iron Will asks before resuming (see resume.py)
            volume_max=150,
        )
        observers = {
            "time-pos": lambda v: self.position_changed.emit(float(v or 0)),
            "duration": lambda v: self.duration_changed.emit(float(v or 0)),
            "pause": lambda v: self.pause_changed.emit(bool(v)),
            "volume": lambda v: self.volume_changed.emit(float(v or 0)),
            "mute": lambda v: self.mute_changed.emit(bool(v)),
            "media-title": lambda v: self.title_changed.emit(v or ""),
            "eof-reached": lambda v: v and self.end_reached.emit(),
            "track-list": lambda v: self.tracks_changed.emit(list(v or [])),
            "speed": lambda v: self.speed_changed.emit(float(v or 1.0)),        }
        for name, fn in observers.items():
            self.mpv.observe_property(name, lambda _n, v, fn=fn: fn(v))

        self._want_pause = False

        @self.mpv.event_callback("file-loaded")
        def _loaded(_event):
            # keep-open pauses mpv when a file ends; re-apply the wanted state once the new file is in,
            # or the next file in the folder would load paused
            self.mpv.pause = self._want_pause
            self.file_loaded.emit(self.path)

    # Playback ----------------------------------------------------------------------------------------
    def open(self, path, start=None, paused=False):
        self.path = str(path)
        self._want_pause = paused
        self.mpv.pause = paused
        for marker in ("ab-loop-a", "ab-loop-b"):  # A-B loops belong to one file, not the next
            self.mpv[marker] = "no"
        if start:
            self.mpv.loadfile(self.path, start=f"{start:.2f}")
        else:
            self.mpv.loadfile(self.path)

    def toggle_pause(self):
        if self.path:
            if self.mpv.eof_reached:
                self.mpv.seek(0, "absolute")
            self.mpv.pause = not self.mpv.pause

    def seek(self, seconds, exact=True):
        if self.path:
            self.mpv.seek(seconds, "absolute+exact" if exact else "absolute+keyframes")

    def skip(self, seconds):
        if self.path:
            self.mpv.seek(seconds, "relative+exact")

    def frame_step(self, forward=True):
        if self.path:
            self.mpv.command("frame-step" if forward else "frame-back-step")

    # Audio -------------------------------------------------------------------------------------------
    @property
    def volume(self):
        return float(self.mpv.volume or 0)

    def set_volume(self, value):
        self.mpv.volume = max(0, min(150, value))
        if value > 0 and self.mpv.mute:
            self.mpv.mute = False

    def toggle_mute(self):
        self.mpv.mute = not self.mpv.mute

    # Tracks and video --------------------------------------------------------------------------------
    def tracks(self, kind):
        return [t for t in (self.mpv.track_list or []) if t.get("type") == kind]

    def select_track(self, kind, track_id, remember=True):
        prop = {"sub": "sid", "audio": "aid", "video": "vid"}[kind]
        setattr(self.mpv, prop, track_id if track_id is not None else "no")
        if remember:
            self.track_picked.emit(kind, track_id)

    def set_speed(self, speed):
        self.mpv.speed = speed

    def set_aspect(self, aspect):
        self.mpv["video-aspect-override"] = aspect

    def screenshot(self, folder, with_subs=False):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        self.mpv["screenshot-directory"] = str(folder)
        self.mpv.command("screenshot", "subtitles" if with_subs else "video")
        return folder

    def shutdown(self):
        self.mpv.terminate()
