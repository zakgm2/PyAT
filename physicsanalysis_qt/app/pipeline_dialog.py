"""
app/pipeline_dialog.py
----------------------
The processing a recording goes through, as the person chooses it and as it is written down for a paper. Two modal windows, each with a button that applies
(nothing changes while a box is being edited):

    Options ▸ Pipeline options…   every choice the processing makes — the motion-correction window, the dF/F baseline, the low-pass filter, the smoothing, the
                                  z-score baseline — with what it does. They are settings, like the motion-correction method beside them: what is chosen is
                                  kept in the settings file, applies to everything opened afterwards, and — when OK is pressed in Options — to the recording on
                                  screen, which is read again from disk (loading/common.reopen_current). What the options are, their defaults, their ranges and
                                  their wording come from the library's registry (backend `pipeline.describe`), so an option added there appears here without
                                  this file being touched.
    Copy pipeline (status bar)    the methods paragraph for the recording on screen (the engine's `methods.text`), written by the library from what was done
                                  to it: the options in force, the motion-correction method, the splices, the software versions. Copy, or save as text.

This file only asks, shows and applies; what an option is, what it allows and what a sentence of the paragraph says is the library's.
"""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from . import errorlog
from .background import run_engine
from .toasts import show_error, show_window_toast
from .window_fit import fit_dialog_to_content, scroll_body
from ..backend import BackendError, api
from ..backend.recordings import recording_ref

_FAR = 1_000_000                       # the bound of a number box for an option that has none

# The motion-correction method (the library's `regression_method`, which is not one of the registry's options: it is how a recording is opened) is chosen in
# the same window, with the options of the motion-correction step.
REGRESSION_LABELS = {
    "ols":    "OLS (default — plain least-squares, no robustness)",
    "ransac": "RANSAC (excludes severe artifacts entirely)",
    "huber":  "Huber (downweights outliers instead of excluding them)",
}
REGRESSION_NOTE = ("How the isosbestic (415 nm) stream is regressed onto the signal (465 nm) stream. The three methods can give noticeably different results on the same "
                   "recording (how much of a transient near a motion artifact survives, say): worth trying each one before settling on one for a dataset.")


def _gray(text):
    label = QLabel(text)
    label.setStyleSheet("color: gray;")
    label.setWordWrap(True)
    return label


def summarize(changed, regression_method="ols"):
    """One line for Options: what is chosen, from {option name: value} of those that are not their default, and the motion-correction method if it is not OLS."""
    parts = []
    if changed:
        names = sorted(changed)
        shown = ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else "")
        parts.append(f"{len(names)} option{'s' if len(names) != 1 else ''} changed: {shown}")
    if regression_method != "ols":
        parts.append(f"{regression_method.upper()} regression")
    return "; ".join(parts) or "All options at their defaults"


def holds_unsaved_work(ctx):
    """Whether what is on screen has anything that Save Changes would keep and a reload from disk would not (markers, highlights, text boxes, splices,
    signal names): Options asks before it reloads. Not an exact test — what is on disk is not compared — so it asks whenever there could be something to lose."""
    cache = ctx.cache or {}
    return bool(cache.get("markers") or cache.get("highlights") or cache.get("text_annotations") or ctx._active_splices or ctx._signal_renames)


def confirm_reload(parent):
    """Asks whether to read the recording again (True: go ahead)."""
    answer = QMessageBox.question(
        parent, "Apply the pipeline options?",
        "Applying reads the recording from disk again, as Reload does. Markers, splices, highlights, text boxes and signal names that you have not "
        "saved with Save Changes are not kept.\n\nApply anyway?")
    return answer == QMessageBox.StandardButton.Yes


class OptionEditor(QWidget):
    """The widgets of one option and how to read its value: a check box (true/false), a list (one of a few), a number box (a number, whole or not), or a check
    box beside a number box for a time that may be left unset. `value()` is the option's value as the library holds it; an option nobody touched answers with
    the value it came in with, exactly, so what a box shows rounded (three decimals) never drifts what is saved."""

    edited = pyqtSignal()

    def __init__(self, option, value):
        super().__init__()
        self.option = option
        self._original = value
        self._touched = False
        kind = option["kind"]
        self.check = self.combo = self.spin = None
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        if kind == "bool":
            self.check = QCheckBox()
            self.check.toggled.connect(self._edited)
            row.addWidget(self.check)
        elif kind == "choice":
            self.combo = QComboBox()
            for choice in option["choices"]:
                self.combo.addItem(choice, choice)
            self.combo.currentIndexChanged.connect(self._edited)
            row.addWidget(self.combo)
        else:
            if kind == "seconds_or_none":
                self.check = QCheckBox("set")
                self.check.toggled.connect(self._edited)
                row.addWidget(self.check)
            self.spin = QSpinBox() if kind == "int" else QDoubleSpinBox()
            low, high = option["minimum"], option["maximum"]
            low, high = (-_FAR if low is None else low), (_FAR if high is None else high)
            self.spin.setRange(int(low), int(high)) if kind == "int" else self.spin.setRange(float(low), float(high))
            if kind != "int":
                self.spin.setDecimals(3)
            if option["unit"]:
                self.spin.setSuffix(" " + option["unit"])
            self.spin.valueChanged.connect(self._edited)
            row.addWidget(self.spin)
        row.addStretch(1)
        self.set_value(value)

    def _edited(self, *_):
        self._touched = True
        if self.option["kind"] == "seconds_or_none":
            self.spin.setEnabled(self.check.isChecked())
        self.edited.emit()

    def set_value(self, value):
        """Shows `value` (nothing counts as edited)."""
        self._original, self._touched = value, False
        widgets = [w for w in (self.check, self.combo, self.spin) if w is not None]
        for w in widgets:
            w.blockSignals(True)
        kind = self.option["kind"]
        if kind == "bool":
            self.check.setChecked(bool(value))
        elif kind == "choice":
            self.combo.setCurrentIndex(max(0, self.combo.findData(value)))
        else:
            if kind == "seconds_or_none":
                self.check.setChecked(value is not None)
                self.spin.setEnabled(value is not None)
            self.spin.setValue(self.option["minimum"] or 0 if value is None else value)
        for w in widgets:
            w.blockSignals(False)

    def value(self):
        if not self._touched:
            return self._original
        kind = self.option["kind"]
        if kind == "bool":
            return self.check.isChecked()
        if kind == "choice":
            return self.combo.currentData()
        if kind == "seconds_or_none" and not self.check.isChecked():
            return None
        return int(self.spin.value()) if kind == "int" else float(self.spin.value())


class PipelineDialog(QDialog):
    """Every option of the pipeline, step by step, and the motion-correction method. `description` is the library's (backend `pipeline.describe()`); `values`
    is {option name: value} for every option as it stands. Apply closes it accepted: `changed()` is then what was chosen (only the options that are not their
    default) and `regression_method()` the method."""

    def __init__(self, parent, description, values, regression_method="ols"):
        super().__init__(parent)
        self.defaults = dict(description["defaults"])
        self.editors = {}
        self.combo_regression = QComboBox()
        for value, label in REGRESSION_LABELS.items():
            self.combo_regression.addItem(label, value)
        self.combo_regression.setCurrentIndex(max(0, self.combo_regression.findData(regression_method)))
        self.setWindowTitle("Pipeline options")
        outer, layout, body = scroll_body(self)                     # see app/window_fit.py

        layout.addWidget(QLabel("<b>How a recording is processed</b>"))
        layout.addWidget(_gray(
            "Each box is one choice the processing makes, the motion-correction method included. They apply to every recording you open (a group analysis too), "
            "and when you press OK in Options the recording on screen is read again from disk with them, as Reload does. An option left at its default is not sent, so a recording that has its own choice saved "
            "(python -m PyATCLI saved pipeline) keeps it. The status bar's Copy pipeline writes down what a recording was processed with."))

        if not any(step["name"] == "motion" for step in description["steps"]):                  # (the method has a place even if the library has no such step)
            box = QGroupBox("Motion correction (TDT recordings only)")
            self._add_regression(QGridLayout(box), 0)
            layout.addWidget(box)
        for step in description["steps"]:
            if not step["options"] and step["name"] != "motion":
                continue
            sources = step.get("sources")
            title = step["title"] if not sources else f"{step['title']} ({' and '.join(sources)} recordings only)"
            box = QGroupBox(title)
            grid = QGridLayout(box)
            row = self._add_regression(grid, 0) if step["name"] == "motion" else 0
            for option in step["options"]:
                editor = OptionEditor(option, values.get(option["name"], option["default"]))
                editor.setToolTip(option["doc"])
                self.editors[option["name"]] = editor
                grid.addWidget(QLabel(option["label"] + ":"), row, 0)
                grid.addWidget(editor, row, 1)
                if option["doc"]:
                    grid.addWidget(_gray(option["doc"]), row + 1, 0, 1, 2)
                row += 2
            layout.addWidget(box)

        self.note = _gray("")
        layout.addWidget(self.note)
        self.problem = QLabel()                                      # (why the options cannot be used, when they cannot)
        self.problem.setStyleSheet("color: #c62828;")
        self.problem.setWordWrap(True)
        self.problem.hide()
        layout.addWidget(self.problem)
        buttons = QHBoxLayout()
        self.btn_apply = QPushButton("Apply")
        self.btn_apply.setDefault(True)
        self.btn_apply.clicked.connect(self._apply)
        self.btn_reset = QPushButton("Reset to Defaults")
        self.btn_reset.clicked.connect(self._reset)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        for button in (self.btn_apply, self.btn_reset, btn_cancel):
            buttons.addWidget(button)
        outer.addLayout(buttons)
        for editor in self.editors.values():
            editor.edited.connect(self._refresh_note)
        self.combo_regression.currentIndexChanged.connect(lambda _i: self._refresh_note())
        self._refresh_note()
        fit_dialog_to_content(self, body, min_width=520)

    def _add_regression(self, grid, row):
        """The motion-correction method, as the first row of a grid; returns the next free row."""
        grid.addWidget(QLabel("Regression method:"), row, 0)
        grid.addWidget(self.combo_regression, row, 1)
        grid.addWidget(_gray(REGRESSION_NOTE), row + 1, 0, 1, 2)
        return row + 2

    def regression_method(self):
        """The motion-correction method as the box stands ("ols", "ransac" or "huber")."""
        return self.combo_regression.currentData()

    def values(self):
        """{option name: value} of every option as the boxes stand."""
        return {name: editor.value() for name, editor in self.editors.items()}

    def changed(self):
        """{option name: value} of the options that are not at their default, as the boxes stand."""
        return {name: value for name, value in self.values().items() if value != self.defaults.get(name)}

    def _refresh_note(self):
        n = len(self.changed())
        method = self.regression_method()
        self.note.setText(f"{n} option{'s' if n != 1 else ''} not at the default" + ("" if method == "ols" else f"; {method.upper()} regression") + ".")
        self.problem.hide()

    def _apply(self):
        """Closes the window, accepted, if the library can use what is chosen; says why, and stays, if it cannot."""
        reason = api.pipeline.problem(self.values())
        if reason:
            self.problem.setText(reason)
            self.problem.show()
            return
        self.accept()

    def _reset(self):
        for name, editor in self.editors.items():
            editor.set_value(self.defaults.get(name, editor.option["default"]))
        self.combo_regression.setCurrentIndex(self.combo_regression.findData("ols"))
        self._refresh_note()


def pipeline_available(ctx):
    """Whether the recording on screen has a pipeline to write down (one the engine holds and says the options of); says why not, if it has not."""
    if ctx.cache is None or ctx.recording_id is None or not ctx.recording_pipeline:
        show_window_toast(ctx, "The pipeline belongs to a recording opened from TDT, Oxysoft or a table — open one first.")
        return False
    return True


class PipelineTextDialog(QDialog):
    """The methods paragraph for the recording on screen, to read, copy or save."""

    def __init__(self, parent, ctx, text):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Pipeline — methods text")
        self.resize(640, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(_gray(
            "Written from what was done to this recording: the options it was processed with, its motion-correction method and splices, and the software "
            "versions. Read it against what you did before you cite it."))
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        font = QFont()
        font.setPointSize(10)
        self.text.setFont(font)
        self.text.setPlainText(text)
        layout.addWidget(self.text, stretch=1)
        row = QHBoxLayout()
        self.btn_copy = QPushButton("Copy")
        self.btn_copy.clicked.connect(self._copy)
        self.btn_save = QPushButton("Save as Text…")
        self.btn_save.clicked.connect(self._save)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        for button in (self.btn_copy, self.btn_save):
            row.addWidget(button)
        row.addStretch(1)
        row.addWidget(btn_close)
        layout.addLayout(row)

    def _copy(self):
        QApplication.clipboard().setText(self.text.toPlainText())
        show_window_toast(self.ctx, "Pipeline text copied")

    def _save(self):
        from ..context import export_file

        def _write(path):
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(self.text.toPlainText() + "\n")

        store = (self.ctx.cache or {}).get("store") or "Data"
        export_file(self.ctx, self, "Save Pipeline Text", f"Pipeline_{store}.txt", "Text (*.txt)", _write)


def open_pipeline_text(ctx):
    """Copy pipeline (status bar): asks the engine to write the methods paragraph for the recording on screen, then shows it."""
    from .. import __version__

    if not pipeline_available(ctx):
        return None
    try:
        ref = recording_ref(ctx)
    except BackendError as e:
        show_error(ctx, f"The pipeline text could not be written: {e}")
        return None
    errorlog.action("pipeline_text")
    return run_engine(ctx, "methods.text", {"recording": ref, "app": {"name": "PyAT", "version": __version__}},
                      lambda answer: PipelineTextDialog(ctx.win, ctx, answer["text"]).exec(),
                      lambda message: show_error(ctx, f"The pipeline text could not be written: {message}"), label="Writing the pipeline text")
