"""
analysis/analysis_picker.py
----------------------------
The toolbar's "Analysis" button — replaces the old mode dropdown. Clicking
it always opens this menu, and going back to it cancels whatever tool was
armed: the menu always starts from the plain plot, so closing it with the X
(or Close) just leaves you there. Pick a tool to arm it, and a toast says
what to do on the graph next. The picked tool is armed for ONE run: the
next double-click on the graph (Curve Fit: the next two clicks) runs it
and it disarms itself, like Splice.

Tick "Persist through trials" at the top of the menu and the tool stays
armed after each run instead, so you can go from one trial to the next by
double-clicking each in turn. Only then does a small panel with a "Done"
button sit in the window's bottom-left corner (toasts.show_pinned_panel):
press it to turn the tool off. It never times out and toasts don't touch
it. Every graph window a tool opens has a "Done" button at the bottom too
(add_done_button). Closing a graph window with its X instead leaves a
persistent tool armed for the next trial.

The analysis window (seconds either side of the point you double-click) is
set from this menu too, rather than from its own top-bar button.

Which tool is armed is ctx.analysis_mode: None, or the "mode" of one of the
_TOOLS below. analysis/dispatch.py's analysis_type() launches FFT/Z-Score/AUC
from it, and the three engines' click handlers read it for Curve Fit; each
calls disarm_analysis() the moment it runs.

Adding a tool means one entry in _TOOLS (plus wiring its launch into
dispatch.analysis_type, or its click handling into the engines, and a Done
button on its graph window).
"""

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox

from .window_settings import open_window_dialog, window_summary
from ..app.toasts import show_error, show_window_toast, show_pinned_panel, hide_pinned_panel
from ..app.window_fit import fit_to_screen

_TOOLS = [
    {
        "mode": "Z-Score",
        "label": "Z-Score PETH",
        "hint": "double-click the graph on the event you want to Z-score",
        "per_trial": "double-click each trial",
        "tooltip": "Z-scores the signal in a window around the point you double-click, "
                   "against the stretch just before it.",
    },
    {
        "mode": "FFT",
        "label": "FFT",
        "hint": "double-click the graph where you want the spectrum taken",
        "per_trial": "double-click each trial",
        "tooltip": "Frequency spectrum of the window around the point you double-click.",
    },
    {
        "mode": "AUC",
        "label": "AUC",
        "hint": "double-click the graph where you want the area measured",
        "per_trial": "double-click each trial",
        "tooltip": "Area under the curve in the window around the point you double-click.",
    },
    {
        "mode": "Curve Fit",
        "label": "Curve Fit",
        "hint": "click two points on the graph to anchor the fit",
        "per_trial": "click two points on each trial",
        "tooltip": "Fits a model to the stretch between two points you click on the graph.",
    },
]

_IDLE_TOOLTIP = ("Analysis — pick FFT, Z-Score, AUC or Curve Fit, then click on the graph. "
                 "The analysis window (seconds around the click) is set here too.")
_ACTIVE_STYLE = "background-color: #FFD54F; color: black;"  # same "armed" yellow as Add Marker


def _tool_for(mode):
    return next(t for t in _TOOLS if t["mode"] == mode)


class _AnalysisPickerDialog(QDialog):
    """Tool buttons plus the analysis-window setting. Choosing a tool closes
    the menu (self.mode says which); closing it any other way picks nothing.
    open_analysis_menu() has already cancelled whatever was armed by the
    time this opens."""

    def __init__(self, ctx):
        super().__init__(ctx.win)
        self.ctx = ctx
        self.mode = None
        self.setWindowTitle("Analysis")
        fit_to_screen(self, 400, 350)
        layout = QVBoxLayout(self)

        persist_row = QHBoxLayout()
        self.chk_persist = QCheckBox("Persist through trials")
        self.chk_persist.setToolTip(
            "Off: the tool you pick runs once, then switches itself off.\n"
            "On: it stays armed after each run, so you can double-click one trial\n"
            "after another — press Done (bottom-left, or on a graph window) when\n"
            "you're finished.")
        self.chk_persist.setChecked(ctx.analysis_persist)
        self.chk_persist.toggled.connect(self._set_persist)
        persist_row.addWidget(self.chk_persist)
        persist_hint = QLabel("press Done to stop")
        persist_hint.setStyleSheet("color: gray;")
        persist_row.addWidget(persist_hint)
        persist_row.addStretch(1)
        layout.addLayout(persist_row)

        intro = QLabel(
            "Pick an analysis, then double-click the graph where you want it\n"
            "(Curve Fit: click two points instead). It analyzes whichever\n"
            "signal is currently plotted."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        for tool in _TOOLS:
            btn = QPushButton(tool["label"])
            btn.setToolTip(tool["tooltip"])
            btn.clicked.connect(lambda _checked=False, mode=tool["mode"]: self._pick(mode))
            layout.addWidget(btn)

        layout.addSpacing(8)
        window_row = QHBoxLayout()
        window_row.addWidget(QLabel("Window around the click:"))
        self.btn_window = QPushButton()
        self.btn_window.setToolTip("Seconds of signal analyzed either side of the point you "
                                   "double-click (used by Z-Score, FFT and AUC).")
        self.btn_window.clicked.connect(self._edit_window)
        window_row.addWidget(self.btn_window)
        window_row.addStretch(1)
        layout.addLayout(window_row)
        self._refresh_window_text()

        layout.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        layout.addWidget(btn_close)

    def _set_persist(self, checked):
        self.ctx.analysis_persist = checked  # remembered for the session, even if no tool gets picked

    def _refresh_window_text(self):
        self.btn_window.setText(f"{window_summary(self.ctx)} — change…")

    def _edit_window(self):
        open_window_dialog(self.ctx)
        self._refresh_window_text()

    def _pick(self, mode):
        self.mode = mode
        self.accept()


def _set_mode(ctx, mode):
    """Arm (or, with None, disarm) a tool and show it on the button — and,
    when "Persist through trials" is ticked, in the pinned Done panel."""
    ctx.analysis_mode = mode
    ctx.slope_clicks.clear()  # never carry a half-finished Curve Fit anchor into the next tool
    btn = ctx.btn_analysis
    if mode is None:
        btn.setText("Analysis")
        btn.setStyleSheet("")
        btn.setToolTip(_IDLE_TOOLTIP)
        hide_pinned_panel(ctx)
        return

    tool = _tool_for(mode)
    label = tool["label"]
    btn.setText(f"Analysis: {label}")
    btn.setStyleSheet(_ACTIVE_STYLE)
    if ctx.analysis_persist:
        btn.setToolTip(f"{label} stays armed until you press Done — click here to cancel it and reopen the menu")
        show_pinned_panel(ctx, f"{label} stays armed — {tool['per_trial']}.\nPress Done when you're finished.",
                          "Done", lambda: stop_analysis(ctx))
    else:
        # One run only: it disarms itself, so there's nothing to keep a Done
        # button on screen for.
        btn.setToolTip(f"{label} is armed for one run — click here to cancel it and reopen the menu")
        hide_pinned_panel(ctx)


def disarm_analysis(ctx):
    """Called by a tool the moment it runs (dispatch.analysis_type for
    FFT/Z-Score/AUC, curve_fit.launch_curve_fit for Curve Fit): an armed
    tool is good for one run, so the next one means picking it again —
    unless "Persist through trials" is ticked, which keeps it armed."""
    if ctx.analysis_mode is not None and not ctx.analysis_persist:
        _set_mode(ctx, None)


def stop_analysis(ctx):
    """Turn the armed tool off for good — the Done buttons. (Not the same
    as disarm_analysis, which persistence can veto.) No-op if nothing is
    armed."""
    if ctx.analysis_mode is not None:
        _set_mode(ctx, None)
        show_window_toast(ctx, "Analysis mode OFF")


def add_done_button(ctx, dialog, btn_row_layout):
    """Adds a "Done" button to the bottom row of an Analysis tool's graph
    window: closes it and turns the armed tool off — the way to end a
    "Persist through trials" run. With nothing persisting it's just a close
    button. Closing the window any other way (its X) leaves a persistent
    tool armed for the next trial."""
    persisting = ctx.analysis_mode is not None and ctx.analysis_persist
    btn = QPushButton("Done")
    btn.setToolTip("Close this window and stop analyzing trials (turns the armed tool off).\n"
                   "Closing it with the X instead keeps the tool armed for the next trial."
                   if persisting else "Close this window.")

    def _done():
        dialog.accept()
        stop_analysis(ctx)  # after accept(): the toast belongs to the main window, not this dialog

    btn.clicked.connect(_done)
    btn_row_layout.addWidget(btn)
    return btn


def open_analysis_menu(ctx):
    """The Analysis button: opens the menu, and going back to it cancels
    whatever tool was armed — so picking arms a fresh one, and closing the
    menu (X or Close) just leaves the plain plot. (The Done buttons are the
    other way to turn a persistent tool off.)"""
    was_armed = ctx.analysis_mode is not None
    if was_armed:
        _set_mode(ctx, None)
    if ctx.cache is None:
        show_error(ctx, "Load a dataset first.")
        return

    dlg = _AnalysisPickerDialog(ctx)
    if dlg.exec() == QDialog.DialogCode.Accepted and dlg.mode:
        _set_mode(ctx, dlg.mode)
        tool = _tool_for(dlg.mode)
        note = " — it stays armed until you press Done" if ctx.analysis_persist else ""
        show_window_toast(ctx, f"{tool['label']}: {tool['hint']}{note}", duration=4000)
    elif was_armed:
        show_window_toast(ctx, "Analysis mode OFF")
