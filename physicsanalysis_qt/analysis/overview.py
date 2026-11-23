"""
analysis/overview.py
--------------------
Recording Overview: the whole recording's traces one above another, with the Z-score of the whole recording. For a TDT recording the panels are
Control (the isosbestic stream), Signal (the main driver), Control Fit (the control as fitted to the signal, which motion correction subtracts),
Z-Score and ΔF/F; for any other recording each channel and its Z-score. Where the Z-score windows around one event or one click z-score each window
against its own baseline, this z-scores the dF/F over the whole recording (the mean and SD of every sample, or the robust version that a few
large transients cannot skew), so a slow drift or a long response shows against the whole session.

The analysis is the engine's: the library's `recording_overview`, asked for about DRAW_ROWS rows (the lowest and highest sample of every stretch of the
recording, so no peak is lost) to draw from. The Z-score is taken over every sample either way. Export CSV asks for the whole table, every sample, so the
file is the recording and not its picture, and the provenance record beside it replays that. Open Results draws the exported file again.

Which panels are shown, and in what order, is the person's: a list beside the plot — no buttons, the list is the control — has a tick for each panel
(a panel that is not ticked is greyed) and is put in order by dragging a panel to where it goes (Alt+Up / Alt+Down move the one that is selected, and a
right-click offers the same and Show all). Only the drawing changes — the Z-score is taken over the whole recording whichever are shown — and the choice is what Export CSV, Export Plot and
their provenance records carry (the library's `panels` parameter), and is remembered for the next time.

Reached from Custom Statistics, for any kind of recording.
"""

import datetime
import shutil

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QKeySequence, QPalette, QShortcut
from PyQt6.QtWidgets import (
    QAbstractItemView, QAbstractScrollArea, QApplication, QComboBox, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from .. import figures
from ..figures.tables import float_array
from ..app import errorlog
from ..app.toasts import show_error, show_window_toast
from ..app.window_fit import fit_to_screen
from ..edit.figure_attributes import EditableFigure
from .. import context as _context            # not `from .. import save_settings`: tests replace it on the module
from ..context import export_file, get_normalized_signal
from ..ui.workspace import present
from .dispatch import export_figure_to_file
from .windows import request_analysis

KIND = "recording_overview"
DRAW_ROWS = 24_000                  # about this many rows are fetched to draw from (figures/draw.py thins them to the window's width)
METHODS = (("Standard — mean and SD of the whole recording", "standard"),
           ("Robust — large transients do not shrink the scale", "robust"))
NEEDS_NEWER_LIBRARY = ("The analysis engine PyAT started has no 'recording_overview' analysis: it is an older PyATCLI than this PyAT needs. "
                       "Update it with: pip install --upgrade PyATCLI")


def default_parameters(ctx):
    """What the window is first asked for: the dF/F (or the recording's first signal) z-scored the standard way."""
    key = get_normalized_signal(ctx)[0] if ctx.cache.get("signals") else "normalized"
    return {"signal": key, "method": "standard", "max_points": DRAW_ROWS}     # (every panel is asked for: which are drawn is chosen in the window)


def summary_text(ctx, params, summary, notes):
    """What was z-scored and how, what scale was used, and how much the picture is drawn from."""
    signals = ctx.cache.get("signals") or {}
    if signals and params["signal"] in signals:
        head = (f"Z-Score of {signals[params['signal']]['label']} ({params['method']}): mean {summary['zscore_mean']:.6g}, "
                f"SD {summary['zscore_sd']:.6g}")
    else:
        head = f"Z-Score of each channel ({params['method']})"
    lines = [head]
    if summary["n_rows"] < summary["n_samples"]:
        lines.append(f"{summary['n_samples']:,} samples over {summary['duration_s']:.1f} s, drawn from {summary['n_rows']:,} points "
                     "that keep every peak and dip; Export CSV has every sample")
    else:
        lines.append(f"{summary['n_samples']:,} samples over {summary['duration_s']:.1f} s")
    lines += [str(n) for n in notes]
    return "\n".join(lines)


class _OverviewDialog(QDialog):
    """Stays open: pick the signal or the method and press Update to z-score again in place."""

    def __init__(self, parent, ctx, result, params):
        super().__init__(parent)
        self.ctx = ctx
        self.params = dict(params)
        self.tables, self.summary, self.notes = {}, {}, []
        self.full_table = None                                  # every panel, as the engine answered (the list below chooses which are drawn)
        self.available = []
        self.setWindowTitle(f"Recording Overview — {ctx.cache['store']}")
        fit_to_screen(self, 1200, 860)
        outer = QHBoxLayout(self)
        layout = QVBoxLayout()
        outer.addLayout(layout, stretch=1)

        controls = QHBoxLayout()
        signals = ctx.cache.get("signals") or {}
        self.signal_combo = None
        if signals:
            controls.addWidget(QLabel("Z-score of:"))
            self.signal_combo = QComboBox()
            for key, signal in signals.items():
                self.signal_combo.addItem(signal["label"], userData=key)
            self.signal_combo.setCurrentIndex(max(0, self.signal_combo.findData(self.params["signal"])))
            controls.addWidget(self.signal_combo)
        controls.addWidget(QLabel("Method:"))
        self.method_combo = QComboBox()
        for label, key in METHODS:
            self.method_combo.addItem(label, userData=key)
        self.method_combo.setCurrentIndex(max(0, self.method_combo.findData(self.params["method"])))
        self.method_combo.setToolTip("Standard: (x - mean) / SD over the whole recording.\nRobust: the same with the mean and SD taken after samples "
                                     "further than 5 robust SDs from the median are pulled in to that limit (the rule the other analyses use "
                                     "for a baseline), so a few large transients do not shrink every other z-score.")
        controls.addWidget(self.method_combo)
        self.btn_update = QPushButton("Update")
        self.btn_update.setDefault(True)
        self.btn_update.clicked.connect(self._update)
        controls.addWidget(self.btn_update)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.fig = figures.new_recording_overview_figure()
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.editable_figure = EditableFigure(ctx, self, self.fig, self.canvas)        # Edit Attributes edits this figure (edit/figure_attributes.py)
        layout.addWidget(self.canvas, stretch=1)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setFont(QFont("Consolas", 9))
        self.lbl_summary.setWordWrap(True)
        layout.addWidget(self.lbl_summary)

        btn_row = QHBoxLayout()
        self.btn_copy = QPushButton("Copy")
        self.btn_copy.clicked.connect(self._copy)
        btn_row.addWidget(self.btn_copy)
        self.btn_csv = QPushButton("Export CSV")
        self.btn_csv.setToolTip("Every sample of the panels that are shown, as a table (time_s, then a column per panel, in the order of the list).")
        self.btn_csv.clicked.connect(self._export_csv)
        btn_row.addWidget(self.btn_csv)
        self.btn_export = QPushButton("Export Plot")
        self.btn_export.clicked.connect(self._export_plot)
        btn_row.addWidget(self.btn_export)
        btn_row.addStretch(1)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        right = QWidget()
        right.setFixedWidth(210)
        side = QVBoxLayout(right)
        side.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("Panels")
        heading.setStyleSheet("font-weight: bold;")
        side.addWidget(heading)
        hint = QLabel("Tick a panel to show it. Drag a panel up or down to put the panels in order.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray;")
        side.addWidget(hint)
        self.panel_list = QListWidget()
        self.panel_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.panel_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.panel_list.setDropIndicatorShown(True)
        self.panel_list.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)         # as tall as its panels, or as the room there is
        self.panel_list.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.panel_list.setToolTip("The panels the recording has. The ticked ones are drawn, top to bottom in this order.\n"
                                   "Drag a panel to move it (or select it and press Alt+Up / Alt+Down); right-click for more.")
        self.panel_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.panel_list.customContextMenuRequested.connect(self._panel_menu)
        for keys, step in (("Alt+Up", -1), ("Alt+Down", 1)):
            shortcut = QShortcut(QKeySequence(keys), self.panel_list)
            shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            shortcut.activated.connect(lambda step=step: self._move(step))
        side.addWidget(self.panel_list)
        side.addStretch(1)
        outer.addWidget(right)

        self._show(result, params)
        self.panel_list.itemChanged.connect(self._panels_changed)
        self.panel_list.model().rowsMoved.connect(self._panels_changed)

    # --- what is on screen

    def _provenance(self):
        """What is on screen as an analyses.py recording_overview: the signal, the method, how many rows were asked for to draw and, if not all of
        them in the recording's order, which panels."""
        parameters = dict(self.params)
        panels = self._panels_param()
        if panels is not None:
            parameters["panels"] = panels
        return {"kind": KIND, "parameters": parameters}

    def _show(self, result, params):
        self.params, self.tables, self.summary, self.notes = dict(params), result.tables, result.summary, list(result.notes)
        self.full_table = result.tables["overview"]
        names = [name for name, _ in figures.overview_panels(self.full_table)]
        if names != self.available:                              # the first answer (or a recording with other panels): the list is made
            self._fill_panel_list(names)
        self._redraw()
        self.lbl_summary.setText(summary_text(self.ctx, params, result.summary, result.notes))

    # --- which panels, in what order

    def _fill_panel_list(self, names):
        """The list of panels: the ones the person had ticked last time (that this recording has) first, in their order, ticked; the rest after them,
        not ticked. If none of the remembered ones are here, all of them in the recording's order, all ticked."""
        self.available = list(names)
        remembered = self.ctx.settings.get("overview_panels")                  # (a settings file can hold anything)
        saved = [n for n in (remembered if isinstance(remembered, list) else []) if isinstance(n, str) and n in names]
        ticked = saved or list(names)
        order = ticked + [n for n in names if n not in ticked]
        self.panel_list.blockSignals(True)
        self.panel_list.clear()
        for name in order:
            item = QListWidgetItem(name, self.panel_list)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
            item.setCheckState(Qt.CheckState.Checked if name in ticked else Qt.CheckState.Unchecked)
        self.panel_list.blockSignals(False)
        self._style_panel_rows()

    def _style_panel_rows(self):
        """A panel that is not ticked is greyed, so which are shown reads at a glance."""
        grey = self.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
        self.panel_list.blockSignals(True)
        for i in range(self.panel_list.count()):
            item = self.panel_list.item(i)
            item.setForeground(grey if item.checkState() != Qt.CheckState.Checked else self.palette().color(QPalette.ColorRole.Text))
        self.panel_list.blockSignals(False)

    def _selected(self):
        """The ticked panels' names, in the order of the list."""
        return [self.panel_list.item(i).text() for i in range(self.panel_list.count())
                if self.panel_list.item(i).checkState() == Qt.CheckState.Checked]

    def _panels_param(self):
        """The `panels` the library is asked for: None when every panel is shown in the recording's own order (what is asked for by default)."""
        selected = self._selected()
        return None if selected == self.available else selected

    def _panels_changed(self, *_):
        """A tick or a move: drawn again from the table the window holds (nothing to ask the engine), and remembered for next time."""
        self._style_panel_rows()
        self.ctx.settings["overview_panels"] = self._selected() or None
        try:
            _context.save_settings(self.ctx.settings)
        except OSError:
            errorlog.error("Could not save the Recording Overview panels", exc_info=True)
        self._redraw()

    def _move(self, step):
        row = self.panel_list.currentRow()
        target = row + step
        if row < 0 or not 0 <= target < self.panel_list.count():
            return
        self.panel_list.blockSignals(True)
        item = self.panel_list.takeItem(row)
        self.panel_list.insertItem(target, item)
        self.panel_list.setCurrentRow(target)
        self.panel_list.blockSignals(False)
        self._panels_changed()

    def _tick_all(self):
        self.panel_list.blockSignals(True)
        for i in range(self.panel_list.count()):
            self.panel_list.item(i).setCheckState(Qt.CheckState.Checked)
        self.panel_list.blockSignals(False)
        self._panels_changed()

    def _tick_only(self, row):
        self.panel_list.blockSignals(True)
        for i in range(self.panel_list.count()):
            self.panel_list.item(i).setCheckState(Qt.CheckState.Checked if i == row else Qt.CheckState.Unchecked)
        self.panel_list.blockSignals(False)
        self._panels_changed()

    def _panel_menu(self, pos):
        """Right-click on the list: what the buttons used to be, for whoever looks for them (dragging does the same)."""
        item = self.panel_list.itemAt(pos)
        if item is not None:
            self.panel_list.setCurrentItem(item)
        row = self.panel_list.currentRow()
        menu = QMenu(self.panel_list)
        up = menu.addAction("Move up", lambda: self._move(-1))
        down = menu.addAction("Move down", lambda: self._move(1))
        up.setEnabled(row > 0)
        down.setEnabled(0 <= row < self.panel_list.count() - 1)
        menu.addSeparator()
        only = menu.addAction("Show only this panel", lambda: self._tick_only(row))
        only.setEnabled(row >= 0)
        menu.addAction("Show all panels", self._tick_all)
        menu.exec(self.panel_list.mapToGlobal(pos))

    def _redraw(self):
        table = self.full_table
        shown = [(name, values) for name, values in figures.overview_panels(table) if name in set(self._selected())]
        order = {name: i for i, name in enumerate(self._selected())}
        shown.sort(key=lambda panel: order[panel[0]])
        figures.draw_recording_overview(self.fig, time=float_array(table["time_s"]), panels=shown, title=figures.overview_title(self.params))
        self.editable_figure.drawn()

    def _export_plot(self):
        if not self._selected():
            show_error(self.ctx, "Tick at least one panel to export.")
            return
        export_figure_to_file(self.ctx, self.fig, "RecordingOverview", self.ctx.cache["store"], provenance=self._provenance())

    def _update(self):
        params = {"signal": self.signal_combo.currentData() if self.signal_combo is not None else self.params["signal"],
                  "method": self.method_combo.currentData(), "max_points": DRAW_ROWS}
        errorlog.action("analysis", tool="Recording Overview", **params)
        self.btn_update.setEnabled(False)

        def on_result(result):
            self.btn_update.setEnabled(True)
            self._show(result, params)

        def on_error(message):
            self.btn_update.setEnabled(True)
            show_error(self.ctx, NEEDS_NEWER_LIBRARY if "Unknown analysis" in message else f"Recording Overview failed: {message}")

        if request_analysis(self.ctx, KIND, params, on_result, label="Recording overview", on_error=on_error) is None:
            self.btn_update.setEnabled(True)

    # --- the buttons

    def _copy(self):
        QApplication.clipboard().setText(self.lbl_summary.text())
        show_window_toast(self.ctx, "Copied to clipboard")

    def _export_csv(self):
        """Asks the engine for every sample (what is drawn is thinned) of the panels that are shown, in their order, then writes that file where the
        person says, with its record."""
        if not self._selected():
            show_error(self.ctx, "Tick at least one panel to export.")
            return
        params = {**self._provenance()["parameters"], "max_points": 0}

        def on_result(result):
            source = result.files.get("overview")
            if not source:
                show_error(self.ctx, "The analysis engine did not hand over the table.")
                return
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            export_file(self.ctx, self, "Export Recording Overview", f"RecordingOverview_{self.ctx.cache['store']}_{stamp}.csv",
                        "CSV (*.csv);;Text (*.txt)", lambda dest: shutil.copyfile(source, dest), provenance={"kind": KIND, "parameters": params})

        request_analysis(self.ctx, KIND, params, on_result, label="Preparing the table", tables="files")


def launch_recording_overview(ctx):
    """Z-scores the loaded recording over its whole length and opens the window for the answer, as a tab."""
    if ctx.cache is None:
        show_error(ctx, "Open a recording first.")
        return
    params = default_parameters(ctx)
    errorlog.action("analysis", tool="Recording Overview", **params)

    def on_error(message):
        show_error(ctx, NEEDS_NEWER_LIBRARY if "Unknown analysis" in message else f"Recording Overview failed: {message}")

    def on_result(result):
        dlg = _OverviewDialog(ctx.win, ctx, result, params)
        show_window_toast(ctx, "Recording overview computed")
        present(ctx, dlg, "Recording Overview")

    request_analysis(ctx, KIND, params, on_result, label="Recording overview", on_error=on_error)
