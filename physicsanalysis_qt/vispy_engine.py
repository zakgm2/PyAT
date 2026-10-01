"""
vispy_engine.py
----------------
GPU-native (OpenGL, shader-based) main-plot engine using VisPy —
selectable as a third alternative to the matplotlib and PyQtGraph
engines via Options -> Plot engine.

Unlike PyQtGraph, VisPy has no high-level "PlotWidget with axes and a
legend" that's viable for embedding one plot in a larger window (its
vispy.plot.Fig/PlotWidget module is explicitly documented upstream as
experimental and owns a whole canvas designed for subplot grids). This
engine is built from vispy.scene's lower-level pieces instead: a
SceneCanvas -> Grid -> AxisWidget(s) + View -> Line/GridLines visuals,
composed by hand the way PyQtGraph's PlotItem does internally but with
no library code hiding it.

Scope note (through "Stage 6" of the build plan — feature-complete):
axes, gridlines, title/axis labels, full Oxysoft/Generic/TDT source
branching, a legend, event markers, mouse interaction (hover snap,
click dispatch, right-click marker menu, a custom pan/zoom camera
matching the app's left-drag-rect-zoom convention — see
vispy_interaction.py), font/margin scaling matched to the other two
engines' widget-size-relative sizing, manual decimation for large
recordings, and PNG export are all in place.

No vispy.scene widget exists for a legend or an "infinite" vertical
marker line the way PyQtGraph gets both for free (LegendItem,
InfiniteLine) — both are hand-built here. The legend is a plain Qt
QWidget overlaid on canvas.native (positioned/resized via
_position_legend), not a scene visual — matplotlib/PyQtGraph's legends
live inside the axes box and don't change the plot's screen footprint,
so an overlay (not a side panel that would shrink the canvas) keeps
VisPy's plot area the same size/aspect as the other two engines at the
same window size. Marker lines are scene.Line/Text pairs spanning the
camera's current y-range, rebuilt via _rebuild_marker_lines() both on
redraw (new dataset, zoom-preserving redraw) and from
RectZoomPanCamera.on_range_changed (vispy_interaction.py) so they stay
extended during live interactive pan/zoom too — VisPy's camera doesn't
emit a usable change event for that on its own (confirmed empirically:
transform_change and canvas.events.draw both no-op on programmatic and
rendered range changes here), so the custom camera calls this callback
itself right after any pan/zoom/rect-zoom it actually applies.

FFT/PETH/Curve Fit/PT2 windows stay matplotlib-rendered regardless of
engine, same as for PyQtGraph — they're cache-driven pop-up figures,
not tied to any live visual objects this engine owns.
"""

import numpy as np
from PyQt6.QtCore import QEvent, QObject
from PyQt6.QtGui import QImage, QPainter
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from vispy import scene
from vispy.color import Color

import PhysicsLibrary as pl

from .context import export_file, get_active_signal, get_checked_signals, trace_color
from .fonts import main_plot_scale, scaled_plot_font_sizes
from .marker_labels import marker_display_label
from .plotting import _min_max_decimate
from .toasts import show_error


class _LegendRepositioner(QObject):
    """Keeps the legend overlay pinned to canvas.native's top-right corner
    across resizes — installed as an event filter on canvas.native since
    it's a VisPy-owned widget class we can't subclass to override
    resizeEvent directly."""

    def __init__(self, legend_widget, canvas_native):
        super().__init__(canvas_native)
        self._legend = legend_widget
        self._canvas_native = canvas_native

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            _position_legend(self._legend, self._canvas_native)
        return False


def _position_legend(legend, canvas_native):
    legend.layout().activate()
    legend.adjustSize()
    margin = 12
    legend.move(canvas_native.width() - legend.width() - margin, margin)


_GEN_COLORS = ['#CC0000', '#0033CC', '#228B22', '#CC6600',
               '#6600CC', '#008888', '#AA0055', '#005588']

# Base pixel budgets for the y/x axis columns at main_plot_scale()'s
# reference widget size (see fonts.py) — sync_vispy_margins() scales
# these with widget size the same way it scales font sizes, so the
# axes take up a consistent fraction of the plot regardless of how
# large the window is.
_BASE_YAXIS_WIDTH = 80
_BASE_XAXIS_HEIGHT = 70


def build_vispy_widget(ctx):
    """Create the SceneCanvas and its axes/gridlines/title scaffolding.
    Call once at startup, mirroring build_pg_widget()."""
    canvas = scene.SceneCanvas(keys='interactive', show=False, bgcolor='white')
    grid = canvas.central_widget.add_grid(margin=10)

    title = scene.Label('', color='black')
    title.height_max = 40
    grid.add_widget(title, row=0, col=0, col_span=2)

    yaxis = scene.AxisWidget(orientation='left', axis_label='', axis_font_size=10,
                              axis_label_margin=45, tick_label_margin=5)
    yaxis.width_max = _BASE_YAXIS_WIDTH
    grid.add_widget(yaxis, row=1, col=0)

    xaxis = scene.AxisWidget(orientation='bottom', axis_label='', axis_font_size=10,
                              axis_label_margin=30, tick_label_margin=5)
    xaxis.height_max = _BASE_XAXIS_HEIGHT
    grid.add_widget(xaxis, row=2, col=1)

    right_padding = grid.add_widget(row=1, col=2)
    right_padding.width_max = 20

    view = grid.add_view(row=1, col=1)
    from .vispy_interaction import RectZoomPanCamera
    view.camera = RectZoomPanCamera()
    def _on_range_changed():
        _rebuild_marker_lines(ctx)
        _redecimate_lines(ctx)
    view.camera.on_range_changed = _on_range_changed

    gridlines = scene.visuals.GridLines(parent=view.scene)
    gridlines.visible = ctx.show_grid

    xaxis.link_view(view)
    yaxis.link_view(view)

    legend = QWidget(canvas.native)
    legend.setObjectName("vispyLegend")
    # Scoped to the legend itself (a bare declaration cascades to every
    # child, boxing each row and label separately), and with the text
    # color fixed: the canvas is always white regardless of the app's
    # light/dark theme, so palette-derived text would vanish on it in dark.
    legend.setStyleSheet(
        "#vispyLegend { background-color: rgba(255, 255, 255, 210); border: 1px solid #999; }"
        "#vispyLegend QLabel { color: black; }")
    legend_layout = QVBoxLayout(legend)
    legend_layout.setContentsMargins(6, 4, 6, 4)
    legend_layout.setSpacing(2)
    legend.hide()
    canvas.native.installEventFilter(_LegendRepositioner(legend, canvas.native))

    ctx.vispy_canvas = canvas
    ctx.vispy_view = view
    ctx.vispy_xaxis = xaxis
    ctx.vispy_yaxis = yaxis
    ctx.vispy_gridlines = gridlines
    ctx.vispy_title_label = title
    ctx.vispy_legend_widget = legend
    ctx.vispy_line_visuals = []
    ctx.vispy_marker_lines = []

    from .vispy_interaction import (
        on_vispy_mouse_moved, on_vispy_mouse_pressed,
        on_vispy_mouse_released, on_vispy_mouse_double_clicked,
    )
    canvas.events.mouse_move.connect(lambda ev: on_vispy_mouse_moved(ctx, ev))
    canvas.events.mouse_press.connect(lambda ev: on_vispy_mouse_pressed(ctx, ev))
    canvas.events.mouse_release.connect(lambda ev: on_vispy_mouse_released(ctx, ev))
    canvas.events.mouse_double_click.connect(lambda ev: on_vispy_mouse_double_clicked(ctx, ev))
    return canvas.native


def vispy_simple_plot(ctx):
    cache = ctx.cache
    view = ctx.vispy_view
    if cache is None or view is None:
        return

    zoom_key = ("vispy", ctx._data_generation)
    is_new_dataset = zoom_key != ctx._last_zoomed_key
    prev_state = None if is_new_dataset else view.camera.get_state()
    # Decimate to whatever x-range will actually be visible once this
    # redraw settles — the existing view's range if it's being kept, or
    # unbounded (decimate over the whole series) for a fresh dataset,
    # since the camera hasn't been fit to it yet at this point. VisPy has
    # no built-in downsampling (unlike PyQtGraph's PlotDataItem — see
    # module docstring), so this is done by hand with the same
    # min/max-envelope decimator the matplotlib engine already uses.
    if is_new_dataset:
        decimate_xlim = (-np.inf, np.inf)
    else:
        rect = prev_state['rect']
        decimate_xlim = (rect.pos[0], rect.pos[0] + rect.size[0])

    # No incremental update path yet (see module docstring) — always a
    # full detach-and-rebuild, same as pg_simple_plot's clear()+rebuild.
    for visual, _, _, _ in ctx.vispy_line_visuals:
        visual.parent = None
    ctx.vispy_line_visuals = []

    legend_info = []  # (color, raw_name) for whichever lines are legend-eligible
    max_points = ctx.settings.get("decimate_max_points", 2000)

    def _add_line(x, y, color, width, raw_name, alpha=1.0, color_key=None):
        # alpha values mirror plotting.py's matplotlib engine line-for-line
        # (0.8 for TDT/overlay traces, 0.5 for Oxysoft per-channel traces,
        # opaque for Oxysoft means and Generic) so a trace looks the same
        # regardless of which engine is currently selected.
        #
        # color_key: which Edit Attributes color pick this line follows —
        # its own legend name, unless it's one of a group's unnamed
        # lines (Oxysoft channels), which follow the group's entry.
        # Resolved before the legend_info append below so the legend's
        # swatch matches the line.
        if color_key or raw_name:
            color = trace_color(ctx, color_key or raw_name, color)
        dx, dy = _min_max_decimate(x, y, decimate_xlim, max_points=max_points)
        line_color = Color(color, alpha=alpha) if alpha < 1.0 else color
        line = scene.Line(pos=_xy(dx, dy), color=line_color, width=width, parent=view.scene)
        ctx.vispy_line_visuals.append((line, x, y, raw_name))  # full-res, for hover/click
        if raw_name is not None:
            legend_info.append((color, raw_name))
        return line

    if cache.get('source') == 'Oxysoft':
        x = cache['x']
        o2hb = cache['o2hb']
        hhb = cache['hhb']
        for i in range(o2hb.shape[0]):
            _add_line(x, o2hb[i], '#FF9999', 1, 'O2Hb channels' if i == 0 else None, alpha=0.5,
                      color_key='O2Hb channels')
            _add_line(x, hhb[i], '#99BBFF', 1, 'HHb channels' if i == 0 else None, alpha=0.5,
                      color_key='HHb channels')
        ff = cache.get('fit_factor_mean')
        ff_tag = f"  [FF: {ff:.1f}%]" if ff is not None else ""
        _add_line(x, pl.mean_channels(o2hb), '#CC0000', 2, f'Mean O2Hb{ff_tag}')
        _add_line(x, pl.mean_channels(hhb), '#0033CC', 2, f'Mean HHb{ff_tag}')
        if 'thb' in cache:
            _add_line(x, pl.mean_channels(cache['thb']), '#228B22', 2, f'Mean tHb{ff_tag}')
        y_label, title_text = "Delta Concentration (uM)", f"NIRS — {cache['store']}"
        x_label = "Time (s)"
    elif cache.get('source') == 'Generic':
        x = cache['x']
        for i, (col_name, y) in enumerate(cache['y_columns'].items()):
            mask = ~np.isnan(y)
            _add_line(x[mask], y[mask], _GEN_COLORS[i % len(_GEN_COLORS)], 2, col_name)
        y_label, title_text = "Value", cache['store']
        x_label = cache.get('x_label', 'X')
    elif cache.get('source') == 'TDT' and len(ctx.plot_signals) > 1:
        checked = get_checked_signals(ctx)
        for key, sig in checked:
            _add_line(cache['x'], sig['y'], sig['color'], 1, sig['label'], alpha=0.8)
        y_label, title_text = "Amplitude", f"Overlay ({len(checked)}) — {cache['store']}"
        x_label = "Time (s)"
    else:
        _, label_text, data_to_plot, color = get_active_signal(ctx)
        _add_line(cache['x'], data_to_plot, color, 1, label_text, alpha=0.8)
        y_label, title_text = "Amplitude", f"{label_text} — {cache['store']}"
        x_label = "Time (s)"

    plot_attrs = ctx.plot_attrs
    ctx._legend_entries = [name for _, name in legend_info]
    ctx._last_title = title_text
    ctx._last_xlabel = x_label
    ctx._last_ylabel = y_label

    ctx.vispy_title_label.text = plot_attrs["title"] or title_text
    ctx.vispy_xaxis.axis.axis_label = plot_attrs["xlabel"] or x_label
    ctx.vispy_yaxis.axis.axis_label = plot_attrs["ylabel"] or y_label
    ctx.vispy_gridlines.visible = ctx.show_grid

    if is_new_dataset:
        view.camera.set_range()
        ctx._last_zoomed_key = zoom_key
    else:
        view.camera.set_state(prev_state)

    _rebuild_legend(ctx, legend_info)
    _rebuild_marker_lines(ctx)


def _rebuild_legend(ctx, legend_info):
    """legend_info: [(color, raw_name), ...] for lines eligible to show
    up in the legend. Respects the same rename/show-hide map Edit
    Attributes writes to plot_attrs['leg_entries'] that the matplotlib
    and PyQtGraph engines already honor."""
    legend = ctx.vispy_legend_widget
    layout = legend.layout()
    while layout.count():
        item = layout.takeAt(0)
        row = item.widget()
        if row is not None:
            # takeAt() only removes the row from the layout — it's still a
            # visible child of the legend, and deleteLater() alone is
            # deferred, so until the event loop gets to it the old row
            # stays painted right on top of the freshly-added ones. That
            # showed up as stacked/duplicated legend entries after every
            # Plot: dropdown switch. Detach it immediately instead.
            row.hide()
            row.setParent(None)
            row.deleteLater()

    plot_attrs = ctx.plot_attrs
    label_map = {}
    if plot_attrs["leg_entries"]:
        label_map = {orig: (new, vis) for orig, new, vis in plot_attrs["leg_entries"]}

    shown_any = False
    for color, raw_name in legend_info:
        display_name, visible = label_map.get(raw_name, (raw_name, True))
        if not visible:
            continue
        shown_any = True
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(4)
        swatch = QLabel()
        swatch.setFixedSize(12, 12)
        swatch.setStyleSheet(f"background-color: {color}; border: 1px solid #444;")
        row_layout.addWidget(swatch)
        row_layout.addWidget(QLabel(display_name))
        layout.addWidget(row)
        # Rows added to an already-visible legend are only shown on a later
        # event-loop pass, and until then the layout counts them as empty —
        # so the adjustSize() below shrank the legend to a blank sliver on
        # every redraw after the first. Show them now so it sizes correctly.
        row.show()

    legend.setVisible(shown_any)
    if shown_any:
        _position_legend(legend, ctx.vispy_canvas.native)


def _rebuild_marker_lines(ctx):
    """Vertical marker lines + labels, spanning the camera's *current*
    y-range (VisPy has no infinite-line visual, so this rebuilds them
    from scratch at whatever range is current — self-contained,
    including clearing the previous set, so it's safe to call both from
    vispy_simple_plot and from the camera's own range-changed callback
    (see RectZoomPanCamera.on_range_changed) to keep them extended
    during live interactive pan/zoom too, not just on redraw."""
    view = ctx.vispy_view
    if view is None or ctx.cache is None:
        return

    for line, text, _ in ctx.vispy_marker_lines:
        line.parent = None
        text.parent = None
    ctx.vispy_marker_lines = []

    rect = view.camera.rect
    y0, y1 = rect.pos[1], rect.pos[1] + rect.size[1]

    for m in ctx.cache['markers']:
        line = scene.Line(pos=np.array([[m['time'], y0], [m['time'], y1]]),
                           color=m['color'], width=1, parent=view.scene)
        text = scene.Text(marker_display_label(ctx, m), color=m['color'], font_size=8,
                           pos=(m['time'], y1), anchor_x='left', anchor_y='top',
                           rotation=90, parent=view.scene)
        ctx.vispy_marker_lines.append((line, text, m))


def _redecimate_lines(ctx):
    """Re-decimate every tracked line to the camera's current x-range —
    called from RectZoomPanCamera.on_range_changed so pan/zoom cost stays
    independent of how many samples the recording has, the same
    invariant plotting.py's update_decimated_lines() keeps for the
    matplotlib engine (VisPy has no built-in downsampling to do this for
    us, unlike PyQtGraph — see module docstring)."""
    view = ctx.vispy_view
    if view is None or not ctx.vispy_line_visuals:
        return
    rect = view.camera.rect
    xlim = (rect.pos[0], rect.pos[0] + rect.size[0])
    max_points = ctx.settings.get("decimate_max_points", 2000)
    for visual, full_x, full_y, _ in ctx.vispy_line_visuals:
        dx, dy = _min_max_decimate(full_x, full_y, xlim, max_points=max_points)
        visual.set_data(pos=_xy(dx, dy))


def vispy_export_view(ctx):
    if ctx.cache is None:
        show_error(ctx, "No plot to export.")
        return
    img = ctx.vispy_canvas.render()
    # The legend is a Qt overlay on canvas.native, not part of the OpenGL
    # scene canvas.render() captures — composite it in separately so an
    # exported view actually matches what's on screen. Grabbing the
    # legend widget directly (rather than the whole canvas.native) avoids
    # re-capturing the scene itself a second time at a possibly different
    # resolution than render()'s own output. Done up front (not inside
    # the write callback) since it's independent of where the file ends
    # up going.
    qimg = QImage(img.tobytes(), img.shape[1], img.shape[0], QImage.Format.Format_RGBA8888)
    if ctx.vispy_legend_widget.isVisible():
        legend_pixmap = ctx.vispy_legend_widget.grab()
        painter = QPainter(qimg)
        painter.drawPixmap(ctx.vispy_legend_widget.pos(), legend_pixmap)
        painter.end()
    export_file(ctx, ctx.win, "Export View", f"{ctx.cache['store']}_view.png", "PNG (*.png)",
                lambda path: qimg.save(path, "PNG"))


def vispy_set_grid_visibility(ctx):
    if ctx.vispy_gridlines is not None:
        ctx.vispy_gridlines.visible = ctx.show_grid


def vispy_reset_zoom(ctx):
    if ctx.vispy_view is not None:
        ctx.vispy_view.camera.set_range()
        _rebuild_marker_lines(ctx)


def vispy_refresh_fonts(ctx):
    """Scales title/axis-label/tick-label font sizes for the current
    widget size, using the same scaled_plot_font_sizes() ratio
    PyQtGraph's engine scales its own fonts by, so all three engines
    look the same size and stay proportional as the window resizes.
    Cheap enough to call on every tick of a live resize drag, mirroring
    pg_refresh_fonts."""
    if ctx.vispy_canvas is None:
        return
    title_fs, xlabel_fs, ylabel_fs, _ = scaled_plot_font_sizes(ctx)

    # scene.Label has no public font-size setter — its own underlying
    # Text visual (accessed the same private-attribute way AxisWidget's
    # public .axis accessor exposes its own underlying AxisVisual) does.
    ctx.vispy_title_label._text_visual.font_size = title_fs
    ctx.vispy_title_label.height_max = max(30, round(title_fs * 2.2))

    ctx.vispy_xaxis.axis.axis_font_size = xlabel_fs
    ctx.vispy_xaxis.axis.tick_font_size = max(6, round(xlabel_fs * 0.8))
    ctx.vispy_yaxis.axis.axis_font_size = ylabel_fs
    ctx.vispy_yaxis.axis.tick_font_size = max(6, round(ylabel_fs * 0.8))


def sync_vispy_margins(ctx):
    """Scales the axis columns' pixel-width budgets with widget size, so
    they stay a consistent fraction of the plot area regardless of
    window size — the direct VisPy equivalent of what sync_pg_margins
    achieves for PyQtGraph, but simpler to get there: VisPy's Grid
    lays out the axes/view itself from each widget's width_max/
    height_max, with no separate margin layer sitting on top that
    double-counts space the axes already reserved for themselves (that
    double-counting is specifically what sync_pg_margins's two-pass
    zero-margin-then-measure technique exists to correct for on
    PyQtGraph's PlotItem — VisPy's Grid has no equivalent problem to
    correct, so this only needs to scale the budgets, not reprobe
    anything after the fact)."""
    if ctx.vispy_canvas is None:
        return
    scale = main_plot_scale(ctx.stacked_plot_widget)
    ctx.vispy_yaxis.width_max = max(50, round(_BASE_YAXIS_WIDTH * scale))
    ctx.vispy_xaxis.height_max = max(40, round(_BASE_XAXIS_HEIGHT * scale))


def _xy(x, y):
    return np.column_stack([x, y])
