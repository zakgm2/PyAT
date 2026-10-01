"""
vispy_interaction.py
----------------------
Mouse interaction for the VisPy main-plot engine: a custom pan/zoom
camera matching the app's left-drag-rect-zoom / right-drag-pan /
wheel-zoom convention (VisPy's stock PanZoomCamera binds left-drag to
pan and right-drag to zoom instead — confirmed empirically: Qt
LeftButton maps to VisPy button 1, RightButton to button 2;
PanZoomCamera treats 1=pan, 2=zoom), plus hover snap + coordinate
readout, click dispatch (analysis/marker-place/curve-fit/splice), and
the right-click marker menu. Mirrors the PyQtGraph engine's own
pg_interaction.py.

Screen-pixel -> data-space mapping uses
canvas.scene.node_transform(view.scene).map(event.pos) — verified
empirically to match view.camera.rect's own coordinates precisely
(mapping the pixel center of the ViewBox reproduces the camera rect's
center to within float noise).
"""

import numpy as np
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QMenu
from vispy import scene
from vispy.scene.cameras import PanZoomCamera

from .markers import MARKER_HIT_PX, place_marker, find_nearest_marker, open_edit_marker_dialog
from .pg_interaction import _nearest_index
from .toasts import show_error, show_window_toast

_MIN_DRAG_PX = 5  # below this, a press+release pair counts as a click, not a drag


def _marker_hit_tolerance(ctx):
    """MARKER_HIT_PX on-screen pixels -> data-space seconds under the
    current camera view, so the hit-test radius around a marker stays a
    constant size on screen instead of ballooning at high zoom — see
    interaction.py's own copy of this for the matplotlib engine. Reuses
    _map_to_data rather than the camera rect directly since that's the
    already-verified pixel->data mapping this module uses everywhere else."""
    x0, _ = _map_to_data(ctx, (0, 0))
    x1, _ = _map_to_data(ctx, (MARKER_HIT_PX, 0))
    return abs(x1 - x0)


class RectZoomPanCamera(PanZoomCamera):
    """Left-drag = rectangle zoom (tracked live via a translucent yellow
    overlay, applied on release), right-drag = pan, wheel = zoom at
    cursor — the app's existing convention on both other engines. A
    plain click (press+release with negligible motion) is deliberately
    left unhandled here (event.handled stays False on release) so it
    still reaches canvas.events.mouse_press/release for
    on_vispy_mouse_clicked's own dispatch (marker placement, curve fit,
    splice) — this camera only ever acts on genuine drags.

    on_range_changed, if set, is called after every pan/zoom/rect-zoom
    this camera actually applies — used to keep event-marker lines
    extended to the new y-range during live interaction (VisPy has no
    infinite-line visual, and no other change event reliably fires here;
    see vispy_engine.py's module docstring for what was tried first)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rect_zoom_start = None  # data-space (x, y) where the left-drag began
        self._rect_visual = None      # lazily created — needs self.viewbox to exist first
        self.on_range_changed = None  # optional callback, set by build_vispy_widget

    def _ensure_rect_visual(self):
        if self._rect_visual is None and self.viewbox is not None:
            self._rect_visual = scene.Rectangle(
                center=(0, 0), width=1, height=1,
                color=(1, 1, 0, 0.3), border_color='black', border_width=1,
                parent=self.viewbox.scene)
            self._rect_visual.visible = False
        return self._rect_visual

    def viewbox_mouse_event(self, event):
        if event.handled or not self.interactive:
            return

        if event.type in ('mouse_wheel', 'gesture_zoom'):
            super().viewbox_mouse_event(event)
            if self.on_range_changed:
                self.on_range_changed()
            return

        if event.type == 'mouse_press':
            event.handled = event.button in (1, 2)
            return

        if event.type == 'mouse_move':
            if event.press_event is None:
                return
            if 2 in event.buttons:
                # Right-drag = pan — same translate math PanZoomCamera's
                # own base class uses for its (left-)button-1 case.
                p1 = np.array(event.last_event.pos)[:2]
                p2 = np.array(event.pos)[:2]
                p1s = self._transform.imap(p1)
                p2s = self._transform.imap(p2)
                self.pan(p1s - p2s)
                if self.on_range_changed:
                    self.on_range_changed()
                event.handled = True
            elif 1 in event.buttons:
                rect_visual = self._ensure_rect_visual()
                if rect_visual is not None:
                    if self._rect_zoom_start is None:
                        self._rect_zoom_start = self._transform.imap(
                            event.press_event.pos[:2])[:2]
                    cur = self._transform.imap(event.pos[:2])[:2]
                    x0, y0 = self._rect_zoom_start
                    x1, y1 = cur
                    rect_visual.center = ((x0 + x1) / 2, (y0 + y1) / 2)
                    rect_visual.width = max(abs(x1 - x0), 1e-9)
                    rect_visual.height = max(abs(y1 - y0), 1e-9)
                    rect_visual.visible = True
                event.handled = True
            else:
                event.handled = False
            return

        if event.type == 'mouse_release':
            if self._rect_zoom_start is not None and event.button == 1:
                end = self._transform.imap(event.pos[:2])[:2]
                x0, y0 = self._rect_zoom_start
                x1, y1 = end
                # Screen-pixel drag distance (not data-space) so the
                # threshold means the same physical distance regardless
                # of current zoom level — mirrors interaction.py's own
                # dx/dy > 5px click-vs-drag check for the matplotlib
                # engine.
                press_px = np.array(event.press_event.pos[:2])
                release_px = np.array(event.pos[:2])
                if np.linalg.norm(release_px - press_px) >= _MIN_DRAG_PX:
                    left, right = sorted((x0, x1))
                    bottom, top = sorted((y0, y1))
                    if right > left and top > bottom:
                        self.rect = (left, bottom, right - left, top - bottom)
                        if self.on_range_changed:
                            self.on_range_changed()
                self._rect_zoom_start = None
                if self._rect_visual is not None:
                    self._rect_visual.visible = False
            event.handled = False  # a plain click still needs to reach app-level dispatch
            return

        event.handled = False


def _map_to_data(ctx, pos):
    """screen-pixel (event.pos, from any canvas.events.* handler) ->
    (x, y) data coordinates under the current camera. See module
    docstring for how this was verified."""
    tr = ctx.vispy_canvas.scene.node_transform(ctx.vispy_view.scene)
    mapped = tr.map(pos)
    return float(mapped[0]), float(mapped[1])


def on_vispy_mouse_moved(ctx, event):
    view = ctx.vispy_view
    if view is None or ctx.cache is None or not ctx.vispy_line_visuals:
        return

    target_x, target_y = _map_to_data(ctx, event.pos)

    points = []
    best_idx = None
    best_y_dist = float('inf')
    for _, fx, fy, _ in ctx.vispy_line_visuals:
        if len(fx) == 0:
            continue
        idx = _nearest_index(fx, target_x)
        snap_x, snap_y = float(fx[idx]), float(fy[idx])
        points.append((snap_x, snap_y))
        y_dist = abs(snap_y - target_y)
        if y_dist < best_y_dist:
            best_y_dist = y_dist
            best_idx = idx

    x_label = ctx.vispy_xaxis.axis.axis_label or "X"
    y_label = ctx.vispy_yaxis.axis.axis_label or "Y"
    pt_str = str(best_idx) if best_idx is not None else "--"
    ctx.status_bar.showMessage(f"{x_label}: {target_x:.2f} | {y_label}: {target_y:.4f} | Pt: {pt_str}")


def _handle_click(ctx, x, y, button, is_double, screen_pos):
    from PyQt6.QtCore import Qt
    from .analysis.dispatch import analysis_type
    from .analysis.curve_fit import launch_curve_fit

    if is_double and button == 1:
        ctx.slope_clicks.clear()
        analysis_type(ctx, x)
        return

    if ctx.marker_mode:
        if button == 1:
            place_marker(ctx, x)
        elif button == 2:
            _right_click_marker_menu(ctx, x, screen_pos, _marker_hit_tolerance(ctx))
        return

    if button == 2:
        tol_s = _marker_hit_tolerance(ctx)
        if find_nearest_marker(ctx, x, tol_s) is not None:
            _right_click_marker_menu(ctx, x, screen_pos, tol_s)
        return

    if ctx.analysis_mode == "Curve Fit" and button == 1:
        if not ctx.vispy_line_visuals:
            return
        best_line, best_dist = None, float('inf')
        for _, fx, fy, _ in ctx.vispy_line_visuals:
            idx = _nearest_index(fx, x)
            dist = abs(float(fy[idx]) - y)
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

    if ctx.splice_click_mode and button == 1:
        from .analysis.splice import apply_splice_at_points

        ctx.slope_clicks.append(x)
        show_window_toast(ctx, f"Point {len(ctx.slope_clicks)}: {x:.2f}s")
        if len(ctx.slope_clicks) == 2:
            t1, t2 = ctx.slope_clicks
            ctx.slope_clicks.clear()
            apply_splice_at_points(ctx, t1, t2)


def on_vispy_mouse_pressed(ctx, event):
    ctx._vispy_press_pos = event.pos
    ctx._vispy_press_button = event.button


def on_vispy_mouse_released(ctx, event):
    if ctx.vispy_view is None or ctx.cache is None:
        return
    press_pos = getattr(ctx, '_vispy_press_pos', None)
    if press_pos is None or event.button != getattr(ctx, '_vispy_press_button', None):
        return
    dx = event.pos[0] - press_pos[0]
    dy = event.pos[1] - press_pos[1]
    if (dx * dx + dy * dy) ** 0.5 > _MIN_DRAG_PX:
        return  # a real drag (rect-zoom/pan) already handled by the camera, not a click

    x, y = _map_to_data(ctx, event.pos)
    screen_pos = ctx.vispy_canvas.native.mapToGlobal(QPoint(int(event.pos[0]), int(event.pos[1])))
    _handle_click(ctx, x, y, event.button, is_double=False, screen_pos=screen_pos)


def on_vispy_mouse_double_clicked(ctx, event):
    if ctx.vispy_view is None or ctx.cache is None:
        return
    x, y = _map_to_data(ctx, event.pos)
    screen_pos = ctx.vispy_canvas.native.mapToGlobal(QPoint(int(event.pos[0]), int(event.pos[1])))
    _handle_click(ctx, x, y, event.button, is_double=True, screen_pos=screen_pos)


def _right_click_marker_menu(ctx, xdata, global_pos, tol_s=2.0):
    from .vispy_engine import vispy_simple_plot
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
    chosen = menu.exec(global_pos)

    if chosen == act_rename:
        if open_edit_marker_dialog(ctx, marker):
            vispy_simple_plot(ctx)
    elif chosen == act_delete:
        before = undo.snapshot(ctx)
        ctx.cache['markers'].pop(idx)
        undo.push(ctx, "deleted a marker", before)
        vispy_simple_plot(ctx)
    elif chosen == act_delete_all:
        before = undo.snapshot(ctx)
        removed = delete_all_same_name(ctx, marker)
        undo.push(ctx, f"deleted {removed} marker(s)", before)
        vispy_simple_plot(ctx)
        show_success(ctx, f"Deleted {removed} '{name}' marker(s)")
