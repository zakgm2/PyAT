"""
toasts.py
---------
Small on-screen notifications: a self-dismissing toast widget in the
window's bottom-RIGHT corner, plus thin wrappers around QMessageBox for
errors/success dialogs.

Only ONE toast is ever on screen — a new one replaces whatever is showing
(and cancels its dismiss timer) instead of piling up on top of it.

The pinned panel (show_pinned_panel) is separate: a message and a button in
the bottom-LEFT corner that stays until hide_pinned_panel(). Toasts never
replace or hide it, and it never times out. The Analysis picker uses it to
keep a "Done" button on screen for as long as an analysis tool is armed.

ProgressToast is the toast for a slow action: it stays up while the action
runs and shows a live percentage (see its docstring, and background.py for
how actions get one).
"""

import time

from PyQt6.QtCore import Qt, QTimer, QObject, QEvent, QEventLoop
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox, QProgressBar,
)

_MARGIN_RIGHT = 30
_MARGIN_LEFT = 76    # clears the Tools sidebar down the window's left edge
_MARGIN_BOTTOM = 60  # clears the status bar

_PROGRESS_DELAY_MS = 300   # an action faster than this never gets a toast, so quick ones don't flash one
_PROGRESS_WIDTH = 300
_PUMP_INTERVAL_S = 0.04    # at most ~25 repaints a second while the GUI thread itself is busy
_STALL_S = 1.2             # no change for this long: the step is one long call, so show it is still alive
_STALL_TICK_MS = 400       # ...by cycling the dots after its description


class _Repositioner(QObject):
    """Keeps the toast and the pinned panel in their corners across window
    resizes (the panel can outlive many of them)."""

    def __init__(self, ctx):
        super().__init__(ctx.win)
        self._ctx = ctx

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            _place_toast(self._ctx)
            _place_panel(self._ctx)
        return False


def _ensure_repositioner(ctx):
    if ctx._toast_repositioner is None:
        ctx._toast_repositioner = _Repositioner(ctx)
        ctx.win.installEventFilter(ctx._toast_repositioner)


def _place_toast(ctx):
    toast = ctx._toast
    if toast is None:
        return
    toast.adjustSize()
    toast.move(ctx.win.width() - toast.width() - _MARGIN_RIGHT,
               ctx.win.height() - toast.height() - _MARGIN_BOTTOM)
    toast.raise_()


def _place_panel(ctx):
    panel = ctx._pinned_panel
    if panel is None:
        return
    panel.adjustSize()
    panel.move(_MARGIN_LEFT, ctx.win.height() - panel.height() - _MARGIN_BOTTOM)
    panel.raise_()


def _close_toast(ctx):
    """Dismiss the toast that's showing, and its pending timer."""
    if ctx._toast_timer is not None:
        ctx._toast_timer.stop()
        ctx._toast_timer = None
    if ctx._toast is not None:
        ctx._toast.hide()
        ctx._toast.deleteLater()
        ctx._toast = None


def show_window_toast(ctx, message, duration=2500):
    _close_toast(ctx)  # one at a time: a new toast replaces the current one
    # A plain child widget (no top-level window flags) so it's positioned
    # in the window's own coordinate space and moves/stacks with it,
    # instead of a separate top-level window pinned to a screen position.
    toast = QWidget(ctx.win)
    toast.setObjectName("windowToast")
    # Purely informational, so clicks pass straight through to the plot.
    toast.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    toast.setStyleSheet(
        "background-color: #333; border-radius: 6px; padding: 8px;"
    )
    layout = QVBoxLayout(toast)
    label = QLabel(message)
    label.setStyleSheet("color: white; font-weight: bold;")
    layout.addWidget(label)

    _ensure_repositioner(ctx)
    ctx._toast = toast
    _place_toast(ctx)
    toast.show()
    toast.raise_()

    timer = QTimer(toast)  # child of the toast, so it can never outlive it
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: _close_toast(ctx) if ctx._toast is toast else None)
    ctx._toast_timer = timer
    timer.start(duration)


def show_pinned_panel(ctx, message, button_text, on_click):
    """Pin a message + button in the window's bottom-left corner until
    hide_pinned_panel(). Replaces an earlier pinned panel; toasts don't
    affect it."""
    hide_pinned_panel(ctx)
    panel = QWidget(ctx.win)
    panel.setObjectName("pinnedPanel")
    panel.setStyleSheet("#pinnedPanel { background-color: #333; border-radius: 6px; padding: 8px; }")
    layout = QVBoxLayout(panel)
    label = QLabel(message)
    label.setStyleSheet("color: white; font-weight: bold;")
    layout.addWidget(label)
    button = QPushButton(button_text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setStyleSheet(
        "QPushButton { background-color: #FFD54F; color: black; font-weight: bold; "
        "border: none; border-radius: 4px; padding: 5px 16px; }"
        "QPushButton:hover { background-color: #FFE082; }")
    button.clicked.connect(on_click)
    layout.addWidget(button)  # bottom of the panel

    _ensure_repositioner(ctx)
    ctx._pinned_panel = panel
    _place_panel(ctx)
    panel.show()
    panel.raise_()


def hide_pinned_panel(ctx):
    if ctx._pinned_panel is not None:
        ctx._pinned_panel.hide()
        ctx._pinned_panel.deleteLater()
        ctx._pinned_panel = None


class ProgressToast(QObject):
    """A toast for a slow action: its name, a live percentage, what it is doing
    right now, and a thin bar. It stays up until finish().

        Loading TDT folder                      62%
        Fitting photobleaching baseline…
        ▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬░░░░░░░░░

    - It only appears if the action is still running after a short delay, so
      quick actions never flash one.
    - Like every toast it shares the one slot: when it first appears it replaces
      whatever toast is up, a newer toast replaces it in turn, and it takes the slot
      back on its next update once that toast has gone. finish() closes this toast
      only, never somebody else's (a "Cut out ..." result toast shown by the action
      itself, say).
    - update(fraction, message) is a slot: connect a worker thread's signal to
      it and Qt runs it on the GUI thread. With pump=True (the work is running ON
      the GUI thread) each update also lets Qt repaint, without handling clicks or
      keys, so the toast keeps moving while the window is busy.
    """

    def __init__(self, ctx, label, pump=False, delay_ms=_PROGRESS_DELAY_MS):
        super().__init__(ctx.win)
        self._ctx = ctx
        self._label = label
        self._pump = pump
        self._delay_s = delay_ms / 1000.0
        self._t0 = time.monotonic()
        self._last_pump = 0.0
        self._fraction = 0.0
        self._message = ""
        self._done = False
        self._shown_once = False
        self._widget = None                                   # our toast, while it is on screen
        self._timer = QTimer(self)                            # shows it after the delay even if no update arrives
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._show_if_due)
        # Some steps are a single long call that can't report from inside (the photobleaching
        # fit is most of a TDT load). Rather than fake a moving percentage, the toast shows it
        # is alive by cycling the dots after the step's description once nothing has changed
        # for a while. (Needs the event loop, so it only runs for work on a worker thread.)
        self._last_change = time.monotonic()
        self._stall_ticks = 0
        self._stall_timer = QTimer(self)
        self._stall_timer.setInterval(_STALL_TICK_MS)
        self._stall_timer.timeout.connect(self._on_stall_tick)

    # -- lifecycle -----------------------------------------------------------------------------
    def start(self):
        self._t0 = time.monotonic()
        self._last_change = self._t0
        self._timer.start()
        self._stall_timer.start()

    def update(self, fraction, message=""):
        if self._done:                                        # late signals after finish() are ignored
            return
        fraction = max(self._fraction, min(1.0, float(fraction)))
        if fraction != self._fraction or (message and message != self._message):
            self._last_change = time.monotonic()
            self._stall_ticks = 0
        self._fraction = fraction
        if message:
            self._message = message
        self._show_if_due()
        # Once the action has run long enough to deserve a toast, let Qt paint and run timers
        # between reports (an older toast's dismiss timer included, so we can get the slot back).
        if self._pump and time.monotonic() - self._t0 >= self._delay_s:
            now = time.monotonic()
            if now - self._last_pump >= _PUMP_INTERVAL_S:
                self._last_pump = now
                QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def finish(self, *_):
        """Close our toast (if it is still the one showing) and stop; accepts and ignores any
        signal arguments so it can be connected straight to a worker's finished/failed."""
        if self._done:
            return
        self._done = True
        self._timer.stop()
        self._stall_timer.stop()
        ctx = self._ctx
        if self._widget is not None and ctx._toast is self._widget:
            _close_toast(ctx)
        self._widget = None
        if getattr(ctx, "_progress_toast", None) is self:
            ctx._progress_toast = None
        self.deleteLater()

    # -- what is on screen ---------------------------------------------------------------------
    def _show_if_due(self):
        if self._done:
            return
        ctx = self._ctx
        if self._widget is not None and ctx._toast is not self._widget:
            self._widget = None                               # replaced by another toast (Qt deleted ours)
        if self._widget is None:
            if time.monotonic() - self._t0 < self._delay_s:
                return                                        # not worth showing yet
            if ctx._toast is not None:
                if self._shown_once:
                    return                                    # a newer toast replaced ours: wait for it to go
                _close_toast(ctx)                             # first appearance: like any new toast, replace what's up
            self._widget = self._build()
            self._shown_once = True
            ctx._toast = self._widget
            _ensure_repositioner(ctx)
            self._render()
            _place_toast(ctx)
            self._widget.show()
            self._widget.raise_()
            return
        self._render()

    def _build(self):
        toast = QWidget(self._ctx.win)
        toast.setObjectName("progressToast")
        toast.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)   # informational: clicks pass through
        toast.setFixedWidth(_PROGRESS_WIDTH)
        toast.setStyleSheet(
            "#progressToast { background-color: #333; border-radius: 6px; }"
            "#progressToast QLabel { background: transparent; color: white; }"
            "#progressToast QProgressBar { background-color: #555; border: none; border-radius: 2px; }"
            "#progressToast QProgressBar::chunk { background-color: #FFD54F; border-radius: 2px; }"
        )
        layout = QVBoxLayout(toast)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(5)

        top = QHBoxLayout()
        self._title = QLabel(self._label)
        self._title.setStyleSheet("font-weight: bold;")
        self._percent = QLabel("0%")
        self._percent.setStyleSheet("font-weight: bold;")
        self._percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self._title, stretch=1)
        top.addWidget(self._percent)
        layout.addLayout(top)

        self._detail = QLabel("")
        self._detail.setWordWrap(True)
        self._detail.setStyleSheet("color: #cfcfcf; font-size: 11px;")
        layout.addWidget(self._detail)

        self._bar = QProgressBar()
        self._bar.setRange(0, 1000)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(5)
        layout.addWidget(self._bar)
        return toast

    def _on_stall_tick(self):
        if self._done or self._widget is None:
            return
        if time.monotonic() - self._last_change >= _STALL_S:
            self._stall_ticks += 1
            self._show_if_due()

    def _render(self):
        # Floor, not round: 100% is only ever shown once the action has really finished.
        self._percent.setText(f"{int(self._fraction * 100)}%")
        message = self._message.rstrip("…. ")
        if self._stall_ticks:
            tail = "." * (1 + (self._stall_ticks - 1) % 3)    # . .. ... . .. ...: still working, just no news
        else:
            tail = "…"
        self._detail.setText(message + tail if message else "")
        self._detail.setVisible(bool(message))
        self._bar.setValue(int(self._fraction * 1000))
        _place_toast(self._ctx)                               # the detail line can wrap, changing the height

    def snapshot(self):
        """What the toast currently says (for tests and debugging)."""
        shown = self._widget is not None and self._ctx._toast is self._widget
        return {
            "visible": shown,
            "label": self._label,
            "percent": self._percent.text() if shown else None,
            "detail": self._detail.text() if shown else None,
            "fraction": self._fraction,
        }


def show_error(ctx, msg):
    QMessageBox.critical(ctx.win, "Error", msg)


def show_success(ctx, msg):
    QMessageBox.information(ctx.win, "Success", msg)
