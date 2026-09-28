"""
loaders/tdt.py
---------------
TDT tank folder loading. TDT's own event markers (epocs) are populated
automatically via PhysicsLibrary's process_tdt_folder().

open_folder() also handles picking a *parent* directory containing
several TDT block subfolders instead of one directly (_find_tdt_subfolders,
_MultiTDTModeDialog, _TDTFolderPickerDialog) — reports how many it found
and asks Single Experiment Analysis (pick one to open) or Hypothesis
Testing (group analysis across them, see analysis/group).
"""

import os

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QButtonGroup, QListWidget, QFileDialog,
)

import PhysicsLibrary as pl

from ..background import run_in_background
from ..sidecar import load_markers_from_sidecar
from ..analysis.splice import load_splice_from_sidecar
from ..plot_signal import refresh_plot_signal_options
from ..toasts import show_error, show_window_toast

# Colors for the raw per-wavelength channels in the Plot dropdown/legend —
# keyed by the 'channels' entry key PhysicsLibrary's process_tdt_folder()
# reports, so a recording with a differently-named stream (any wavelength,
# any experimental setup) still gets a sensible, consistent color; only
# the two roles that function ever emits need an entry here.
_CHANNEL_COLORS = {
    "main_driver": "#2E7D32",  # green — conventional for the probe/signal channel
    "isosbestic":  "#7B1FA2",  # purple — conventional for the isosbestic control
}


def _build_signal_options(result):
    """Plot-option choices for the toolbar's "Plot:" dropdown: the
    computed normalized trace plus whatever raw per-wavelength channels
    this recording's process_tdt_folder() call found. Not hardcoded to
    exactly "Normalized/Isosbestic/Main Driver" — a block with no
    isosbestic reference stream just won't have that key, and any future
    channel role PhysicsLibrary reports shows up automatically with a
    fallback color."""
    options = {
        "normalized": {"label": "Normalized (dF/F)", "y": result["corr"], "color": "blue"},
    }
    for ch in result.get("channels", []):
        options[ch["key"]] = {
            "label": ch["label"],
            "y":     ch["y"],
            "color": _CHANNEL_COLORS.get(ch["key"], "#555555"),
        }
    return options


def _find_tdt_subfolders(path):
    """Every valid TDT block (has .Tbk files) anywhere under path, at any
    depth — a cohort folder containing per-subcohort folders that each
    contain the actual per-animal/per-session TDT blocks is a real lab
    layout, not just a flat one level down, so this has to walk the
    whole subtree rather than just path's immediate children. Anything
    that's never a valid TDT block anywhere in the tree (other folders,
    loose files of any type) is silently skipped, not reported, same as
    validate_tdt_folder already does for a single folder.

    Stops descending once a directory is confirmed to be a TDT block
    itself (topdown os.walk, pruning `dirs` in place) — its own internal
    files/subfolders are TDT's, not further recordings to find, and
    there's no reason to keep walking into them.

    Guards against a directory cycle (a folder that links back to one of
    its own ancestors, so the "further down" it looks like never bottoms
    out) by tracking each directory's *real*, symlink/junction-resolved
    identity rather than trusting os.walk's own followlinks=False
    default — confirmed by direct testing that that default does NOT
    catch a Windows NTFS junction cycle (os.path.islink() simply returns
    False for a junction, unlike a real symlink), which would otherwise
    have os.walk descend into the same real folder over and over,
    reporting it as more and more distinct-looking "finds" each time,
    stopped only by accidentally hitting the OS's path-length limit
    rather than by any real protection."""
    found = []
    visited_real_dirs = {os.path.realpath(path)}
    for root, dirs, _files in os.walk(path):
        kept = []
        for name in dirs:
            real = os.path.realpath(os.path.join(root, name))
            if real in visited_real_dirs:
                continue  # cycle — this real directory was already walked
            visited_real_dirs.add(real)
            kept.append(name)
        dirs[:] = kept

        if root == path:
            continue  # already checked by open_folder before calling here
        valid, _ = pl.validate_tdt_folder(root)
        if valid:
            found.append(root)
            dirs[:] = []  # don't walk into a confirmed TDT block's own contents
    found.sort()
    return found


def open_folder(ctx):
    start_dir = ctx.last_dir or ctx.settings["default_folder"]
    path = QFileDialog.getExistingDirectory(ctx.win, "Open Data Folder", start_dir)
    if not path:
        return
    ctx.last_dir = path

    # The common case: the picked folder is itself one TDT block — load it
    # exactly as before, no extra prompt. The multi-folder flow below only
    # kicks in when someone picks a *parent* directory instead (e.g. a
    # cohort folder full of per-animal/per-session TDT block subfolders).
    valid, _ = pl.validate_tdt_folder(path)
    if valid:
        _load_folder(ctx, path)
        return

    found = _find_tdt_subfolders(path)
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
    folders _find_tdt_subfolders found to actually load.

    Labels each entry with its path relative to the top folder that was
    searched, not just its own basename — _find_tdt_subfolders can now
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
    from ..plotting import simple_plot

    try:
        fmt = pl.detect_format(folder_path)
    except Exception as e:
        show_error(ctx, str(e))
        return

    if fmt.name != "TDT":
        show_error(ctx, "Only TDT folders are supported via 'Open TDT Folder'.")
        return

    regression_method = ctx.settings.get("regression_method", "ols")

    def _work(progress):
        valid, msg = pl.validate_tdt_folder(folder_path)
        if not valid:
            raise ValueError(f"TDT validation failed: {msg}")
        return pl.process_tdt_folder(folder_path, regression_method=regression_method, progress=progress)

    def _on_success(result):
        # A stale splice from whatever was loaded before this must not
        # carry over — Open (unlike Reload, which already clears this)
        # can load an entirely different folder.
        ctx.original_cache = None
        ctx._active_splices = []
        ctx._data_generation += 1
        ctx.cache = {
            'source':      'TDT',
            'source_path': folder_path,
            'store':       os.path.basename(folder_path.rstrip('/\\')),
            'x':           result['x'],
            'raw':         result['raw'],
            'corr':        result['corr'],
            'fs':          result['fs'],
            'detected_markers': result.get('markers', []),
            'markers':     [],
            'signals':     _build_signal_options(result),
        }
        ctx.plot_signal = "normalized"  # reset — a prior dataset's pick may not exist here
        # Splice MUST replay before markers load — a saved splice.json is
        # replayed against this fresh, unspliced cache (which starts with
        # 'markers': [] above), re-deriving x/raw/corr/detected_markers
        # from the raw data. markers.json, in contrast, already holds the
        # FINAL post-splice marker state as of the last Save Changes — it
        # needs to land after replay finishes and just overwrite outright,
        # not go through the cut/shift logic a second time. Loading it
        # first (the old order) fed markers.json's already-final,
        # possibly-post-splice timestamps through splice replay's own
        # cut/shift logic a second time, silently dropping any marker that
        # had been added after a splice (its post-splice timestamp got
        # reinterpreted as if it were on the original, unspliced timeline).
        load_splice_from_sidecar(ctx)
        load_markers_from_sidecar(ctx)
        refresh_plot_signal_options(ctx)
        simple_plot(ctx)
        # No "Folder: X" here — the plot's own title already shows the store name (see
        # plotting.py), so that would just repeat what's already on screen. The inlier
        # fraction is the only thing actually worth a toast for: it isn't shown anywhere else,
        # and it's the number that matters when comparing regression methods on the same
        # recording. Nothing to add for a single-channel recording (no motion correction ran),
        # so no toast at all — the plot appearing is confirmation enough.
        inlier_fraction = result.get('motion_correction_inlier_fraction')
        if inlier_fraction is not None:
            show_window_toast(
                ctx, f"{regression_method.upper()} motion correction kept "
                     f"{inlier_fraction * 100:.0f}% of samples as inliers")

    def _on_error(msg):
        show_error(ctx, msg)

    run_in_background(ctx, _work, _on_success, _on_error, label="Loading TDT folder")
