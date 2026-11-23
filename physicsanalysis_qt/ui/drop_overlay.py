"""
ui/drop_overlay.py
------------------
What the window shows so that opening a file by dropping it can be found (loading/drop.py is the part that opens it):

  * with nothing loaded, a quiet card in the middle of the plot area: "Drag a file or folder here to open it" and what can be dropped;
  * while a drag carrying files is over the window, the plot area is veiled and framed with a dashed border and says what dropping would
    open, or, in red, that the file cannot be opened.

One widget covers the plot area and lets every mouse and drag event through to what is under it (the plots stay usable, and the drop still
reaches the event filter in loading/drop.py). It reads its colours from the palette, so it follows the light and dark themes.
"""

from PyQt6.QtCore import QEvent, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPalette, QPen, QPolygonF
from PyQt6.QtWidgets import QWidget

REFUSED = QColor(200, 60, 60)                         # a file that cannot be opened: red reads the same on both themes


class DropOverlay(QWidget):
    def __init__(self, ctx, parent):
        super().__init__(parent)
        self.ctx = ctx
        self.hint = ("Drag a file or folder here to open it", "")        # (title, detail) of the card shown while nothing is loaded
        self._drag = None                                                 # None, or (ok, title, detail) while a drag is over the window
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        parent.installEventFilter(self)                                   # keeps it covering the plot area when that is resized
        parent.currentChanged.connect(lambda _index: self.raise_())       # showing the other plot engine (Options) raises that above this
        self.hide()

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:        # also while it is waiting for the window to be shown
            self.setGeometry(self.parentWidget().rect())
        return False

    # What is shown

    @property
    def dragging(self):
        return self._drag is not None

    def begin_drag(self, ok, title, detail):
        self._drag = (ok, title, detail)
        self.refresh()

    def end_drag(self):
        self._drag = None
        self.refresh()

    def refresh(self):
        """Shown while a drag is over the window, and while nothing is loaded; hidden otherwise."""
        if self._drag is None and self.ctx.cache is not None:
            self.hide()
            return
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.update()

    # Painting

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        area = QRectF(self.rect())
        if self._drag is not None:
            self._paint_drag(painter, palette, area, *self._drag)
        else:
            self._paint_hint(painter, palette, area, *self.hint)

    def _paint_drag(self, painter, palette, area, ok, title, detail):
        accent = palette.color(QPalette.ColorRole.Highlight) if ok else REFUSED
        if palette.color(QPalette.ColorRole.Window).lightness() < 128:               # on the dark theme the accent is brightened to stay readable
            accent = accent.lighter(150)
        veil = QColor(palette.color(QPalette.ColorRole.Window))
        veil.setAlpha(228)
        painter.fillRect(area, veil)
        tint = QColor(accent)
        tint.setAlpha(34)
        painter.fillRect(area, tint)
        frame = area.adjusted(14, 14, -14, -14)
        painter.setPen(QPen(accent, 3, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(frame, 16, 16)
        self._paint_message(painter, frame, ok, title, detail, accent, palette.color(QPalette.ColorRole.WindowText), scale=1.0)

    def _paint_hint(self, painter, palette, area, title, detail):
        text = palette.color(QPalette.ColorRole.WindowText)
        muted = QColor(text)
        muted.setAlpha(170)
        width = min(600.0, area.width() - 40.0)
        if width < 220.0:                                 # a window this narrow has no room for it
            return
        height = self._message_height(width - 40.0, title, detail, scale=0.95) + 40.0
        card = QRectF(area.center().x() - width / 2, area.center().y() - height / 2, width, height)
        fill = QColor(palette.color(QPalette.ColorRole.Base))
        fill.setAlpha(238)
        painter.setPen(QPen(palette.color(QPalette.ColorRole.Mid), 1.5, Qt.PenStyle.DashLine))
        painter.setBrush(fill)
        painter.drawRoundedRect(card, 14, 14)
        self._paint_message(painter, card.adjusted(20, 20, -20, -20), True, title, detail, muted, muted, scale=0.95)

    # The icon, the title and the detail, stacked and centred in `box`. `scale` shrinks all three together.

    def _fonts(self, scale):
        base = self.font().pointSizeF()
        if base <= 0:                                     # a font given in pixels
            base = 10.0
        title, detail = QFont(self.font()), QFont(self.font())
        title.setPointSizeF(base * 1.7 * scale)
        title.setBold(True)
        detail.setPointSizeF(base * 1.05 * scale)
        return title, detail

    def _message_height(self, width, title, detail, scale):
        title_font, detail_font = self._fonts(scale)
        flags = Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap
        height = 64.0 * scale + 10.0 + QFontMetricsF(title_font).boundingRect(QRectF(0, 0, width, 10000), flags, title).height()
        if detail:
            height += 8.0 + QFontMetricsF(detail_font).boundingRect(QRectF(0, 0, width, 10000), flags, detail).height()
        return height

    def _paint_message(self, painter, box, ok, title, detail, accent, text, scale):
        title_font, detail_font = self._fonts(scale)
        flags = Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap
        width = box.width() - 40.0
        icon = 64.0 * scale
        title_h = QFontMetricsF(title_font).boundingRect(QRectF(0, 0, width, 10000), flags, title).height()
        detail_h = QFontMetricsF(detail_font).boundingRect(QRectF(0, 0, width, 10000), flags, detail).height() if detail else 0.0
        total = icon + 10.0 + title_h + (8.0 + detail_h if detail else 0.0)
        top = box.center().y() - total / 2
        left = box.left() + 20.0
        _draw_icon(painter, QPointF(box.center().x(), top + icon / 2), icon, ok, accent)
        top += icon + 10.0
        painter.setFont(title_font)
        painter.setPen(accent)
        painter.drawText(QRectF(left, top, width, title_h), flags, title)
        if detail:
            painter.setFont(detail_font)
            painter.setPen(text)
            painter.drawText(QRectF(left, top + title_h + 8.0, width, detail_h), flags, detail)


def _draw_icon(painter, centre, size, ok, colour):
    """A tray with an arrow going into it (something to drop), or a cross when what is dragged cannot be opened."""
    painter.setPen(QPen(colour, max(2.0, size / 13.0), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    x, y, s = centre.x(), centre.y() - size / 2, size
    if ok:
        painter.drawLine(QPointF(x, y + 0.02 * s), QPointF(x, y + 0.62 * s))
        painter.drawPolyline(QPolygonF([QPointF(x - 0.20 * s, y + 0.42 * s), QPointF(x, y + 0.62 * s), QPointF(x + 0.20 * s, y + 0.42 * s)]))
        painter.drawPolyline(QPolygonF([QPointF(x - 0.40 * s, y + 0.62 * s), QPointF(x - 0.40 * s, y + 0.92 * s),
                                        QPointF(x + 0.40 * s, y + 0.92 * s), QPointF(x + 0.40 * s, y + 0.62 * s)]))
    else:
        painter.drawLine(QPointF(x - 0.30 * s, y + 0.20 * s), QPointF(x + 0.30 * s, y + 0.80 * s))
        painter.drawLine(QPointF(x + 0.30 * s, y + 0.20 * s), QPointF(x - 0.30 * s, y + 0.80 * s))


def refresh(ctx):
    """Called when a recording has been loaded: the card for the empty window goes away. (Nothing to do before the window has been built.)"""
    overlay = getattr(ctx, "drop_overlay", None)
    if overlay is not None:
        overlay.refresh()
