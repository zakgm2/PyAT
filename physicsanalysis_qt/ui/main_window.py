"""
ui/main_window.py
--------------------
Assembles the QMainWindow: toolbar, plot canvas (matplotlib and
PyQtGraph both built up front, stacked in a QStackedWidget so switching
engines in Options is instant), mouse/scroll/resize event wiring,
rectangle selector, status bar.
"""

from datetime import date

from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.widgets import RectangleSelector
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy, QStatusBar, QStackedWidget,
    QToolButton,
)

from .. import interaction
from .. import undo
from ..pg_engine import build_pg_widget, sync_pg_margins
from ..toasts import show_error, show_window_toast
from ..update_check import local_version
from ..vispy_engine import build_vispy_widget, sync_vispy_margins
from ..window_fit import fit_to_screen
from .toolbar import build_toolbar
from .edit_toolbar import build_edit_toolbar

REPO_URL = "https://github.com/zakgm2/PyAT"
FEEDBACK_URL = f"{REPO_URL}/issues"
COFFEE_URL = "https://buymeacoffee.com/zakgm2"


def _widget_for_engine(ctx):
    engine = ctx.settings.get("plot_engine")
    if engine == "pyqtgraph":
        return ctx.pg_widget
    if engine == "vispy":
        return ctx.vispy_canvas.native
    return ctx.canvas


class _PlotStack(QStackedWidget):
    """QStackedWidget that debounce-triggers a re-render on resize when
    the PyQtGraph or VisPy engine is active, so their fonts stay scaled
    to the current widget size — matplotlib gets this for free via its
    own resize_event (see interaction.on_resize). Also keeps each
    engine's inset margins matched to matplotlib's subplot margins on
    every resize, so all three engines frame their plot the same
    distance from the edges — the widget itself stays full size either
    way; only how much of it the axes/data occupy changes."""

    def __init__(self, ctx):
        super().__init__()
        self._ctx = ctx
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._replot)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        ctx = self._ctx
        if ctx.cache is None:
            return
        # Cheap margin + font sync on every tick (reuses the last measured
        # axis size, single pass, no flash-prone zero-margin probe, and no
        # touching line data) so the plot area and title/axis/legend text
        # track the widget size live and continuously during the drag,
        # matching how matplotlib's own canvas already redraws live. The
        # accurate two-pass reprobe + full data replot are debounced to
        # once after the drag settles, since both are more expensive.
        engine = ctx.settings.get("plot_engine")
        if engine == "pyqtgraph":
            from ..pg_engine import pg_refresh_fonts
            pg_refresh_fonts(ctx)
        elif engine == "vispy":
            from ..vispy_engine import vispy_refresh_fonts
            vispy_refresh_fonts(ctx)
        sync_pg_margins(ctx, reprobe=False)
        sync_vispy_margins(ctx)
        self._timer.start(150)

    def _replot(self):
        # Not a full pg_simple_plot() — this settle-tick only exists to
        # get an accurate (reprobe=True) margin/font pass once the drag
        # stops; pg_refresh_fonts already does that without touching line
        # data, markers, or view range. A full rebuild here was pure
        # overkill for that and paid for it with a one-frame flash on
        # every resize settle, including the layout reflow a fresh TDT
        # load triggers by revealing the Plot dropdown for the first time
        # — same class of bug pg_set_grid_visibility's docstring already
        # covers for grid toggles.
        ctx = self._ctx
        engine = ctx.settings.get("plot_engine")
        if engine == "pyqtgraph":
            from ..pg_engine import pg_refresh_fonts
            pg_refresh_fonts(ctx)
        elif engine == "vispy":
            from ..vispy_engine import vispy_refresh_fonts
            vispy_refresh_fonts(ctx)
        sync_pg_margins(ctx, reprobe=True)
        sync_vispy_margins(ctx)


def build_main_window(ctx):
    ctx.win = QMainWindow()
    try:
        version = local_version("physicsanalysis_qt")
    except Exception:
        version = None  # missing/unreadable pyproject.toml (e.g. a packaged build) — title still works without it
    title = "PyAT (Python Analysis Tool)" + (f" — v{version}" if version else "")
    ctx.win.setWindowTitle(title)
    # The main window may take most of the screen (95%, vs. a dialog's
    # 85%) — it's the app itself, not a pop-up over it.
    fit_to_screen(ctx.win, 1250, 850, max_width_frac=0.95, max_height_frac=0.95)

    central = QWidget()
    ctx.win.setCentralWidget(central)
    outer_layout = QHBoxLayout(central)
    outer_layout.setContentsMargins(0, 0, 0, 0)
    outer_layout.setSpacing(0)

    edit_toolbar = build_edit_toolbar(ctx)
    outer_layout.addWidget(edit_toolbar)

    right_column = QWidget()
    root_layout = QVBoxLayout(right_column)
    root_layout.setContentsMargins(0, 0, 0, 0)
    outer_layout.addWidget(right_column, stretch=1)

    toolbar = build_toolbar(ctx)
    root_layout.addWidget(toolbar)

    ctx.stacked_plot_widget = _PlotStack(ctx)
    root_layout.addWidget(ctx.stacked_plot_widget, stretch=1)

    _build_matplotlib_canvas(ctx)
    ctx.stacked_plot_widget.addWidget(ctx.canvas)

    build_pg_widget(ctx)  # sets ctx.pg_widget / ctx.pg_plot_item
    ctx.stacked_plot_widget.addWidget(ctx.pg_widget)

    vispy_native = build_vispy_widget(ctx)  # sets ctx.vispy_canvas / ctx.vispy_view
    ctx.stacked_plot_widget.addWidget(vispy_native)

    ctx.stacked_plot_widget.setCurrentWidget(_widget_for_engine(ctx))
    sync_pg_margins(ctx)
    sync_vispy_margins(ctx)

    ctx.status_bar = QStatusBar()
    ctx.win.setStatusBar(ctx.status_bar)
    ctx.status_bar.showMessage("X: -- | Y: -- | Pt: --")
    ctx.status_bar.addPermanentWidget(_build_coffee_button())
    ctx.status_bar.addPermanentWidget(_build_citation_button(ctx))
    ctx.status_bar.addPermanentWidget(_build_feedback_button())

    # Ctrl+Z: undoes the last marker/splice edit (undo.py), one step at a time — not a general
    # app-wide undo (Edit Attributes, Options, plot engine, etc. are untouched by it). Default
    # WindowShortcut context: a focused QLineEdit's own built-in text-undo still consumes Ctrl+Z
    # first, so this only fires when nothing is mid-edit.
    shortcut_undo = QShortcut(QKeySequence("Ctrl+Z"), ctx.win)
    shortcut_undo.activated.connect(lambda: _undo_last_action(ctx))

    return ctx.win


def _undo_last_action(ctx):
    if ctx.cache is None:
        return
    label = undo.undo(ctx)
    if label is None:
        show_error(ctx, "Nothing to undo.")
    else:
        show_window_toast(ctx, f"Undid: {label}")


def _build_coffee_button():
    """Coffee icon in the status bar — opens the Buy Me a Coffee page in
    the user's browser, same open-external-link pattern as the feedback
    button below."""
    btn = QToolButton()
    btn.setText("☕")
    btn.setToolTip("Buy Me a Coffee")
    btn.setAutoRaise(True)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(COFFEE_URL)))
    return btn


def _build_feedback_button():
    """Bug icon in the status bar's bottom-right corner — opens the GitHub
    issues page in the user's browser so bug reports/feedback don't need
    to be routed through the developer manually."""
    btn = QToolButton()
    btn.setText("\U0001F41E")  # 🐞
    btn.setToolTip("Send Feedback")
    btn.setAutoRaise(True)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(FEEDBACK_URL)))
    return btn


def apa_citation():
    """APA 7 software citation. Year is "today" rather than a stored
    per-version release date — this project doesn't track one, and for a
    citation generated at run time that's a reasonable stand-in."""
    try:
        version = local_version("physicsanalysis_qt")
    except Exception:
        version = None
    version_part = f" (Version {version})" if version else ""
    return f"Grand Maison, Z. ({date.today().year}). PyAT: Python Analysis Tool{version_part} [Computer software]. {REPO_URL}"


def _build_citation_button(ctx):
    """Quote-mark icon in the status bar — copies an APA citation for this
    app to the clipboard and confirms with a toast, so users citing it in
    a paper don't have to hand-write the format themselves."""
    btn = QToolButton()
    btn.setText("❝ APA Citation")
    btn.setToolTip("Copy APA citation to clipboard")
    btn.setAutoRaise(True)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def _copy():
        ctx.app.clipboard().setText(apa_citation())
        show_window_toast(ctx, "Citation copied to clipboard")

    btn.clicked.connect(_copy)
    return btn


def _build_matplotlib_canvas(ctx):
    ctx.fig = Figure(figsize=(8, 4), dpi=100)
    ctx.ax = ctx.fig.add_subplot(111)
    ctx.canvas = FigureCanvasQTAgg(ctx.fig)
    ctx.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    ctx.canvas.mpl_connect('button_press_event', lambda e: interaction.on_press(ctx, e))
    ctx.canvas.mpl_connect('motion_notify_event', lambda e: interaction.on_motion(ctx, e))
    ctx.canvas.mpl_connect('button_release_event', lambda e: interaction.on_release(ctx, e))

    zoom_fun = interaction.zoom_factory(ctx, base_scale=1.1)
    ctx.canvas.mpl_connect('scroll_event', zoom_fun)
    ctx.canvas.mpl_connect('resize_event', lambda e: interaction.on_resize(ctx, e))

    ctx.rect_selector = RectangleSelector(
        ctx.ax, lambda eclick, erelease: interaction.on_select(ctx, eclick, erelease),
        useblit=True, button=[1],
        minspanx=5, minspany=0.001,
        props=dict(facecolor='yellow', edgecolor='black', alpha=0.3, fill=True),
        interactive=True
    )
    ctx.rect_selector.set_active(True)
    ctx.canvas.draw()


def switch_plot_engine(ctx):
    """Called by Options when the user changes the plot engine. Swaps the
    visible widget in the stack and re-renders the current dataset with
    the newly selected engine."""
    from ..plotting import simple_plot

    ctx.stacked_plot_widget.setCurrentWidget(_widget_for_engine(ctx))
    sync_pg_margins(ctx)
    sync_vispy_margins(ctx)
    if ctx.cache is not None:
        simple_plot(ctx)
