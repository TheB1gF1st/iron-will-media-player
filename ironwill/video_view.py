"""MpvVideoWidget: mpv draws each frame into this OpenGL widget (libmpv render API) instead of owning its
own native window. That is what lets the Qt controls float over the video with real transparency."""
import ctypes

from PySide6.QtCore import Signal
from PySide6.QtGui import QOpenGLContext
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from .engine import mpv


class MpvVideoWidget(QOpenGLWidget):
    frame_ready = Signal()
    ready = Signal()  # emitted once mpv can draw here: open files only after this, or mpv disables video

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self.ctx = None
        self._get_proc = mpv.MpvGlGetProcAddressFn(self._proc_address)
        # mpv calls update_cb from its render thread; hop to the GUI thread before repainting.
        self.frame_ready.connect(self.update)
        self.setMouseTracking(True)

    @staticmethod
    def _proc_address(_ctx, name):
        gl = QOpenGLContext.currentContext()
        return int(gl.getProcAddress(name)) if gl else 0

    def initializeGL(self):
        self.context().aboutToBeDestroyed.connect(self._free)
        self.ctx = mpv.MpvRenderContext(
            self.engine.mpv, "opengl", opengl_init_params={"get_proc_address": self._get_proc})
        self.ctx.update_cb = self.frame_ready.emit
        self.ready.emit()

    def paintGL(self):
        ratio = self.devicePixelRatioF()
        w, h = int(self.width() * ratio), int(self.height() * ratio)
        if not self.engine.path:
            f = self.context().functions()
            f.glClearColor(0.0, 0.0, 0.0, 1.0)
            f.glClear(0x4000)  # GL_COLOR_BUFFER_BIT
            return
        if self.ctx:
            self.ctx.render(flip_y=True, opengl_fbo={"w": w, "h": h, "fbo": self.defaultFramebufferObject()})

    def _free(self):
        if self.ctx:
            self.makeCurrent()
            self.ctx.free()
            self.ctx = None
            self.doneCurrent()

    def shutdown(self):
        self._free()
