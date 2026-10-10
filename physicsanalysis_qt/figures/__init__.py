"""
physicsanalysis_qt.figures
--------------------------
Everything that draws, and everything that writes a drawing to a file. The analysis library computes and writes numbers (tables, records, the plan of a
view); PyAT draws them, with the same code whether a figure goes on the screen or into a file, so what is exported is what was shown.

    draw.py        the figures of the analysis windows (Z-score, AUC, FFT, Curve Fit, Event PETH), drawn from arrays or from a result's tables
    group.py       the figures of a group analysis (traces, heatmaps, measures, diagnostics), from the results or the tables they were written to
    panels.py      the generic figure: one panel per table, for what has no window of its own
    from_tables.py build_figure(): the figure for a finished analysis's tables — what Open Results… shows
    view.py        the main plot's lines styled, and Export View: the plot redrawn as a figure
    attributes.py  Edit Graph Attributes: the rules the dialog applies (text, sizes, legend, colours)
    style.py       font sizes and the default colour of a signal
    render.py      render_figure(): PNG / TIFF / PDF / SVG, editable text, no clock in vector files; save_figure(): that, with the CSV of the
                   data behind the figure and renamed labels — what Export Figure does
    data.py        figure_tables() / write_figure_data(): the CSV of the data behind a figure, read off its artists
    labels.py      text_items() / edited_texts(): the words on a figure that can be changed for an export
    tables.py      looking at result tables by their columns

Plain names are re-exported here; the module a name lives in is the one to patch in a test.
"""

from . import attributes, data, draw, from_tables, group, labels, panels, render, style, tables, view
from .data import DATA_COLUMNS, figure_tables, panel_name, write_figure_data
from .draw import (
    EVENT_PETH_VIEWS, auc_window_figure, auc_window_from_tables, curve_fit_from_tables, draw_curve_fit, draw_event_peth,
    event_peth_from_tables, fft_window_figure, fft_window_from_tables, new_curve_fit_figure, new_event_peth_figure,
    zscore_window_figure, zscore_window_from_tables,
)
from .errors import NothingToPlot
from .from_tables import build_figure
from .group import (
    MeasuresDisplayOptions, build_all_figures, build_diagnostics_figure, build_heatmap_figures, build_measures_figure,
    build_trace_figure, figure_title_text, save_figures, set_figure_title_text,
)
from .labels import TextItem, edited_texts, text_items
from .render import FORMATS, VECTOR_FORMATS, figure_notes, render_figure, save_figure
from .style import SIGNAL_COLORS, channel_color, fig_font_sizes, signal_color
from .view import ViewExport, build_view, default_plot_attrs, plan_view, plot_attrs, view_traces

__all__ = [
    "attributes", "data", "draw", "from_tables", "group", "labels", "panels", "render", "style", "tables", "view",
    "ViewExport", "build_view", "default_plot_attrs", "plan_view", "plot_attrs", "view_traces",
    "MeasuresDisplayOptions", "build_all_figures", "build_diagnostics_figure", "build_heatmap_figures", "build_measures_figure",
    "build_trace_figure", "figure_title_text", "save_figures", "set_figure_title_text", "build_figure",
    "EVENT_PETH_VIEWS", "auc_window_figure", "auc_window_from_tables", "curve_fit_from_tables", "draw_curve_fit",
    "draw_event_peth", "event_peth_from_tables", "fft_window_figure", "fft_window_from_tables", "new_curve_fit_figure",
    "new_event_peth_figure", "zscore_window_figure", "zscore_window_from_tables",
    "SIGNAL_COLORS", "channel_color", "fig_font_sizes", "signal_color",
    "DATA_COLUMNS", "figure_tables", "panel_name", "write_figure_data",
    "TextItem", "edited_texts", "text_items",
    "NothingToPlot", "FORMATS", "VECTOR_FORMATS", "figure_notes", "render_figure", "save_figure",
]
