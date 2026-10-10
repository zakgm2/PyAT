"""
plot/fonts.py
-------------
Font scaling for the main plot of the PyQtGraph engine. (The golden-ratio sizes of the analysis figures are
figures.fig_font_sizes.)
"""

# Reference plot-widget size the main-plot font sizes in ctx.plot_attrs
# were tuned against. Scaling relative to this (rather than using the
# configured sizes as fixed absolute values) keeps text proportional to
# the plot area as the window is resized, and keeps the two engines
# visually consistent — matplotlib renders text into a fixed-DPI raster
# image, PyQtGraph renders native Qt fonts at the OS's own DPI, so the
# same literal point size looks different in each; scaling both from the
# same widget-size ratio is what actually keeps them looking the same.
_MAIN_PLOT_REF_W = 1180
_MAIN_PLOT_REF_H = 700


def main_plot_scale(widget):
    """Scale factor for main-plot fonts, relative to _MAIN_PLOT_REF_*."""
    if widget is None:
        return 1.0
    w, h = widget.width(), widget.height()
    if w <= 0 or h <= 0:
        return 1.0
    diag = (w ** 2 + h ** 2) ** 0.5
    ref_diag = (_MAIN_PLOT_REF_W ** 2 + _MAIN_PLOT_REF_H ** 2) ** 0.5
    return diag / ref_diag


def scaled_plot_font_sizes(ctx):
    """(title_fs, xlabel_fs, ylabel_fs, leg_fs) in points for the main
    plot, scaled by main_plot_scale() — used by the PyQtGraph engine so it
    stays visually consistent with matplotlib, which doesn't need this at
    all (it scales its own figure text via figures.fig_font_sizes instead)."""
    plot_attrs = ctx.plot_attrs
    scale = main_plot_scale(ctx.stacked_plot_widget)
    return (
        max(8, round(plot_attrs["title_fs"] * scale)),
        max(6, round(plot_attrs["xlabel_fs"] * scale)),
        max(6, round(plot_attrs["ylabel_fs"] * scale)),
        max(5, round(plot_attrs["leg_fs"] * scale)),
    )
