"""Draw the application icon and write packaging/icon.ico.

Run when the mark changes:

    python packaging/make_icon.py

The result is committed, so a normal build does not need to run this and the
exe build has no extra step.

The mark is an aperture ring with a single bright star off-centre, in the
app's amber on its own near-black. It has to survive being 16 pixels wide in
a taskbar, so it is one ring, one dot and nothing else -- anything with more
detail turns to mush at that size, which is the usual way an app ends up with
an icon that reads as a smudge.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QApplication

# Straight from the app's own palette, so the icon and the window agree.
GROUND = "#12161F"
ACCENT = "#E8A33D"
STAR = "#FFF4E2"

# Sizes Windows actually asks for, smallest first.
SIZES = [16, 20, 24, 32, 48, 64, 128, 256]


def draw(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Rounded tile, so it reads as an application rather than a stray glyph.
    radius = size * 0.22
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(GROUND))
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    # The aperture: a ring, weighted so it stays visible when tiny.
    inset = size * 0.22
    ring = QRectF(inset, inset, size - inset * 2, size - inset * 2)
    width = max(1.0, size * 0.085)
    pen = QPen(QColor(ACCENT), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(ring)

    # One star inside it. At 16px this is a couple of pixels, which is the
    # point: it reads as "something in the aperture" rather than as detail.
    centre = QPointF(size * 0.60, size * 0.42)
    glow = size * 0.13
    gradient = QRadialGradient(centre, glow)
    gradient.setColorAt(0.0, QColor(STAR))
    gradient.setColorAt(0.45, QColor(255, 244, 226, 210))
    gradient.setColorAt(1.0, QColor(255, 244, 226, 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawEllipse(centre, glow, glow)

    painter.end()
    return image


def _png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def write_ico(images: list[QImage], target: Path) -> None:
    """Assemble a multi-size .ico by hand.

    Qt's ICO writer only puts ONE frame in a file, so Windows would be left
    scaling a single size to every other -- which is exactly how an icon ends
    up looking soft in the taskbar. The container itself is trivial: a short
    directory followed by the frames, and since Vista each frame may simply
    be a PNG.
    """
    frames = [_png_bytes(image) for image in images]

    # ICONDIR: reserved, type 1 (icon), image count.
    header = struct.pack("<HHH", 0, 1, len(frames))
    # Each ICONDIRENTRY is 16 bytes, and they all precede the image data.
    offset = len(header) + 16 * len(frames)

    directory = b""
    for image, data in zip(images, frames):
        # 0 means 256 in this field, which is why 256 is the largest size.
        width = 0 if image.width() >= 256 else image.width()
        height = 0 if image.height() >= 256 else image.height()
        directory += struct.pack(
            "<BBBBHHII", width, height, 0, 0, 1, 32, len(data), offset
        )
        offset += len(data)

    target.write_bytes(header + directory + b"".join(frames))


def main() -> int:
    app = QApplication(sys.argv)  # noqa: F841 - needed for QImage/QPainter
    target = Path(__file__).resolve().parent / "icon.ico"

    write_ico([draw(size) for size in SIZES], target)
    print(
        f"wrote {target} ({target.stat().st_size / 1024:.1f} KB, "
        f"{len(SIZES)} sizes: {', '.join(str(s) for s in SIZES)})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
