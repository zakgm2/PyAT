"""
analysis/group/setup_dialog.py
--------------------------------
Group analysis, step 1: what to analyse. A short wizard over the recordings found
under the folder the person opened:

  1. Recordings  which ones, what each subject is called, and the group's name
  2. Markers     which of the markers the recordings share to analyse (the variables)
  3. Window      the window around each event, its baseline and response window, the signal
  4. Measures    AUC, peak, mean, latency to peak, decay time, and the comparison settings
  5. Review      the design (usable trials per subject and marker), problems, where it saves

It ends by saving the choices as analysis_settings.json in a folder named after the
group, inside the output location, and then runs the analysis (run.py). The dialog only
collects and checks settings; the rules for what is valid live in PhysicsLibrary's GroupSpec,
and the event lists come from scan.py, which builds them the way the single-recording Event
PETH does.
"""

import html
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QGridLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QRadioButton,
    QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import PhysicsLibrary as pl
from PhysicsLibrary.analysis import group as pl_group

from ...background import run_in_background
from ...toasts import show_error, show_window_toast
from ...window_fit import fit_to_screen
from .output import SETTINGS_FILENAME, output_base, resolve_group_dir, safe_folder_name, write_settings
from .run import start_group_run
from .scan import default_subject_names, scan_recordings

_ERROR_STYLE = "color: #d9534f;"
_MUTED_STYLE = "color: gray;"

_METRIC_TEXT = {
    "auc":     "AUC: the area under the baseline-corrected trace across the response window",
    "peak":    "Peak amplitude: the largest baseline-corrected value in the response window",
    "mean":    "Mean amplitude: the average of the baseline-corrected trace across the response window",
    "latency": "Latency to peak: seconds from the event to the peak",
    "decay":   "Decay time: seconds from the peak until the trace has fallen to a set share of it",
}
_DIRECTION_TEXT = {
    "positive": "Positive peak (the largest increase)",
    "negative": "Negative peak (the largest decrease)",
    "absolute": "Largest deflection, either direction",
}
_SIGNAL_TEXT = {
    "dff":    "dF/F minus the baseline mean (keeps the signal's own units)",
    "zscore": "Z-score against the baseline (its mean and SD, as in the TDT example)",
}


def describe_analysis(n_markers):
    """One sentence on what the analysis will do with this many markers."""
    if n_markers == 0:
        return "Pick the marker or markers to analyse."
    if n_markers == 1:
        return ("One marker: nothing to compare it with. AUC and mean amplitude are tested against zero (the "
                "baseline-corrected trace has mean zero without a response); peak, latency and decay time are "
                "reported as estimates with intervals, since they have no zero to be tested against.")
    if n_markers == 2:
        return ("Two markers: each measure is compared between them with a linear mixed-effects model (marker "
                "as the fixed effect; subject, and subject x marker, as random effects).")
    return (f"{n_markers} markers: each measure is compared across them with a linear mixed-effects model (marker "
            "as the fixed effect; subject, and subject x marker, as random effects), followed by every pairwise "
            "comparison between markers, adjusted for the number of comparisons.")


def _item(text="", checkable=False, editable=False, checked=False, align=None, muted=False, tip=None):
    it = QTableWidgetItem(text)
    flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
    if checkable:
        flags |= Qt.ItemFlag.ItemIsUserCheckable
        it.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
    if editable:
        flags |= Qt.ItemFlag.ItemIsEditable
    it.setFlags(flags)
    if align is not None:
        it.setTextAlignment(align | Qt.AlignmentFlag.AlignVCenter)
    if muted:
        it.setForeground(QBrush(QColor("gray")))
    if tip:
        it.setToolTip(tip)
    return it


def _table(columns):
    t = QTableWidget(0, len(columns))
    t.setHorizontalHeaderLabels(columns)
    t.verticalHeader().setVisible(False)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setAlternatingRowColors(True)
    return t


def _wrapped(text="", style=None):
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    if style:
        lbl.setStyleSheet(style)
    return lbl


class _Page(QWidget):
    """One page of the wizard. on_show() refreshes it from the pages before it; problems() are the
    reasons the wizard should not move on yet; apply() writes the page's choices into a GroupSpec."""

    title = ""

    def __init__(self, dlg):
        super().__init__()
        self.dlg = dlg

    def on_show(self):
        pass

    def problems(self):
        return []

    def apply(self, spec):
        pass


class _RecordingsPage(_Page):
    title = "Recordings"

    def __init__(self, dlg):
        super().__init__(dlg)
        scans = dlg.scans
        lay = QVBoxLayout(self)
        lay.addWidget(_wrapped(
            f"Found {len(scans)} TDT recordings under {dlg.base_path}. Each recording is one subject in the "
            "group. Rename the subjects if you like, and untick any recording to leave it out."))

        row = QHBoxLayout()
        row.addWidget(QLabel("Group name:"))
        default_name = os.path.basename(dlg.base_path.rstrip("/\\")) or "Group"
        self.e_group = QLineEdit(default_name)
        self.e_group.textChanged.connect(self._update_path_label)
        row.addWidget(self.e_group, stretch=1)
        lay.addLayout(row)
        self.lbl_path = _wrapped(style=_MUTED_STYLE)
        lay.addWidget(self.lbl_path)

        self.table = _table(["", "Subject", "Recording", "Events", "Notes"])
        names = default_subject_names([s["folder"] for s in scans], dlg.base_path)
        self.table.blockSignals(True)
        self.table.setRowCount(len(scans))
        for i, (sc, subject) in enumerate(zip(scans, names)):
            bad = bool(sc["error"])
            notes = []
            if bad:
                notes.append("Could not be read: " + sc["error"])
            if sc["n_splices"]:
                notes.append(f"{sc['n_splices']} saved splice{'s' if sc['n_splices'] != 1 else ''} applied")
            if sc["n_saved_markers"]:
                notes.append(f"{sc['n_saved_markers']} saved markers")
            notes.extend(sc["warnings"])
            self.table.setItem(i, 0, _item(checkable=True, checked=not bad) if not bad else _item(checkable=False, muted=True))
            self.table.setItem(i, 1, _item(subject, editable=not bad, muted=bad))
            self.table.setItem(i, 2, _item(sc["label"], muted=bad, tip=sc["folder"]))
            self.table.setItem(i, 3, _item("" if bad else f"{sc['n_events']:,}",
                                           align=Qt.AlignmentFlag.AlignRight, muted=bad))
            self.table.setItem(i, 4, _item("; ".join(notes), muted=bad, tip="\n".join(notes) or None))
        self.table.blockSignals(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.table.setColumnWidth(1, 240)
        self.table.setColumnWidth(4, 260)
        self.table.itemChanged.connect(lambda _item: self._update_count())
        lay.addWidget(self.table, stretch=1)

        bottom = QHBoxLayout()
        btn_all = QPushButton("Select all")
        btn_all.clicked.connect(lambda: self._set_all(True))
        btn_none = QPushButton("Select none")
        btn_none.clicked.connect(lambda: self._set_all(False))
        bottom.addWidget(btn_all)
        bottom.addWidget(btn_none)
        bottom.addStretch(1)
        self.lbl_count = QLabel()
        bottom.addWidget(self.lbl_count)
        lay.addLayout(bottom)
        self._update_path_label()
        self._update_count()

    def _set_all(self, checked):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i, sc in enumerate(self.dlg.scans):
            if not sc["error"]:
                self.table.item(i, 0).setCheckState(state)

    def _update_count(self):
        n = len(self.included())
        self.lbl_count.setText(f"{n} of {len(self.dlg.scans)} recordings included")

    def _update_path_label(self):
        typed = self.e_group.text().strip()
        folder = safe_folder_name(typed)
        base = output_base(self.dlg.ctx)
        if not typed:
            self.lbl_path.setStyleSheet(_ERROR_STYLE)
            self.lbl_path.setText("Type a name for the group. Its results are saved in a folder with that name.")
            return
        if not folder:
            self.lbl_path.setStyleSheet(_ERROR_STYLE)
            self.lbl_path.setText("That name can't be used as a folder name.")
            return
        self.lbl_path.setStyleSheet(_MUTED_STYLE)
        adjusted = "" if folder == typed else f" (characters a folder can't hold were replaced: '{folder}')"
        if base:
            self.lbl_path.setText(f"Results are saved in {os.path.join(base, 'Group Analysis', folder)}{adjusted}")
        else:
            self.lbl_path.setText(f"Results are saved in a folder called '{folder}'{adjusted}. No output folder is "
                                  "set in Options, so you will be asked where to put it.")

    def included(self):
        out = []
        for i, sc in enumerate(self.dlg.scans):
            if self.table.item(i, 0).checkState() == Qt.CheckState.Checked:
                out.append({"scan": sc, "subject": self.table.item(i, 1).text().strip()})
        return out

    def problems(self):
        out = []
        typed = self.e_group.text().strip()
        if not typed:
            out.append("Type a name for the group.")
        elif not safe_folder_name(typed):
            out.append("That group name can't be used as a folder name.")
        inc = self.included()
        if len(inc) < 2:
            out.append("Include at least two recordings: a group comparison needs more than one subject.")
        names = [r["subject"] for r in inc]
        if any(not n for n in names):
            out.append("Every included recording needs a subject name.")
        elif len(set(names)) != len(names):
            out.append("Subject names must be unique (repeated: " + ", ".join(sorted({n for n in names if names.count(n) > 1})) + ").")
        return out

    def apply(self, spec):
        spec.group_name = self.e_group.text().strip()
        spec.subjects = [{"subject": r["subject"], "folder": r["scan"]["folder"]} for r in self.included()]


class _MarkersPage(_Page):
    title = "Markers"

    def __init__(self, dlg):
        super().__init__(dlg)
        self._ticked = set()
        lay = QVBoxLayout(self)
        lay.addWidget(_wrapped(
            "The markers are the events to analyse: each occurrence of a marker (a lever press, a note) is one trial, "
            "listed under the same names as in the single-recording analyses (a store's name with a 1 for its onset "
            "or a 0 for its offset, or a note's own text). Pick the ones to analyse together."))
        self.chk_all = QCheckBox("Also show markers that are not in every included recording")
        self.chk_all.toggled.connect(lambda _c: self._rebuild())
        lay.addWidget(self.chk_all)
        self.table = _table(["", "Marker", "Events", "In recordings", "Per recording"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(lambda _i: self._on_ticks_changed())
        lay.addWidget(self.table, stretch=1)
        self.lbl_plan = _wrapped()
        lay.addWidget(self.lbl_plan)

    def on_show(self):
        self._rebuild()

    def _displayed_ticks(self):
        out = []
        for i in range(self.table.rowCount()):
            if self.table.item(i, 0).checkState() == Qt.CheckState.Checked:
                out.append(self.table.item(i, 1).text())
        return out

    def _on_ticks_changed(self):
        shown = {self.table.item(i, 1).text() for i in range(self.table.rowCount())}
        self._ticked = (self._ticked - shown) | set(self._displayed_ticks())
        self.lbl_plan.setText(describe_analysis(len(self._ticked)))

    def _rebuild(self):
        shown_before = {self.table.item(i, 1).text() for i in range(self.table.rowCount())}
        if shown_before:
            self._ticked = (self._ticked - shown_before) | set(self._displayed_ticks())
        design = self.dlg.design_scans()
        index = pl.marker_index(design)
        n = len(design)
        names = [m for m, e in index.items() if self.chk_all.isChecked() or e["recordings"] == n]
        names.sort(key=lambda m: (index[m]["recordings"] != n, m))
        self._ticked &= set(names)
        self.table.blockSignals(True)
        self.table.setRowCount(len(names))
        for i, m in enumerate(names):
            e = index[m]
            partial = e["recordings"] != n
            counts = list(e["per_subject"].values())
            lo, hi = min(counts), max(counts)
            missing = [r["subject"] for r in design if r["subject"] not in e["per_subject"]]
            tip = ("Missing from: " + ", ".join(missing)) if missing else None
            self.table.setItem(i, 0, _item(checkable=True, checked=m in self._ticked))
            self.table.setItem(i, 1, _item(m, muted=partial, tip=tip))
            self.table.setItem(i, 2, _item(f"{e['events']:,}", align=Qt.AlignmentFlag.AlignRight, muted=partial))
            self.table.setItem(i, 3, _item(f"{e['recordings']} of {n}", align=Qt.AlignmentFlag.AlignRight,
                                           muted=partial, tip=tip))
            self.table.setItem(i, 4, _item(str(lo) if lo == hi else f"{lo} to {hi}",
                                           align=Qt.AlignmentFlag.AlignRight, muted=partial))
        self.table.blockSignals(False)
        self.lbl_plan.setText(describe_analysis(len(self._ticked)))

    def selected(self):
        return [self.table.item(i, 1).text() for i in range(self.table.rowCount())
                if self.table.item(i, 0).checkState() == Qt.CheckState.Checked]

    def problems(self):
        return [] if self.selected() else ["Pick at least one marker."]

    def apply(self, spec):
        spec.markers = self.selected()


def _seconds_spin(lo, hi, value):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(1)
    s.setSingleStep(0.5)
    s.setSuffix(" s")
    s.setValue(value)
    return s


class _WindowPage(_Page):
    title = "Window"

    def __init__(self, dlg):
        super().__init__(dlg)
        lay = QVBoxLayout(self)
        lay.addWidget(_wrapped(
            "Each trial is a window around its event. The baseline is the stretch of that window the trial is "
            "compared with, and the response window is where its response is measured. Times are seconds "
            "relative to the event (before it is negative)."))

        grid = QGridLayout()
        self.pre = _seconds_spin(0.5, 600, pl_group.DEFAULT_PRE)
        self.post = _seconds_spin(0.5, 600, pl_group.DEFAULT_POST)
        self.b0 = _seconds_spin(-600, 0, pl_group.DEFAULT_BASELINE[0])
        self.b1 = _seconds_spin(-600, 0, pl_group.DEFAULT_BASELINE[1])
        self.r0 = _seconds_spin(0, 600, pl_group.DEFAULT_RESPONSE[0])
        self.r1 = _seconds_spin(0, 600, pl_group.DEFAULT_RESPONSE[1])
        grid.addWidget(QLabel("Window:"), 0, 0)
        grid.addWidget(QLabel("before the event"), 0, 1)
        grid.addWidget(self.pre, 0, 2)
        grid.addWidget(QLabel("after the event"), 0, 3)
        grid.addWidget(self.post, 0, 4)
        grid.addWidget(QLabel("Baseline:"), 1, 0)
        grid.addWidget(QLabel("from"), 1, 1)
        grid.addWidget(self.b0, 1, 2)
        grid.addWidget(QLabel("to"), 1, 3)
        grid.addWidget(self.b1, 1, 4)
        grid.addWidget(QLabel("Response:"), 2, 0)
        grid.addWidget(QLabel("from"), 2, 1)
        grid.addWidget(self.r0, 2, 2)
        grid.addWidget(QLabel("to"), 2, 3)
        grid.addWidget(self.r1, 2, 4)
        self.smooth = _seconds_spin(0.0, 10.0, pl_group.GroupSpec().smooth_seconds)
        self.smooth.setDecimals(2)
        self.smooth.setSingleStep(0.1)
        grid.addWidget(QLabel("Smoothing:"), 3, 0)
        grid.addWidget(QLabel("moving average of"), 3, 1)
        grid.addWidget(self.smooth, 3, 2)
        grid.addWidget(QLabel("(0 = none; Event PETH uses 0.5 s)"), 3, 3, 1, 2)
        grid.setColumnStretch(5, 1)
        lay.addLayout(grid)

        sig = QGroupBox("Signal")
        sig_lay = QVBoxLayout(sig)
        self.signal_group = QButtonGroup(self)
        self._signal_buttons = {}
        for key in pl_group.SIGNALS:
            rb = QRadioButton(_SIGNAL_TEXT[key])
            self.signal_group.addButton(rb)
            self._signal_buttons[key] = rb
            sig_lay.addWidget(rb)
        self._signal_buttons["dff"].setChecked(True)
        lay.addWidget(sig)

        row = QHBoxLayout()
        btn_reset = QPushButton("Reset to the standard defaults")
        btn_reset.clicked.connect(self._reset)
        row.addWidget(btn_reset)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(_wrapped(
            "The defaults follow TDT's own fiber photometry epoch-averaging example: 10 s either side of the event "
            "with the baseline from 10 to 6 s before it. There is no formal standard; GuPPy and pMAT leave the "
            "window and baseline to the user.", _MUTED_STYLE))

        self.lbl_problems = _wrapped(style=_ERROR_STYLE)
        lay.addWidget(self.lbl_problems)
        self.table = _table(["Marker", "Events", "Usable", "Sharing samples with another trial"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            header.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMaximumHeight(180)
        lay.addWidget(self.table)
        lay.addWidget(_wrapped(
            "Usable: the whole window lies inside the recording. Trials whose windows overlap contain the same "
            "stretch of signal, so they are not independent of each other.", _MUTED_STYLE))
        lay.addStretch(1)

        # Connected last: every widget _refresh() reads or fills exists by now.
        for w in (self.pre, self.post, self.b0, self.b1, self.r0, self.r1, self.smooth):
            w.valueChanged.connect(lambda _v: self._refresh())
        for rb in self._signal_buttons.values():
            rb.toggled.connect(lambda _c: self._refresh())

    def _reset(self):
        for w, v in ((self.pre, pl_group.DEFAULT_PRE), (self.post, pl_group.DEFAULT_POST),
                     (self.b0, pl_group.DEFAULT_BASELINE[0]), (self.b1, pl_group.DEFAULT_BASELINE[1]),
                     (self.r0, pl_group.DEFAULT_RESPONSE[0]), (self.r1, pl_group.DEFAULT_RESPONSE[1]),
                     (self.smooth, pl_group.GroupSpec().smooth_seconds)):
            w.setValue(v)
        self._signal_buttons["dff"].setChecked(True)

    def on_show(self):
        self._refresh()

    def _signal(self):
        return next(k for k, rb in self._signal_buttons.items() if rb.isChecked())

    def _window_spec(self):
        return pl_group.GroupSpec(pre=self.pre.value(), post=self.post.value(),
                                  baseline=(self.b0.value(), self.b1.value()),
                                  response=(self.r0.value(), self.r1.value()), signal=self._signal(),
                                  smooth_seconds=self.smooth.value())

    def _refresh(self):
        spec = self._window_spec()
        probs = spec.window_problems()
        self.lbl_problems.setText("\n".join(probs))
        markers = self.dlg.selected_markers()
        self.table.setRowCount(0)
        if probs or not markers:
            return
        summary = pl.design_summary(self.dlg.design_scans(), markers, spec.pre, spec.post)
        self.table.setRowCount(len(markers))
        for i, m in enumerate(markers):
            info = summary["markers"][m]
            share = f"{info['overlapping']:,} ({info['overlapping'] / info['usable']:.0%})" if info["usable"] else "-"
            self.table.setItem(i, 0, _item(m))
            self.table.setItem(i, 1, _item(f"{info['events']:,}", align=Qt.AlignmentFlag.AlignRight))
            self.table.setItem(i, 2, _item(f"{info['usable']:,}", align=Qt.AlignmentFlag.AlignRight))
            self.table.setItem(i, 3, _item(share, align=Qt.AlignmentFlag.AlignRight))

    def problems(self):
        return self._window_spec().window_problems()

    def apply(self, spec):
        w = self._window_spec()
        spec.pre, spec.post, spec.baseline, spec.response, spec.signal = w.pre, w.post, w.baseline, w.response, w.signal
        spec.smooth_seconds = w.smooth_seconds


class _MetricsPage(_Page):
    title = "Measures"

    def __init__(self, dlg):
        super().__init__(dlg)
        lay = QVBoxLayout(self)
        lay.addWidget(_wrapped(
            "Each trial is reduced to a few numbers, and each number is analysed on its own. Baseline-corrected means "
            "the trial with the baseline mean subtracted (and, for the z-score signal, divided by the baseline's SD)."))
        self.checks = {}
        for key in pl_group.METRICS:
            cb = QCheckBox(_METRIC_TEXT[key])
            cb.setChecked(True)
            cb.toggled.connect(lambda _c: self._update_enabled())
            self.checks[key] = cb
            lay.addWidget(cb)

        opts = QGroupBox("Options")
        grid = QGridLayout(opts)
        grid.addWidget(QLabel("Peak direction:"), 0, 0)
        self.combo_dir = QComboBox()
        for key in pl_group.PEAK_DIRECTIONS:
            self.combo_dir.addItem(_DIRECTION_TEXT[key], userData=key)
        self.combo_dir.setCurrentIndex(self.combo_dir.findData(pl_group.GroupSpec().peak_direction))
        grid.addWidget(self.combo_dir, 0, 1)
        self.lbl_dir = _wrapped("Used by the peak, the latency and the decay time. The default, the largest "
                                "deflection either way, is what Event PETH reports.", _MUTED_STYLE)
        grid.addWidget(self.lbl_dir, 1, 0, 1, 2)
        grid.addWidget(QLabel("Decay time counts until the trace falls to:"), 2, 0)
        self.spin_decay = QSpinBox()
        self.spin_decay.setRange(1, 99)
        self.spin_decay.setValue(50)
        self.spin_decay.setSuffix(" % of the peak")
        grid.addWidget(self.spin_decay, 2, 1)
        grid.setColumnStretch(1, 1)
        lay.addWidget(opts)
        lay.addWidget(_wrapped(
            "A decay time is only defined when the trace does fall back that far after the peak, within the window; "
            "otherwise it is left empty for that trial.", _MUTED_STYLE))

        comp = QGroupBox("Comparisons between markers")
        comp_grid = QGridLayout(comp)
        comp_grid.addWidget(QLabel("Correct the pairwise comparisons with:"), 0, 0)
        self.combo_correction = QComboBox()
        for key in pl_group.CORRECTIONS:
            self.combo_correction.addItem(pl_group.CORRECTION_LABELS[key], userData=key)
        self.combo_correction.setCurrentIndex(self.combo_correction.findData(pl_group.GroupSpec().correction))
        comp_grid.addWidget(self.combo_correction, 0, 1)
        comp_grid.addWidget(QLabel("Significance level:"), 1, 0)
        self.spin_alpha = QDoubleSpinBox()
        self.spin_alpha.setDecimals(3)
        self.spin_alpha.setRange(0.001, 0.5)
        self.spin_alpha.setSingleStep(0.01)
        self.spin_alpha.setValue(pl_group.GroupSpec().alpha)
        comp_grid.addWidget(self.spin_alpha, 1, 1)
        comp_grid.setColumnStretch(1, 1)
        lay.addWidget(comp)
        lay.addWidget(_wrapped("These apply when two or more markers are compared: every pair is tested, and the "
                               "p-values are corrected for how many pairs there are.", _MUTED_STYLE))
        lay.addStretch(1)
        self._update_enabled()

    def _update_enabled(self):
        c = self.checks
        self.combo_dir.setEnabled(c["peak"].isChecked() or c["latency"].isChecked() or c["decay"].isChecked())
        self.spin_decay.setEnabled(c["decay"].isChecked())

    def problems(self):
        return [] if any(cb.isChecked() for cb in self.checks.values()) else ["Pick at least one measure."]

    def apply(self, spec):
        spec.metrics = [k for k in pl_group.METRICS if self.checks[k].isChecked()]
        spec.peak_direction = self.combo_dir.currentData()
        spec.decay_fraction = self.spin_decay.value() / 100.0
        spec.correction = self.combo_correction.currentData()
        spec.alpha = self.spin_alpha.value()


class _ReviewPage(_Page):
    title = "Review"

    def __init__(self, dlg):
        super().__init__(dlg)
        lay = QVBoxLayout(self)
        self.lbl_summary = _wrapped()
        self.lbl_summary.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.lbl_summary)
        self.table = _table([])
        lay.addWidget(self.table, stretch=1)
        self.lbl_notes = _wrapped()
        self.lbl_notes.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.lbl_notes)
        self.lbl_problems = _wrapped(style=_ERROR_STYLE)
        lay.addWidget(self.lbl_problems)
        self.lbl_out = _wrapped(style=_MUTED_STYLE)
        lay.addWidget(self.lbl_out)

    def on_show(self):
        spec = self.dlg.build_spec()
        problems = spec.problems()
        self.lbl_problems.setText("\n".join(problems))
        e = html.escape
        n_sub, n_mark = len(spec.subjects), len(spec.markers)
        direction = _DIRECTION_TEXT[spec.peak_direction].split(" (")[0].lower()
        measures = ", ".join(pl_group.METRIC_LABELS[m] for m in spec.metrics)
        lines = [
            f"<b>{e(spec.group_name)}</b>: {n_sub} subjects, {n_mark} marker{'s' if n_mark != 1 else ''}",
            f"<b>Markers</b>: {e(', '.join(spec.markers))}",
            f"<b>Window</b>: {spec.pre:g} s before to {spec.post:g} s after each event; baseline {spec.baseline[0]:g} to "
            f"{spec.baseline[1]:g} s; response {spec.response[0]:g} to {spec.response[1]:g} s",
            f"<b>Signal</b>: {e(_SIGNAL_TEXT[spec.signal])}; "
            + (f"smoothed with a {spec.smooth_seconds:g} s moving average" if spec.smooth_seconds > 0 else "not smoothed")
            + f"; motion correction {spec.regression_method.upper()} (Options)",
            f"<b>Measures</b>: {e(measures)}; {e(direction)}; decay to {spec.decay_fraction:.0%} of the peak",
            f"<b>Comparisons</b>: {e(pl_group.CORRECTION_LABELS[spec.correction])}, significance level {spec.alpha:g}",
            e(describe_analysis(n_mark)),
        ]
        self.lbl_summary.setText("<br>".join(lines))

        self.table.clear()
        self.table.setRowCount(0)
        if not problems:
            summary = pl.design_summary(self.dlg.design_scans(), spec.markers, spec.pre, spec.post)
            self.table.setColumnCount(len(spec.markers) + 1)
            self.table.setHorizontalHeaderLabels(["Usable trials"] + list(spec.markers))
            subjects = [s["subject"] for s in spec.subjects]
            self.table.setRowCount(len(subjects) + 1)
            totals = {m: 0 for m in spec.markers}
            for i, s in enumerate(subjects):
                self.table.setItem(i, 0, _item(s))
                for j, m in enumerate(spec.markers, start=1):
                    cell = summary["cells"][s][m]
                    totals[m] += cell["usable"]
                    tip = f"{cell['events']} events, {cell['usable']} usable, {cell['overlapping']} sharing samples"
                    self.table.setItem(i, j, _item(str(cell["usable"]), align=Qt.AlignmentFlag.AlignRight,
                                                   muted=cell["usable"] == 0, tip=tip))
            last = len(subjects)
            self.table.setItem(last, 0, _item("All subjects"))
            for j, m in enumerate(spec.markers, start=1):
                self.table.setItem(last, j, _item(f"{totals[m]:,}", align=Qt.AlignmentFlag.AlignRight))
            self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
            for j in range(1, len(spec.markers) + 1):
                self.table.horizontalHeader().setSectionResizeMode(j, QHeaderView.ResizeMode.ResizeToContents)
            notes = []
            for w in summary["warnings"]:
                colour = "#d9534f" if w["level"] == "warning" else "gray"
                notes.append(f"<span style='color:{colour}'>{e(w['text'])}</span>")
            self.lbl_notes.setText("<br>".join(notes))
        else:
            self.lbl_notes.setText("")

        base = output_base(self.dlg.ctx)
        folder = safe_folder_name(spec.group_name)
        where = (os.path.join(base, "Group Analysis", folder) if base and folder
                 else f"a folder called '{folder}' (you will be asked where)")
        self.lbl_out.setText(f"Run analysis saves these settings as {SETTINGS_FILENAME} in {where}, then loads each "
                             "recording, measures its trials, fits the models, and writes the tables and a report "
                             "there. It takes a few seconds per recording.")


class GroupSetupDialog(QDialog):
    """The wizard. On accept the settings are saved: `spec` holds the GroupSpec, `group_dir` the folder it was
    saved in and `settings_path` the file."""

    def __init__(self, parent, ctx, scans, base_path, store_labels=None):
        super().__init__(parent)
        self.ctx = ctx
        self.scans = scans
        self.base_path = base_path
        self.store_labels = dict(store_labels or {})
        self.spec = None
        self.group_dir = None
        self.settings_path = None

        self.setWindowTitle("Group analysis")
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setSizeGripEnabled(True)
        fit_to_screen(self, 980, 700)

        layout = QVBoxLayout(self)
        self.lbl_step = QLabel()
        self.lbl_step.setStyleSheet("font-size: 13pt; font-weight: bold;")
        layout.addWidget(self.lbl_step)

        self.pages = [_RecordingsPage(self), _MarkersPage(self), _WindowPage(self), _MetricsPage(self),
                      _ReviewPage(self)]
        self.stack = QStackedWidget()
        for p in self.pages:
            self.stack.addWidget(p)
        layout.addWidget(self.stack, stretch=1)

        self.lbl_problem = _wrapped(style=_ERROR_STYLE)
        layout.addWidget(self.lbl_problem)

        row = QHBoxLayout()
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        row.addWidget(btn_cancel)
        row.addStretch(1)
        self.btn_back = QPushButton("Back")
        self.btn_back.clicked.connect(lambda: self._go(-1))
        row.addWidget(self.btn_back)
        self.btn_next = QPushButton("Next")
        self.btn_next.setDefault(True)
        self.btn_next.clicked.connect(lambda: self._go(1))
        row.addWidget(self.btn_next)
        layout.addLayout(row)
        self._show_page(0)

    # --- what the pages ask of each other -------------------------------------------------------
    def design_scans(self):
        """The included recordings as design_summary / marker_index want them."""
        return [{"subject": r["subject"], "groups": r["scan"]["groups"], "t_range": r["scan"]["t_range"]}
                for r in self.pages[0].included()]

    def selected_markers(self):
        return self.pages[1].selected()

    def build_spec(self):
        spec = pl_group.GroupSpec(regression_method=self.ctx.settings.get("regression_method", "ols"),
                                  store_labels=dict(self.store_labels))
        for p in self.pages:
            p.apply(spec)
        return spec

    # --- navigation ----------------------------------------------------------------------------
    def _show_page(self, index):
        self.stack.setCurrentIndex(index)
        page = self.pages[index]
        page.on_show()
        self.lbl_step.setText(f"Group analysis: step {index + 1} of {len(self.pages)}, {page.title}")
        self.btn_back.setEnabled(index > 0)
        self.btn_next.setText("Run analysis" if index == len(self.pages) - 1 else "Next")
        self.lbl_problem.setText("")

    def _go(self, delta):
        index = self.stack.currentIndex()
        if delta < 0:
            self._show_page(max(0, index - 1))
            return
        problems = self.pages[index].problems()
        if problems:
            self.lbl_problem.setText("\n".join(problems))
            return
        if index == len(self.pages) - 1:
            self._finish()
        else:
            self._show_page(index + 1)

    def _finish(self):
        spec = self.build_spec()
        problems = spec.problems()
        if problems:
            self.lbl_problem.setText("\n".join(problems))
            return
        # resolve_group_dir() always hands back a folder with no analysis_settings.json in it yet
        # (a group name already run gets " (2)", " (3)", ...), so there is never anything here to
        # ask about replacing.
        group_dir = resolve_group_dir(self.ctx, self, spec.group_name)
        if group_dir is None:
            return
        try:
            path = write_settings(group_dir, spec, self.scans)
        except Exception as e:
            show_error(self.ctx, f"Could not save the settings: {e}")
            return
        self.spec, self.group_dir, self.settings_path = spec, group_dir, path
        self.accept()


def launch_group_analysis(ctx, folders, base_path):
    """Entry point from the multi-recording prompt (loaders/tdt.py): scan the recordings in the
    background, with a progress toast, then open the setup wizard."""
    store_labels = dict(ctx.store_labels)

    def _work(progress):
        return scan_recordings(folders, base_path, store_labels, progress=progress)

    def _on_success(scans):
        if all(s["error"] for s in scans):
            show_error(ctx, "None of the recordings could be read:\n" + "\n".join(
                f"{s['label']}: {s['error']}" for s in scans[:5]))
            return
        dlg = GroupSetupDialog(ctx.win, ctx, scans, base_path, store_labels)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            start_group_run(ctx, dlg.spec, dlg.group_dir)

    def _on_error(msg):
        show_error(ctx, f"Could not scan the recordings: {msg}")

    run_in_background(ctx, _work, _on_success, _on_error, label="Scanning recordings")
