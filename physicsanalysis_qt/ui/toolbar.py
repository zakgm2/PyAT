"""
ui/toolbar.py
---------------
Builds the top toolbar: Open menu, the Analysis button, view
controls, and (pushed to the far right via a stretch, so it sits in the
window's top-right corner) the Options gear icon. Grid visibility lives
in the Edit Attributes dialog (edit/attributes.py); Add Marker, Splice, Save
Markers, and Measure Intervals live in the left icon sidebar
(edit_toolbar.py), not here.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QMenu, QLabel, QToolButton,
)

from ..loading.tdt import open_folder, reload_folder
from ..loading.oxysoft import open_file, reload_file
from ..loading.generic import launch_generic_file_loader, reload_generic
from ..loading.pt2 import launch_pt2_viewer
from ..fieldstudy.open_study import open_field_study_folder
from ..plot.plotting import export_canvas_action
from ..plot.plot_signal import build_plot_signal_control
from ..edit.attributes import open_attributes_window
from ..app.options import open_options_dialog
from ..app.toasts import show_error
from ..analysis.window_settings import init_window_settings
from ..analysis.analysis_picker import open_analysis_menu
from ..fieldstudy.results import launch_field_study_results
from ..fieldstudy.validation import launch_field_study_validation
from ..analysis.custom_statistics import launch_custom_statistics
from ..analysis.open_results import open_results


def _reload_current(ctx):
    """Re-read whatever's currently loaded from disk, in place — not the
    same thing as Open, which always prompts a file picker. Falls back to
    Open only when nothing's loaded yet (there's nothing to reload)."""
    if ctx.cache is None:
        open_folder(ctx)
        return
    source = ctx.cache.get('source')
    path = ctx.cache.get('source_path')
    if not path:
        show_error(ctx, "Nothing to reload — no source file/folder on record.")
        return
    ctx.original_cache = None  # a fresh disk read makes any saved pre-splice cache stale
    if source == 'TDT':
        reload_folder(ctx, path)
    elif source == 'Oxysoft':
        reload_file(ctx, path)
    elif source == 'Generic':
        reload_generic(ctx, path)
    else:
        show_error(ctx, f"Reload isn't supported for '{source}' data.")


def build_toolbar(ctx):
    toolbar = QWidget()
    layout = QHBoxLayout(toolbar)
    layout.setContentsMargins(8, 6, 8, 6)

    open_menu_btn = QPushButton("Open ▾")
    open_menu = QMenu(open_menu_btn)
    open_menu.addAction("Open TDT Folder", lambda: open_folder(ctx))
    open_menu.addAction("Open TXT (Oxysoft)", lambda: open_file(ctx))
    open_menu.addAction("Open Excel/CSV/TSV", lambda: launch_generic_file_loader(ctx))
    open_menu.addAction("Open PT2 (EFNMR)", lambda: launch_pt2_viewer(ctx))
    open_menu.addSeparator()
    act_results = open_menu.addAction("Open Results…", lambda: open_results(ctx))
    act_results.setToolTip("Look at a finished analysis again: a group analysis's folder (pick its analysis_settings.json), "
                           "an analysis' .provenance.json record, or an exported table (.csv).")
    open_menu_btn.setMenu(open_menu)
    layout.addWidget(open_menu_btn)

    btn_reload = QPushButton("Reload")
    btn_reload.clicked.connect(lambda: _reload_current(ctx))
    layout.addWidget(btn_reload)

    layout.addWidget(QLabel("|"))

    field_study_menu_btn = QPushButton("Text Field Study ▾")
    field_study_menu = QMenu(field_study_menu_btn)
    act_open_study = field_study_menu.addAction(
        "1. Open Study Folder…", lambda: open_field_study_folder(ctx))
    act_open_study.setToolTip("Pick a folder and choose which fields to compare — "
                               "results open automatically when it's done.")
    act_reopen_results = field_study_menu.addAction(
        "Reopen Last Results", lambda: launch_field_study_results(ctx))
    act_reopen_results.setToolTip("Results already opened automatically after step 1 — "
                                   "use this only if you closed that window and want it back.")
    act_validate = field_study_menu.addAction(
        "2. Statistical Validation", lambda: launch_field_study_validation(ctx))
    act_validate.setToolTip("Optional follow-up once you have results: is the similarity "
                             "you're seeing likely real, and how confident should you be?")
    field_study_menu_btn.setMenu(field_study_menu)
    layout.addWidget(field_study_menu_btn)

    layout.addWidget(QLabel("|"))

    btn_custom_stats = QPushButton("Custom Statistics")
    btn_custom_stats.clicked.connect(lambda: launch_custom_statistics(ctx))
    layout.addWidget(btn_custom_stats)

    # Analysis: a button like Custom Statistics — opens a picker (FFT,
    # Z-Score, AUC, Curve Fit, plus the analysis window setting), then
    # asks you to double-click the graph. See analysis/analysis_picker.py.
    init_window_settings(ctx)
    ctx.btn_analysis = QPushButton("Analysis")
    ctx.btn_analysis.setToolTip(
        "Analysis — pick FFT, Z-Score, AUC or Curve Fit, then click on the graph. "
        "The analysis window (seconds around the click) is set here too.")
    ctx.btn_analysis.clicked.connect(lambda: open_analysis_menu(ctx))
    layout.addWidget(ctx.btn_analysis)

    layout.addWidget(build_plot_signal_control(ctx))

    layout.addWidget(QLabel("|"))

    btn_export_view = QPushButton("Export View")
    btn_export_view.clicked.connect(lambda: export_canvas_action(ctx))
    layout.addWidget(btn_export_view)

    btn_edit_attrs = QPushButton("Edit Attributes")
    btn_edit_attrs.clicked.connect(lambda: open_attributes_window(ctx))
    layout.addWidget(btn_edit_attrs)

    layout.addStretch(1)

    # Gear icon, pushed to the far right by the stretch above so it sits
    # in the window's top-right corner — deliberately sized larger than
    # a normal toolbar button (this row's height is otherwise ~30px) so
    # it reads clearly as its own thing, not just another button in the
    # row.
    btn_options = QToolButton()
    btn_options.setText("⚙")  # ⚙
    btn_options.setFont(QFont("Segoe UI Emoji", 20))
    btn_options.setFixedSize(40, 40)
    btn_options.setToolTip("Options")
    btn_options.setAutoRaise(True)
    btn_options.setCursor(Qt.CursorShape.PointingHandCursor)
    btn_options.clicked.connect(lambda: open_options_dialog(ctx))
    layout.addWidget(btn_options)

    return toolbar
