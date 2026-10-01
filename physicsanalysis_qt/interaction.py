"""
interaction.py
---------------
Mouse/view interaction: rect-select zoom, right-click pan, blit-based
hover tracker, scroll zoom, resize-safe zoom, reset zoom.
"""

import time

import numpy as np
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QInputDialog

_PAN_MIN_FRAME_INTERVAL = 1 / 30  # cap pan redraws at ~30 fps

from . import plotting
from .markers import MARKER_HIT_PX, place_marker, find_nearest_marker, right_click_marker_menu
from .toasts import show_error, show_window_toast


def _marker_hit_tolerance(ctx):
    """MARKER_HIT_PX on-screen pixels, converted to data-space seconds using
    the axes' *current* view — a fixed-seconds tolerance would swallow far
    more of the visible plot at high zoom than at low zoom, which is what
    made right-click-to-pan near a marker nearly impossible once zoomed in
    (the marker-menu check fires on button *press*, before panning even
    starts, so it doesn't get a chance to distinguish a click from a drag
    the way the PyQtGraph/VisPy engines' click-vs-drag checks already do)."""
    ax = ctx.ax
    bbox = ax.get_window_extent()
    if bbox.width <= 0:
        return 2.0
    xlim = ax.get_xlim()
    return MARKER_HIT_PX * (xlim[1] - xlim[0]) / bbox.width


def on_select(ctx, eclick, erelease):
    if eclick.dblclick:
        return
    if abs(eclick.x - erelease.x) < 10 or abs(eclick.y - erelease.y) < 10:
        return
    x1, y1 = eclick.xdata, eclick.ydata
    x2, y2 = erelease.xdata, erelease.ydata
    if None in [x1, x2, y1, y2]:
        return
    ctx.ax.set_xlim(min(x1, x2), max(x1, x2))
    ctx.ax.set_ylim(min(y1, y2), max(y1, y2))
    ctx.rect_selector.clear()
    _refresh_hover_bg(ctx)
    show_window_toast(ctx, "Zoomed to Selection")


_DBLCLICK_MAX_INTERVAL = 0.4  # seconds
_DBLCLICK_MAX_PIXEL_DIST = 6


def _is_manual_double_click(ctx, event):
    """Own double-click detection, independent of matplotlib's
    event.dblclick — see the note on ctx._last_click_time."""
    now = time.monotonic()
    is_double = False
    if ctx._last_click_xy is not None and now - ctx._last_click_time <= _DBLCLICK_MAX_INTERVAL:
        lx, ly = ctx._last_click_xy
        if abs(event.x - lx) <= _DBLCLICK_MAX_PIXEL_DIST and abs(event.y - ly) <= _DBLCLICK_MAX_PIXEL_DIST:
            is_double = True
    if is_double:
        ctx._last_click_time = 0.0
        ctx._last_click_xy = None
    else:
        ctx._last_click_time = now
        ctx._last_click_xy = (event.x, event.y)
    return is_double


def _apply_and_redraw(ctx):
    if ctx.settings.get("plot_engine") in ("pyqtgraph", "vispy"):
        plotting.simple_plot(ctx)  # neither has an incremental "apply" — full rebuild
    else:
        plotting._apply_plot_attrs(ctx)
        ctx.canvas.draw_idle()
        _refresh_hover_bg(ctx)


def _text_hit(fig, artist, px, py):
    try:
        bbox = artist.get_window_extent(renderer=fig.canvas.get_renderer())
    except Exception:
        return False
    return bbox.contains(px, py)


def _hit_marker_label(ctx, event):
    """The marker dict whose label text the click landed on (see
    plotting._update_plot_with_notes, which tracks every (marker, Text artist) pair it drew in
    ctx._marker_label_artists), or None. An unnamed marker has no label artist at all, so it can
    never be dragged this way — nothing to drag."""
    if event.x is None or event.y is None:
        return None
    for marker, artist in reversed(ctx._marker_label_artists):
        if _text_hit(ctx.fig, artist, event.x, event.y):
            return marker
    return None


def _hit_text_annotation(ctx, event):
    """The text-annotation dict the click landed on (see plotting._draw_text_annotations /
    ctx._text_annotation_artists), or None."""
    if event.x is None or event.y is None:
        return None
    for annotation, artist in reversed(ctx._text_annotation_artists):
        if _text_hit(ctx.fig, artist, event.x, event.y):
            return annotation
    return None


def _rename_legend_entry(ctx, current_label, new_label):
    plot_attrs = ctx.plot_attrs
    saved_entry_map = {orig: (new, vis) for orig, new, vis in (plot_attrs["leg_entries"] or [])}
    target_orig = None
    target_vis = True
    for orig in ctx._legend_entries:
        disp, vis = saved_entry_map.get(orig, (orig, True))
        if disp == current_label:
            target_orig, target_vis = orig, vis
            break
    if target_orig is None:
        return
    saved_entry_map[target_orig] = (new_label, target_vis)
    plot_attrs["leg_entries"] = [
        (orig, *saved_entry_map.get(orig, (orig, True))) for orig in ctx._legend_entries
    ]


def _try_rename_text_element(ctx, event):
    """Double-click on the title, an axis label, or a legend entry to
    retype just that one — matplotlib engine only (title/labels/legend
    are Text artists we can hit-test against click position)."""
    if event.x is None or event.y is None or ctx.settings.get("plot_engine") in ("pyqtgraph", "vispy"):
        return False

    ax, fig = ctx.ax, ctx.fig
    px, py = event.x, event.y

    targets = [
        (ax.title, "Rename Title", "Title:", "title"),
        (ax.xaxis.label, "Rename X Label", "X Label:", "xlabel"),
        (ax.yaxis.label, "Rename Y Label", "Y Label:", "ylabel"),
    ]
    for artist, dlg_title, dlg_label, attr_key in targets:
        if artist.get_text() and _text_hit(fig, artist, px, py):
            new_text, ok = QInputDialog.getText(ctx.win, dlg_title, dlg_label, text=artist.get_text())
            if ok and new_text.strip():
                ctx.plot_attrs[attr_key] = new_text.strip()
                _apply_and_redraw(ctx)
            return True

    legend = ax.get_legend()
    if legend is not None:
        for txt in legend.get_texts():
            if _text_hit(fig, txt, px, py):
                new_text, ok = QInputDialog.getText(ctx.win, "Rename Legend Entry", "Label:", text=txt.get_text())
                if ok and new_text.strip():
                    _rename_legend_entry(ctx, txt.get_text(), new_text.strip())
                    _apply_and_redraw(ctx)
                return True

    return False


def on_press(ctx, event):
    from .analysis.dispatch import analysis_type

    is_double = event.button == 1 and _is_manual_double_click(ctx, event)

    if is_double:
        # _try_rename_text_element may open a modal QInputDialog — same
        # RectangleSelector desync issue as analysis_type's own dialogs
        # (see its comment): its press handler also sees this same click
        # before we know whether we're about to block on a dialog, so
        # deactivate first and reactivate on the next Qt tick rather than
        # synchronously, for the same reason spelled out there.
        ctx.rect_selector.set_active(False)
        try:
            handled = _try_rename_text_element(ctx, event)
        finally:
            def _reactivate():
                ctx.rect_selector.clear()
                ctx.rect_selector.set_active(True)
            QTimer.singleShot(0, _reactivate)
        if handled:
            return

    if event.inaxes != ctx.ax:
        return

    # Double left-click: routed analysis (FFT / PETH / Curve Fit hint)
    if is_double and event.xdata is not None:
        ctx.slope_clicks.clear()
        analysis_type(ctx, event.xdata)
        return

    # Text mode: left-click places a text box there (asks for content/font size via dialog),
    # nothing else — right-click still works for drag/delete on an existing one, below.
    # place_text_annotation blocks on a modal QDialog while still inside this press handler —
    # same RectangleSelector-desync issue analysis_type() has (see its own comment for the full
    # explanation): deactivate it first since its handler for this same press hasn't fired yet
    # (callbacks run in registration order, ours first), and reactivate on the next Qt tick, not
    # synchronously here, or it would start a fresh drag with no release left to end it.
    if ctx.text_mode:
        if (event.button == 1 and not event.dblclick
                and event.xdata is not None and event.ydata is not None):
            from .analysis.text_annotation import place_text_annotation
            ctx.rect_selector.set_active(False)
            try:
                place_text_annotation(ctx, event.xdata, event.ydata)
            finally:
                def _reactivate():
                    ctx.rect_selector.clear()
                    ctx.rect_selector.set_active(True)
                QTimer.singleShot(0, _reactivate)
        return

    # Marker mode: left-click places, right-click edits, nothing else
    if ctx.marker_mode:
        if event.button == 1 and not event.dblclick and event.xdata is not None:
            place_marker(ctx, event.xdata)
        elif event.button == 3 and event.xdata is not None:
            right_click_marker_menu(ctx, event.xdata, QCursor.pos(), _marker_hit_tolerance(ctx))
        return

    # Highlighter mode: left-click captures a point, same drag-detection pattern as Curve
    # Fit/Splice below — the actual highlight is created in on_release once there are two.
    if ctx.highlight_click_mode:
        if event.button == 1 and not event.dblclick:
            ctx.press_x, ctx.press_y = event.x, event.y
        return

    # Right-click: drag or delete a text annotation if the click landed on one, else drag a
    # marker's label if it landed on one, else the marker context menu if near one, else delete
    # a highlight if inside one, else pan. Checked in that order — most specific/smallest target
    # first, "is this anywhere inside a wide highlight span" last.
    if event.button == 3:
        text_hit = _hit_text_annotation(ctx, event)
        if text_hit is not None:
            from . import undo
            ctx._dragging_text = text_hit
            ctx._dragging_text_before = undo.snapshot(ctx)
            ctx.press_x, ctx.press_y = event.x, event.y  # on_release tells a hold-drag from a plain click by this
            return
        hit = _hit_marker_label(ctx, event)
        if hit is not None:
            from . import undo
            ctx._dragging_label = hit
            ctx._dragging_label_before = undo.snapshot(ctx)
            return
        tol_s = _marker_hit_tolerance(ctx)
        if event.xdata is not None and find_nearest_marker(ctx, event.xdata, tol_s) is not None:
            right_click_marker_menu(ctx, event.xdata, QCursor.pos(), tol_s)
            return
        if event.xdata is not None:
            from .analysis.highlight import find_highlight_at, delete_highlight
            highlight = find_highlight_at(ctx, event.xdata)
            if highlight is not None:
                delete_highlight(ctx, highlight)
                show_window_toast(ctx, "Highlight deleted")
                return
        ctx.is_dragging = True
        ctx.press_x, ctx.press_y = event.x, event.y
        ctx._last_pan_draw_time = 0.0
        return

    # Curve Fit mode: record mouse-down pixel position for drag detection
    if ctx.analysis_mode == "Curve Fit":
        if event.button == 1 and not event.dblclick:
            ctx.press_x, ctx.press_y = event.x, event.y
        return

    # Splice mode: same drag-detection pattern as Curve Fit above
    if ctx.splice_click_mode:
        if event.button == 1 and not event.dblclick:
            ctx.press_x, ctx.press_y = event.x, event.y
        return

    # Middle-click: reset zoom
    if event.button == 2:
        reset_zoom(ctx)
        return

    # Falls through to here only for a plain left-press in the default
    # zoom mode — RectangleSelector's own handler (registered separately)
    # is about to start its drag-select. Suppress the hover tracker's own
    # blit for the duration (see on_motion) so the two blit systems stop
    # fighting over the same canvas region every motion tick, which is
    # what was causing the selection rectangle to visibly flash/flicker
    # while resizing it.
    if event.button == 1 and not event.dblclick:
        ctx._rect_dragging = True


def on_motion(ctx, event):
    ax, canvas, fig = ctx.ax, ctx.canvas, ctx.fig

    # -1. Dragging a text annotation (right-click-and-hold on one, see _hit_text_annotation in
    # on_press) — free 2D movement, not constrained to a line the way a marker label is.
    if ctx._dragging_text is not None:
        if event.xdata is not None and event.ydata is not None:
            annotation = ctx._dragging_text
            annotation['x'], annotation['y'] = event.xdata, event.ydata
            for a, artist in ctx._text_annotation_artists:
                if a is annotation:
                    artist.set_position((event.xdata, event.ydata))
                    canvas.draw_idle()
                    break
        return

    # 0. Dragging a marker's label (right-click-and-hold on one, see _hit_marker_label in
    # on_press) — moves just that label up/down the marker's own line, not the whole view.
    if ctx._dragging_label is not None:
        if event.y is not None:
            marker = ctx._dragging_label
            frac = min(1.0, max(0.0, ax.transAxes.inverted().transform((event.x, event.y))[1]))
            marker['label_y'] = frac
            for m, artist in ctx._marker_label_artists:
                if m is marker:
                    artist.set_position((marker['time'], frac))
                    artist.set_va('top' if frac > 0.5 else 'bottom')
                    canvas.draw_idle()
                    break
        return

    # 1. Panning (right-click drag)
    if ctx.is_dragging and event.inaxes == ax and event.x is not None:
        dx, dy = event.x - ctx.press_x, event.y - ctx.press_y
        ctx.press_x, ctx.press_y = event.x, event.y
        bbox = ax.get_window_extent()
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        shift_x = (dx / bbox.width) * (xlim[1] - xlim[0])
        shift_y = (dy / bbox.height) * (ylim[1] - ylim[0])
        ax.set_xlim(xlim[0] - shift_x, xlim[1] - shift_x)
        ax.set_ylim(ylim[0] - shift_y, ylim[1] - shift_y)

        # Redrawing a long trace (TDT/Oxysoft recordings can be hundreds of
        # thousands of samples) on every single mouse-move tick is the
        # actual bottleneck — Qt's draw_idle() coalescing doesn't help
        # because each individual redraw is itself slow, so the event queue
        # backs up. Cap the redraw rate instead; xlim/ylim above still
        # update every tick (cheap), so the final position is always
        # correct even on frames we skip drawing.
        now = time.monotonic()
        if now - ctx._last_pan_draw_time >= _PAN_MIN_FRAME_INTERVAL:
            ctx._last_pan_draw_time = now
            canvas.draw_idle()
        return

    # RectangleSelector (drag-to-zoom) is mid-drag — its own motion handler
    # (registered separately) does its own blit of the selection rectangle.
    # The hover tracker below does an independent blit of the same canvas
    # region on every tick too; running both was a race between two blit
    # systems repainting the same area, which is what was causing the
    # selection rectangle to visibly flash while resizing it.
    if ctx._rect_dragging:
        return

    # 2. Hover tracker (blit-based)
    hover_ready = (ctx.tracker_dots and ctx.connecting_line is not None and ctx._hover_bg is not None)
    if not hover_ready or event.inaxes != ax or event.xdata is None:
        if hover_ready and not ctx.is_dragging:
            canvas.restore_region(ctx._hover_bg)
            for dot in ctx.tracker_dots:
                dot.set_visible(False)
                ax.draw_artist(dot)
            ctx.connecting_line.set_visible(False)
            ax.draw_artist(ctx.connecting_line)
            canvas.blit(fig.bbox)
            ctx.status_bar.showMessage("X: -- | Y: -- | Pt: --")
        return

    target_x = event.xdata
    y_values_at_x = []
    snap_x = None
    closest_idx = None
    best_y_dist = float('inf')

    visible_lines = [
        l for l in ax.get_lines()
        if not str(l.get_label()).startswith('_')
        and len(l.get_xdata()) > 2
        and l.get_linewidth() >= 1.5
    ]

    # Trace lines are decimated for rendering (see plotting.py), which would
    # otherwise make hover only able to snap to one of ~2000 visible points
    # instead of the real sample. Look up full-resolution data for lines
    # that are tracked, so the snap and the "Pt:" index stay exact.
    full_res = {id(line): (fx, fy) for line, fx, fy in ctx._decim_lines}

    for i, line in enumerate(visible_lines):
        fx, fy = full_res.get(id(line), (None, None))
        if fx is not None:
            x_data, y_data = fx, fy
        else:
            x_data = np.asarray(line.get_xdata())
            y_data = np.asarray(line.get_ydata())
        if len(x_data) == 0:
            continue
        idx = int(np.abs(x_data - target_x).argmin())
        snap_x = float(x_data[idx])
        snap_y = float(y_data[idx])
        closest_idx = idx
        y_values_at_x.append(snap_y)

        if i < len(ctx.tracker_dots):
            ctx.tracker_dots[i].set_data([snap_x], [snap_y])
            ctx.tracker_dots[i].set_color(line.get_color())
            ctx.tracker_dots[i].set_visible(True)

        y_dist = abs(snap_y - event.ydata)
        if y_dist < best_y_dist:
            best_y_dist = y_dist
            ctx.active_snap_line = line

    for j in range(len(visible_lines), len(ctx.tracker_dots)):
        ctx.tracker_dots[j].set_visible(False)

    if len(y_values_at_x) >= 2 and snap_x is not None:
        ctx.connecting_line.set_data([snap_x, snap_x],
                                      [min(y_values_at_x), max(y_values_at_x)])
        ctx.connecting_line.set_visible(True)
    else:
        ctx.connecting_line.set_visible(False)

    canvas.restore_region(ctx._hover_bg)
    for dot in ctx.tracker_dots:
        ax.draw_artist(dot)
    ax.draw_artist(ctx.connecting_line)
    canvas.blit(fig.bbox)

    raw_xlbl = ax.get_xlabel() or ctx.plot_attrs.get("xlabel") or "X"
    raw_ylbl = ax.get_ylabel() or ctx.plot_attrs.get("ylabel") or "Y"
    clean_x = str(raw_xlbl).strip() or "X"
    clean_y = str(raw_ylbl).strip() or "Y"
    pt_str = str(closest_idx) if closest_idx is not None else "--"
    ctx.status_bar.showMessage(f"{clean_x}: {event.xdata:.2f} | {clean_y}: {event.ydata:.4f} | Pt: {pt_str}")


def _refresh_hover_bg(ctx):
    """Full redraw + recapture blit background. Call after view changes settle."""
    ctx._hover_bg_timer = None

    saved_dots = [(list(d.get_xdata()), list(d.get_ydata())) for d in ctx.tracker_dots]
    saved_conn = (list(ctx.connecting_line.get_xdata()), list(ctx.connecting_line.get_ydata())) \
        if ctx.connecting_line is not None else ([], [])
    for dot in ctx.tracker_dots:
        dot.set_data([], [])
    if ctx.connecting_line is not None:
        ctx.connecting_line.set_data([], [])

    plotting._apply_plot_attrs(ctx)
    ctx.canvas.draw()
    ctx._hover_bg = ctx.canvas.copy_from_bbox(ctx.fig.bbox)

    for dot, (xd, yd) in zip(ctx.tracker_dots, saved_dots):
        dot.set_data(xd, yd)
    if ctx.connecting_line is not None:
        ctx.connecting_line.set_data(*saved_conn)

    if any(len(d.get_xdata()) > 0 for d in ctx.tracker_dots):
        ctx.canvas.restore_region(ctx._hover_bg)
        for dot in ctx.tracker_dots:
            ctx.ax.draw_artist(dot)
        if ctx.connecting_line is not None and len(ctx.connecting_line.get_xdata()) > 0:
            ctx.ax.draw_artist(ctx.connecting_line)
        ctx.canvas.blit(ctx.fig.bbox)


def _schedule_hover_bg_refresh(ctx, delay_ms=150):
    if ctx._hover_bg_timer is not None:
        ctx._hover_bg_timer.stop()
    ctx._hover_bg_timer = QTimer()
    ctx._hover_bg_timer.setSingleShot(True)
    ctx._hover_bg_timer.timeout.connect(lambda: _refresh_hover_bg(ctx))
    ctx._hover_bg_timer.start(delay_ms)


def on_release(ctx, event):
    from .analysis.curve_fit import launch_curve_fit

    if ctx._dragging_text is not None:
        annotation = ctx._dragging_text
        before = ctx._dragging_text_before
        ctx._dragging_text = None
        ctx._dragging_text_before = None
        dx = abs(event.x - ctx.press_x) if ctx.press_x is not None and event.x is not None else 999
        dy = abs(event.y - ctx.press_y) if ctx.press_y is not None and event.y is not None else 999
        if dx <= 5 and dy <= 5:
            # A plain right-click, not a hold-and-drag — delete instead (any imperceptible
            # sub-5px position nudge from the hold is moot, it's about to be removed anyway).
            from .analysis.text_annotation import delete_text_annotation
            delete_text_annotation(ctx, annotation)
            show_window_toast(ctx, "Text box deleted")
        else:
            from . import undo
            undo.push(ctx, "moved a text box", before)
            # A plain draw() isn't enough on its own: the hover tracker's blit cache
            # (ctx._hover_bg, captured by _refresh_hover_bg) still holds the OLD canvas image
            # from before the drag, and the very next mouse-move pastes that straight back over
            # whatever was just drawn (restore_region in on_motion's hover section below) —
            # which is what made the new position look like it "snapped back" until some later,
            # unrelated redraw happened to recapture the background. _refresh_hover_bg both
            # forces the repaint and recaptures that cache, same as panning already does after
            # its own drag (see `was_dragging` below).
            _refresh_hover_bg(ctx)
            show_window_toast(ctx, "Text box moved")
        return

    if ctx._dragging_label is not None:
        from . import undo
        undo.push(ctx, "moved a marker label", ctx._dragging_label_before)
        ctx._dragging_label = None
        ctx._dragging_label_before = None
        _refresh_hover_bg(ctx)  # same stale-blit-cache reasoning as the text-drag case above
        return

    was_dragging = ctx.is_dragging
    ctx.is_dragging = False
    if was_dragging:
        _refresh_hover_bg(ctx)

    if ctx._rect_dragging:
        ctx._rect_dragging = False
        _refresh_hover_bg(ctx)

    if (ctx.analysis_mode == "Curve Fit"
            and event.button == 1
            and event.inaxes == ctx.ax
            and event.xdata is not None):

        dx = abs(event.x - ctx.press_x) if ctx.press_x is not None else 999
        dy = abs(event.y - ctx.press_y) if ctx.press_y is not None else 999
        if dx > 5 or dy > 5:
            return

        try:
            snap_line = ctx.active_snap_line
            if snap_line is None:
                all_lines = ctx.ax.get_lines()
                for line in all_lines:
                    label = str(line.get_label()).lower()
                    if 'mean' in label or 'average' in label or 'avg' in label:
                        snap_line = line
                        break
                if snap_line is None:
                    valid = [l for l in all_lines if len(l.get_xdata()) > 2
                             and l.get_linewidth() >= 1.5]
                    snap_line = valid[-1] if valid else None

            if snap_line is None:
                show_error(ctx, "No active data trace found to analyze.")
                return

            # launch_curve_fit indexes directly into the full-resolution
            # cache arrays, so this index must come from full-resolution
            # data too — snap_line.get_xdata() is the decimated render data
            # (see plotting.py) and would give an index in the wrong range.
            full_res = {id(line): fx for line, fx, _ in ctx._decim_lines}
            x_data = full_res.get(id(snap_line))
            if x_data is None:
                x_data = snap_line.get_xdata()
            nearest_idx = int(np.abs(x_data - event.xdata).argmin())
            ctx.slope_clicks.append((nearest_idx, event.xdata))
            show_window_toast(ctx, f"Point {len(ctx.slope_clicks)}: {event.xdata:.2f}s")

            if len(ctx.slope_clicks) == 2:
                launch_curve_fit(ctx, snap_line, ctx.slope_clicks[0], ctx.slope_clicks[1])
                ctx.slope_clicks.clear()
        except Exception as e:
            show_error(ctx, f"Curve fit capture failed: {e}")
            ctx.slope_clicks.clear()
        return

    if (ctx.splice_click_mode
            and event.button == 1
            and event.inaxes == ctx.ax
            and event.xdata is not None):
        from .analysis.splice import apply_splice_at_points

        dx = abs(event.x - ctx.press_x) if ctx.press_x is not None else 999
        dy = abs(event.y - ctx.press_y) if ctx.press_y is not None else 999
        if dx > 5 or dy > 5:
            return

        ctx.slope_clicks.append(event.xdata)
        show_window_toast(ctx, f"Point {len(ctx.slope_clicks)}: {event.xdata:.2f}s")

        if len(ctx.slope_clicks) == 2:
            t1, t2 = ctx.slope_clicks
            ctx.slope_clicks.clear()
            apply_splice_at_points(ctx, t1, t2)
        return

    if (ctx.highlight_click_mode
            and event.button == 1
            and event.inaxes == ctx.ax
            and event.xdata is not None):
        from .analysis.highlight import apply_highlight_at_point

        dx = abs(event.x - ctx.press_x) if ctx.press_x is not None else 999
        dy = abs(event.y - ctx.press_y) if ctx.press_y is not None else 999
        if dx > 5 or dy > 5:
            return

        apply_highlight_at_point(ctx, event.xdata)


def zoom_factory(ctx, base_scale=1.2):
    ax = ctx.ax

    def zoom_fun(event):
        if event.x is None or event.y is None:
            return
        bbox = ax.get_window_extent()
        is_on_x = event.y < bbox.ymin
        is_on_y = event.x < bbox.xmin
        is_inside = event.inaxes == ax
        scale_factor = 1 / base_scale if event.button == 'up' else \
            base_scale if event.button == 'down' else None
        if scale_factor is None:
            return
        cur_xlim, cur_ylim = ax.get_xlim(), ax.get_ylim()
        if is_on_x and not is_on_y:
            xdata = event.xdata if event.xdata is not None else sum(cur_xlim) / 2
            new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
            rel_x = (cur_xlim[1] - xdata) / (cur_xlim[1] - cur_xlim[0])
            ax.set_xlim([xdata - new_width * (1 - rel_x), xdata + new_width * rel_x])
        elif is_on_y and not is_on_x:
            ydata = event.ydata if event.ydata is not None else sum(cur_ylim) / 2
            new_height = (cur_ylim[1] - cur_ylim[0]) * scale_factor
            rel_y = (cur_ylim[1] - ydata) / (cur_ylim[1] - cur_ylim[0])
            ax.set_ylim([ydata - new_height * (1 - rel_y), ydata + new_height * rel_y])
        elif is_inside and event.xdata is not None and event.ydata is not None:
            new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
            new_height = (cur_ylim[1] - cur_ylim[0]) * scale_factor
            rel_x = (cur_xlim[1] - event.xdata) / (cur_xlim[1] - cur_xlim[0])
            rel_y = (cur_ylim[1] - event.ydata) / (cur_ylim[1] - cur_ylim[0])
            ax.set_xlim([event.xdata - new_width * (1 - rel_x), event.xdata + new_width * rel_x])
            ax.set_ylim([event.ydata - new_height * (1 - rel_y), event.ydata + new_height * rel_y])
        ctx._hover_bg = None
        ctx.canvas.draw_idle()
        _schedule_hover_bg_refresh(ctx)

    return zoom_fun


def on_resize(ctx, event):
    # Matplotlib's canvas already redraws live and continuously as the
    # widget resizes (fixed subplot fractions reposition the axes box for
    # free), but title/axis-label/legend font sizes are fixed point values
    # that don't rescale on their own — re-applying them here on every tick
    # keeps text scaling smoothly with the window instead of only jumping
    # once on the next full simple_plot(). Cheap: no clear/rebuild, just
    # font sizes + a draw_idle.
    #
    # The matplotlib canvas still exists (hidden) while PyQtGraph/VisPy is
    # the active engine and is resized along with the window, so this fires
    # for them too — and _apply_plot_attrs() overwrites ctx._legend_entries
    # from matplotlib's own (empty) legend, wiping the entries the active
    # engine recorded. That left PyQtGraph's Plot: dropdown unable to find
    # the old legend row to replace, so the legend grew by one every switch.
    # Nothing here is needed for those engines (they rescale their own
    # fonts), and switch_plot_engine() does a full re-render on the way back.
    if ctx.settings.get("plot_engine") in ("pyqtgraph", "vispy"):
        return
    if ctx.cache is not None and ctx.ax is not None:
        plotting._apply_plot_attrs(ctx)
        ctx.canvas.draw_idle()
    ctx._hover_bg = None
    _schedule_hover_bg_refresh(ctx, delay_ms=250)


def reset_zoom(ctx):
    if ctx.cache is None:
        return
    if ctx.settings.get("plot_engine") == "pyqtgraph":
        from .pg_engine import pg_reset_zoom
        pg_reset_zoom(ctx)
        return
    if ctx.settings.get("plot_engine") == "vispy":
        from .vispy_engine import vispy_reset_zoom
        vispy_reset_zoom(ctx)
        return
    ctx.ax.set_xlim(*plotting.padded_xlim(ctx.cache['x']))
    ctx.ax.autoscale(axis='y')
    _refresh_hover_bg(ctx)
    ctx.canvas.draw_idle()
