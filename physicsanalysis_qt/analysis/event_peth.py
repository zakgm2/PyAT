"""
analysis/event_peth.py
-------------------------
GuPPy-style event-triggered PETH: pick one event/marker name, Z-score
every occurrence of it against its own pre-event baseline, stack every
trial as a row in a heatmap (so trial-to-trial consistency is visible
at a glance), and plot either the trial-averaged trace or (View:
Trials) every checked trial's own trace overlaid, color-coded, below
it. TDT-only — event markers are a TDT-specific concept elsewhere in
this app too.

Distinct from peth.py's launch_zscore_peth, which analyzes a single
arbitrary clicked point rather than every occurrence of a named event.
"""

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.ticker import MaxNLocator
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QWidget, QButtonGroup,
)

import PhysicsLibrary as pl

from ..background import run_in_background
from ..context import get_normalized_signal, signal_short_label
from ..fonts import fig_font_sizes
from ..marker_labels import marker_display_label
from ..toasts import show_error, show_window_toast
from .dispatch import add_stats_export_buttons, export_figure_to_file, get_window
from ..window_fit import fit_to_screen

# Cycled (modulo) across trials in the "Trials" overlay view — tab10 +
# tab20's paler companions, same categorical-palette idea as plotting.py's
# _GEN_COLORS for Generic-source channels, just a longer list since trial
# counts run higher than typical column counts.
_TRIAL_COLORS = [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
    '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
    '#aec7e8', '#ffbb78', '#98df8a', '#ff9896', '#c5b0d5',
]


def _group_markers_by_name(ctx):
    """{display_name: [sorted event times]} across every event TDT
    actually detected in this recording (ctx.cache['detected_markers']),
    plus anything manually placed or already added to the plot
    (ctx.cache['markers']) — deduped by (name, time) so a marker that's
    both detected and already plotted doesn't get double-counted. This
    intentionally does NOT require an event to already be on the plot:
    the whole point is finding out which event types are worth plotting
    in the first place. High/low phase markers count as separate event
    names (their display label already differs by the ¹/⁰ suffix)."""
    groups = {}
    seen = set()
    for m in ctx.cache.get('detected_markers', []) + ctx.cache['markers']:
        name = marker_display_label(ctx, m)
        key = (name, m['time'])
        if key in seen:
            continue
        seen.add(key)
        groups.setdefault(name, []).append(m['time'])
    for name in groups:
        groups[name].sort()
    return groups


class _EventPethResultsDialog(QDialog):
    """Stays open across event switches — picking a different event from
    the combo re-runs the computation in place instead of requiring you
    to close this and reopen a separate picker dialog."""

    SORT_TRIAL_ORDER = "Trial order"
    SORT_PEAK_AMPLITUDE = "Peak amplitude"

    def __init__(self, parent, ctx, groups, initial_event_name):
        super().__init__(parent)
        self.ctx = ctx
        self.groups = groups
        self.event_name = initial_event_name
        self.peth_result = None
        self.per_trial_auc = []
        self.last_group_auc = None
        self.per_trial_peri = []
        self.last_group_peri = None
        self.last_mean_trace = None
        self.bin_width = 1.0  # snapshotted from the live field in _run() — see _bin_width()'s docstring
        self.active_view = "zscore"  # "zscore" | "trials" | "auc" | "peak" | "bins" — which overlay/export is active
        self._colorbar = None

        self.setWindowTitle("Event PETH")
        fit_to_screen(self, 940, 720)
        outer = QHBoxLayout(self)

        left = QVBoxLayout()
        outer.addLayout(left, stretch=1)
        layout = left

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Event:"))
        self.combo_event = QComboBox()
        for name in sorted(groups.keys()):
            self.combo_event.addItem(f"{name}  ({len(groups[name])} occurrences)", userData=name)
        self.combo_event.setCurrentIndex(self.combo_event.findData(initial_event_name))
        self.combo_event.currentIndexChanged.connect(self._on_event_changed)
        top_row.addWidget(self.combo_event, stretch=1)

        self.lbl_trials = QLabel("")
        top_row.addWidget(self.lbl_trials)

        top_row.addWidget(QLabel("Row order:"))
        self.sort_combo = QComboBox()
        self.sort_combo.addItems([self.SORT_TRIAL_ORDER, self.SORT_PEAK_AMPLITUDE])
        self.sort_combo.currentTextChanged.connect(self._redraw)
        top_row.addWidget(self.sort_combo)
        layout.addLayout(top_row)

        window_row = QHBoxLayout()
        window_row.addWidget(QLabel("Window — pre (s):"))
        self.e_pre = QLineEdit(str(int(ctx.window_pre or get_window(ctx)[0])))
        self.e_pre.setFixedWidth(50)
        window_row.addWidget(self.e_pre)
        window_row.addWidget(QLabel("post (s):"))
        self.e_post = QLineEdit(str(int(ctx.window_post or get_window(ctx)[1])))
        self.e_post.setFixedWidth(50)
        window_row.addWidget(self.e_post)
        window_row.addWidget(QLabel("bin (s):"))
        self.e_bin = QLineEdit("1.0")
        self.e_bin.setFixedWidth(50)
        window_row.addWidget(self.e_bin)
        btn_recalc = QPushButton("Recalculate")
        btn_recalc.clicked.connect(lambda: self._run(self.event_name))
        window_row.addWidget(btn_recalc)
        window_row.addStretch(1)
        layout.addLayout(window_row)

        # View toggles — mutually exclusive, control both what's overlaid
        # on ax_line below and what the shared Export CSV/Copy buttons
        # produce (see _redraw and the *_csv_rows/_csv_header_* dispatch
        # methods). Z-Score is the plain baseline (just the trace itself,
        # no derived stat) and is the default on open.
        view_row = QHBoxLayout()
        view_row.addWidget(QLabel("View:"))
        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self._view_buttons = {}
        for view_id, label in [("zscore", "Z-Score"), ("trials", "Trials"), ("auc", "AUC"),
                                ("peak", "Peak"), ("bins", "Bins")]:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.toggled.connect(lambda checked, v=view_id: self._on_view_toggled(v, checked))
            self.view_group.addButton(btn)
            self._view_buttons[view_id] = btn
            view_row.addWidget(btn)
        self._view_buttons["zscore"].setChecked(True)
        view_row.addStretch(1)
        layout.addLayout(view_row)

        self.fig = Figure(figsize=(8, 7), dpi=100)
        self.ax_heat, self.ax_line = self.fig.subplots(
            2, 1, sharex=True, gridspec_kw={'height_ratios': [2, 1]}
        )
        self.canvas = FigureCanvasQTAgg(self.fig)
        layout.addWidget(self.canvas, stretch=1)

        self.lbl_group = QLabel("")
        self.lbl_group.setFont(QFont("Consolas", 9))
        self.lbl_group.setWordWrap(True)  # Bins' summary text is one line per bin —
        # without this, Qt sizes (and stretches) the whole dialog to fit it on one
        # line instead of wrapping, fighting any manual resize.
        layout.addWidget(self.lbl_group)

        btn_row = QHBoxLayout()
        add_stats_export_buttons(
            ctx, self, btn_row,
            get_clipboard_text=self._current_clipboard_text,
            csv_default_name=lambda: f"EventPETH_{self.event_name}_{self.active_view}",
            csv_header=self._current_csv_header,
            get_csv_rows=self._current_csv_rows,
        )
        self.btn_export = QPushButton("Export Plot")
        self.btn_export.clicked.connect(
            lambda: export_figure_to_file(ctx, self.fig, "EventPETH", self.event_name)
        )
        btn_row.addWidget(self.btn_export)
        layout.addLayout(btn_row)

        # Right side: per-trial include/exclude checklist — no automatic
        # rejection (std/threshold cutoffs), just a manual way to drop a
        # trial that looks contaminated (movement, a marker that fired on
        # a false trigger, ...) from the heatmap and mean/SEM trace without
        # having to change the event or window. Rebuilt fresh (all checked)
        # every time _run() computes a new trial set, since checkbox state
        # tied to a row index wouldn't mean anything for a different event
        # or window's trial count. Per-trial AUC/Peak/Latency/Mean-Time-
        # Bins are computed here too (see _populate_trial_list) but stay
        # export-only — the CSV/Copy buttons above are the actual way to
        # see them, not this list.
        right = QVBoxLayout()
        right_widget = QWidget()
        right_widget.setLayout(right)
        right_widget.setFixedWidth(180)
        outer.addWidget(right_widget)

        right.addWidget(QLabel("Trials"))
        trial_btn_row = QHBoxLayout()
        btn_select_all = QPushButton("All")
        btn_select_all.clicked.connect(lambda: self._set_all_trials_checked(True))
        trial_btn_row.addWidget(btn_select_all)
        btn_select_none = QPushButton("None")
        btn_select_none.clicked.connect(lambda: self._set_all_trials_checked(False))
        trial_btn_row.addWidget(btn_select_none)
        right.addLayout(trial_btn_row)

        self.trial_list = QListWidget()
        self.trial_list.itemChanged.connect(self._redraw)
        right.addWidget(self.trial_list, stretch=1)

        self._run(initial_event_name)

    def _on_view_toggled(self, view_id, checked):
        # QButtonGroup fires toggled(False) for the outgoing button and
        # toggled(True) for the incoming one on every switch — only act
        # on the incoming one, or this would redraw twice per click (once
        # with a stale view_id) and briefly set active_view to the wrong
        # value in between.
        if not checked:
            return
        self.active_view = view_id
        self._redraw()

    def _on_event_changed(self):
        name = self.combo_event.currentData()
        if name and name != self.event_name:
            self._run(name)

    def _read_window(self):
        default_pre, default_post = get_window(self.ctx)
        try:
            pre = max(0.1, float(self.e_pre.text()))
        except ValueError:
            pre = default_pre
        try:
            post = max(0.1, float(self.e_post.text()))
        except ValueError:
            post = default_post
        return pre, post

    def _run(self, event_name):
        ctx = self.ctx
        self.event_name = event_name
        self.combo_event.setEnabled(False)

        event_times = self.groups[event_name]
        self.pre, self.post = self._read_window()
        # Snapshotted here (not re-read live in _redraw) so the per-trial
        # bins computed below and the group bins _redraw() computes later
        # always agree on bin width, even if the user edits the field
        # without clicking Recalculate in between — see _bin_width().
        self.bin_width = self._bin_width()
        key, _, data_source, _ = get_normalized_signal(ctx)
        self.mode_str = signal_short_label(key)
        time_array = ctx.cache['x']
        fs = ctx.cache['fs']
        pre, post = self.pre, self.post

        def _work(progress):
            plan = pl.Plan(progress, [("Smoothing the signal", 10), ("Aligning trials", 90)])
            plan.begin("Smoothing the signal")
            clean_signal = pl.smooth_signal(data_source, fs)
            return pl.compute_event_zscore_peth(time_array, clean_signal, event_times, pre, post,
                                                progress=plan.sub("Aligning trials"))

        def _on_success(result):
            self.combo_event.setEnabled(True)
            if result["trial_matrix"].shape[0] == 0:
                show_error(ctx, f"No usable trials for '{event_name}' — all occurrences were "
                                 f"too close to the start/end of the recording for the current window.")
                return
            self.peth_result = result
            self._populate_trial_list(result)
            self.setWindowTitle(f"Event PETH — {event_name} ({self.mode_str})")
            show_window_toast(ctx, f"Event PETH: {result['trial_matrix'].shape[0]} trial(s) for '{event_name}'")
            self._redraw()

        def _on_error(msg):
            self.combo_event.setEnabled(True)
            show_error(ctx, f"Event PETH failed: {msg}")

        run_in_background(ctx, _work, _on_success, _on_error, label=f"Computing Event PETH for '{event_name}'")

    def _populate_trial_list(self, result):
        """Rebuild the trial checklist (all checked) for a freshly computed
        trial set — called once per _run(), never mutated in place, since
        checkbox state tied to a row index wouldn't carry over correctly
        to a different event or window's trial count.

        Per-trial AUC/peri-event stats are computed once here (independent
        of which trials end up checked) rather than in _redraw — unlike
        the group versions, an individual trial's own stats don't change
        based on what else is checked, so there's no reason to recompute
        them on every checkbox toggle. Kept export-only (see the AUC/
        Peak-Latency/Bins buttons above) rather than shown in this list."""
        self.per_trial_auc = pl.compute_auc_matrix(
            result["time_axis"], result["trial_matrix"])["per_trial"]
        self.per_trial_peri = pl.compute_peri_event_matrix(
            result["time_axis"], result["trial_matrix"], self.post, self.bin_width)["per_trial"]

        self.trial_list.blockSignals(True)
        self.trial_list.clear()
        for i, t in enumerate(result["trial_event_times"]):
            item = QListWidgetItem(f"Trial {i + 1} — {t:.2f}s")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.trial_list.addItem(item)
        self.trial_list.blockSignals(False)

    def _bin_width(self):
        """Reads the live "bin (s):" field — only called from _run(), which
        snapshots the result into self.bin_width. Every other bin
        computation (per-trial in _populate_trial_list, group in _redraw)
        reads self.bin_width instead of this directly, so an edit to the
        field doesn't silently desync per-trial bins from the group's
        until the next Recalculate."""
        try:
            return max(0.01, float(self.e_bin.text()))
        except ValueError:
            return 1.0

    def _bin_edges(self):
        """Bin edges shared by every trial + the group row — all computed
        from the same self.post/self.bin_width, so column count/labels stay
        consistent across the whole CSV regardless of which row it's for.
        Falls back to the group's own bins (set any time _redraw ran) if
        no trial exists yet to read them from."""
        if self.per_trial_peri:
            return self.per_trial_peri[0]["mean_bins"]
        if self.last_group_peri is not None:
            return self.last_group_peri["mean_bins"]
        return []

    # --- view dispatch: the single Export/Copy button pair delegates to
    # whichever of these matches self.active_view (set by the toggle row) ---

    def _current_csv_header(self):
        return {"zscore": self._csv_header_zscore, "trials": self._csv_header_trials,
                "auc": self._csv_header_auc, "peak": self._csv_header_peak,
                "bins": self._csv_header_bins}[self.active_view]()

    def _current_csv_rows(self):
        return {"zscore": self._zscore_csv_rows, "trials": self._trials_csv_rows,
                "auc": self._auc_csv_rows, "peak": self._peak_csv_rows,
                "bins": self._bins_csv_rows}[self.active_view]()

    def _current_clipboard_text(self):
        return self.lbl_group.text()

    def _csv_header_zscore(self):
        return ["time_from_event_s", "z_score"]

    def _zscore_csv_rows(self):
        if self.peth_result is None or self.last_mean_trace is None:
            return []
        time_axis = self.peth_result["time_axis"]
        return [[f"{t:.4f}", f"{z:.6g}"] for t, z in zip(time_axis, self.last_mean_trace)]

    def _csv_header_trials(self):
        return ["Trial", "Trial Event Time (s)", "time_from_event_s", "z_score"]

    def _trials_csv_rows(self):
        # Exactly the traces currently drawn (checked trials only) — unlike
        # AUC/Peak/Bins there's no group aggregate row here, since the
        # whole point of this view is the individual traces, not a stat
        # derived from them.
        if self.peth_result is None:
            return []
        time_axis = self.peth_result["time_axis"]
        matrix = self.peth_result["trial_matrix"]
        trial_times = self.peth_result["trial_event_times"]
        rows = []
        for i in self._selected_trial_indices():
            for t, z in zip(time_axis, matrix[i]):
                rows.append([i + 1, f"{trial_times[i]:.4f}", f"{t:.4f}", f"{z:.6g}"])
        return rows

    def _csv_header_auc(self):
        return ["Trial", "Trial Event Time (s)", "Total AUC", "Positive AUC", "Negative AUC", "Checked"]

    def _auc_csv_rows(self):
        if self.peth_result is None:
            return []
        checked = set(self._selected_trial_indices())
        rows = []
        for i, t in enumerate(self.peth_result["trial_event_times"]):
            a = self.per_trial_auc[i]
            rows.append([i + 1, f"{t:.4f}", f"{a['total_auc']:.6g}",
                         f"{a['positive_auc']:.6g}", f"{a['negative_auc']:.6g}", i in checked])
        g = self.last_group_auc if self.last_group_auc is not None else \
            {"total_auc": 0.0, "positive_auc": 0.0, "negative_auc": 0.0}
        rows.append(["GROUP (checked only)", "", f"{g['total_auc']:.6g}",
                     f"{g['positive_auc']:.6g}", f"{g['negative_auc']:.6g}", ""])
        return rows

    def _csv_header_peak(self):
        return ["Trial", "Trial Event Time (s)", "Peak Amplitude", "Time-to-Peak (s)", "Checked"]

    def _peak_csv_rows(self):
        if self.peth_result is None:
            return []
        checked = set(self._selected_trial_indices())
        rows = []
        for i, t in enumerate(self.peth_result["trial_event_times"]):
            p = self.per_trial_peri[i]
            rows.append([i + 1, f"{t:.4f}", f"{p['peak_amplitude']:.6g}",
                         f"{p['latency']:.6g}", i in checked])
        gp = self.last_group_peri if self.last_group_peri is not None else \
            {"peak_amplitude": 0.0, "latency": 0.0}
        rows.append(["GROUP (checked only)", "", f"{gp['peak_amplitude']:.6g}",
                     f"{gp['latency']:.6g}", ""])
        return rows

    def _csv_header_bins(self):
        header = ["Trial", "Trial Event Time (s)"]
        header += [f"Bin {b['bin_start']:.1f}-{b['bin_end']:.1f}s Mean" for b in self._bin_edges()]
        header.append("Checked")
        return header

    def _bins_csv_rows(self):
        if self.peth_result is None:
            return []
        checked = set(self._selected_trial_indices())
        n_bins = len(self._bin_edges())
        rows = []
        for i, t in enumerate(self.peth_result["trial_event_times"]):
            p = self.per_trial_peri[i]
            row = [i + 1, f"{t:.4f}"] + [f"{b['mean']:.6g}" for b in p["mean_bins"]]
            row.append(i in checked)
            rows.append(row)
        gp = self.last_group_peri if self.last_group_peri is not None else {"mean_bins": []}
        # gp['mean_bins'] is legitimately [] when 0 trials are checked
        # (nothing to compute bins from) — pad to n_bins so this row still
        # lines up under the header's fixed bin columns either way.
        bin_means = [f"{b['mean']:.6g}" for b in gp["mean_bins"]]
        group_row = ["GROUP (checked only)", ""] + bin_means + [""] * (n_bins - len(bin_means))
        group_row.append("")
        rows.append(group_row)
        return rows

    def _group_bins_summary_text(self):
        gp = self.last_group_peri
        if not gp or not gp.get("mean_bins"):
            return ""
        return "Group Mean Time Bins — " + "  ".join(
            f"{b['bin_start']:.1f}-{b['bin_end']:.1f}s: {b['mean']:.2f}" for b in gp["mean_bins"]
        )

    def _set_all_trials_checked(self, checked):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.trial_list.blockSignals(True)
        for i in range(self.trial_list.count()):
            self.trial_list.item(i).setCheckState(state)
        self.trial_list.blockSignals(False)
        self._redraw()

    def _selected_trial_indices(self):
        return [i for i in range(self.trial_list.count())
                if self.trial_list.item(i).checkState() == Qt.CheckState.Checked]

    def _row_order(self, sub_matrix):
        n = sub_matrix.shape[0]
        if self.sort_combo.currentText() == self.SORT_PEAK_AMPLITUDE:
            peak = np.abs(sub_matrix).max(axis=1) if n else np.array([])
            return np.argsort(peak)[::-1]
        return np.arange(n)

    def _redraw(self):
        if self.peth_result is None:
            return
        result = self.peth_result
        time_axis = result["time_axis"]
        matrix = result["trial_matrix"]

        # Mean/SEM recomputed here from just the checked trials — not
        # result["mean_trace"]/["sem_trace"], which cover every usable
        # trial regardless of the checklist. pl.compute_group_stats uses
        # the same formula compute_event_zscore_peth() uses internally
        # for its own full-trial-set mean/SEM (ddof=1, zero SEM if <2
        # trials, zero mean+SEM if 0 trials).
        selected = self._selected_trial_indices()
        sub_matrix = matrix[selected] if selected else matrix[:0]
        n_total = matrix.shape[0]
        n_selected = sub_matrix.shape[0]
        mean_trace, sem_trace = pl.compute_group_stats(sub_matrix)

        self.lbl_trials.setText(f"{n_selected} of {n_total} trial(s)")
        self.last_mean_trace = mean_trace

        # Both group stats are kept up to date every redraw regardless of
        # which view is active — switching to AUC/Peak/Bins and exporting
        # immediately must reflect the current trial selection, not
        # whatever was last computed while that view happened to be active.
        self.last_group_auc = pl.compute_auc_from_trace(time_axis, mean_trace) if n_selected > 0 else \
            {"total_auc": 0.0, "positive_auc": 0.0, "negative_auc": 0.0}
        g = self.last_group_auc

        self.last_group_peri = pl.compute_peri_event_from_trace(
            time_axis, mean_trace, self.post, self.bin_width) if n_selected > 0 else \
            {"peak_amplitude": 0.0, "latency": 0.0, "mean_bins": []}
        gp = self.last_group_peri

        if self.active_view == "auc":
            self.lbl_group.setText(
                f"Group AUC — total: {g['total_auc']:.2f}  +: {g['positive_auc']:.2f}  "
                f"-: {g['negative_auc']:.2f}  (n={n_selected})"
            )
        elif self.active_view == "peak":
            self.lbl_group.setText(
                f"Group Peak: {gp['peak_amplitude']:.2f} @ +{gp['latency']:.2f}s  (n={n_selected})"
            )
        elif self.active_view == "bins":
            self.lbl_group.setText(self._group_bins_summary_text() or f"(n={n_selected})")
        elif self.active_view == "trials":
            self.lbl_group.setText(f"Individual trial Z-Score traces — {n_selected} of {n_total} trial(s)")
        else:  # zscore
            self.lbl_group.setText(f"Group Z-Score trace — {n_selected} of {n_total} trial(s)")

        # Must remove the colorbar before clearing ax_heat — it restores
        # ax_heat's original (pre-colorbar) subplot geometry on removal,
        # which breaks if ax_heat's state has already changed underneath it.
        if self._colorbar is not None:
            self._colorbar.remove()
            self._colorbar = None
        self.ax_heat.clear()
        self.ax_line.clear()

        if n_selected == 0:
            self.ax_heat.text(0.5, 0.5, "No trials selected",
                               ha='center', va='center', transform=self.ax_heat.transAxes)
        else:
            order = self._row_order(sub_matrix)
            # Scaled to this trial set's own spread rather than a fixed range, so a quiet
            # recording isn't washed out and a big responder isn't clipped.
            scale = np.nanpercentile(np.abs(sub_matrix), 98) or 1.0
            im = self.ax_heat.imshow(
                sub_matrix[order], aspect='auto', cmap='YlGnBu_r',
                extent=[-self.pre, self.post, n_selected, 0],
                vmin=-scale, vmax=scale, interpolation='nearest',
            )
            self._colorbar = self.fig.colorbar(im, ax=self.ax_heat, fraction=0.046, pad=0.04, label="Z-score")

        tfs, lfs, _ = fig_font_sizes(self.fig)
        self.ax_heat.set_ylabel("Trial", fontweight='bold', fontsize=lfs)
        # Trial rows are a count, not a continuous quantity — matplotlib's
        # default locator can otherwise land on fractional ticks (e.g. 2.5)
        # for small trial counts, which reads as meaningless for "Trial".
        self.ax_heat.yaxis.set_major_locator(MaxNLocator(integer=True))
        self.ax_heat.axvline(0, color='red', linestyle='--', alpha=0.7)

        if self.active_view == "trials":
            # Every checked trial's own trace, no mean/SEM — a different
            # color per trial (cycled if there are more trials than
            # colors), so trial-to-trial shape/timing differences are
            # visible directly instead of collapsed into one average.
            for local_i, orig_i in enumerate(selected):
                self.ax_line.plot(time_axis, matrix[orig_i],
                                   color=_TRIAL_COLORS[local_i % len(_TRIAL_COLORS)],
                                   linewidth=1.0, alpha=0.85)
        else:
            self.ax_line.plot(time_axis, mean_trace, color='black', linewidth=1.5, label="Mean")
            self.ax_line.fill_between(time_axis, mean_trace - sem_trace, mean_trace + sem_trace,
                                        color='black', alpha=0.2, label="SEM")
        self.ax_line.axvline(0, color='red', linestyle='--', alpha=0.7)

        # View-specific overlay for the group trace — only the active
        # toggle's overlay is drawn, matching what Export CSV currently
        # produces (see _current_csv_rows). "zscore" (the baseline view)
        # deliberately adds nothing beyond the mean/SEM trace above.
        if n_selected > 0:
            if self.active_view == "auc":
                self.ax_line.fill_between(time_axis, mean_trace, 0, where=(mean_trace >= 0),
                                           color='green', alpha=0.25)
                self.ax_line.fill_between(time_axis, mean_trace, 0, where=(mean_trace <= 0),
                                           color='red', alpha=0.25)
            elif self.active_view == "peak":
                self.ax_line.axvline(gp["latency"], color='gray', lw=1.0, linestyle=':', alpha=0.7)
                self.ax_line.scatter([gp["latency"]], [gp["peak_amplitude"]],
                                      color='red', zorder=5, s=35, label="Peak")
            elif self.active_view == "bins":
                for b in gp["mean_bins"]:
                    self.ax_line.axvline(b["bin_start"], color='gray', lw=0.5, alpha=0.3)

        self.ax_line.set_xlim([-self.pre, self.post])
        self.ax_line.set_ylabel(f"Z-Score ({self.mode_str})", fontweight='bold', fontsize=lfs)
        self.ax_line.set_xlabel("Time from Event (s)", fontweight='bold', fontsize=lfs)
        if self.active_view != "trials":
            # Trials view has no labeled artists (a legend entry per trial
            # would be unreadable past a handful of trials) — color is
            # identified via the trial list on the right instead.
            self.ax_line.legend(fontsize=lfs * 0.8, loc='upper right')

        self.fig.suptitle(f"Event PETH — {self.event_name}", fontsize=tfs, fontweight='bold')
        self.fig.tight_layout(rect=[0, 0, 1, 0.96])
        self.canvas.draw_idle()


def launch_event_peth(ctx):
    if ctx.cache is None or ctx.cache.get('source') != 'TDT':
        show_error(ctx, "Event PETH is only available for TDT data.")
        return

    groups = _group_markers_by_name(ctx)
    if not groups:
        show_error(ctx, "No events found in this recording.")
        return

    initial_name = sorted(groups.keys())[0]
    dlg = _EventPethResultsDialog(ctx.win, ctx, groups, initial_name)
    dlg.exec()
