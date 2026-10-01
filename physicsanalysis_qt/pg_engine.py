"""
pg_engine.py
------------
GPU-accelerated (OpenGL-backed rendering pipeline, CPU-side compiled
downsampling) main-plot engine using PyQtGraph, selectable as an
alternative to the matplotlib engine via Options -> Plot engine.

Scope: building/rendering the MAIN plot view only (font/margin scaling,
lines, markers, legend, grid, export). Mouse interaction (hover snap,
click dispatch, right-click marker menu) lives in pg_interaction.py —
mirrors the matplotlib engine's own plotting.py / interaction.py split.
FFT/PETH/Curve Fit/PT2 windows stay matplotlib-rendered regardless of
engine — they open fresh small figures each time and aren't the
performance bottleneck; both analysis_type() and launch_curve_fit() are
cache-driven (not tied to matplotlib Line2D objects), so they work
unchanged from either engine.

PyQtGraph's PlotDataItem does its own compiled min/max downsampling
(setDownsampling) at paint time, which is why this engine doesn't need
the manual _min_max_decimate() from plotting.py — that logic is
specific to matplotlib's Agg renderer, which has no equivalent built-in.
"""

import numpy as np
import pyqtgraph as pg
import pyqtgraph.exporters  # noqa: F401 — registers pg.exporters.ImageExporter
from PyQt6.QtCore import Qt

import PhysicsLibrary as pl

from .context import export_file, get_active_signal, get_checked_signals, trace_color
from .fonts import scaled_plot_font_sizes
from .pg_interaction import on_pg_mouse_moved, on_pg_mouse_clicked
from .toasts import show_error


class _PanZoomViewBox(pg.ViewBox):
    """Left-drag = rectangle zoom (pyqtgraph's own RectMode default).
    Right-drag = simple pan, to match the matplotlib engine's mouse
    mapping instead of pyqtgraph's default (right-drag scales) — UNLESS
    the drag starts on a marker's label, in which case it moves the label
    up/down its line instead (see _hit_marker_label_pg). InfLineLabel has
    its own built-in dragging, but only for the left button, which this
    app already uses for placing/selecting — so that's driven manually
    here instead of turning movable=True on, to stay on the right button
    the matplotlib engine also uses for this (see interaction.py)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ctx = None
        self._dragging_label_item = None
        self._dragging_text_item = None

    def mouseDragEvent(self, ev, axis=None):
        ctx = self._ctx
        if ctx is not None and ev.button() == Qt.MouseButton.RightButton:
            from .pg_interaction import _hit_marker_label_pg, _hit_text_annotation_pg
            if ev.isStart():
                view_pos = self.mapToView(ev.buttonDownPos())
                self._dragging_text_item = _hit_text_annotation_pg(ctx, view_pos.x(), view_pos.y())
                if self._dragging_text_item is not None:
                    from . import undo
                    ctx._dragging_text = self._dragging_text_item[0]
                    ctx._dragging_text_before = undo.snapshot(ctx)
                else:
                    self._dragging_label_item = _hit_marker_label_pg(ctx, view_pos.x(), view_pos.y())
                    if self._dragging_label_item is not None:
                        from . import undo
                        ctx._dragging_label = self._dragging_label_item
                        ctx._dragging_label_before = undo.snapshot(ctx)

            if self._dragging_text_item is not None:
                ev.accept()
                annotation, item = self._dragging_text_item
                view_pos = self.mapToView(ev.pos())
                annotation['x'], annotation['y'] = view_pos.x(), view_pos.y()
                item.setPos(view_pos.x(), view_pos.y())
                if ev.isFinish():
                    from . import undo
                    undo.push(ctx, "moved a text box", ctx._dragging_text_before)
                    ctx._dragging_text = None
                    ctx._dragging_text_before = None
                    self._dragging_text_item = None
                return

            if self._dragging_label_item is not None:
                ev.accept()
                marker, line = self._dragging_label_item
                view_pos = self.mapToView(ev.pos())
                (_, _), (y0, y1) = self.viewRange()
                frac = min(1.0, max(0.0, (view_pos.y() - y0) / (y1 - y0))) if y1 != y0 else 0.5
                marker['label_y'] = frac
                if line.label is not None:
                    line.label.setPosition(frac)
                if ev.isFinish():
                    from . import undo
                    undo.push(ctx, "moved a marker label", ctx._dragging_label_before)
                    ctx._dragging_label = None
                    ctx._dragging_label_before = None
                    self._dragging_label_item = None
                return

        if ev.button() == Qt.MouseButton.RightButton:
            ev.accept()
            tr = self.childGroup.transform()
            tr_inv = pg.functions.invertQTransform(tr)
            delta = tr_inv.map(ev.pos()) - tr_inv.map(ev.lastPos())
            self.translateBy(x=-delta.x(), y=-delta.y())
            return
        super().mouseDragEvent(ev, axis=axis)


def build_pg_widget(ctx):
    """Create the PlotWidget and wire mouse handling. Call once at startup."""
    vb = _PanZoomViewBox()
    vb.setMouseMode(pg.ViewBox.RectMode)
    vb.setMenuEnabled(False)  # we implement our own right-click marker menu
    vb._ctx = ctx  # see _PanZoomViewBox.mouseDragEvent's marker-label-drag handling

    widget = pg.PlotWidget(viewBox=vb)
    widget.setBackground('w')
    plot_item = widget.getPlotItem()
    plot_item.showGrid(x=True, y=True, alpha=0.3)

    ctx.pg_widget = widget
    ctx.pg_plot_item = plot_item
    ctx.pg_viewbox = vb
    ctx.pg_lines = []
    ctx.pg_hover_scatter = pg.ScatterPlotItem(size=8, brush='k', pen=None)
    ctx.pg_hover_scatter.setZValue(10)
    plot_item.addItem(ctx.pg_hover_scatter)
    ctx.pg_hover_scatter.hide()

    widget.scene().sigMouseMoved.connect(lambda pos: on_pg_mouse_moved(ctx, pos))
    widget.scene().sigMouseClicked.connect(lambda ev: on_pg_mouse_clicked(ctx, ev))
    return widget


_GEN_COLORS = ['#CC0000', '#0033CC', '#228B22', '#CC6600',
               '#6600CC', '#008888', '#AA0055', '#005588']


def _title_row_height(title_fs):
    return max(30, round(title_fs * 2.2))


def _set_legend_font_size(legend, leg_fs):
    """LegendItem.setLabelTextSize() only stores the new size in opts —
    it never re-renders the already-displayed label text (a pyqtgraph
    bug: LabelItem.setAttr() just updates opts, only setText() actually
    rebuilds the HTML and re-measures the item), so the legend visually
    never resizes. Re-set each label's text explicitly to force it."""
    if legend is None:
        return
    size = f'{leg_fs}pt'
    legend.opts['labelTextSize'] = size
    for _, label in legend.items:
        label.setText(label.text, size=size)


def sync_pg_margins(ctx, reprobe=True):
    """Make the PlotItem's actual data area (viewbox) the same pixel size
    as matplotlib's axes box would be at this widget size.

    matplotlib's subplot fractions (left=0.125, right=0.10, top=0.12,
    bottom=0.11 — read from ctx.fig so this tracks any future change)
    measure from the canvas edge to the axes box, and already include
    whatever space matplotlib needs for tick/axis labels. PyQtGraph is
    different: setContentsMargins() reserves space *in addition to*
    whatever its own AxisItems already auto-size themselves to fit their
    tick/axis label text. Applying the full matplotlib fraction as a pg
    margin therefore double-counts that space and makes the pg plot area
    noticeably smaller than matplotlib's for the same widget size.

    Fix: measure how much width/height pg's own left/bottom axes actually
    consume, and only reserve the remainder as margin. The top margin is
    similarly reduced by the title row's height (see pg_simple_plot) since
    that row is also additional space, not included in PlotItem's own axis
    auto-sizing. There's no axis on the right, so that side needs no such
    correction.

    reprobe=True (default) does a two-pass measurement — zero the margins,
    force a layout pass, read the axes' real geometry — which is accurate
    but briefly flashes the plot to fill the whole widget for one frame
    unless repaints are frozen around it, so it's relatively expensive.
    reprobe=False reuses the last measured axis size instead of
    re-measuring, so it's cheap enough to call on every tick of a live
    resize drag (axis label width rarely changes mid-drag — only the tick
    values' digit count could shift it, a one-pixel-scale concern) and
    keeps the plot area tracking the widget size continuously instead of
    jumping once after the drag settles."""
    plot_item = ctx.pg_plot_item
    if plot_item is None or ctx.pg_widget is None or ctx.fig is None:
        return
    sp = ctx.fig.subplotpars
    w, h = ctx.pg_widget.width(), ctx.pg_widget.height()
    if w <= 0 or h <= 0:
        return

    title_fs, _, _, _ = scaled_plot_font_sizes(ctx)
    target_left = round(sp.left * w)
    target_right = round((1 - sp.right) * w)
    target_top = max(0, round((1 - sp.top) * h) - _title_row_height(title_fs))
    target_bottom = round(sp.bottom * h)

    if reprobe or ctx._pg_axis_probe is None:
        # Pass 1 briefly zeroes out left/bottom margins to measure the
        # axes' real geometry, which would otherwise flash the plot to fill
        # the whole widget for one frame before pass 2 corrects it. Freeze
        # repaints for the probe so that intermediate state never shows.
        ctx.pg_widget.setUpdatesEnabled(False)
        try:
            plot_item.setContentsMargins(0, target_top, 0, 0)
            plot_item.layout.activate()
            left_axis_w = plot_item.getAxis('left').geometry().width()
            bottom_axis_h = plot_item.getAxis('bottom').geometry().height()
            ctx._pg_axis_probe = (left_axis_w, bottom_axis_h)

            left = max(0, target_left - round(left_axis_w))
            bottom = max(0, target_bottom - round(bottom_axis_h))
            plot_item.setContentsMargins(left, target_top, target_right, bottom)
        finally:
            ctx.pg_widget.setUpdatesEnabled(True)
    else:
        # Cheap path: reuse the last measured axis size, single pass, no
        # flash-prone zero-margin step — safe to call every resize tick.
        left_axis_w, bottom_axis_h = ctx._pg_axis_probe
        left = max(0, target_left - round(left_axis_w))
        bottom = max(0, target_bottom - round(bottom_axis_h))
        plot_item.setContentsMargins(left, target_top, target_right, bottom)


def pg_simple_plot(ctx):
    cache = ctx.cache
    plot_item = ctx.pg_plot_item
    if cache is None or plot_item is None:
        return

    zoom_key = ("pyqtgraph", ctx._data_generation)
    is_new_dataset = zoom_key != ctx._last_zoomed_key
    prev_range = None if is_new_dataset else plot_item.vb.viewRange()

    # The clear()-then-rebuild below briefly leaves the ViewBox showing the
    # *previous* view range with the new (or no) content in it, until the
    # final autoRange()/setRange() call at the bottom corrects it — visible
    # as a jarring zoom-in-then-back-out flash on every signal switch if
    # Qt composites that intermediate frame. Freeze repaints for the whole
    # rebuild so only the final, fully-correct frame ever reaches the
    # screen — same technique sync_pg_margins() uses for its own
    # zero-margin measurement pass, for the same reason.
    ctx.pg_widget.setUpdatesEnabled(False)
    try:
        _pg_simple_plot_impl(ctx, cache, plot_item, zoom_key, is_new_dataset, prev_range)
    finally:
        ctx.pg_widget.setUpdatesEnabled(True)


def _pg_simple_plot_impl(ctx, cache, plot_item, zoom_key, is_new_dataset, prev_range):
    # While autorange is on, every single addItem() call below re-fits the
    # view to whatever's been added *so far* — with several lines plus
    # markers added one at a time, that's a rapid-fire zoom-out/zoom-in
    # flash before the final range (set at the end of this function) ever
    # takes effect. Disable it for the whole rebuild; it gets explicitly
    # re-enabled (new dataset) or replaced with an explicit setRange
    # (redraw of existing view) once, after everything is back in place.
    plot_item.vb.disableAutoRange()

    plot_item.clear()
    ctx.pg_lines = []
    plot_item.addItem(ctx.pg_hover_scatter)
    ctx.pg_hover_scatter.hide()

    legend = plot_item.addLegend()
    plot_attrs = ctx.plot_attrs
    label_map = {}
    if plot_attrs["leg_entries"]:
        label_map = {orig: (new, vis) for orig, new, vis in plot_attrs["leg_entries"]}
    raw_names = []

    def _add_line(x, y, color, width, raw_name, alpha=1.0, color_key=None):
        # alpha values mirror plotting.py's matplotlib engine line-for-line
        # (0.8 for TDT/overlay traces, 0.5 for Oxysoft per-channel traces,
        # opaque for Oxysoft means and Generic) so a trace looks the same
        # regardless of which engine is currently selected.
        #
        # color_key: which Edit Attributes color pick this line follows —
        # its own legend name, unless it's one of a group's unnamed
        # lines (Oxysoft channels), which follow the group's entry.
        if color_key or raw_name:
            color = trace_color(ctx, color_key or raw_name, color)
        pen_color = pg.mkColor(color)
        if alpha < 1.0:
            pen_color.setAlphaF(alpha)
        pen = pg.mkPen(color=pen_color, width=width)
        item = pg.PlotDataItem(x, y, pen=pen)
        item.setDownsampling(auto=True, method='peak')
        # NOT setClipToView(True): triggers a real pyqtgraph bug (reproduces
        # on bare PlotWidget, all recent versions incl. 0.13.7/0.14.0) where
        # PlotDataItem._getDisplayDataset() resolves `view` to the PlotWidget
        # instead of its ViewBox and calls view.autoRangeEnabled(), which
        # PlotWidget.__getattr__ doesn't proxy -> AttributeError, spammed to
        # the console on every clear()+rebuild. setDownsampling alone already
        # bounds rendered points to ~pixel count; clip-to-view was a minor
        # extra optimization, not worth the crash.
        plot_item.addItem(item)
        ctx.pg_lines.append((item, x, y))
        # Legend entries are resolved here (not via PlotDataItem's own
        # `name=`) so the show/hide + rename map from Edit Attributes can
        # be applied without needing to touch the line's underlying data —
        # matplotlib's engine works the same way (line labels never
        # change, only what the legend displays for them).
        if raw_name is not None:
            raw_names.append(raw_name)
            display_name, visible = label_map.get(raw_name, (raw_name, True))
            if visible:
                legend.addItem(item, display_name)
        return item

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
        y_label, title = "Delta Concentration (uM)", f"NIRS — {cache['store']}"
        x_label = "Time (s)"
    elif cache.get('source') == 'Generic':
        x = cache['x']
        for i, (col_name, y) in enumerate(cache['y_columns'].items()):
            mask = ~np.isnan(y)
            _add_line(x[mask], y[mask], _GEN_COLORS[i % len(_GEN_COLORS)], 2, col_name)
        y_label, title = "Value", cache['store']
        x_label = cache.get('x_label', 'X')
    elif cache.get('source') == 'TDT' and len(ctx.plot_signals) > 1:
        checked = get_checked_signals(ctx)
        for key, sig in checked:
            _add_line(cache['x'], sig['y'], sig['color'], 1, sig['label'], alpha=0.8)
        y_label, title = "Amplitude", f"Overlay ({len(checked)}) — {cache['store']}"
        x_label = "Time (s)"
    else:
        _, label_text, data_to_plot, color = get_active_signal(ctx)
        _add_line(cache['x'], data_to_plot, color, 1, label_text, alpha=0.8)
        y_label, title = "Amplitude", f"{label_text} — {cache['store']}"
        x_label = "Time (s)"

    from .marker_labels import marker_display_label
    ctx._marker_label_lines = []  # (marker dict, InfiniteLine) with a label — drag hit-testing
    for m in cache['markers']:
        text = marker_display_label(ctx, m)
        kwargs = {}
        if text:
            # 'position': fraction along the line, 0 (bottom) to 1 (top) — draggable, see
            # interaction.py's right-click-and-hold label-drag handling.
            kwargs["label"] = text
            kwargs["labelOpts"] = {'position': m.get('label_y', 0.95), 'color': m['color'],
                                    'rotateAxis': (1, 0)}
        line = pg.InfiniteLine(
            pos=m['time'], angle=90, movable=False,
            pen=pg.mkPen(color=m['color'], width=2, style=Qt.PenStyle.DashLine),
            **kwargs,
        )
        plot_item.addItem(line)
        if text:
            ctx._marker_label_lines.append((m, line))

    for h in cache.get('highlights', []):
        from .analysis.highlight import HIGHLIGHT_ALPHA
        color = pg.mkColor(h['color'])
        color.setAlphaF(HIGHLIGHT_ALPHA)
        region = pg.LinearRegionItem(values=(h['start'], h['end']), movable=False,
                                      brush=pg.mkBrush(color), pen=pg.mkPen(None))
        region.setZValue(-10)
        plot_item.addItem(region)

    ctx._text_annotation_items = []  # (annotation dict, TextItem) — drag/delete hit-testing
    for t in cache.get('text_annotations', []):
        item = pg.TextItem(text=t['text'], color='k', anchor=(0, 1))
        font = item.textItem.font()
        font.setPointSize(t.get('fontsize', 10))
        item.textItem.setFont(font)
        item.setPos(t['x'], t['y'])
        item.setZValue(5)
        plot_item.addItem(item)
        ctx._text_annotation_items.append((t, item))

    ctx._legend_entries = raw_names
    ctx._last_title = title
    ctx._last_xlabel = x_label
    ctx._last_ylabel = y_label

    title_text = plot_attrs["title"] or title
    xlabel_text = plot_attrs["xlabel"] or x_label
    ylabel_text = plot_attrs["ylabel"] or y_label

    # Scaled relative to the plot widget's actual on-screen size (same
    # reference matplotlib's engine uses) so the two engines look the same
    # size and both stay proportional as the window is resized, instead of
    # each interpreting the configured "24pt" through a different renderer
    # (matplotlib: fixed-DPI raster; PyQtGraph: native Qt font at OS DPI).
    title_fs, xlabel_fs, ylabel_fs, leg_fs = scaled_plot_font_sizes(ctx)
    weight = 'bold' if plot_attrs.get("bold", True) else 'normal'

    plot_item.setTitle(title_text, size=f'{title_fs}pt', color='#000',
                        **{'font-weight': weight})
    # PlotItem.setTitle() hardcodes its title row to a fixed 30px height
    # regardless of the font size passed in — with anything bigger than
    # the ~11pt default it was written for, the title text overflows
    # downward into the plot area. Override the cap it sets internally.
    # (sync_pg_margins() below accounts for the extra height this reserves
    # so the top margin doesn't also grow and shrink the plot area twice.)
    plot_item.titleLabel.setMaximumHeight(16777215)  # Qt's widget max height
    plot_item.layout.setRowFixedHeight(0, _title_row_height(title_fs))

    plot_item.setLabel('bottom', xlabel_text,
                        **{'font-size': f'{xlabel_fs}pt', 'font-weight': weight, 'color': '#000'})
    plot_item.setLabel('left', ylabel_text,
                        **{'font-size': f'{ylabel_fs}pt', 'font-weight': weight, 'color': '#000'})
    _set_legend_font_size(legend, leg_fs)

    plot_item.showGrid(x=ctx.show_grid, y=ctx.show_grid, alpha=0.3)
    if is_new_dataset:
        # enableAutoRange() only *arms* PyQtGraph's continuous auto-fit —
        # it doesn't compute anything synchronously, so viewRange() can
        # still read back the placeholder [0, 1]/[0, 1] view until some
        # later internal update actually runs it. A same-dataset redraw
        # in between (e.g. switching the Plot signal dropdown) would then
        # capture and lock in that placeholder as "the view to preserve"
        # instead of the real full-recording range. autoRange() is the
        # one-shot method that fits to content immediately, so the range
        # is always correct by the time this function returns.
        plot_item.vb.autoRange()
        ctx._last_zoomed_key = zoom_key
    else:
        (xr, yr) = prev_range
        plot_item.vb.setRange(xRange=xr, yRange=yr, padding=0)
    sync_pg_margins(ctx)


def pg_refresh_fonts(ctx):
    """Re-apply title/axis-label/legend font sizes for the current widget
    size without touching line data, markers, grid, or view range — cheap
    enough to call on every tick of a live resize drag (see sync_pg_margins'
    reprobe=False path, which this mirrors) so text keeps scaling smoothly
    instead of jumping once after the drag settles."""
    plot_item = ctx.pg_plot_item
    if plot_item is None or ctx.cache is None:
        return
    plot_attrs = ctx.plot_attrs
    title_text = plot_attrs["title"] or ctx._last_title or ""
    xlabel_text = plot_attrs["xlabel"] or ctx._last_xlabel or ""
    ylabel_text = plot_attrs["ylabel"] or ctx._last_ylabel or ""

    title_fs, xlabel_fs, ylabel_fs, leg_fs = scaled_plot_font_sizes(ctx)
    weight = 'bold' if plot_attrs.get("bold", True) else 'normal'

    plot_item.setTitle(title_text, size=f'{title_fs}pt', color='#000',
                        **{'font-weight': weight})
    plot_item.titleLabel.setMaximumHeight(16777215)
    plot_item.layout.setRowFixedHeight(0, _title_row_height(title_fs))

    plot_item.setLabel('bottom', xlabel_text,
                        **{'font-size': f'{xlabel_fs}pt', 'font-weight': weight, 'color': '#000'})
    plot_item.setLabel('left', ylabel_text,
                        **{'font-size': f'{ylabel_fs}pt', 'font-weight': weight, 'color': '#000'})
    _set_legend_font_size(plot_item.legend, leg_fs)


def pg_update_active_signal(ctx):
    """Swap the active TDT signal's line data/color/legend/title in place
    when only which cache['signals'] entry is shown changes (the Plot
    dropdown) — not a clear()+rebuild through pg_simple_plot(). Same fix
    pattern pg_set_grid_visibility already uses for grid toggles (see its
    docstring): a full rebuild briefly shows an intermediate frame (the
    scene right after clear(), before the new line/range are back in
    place) that Qt can composite as a one-frame flash on every switch —
    skipping the rebuild entirely removes the intermediate state, not
    just how long it's visible for.

    Only valid for TDT's single-line case (Oxysoft/Generic never reach
    get_active_signal — they don't have a Plot dropdown at all). Returns
    False — so the caller falls back to a full pg_simple_plot() — unless
    exactly one trace is currently drawn: nothing rendered yet this
    session, or the plot is showing Overlay All (several lines), where
    retargeting the first line would leave the others (and their legend
    rows) behind on top of the newly selected signal.
    """
    cache = ctx.cache
    plot_item = ctx.pg_plot_item
    if cache is None or plot_item is None or len(ctx.pg_lines) != 1:
        return False

    item, _, _ = ctx.pg_lines[0]
    _, label, y, color = get_active_signal(ctx)
    color = trace_color(ctx, label, color)

    item.setData(cache['x'], y)
    item.setPen(pg.mkPen(color=color, width=1))
    ctx.pg_lines[0] = (item, cache['x'], y)

    plot_attrs = ctx.plot_attrs
    label_map = {}
    if plot_attrs["leg_entries"]:
        label_map = {orig: (new, vis) for orig, new, vis in plot_attrs["leg_entries"]}
    display_name, visible = label_map.get(label, (label, True))

    legend = plot_item.legend
    if legend is not None:
        # Removed by the line item itself, not by name via
        # ctx._legend_entries — that list is shared bookkeeping other code
        # can reset, whereas the legend's own record of this item can't go
        # stale. (No-op if the entry was hidden via Edit Attributes.)
        legend.removeItem(item)
        if visible:
            legend.addItem(item, display_name)
    ctx._legend_entries = [label]

    title = f"{label} — {cache['store']}"
    ctx._last_title = title
    title_text = plot_attrs["title"] or title
    title_fs, _, _, _ = scaled_plot_font_sizes(ctx)
    weight = 'bold' if plot_attrs.get("bold", True) else 'normal'
    plot_item.setTitle(title_text, size=f'{title_fs}pt', color='#000',
                        **{'font-weight': weight})

    plot_item.vb.autoRange()
    return True


def pg_set_grid_visibility(ctx):
    if ctx.pg_plot_item is not None:
        ctx.pg_plot_item.showGrid(x=ctx.show_grid, y=ctx.show_grid, alpha=0.3)


def pg_reset_zoom(ctx):
    if ctx.pg_plot_item is not None:
        # .autoRange(), not enableAutoRange() — see pg_simple_plot's
        # comment: the latter only arms a future auto-fit rather than
        # computing one now, which is fine for a UI button today (nothing
        # reads the range back synchronously afterward) but is the same
        # hazard if that ever changes.
        ctx.pg_plot_item.vb.autoRange()


def pg_export_view(ctx):
    if ctx.cache is None:
        show_error(ctx, "No plot to export.")
        return

    def _write(path):
        exporter = pg.exporters.ImageExporter(ctx.pg_plot_item)
        exporter.export(path)

    export_file(ctx, ctx.win, "Export View", f"{ctx.cache['store']}_view.png", "PNG (*.png)", _write)
