"""
loading/drop.py
---------------
Drag and drop: drop a file or a folder anywhere on the main window to open it, the same as picking it in the Open menu.

    a TDT folder (or a folder holding TDT folders)    -> Open TDT Folder
    several TDT folders                               -> the same question as a parent folder holding several: Single Experiment or Group Analysis
    an Oxysoft .txt export                            -> Open TXT (Oxysoft)
    .xlsx .xls .csv .tsv .dat, any other .txt         -> Open Excel/CSV/TSV (the table and column picker)
    a .pt2 image                                      -> Open PT2 (EFNMR)
    a .provenance.json, or a folder with an           -> Open Results
      analysis_settings.json in it

Several folders dropped together are all looked at (a folder may be a TDT block or hold several) and, if that makes more than one recording, they get what picking a
parent folder that holds several gets: the Single Experiment or Group Analysis question. Any other mix of items: the window holds one recording, so the first is
opened and a message says how many were left. What a dropped path is
comes from the engine (`files.inspect`, which also tells an Oxysoft export from other text), so the drop opens it exactly as the Open menu would, with the
same progress toast and the same messages (including "package not installed" for a reader that is not installed). Nothing is opened for a path the
engine cannot see, and a drop while a load is running is refused like a second Open is.

What the window shows about all this is ui/drop_overlay.py: while a drag is over it, the plot area says what dropping would open; with nothing loaded, a card says
files can be dropped there.

The plot widgets may accept drops themselves (a QGraphicsView does), and then Qt would never offer the drop to the main window; an application-level
event filter, limited to widgets of the main window, takes the drops first.
"""

import os

from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtWidgets import QApplication, QWidget

from . import generic, oxysoft, pt2, tdt
from ..analysis.open_results import open_results
from ..app import errorlog
from ..app.background import run_engine
from ..app.toasts import show_error, show_window_toast
from ..ui.drop_overlay import DropOverlay

TABLE_SUFFIXES = (".xlsx", ".xls", ".csv", ".tsv", ".dat")
RESULTS_NAMES = ("analysis_settings.json",)
RESULTS_SUFFIXES = (".provenance.json",)
SUPPORTED = ("a TDT folder", "an Oxysoft .txt export", "an Excel, CSV or TSV table", "a .pt2 image", "a results file (.provenance.json)")
KIND_NAMES = {"folder": "TDT folder", "results": "saved results", "pt2": ".pt2 image", "text": "text file", "table": "table"}
HINT = ("Drag a file or folder here to open it",
        "A TDT folder, an Oxysoft .txt export, an Excel, CSV or TSV table, a .pt2 image or saved results. The Open menu above does the same.")


def classify(path):
    """What a dropped path is judged by its name alone: "folder", "results", "pt2", "text" (a .txt: an Oxysoft export or a plain table, the engine
    tells which), "table", or None for a file this program does not open. A folder with an analysis_settings.json in it is "results"."""
    if os.path.isdir(path):
        return "results" if os.path.isfile(os.path.join(path, RESULTS_NAMES[0])) else "folder"
    name = os.path.basename(path).lower()
    if name in RESULTS_NAMES or name.endswith(RESULTS_SUFFIXES):
        return "results"
    if name.endswith(".pt2"):
        return "pt2"
    if name.endswith(".txt"):
        return "text"
    if name.endswith(TABLE_SUFFIXES):
        return "table"
    return None


def local_paths(mime):
    """The local files and folders a drag carries, in order (a link to a web page is not one)."""
    return [url.toLocalFile() for url in mime.urls() if url.isLocalFile() and url.toLocalFile()] if mime.hasUrls() else []


def describe(paths):
    """The words the status bar shows over a drag: what dropping would open."""
    first = paths[0]
    kind = classify(first)
    if len(paths) > 1 and all(classify(p) == "folder" for p in paths):
        return f"Drop to open {len(paths)} folders (Single Experiment or Group Analysis)"
    if kind is None:
        return f"Cannot open {os.path.basename(first)}: drop {', '.join(SUPPORTED[:-1])} or {SUPPORTED[-1]}"
    more = f" (and {len(paths) - 1} more, which will be skipped)" if len(paths) > 1 else ""
    return f"Drop to open {os.path.basename(first.rstrip('/' + os.sep)) or first}{more}"


def explain(paths):
    """(ok, title, detail): what the overlay (ui/drop_overlay.py) says over a drag. `ok` is False for what cannot be opened."""
    first = paths[0]
    name = os.path.basename(first.rstrip("/" + os.sep)) or first
    if len(paths) > 1 and all(classify(p) == "folder" for p in paths):
        return True, f"Drop to open {len(paths)} folders", "You will be asked whether to look at one recording or compare them (Single Experiment or Group Analysis)."
    kind = classify(first)
    if kind is None:
        return False, "This cannot be opened", f"{name}\nDrop {', '.join(SUPPORTED[:-1])} or {SUPPORTED[-1]}."
    more = f"\n{len(paths) - 1} more dropped with it will be skipped (one recording at a time)." if len(paths) > 1 else ""
    return True, "Drop to open", f"{name} ({KIND_NAMES[kind]}){more}"


def open_dropped(ctx, paths):
    """Opens the first of `paths` the way the Open menu would; says so when others are left. Returns what it did (for the tests): the kind opened, or None."""
    paths = [p for p in paths if p]
    if not paths:
        return None
    path = paths[0]
    kind = classify(path)
    if len(paths) > 1 and all(classify(p) == "folder" for p in paths):
        errorlog.action("drop", kind="folders", n_items=len(paths))
        ctx.last_dir = os.path.dirname(paths[0].rstrip("/" + os.sep))
        tdt.open_folders_paths(ctx, paths)
        return "folders"
    errorlog.action("drop", kind=kind or "unsupported", n_items=len(paths))
    if kind is None:
        show_error(ctx, f"Cannot open {os.path.basename(path)}.\n\nDrop {', '.join(SUPPORTED[:-1])} or {SUPPORTED[-1]}.")
        return None
    if len(paths) > 1:
        show_window_toast(ctx, f"Opening {os.path.basename(path.rstrip('/' + os.sep)) or path}; {len(paths) - 1} other item(s) skipped (one recording at a time)")
    ctx.last_dir = path if os.path.isdir(path) else os.path.dirname(path)

    if kind == "folder":
        tdt.open_folder_path(ctx, path)
    elif kind == "pt2":
        pt2.open_pt2_path(ctx, path)
    elif kind == "table":
        generic._load_generic_path(ctx, path)
    elif kind == "results":
        open_results(ctx, path=os.path.join(path, RESULTS_NAMES[0]) if os.path.isdir(path) else path)
    else:                                                                        # a .txt: the engine says whether it is an Oxysoft export
        def _route(info):
            if info["kind"] == "oxysoft":
                oxysoft._load_single_file(ctx, path)
            else:
                generic._load_generic_path(ctx, path)

        run_engine(ctx, "files.inspect", {"path": path}, _route, lambda message: show_error(ctx, message))
    return kind


class _DropFilter(QObject):
    """Takes drag and drop events for widgets of the main window (see the module's docstring for why this is not dragEnterEvent on the window)."""

    def __init__(self, ctx):
        super().__init__(ctx.win)
        self.ctx = ctx

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind not in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop, QEvent.Type.DragLeave):
            return False
        if not isinstance(obj, QWidget) or obj.window() is not self.ctx.win:                 # a dialog's own drops are its business
            return False
        if kind == QEvent.Type.DragLeave:
            self.ctx.status_bar.clearMessage()
            self.ctx.drop_overlay.end_drag()
            return False
        paths = local_paths(event.mimeData())
        if not paths:
            return False
        if kind == QEvent.Type.Drop:
            self.ctx.status_bar.clearMessage()
            self.ctx.drop_overlay.end_drag()
            event.acceptProposedAction()
            open_dropped(self.ctx, paths)
            return True
        event.acceptProposedAction()
        if kind == QEvent.Type.DragEnter:
            self.ctx.status_bar.showMessage(describe(paths))
            self.ctx.drop_overlay.begin_drag(*explain(paths))
        return True


def install_drop(ctx):
    """Lets files and folders be dropped on the main window. Called once, when the window is built."""
    ctx.win.setAcceptDrops(True)
    ctx.drop_overlay = DropOverlay(ctx, ctx.stacked_plot_widget)
    ctx.drop_overlay.hint = HINT
    ctx.drop_overlay.refresh()
    ctx._drop_filter = _DropFilter(ctx)
    QApplication.instance().installEventFilter(ctx._drop_filter)
