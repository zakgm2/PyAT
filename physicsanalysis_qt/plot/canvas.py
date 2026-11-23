"""
plot/canvas.py
--------------
The matplotlib plot's Qt canvas. matplotlib's own repaint turns the buffer into another pixel format, in numpy, at every paint — milliseconds on a big or high-DPI
canvas, a quarter of the time of a drag frame. Here the buffer is handed to Qt as it is.

Nothing else is changed: what is painted is what matplotlib drew (a test compares them), and a drag draws the plot properly at every frame it can (plot/interaction.py).
"""

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QImage, QPainter


class PictureCanvas(FigureCanvasQTAgg):
    def paintEvent(self, event):
        draw_pending = getattr(self, "_draw_idle", None)
        if draw_pending is not None:
            draw_pending()                                    # (a draw that was asked for and has not been done yet: matplotlib does it first too)
        buf = np.asarray(self.buffer_rgba()) if hasattr(self, "renderer") else None
        ratio = self.device_pixel_ratio
        if buf is None or buf.shape[:2] != (round(self.height() * ratio), round(self.width() * ratio)) or not buf.flags.c_contiguous:
            return super().paintEvent(event)                  # (nothing drawn yet, or the buffer is not of this size yet: as matplotlib does it)
        height, width = buf.shape[:2]
        image = QImage(buf.data, width, height, 4 * width, QImage.Format.Format_RGBX8888)
        image.setDevicePixelRatio(ratio)
        painter = QPainter(self)
        rect = event.rect()
        source = QRect(round(rect.x() * ratio), round(rect.y() * ratio), round(rect.width() * ratio), round(rect.height() * ratio))
        painter.drawImage(rect, image, source)
        painter.end()
