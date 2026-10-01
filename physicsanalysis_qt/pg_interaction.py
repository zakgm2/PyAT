"""
pg_interaction.py
------------------
Mouse interaction for the PyQtGraph main-plot engine: hover snap +
coordinate readout, click dispatch (analysis/marker-place/curve-fit),
and the right-click marker rename/delete menu. Split out of pg_engine.py,
which now only builds/renders the plot — mirrors the matplotlib engine's
own plotting.py / interaction.py split.
"""

import numpy as np
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QMenu

from .markers import MARKER_HIT_PX, place_marker, find_nearest_marker, open_edit_marker_dialog
from .toasts import show_error, show_window_toast


def _nearest_index(full_x, x):
    return int(np.abs(full_x - x).argmin())


def _marker_hit_tolerance(ctx):
    """MARKER_HIT_PX on-screen pixels -> data-space seconds under the
    ViewBox's current view range, so the hit-test radius around a marker
    stays a constant size on screen instead of ballooning at high zoom —
    see interaction.py's own copy of this for the matplotlib engine."""
    vb = ctx.pg_viewbox
    width_px = vb.width()
    if not width_px:
        return 2.0
    (x0, x1), _ = vb.viewRange()
    return MARKER_HIT_PX * (x1 - x0) / width_px


def _hit_marker_label_pg(ctx, view_x, view_y):
    """(marker, InfiniteLine) whose label is near (view_x, view_y) — both in data/view
    coordinates — or None. Proximity-based (x within the usual marker-hit tolerance, y within a
    small pixel band around the label's current height) rather than exact bounding-box
    hit-testing against the rendered InfLineLabel, which is simpler and plenty robust for a
    short, single-line label. See _PanZoomViewBox.mouseDragEvent in pg_engine.py, which drives
    the actual drag."""
    if not ctx._marker_label_lines:
        return None
    vb = ctx.pg_viewbox
    height_px = vb.height()
    if not height_px:
        return None
    (x0, x1), (y0, y1) = vb.viewRange()
    tol_x = _marker_hit_tolerance(ctx)
    tol_y = 14 * (y1 - y0) / height_px  # ~14px vertical tolerance, one text line's ballpark
    for marker, line in ctx._marker_label_lines:
        if abs(marker['time'] - view_x) > tol_x:
            continue
        label_y_data = y0 + marker.get('label_y', 0.95) * (y1 - y0)
        if abs(label_y_data - view_y) <= tol_y:
            return (marker, line)
    return None


def _hit_text_annotation_pg(ctx, view_x, view_y):
    """(annotation dict, TextItem) near (view_x, view_y) — both in data/view coordinates — or
    None. Proximity-based against the item's own (x, y) anchor point, same reasoning as
    _hit_marker_label_pg: simpler than exact bounding-box hit-testing and plenty robust for a
    short text box."""
    if not ctx._text_annotation_items:
        return None
    vb = ctx.pg_viewbox
    width_px, height_px = vb.width(), vb.height()
    if not width_px or not height_px:
        return None
    (x0, x1), (y0, y1) = vb.viewRange()
    tol_x = 20 * (x1 - x0) / width_px   # ~20px — text boxes are wider than a marker tick
    tol_y = 14 * (y1 - y0) / height_px
    for annotation, item in reversed(ctx._text_annotation_items):
        if abs(annotation['x'] - view_x) <= tol_x and abs(annotation['y'] - view_y) <= tol_y:
            return (annotation, item)
    return None


def on_pg_mouse_moved(ctx, scene_pos):
    plot_item = ctx.pg_plot_item
    if plot_item is None or ctx.cache is None or not ctx.pg_lines:
        return
    if not plot_item.sceneBoundingRect().contains(scene_pos):
        ctx.pg_hover_scatter.hide()
        ctx.status_bar.showMessage("X: -- | Y: -- | Pt: --")
        return

    view_pos = ctx.pg_viewbox.mapSceneToView(scene_pos)
    target_x, target_y = view_pos.x(), view_pos.y()

    points = []
    best_idx = None
    best_y_dist = float('inf')
    for item, fx, fy in ctx.pg_lines:
        if len(fx) == 0:
            continue
        idx = _nearest_index(fx, target_x)
        snap_x, snap_y = float(fx[idx]), float(fy[idx])
        points.append((snap_x, snap_y))
        y_dist = abs(snap_y - target_y)
        if y_dist < best_y_dist:
            best_y_dist = y_dist
            best_idx = idx

    if points:
        ctx.pg_hover_scatter.setData(pos=points)
        ctx.pg_hover_scatter.show()

    x_label = plot_item.getAxis('bottom').labelText or "X"
    y_label = plot_item.getAxis('left').labelText or "Y"
    pt_str = str(best_idx) if best_idx is not None else "--"
    ctx.status_bar.showMessage(f"{x_label}: {target_x:.2f} | {y_label}: {target_y:.4f} | Pt: {pt_str}")


def on_pg_mouse_clicked(ctx, ev):
    from PyQt6.QtCore import Qt
    from .analysis.dispatch import analysis_type
    from .analysis.curve_fit import launch_curve_fit

    plot_item = ctx.pg_plot_item
    if plot_item is None or ctx.cache is None:
        return
    if not plot_item.sceneBoundingRect().contains(ev.scenePos()):
        return

    view_pos = ctx.pg_viewbox.mapSceneToView(ev.scenePos())
    x = view_pos.x()

    if ev.double() and ev.button() == Qt.MouseButton.LeftButton:
        ctx.slope_clicks.clear()
        analysis_type(ctx, x)
        return

    if ctx.text_mode:
        if ev.button() == Qt.MouseButton.LeftButton:
            from .analysis.text_annotation import place_text_annotation
            place_text_annotation(ctx, x, view_pos.y())
        return

    if ctx.marker_mode:
        if ev.button() == Qt.MouseButton.LeftButton:
            place_marker(ctx, x)
        elif ev.button() == Qt.MouseButton.RightButton:
            _right_click_marker_menu(ctx, x, ev.screenPos(), _marker_hit_tolerance(ctx))
        return

    if ctx.highlight_click_mode and ev.button() == Qt.MouseButton.LeftButton:
        from .analysis.highlight import apply_highlight_at_point
        apply_highlight_at_point(ctx, x)
        return

    if ev.button() == Qt.MouseButton.RightButton:
        # A genuine click (no real drag) — delete a text annotation/highlight if the click
        # landed on one, else the marker menu if near a marker. A right-click-and-hold that
        # turns into an actual drag is a different pyqtgraph event entirely, handled by
        # _PanZoomViewBox.mouseDragEvent (pg_engine.py) instead — pyqtgraph itself already
        # separates "click" from "drag", so there's no click-vs-drag threshold to do by hand
        # here the way interaction.py's matplotlib version needs.
        text_hit = _hit_text_annotation_pg(ctx, x, view_pos.y())
        if text_hit is not None:
            from .analysis.text_annotation import delete_text_annotation
            delete_text_annotation(ctx, text_hit[0])
            show_window_toast(ctx, "Text box deleted")
            return
        tol_s = _marker_hit_tolerance(ctx)
        if find_nearest_marker(ctx, x, tol_s) is not None:
            _right_click_marker_menu(ctx, x, ev.screenPos(), tol_s)
            return
        from .analysis.highlight import find_highlight_at, delete_highlight
        highlight = find_highlight_at(ctx, x)
        if highlight is not None:
            delete_highlight(ctx, highlight)
            show_window_toast(ctx, "Highlight deleted")
        return

    if ctx.analysis_mode == "Curve Fit" and ev.button() == Qt.MouseButton.LeftButton:
        if not ctx.pg_lines:
            return
        # Pick whichever tracked line is closest in y to the click, same
        # heuristic the matplotlib engine uses for active_snap_line.
        best_line, best_dist = None, float('inf')
        for item, fx, fy in ctx.pg_lines:
            idx = _nearest_index(fx, x)
            dist = abs(float(fy[idx]) - view_pos.y())
            if dist < best_dist:
                best_dist = dist
                best_line = (fx, fy)
        if best_line is None:
            show_error(ctx, "No active data trace found to analyze.")
            return
        fx, _ = best_line
        idx = _nearest_index(fx, x)
        ctx.slope_clicks.append((idx, x))
        show_window_toast(ctx, f"Point {len(ctx.slope_clicks)}: {x:.2f}s")
        if len(ctx.slope_clicks) == 2:
            launch_curve_fit(ctx, None, ctx.slope_clicks[0], ctx.slope_clicks[1])
            ctx.slope_clicks.clear()
        return

    if ctx.splice_click_mode and ev.button() == Qt.MouseButton.LeftButton:
        # Never wired up for this engine — only interaction.py (matplotlib)
        # had the click-to-anchor handling, so Splice mode silently did
        # nothing here. No line-snapping needed (unlike Curve Fit above):
        # a splice range is a time boundary, not tied to a signal's value.
        from .analysis.splice import apply_splice_at_points

        ctx.slope_clicks.append(x)
        show_window_toast(ctx, f"Point {len(ctx.slope_clicks)}: {x:.2f}s")
        if len(ctx.slope_clicks) == 2:
            t1, t2 = ctx.slope_clicks
            ctx.slope_clicks.clear()
            apply_splice_at_points(ctx, t1, t2)


def _right_click_marker_menu(ctx, xdata, global_pos, tol_s=2.0):
    from .pg_engine import pg_simple_plot  # local import: avoid module cycle at import time
    from .marker_labels import marker_display_label
    from .markers import delete_all_same_name
    from .toasts import show_success
    from . import undo

    idx = find_nearest_marker(ctx, xdata, tol_s)
    if idx is None:
        return
    marker = ctx.cache['markers'][idx]
    name = marker_display_label(ctx, marker)

    menu = QMenu(ctx.win)
    act_rename = menu.addAction(f"Rename '{name}'")
    act_delete = menu.addAction(f"Delete '{name}'")
    act_delete_all = menu.addAction(f"Delete all '{name}' markers")
    chosen = menu.exec(QPoint(int(global_pos.x()), int(global_pos.y())))

    if chosen == act_rename:
        if open_edit_marker_dialog(ctx, marker):
            pg_simple_plot(ctx)
    elif chosen == act_delete:
        before = undo.snapshot(ctx)
        ctx.cache['markers'].pop(idx)
        undo.push(ctx, "deleted a marker", before)
        pg_simple_plot(ctx)
    elif chosen == act_delete_all:
        before = undo.snapshot(ctx)
        removed = delete_all_same_name(ctx, marker)
        undo.push(ctx, f"deleted {removed} marker(s)", before)
        pg_simple_plot(ctx)
        show_success(ctx, f"Deleted {removed} '{name}' marker(s)")
