"""
edit/splice.py
--------------
GUI orchestration for non-destructive time-range edits — the actual
array/marker math (trim vs. cut-and-stitch) lives in PyATCLI's
splice.py (splice_keep_inside / splice_cut_out), and applying one to a
recording (per source, with the TDT dF/F re-fit) in its recording.py
(apply_splice). The analysis engine does that work (a TDT splice re-fits
dF/F, seconds on a long recording, so it never runs on this thread): this
module is the dialogs, the click-capture wiring, the requests to the engine
and sidecar persistence tied to ctx.cache. A splice is pure state — the
engine keeps one variant of the recording per list of splices — so undo,
removing a splice and restoring the full recording are asking for an earlier
list, and only the first needs the engine at all.

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
PyATCLI's compute_dff) on the surviving raw signal, instead of
just cutting the already-computed dF/F trace along with everything
else — an artifact dragging the original fit can still be included or
excluded by either operation, so both need a fresh fit, not just a
shorter view of the old one (see PyATCLI.apply_splice).

Works on TDT, Oxysoft, and Generic sources alike — each has a different
cache shape, which PyATCLI.apply_splice branches on. The
click-to-anchor capture that drives this (plot/interaction.py, plot/pg_interaction.py)
is source-agnostic — it only ever reads two
x-coordinates off the plot, never a specific signal's data.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QButtonGroup, QListWidget,
)

from ..backend import api
from ..app import errorlog
from . import undo
from ..backend.errors import BackendError
from ..backend.recordings import recording_ref, variant_from_wire
from ..app.background import run_engine
from ..app.toasts import show_error, show_window_toast
from ..app.window_fit import fit_to_screen

MODE_KEEP_INSIDE = api.recording.splice_keep_inside
MODE_CUT_OUT = api.recording.splice_cut_out


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
    then hands control to the plot for two clicks (see plot/interaction.py's
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


def _carry_window_state(ctx, cache, markers, source):
    """Puts on a recording the engine handed back what the engine does not hold: the window's own markers (moved through the splices by the
    engine, so they are given here), its highlights and text boxes (as `source` has them), and the names given to its signals."""
    if markers is not None:
        cache["markers"] = markers
    for key in ("highlights", "text_annotations"):
        if key in source:
            cache[key] = source[key]
        else:
            cache.pop(key, None)
    if ctx._signal_renames:
        api.recording.apply_signal_labels(cache, ctx._signal_renames)
    return cache


def _state_token(ctx):
    """What the recording is right now, to tell whether it changed while the engine was working out a splice for it."""
    return (ctx._data_generation, [dict(s) for s in ctx._active_splices], [dict(m) for m in ctx.cache.get('markers', [])])


def _too_little(mode):
    return ("Can't cut that range — at least 2 samples need to remain."
            if mode == MODE_CUT_OUT else
            "That range doesn't contain enough samples to analyze.")


CHANGED_MEANWHILE = ("The recording changed while the splice was being computed, so it was not applied — "
                     "try it again.")


def apply_splice(ctx, mode, start, end, announce=True, on_done=None):
    """Applies one splice on top of whatever's currently shown — splices
    stack rather than each one restarting from the pristine original, so
    removing a second artifact doesn't undo the first. Records the
    operation on ctx._active_splices so Save Changes (sidecar.py) can write
    it out and it can later be reviewed/removed via remove_splice().

    The engine works it out (a TDT splice re-fits ΔF/F: a progress toast
    follows it) and the window changes when it answers, not before this
    returns. `on_done(True or False)` is called when it has — False if the
    range left too little, the engine failed, or the recording was changed
    meanwhile (a marker placed while the dF/F was re-fitting, say: the
    result would have lost it, so it is not applied)."""
    from ..plot.plotting import simple_plot

    def done(ok):
        if on_done is not None:
            on_done(ok)

    try:
        ref = recording_ref(ctx)
    except BackendError as e:
        show_error(ctx, str(e))
        done(False)
        return None
    token = _state_token(ctx)
    params = {"id": ref["id"], "mode": mode, "start": float(start), "end": float(end), "splices": ref["splices"], "markers": ref["markers"]}

    def _on_success(wired):
        if _state_token(ctx) != token:
            show_error(ctx, CHANGED_MEANWHILE)
            done(False)
            return
        cache, new_splices = variant_from_wire(wired)
        _carry_window_state(ctx, cache, wired.get("markers"), ctx.cache)
        before = undo.snapshot(ctx)
        if ctx.original_cache is None:
            ctx.original_cache = ctx.cache

        ctx._data_generation += 1
        ctx.cache = cache
        ctx._active_splices = new_splices
        errorlog.action("splice", mode=mode, start_s=start, end_s=end)
        undo.push(ctx, "applied a splice", before)
        simple_plot(ctx)
        if announce:
            n_samples = len(cache['x'])
            if mode == MODE_CUT_OUT:
                verb = f"Cut out {start:.1f}s–{end:.1f}s, {n_samples} samples remain"
            else:
                verb = f"Spliced to {start:.1f}s–{end:.1f}s ({n_samples} samples)"
            if cache.get('source') == 'TDT':
                verb += f" — {ctx.recording_method.upper()} dF/F recomputed on the result"
            show_window_toast(ctx, verb)
        done(True)

    def _on_failure(error):
        if announce and not error.cancelled:
            show_error(ctx, _too_little(mode) if error.code == "invalid_input" else str(error))
        done(False)

    # A TDT splice (either mode) re-fits ΔF/F on whatever raw signal survives, which takes seconds on a
    # long recording: the progress toast shows then (and stays out of the way for the instant splices on
    # other sources, since it only appears after a short delay).
    return run_engine(ctx, "recording.splice", params, _on_success, label="Recomputing dF/F", on_failure=_on_failure)


def apply_splice_at_points(ctx, t1, t2):
    """Called once two points have been clicked in Splice mode — applies
    immediately using the mode chosen in start_splice_flow, no further
    dialog.

    Each click is clamped to the recording's own time range first — none
    of the two plot engines (plot/interaction.py/pg_interaction.py)
    restrict clicks to where data actually is, only
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
    apply_splice(ctx, mode, start, end)


def remove_splice(ctx, index, on_done=None):
    """Removes one splice from the stack and recomputes ctx.cache by
    replaying every remaining splice, in order, from the pristine
    original — the only correct way to reflect removing a middle splice,
    since each one's start/end were recorded relative to whatever the
    recording looked like right before it was applied. Note: removing an
    earlier splice can shift what a later one's saved range actually
    lines up with, the same way deleting a step from any sequential edit
    history can (Undo-stack tools all share this tradeoff).

    The replay is the engine's (it is asked for the recording with the
    remaining list, and for the markers the original had moved through it);
    the window changes when it answers. `on_done(True or False)` says how
    it went. Returns True if it was started (or, for the last splice, done)."""
    from ..plot.plotting import simple_plot

    def done(ok):
        if on_done is not None:
            on_done(ok)

    if not (0 <= index < len(ctx._active_splices)):
        done(False)
        return False

    remaining = ctx._active_splices[:index] + ctx._active_splices[index + 1:]
    if not remaining:
        restore_full_recording(ctx)
        done(True)
        return True

    try:
        ref = recording_ref(ctx, splices=remaining, markers=ctx.original_cache.get('markers', []))
    except BackendError as e:
        show_error(ctx, str(e))
        done(False)
        return False
    token = _state_token(ctx)

    def _on_success(wired):
        if _state_token(ctx) != token:
            show_error(ctx, CHANGED_MEANWHILE)
            done(False)
            return
        cache, splices = variant_from_wire(wired)
        _carry_window_state(ctx, cache, wired.get("markers"), ctx.original_cache)
        before = undo.snapshot(ctx)
        ctx._data_generation += 1
        ctx.cache = cache
        ctx._active_splices = splices
        errorlog.action("splice_removed", index=index, remaining=len(splices))
        undo.push(ctx, "removed a splice", before)
        simple_plot(ctx)
        show_window_toast(ctx, f"Removed splice — {len(splices)} remaining")
        done(True)

    def _on_failure(error):
        if not error.cancelled:
            show_error(ctx, "Removing that splice makes an earlier range invalid — "
                            "try removing a different one, or Restore Full Recording."
                            if error.code == "invalid_input" else str(error))
        done(False)

    return run_engine(ctx, "recording.view", {"id": ref["id"], "splices": ref["splices"], "markers": ref["markers"]},
                      _on_success, label="Replaying splices", on_failure=_on_failure) is not None


def restore_full_recording(ctx):
    if ctx.original_cache is None:
        show_error(ctx, "No splice active — nothing to restore.")
        return

    from ..plot.plotting import simple_plot

    before = undo.snapshot(ctx)
    ctx._data_generation += 1
    ctx.cache = ctx.original_cache
    ctx.original_cache = None
    ctx._active_splices = []
    errorlog.action("splice_restore_full")
    undo.push(ctx, "restored the full recording", before)
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
        self.setEnabled(False)                                             # the replay takes the engine a moment

        def done(ok):
            self.setEnabled(True)
            if not ok:
                return
            if self.ctx._active_splices:
                self._refresh_list()
            else:
                self.accept()

        if not remove_splice(self.ctx, row, on_done=done):
            self.setEnabled(True)

    def _restore_all(self):
        restore_full_recording(self.ctx)
        self.accept()


def open_splice_manager(ctx):
    if not ctx._active_splices:
        show_error(ctx, "No splices active.")
        return
    dlg = _SpliceManagerDialog(ctx.win, ctx)
    dlg.exec()
