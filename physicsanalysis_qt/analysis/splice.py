"""
analysis/splice.py
---------------------
GUI orchestration for non-destructive time-range edits — the actual
array/marker math (trim vs. cut-and-stitch) lives in PhysicsLibrary's
splice.py (splice_keep_inside / splice_cut_out); this module is just
the dialogs, click-capture wiring, and sidecar persistence tied to
ctx.cache.

Every analysis tool in the app (FFT, PETH, Curve Fit, Event PETH, Peak
Finder, markers) reads straight from ctx.cache, so swapping ctx.cache
for an edited copy makes them all "just work" on it with no changes to
any of them. The full original recording is kept in ctx.original_cache
and can be restored at any time.

Flow: pick a mode first (small dialog, no time fields), then click two
points directly on the plot — same click-to-anchor pattern as Curve
Fit. No typed start/end numbers anywhere in this path.

Splices stack: each new one applies on top of whatever's currently
shown rather than always restarting from the pristine original, so
removing several separate artifacts from the same recording doesn't
mean the second attempt undoes the first. ctx._active_splices records
every applied splice in order — see remove_splice()/open_splice_manager
for reviewing or removing one without discarding the rest, and
restore_full_recording() for discarding all of them at once.

For TDT, both modes re-run motion/bleaching correction (via
PhysicsLibrary's compute_dff) on the surviving raw signal, instead of
just cutting the already-computed dF/F trace along with everything
else — an artifact dragging the original fit can still be included or
excluded by either operation, so both need a fresh fit, not just a
shorter view of the old one (see _splice_once).

Works on TDT, Oxysoft, and Generic sources alike — each has a different
cache shape (TDT: raw/corr + optional per-wavelength 'signals'; Oxysoft:
2D o2hb/hhb/optional-thb detector arrays; Generic: a y_columns dict of
1D arrays), so _splice_once branches on ctx.cache['source'] and hands
PhysicsLibrary's splice_keep_inside/splice_cut_out whichever arrays that
source actually has via extra_channels (which slices along each array's
last axis, so a 2D detector array and a 1D column both just work). The
click-to-anchor capture that drives this (interaction.py, pg_interaction.py,
vispy_interaction.py) was already source-agnostic — it only ever reads
two x-coordinates off the plot, never a specific signal's data — so this
one module was the only place actually restricting splicing to TDT.
"""

import json
import os

import PhysicsLibrary as pl
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QButtonGroup, QListWidget,
)

from ..background import run_with_progress
from ..toasts import show_error, show_window_toast
from ..window_fit import fit_to_screen

MODE_KEEP_INSIDE = "keep_inside"
MODE_CUT_OUT = "cut_out"


class _SpliceModePickerDialog(QDialog):
    """Just the mode choice — no time fields. Closing this (Start
    Clicking) is what hands control back to the plot for the two-click
    point selection."""

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.mode = None
        self.setWindowTitle("Splice Recording")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            "Works on a copy — the original recording is kept untouched and\n"
            "restorable at any time. Choose what to do, then click two points\n"
            "on the graph to mark the range."
        ))

        # Cut Out listed first and checked by default — removing an
        # artifact is the more common use case than trimming to a range.
        self.rb_cut = QRadioButton("Cut out this range (remove an artifact, stitch the rest together)")
        self.rb_cut.setChecked(True)
        self.rb_keep = QRadioButton("Keep only this range")
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.rb_cut)
        mode_group.addButton(self.rb_keep)
        layout.addWidget(self.rb_cut)
        layout.addWidget(self.rb_keep)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("Start Clicking…")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _accept(self):
        self.mode = MODE_CUT_OUT if self.rb_cut.isChecked() else MODE_KEEP_INSIDE
        self.accept()


def start_splice_flow(ctx):
    """Entry point for the sidebar's scissors icon: asks the mode first,
    then hands control to the plot for two clicks (see interaction.py's
    on_release Splice-mode handling, which calls apply_splice_at_points
    below once it has both points). Called fresh on every click of the
    icon — always reopens the mode picker, even if a previous splice
    flow is still mid-click-capture (starting over just discards those
    stray clicks, same as re-picking Curve Fit would)."""
    if ctx.cache is None or ctx.cache.get('source') not in ('TDT', 'Oxysoft', 'Generic'):
        show_error(ctx, "Splicing isn't available for this data type.")
        return False

    dlg = _SpliceModePickerDialog(ctx.win, ctx)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False

    ctx._pending_splice_mode = dlg.mode
    ctx.slope_clicks.clear()
    ctx.splice_click_mode = True
    show_window_toast(ctx, "Click two points on the graph to mark the range")
    return True


def _splice_once(source_cache, mode, start, end, regression_method="ols", progress=None):
    """Pure computation: apply one splice to source_cache, returning the
    new spliced cache dict, or None if the range isn't usable. No ctx
    mutation, no toast/redraw — shared by _apply_splice (one interactive
    step) and remove_splice/load_splice_from_sidecar (replaying several
    steps in a row from the pristine original).

    Branches on the cache's source since each one carries the actual
    signal in different keys — see the module docstring. All three paths
    funnel every source-specific array through PhysicsLibrary's
    extra_channels (sliced along each array's own last axis, so Oxysoft's
    2D per-detector arrays and Generic's 1D columns both just work) so
    the trim/cut-and-stitch math itself lives in exactly one place.

    regression_method only matters for TDT (see below) — unused by
    Oxysoft/Generic, which have no correction pipeline of their own to
    re-run. The same goes for `progress` (a PhysicsLibrary progress
    callback): only that recompute is slow enough to report on."""
    splice_fn = pl.splice_cut_out if mode == MODE_CUT_OUT else pl.splice_keep_inside
    source = source_cache.get('source')
    x = source_cache['x']
    markers = source_cache['markers']
    detected_markers = source_cache.get('detected_markers', [])

    if source == 'TDT':
        # The Plot dropdown's raw per-wavelength channels (main driver,
        # isosbestic, ...) are sample-aligned with x/raw/corr and must be
        # trimmed/cut identically or they'd end up the wrong length (and
        # showing the wrong span of samples) after this splice —
        # 'normalized' is excluded since it's already the freshly-spliced
        # 'corr' below.
        source_signals = source_cache.get('signals', {})
        extra_channels = {k: sig['y'] for k, sig in source_signals.items() if k != 'normalized'}

        result = splice_fn(x, source_cache['raw'], source_cache['corr'],
                            markers, detected_markers, start, end, extra_channels=extra_channels)
        if result is None:
            return None

        raw_out, corr_out = result['raw'], result['corr']

        # Both modes: re-running motion/bleaching correction on whatever raw signal survived
        # (the stitched remainder for Cut Out, the kept window for Keep Inside) can give a
        # genuinely better fit than the original one — an artifact dragging the original fit
        # may now be excluded (Cut Out) or isolated to what's left (Keep Inside) — not just a
        # shorter view of the same fit either way. Only possible when the raw main-driver
        # channel survived the splice above (every TDT recording has one — see
        # process_tdt_folder — so this is really just a defensive check).
        if 'main_driver' in result['extra_channels']:
            y_465 = result['extra_channels']['main_driver']
            y_415 = result['extra_channels'].get('isosbestic')
            computed = pl.compute_dff(y_465, y_415, source_cache['fs'],
                                       regression_method=regression_method, progress=progress)
            raw_out, corr_out = computed['raw'], computed['corr']

        spliced = dict(source_cache)
        spliced['x'] = result['x']
        spliced['raw'] = raw_out
        spliced['corr'] = corr_out
        spliced['markers'] = result['markers']
        spliced['detected_markers'] = result['detected_markers']
        if source_signals:
            spliced['signals'] = {
                key: {**sig, 'y': corr_out if key == 'normalized' else result['extra_channels'][key]}
                for key, sig in source_signals.items()
            }
        return spliced

    if source == 'Oxysoft':
        # No single raw/corr pair here — the detector arrays (each shape
        # (n_channels, n_samples)) ARE the signal, so they go through
        # extra_channels instead; x is passed as a throwaway raw/corr
        # placeholder since the function requires something 1D there,
        # but result['raw']/['corr'] are never read back out below.
        extra_channels = {'o2hb': source_cache['o2hb'], 'hhb': source_cache['hhb']}
        if 'thb' in source_cache:
            extra_channels['thb'] = source_cache['thb']

        result = splice_fn(x, x, x, markers, detected_markers, start, end,
                            extra_channels=extra_channels)
        if result is None:
            return None

        spliced = dict(source_cache)
        spliced['x'] = result['x']
        spliced['o2hb'] = result['extra_channels']['o2hb']
        spliced['hhb'] = result['extra_channels']['hhb']
        if 'thb' in source_cache:
            spliced['thb'] = result['extra_channels']['thb']
        spliced['markers'] = result['markers']
        spliced['detected_markers'] = result['detected_markers']
        return spliced

    if source == 'Generic':
        # y_columns are the signal(s) — same throwaway-placeholder
        # reasoning as Oxysoft above for the required raw/corr args.
        extra_channels = dict(source_cache['y_columns'])

        result = splice_fn(x, x, x, markers, detected_markers, start, end,
                            extra_channels=extra_channels)
        if result is None:
            return None

        spliced = dict(source_cache)
        spliced['x'] = result['x']
        spliced['y_columns'] = result['extra_channels']
        spliced['markers'] = result['markers']
        spliced['detected_markers'] = result['detected_markers']
        return spliced

    return None


def _spliced_store_name(base_name, splices):
    """Store label reflecting every splice currently applied, in order —
    derived fresh from the splice list each time (rather than appending a
    tag onto whatever the previous label happened to be) so it stays
    correct after remove_splice() changes which ones are still active."""
    if not splices:
        return base_name
    tags = ", ".join(
        f"{'cut' if s['mode'] == MODE_CUT_OUT else 'kept'} {s['start']:.1f}s-{s['end']:.1f}s"
        for s in splices
    )
    return f"{base_name} [{tags}]"


def _apply_splice(ctx, mode, start, end, announce=True, progress=None):
    """Applies one splice on top of whatever's currently shown — splices
    stack rather than each one restarting from the pristine original, so
    removing a second artifact doesn't undo the first. Records the
    operation on ctx._active_splices so it can be written out by
    save_splice() and later reviewed/removed via remove_splice().

    `progress` follows the ΔF/F recompute of a TDT Cut Out (see _splice_once)."""
    from ..plotting import simple_plot

    regression_method = ctx.settings.get("regression_method", "ols")
    spliced = _splice_once(ctx.cache, mode, start, end, regression_method=regression_method, progress=progress)
    if spliced is None:
        if announce:
            msg = ("Can't cut that range — at least 2 samples need to remain."
                   if mode == MODE_CUT_OUT else
                   "That range doesn't contain enough samples to analyze.")
            show_error(ctx, msg)
        return False

    if ctx.original_cache is None:
        ctx.original_cache = ctx.cache

    new_splices = ctx._active_splices + [{"mode": mode, "start": start, "end": end}]
    spliced['store'] = _spliced_store_name(ctx.original_cache['store'], new_splices)

    ctx._data_generation += 1
    ctx.cache = spliced
    ctx._active_splices = new_splices
    simple_plot(ctx)
    if announce:
        n_samples = len(spliced['x'])
        if mode == MODE_CUT_OUT:
            verb = f"Cut out {start:.1f}s–{end:.1f}s, {n_samples} samples remain"
        else:
            verb = f"Spliced to {start:.1f}s–{end:.1f}s ({n_samples} samples)"
        if ctx.cache.get('source') == 'TDT':
            verb += f" — {regression_method.upper()} dF/F recomputed on the result"
        show_window_toast(ctx, verb)
    return True


def apply_splice_at_points(ctx, t1, t2):
    """Called once two points have been clicked in Splice mode — applies
    immediately using the mode chosen in start_splice_flow, no further
    dialog.

    Each click is clamped to the recording's own time range first — none
    of the three plot engines (interaction.py/pg_interaction.py/
    vispy_interaction.py) restrict clicks to where data actually is, only
    to the visible axes area, so a click past either edge (e.g. trying to
    grab "the very start" but landing slightly before it) would otherwise
    hand this an out-of-range time instead of the boundary sample the
    user clearly meant."""
    ctx.splice_click_mode = False  # the flow that started with start_splice_flow() is done
    mode = getattr(ctx, '_pending_splice_mode', None) or MODE_CUT_OUT
    x = ctx.cache['x']
    t1 = min(max(t1, x[0]), x[-1])
    t2 = min(max(t2, x[0]), x[-1])
    start, end = sorted((t1, t2))
    # A TDT splice (either mode) re-fits ΔF/F on whatever raw signal survives, which takes
    # seconds on a long recording: run_with_progress shows a progress toast then (and stays
    # out of the way for the instant splices on other sources, since it only appears after a
    # short delay).
    run_with_progress(ctx, "Recomputing dF/F",
                      lambda progress: _apply_splice(ctx, mode, start, end, progress=progress))


def remove_splice(ctx, index):
    """Removes one splice from the stack and recomputes ctx.cache by
    replaying every remaining splice, in order, from the pristine
    original — the only correct way to reflect removing a middle splice,
    since each one's start/end were recorded relative to whatever the
    recording looked like right before it was applied. Note: removing an
    earlier splice can shift what a later one's saved range actually
    lines up with, the same way deleting a step from any sequential edit
    history can (Undo-stack tools all share this tradeoff).

    Returns True if the removal (and any needed recompute) succeeded.
    """
    from ..plotting import simple_plot

    if not (0 <= index < len(ctx._active_splices)):
        return False

    remaining = ctx._active_splices[:index] + ctx._active_splices[index + 1:]
    if not remaining:
        restore_full_recording(ctx)
        return True

    regression_method = ctx.settings.get("regression_method", "ols")

    def _replay(progress):
        # One equal slice of the bar per splice: each one re-fits ΔF/F from scratch.
        plan = pl.Plan(progress, [(f"Splice {i + 1} of {len(remaining)}", 1) for i in range(len(remaining))])
        cache = ctx.original_cache
        for i, s in enumerate(remaining):
            cache = _splice_once(cache, s["mode"], s["start"], s["end"], regression_method=regression_method,
                                 progress=plan.sub(f"Splice {i + 1} of {len(remaining)}"))
            if cache is None:
                return None
        return cache

    cache = run_with_progress(ctx, "Replaying splices", _replay)
    if cache is None:
        show_error(ctx, "Removing that splice makes an earlier range invalid — "
                         "try removing a different one, or Restore Full Recording.")
        return False

    cache['store'] = _spliced_store_name(ctx.original_cache['store'], remaining)
    ctx._data_generation += 1
    ctx.cache = cache
    ctx._active_splices = remaining
    simple_plot(ctx)
    show_window_toast(ctx, f"Removed splice — {len(remaining)} remaining")
    return True


def restore_full_recording(ctx):
    if ctx.original_cache is None:
        show_error(ctx, "No splice active — nothing to restore.")
        return

    from ..plotting import simple_plot

    ctx._data_generation += 1
    ctx.cache = ctx.original_cache
    ctx.original_cache = None
    ctx._active_splices = []
    simple_plot(ctx)
    show_window_toast(ctx, "Restored full recording")


def is_spliced(ctx):
    return ctx.original_cache is not None


class _SpliceManagerDialog(QDialog):
    """Lists every splice currently stacked on the recording, each
    removable individually (see remove_splice() for why removing an
    earlier one can shift what a later one's saved range lines up
    with), plus a one-click full restore."""

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Manage Splices")
        fit_to_screen(self, 440, 320)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            "Applied in order, top to bottom. Removing one replays the rest\n"
            "from the original recording — removing an earlier splice can shift\n"
            "what a later splice's saved range actually lines up with."
        ))

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget, stretch=1)

        btn_row = QHBoxLayout()
        btn_remove = QPushButton("Remove Selected")
        btn_remove.clicked.connect(self._remove_selected)
        btn_row.addWidget(btn_remove)
        btn_restore_all = QPushButton("Restore Full Recording")
        btn_restore_all.clicked.connect(self._restore_all)
        btn_row.addWidget(btn_restore_all)
        btn_close = QPushButton("Close")
        btn_close.setDefault(True)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self._refresh_list()

    def _refresh_list(self):
        self.list_widget.clear()
        for i, s in enumerate(self.ctx._active_splices):
            verb = "Cut out" if s["mode"] == MODE_CUT_OUT else "Kept"
            self.list_widget.addItem(f"{i + 1}. {verb} {s['start']:.1f}s–{s['end']:.1f}s")

    def _remove_selected(self):
        row = self.list_widget.currentRow()
        if row < 0:
            show_error(self.ctx, "Select a splice to remove first.")
            return
        if remove_splice(self.ctx, row):
            if self.ctx._active_splices:
                self._refresh_list()
            else:
                self.accept()

    def _restore_all(self):
        restore_full_recording(self.ctx)
        self.accept()


def open_splice_manager(ctx):
    if not ctx._active_splices:
        show_error(ctx, "No splices active.")
        return
    dlg = _SpliceManagerDialog(ctx.win, ctx)
    dlg.exec()


def splice_sidecar_path(ctx):
    """A splice.json next to markers.json in the same JSON saves/
    folder (see sidecar.py) — describes every splice currently stacked,
    in order. sidecar_path() reads ctx.cache['source_path'], which stays
    the same whether or not a splice is currently active (source_cache
    is carried through via `dict(source_cache)` in _splice_once above),
    so no special-casing needed here for the spliced-vs-not state."""
    from ..sidecar import sidecar_path
    path = sidecar_path(ctx)
    if not path:
        return None
    return os.path.join(os.path.dirname(path), "splice.json")


def save_splice(ctx):
    """Writes every active splice (if any) to splice.json as a list;
    removes it if no splice is active, so 'Save Changes' with nothing
    spliced doesn't leave a stale splice.json implying an edit that's no
    longer there."""
    if ctx.cache is None:
        return
    path = splice_sidecar_path(ctx)
    if not path:
        show_error(ctx, "No source file/folder path to save the splice next to.")
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if is_spliced(ctx) and ctx._active_splices:
            with open(path, 'w') as f:
                json.dump(ctx._active_splices, f, indent=2)
            n = len(ctx._active_splices)
            show_window_toast(ctx, f"{n} splice{'s' if n != 1 else ''} saved -> JSON saves/splice.json")
        elif os.path.exists(path):
            os.remove(path)
    except Exception as e:
        show_error(ctx, f"Could not save splice: {e}")


def load_splice_from_sidecar(ctx):
    """Called right after a fresh load (see loaders/tdt.py) — if a
    splice.json exists, replays every saved splice against the
    just-loaded full recording, in order, with no dialog, same as
    markers restoring silently. Accepts both the current format (a list
    of splices) and the old single-splice format (a flat
    {"mode", "start", "end"} dict, from before splices could stack)."""
    path = splice_sidecar_path(ctx)
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, 'r') as f:
            saved = json.load(f)
        splices = [saved] if isinstance(saved, dict) else saved

        def _replay(progress):
            plan = pl.Plan(progress, [(f"Splice {i + 1} of {len(splices)}", 1) for i in range(len(splices))])
            n_applied = 0
            for i, s in enumerate(splices):
                if _apply_splice(ctx, s["mode"], s["start"], s["end"], announce=False,
                                 progress=plan.sub(f"Splice {i + 1} of {len(splices)}")):
                    n_applied += 1
            return n_applied

        applied = run_with_progress(ctx, "Restoring saved splices", _replay)
        if applied:
            show_window_toast(ctx, f"Restored {applied} splice{'s' if applied != 1 else ''}")
    except Exception as e:
        show_error(ctx, f"Could not restore saved splice: {e}")
