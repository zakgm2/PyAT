"""
analysis/peak_finder.py
--------------------------
Auto-detect statistically significant peaks in the loaded signal
(PhysicsLibrary's find_significant_peaks / find_peak_near_events), for
when the externally-supplied event markers (TDT epocs, manually placed
markers) don't actually line up with where the neural signal itself is
doing something. Three scopes:
  - Whole recording: blind peak-finding with no relation to markers.
  - One specific event: is there a real peak near this one occurrence?
  - All events with a name: check alignment across every occurrence of
    an event type, so you can see whether it's consistent or not.
Peaks found in the two event-scoped modes are reported with latency
relative to the event; all detected peaks (any scope) are added as
markers so they work with the rest of the marker system, including
Event PETH.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QCheckBox,
    QPushButton, QMessageBox, QComboBox, QStackedWidget, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView,
)

import PhysicsLibrary as pl

from ..background import run_in_background
from ..context import get_normalized_signal
from ..marker_labels import marker_display_label
from ..toasts import show_error, show_window_toast
from .dispatch import add_stats_export_buttons, get_window
from .event_peth import _group_markers_by_name
from ..window_fit import fit_to_screen

_AUTO_PEAK_COLOR = "magenta"
_MANY_PEAKS_WARNING = 300

SCOPE_WHOLE = "Whole recording"
SCOPE_ONE_EVENT = "One specific event"
SCOPE_ALL_SAME_NAME = "All events with a chosen name"
SCOPE_SCAN_ALL_TYPES = "Scan every event type at once"


class _PeakFinderDialog(QDialog):
    @staticmethod
    def _all_known_markers(ctx):
        """Every event TDT detected plus anything manually placed/already
        plotted, deduped by (time, label) — same source as
        _group_markers_by_name, so this list isn't limited to what's
        currently on the plot."""
        seen = set()
        markers = []
        for m in ctx.cache.get('detected_markers', []) + ctx.cache['markers']:
            key = (m['time'], m.get('label'), m.get('store'), m.get('phase'))
            if key in seen:
                continue
            seen.add(key)
            markers.append(m)
        markers.sort(key=lambda m: m['time'])
        return markers

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Find Significant Peaks")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            "Z-scores the signal and marks local peaks at or above the threshold —\n"
            "either blindly across the whole recording, or checked against your\n"
            "existing event markers to see if a real response actually lines up."
        ))

        row_scope = QHBoxLayout()
        row_scope.addWidget(QLabel("Scope:"))
        self.combo_scope = QComboBox()
        self.combo_scope.addItems([SCOPE_SCAN_ALL_TYPES, SCOPE_ALL_SAME_NAME, SCOPE_ONE_EVENT, SCOPE_WHOLE])
        self.combo_scope.currentTextChanged.connect(self._on_scope_changed)
        row_scope.addWidget(self.combo_scope, stretch=1)
        layout.addLayout(row_scope)

        self.markers = self._all_known_markers(ctx) if ctx.cache else []
        self.groups = _group_markers_by_name(ctx) if ctx.cache else {}

        self.stack = QStackedWidget()
        self._scope_pages = {}

        self._scope_pages[SCOPE_SCAN_ALL_TYPES] = self.stack.addWidget(QWidget())
        self._scope_pages[SCOPE_WHOLE] = self.stack.addWidget(QWidget())

        one_event_widget = QWidget()
        one_event_layout = QHBoxLayout(one_event_widget)
        one_event_layout.setContentsMargins(0, 0, 0, 0)
        one_event_layout.addWidget(QLabel("Event:"))
        self.combo_one_event = QComboBox()
        for i, m in enumerate(self.markers):
            name = marker_display_label(ctx, m)
            self.combo_one_event.addItem(f"{name}  @ {m['time']:.2f}s", userData=i)
        one_event_layout.addWidget(self.combo_one_event, stretch=1)
        self._scope_pages[SCOPE_ONE_EVENT] = self.stack.addWidget(one_event_widget)

        all_same_widget = QWidget()
        all_same_layout = QHBoxLayout(all_same_widget)
        all_same_layout.setContentsMargins(0, 0, 0, 0)
        all_same_layout.addWidget(QLabel("Event:"))
        self.combo_event_name = QComboBox()
        for name in sorted(self.groups.keys()):
            self.combo_event_name.addItem(f"{name}  ({len(self.groups[name])} occurrences)", userData=name)
        all_same_layout.addWidget(self.combo_event_name, stretch=1)
        self._scope_pages[SCOPE_ALL_SAME_NAME] = self.stack.addWidget(all_same_widget)

        layout.addWidget(self.stack)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Z-score threshold:"))
        self.spin_z = QDoubleSpinBox()
        self.spin_z.setRange(0.5, 20.0)
        self.spin_z.setSingleStep(0.25)
        # 5 = the usual five-sigma convention. Each event's window is searched for
        # its LARGEST z, so a low threshold "finds" a response by chance in most
        # windows: on a real recording random pseudo-events got one 58% of the
        # time at 2.5, 40% at 3, 21% at 4 and 10% at 5 (5 s baseline, 10 s window).
        self.spin_z.setValue(5.0)
        self.spin_z.setToolTip(
            "How many standard deviations a peak must reach to count. Default 5.\n"
            "Lower values find a \"response\" by chance in most event windows\n"
            "(on a real recording, random events got one 58% of the time at 2.5, 10% at 5)."
        )
        row1.addWidget(self.spin_z)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.lbl_dist = QLabel("Minimum spacing (s):")
        row2.addWidget(self.lbl_dist)
        self.spin_dist = QDoubleSpinBox()
        self.spin_dist.setRange(0.05, 300.0)
        self.spin_dist.setSingleStep(0.5)
        self.spin_dist.setValue(1.0)
        row2.addWidget(self.spin_dist)
        layout.addLayout(row2)

        self.cb_troughs = QCheckBox("Also consider negative dips (troughs)")
        layout.addWidget(self.cb_troughs)

        btn_row = QHBoxLayout()
        btn_run = QPushButton("Find Peaks")
        btn_run.setDefault(True)
        btn_run.clicked.connect(self._accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_run)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        self._on_scope_changed(self.combo_scope.currentText())

    def _on_scope_changed(self, scope):
        self.stack.setCurrentIndex(self._scope_pages[scope])
        # Spacing between peaks only makes sense scanning the whole
        # recording — event-scoped modes look at one window per event.
        is_whole = scope == SCOPE_WHOLE
        self.lbl_dist.setVisible(is_whole)
        self.spin_dist.setVisible(is_whole)

    def _accept(self):
        scope = self.combo_scope.currentText()
        if scope == SCOPE_ONE_EVENT and not self.markers:
            show_error(self.ctx, "No markers on the plot to pick from.")
            return
        if scope in (SCOPE_ALL_SAME_NAME, SCOPE_SCAN_ALL_TYPES) and not self.groups:
            show_error(self.ctx, "No markers on the plot to pick from.")
            return
        self.scope = scope
        self.z_threshold = self.spin_z.value()
        self.min_distance = self.spin_dist.value()
        self.include_troughs = self.cb_troughs.isChecked()
        if self.scope == SCOPE_ONE_EVENT:
            idx = self.combo_one_event.currentData()
            m = self.markers[idx]
            self.event_name = marker_display_label(self.ctx, m)
            self.event_times = [m['time']]
        elif self.scope == SCOPE_ALL_SAME_NAME:
            self.event_name = self.combo_event_name.currentData()
            self.event_times = self.groups[self.event_name]
        else:
            self.event_name = None
            self.event_times = None
        self.accept()


class _AlignmentResultsDialog(QDialog):
    """Per-event found/not-found + latency table for the two event-scoped modes."""

    def __init__(self, parent, ctx, event_name, results):
        super().__init__(parent)
        self.setWindowTitle(f"Peak Alignment — {event_name}")
        fit_to_screen(self, 500, 400)
        layout = QVBoxLayout(self)

        n_found = sum(1 for r in results if r["found"])
        summary = f"{n_found} / {len(results)} event(s) had a peak at or above threshold."
        layout.addWidget(QLabel(summary))

        table = QTableWidget(len(results), 4)
        table.setHorizontalHeaderLabels(["Event Time (s)", "Found?", "Latency (s)", "Z-score"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        for row, r in enumerate(results):
            table.setItem(row, 0, QTableWidgetItem(f"{r['event_time']:.2f}"))
            table.setItem(row, 1, QTableWidgetItem("Yes" if r["found"] else "No"))
            table.setItem(row, 2, QTableWidgetItem(f"{r['latency']:.2f}" if r["found"] else "--"))
            table.setItem(row, 3, QTableWidgetItem(f"{r['z_score']:.2f}" if r["found"] else "--"))
        layout.addWidget(table)

        btn_row = QHBoxLayout()
        add_stats_export_buttons(
            ctx, self, btn_row,
            get_clipboard_text=lambda: summary,
            csv_default_name=f"PeakAlignment_{event_name}",
            csv_header=["Event Time (s)", "Found", "Latency (s)", "Z-score"],
            get_csv_rows=lambda: [
                [f"{r['event_time']:.4f}", r['found'],
                 f"{r['latency']:.4f}" if r['found'] else "",
                 f"{r['z_score']:.4f}" if r['found'] else ""]
                for r in results
            ],
        )
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)


def _add_peak_markers(ctx, entries):
    """entries: list of (time, kind) tuples."""
    for t, kind in entries:
        label = "AutoPeak" if kind == "peak" else "AutoTrough"
        ctx.cache['markers'].append({
            "time": t, "label": label, "color": _AUTO_PEAK_COLOR, "fontsize": 8,
        })


class _ScanAllTypesResultsDialog(QDialog):
    """One row per event name, sorted by hit rate — lets you see at a
    glance which event types actually correspond to a real signal
    response before choosing what (if anything) to add to the plot."""

    def __init__(self, parent, ctx, by_event):
        super().__init__(parent)
        self.ctx = ctx
        self.by_event = by_event  # {name: [result dicts]}
        self.setWindowTitle("Peak Scan — All Event Types")
        fit_to_screen(self, 650, 420)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            "How many occurrences of each event type had an aligned peak. Higher hit\n"
            "rate / z-score means that event is more likely tied to a real response."
        ))

        self.rows = sorted(
            by_event.items(),
            key=lambda kv: (sum(r["found"] for r in kv[1]) / len(kv[1])) if kv[1] else 0,
            reverse=True,
        )

        table = QTableWidget(len(self.rows), 5)
        table.setHorizontalHeaderLabels(
            ["Event", "Occurrences", "Found", "Hit Rate", "Avg Z (found only)"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        for row, (name, results) in enumerate(self.rows):
            n_total = len(results)
            found = [r for r in results if r["found"]]
            hit_rate = len(found) / n_total if n_total else 0.0
            avg_z = sum(r["z_score"] for r in found) / len(found) if found else float("nan")
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, QTableWidgetItem(str(n_total)))
            table.setItem(row, 2, QTableWidgetItem(str(len(found))))
            table.setItem(row, 3, QTableWidgetItem(f"{hit_rate:.0%}"))
            table.setItem(row, 4, QTableWidgetItem(f"{avg_z:.2f}" if found else "--"))
        table.itemDoubleClicked.connect(lambda item: self._view_details(item.row()))
        layout.addWidget(table)
        layout.addWidget(QLabel("Double-click a row for that event's per-occurrence details."))

        btn_row = QHBoxLayout()
        btn_add_all = QPushButton("Add Markers for All Found Peaks")
        btn_add_all.clicked.connect(self._add_all_found)
        btn_row.addWidget(btn_add_all)
        add_stats_export_buttons(
            ctx, self, btn_row,
            get_clipboard_text=lambda: "\n".join(
                f"{name}: {sum(r['found'] for r in results)}/{len(results)} found"
                for name, results in self.rows
            ),
            csv_default_name="PeakScan_AllEventTypes",
            csv_header=["Event", "Occurrences", "Found", "Hit Rate", "Avg Z (found only)"],
            get_csv_rows=lambda: [
                [name, len(results), sum(r["found"] for r in results),
                 f"{(sum(r['found'] for r in results) / len(results)) if results else 0.0:.4f}",
                 (f"{sum(r['z_score'] for r in results if r['found']) / max(1, sum(r['found'] for r in results)):.4f}"
                  if any(r['found'] for r in results) else "")]
                for name, results in self.rows
            ],
        )
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _view_details(self, row):
        name, results = self.rows[row]
        dlg = _AlignmentResultsDialog(self, self.ctx, name, results)
        dlg.exec()

    def _add_all_found(self):
        from ..plotting import simple_plot
        entries = [
            (r["peak_time"], r["kind"])
            for results in self.by_event.values()
            for r in results if r["found"]
        ]
        if not entries:
            show_error(self.ctx, "No found peaks to add.")
            return
        _add_peak_markers(self.ctx, entries)
        simple_plot(self.ctx)
        show_window_toast(self.ctx, f"Added {len(entries)} auto-detected peak marker(s)")


def launch_peak_finder(ctx):
    if ctx.cache is None or ctx.cache.get('source') != 'TDT':
        show_error(ctx, "Peak finding is only available for TDT data.")
        return

    dlg = _PeakFinderDialog(ctx.win, ctx)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return

    _, _, data_source, _ = get_normalized_signal(ctx)
    time_array = ctx.cache['x']
    fs = ctx.cache['fs']
    scope = dlg.scope
    z_threshold, include_troughs = dlg.z_threshold, dlg.include_troughs

    groups = dlg.groups

    def _work(progress):
        plan = pl.Plan(progress, [("Smoothing the signal", 10), ("Searching for peaks", 90)])
        plan.begin("Smoothing the signal")
        clean_signal = pl.smooth_signal(data_source, fs)
        plan.begin("Searching for peaks")
        if scope == SCOPE_WHOLE:
            peaks = pl.find_significant_peaks(
                time_array, clean_signal, z_threshold=z_threshold,
                min_distance_sec=dlg.min_distance, include_troughs=include_troughs,
            )
            plan.done()
            return peaks
        pre, post = get_window(ctx)
        if scope == SCOPE_SCAN_ALL_TYPES:
            # One tick per event type (each type's own events are quick to search).
            return {
                name: pl.find_peak_near_events(
                    time_array, clean_signal, times, pre, post,
                    z_threshold=z_threshold, include_troughs=include_troughs,
                )
                for name, times in plan.track("Searching for peaks", groups.items())
            }
        return pl.find_peak_near_events(
            time_array, clean_signal, dlg.event_times, pre, post,
            z_threshold=z_threshold, include_troughs=include_troughs,
            progress=plan.sub("Searching for peaks"),
        )

    def _on_success(result):
        from ..plotting import simple_plot

        if scope == SCOPE_WHOLE:
            peaks = result
            if not peaks:
                show_error(ctx, f"No peaks found at z >= {z_threshold:g} — try a lower threshold.")
                return
            if len(peaks) > _MANY_PEAKS_WARNING:
                reply = QMessageBox.question(
                    ctx.win, "A lot of peaks found",
                    f"Found {len(peaks)} peaks at this threshold — that's a lot to add as "
                    f"markers. Raise the threshold instead, or add them anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            _add_peak_markers(ctx, [(p["time"], p["kind"]) for p in peaks])
            simple_plot(ctx)
            show_window_toast(ctx, f"Added {len(peaks)} auto-detected peak marker(s)")
            return

        if scope == SCOPE_SCAN_ALL_TYPES:
            # Just show the summary — nothing gets added to the plot until
            # the user explicitly chooses to, from the summary dialog.
            n_types = len(result)
            n_found = sum(1 for results in result.values() for r in results if r["found"])
            show_window_toast(ctx, f"Scanned {n_types} event type(s), {n_found} aligned peak(s) found")
            summary_dlg = _ScanAllTypesResultsDialog(ctx.win, ctx, result)
            summary_dlg.exec()
            return

        results = result
        found_entries = [(r["peak_time"], r["kind"]) for r in results if r["found"]]
        if found_entries:
            _add_peak_markers(ctx, found_entries)
            simple_plot(ctx)
        show_window_toast(
            ctx, f"{len(found_entries)} / {len(results)} event(s) had an aligned peak"
        )
        results_dlg = _AlignmentResultsDialog(ctx.win, ctx, dlg.event_name, results)
        results_dlg.exec()

    def _on_error(msg):
        show_error(ctx, f"Peak finding failed: {msg}")

    run_in_background(ctx, _work, _on_success, _on_error, label="Finding significant peaks")
