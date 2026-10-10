"""Builds the app icon: the "I will" brush script filled with a red-to-black gradient (left to right) over a
line-drawn play button stroked with a white-to-gunmetal gradient (top to bottom, perpendicular to the script's).

    E:\\PythonMedia\\python.exe tools\\make_icon.py

Writes ironwill/assets/icon-1024.png and ironwill/assets/iron-will.ico (16-256 px)."""
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen)

ASSETS = Path(__file__).resolve().parent.parent / "ironwill" / "assets"
SIZE = 1024
RED, BLACK = QColor("#E81123"), QColor("#0B0B0C")
WHITE, GUNMETAL = QColor("#FFFFFF"), QColor("#2C3539")
EDGE = QColor("#3C4248")  # thin gunmetal edge so the black end of the script still shows on dark desktops


def play_path(rect):
    """Right-pointing triangle with softly rounded corners."""
    l, t, r, b = rect.left(), rect.top(), rect.right(), rect.bottom()
    pts = [QPointF(l, t), QPointF(r, (t + b) / 2), QPointF(l, b)]
    radius = rect.width() * 0.09
    path = QPainterPath()
    for i, p in enumerate(pts):
        prev, nxt = pts[i - 1], pts[(i + 1) % 3]

        def toward(a, z, d):
            v = z - a
            length = (v.x() ** 2 + v.y() ** 2) ** 0.5
            return a + v * (d / length)

        a, z = toward(p, prev, radius), toward(p, nxt, radius)
        path.moveTo(a) if i == 0 else path.lineTo(a)
        path.quadTo(p, z)
    path.closeSubpath()
    return path


def draw_play(p, size, stroke):
    box = QRectF(size * 0.28, size * 0.08, size * 0.58, size * 0.74)
    grad = QLinearGradient(0, box.top(), 0, box.bottom())  # vertical
    grad.setColorAt(0.0, WHITE)
    grad.setColorAt(1.0, GUNMETAL)
    pen = QPen(grad, stroke)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(play_path(box))


def script_layer(size):
    logo = QImage(str(ASSETS / "i-will.png")).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    w = int(size * 0.94)
    logo = logo.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation)
    x, y = (size - w) // 2, int(size * 0.45 - logo.height() / 2)  # centered on the play button
    # Full-canvas mask: DestinationIn only clears pixels the source covers, so the mask must span everything.
    mask = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    mask.fill(Qt.GlobalColor.transparent)
    mq = QPainter(mask)
    mq.drawImage(x, y, logo)
    mq.end()

    def filled(colorize):
        img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        q = QPainter(img)
        q.setRenderHint(QPainter.RenderHint.Antialiasing)
        colorize(q)
        q.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        q.drawImage(0, 0, mask)
        q.end()
        return img

    def gradient(q):
        g = QLinearGradient(x, 0, x + w, 0)  # horizontal: red on the left fading to black on the right
        g.setColorAt(0.0, RED)
        g.setColorAt(0.55, QColor("#8E0A15"))
        g.setColorAt(1.0, BLACK)
        q.fillRect(0, 0, size, size, g)

    body = filled(gradient)
    edge = filled(lambda q: q.fillRect(0, 0, size, size, EDGE))
    out = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    q = QPainter(out)
    r = max(1, size // 256)  # edge thickness: stamp the solid copy in a small ring (cheap dilation)
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            if dx * dx + dy * dy <= r * r:
                q.drawImage(dx, dy, edge)
    q.drawImage(0, 0, body)
    q.end()
    return out


def render(size, with_script=True):
    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    # Small sizes can't carry the script legibly, so they get a bolder play button alone.
    draw_play(p, size, size * (0.045 if with_script else 0.11))
    if with_script:
        p.drawImage(0, 0, script_layer(size))
    p.end()
    return img


def png_bytes(img):
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def write_ico(path, images):
    entries, blobs = [], []
    offset = 6 + 16 * len(images)
    for img in images:
        data = png_bytes(img)
        s = img.width()
        entries.append(struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset))
        blobs.append(data)
        offset += len(data)
    path.write_bytes(struct.pack("<HHH", 0, 1, len(images)) + b"".join(entries) + b"".join(blobs))


def main():
    QGuiApplication(sys.argv)
    big = render(SIZE)
    big.save(str(ASSETS / "icon-1024.png"))
    sizes = []
    for s in (16, 24, 32, 48, 64, 128, 256):
        if s <= 32:
            sizes.append(render(s * 4, with_script=False).scaled(s, s, Qt.AspectRatioMode.KeepAspectRatio,
                                                                 Qt.TransformationMode.SmoothTransformation))
        else:
            sizes.append(big.scaled(s, s, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    write_ico(ASSETS / "iron-will.ico", sizes)
    print("wrote", ASSETS / "iron-will.ico", "and icon-1024.png")


if __name__ == "__main__":
    main()
