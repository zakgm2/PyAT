"""
analysis/event_compare.py
-------------------------
Compare Events: tick several events and overlay the average Z-score of each on one plot (mean +/- SEM, a colour per event), with
each event's peak, latency and AUC side by side underneath. Every event is analysed exactly as the Event PETH window analyses it
(each occurrence z-scored against its own pre-event baseline, all usable trials averaged), so an event's trace and numbers here
are the ones Event PETH shows for it; this window only puts them next to each other, in one window setting, so they can be compared.

The analysis is the engine's: the library's `event_compare` (the same one a script or `python -m PyATCLI run event_compare` runs),
asked for the ticked events with the times the window holds for them. Its two tables are what Export CSV writes (the mean traces,
or the summary: pick which beside the button) and the figure is drawn from them (figures/draw.py, the same drawing Open Results
uses), so what is exported is what is on screen, and the provenance record beside an export replays it.

Reached from Custom Statistics, or from the Event PETH window's "Compare events…" button, which starts it with that window's event
ticked and its window settings. TDT only, like Event PETH: event markers are a TDT concept in this app.
"""

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from .. import figures
from ..app import errorlog
from ..app.toasts import show_error, show_window_toast
from ..app.window_fit import fit_to_screen
from ..edit.figure_attributes import EditableFigure
from ..backend import api
from ..context import get_normalized_signal, signal_short_label
from ..ui.workspace import present
from .dispatch import add_stats_export_buttons, export_figure_to_file, get_window
from .windows import request_analysis

NEEDS_NEWER_LIBRARY = ("The analysis engine PyAT started has no 'event_compare' analysis: it is an older PyATCLI than this PyAT needs. "
                       "Update it with: pip install --upgrade PyATCLI")


def summary_text(summary, pre, post, bin_s):
    """The per-event numbers as a monospaced table: trials, the peak of the average and when it comes, the area under it."""
    names = [str(n) for n in summary["Event"]]
    width = min(28, max([len("Event")] + [len(n) for n in names]))
    lines = [f"{'Event':<{width}}  {'Trials':>6}  {'Peak (z)':>9}  {'at (s)':>7}  {'AUC':>9}  {'+AUC':>9}  {'-AUC':>9}"]
    for name, (_, row) in zip(names, summary.iterrows()):
        shown = name if len(name) <= width else name[:width - 1] + "…"
        lines.append(f"{shown:<{width}}  {int(row['Trials']):>6}  {row['Peak Amplitude']:>9.2f}  {row['Time-to-Peak (s)']:>+7.2f}  "
                     f"{row['Total AUC']:>9.2f}  {row['Positive AUC']:>+9.2f}  {row['Negative AUC']:>+9.2f}")
    lines.append(f"Window: -{pre:g}s / +{post:g}s around each event, {bin_s:g}s bins")
    return "\n".join(lines)


class _EventCompareDialog(QDialog):
    """Stays open: change the ticked events or the window and press Compare to run it again in place."""

    TABLES = (("Mean traces", "traces"), ("Summary", "summary"))

    def __init__(self, parent, ctx, groups, initial_events=(), window=None):
        super().__init__(parent)
        self.ctx = ctx
        self.groups = groups
        self.params = None                       # what the results on screen were asked for (the provenance's parameters)
        self.tables = {}                         # {"traces", "summary"} of those results
        self.events = []                         # the figure's events, from the traces table
        self.notes = []
        key, _, _, _ = get_normalized_signal(ctx)
        self.mode_str = signal_short_label(key)

        self.setWindowTitle("Compare Events")
        fit_to_screen(self, 1000, 720)
        outer = QHBoxLayout(self)
        layout = QVBoxLayout()
        outer.addLayout(layout, stretch=1)

        layout.addWidget(QLabel("Tick the events to overlay (right), then press Compare. Each event is z-scored exactly as in Event PETH."))

        pre, post, bin_s = window or (get_window(ctx)[0], get_window(ctx)[1], 1.0)
        window_row = QHBoxLayout()
        window_row.addWidget(QLabel("Window — pre (s):"))
        self.e_pre = QLineEdit(f"{pre:g}")
        self.e_pre.setFixedWidth(50)
        window_row.addWidget(self.e_pre)
        window_row.addWidget(QLabel("post (s):"))
        self.e_post = QLineEdit(f"{post:g}")
        self.e_post.setFixedWidth(50)
        window_row.addWidget(self.e_post)
        window_row.addWidget(QLabel("bin (s):"))
        self.e_bin = QLineEdit(f"{bin_s:g}")
        self.e_bin.setFixedWidth(50)
        window_row.addWidget(self.e_bin)
        self.btn_compare = QPushButton("Compare")
        self.btn_compare.setDefault(True)
        self.btn_compare.clicked.connect(self._compare)
        window_row.addWidget(self.btn_compare)
        self.chk_sem = QCheckBox("SEM bands")
        self.chk_sem.setChecked(True)
        self.chk_sem.setToolTip("The shaded band around each average is its standard error across that event's trials.")
        self.chk_sem.toggled.connect(self._redraw)
        window_row.addWidget(self.chk_sem)
        window_row.addStretch(1)
        layout.addLayout(window_row)

        self.fig = figures.new_event_compare_figure()
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.editable_figure = EditableFigure(ctx, self, self.fig, self.canvas)        # the title is automatic, from the events compared, until one is typed there
        layout.addWidget(self.canvas, stretch=1)

        self.lbl_summary = QLabel("")
        self.lbl_summary.setFont(QFont("Consolas", 9))
        self.lbl_summary.setWordWrap(True)
        layout.addWidget(self.lbl_summary)

        btn_row = QHBoxLayout()
        add_stats_export_buttons(
            ctx, self, btn_row,
            get_clipboard_text=lambda: self.lbl_summary.text(),
            csv_default_name=lambda: f"EventCompare_{self.table_combo.currentData()}",
            csv_header=self._csv_header, get_csv_rows=self._csv_rows, provenance=self._provenance,
        )
        self.table_combo = QComboBox()
        for label, table in self.TABLES:
            self.table_combo.addItem(label, userData=table)
        self.table_combo.setToolTip("Which table Export CSV writes: every event's mean and SEM along the window, or the one-row-per-event summary.")
        btn_row.addWidget(self.table_combo)
        self.btn_export = QPushButton("Export Plot")
        self.btn_export.clicked.connect(
            lambda: export_figure_to_file(ctx, self.fig, "EventCompare", f"{len(self.events)}events", provenance=self._provenance()))
        btn_row.addWidget(self.btn_export)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        right = QVBoxLayout()
        right_widget = QWidget()
        right_widget.setLayout(right)
        right_widget.setFixedWidth(230)
        outer.addWidget(right_widget)
        right.addWidget(QLabel("Events"))
        pick_row = QHBoxLayout()
        for text, state in (("All", True), ("None", False)):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _checked=False, s=state: self._set_all_ticked(s))
            pick_row.addWidget(btn)
        right.addLayout(pick_row)
        self.event_list = QListWidget()
        wanted = set(initial_events)
        for name in sorted(groups):
            item = QListWidgetItem(f"{name}  ({len(groups[name])})", self.event_list)
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in wanted else Qt.CheckState.Unchecked)
        right.addWidget(self.event_list, stretch=1)

        self._redraw()
        if self._ticked():
            self._compare()

    # --- what is ticked, what was run

    def _ticked(self):
        return [self.event_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.event_list.count())
                if self.event_list.item(i).checkState() == Qt.CheckState.Checked]

    def _set_all_ticked(self, ticked):
        state = Qt.CheckState.Checked if ticked else Qt.CheckState.Unchecked
        for i in range(self.event_list.count()):
            self.event_list.item(i).setCheckState(state)

    def _read_window(self):
        default_pre, default_post = get_window(self.ctx)
        values = []
        for field, default, floor in ((self.e_pre, default_pre, 0.1), (self.e_post, default_post, 0.1), (self.e_bin, 1.0, 0.01)):
            try:
                values.append(max(floor, float(field.text())))
            except ValueError:
                values.append(default)
        return tuple(values)

    def _provenance(self):
        """What is on screen as an analyses.py event_compare: the events, the times each had, the window and the bin width."""
        return {"kind": "event_compare", "parameters": dict(self.params)} if self.params is not None else None

    def _compare(self):
        names = self._ticked()
        if not names:
            show_error(self.ctx, "Tick at least one event to compare.")
            return
        pre, post, bin_s = self._read_window()
        params = {"events": names, "event_groups": {n: [float(t) for t in self.groups[n]] for n in names},
                  "pre_s": float(pre), "post_s": float(post), "bin_s": float(bin_s)}
        errorlog.action("analysis", tool="Compare Events", events=names, pre_s=pre, post_s=post, bin_s=bin_s)
        self.btn_compare.setEnabled(False)

        def on_result(result):
            self.btn_compare.setEnabled(True)
            self.params, self.tables, self.notes = params, result.tables, list(result.notes)
            self.events = figures.compare_events_from_tables(result.tables) or []
            self.lbl_summary.setText(summary_text(result.tables["summary"], pre, post, bin_s))
            self.setWindowTitle(f"Compare Events — {len(self.events)} event(s) ({self.mode_str})")
            self._redraw()
            show_window_toast(self.ctx, f"Compared {len(self.events)} event(s)" + (f"; {self.notes[0]}" if self.notes else ""))

        def on_error(message):
            self.btn_compare.setEnabled(True)
            show_error(self.ctx, NEEDS_NEWER_LIBRARY if "Unknown analysis" in message and "event_compare" in message
                       else f"Compare Events failed: {message}")

        if request_analysis(self.ctx, "event_compare", params, on_result, label=f"Comparing {len(names)} event(s)", on_error=on_error) is None:
            self.btn_compare.setEnabled(True)

    # --- the figure and the CSV

    def _redraw(self):
        pre, post = (self.params["pre_s"], self.params["post_s"]) if self.params else self._read_window()[:2]
        figures.draw_event_compare(self.fig, events=self.events, pre=pre, post=post, signal_label=self.mode_str, show_sem=self.chk_sem.isChecked())
        self.editable_figure.drawn()

    def _csv_header(self):
        table = self.tables.get(self.table_combo.currentData())
        return [str(c) for c in table.columns] if table is not None else []

    def _csv_rows(self):
        """The rows of the chosen table as the other analysis windows write theirs: times to 4 decimals, the rest to 6 significant digits."""
        table = self.tables.get(self.table_combo.currentData())
        if table is None:
            return []
        rows = []
        for record in table.itertuples(index=False):
            row = []
            for column, value in zip(table.columns, record):
                if column == "Event":
                    row.append(value)
                elif column in ("Occurrences", "Trials", "n"):
                    row.append(int(value))
                elif column == "time_from_event_s":
                    row.append(f"{value:.4f}")
                else:
                    row.append(f"{value:.6g}")
            rows.append(row)
        return rows


def launch_event_compare(ctx, initial_events=(), window=None):
    """Opens Compare Events as a tab. `initial_events` are ticked and compared at once; `window` is (pre, post, bin) in
    seconds, the analysis window setting if left out."""
    if ctx.cache is None or ctx.cache.get('source') != 'TDT':
        show_error(ctx, "Compare Events is only available for TDT data.")
        return
    groups = api.markers.group_by_name(ctx.cache, ctx.store_labels)
    if not groups:
        show_error(ctx, "No events found in this recording.")
        return
    dlg = _EventCompareDialog(ctx.win, ctx, groups, initial_events, window)
    present(ctx, dlg, "Compare Events")
