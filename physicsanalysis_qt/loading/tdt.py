"""
loading/tdt.py
--------------
TDT tank folder loading. TDT's own event markers (epocs) are populated
automatically via PyATCLI's process_tdt_folder().

open_folder() also handles picking a *parent* directory containing
several TDT block subfolders instead of one directly
(PyATCLI.find_tdt_recordings, _MultiTDTModeDialog,
_TDTFolderPickerDialog) — reports how many it found and asks Single
Experiment Analysis (pick one to open) or Hypothesis Testing (group
analysis across them, see analysis/group).

What a loaded recording *is* (the cache dict) is built by PyATCLI's
recording.py, so a script gets the same one; the reading itself happens in the
analysis engine (backend/), a second process, so a large tank never freezes the
window. This module drives the dialogs and the choice of folder.
"""

import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QButtonGroup, QListWidget, QFileDialog,
)

from .common import open_recording
from ..app.background import run_engine
from ..app.toasts import show_error, show_window_toast


def open_folder(ctx):
    start_dir = ctx.last_dir or ctx.settings["default_folder"]
    path = QFileDialog.getExistingDirectory(ctx.win, "Open Data Folder", start_dir)
    if not path:
        return
    ctx.last_dir = path

    # The engine looks at the folder (a walk of a whole cohort folder, on a network drive, can take seconds) and says what it is.
    run_engine(ctx, "files.inspect", {"path": path}, lambda info: _after_inspect(ctx, path, info),
               lambda message: show_error(ctx, message), label="Looking for recordings")


def _after_inspect(ctx, path, info):
    # The common case: the picked folder is itself one TDT block — load it
    # exactly as before, no extra prompt. The multi-folder flow below only
    # kicks in when someone picks a *parent* directory instead (e.g. a
    # cohort folder full of per-animal/per-session TDT block subfolders).
    if info["valid"]:
        _load_folder(ctx, path)
        return

    found = info["recordings"]
    if not found:
        show_error(ctx, "No TDT folders found in the selected directory.")
        return

    if len(found) == 1:
        _load_folder(ctx, found[0])
        return

    _prompt_multi_tdt(ctx, found, path)


class _MultiTDTModeDialog(QDialog):
    """Shown when Open Data Folder finds more than one TDT block inside
    the picked directory — reports the count and asks how to proceed.
    Hypothesis Testing opens the group analysis setup (analysis/group)
    over every recording found. Single Experiment Analysis is today's
    normal single-folder flow, just with a folder to pick from afterward."""

    def __init__(self, parent, n_found):
        super().__init__(parent)
        self.mode = None
        self.setWindowTitle("Multiple TDT Folders Found")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            f"Found {n_found} TDT recordings under this directory (searched every\n"
            "subfolder, any depth) — anything else in there was ignored. How do\n"
            "you want to proceed?"
        ))

        self.rb_single = QRadioButton("Single Experiment Analysis — pick one recording to open")
        self.rb_single.setChecked(True)
        self.rb_hypothesis = QRadioButton("Group Analysis - compare across recordings")
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.rb_single)
        mode_group.addButton(self.rb_hypothesis)
        layout.addWidget(self.rb_single)
        layout.addWidget(self.rb_hypothesis)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("Continue")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _accept(self):
        self.mode = "hypothesis" if self.rb_hypothesis.isChecked() else "single"
        self.accept()


class _TDTFolderPickerDialog(QDialog):
    """Single-Experiment-Analysis follow-up: pick exactly one of the
    folders PyATCLI.find_tdt_recordings found to actually load.

    Labels each entry with its path relative to the top folder that was
    searched, not just its own basename — find_tdt_recordings can now
    find folders nested at different depths (e.g. a subcohort folder
    full of per-animal folders), and two of those could easily share a
    basename (two different subcohorts each having their own
    "Animal1_Day1"); the bare name alone couldn't tell them apart."""

    def __init__(self, parent, folders, base_path):
        super().__init__(parent)
        self.folders = folders
        self.chosen = None
        self.setWindowTitle("Choose a Recording")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Which recording do you want to open?"))

        self.list_widget = QListWidget()
        self.list_widget.addItems([os.path.relpath(f, base_path) for f in folders])
        self.list_widget.setCurrentRow(0)
        self.list_widget.itemDoubleClicked.connect(lambda _: self._accept())
        layout.addWidget(self.list_widget, stretch=1)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("Open")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _accept(self):
        row = self.list_widget.currentRow()
        if row >= 0:
            self.chosen = self.folders[row]
        self.accept()


def _prompt_multi_tdt(ctx, found, base_path):
    mode_dlg = _MultiTDTModeDialog(ctx.win, len(found))
    if mode_dlg.exec() != QDialog.DialogCode.Accepted:
        return

    if mode_dlg.mode == "hypothesis":
        from ..analysis.group import launch_group_analysis
        launch_group_analysis(ctx, found, base_path)
        return

    picker = _TDTFolderPickerDialog(ctx.win, found, base_path)
    if picker.exec() == QDialog.DialogCode.Accepted and picker.chosen:
        _load_folder(ctx, picker.chosen)


def reload_folder(ctx, folder_path):
    """Re-run the load for a folder already on disk — no file dialog,
    used by the toolbar's Reload button to re-read the currently loaded
    TDT folder from scratch instead of asking the user to pick it again."""
    _load_folder(ctx, folder_path)


def _load_folder(ctx, folder_path):
    regression_method = ctx.settings.get("regression_method", "ols")

    def _after(opened):
        # No "Folder: X" here — the plot's own title already shows the store name (see
        # plot/plotting.py), so that would just repeat what's already on screen. The inlier
        # fraction is the only thing actually worth a toast for: it isn't shown anywhere else,
        # and it's the number that matters when comparing regression methods on the same
        # recording. Nothing to add for a single-channel recording (no motion correction ran),
        # so no toast at all — the plot appearing is confirmation enough. (The fit of the
        # recording as recorded, not of what a saved splice left of it.)
        recorded = opened.original_cache if opened.original_cache is not None else opened.cache
        inlier_fraction = recorded.get('motion_correction_inlier_fraction')
        if inlier_fraction is not None:
            show_window_toast(
                ctx, f"{opened.regression_method.upper()} motion correction kept "
                     f"{inlier_fraction * 100:.0f}% of samples as inliers")

    # The engine validates the folder, reads and processes it, replays the saved splices and puts the
    # saved markers, highlights, text boxes and signal names on — see loading/common.py.
    open_recording(ctx, folder_path, load={"regression_method": regression_method}, label="Loading TDT folder",
                   reset_signal=True, after=_after)
