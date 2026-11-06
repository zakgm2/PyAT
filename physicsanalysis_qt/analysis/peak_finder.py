"""
analysis/peak_finder.py
--------------------------
Auto-detect statistically significant peaks in the loaded signal
(PyATCLI's find_significant_peaks / find_peak_near_events), for
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

Two things guard against reading chance as a result. The whole-recording
search ignores the first seconds of the recording (a trace is least settled
right after the light comes on). The event-scoped searches can be compared
with shifted copies of the same events (a shuffle null): "found" near an
event is partly chance, and the p-values say how much.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox, QSpinBox, QCheckBox,
    QPushButton, QMessageBox, QComboBox, QStackedWidget, QWidget,
    QTableWidget, QTableWidgetItem, QHeaderView,
)

from ..app import errorlog
from ..backend.errors import BackendError
from ..backend.recordings import recording_ref
from ..app.background import run_engine
from ..edit.marker_labels import marker_display_label
from ..app.toasts import show_error, show_window_toast
from .dispatch import add_stats_export_buttons, get_window
from .event_peth import _group_markers_by_name
from ..app.window_fit import fit_to_screen

_AUTO_PEAK_COLOR = "magenta"
_MANY_PEAKS_WARNING = 300

SCOPE_WHOLE = "Whole recording"
SCOPE_ONE_EVENT = "One specific event"
SCOPE_ALL_SAME_NAME = "All events with a chosen name"
SCOPE_SCAN_ALL_TYPES = "Scan every event type at once"

# the scope names PyATCLI's peak_finder analysis uses
_SCOPE_IDS = {SCOPE_WHOLE: "whole", SCOPE_ONE_EVENT: "one_event", SCOPE_ALL_SAME_NAME: "all_same_name",
              SCOPE_SCAN_ALL_TYPES: "scan_all"}

DEFAULT_START_BUFFER_S = 10.0     # PyATCLI's default for the whole-recording search
DEFAULT_SHUFFLES = 1000           # and for the shuffle null


def _p_text(p, digits=3):
    return "--" if p is None else f"{p:.{digits}f}"


def _p_csv(p):
    return "" if p is None else f"{p:.4f}"


def _chance_sentence(null):
    """What the shifted copies of the events say about chance, as a sentence."""
    if not null.get("available"):
        return f"No chance level could be measured: {null.get('reason') or 'not available'}."
    return (f"Shifted copies of these events find a peak in {null['chance_hit_rate']:.0%} of windows by chance "
            f"(about {null['expected_by_chance']:.1f} of {null['n_tested']} events); the chance of this many events or more "
            f"having one is p = {null['p_count']:.3f} ({null['n_shuffles']} shuffles).")


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

        # The first seconds of a trace are the least settled (the bleaching is steepest, the motion-correction fit has the
        # least to go on), and the whole-recording z-score reads that as unusual; the search skips them. The mean and SD
        # still come from the whole recording, so no other peak's z changes.
        self.buffer_widget = QWidget()
        row_buffer = QHBoxLayout(self.buffer_widget)
        row_buffer.setContentsMargins(0, 0, 0, 0)
        row_buffer.addWidget(QLabel("Ignore the first (s):"))
        self.spin_buffer = QDoubleSpinBox()
        self.spin_buffer.setRange(0.0, 3600.0)
        self.spin_buffer.setSingleStep(1.0)
        self.spin_buffer.setValue(DEFAULT_START_BUFFER_S)
        self.spin_buffer.setToolTip(
            "No peak is reported in this many seconds at the start of the recording: a trace is least settled\n"
            "right after the light comes on, and the tail of the bleaching there reads as unusual.\n"
            "The z-scores still use the whole recording, so no other peak changes. 0 searches everything.\n"
            "Look at the first minute of your own recording and set what it needs."
        )
        row_buffer.addWidget(self.spin_buffer)
        layout.addWidget(self.buffer_widget)

        # A response search takes the LARGEST z in each window, so some windows reach the threshold by chance. Moving the
        # whole train of events by a random shift and searching those windows the same way measures how often.
        self.null_widget = QWidget()
        row_null = QHBoxLayout(self.null_widget)
        row_null.setContentsMargins(0, 0, 0, 0)
        self.cb_null = QCheckBox("Compare with shuffled event times (chance level)")
        self.cb_null.setChecked(True)
        self.cb_null.setToolTip(
            "Finding a peak near an event is partly chance, because the search takes the largest z in each window.\n"
            "This moves the whole train of events by a random shift, searches those windows the same way, and\n"
            "reports how often that finds a peak and how likely it is that as many of your events did.\n"
            "About two seconds per 20 events at 1000 shuffles."
        )
        row_null.addWidget(self.cb_null)
        self.spin_shuffles = QSpinBox()
        self.spin_shuffles.setRange(100, 20000)
        self.spin_shuffles.setSingleStep(100)
        self.spin_shuffles.setValue(DEFAULT_SHUFFLES)
        self.spin_shuffles.setSuffix(" shuffles")
        self.cb_null.toggled.connect(self.spin_shuffles.setEnabled)
        row_null.addWidget(self.spin_shuffles)
        layout.addWidget(self.null_widget)

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
        self.buffer_widget.setVisible(is_whole)           # the start buffer is for the whole-recording search,
        self.null_widget.setVisible(not is_whole)         # the chance level for the searches near events

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
        self.start_buffer = self.spin_buffer.value()
        self.n_shuffles = self.spin_shuffles.value() if self.cb_null.isChecked() else 0
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

    def __init__(self, parent, ctx, event_name, results, provenance=None, null=None):
        super().__init__(parent)
        self.setWindowTitle(f"Peak Alignment — {event_name}")
        fit_to_screen(self, 560 if null else 500, 400)
        layout = QVBoxLayout(self)

        # `null`: the shuffle null of these events (compute.peaks, n_shuffles > 0), or None when it was not asked for
        p_events = (null["p_event"] if null.get("available") else [None] * len(results)) if null else None
        n_found = sum(1 for r in results if r["found"])
        summary = f"{n_found} / {len(results)} event(s) had a peak at or above threshold."
        if null:
            summary += " " + _chance_sentence(null)
        label = QLabel(summary)
        label.setWordWrap(True)
        layout.addWidget(label)

        header = ["Event Time (s)", "Found", "Latency (s)", "Z-score"] + (["p (shuffle)"] if null else [])
        table = QTableWidget(len(results), len(header))
        table.setHorizontalHeaderLabels(["Event Time (s)", "Found?", "Latency (s)", "Z-score"] + (["p (shuffle)"] if null else []))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        for row, r in enumerate(results):
            table.setItem(row, 0, QTableWidgetItem(f"{r['event_time']:.2f}"))
            table.setItem(row, 1, QTableWidgetItem("Yes" if r["found"] else "No"))
            table.setItem(row, 2, QTableWidgetItem(f"{r['latency']:.2f}" if r["found"] else "--"))
            table.setItem(row, 3, QTableWidgetItem(f"{r['z_score']:.2f}" if r["found"] else "--"))
            if null:
                table.setItem(row, 4, QTableWidgetItem(_p_text(p_events[row])))
        layout.addWidget(table)

        btn_row = QHBoxLayout()
        add_stats_export_buttons(
            ctx, self, btn_row,
            get_clipboard_text=lambda: summary,
            csv_default_name=f"PeakAlignment_{event_name}",
            csv_header=header,
            get_csv_rows=lambda: [
                [f"{r['event_time']:.4f}", r['found'],
                 f"{r['latency']:.4f}" if r['found'] else "",
                 f"{r['z_score']:.4f}" if r['found'] else ""]
                + ([_p_csv(p_events[i])] if null else [])
                for i, r in enumerate(results)
            ],
            provenance=provenance,
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

    def __init__(self, parent, ctx, by_event, provenance=None, nulls=None):
        super().__init__(parent)
        self.ctx = ctx
        self.by_event = by_event  # {name: [result dicts]}
        self.provenance = provenance
        self.nulls = nulls or {}  # {name: shuffle-null dict}, empty when it was not asked for
        self.setWindowTitle("Peak Scan — All Event Types")
        fit_to_screen(self, 900 if self.nulls else 650, 420)      # three more columns with the chance level
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            "How many occurrences of each event type had an aligned peak. Higher hit\n"
            "rate / z-score means that event is more likely tied to a real response."
        ))
        if self.nulls:
            note = QLabel(
                "Chance Hit Rate: how often shifted copies of that event's train find a peak. p (shuffle): how likely it is that as\n"
                "many of its occurrences did by chance. p (Holm): that p corrected for the number of event types scanned."
            )
            note.setWordWrap(True)
            layout.addWidget(note)

        self.rows = sorted(
            by_event.items(),
            key=lambda kv: (sum(r["found"] for r in kv[1]) / len(kv[1])) if kv[1] else 0,
            reverse=True,
        )

        columns = ["Event", "Occurrences", "Found", "Hit Rate", "Avg Z (found only)"]
        if self.nulls:
            columns += ["Chance Hit Rate", "p (shuffle)", "p (Holm)"]
        table = QTableWidget(len(self.rows), len(columns))
        table.setHorizontalHeaderLabels(columns)
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
            if self.nulls:
                chance, p_count, p_holm = self._null_values(name)
                table.setItem(row, 5, QTableWidgetItem("--" if chance is None else f"{chance:.0%}"))
                table.setItem(row, 6, QTableWidgetItem(_p_text(p_count)))
                table.setItem(row, 7, QTableWidgetItem(_p_text(p_holm)))
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
            csv_header=columns,
            get_csv_rows=lambda: [
                [name, len(results), sum(r["found"] for r in results),
                 f"{(sum(r['found'] for r in results) / len(results)) if results else 0.0:.4f}",
                 (f"{sum(r['z_score'] for r in results if r['found']) / max(1, sum(r['found'] for r in results)):.4f}"
                  if any(r['found'] for r in results) else "")]
                + ([_p_csv(v) for v in self._null_values(name)] if self.nulls else [])
                for name, results in self.rows
            ],
            provenance=provenance,
        )
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _null_values(self, name):
        """(chance hit rate, p (shuffle), p (Holm)) of one event type; None where the library could not measure it."""
        null = self.nulls.get(name)
        if not null or not null.get("available"):
            return None, None, None
        return null["chance_hit_rate"], null["p_count"], null.get("p_count_holm")

    def _view_details(self, row):
        name, results = self.rows[row]
        dlg = _AlignmentResultsDialog(self, self.ctx, name, results, provenance=self.provenance, null=self.nulls.get(name))
        dlg.exec()

    def _add_all_found(self):
        from ..plot.plotting import simple_plot
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

    scope = dlg.scope
    z_threshold, include_troughs = dlg.z_threshold, dlg.include_troughs
    start_buffer, n_shuffles = dlg.start_buffer, dlg.n_shuffles
    errorlog.action("analysis", tool="Peak Finder", scope=scope, z_threshold=z_threshold, include_troughs=include_troughs,
                    start_buffer_s=start_buffer if scope == SCOPE_WHOLE else None, n_shuffles=None if scope == SCOPE_WHOLE else n_shuffles)

    groups = dlg.groups

    try:
        ref = recording_ref(ctx)
    except BackendError as e:
        show_error(ctx, f"Peak finding failed: {e}")
        return

    # The search runs in the analysis engine (compute.peaks: the normalized signal, smoothed, then the
    # peaks): over the whole recording, or the peak nearest each of one event type's times, or each type's.
    window = get_window(ctx)
    if scope == SCOPE_WHOLE:
        request = {"recording": ref, "scope": "whole", "z_threshold": z_threshold, "include_troughs": include_troughs,
                   "min_distance_s": dlg.min_distance, "start_buffer_s": start_buffer}
    else:
        events = groups if scope == SCOPE_SCAN_ALL_TYPES else {dlg.event_name or "event": [float(t) for t in dlg.event_times]}
        request = {"recording": ref, "scope": "events", "z_threshold": z_threshold, "include_troughs": include_troughs,
                   "events": events, "pre": window[0], "post": window[1], "n_shuffles": n_shuffles, "seed": 0}

    prov_params = {"scope": _SCOPE_IDS[scope], "z_threshold": float(z_threshold), "include_troughs": bool(include_troughs),
                   "pre_s": float(window[0]), "post_s": float(window[1])}
    if scope == SCOPE_WHOLE:
        prov_params.update(min_distance_s=float(dlg.min_distance), start_buffer_s=float(start_buffer))
    elif scope == SCOPE_ONE_EVENT:
        prov_params.update(event_time=float(dlg.event_times[0]), n_shuffles=int(n_shuffles), seed=0)
    elif scope == SCOPE_ALL_SAME_NAME:
        prov_params.update(event=dlg.event_name, event_times=[float(t) for t in dlg.event_times], n_shuffles=int(n_shuffles), seed=0)
    else:
        prov_params.update(event_groups={name: [float(t) for t in times] for name, times in groups.items()},
                           n_shuffles=int(n_shuffles), seed=0)
    prov = {"kind": "peak_finder", "parameters": prov_params}

    def _on_success(answer):
        from ..plot.plotting import simple_plot

        if scope == SCOPE_WHOLE:
            result = answer["peaks"]
        elif scope == SCOPE_SCAN_ALL_TYPES:
            result = answer["groups"]
        else:
            result = next(iter(answer["groups"].values()))

        if scope == SCOPE_WHOLE:
            peaks = result
            if not peaks:
                show_error(ctx, f"No peaks found at z >= {z_threshold:g} after the first {start_buffer:g} s — try a lower threshold.")
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
            summary_dlg = _ScanAllTypesResultsDialog(ctx.win, ctx, result, provenance=prov, nulls=answer.get("null"))
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
        null = next(iter(answer["null"].values())) if answer.get("null") else None
        results_dlg = _AlignmentResultsDialog(ctx.win, ctx, dlg.event_name, results, provenance=prov, null=null)
        results_dlg.exec()

    def _on_error(msg):
        show_error(ctx, f"Peak finding failed: {msg}")

    run_engine(ctx, "compute.peaks", request, _on_success, _on_error, label="Finding significant peaks")
