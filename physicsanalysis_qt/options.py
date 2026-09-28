"""
options.py
----------
Options dialog: default folder for Open dialogs, performance settings
(render decimation, background loading), and plot engine selection
(matplotlib/CPU vs PyQtGraph/GPU).
"""

import os

from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QSpinBox, QComboBox, QFileDialog, QGroupBox,
    QMessageBox,
)

from . import plotting
from .window_fit import scroll_body, fit_dialog_to_content


_ENGINE_LABELS = {
    "matplotlib": "Matplotlib (CPU)",
    "pyqtgraph":  "PyQtGraph (GPU-accelerated)",
    "vispy":      "VisPy (OpenGL, experimental)",
}
_ENGINE_VALUES = {v: k for k, v in _ENGINE_LABELS.items()}

_REGRESSION_LABELS = {
    "ols":    "OLS (default — plain least-squares, no robustness)",
    "ransac": "RANSAC (excludes severe artifacts entirely)",
    "huber":  "Huber (downweights outliers instead of excluding them)",
}
_REGRESSION_VALUES = {v: k for k, v in _REGRESSION_LABELS.items()}


class OptionsDialog(QDialog):
    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Options")
        outer, layout, body = scroll_body(self)  # see window_fit.py

        gb_theme = QGroupBox("Appearance")
        gt = QGridLayout(gb_theme)
        gt.addWidget(QLabel("Theme:"), 0, 0)
        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["Light", "Dark"])
        self.combo_theme.setCurrentText(ctx.settings.get("theme", "light").capitalize())
        gt.addWidget(self.combo_theme, 0, 1)
        layout.addWidget(gb_theme)

        gb_engine = QGroupBox("Plot Engine (main plot only)")
        g0 = QGridLayout(gb_engine)
        g0.addWidget(QLabel("Engine:"), 0, 0)
        self.combo_engine = QComboBox()
        self.combo_engine.addItems(list(_ENGINE_LABELS.values()))
        self.combo_engine.setCurrentText(_ENGINE_LABELS[ctx.settings["plot_engine"]])
        g0.addWidget(self.combo_engine, 0, 1)
        engine_note = QLabel(
            "PyQtGraph is GPU-accelerated and handles large recordings much better.\n"
            "VisPy is OpenGL/GPU-native but still an early, work-in-progress engine\n"
            "here — markers, legend, and most interactions aren't wired up yet.\n"
            "Legend position (below) is matplotlib-only. FFT/PETH/Curve Fit/PT2\n"
            "windows always use matplotlib either way."
        )
        engine_note.setStyleSheet("color: gray;")
        engine_note.setWordWrap(True)
        g0.addWidget(engine_note, 1, 0, 1, 2)
        layout.addWidget(gb_engine)

        gb_regression = QGroupBox("Motion Correction (TDT)")
        gr = QGridLayout(gb_regression)
        gr.addWidget(QLabel("Regression:"), 0, 0)
        self.combo_regression = QComboBox()
        self.combo_regression.addItems(list(_REGRESSION_LABELS.values()))
        self.combo_regression.setCurrentText(
            _REGRESSION_LABELS[ctx.settings.get("regression_method", "ols")])
        gr.addWidget(self.combo_regression, 0, 1)
        regression_note = QLabel(
            "Used to regress the isosbestic (415nm) stream onto the signal (465nm)\n"
            "stream during motion correction. Clicking OK reprocesses the currently\n"
            "loaded TDT recording with the new method right away — no separate Reload\n"
            "needed — and it applies to anything opened after this point too.\n"
            "The three methods can give noticeably different results on the same\n"
            "recording (e.g. how much of a transient near a motion artifact survives) —\n"
            "worth trying each one to see what you actually get before settling on\n"
            "one for a given dataset."
        )
        regression_note.setStyleSheet("color: gray;")
        regression_note.setWordWrap(True)
        gr.addWidget(regression_note, 1, 0, 1, 2)
        layout.addWidget(gb_regression)

        gb_folder = QGroupBox("Folders")
        g1 = QGridLayout(gb_folder)
        g1.addWidget(QLabel("Default folder (Open dialogs):"), 0, 0)
        self.e_folder = QLineEdit(ctx.settings["default_folder"])
        g1.addWidget(self.e_folder, 0, 1)
        btn_browse = QPushButton("📁 Browse…")
        btn_browse.clicked.connect(self._browse)
        g1.addWidget(btn_browse, 0, 2)

        g1.addWidget(QLabel("Output folder (exports):"), 1, 0)
        self.e_output_folder = QLineEdit(ctx.settings.get("output_folder", ""))
        self.e_output_folder.setPlaceholderText("(same as last-opened folder)")
        g1.addWidget(self.e_output_folder, 1, 1)
        btn_browse_output = QPushButton("📁 Browse…")
        btn_browse_output.clicked.connect(self._browse_output)
        g1.addWidget(btn_browse_output, 1, 2)

        output_note = QLabel(
            "When set, CSV/PNG/PDF/SVG exports (Curve Fit, FFT, PETH, AUC,\n"
            "plot exports, …) save straight here with no dialog at all — into\n"
            "<this folder>/<TDT or Oxysoft or Generic or …>/<recording name>/,\n"
            "so one recording's exports collect together across reloads and\n"
            "sessions instead of piling up flat. Leave blank to get a save\n"
            "dialog instead, seeded from wherever you last opened a file."
        )
        output_note.setStyleSheet("color: gray;")
        output_note.setWordWrap(True)
        g1.addWidget(output_note, 2, 0, 1, 3)
        layout.addWidget(gb_folder)

        gb_perf = QGroupBox("Performance (matplotlib engine)")
        g2 = QGridLayout(gb_perf)
        g2.addWidget(QLabel("Max rendered points per trace:"), 0, 0)
        self.spin_points = QSpinBox()
        self.spin_points.setRange(200, 20000)
        self.spin_points.setSingleStep(200)
        self.spin_points.setValue(ctx.settings["decimate_max_points"])
        g2.addWidget(self.spin_points, 0, 1)

        self.cb_threaded = QCheckBox(
            "Load data files on a background thread (default: on)\n"
            "Keeps the UI responsive (and the progress toast moving) during\n"
            "large loads and analyses instead of freezing until they finish."
        )
        self.cb_threaded.setChecked(ctx.settings["background_loading"])
        g2.addWidget(self.cb_threaded, 1, 0, 1, 2)

        threaded_note = QLabel(
            "Turn this off only if a load ever behaves strangely (hangs, wrong\n"
            "data, or a crash) — that would point to a thread-safety issue in\n"
            "the TDT/Oxysoft parsing code, and running on the main thread\n"
            "instead rules that out. Also useful when debugging a load error\n"
            "yourself: off gives the real traceback instead of a summarized\n"
            "error message."
        )
        threaded_note.setStyleSheet("color: gray;")
        threaded_note.setWordWrap(True)
        g2.addWidget(threaded_note, 2, 0, 1, 2)

        layout.addWidget(gb_perf)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._apply)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        outer.addLayout(btn_row)

        fit_dialog_to_content(self, body, min_width=500)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Default Folder", self.e_folder.text())
        if path:
            self.e_folder.setText(path)

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(
            self, "Output Folder", self.e_output_folder.text() or self.e_folder.text())
        if path:
            self.e_output_folder.setText(path)

    def _apply(self):
        folder = self.e_folder.text().strip()
        if folder and os.path.isdir(folder):
            self.ctx.settings["default_folder"] = folder

        output_folder = self.e_output_folder.text().strip()
        if not output_folder or os.path.isdir(output_folder):
            self.ctx.settings["output_folder"] = output_folder

        self.ctx.settings["decimate_max_points"] = self.spin_points.value()
        self.ctx.settings["background_loading"] = self.cb_threaded.isChecked()

        new_engine = _ENGINE_VALUES[self.combo_engine.currentText()]
        engine_changed = new_engine != self.ctx.settings["plot_engine"]
        self.ctx.settings["plot_engine"] = new_engine

        new_regression = _REGRESSION_VALUES[self.combo_regression.currentText()]
        regression_changed = new_regression != self.ctx.settings.get("regression_method", "ols")
        self.ctx.settings["regression_method"] = new_regression

        new_theme = self.combo_theme.currentText().lower()
        theme_changed = new_theme != self.ctx.settings.get("theme", "light")
        self.ctx.settings["theme"] = new_theme

        from .context import save_settings
        save_settings(self.ctx.settings)

        self.accept()

        if theme_changed:
            from .theme import apply_theme
            apply_theme(self.ctx.app, new_theme)
            if self.ctx.cache is not None:
                plotting.simple_plot(self.ctx)
            else:
                plotting.apply_theme_to_canvas(self.ctx)

        if engine_changed:
            from .ui.main_window import switch_plot_engine
            switch_plot_engine(self.ctx)

        if regression_changed and self.ctx.cache is not None and self.ctx.cache.get('source') == 'TDT':
            from .ui.toolbar import _reload_current
            _reload_current(self.ctx)


def open_options_dialog(ctx):
    dlg = OptionsDialog(ctx.win, ctx)
    dlg.exec()
