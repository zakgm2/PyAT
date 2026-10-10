"""
edit/signal_names.py
--------------------
Naming a recording's signals. The library gives a TDT recording's signals names built from its
stores ("Main Driver (_465A)", "Isosbestic (_405A)"), which is right for a first look and wrong for
a figure. A name given here replaces the built one everywhere that signal appears — the legend, the
Plot menu, every analysis window and export (the "Channel" column of the CSVs included) — and is
saved with the recording by Save Changes (signal_labels.json, see edit/sidecar.py), so the next load
and any script using the recording (PyATCLI.load_recording) call it the same thing.

apply_signal_renames() does the renaming; the Plot menu's "Rename signals…" dialog and the legend
entries in Edit Graph Attributes both go through it.
"""

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout

from ..app import errorlog
from ..backend import api
from .. import figures
from ..context import signal_short_label
from ..plot.plot_signal import relabel_plot_signal_options
from ..app.toasts import show_error


# The rules for naming signals are the recording's (the library's, through api.recording), shared with scripts: a name must say something and two signals
# can't share one (name_problem), what would change (plan_signal_renames), and the colour and legend edit that follow a signal to its new name.
def name_problem(final_labels):
    return api.recording.name_problem(final_labels)


def apply_signal_renames(ctx, renames, redraw=True):
    """Renames signals: {signal key: new name}. A key the recording doesn't have, or a name that is empty or
    unchanged, is skipped. Returns {key: new name} for what changed ({} if nothing did).

    Raises ValueError, with nothing changed, if the result would give two signals the same name.

    Updates the live recording, the pre-splice original (so Remove Splice and Restore Full Recording keep the
    names) and everything Ctrl+Z can bring back; carries the trace colours and legend edits over to the new
    names; refreshes the Plot menu; and, unless redraw is False (the caller is about to redraw), redraws the
    main plot. The names are kept in ctx._signal_renames for Save Changes to write."""
    cache = ctx.cache
    changes = api.recording.plan_signal_renames(cache, renames)            # ValueError, with nothing changed, if two would share a name
    if not changes:
        return {}
    current = api.recording.current_signal_labels(cache)

    holders = [ctx.cache, ctx.original_cache]
    for entry in ctx._undo_stack:
        holders += [entry["cache"], entry["original_cache"]]
    seen = set()
    for held in holders:
        if held is not None and id(held) not in seen:
            seen.add(id(held))
            api.recording.apply_signal_labels(held, changes)

    figures.attributes.migrate_names(ctx.plot_attrs, {current[key]: name for key, name in changes.items()})
    ctx._signal_renames.update(changes)
    errorlog.action("rename_signals", n=len(changes))
    relabel_plot_signal_options(ctx)
    if redraw:
        from ..plot.plotting import simple_plot
        simple_plot(ctx)
    return changes


class SignalNamesDialog(QDialog):
    """One line per signal: what to call it."""

    def __init__(self, ctx):
        super().__init__(ctx.win)
        self.ctx = ctx
        self.setWindowTitle("Rename Signals")
        layout = QVBoxLayout(self)
        note = QLabel("Used in the legend, the Plot menu, analyses and exports. Save Changes keeps the names "
                      "with the recording.")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.edits = {}
        for key, name in api.recording.current_signal_labels(ctx.cache).items():
            edit = QLineEdit(name)
            edit.setMinimumWidth(280)
            form.addRow(signal_short_label(key) + ":", edit)
            self.edits[key] = edit
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        try:
            apply_signal_renames(self.ctx, {key: edit.text() for key, edit in self.edits.items()})
        except ValueError as e:
            show_error(self.ctx, str(e))                                   # the dialog stays open for a different name
            return
        self.accept()


def open_signal_names_dialog(ctx):
    if ctx.cache is None or not ctx.cache.get('signals'):
        return
    SignalNamesDialog(ctx).exec()
