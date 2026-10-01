"""
plot_signal.py
--------------
The toolbar's "Plot:" control — a dropdown button with a checkbox per computed signal a dataset
offers more than one of (currently TDT: the normalized dF/F trace, plus whatever raw
per-wavelength channels PhysicsLibrary's process_tdt_folder() found — a main driver/probe channel
always, an isosbestic/control channel too if the recording has a 415 reference stream). Ticking
more than one overlays them all on the main plot, one line each. A dropdown rather than a row of
inline checkboxes (an earlier version of this) because a row grows with however many signals a
recording has and doesn't fit a narrow toolbar — one fixed-width button does regardless.

The checkboxes live inside the dropdown as QWidgetActions wrapping real QCheckBox widgets, not
plain checkable QActions — clicking a plain QAction closes the menu immediately (the usual single-
choice menu behavior), which would make ticking more than one signal require reopening the menu
for every box. A QWidgetAction's child widget handles its own clicks, so the menu stays open
across repeated ticks, the way a multi-select dropdown is expected to behave.

Analysis tools (AUC, FFT, Curve Fit, Z-Score PETH) still work on exactly one signal regardless of
how many boxes are ticked — see context.get_active_signal()'s docstring; ctx.plot_signal (not
plot_signals) is what they read, kept in sync with whichever box was ticked most recently.

Kept as its own module (not folded into ui/toolbar.py or loaders/tdt.py)
because both of those need it and importing across them directly would be
circular — toolbar.py already imports loaders/tdt.py for the Open/Reload
actions.
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QToolButton, QMenu, QWidgetAction, QCheckBox


def build_plot_signal_control(ctx):
    """Toolbar widget: one dropdown button, "Plot:" plus a summary of what's ticked, opening a
    menu of checkboxes — one per signal, filled in by refresh_plot_signal_options once a load
    knows what's available. Hidden until then."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)

    ctx.plot_signal_button = QToolButton()
    ctx.plot_signal_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    ctx.plot_signal_menu = QMenu(ctx.plot_signal_button)
    ctx.plot_signal_button.setMenu(ctx.plot_signal_menu)
    ctx.plot_signal_checkboxes = {}
    layout.addWidget(ctx.plot_signal_button)

    row.setVisible(False)
    ctx.plot_signal_row = row
    return row


def _button_text(ctx):
    cache = ctx.cache
    signals = cache.get('signals') if cache else None
    if not signals:
        return "Plot"
    checked = [signals[k]['label'] for k in signals if k in ctx.plot_signals]
    if len(checked) == 1:
        return f"Plot: {checked[0]}"
    if len(checked) > 1:
        return f"Plot: {len(checked)} signals"
    return "Plot"  # shouldn't happen — _on_toggled never allows zero ticked


def _on_toggled(ctx, key, checked):
    if checked:
        ctx.plot_signals.add(key)
        ctx.plot_signal = key  # most-recently-ticked becomes the "primary" signal for analysis
                                # tools (get_active_signal) — see the module docstring.
    else:
        ctx.plot_signals.discard(key)
        if not ctx.plot_signals:
            # Never leave nothing ticked — the plot would have nothing to draw. Re-check the box
            # that was just unticked instead of silently blocking the click; a single signal is
            # still a perfectly valid state, just not "zero signals".
            box = ctx.plot_signal_checkboxes[key]
            box.blockSignals(True)
            box.setChecked(True)
            box.blockSignals(False)
            ctx.plot_signals.add(key)
        elif ctx.plot_signal == key:
            ctx.plot_signal = next(iter(ctx.plot_signals))

    ctx.plot_signal_button.setText(_button_text(ctx))

    if ctx.cache is None:
        return

    if len(ctx.plot_signals) == 1 and ctx.settings.get("plot_engine") == "pyqtgraph":
        # Swap the line's data in place instead of a full pg_simple_plot()
        # clear()+rebuild — see pg_update_active_signal's docstring: the
        # rebuild briefly shows an intermediate frame that Qt can paint as
        # a one-frame flash on every switch. Falls back to a full render
        # below only if there's no line yet to update, or more than one
        # signal is ticked (pg_update_active_signal's own guard).
        from .pg_engine import pg_update_active_signal
        if pg_update_active_signal(ctx):
            return

    # Different signals can have wildly different scale/units (raw
    # fluorescence vs. dF/F) and there's no reason a pan/zoom on one
    # would still make sense on another — always fit to the newly
    # selected signal(s)' full data, same as a fresh load, rather than
    # trying to carry over whatever view was active before.
    ctx._data_generation += 1
    from .plotting import simple_plot
    simple_plot(ctx)


def refresh_plot_signal_options(ctx):
    """Call once after any load finishes. Rebuilds the dropdown's checkboxes from
    cache['signals'] (only present for sources that offer more than one
    plottable signal — currently TDT) and hides the whole control for
    everything else (Oxysoft, Generic, ...) instead of leaving stale
    options from whatever was loaded before."""
    cache = ctx.cache
    signals = cache.get('signals') if cache else None

    ctx.plot_signal_menu.clear()
    ctx.plot_signal_checkboxes = {}

    if not signals:
        ctx.plot_signal_row.setVisible(False)
        ctx.plot_signals = set()
        return

    # Every load (Open or Reload alike) resets ctx.plot_signal to "normalized" first (see
    # loaders/tdt.py) so a previous dataset's pick never silently carries over — starting the
    # checkboxes from anything but that single default here would undo that on every load.
    default_key = ctx.plot_signal if ctx.plot_signal in signals else next(iter(signals))
    checked_keys = {default_key}

    for key, sig in signals.items():
        box = QCheckBox(sig['label'])
        box.setChecked(key in checked_keys)
        box.toggled.connect(lambda state, k=key: _on_toggled(ctx, k, state))
        action = QWidgetAction(ctx.plot_signal_menu)
        action.setDefaultWidget(box)
        ctx.plot_signal_menu.addAction(action)
        ctx.plot_signal_checkboxes[key] = box

    ctx.plot_signals = set(checked_keys)
    if ctx.plot_signal not in ctx.plot_signals:
        ctx.plot_signal = next(iter(ctx.plot_signals))
    ctx.plot_signal_button.setText(_button_text(ctx))
    ctx.plot_signal_row.setVisible(True)
