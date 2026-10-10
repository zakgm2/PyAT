"""
app/window_fit.py
-----------------
Keeps windows usable on small screens. Two independent problems, two tools:

  fit_to_screen(widget, w, h)
      For windows with a fixed preferred size (plot pop-ups, tables, the
      main window): a plain resize(w, h) ignores the display entirely, so
      on a 1366x768 laptop a 650-850px-tall window spilled off the bottom.
      This clamps the initial size to the screen the window is on.

  scroll_body(dialog) + fit_dialog_to_content(dialog, body)
      For form-style dialogs whose *content* decides how tall they are
      (Options, Edit Attributes — one row per legend entry, Add Marker,
      Compare Fields). Their stacked layouts refuse to shrink below their
      own content height, so on a short screen the dialog outgrew the
      display and pushed its OK/Apply buttons off-screen. The fix is
      structural: the form goes in a scroll area, the action buttons stay
      pinned outside it, and the initial size is capped to the screen.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QFrame, QScrollArea, QStyle, QVBoxLayout, QWidget,
)

_MAX_WIDTH_FRAC = 0.9
_MAX_HEIGHT_FRAC = 0.85


def _available(widget):
    screen = widget.screen() or QApplication.primaryScreen()
    return screen.availableGeometry()


def fit_to_screen(widget, width, height,
                  max_width_frac=_MAX_WIDTH_FRAC, max_height_frac=_MAX_HEIGHT_FRAC):
    """resize(width, height), but never wider/taller than max_*_frac of the
    screen's usable area (i.e. excluding the taskbar). A no-op on any
    screen big enough for the preferred size."""
    avail = _available(widget)
    widget.resize(min(width, int(avail.width() * max_width_frac)),
                  min(height, int(avail.height() * max_height_frac)))


def scroll_body(dialog):
    """Sets up `dialog` as scroll area (the form) + pinned area below it
    (the buttons), and gives it a maximize button and a resize grip — a
    plain QDialog gets neither.

    Returns (outer, layout, body):
      layout -- add the form's widgets/group boxes here (scrolls)
      outer  -- add the OK/Apply/Cancel row here (stays pinned, always visible)
      body   -- pass to fit_dialog_to_content() once everything's added
    """
    dialog.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
    dialog.setSizeGripEnabled(True)

    outer = QVBoxLayout(dialog)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    body = QWidget()
    layout = QVBoxLayout(body)
    scroll.setWidget(body)
    outer.addWidget(scroll, stretch=1)
    return outer, layout, body


def fit_dialog_to_content(dialog, body, min_width=0):
    """Initial size for a scroll_body() dialog: whatever the content
    actually needs, capped to the screen (the scroll area takes over
    beyond that). Call once, after the form is fully built.

    Width is at least min_width, or the content's own minimum width if
    larger — inside a scroll area a too-narrow dialog gets a horizontal
    scrollbar instead of widening itself the way a plain layout would.
    Height uses the *wrapped* height at that width: word-wrapped notes get
    taller as the width shrinks, which sizeHint() alone ignores."""
    lay = body.layout()
    lay.addStretch(1)  # spare height goes here, not into stretched group boxes

    avail = _available(dialog)
    scrollbar_w = dialog.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
    chrome_w = scrollbar_w + 40  # scrollbar + dialog/frame margins

    width = min(max(min_width, body.minimumSizeHint().width() + chrome_w),
                int(avail.width() * _MAX_WIDTH_FRAC))
    content_w = width - chrome_w
    content_h = (lay.totalHeightForWidth(content_w) if lay.hasHeightForWidth()
                 else body.sizeHint().height())
    height = min(content_h + 80, int(avail.height() * _MAX_HEIGHT_FRAC))  # +80: button row, margins
    dialog.resize(width, height)
