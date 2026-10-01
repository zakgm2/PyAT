"""
context.py
----------
Shared application state, passed explicitly to every function that needs
it. Replaces the module-level globals from the single-file version — a
plain object works fine here (this is a small desktop app, not a service),
but keeping it in one place instead of scattered globals means every
module can see exactly what state exists without hunting for `global`
statements.
"""

import json
import os
from pathlib import Path

from . import outputs

_MARKER_COLORS = ["green", "red", "blue", "orange", "purple", "black"]

_PHI = 1.6180339887  # golden ratio

_SETTINGS_PATH = Path.home() / ".physicsanalysis" / "settings.json"


def load_settings():
    settings = default_settings()
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        settings.update({k: v for k, v in saved.items() if k in settings})
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return settings


def save_settings(settings):
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)


def default_plot_attrs():
    return {
        "title":       None,
        "xlabel":      None,
        "ylabel":      None,
        "title_fs":    24,
        "xlabel_fs":   16,
        "ylabel_fs":   16,
        "leg_fs":      14,
        "leg_loc":     "upper left",
        "leg_entries": None,
        "bold":        True,
        "line_colors": {},  # {legend entry name: "#rrggbb"} — user overrides, see trace_color()
    }


def default_settings():
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    return {
        "default_folder":      desktop if os.path.isdir(desktop) else os.path.expanduser("~"),
        "output_folder":       "",  # "" = fall back to last-opened folder, then default_folder — see get_export_dir()
        "decimate_max_points": 2000,
        "background_loading":  True,
        "plot_engine":         "matplotlib",  # "matplotlib" | "pyqtgraph" | "vispy"
        "theme":               "light",       # "light" | "dark"
        "regression_method":   "ols",         # "ransac" | "huber" | "ols" — TDT motion correction, see PhysicsLibrary.REGRESSION_METHODS
    }


class AppState:
    """Holds every piece of mutable state the GUI needs, plus references
    to the widgets built in ui/main_window.py. Widget fields start as
    None and are filled in once during startup."""

    def __init__(self, app):
        # Qt
        self.app = app
        self.win = None
        self.status_bar = None

        # Matplotlib
        self.fig = None
        self.ax = None
        self.canvas = None
        self.rect_selector = None

        # PyQtGraph (GPU) engine — only populated if that engine is used
        self.stacked_plot_widget = None  # QStackedWidget holding both canvases
        self.pg_widget = None
        self.pg_plot_item = None
        self.pg_viewbox = None
        self.pg_lines = []            # (PlotDataItem, full_x, full_y)
        self._pg_axis_probe = None    # (left_axis_w, bottom_axis_h) cache — see sync_pg_margins
        self.pg_hover_scatter = None

        # VisPy (OpenGL, GPU-native) engine — only populated if that
        # engine is used. Built incrementally alongside pg_* above as
        # vispy_engine.py grows (see the VisPy build-stage plan).
        self.vispy_canvas = None        # vispy.scene.SceneCanvas
        self.vispy_view = None          # grid.add_view() result
        self.vispy_line_visuals = []    # (Line visual, full_x, full_y, raw_name)
        self.vispy_legend_widget = None # hand-built Qt overlay, not part of the scene
        self.vispy_marker_lines = []    # (Line visual, Text visual, marker_dict)
        self._vispy_press_pos = None    # (x, y) screen pixel — click-vs-drag detection
        self._vispy_press_button = None

        # Toolbar widgets (assigned in ui/toolbar.py)
        self.btn_analysis = None
        self.btn_add_marker = None

        # Which Analysis tool is armed for the next click on the graph: None,
        # or "Z-Score" / "FFT" / "AUC" / "Curve Fit" — see
        # analysis/analysis_picker.py, which sets it, and analysis/dispatch.py
        self.analysis_mode = None
        # The picker's "Persist through trials" checkbox: when True an armed
        # tool stays armed after each run instead of disarming after one.
        self.analysis_persist = False

        # Analysis window (pre/post seconds around a clicked event) — see
        # analysis/window_settings.py for the dialog (opened from the picker)
        self.window_pre = None
        self.window_post = None
        self.window_symmetric = True

        # Store id -> renamed display name (e.g. 'PP1_' -> 'Left Lever'),
        # set via right-click Edit Marker's "rename all" toggle — see
        # marker_labels.py. The store id itself never changes, only how
        # it's displayed everywhere (plot, dialogs, Event Intervals table).
        self.store_labels = {}

        # Data
        self.cache = None
        # The unspliced full recording, saved off the first time Splice
        # Recording is used, so Restore Full Recording can bring it back
        # without re-loading from disk. None when no splice is active.
        self.original_cache = None
        # List of {"mode": ..., "start": ..., "end": ...}, one per splice
        # currently applied, in the order they were applied — several can
        # stack (e.g. removing more than one artifact from the same
        # recording). What save_splice() (analysis/splice.py) writes to
        # the JSON saves/ sidecar. Empty when no splice is active.
        self._active_splices = []
        # Ctrl+Z stack (undo.py) — one snapshot per marker/splice-mutating action, most recent
        # last. Popped and restored wholesale by undo.undo(), not a bespoke inverse per action.
        self._undo_stack = []
        # Set by analysis/splice.py's start_splice_flow() while the user
        # is choosing what kind of splice, read by apply_splice_at_points().
        self._pending_splice_mode = None
        # True from a successful start_splice_flow() until the two clicks
        # it's waiting for are both in (apply_splice_at_points) — the
        # click handlers (interaction.py, pg_interaction.py) check this
        # directly — it's separate from analysis_mode above, since only the
        # sidebar's scissors icon starts a splice, not the Analysis button.
        self.splice_click_mode = False
        self.selected_path = None
        self.last_dir = None  # last folder browsed in any Open dialog
        # Which entry of cache['signals'] the main plot (and every
        # TDT-only analysis dialog) currently shows — e.g. "normalized",
        # "isosbestic", "main_driver". Only meaningful for a cache that
        # actually has a 'signals' map; see get_active_signal() below.
        # Reset to "normalized" on every fresh load (loaders/tdt.py) so a
        # previous dataset's selection (e.g. "isosbestic") never silently
        # carries over to one that doesn't have that channel.
        self.plot_signal = "normalized"
        # Which cache['signals'] entries are ticked in the toolbar's Plot dropdown — the main
        # plot overlays all of them at once (one line each) when there's more than one; analysis
        # tools still go through plot_signal (above) alone, see get_active_signal()'s docstring.
        self.plot_signals = {"normalized"}
        self.plot_signal_row = None          # QWidget row wrapping the dropdown button below
        self.plot_signal_button = None       # toolbar "Plot:" dropdown button, see plot_signal.py
        self.plot_signal_menu = None         # the button's QMenu of checkboxes
        self.plot_signal_checkboxes = {}     # {key: QCheckBox}, inside plot_signal_menu
        self.show_grid = True
        self.plot_attrs = default_plot_attrs()

        # Text field study data (see loaders/text_field_study.py) — a
        # pandas DataFrame, not the x/y/markers shape ctx.cache holds for
        # every signal-plot source, so it gets its own attribute rather
        # than overloading ctx.cache (which plotting/marker/analysis code
        # throughout the app assumes has that shape).
        self.study_data = None
        self.study_data_path = None
        self.study_data_config = None  # the field_study_config.py dict used for this load

        # (engine, generation) the view was last reset-to-fit for. Redraws
        # triggered by things that aren't a fresh data load (grid toggle,
        # marker add/edit, attribute changes, switching the Plot signal
        # dropdown) compare against this so they can preserve the current
        # zoom/pan instead of snapping back to the full-data view every
        # time — an actual new dataset OR switching engines (the other
        # engine's view never had valid data in it) resets it.
        #
        # Uses an explicit counter (below), not id(cache): a freed cache
        # dict's memory address can be reused by the very next dict CPython
        # allocates (same size/shape, back-to-back Open/Reload), which
        # would make id(new_cache) == id(old_cache) by pure coincidence —
        # silently treating a brand new recording as "unchanged" and
        # snapping the view to whatever was zoomed in the previous one.
        self._last_zoomed_key = None
        # Bumped exactly once every time ctx.cache is replaced with a
        # genuinely new dataset (Open/Reload, splice apply, restore full
        # recording) — never for an in-place redraw of the same dataset
        # (e.g. switching the Plot signal dropdown, which must NOT reset
        # the zoom). See _last_zoomed_key above.
        self._data_generation = 0

        # Marker mode
        self.marker_mode = False
        self.marker_stamp = {"label": "Marker", "color": "green", "fontsize": 8}

        # Hover / blit
        self.tracker_dots = []
        self.connecting_line = None
        self.active_snap_line = None
        self._hover_bg = None
        self._hover_bg_timer = None  # QTimer instance

        # Pan / drag
        self.is_dragging = False
        self.press_x = None
        self.press_y = None
        # True while RectangleSelector's own drag-to-zoom is in progress
        # (see interaction.py's on_press/on_motion/on_release) — suppresses
        # the hover tracker's own blit for the duration so the two blit
        # systems don't fight over the same canvas region.
        self._rect_dragging = False
        self._last_pan_draw_time = 0.0
        # Right-click-and-hold on a marker's label (matplotlib: interaction.py; PyQtGraph:
        # pg_interaction.py) — moves just that label up/down the marker's own line. None when no
        # drag is in progress; the marker dict being dragged while one is.
        self._dragging_label = None
        self._dragging_label_before = None  # undo.snapshot() taken at drag-start
        self._marker_label_artists = []  # matplotlib: (marker dict, Text artist), see plotting.py
        self._marker_label_lines = []    # PyQtGraph: (marker dict, InfiniteLine), see pg_engine.py

        # Highlighter tool (analysis/highlight.py) — click-to-arm two-click flow, same shape as
        # Splice's own splice_click_mode/_pending_splice_mode below.
        self.highlight_click_mode = False
        self._pending_highlight_color = None

        # Text tool (analysis/text_annotation.py) — click-to-place, then right-click-and-hold to
        # drag an existing one, or a plain right-click (no hold) to delete it.
        self.text_mode = False
        self.btn_text_tool = None  # toolbar icon button, see ui/edit_toolbar.py
        self._dragging_text = None         # the annotation dict being dragged, or None
        self._dragging_text_before = None  # undo.snapshot() taken at drag-start
        self._text_annotation_artists = []  # matplotlib: (annotation dict, Text artist)
        self._text_annotation_items = []    # PyQtGraph: (annotation dict, pg.TextItem)

        # Decimation: (line, full_x, full_y) for every plotted trace, so its
        # rendered vertex count can be kept bounded to the visible pixel
        # range regardless of how many samples the recording actually has.
        self._decim_lines = []

        # Curve fit click capture
        self.slope_clicks = []

        # Manual double-click detection for the matplotlib canvas (see
        # interaction.py's on_press) — matplotlib's own event.dblclick can
        # miss pairs because RectangleSelector's press handler also sees
        # the first click of a would-be double-click before we know it's
        # part of one, occasionally leaving its internal state out of sync
        # with matplotlib's click-timing tracker.
        self._last_click_time = 0.0
        self._last_click_xy = None

        # Settings (Options dialog) — persisted to disk, see load_settings/save_settings
        self.settings = load_settings()

        # Engine-agnostic cache of the computed default title/labels and
        # legend entry order, so Edit Attributes can read/apply consistent
        # values regardless of which engine actually rendered them.
        self._last_title = ""
        self._last_xlabel = ""
        self._last_ylabel = ""
        self._legend_entries = []  # list of label strings, in plotted order
        self._trace_default_colors = {}  # legend entry name -> color the engines drew it in by default

        # The one toast on screen (toasts.py keeps it to one at a time) and
        # the timer that will dismiss it, plus the separate pinned panel
        # (message + button, bottom-left) that toasts never touch.
        self._toast = None
        self._toast_timer = None
        self._pinned_panel = None
        self._toast_repositioner = None
        self._progress_toast = None  # the ProgressToast of the slow action running now, if any (toasts.py)

        # Background loading (Options: "Load data files on a background thread")
        self._bg_thread = None
        self._bg_worker = None


def trace_color(ctx, key, default):
    """The color to draw a main-plot trace in: the user's pick from Edit
    Attributes if there is one for this legend entry (`key` is its raw,
    un-renamed name), otherwise the engine's own `default`.

    Every engine draws its traces through this, so a pick applies the same
    way whichever engine is active. It also records `default` so the Edit
    Attributes dialog can show — and reset to — what a trace would be
    drawn in without an override."""
    ctx._trace_default_colors[key] = default
    return ctx.plot_attrs["line_colors"].get(key) or default


def get_active_signal(ctx):
    """Resolve the single "primary" signal — ctx.plot_signal — that every TDT-only analysis
    dialog (AUC, FFT, Curve Fit, Z-Score PETH) works on, as (key, label, y, color). The main
    plot's toolbar row can have several boxes ticked at once for overlay display (see
    get_checked_signals below), but an analysis tool still needs exactly one signal to run
    against — ctx.plot_signal tracks whichever was checked/clicked most recently, so it's always
    the one you were most recently looking at, ticked or not.

    cache['signals'] is a dict built by the loader (see loaders/tdt.py)
    mapping a plot-option key ("normalized", "isosbestic", "main_driver",
    ...) to {"label", "y", "color"} — deliberately not hardcoded to
    exactly those three: a recording with no isosbestic reference stream
    just won't have that key, and this still works. Sources that don't
    offer more than one plottable signal (Oxysoft, Generic — they already
    plot every channel at once) have no 'signals' map at all, so this
    falls back to the cache's default normalized trace directly.
    """
    cache = ctx.cache
    signals = cache.get('signals')
    if not signals:
        y = cache['corr'] if 'corr' in cache else cache['raw']
        return "normalized", "dF/F (corrected)", y, 'blue'
    key = ctx.plot_signal if ctx.plot_signal in signals else next(iter(signals))
    sig = signals[key]
    return key, sig['label'], sig['y'], sig['color']


def get_checked_signals(ctx):
    """The TDT plot signals currently ticked in the toolbar's Plot row, in cache['signals']
    order, as [(key, {"label", "y", "color"}), ...] — what the main plot draws, one line each.
    Falls back to [get_active_signal's key] if somehow nothing is ticked (the UI itself always
    keeps at least one box checked), so a caller never ends up drawing nothing at all."""
    cache = ctx.cache
    signals = cache.get('signals') if cache else None
    if not signals:
        return []
    checked = ctx.plot_signals & signals.keys()
    if not checked:
        key = ctx.plot_signal if ctx.plot_signal in signals else next(iter(signals))
        checked = {key}
    return [(key, sig) for key, sig in signals.items() if key in checked]


def get_normalized_signal(ctx):
    """Like get_active_signal, but always resolves to the normalized
    (dF/F) trace regardless of what ctx.plot_signal / the main plot's
    "Plot:" dropdown currently shows. Every analysis dialog (Curve Fit,
    FFT, Z-Score PETH, Event PETH, Peak Finder, AUC) must analyze the
    same normalized signal no matter which signal is currently being
    *displayed* — this exists specifically to decouple that from
    get_active_signal, which the plotting engines' own render calls keep
    using unchanged so the main plot still honors the dropdown.
    """
    cache = ctx.cache
    signals = cache.get('signals')
    if not signals:
        y = cache['corr'] if 'corr' in cache else cache['raw']
        return "normalized", "dF/F (corrected)", y, 'blue'
    key = "normalized" if "normalized" in signals else next(iter(signals))
    sig = signals[key]
    return key, sig['label'], sig['y'], sig['color']


def get_export_dir(ctx):
    """Starting directory for every *save* dialog (CSV/PNG/PDF/SVG
    exports) — settings["output_folder"] if the user has set one
    (Options → Output Folder), else the same last-opened-folder-then-
    default-folder fallback these dialogs used before that setting
    existed. Deliberately separate from settings["default_folder"],
    which only seeds *Open* dialogs — pinning exports to one folder
    shouldn't also redirect where Open starts browsing from, and vice
    versa."""
    return ctx.settings.get("output_folder") or ctx.last_dir or ctx.settings["default_folder"]


def export_file(ctx, parent, title, default_filename, filter_str, write_fn,
                dest_dir=None, recording_type=None, recording_source=None):
    """Saves an export (a figure image or a CSV) to disk. write_fn(path)
    does the actual writing — called once a destination is settled,
    either way below.

    If settings["output_folder"] is set (Options → Output Folder), saves
    straight there — into a folder for the current recording's data type,
    then one for the recording itself (outputs.recording_dir), so a
    recording's exports accumulate together instead of piling up flat —
    with no dialog at all, just a confirmation toast. A repeat export never
    silently replaces the last one either way: outputs.unique_path() adds
    " (2)", " (3)", ... to default_filename if something is already there.
    Otherwise (no output folder set) prompts via a save dialog seeded from
    get_export_dir(ctx), exactly like every export already did before that
    setting existed — a native dialog already asks before replacing an
    existing file on its own, so unique_path() isn't needed there. A
    write_fn failure (bad path, permissions, ...) surfaces as an error
    instead of failing silently either way.

    dest_dir : an already-resolved destination folder (e.g. a group
        analysis's own folder, see analysis/group/output.py) — used as-is,
        with no dialog and regardless of whether Options -> Output folder
        is set. Takes priority over everything below.
    recording_type, recording_source : what identifies "the current
        recording" for outputs.recording_dir, for a caller whose data
        isn't in ctx.cache (PT2, the text field study tools — everything
        else already has ctx.cache['source']/['source_path'] and needs
        neither passed). Ignored if dest_dir is given.
    """
    from PyQt6.QtWidgets import QFileDialog

    from .toasts import show_error, show_window_toast

    if dest_dir is not None:
        folder = dest_dir
    else:
        output_folder = ctx.settings.get("output_folder")
        if not output_folder:
            folder = None
        elif recording_type is not None and recording_source is not None:
            folder = outputs.recording_dir(output_folder, recording_type, recording_source)
        elif ctx.cache is not None and ctx.cache.get("source") and ctx.cache.get("source_path"):
            folder = outputs.recording_dir(output_folder, ctx.cache["source"], ctx.cache["source_path"])
        else:
            folder = output_folder

    if folder is not None:
        path = outputs.unique_path(os.path.join(folder, default_filename))
    else:
        path, _ = QFileDialog.getSaveFileName(
            parent, title, os.path.join(get_export_dir(ctx), default_filename), filter_str)
        if not path:
            return
    try:
        write_fn(path)
    except Exception as e:
        show_error(ctx, f"Export failed: {e}")
        return
    show_window_toast(ctx, f"Saved {os.path.basename(path)}")


def signal_short_label(key):
    """"main_driver" -> "Main Driver" — a compact form of an active-signal
    key for dialog titles/export filenames, where the full descriptive
    label (e.g. "Isosbestic (415A)") would be redundant/unwieldy."""
    return key.replace('_', ' ').title()
