"""Edit Attributes for the figure of an analysis window (figures/restyle.py, edit/figure_attributes.py).

What a person changes about a figure — its words, their sizes, a line's colour, the dot on every sample, the legend, the grid — is kept apart from the
figure and put back on it after every drawing. These tests say so at three levels: the rules on the figures the app draws (matplotlib only), the dialog
that makes the edits, and the real windows (offscreen): that an edit is still there when the window draws its figure again, that the Edit Attributes
button and the button in a window's header edit the window in front, and that what is exported is what was edited, and says so."""

import io
import os
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.colors import to_hex
from PyQt6.QtWidgets import QApplication, QDialog, QPushButton

from physicsanalysis_qt import figures
from physicsanalysis_qt.analysis import auc, curve_fit, dispatch, event_compare, event_peth, fft, overview, peth
from physicsanalysis_qt.analysis.figure_window import ResultsFigureDialog
from physicsanalysis_qt.edit import attributes, figure_attributes
from physicsanalysis_qt.edit.attributes import AttributesDialog, open_attributes_window
from physicsanalysis_qt.edit.figure_attributes import EditableFigure, FigureAttributesDialog
from physicsanalysis_qt.export import figure_export
from physicsanalysis_qt.figures import restyle
from physicsanalysis_qt.figures.restyle import FIGURE_TITLE, LABEL, LEGEND, PANEL_TITLE, FigureEdits
from physicsanalysis_qt.ui import workspace

from tests.test_draw_exported_csv import QUIET_TOAST
from tests.test_workspace import WorkspaceCase

T = np.linspace(-10, 20, 301)
M = np.random.default_rng(1).normal(size=(8, T.size)).cumsum(axis=1) * 0.1


def peth_figure():
    fig = figures.new_event_peth_figure()
    figures.draw_event_peth(fig, time_axis=T, trial_matrix=M, trial_numbers=list(range(1, 9)), pre=10, post=20, event_name="Press")
    return fig


def compare_figure():
    fig = figures.new_event_compare_figure()
    figures.draw_event_compare(fig, pre=10, post=20, events=[{"event": "A", "t": T, "mean": M[0], "sem": np.abs(M[1]) * 0.1, "n": 3},
                                                             {"event": "B", "t": T, "mean": M[2], "sem": np.abs(M[3]) * 0.1, "n": 4}])
    return fig


def blank_compare_figure():
    fig = figures.new_event_compare_figure()
    figures.draw_event_compare(fig, events=[], pre=10, post=20)                                                 # (the blank figure that asks for events)
    return fig


def zscore_figure():
    return figures.zscore_window_figure([{"channel": "Fp1", "color": "blue", "t": T, "z": M[0]}, {"channel": "Fp2", "color": "green", "t": T, "z": M[1]}], 10, 20)


def auc_figure():
    return figures.auc_window_figure([{"channel": "Fp1", "color": "blue", "t": T, "y": M[0]}])


def curve_figure():
    fig = figures.new_curve_fit_figure()
    figures.draw_curve_fit(fig, [{"label": "Fp1", "color": "blue", "x_ctx": T, "y_ctx": M[0], "x": T[100:200], "y": M[0][100:200], "fit": M[0][100:200] * 0.9,
                                  "r2": 0.91}], model_name="Linear", t1=float(T[100]), t2=float(T[199]), view_start=-10, view_end=20)
    return fig


def overview_figure():
    rng = np.random.default_rng(2)
    fig = figures.new_recording_overview_figure(panels=4)
    figures.draw_recording_overview(fig, time=np.arange(500) / 10, panels=[(n, rng.normal(size=500)) for n in ("Control", "Signal", "Control Fit", "Z-Score")])
    return fig


def parts_of(make):
    fig = make()
    FigureCanvasAgg(fig)
    return fig, restyle.describe(fig)


def png(fig):
    out = io.BytesIO()
    fig.savefig(out, format="png", dpi=80)
    return out.getvalue()


def snapshot(fig):
    """What a person can see of a figure's words, lines and legends, as plain values (for telling that an edit was put back)."""
    out = [(t.get_text(), t.get_fontsize(), str(t.get_fontweight())) for t in (fig._suptitle, *(a for ax in fig.axes for a in (ax.title, ax.xaxis.label, ax.yaxis.label)))
           if t is not None]
    for ax in fig.axes:
        out += [(line.get_label(), line.get_color(), line.get_marker(), line.get_markersize()) for line in ax.lines]
        out += [tuple(c.get_facecolor()[0]) for c in ax.collections if len(c.get_facecolor())]
        legend = ax.get_legend()
        out.append(None if legend is None else ([t.get_text() for t in legend.get_texts()], legend._loc, legend.get_texts()[0].get_fontsize() if legend.get_texts() else 0))
    return out


class TestDescribe(unittest.TestCase):
    def test_the_texts_are_the_ones_export_figure_lists_with_what_each_is(self):
        fig, parts = parts_of(peth_figure)
        self.assertEqual([(t.key, t.kind) for t in parts.texts], [("Figure title", FIGURE_TITLE), ("Trials heatmap: Y label", LABEL), ("Group trace: X label", LABEL),
                                                                  ("Group trace: Y label", LABEL), ("Colour bar label", LABEL)])
        self.assertEqual([t.key for t in parts.texts], [i.caption for i in figures.text_items(fig) if "Legend" not in i.caption])        # (a legend's words are its entries')
        self.assertEqual([t.default for t in parts.texts][:1], ["Event PETH — Press"])

    def test_a_figure_of_one_panel_names_things_without_the_panel_and_one_of_several_with_it(self):
        _, one = parts_of(compare_figure)
        self.assertEqual([t.key for t in one.texts], ["Figure title", "X label", "Y label"])
        self.assertEqual([s.key for s in one.series], ["A (n=3)", "B (n=4)"])
        self.assertEqual([e.key for e in one.legends[0].entries], ["A (n=3)", "B (n=4)"])
        _, several = parts_of(overview_figure)
        self.assertEqual([s.key for s in several.series], ["Control: line 1", "Signal: line 1", "Control Fit: Signal", "Control Fit: Control fit", "Z-Score: line 1"])
        self.assertIn("Control Fit: Title (left)", [t.key for t in several.texts])

    def test_the_kinds_of_text_and_which_sizes_a_figure_has(self):
        _, parts = parts_of(overview_figure)
        self.assertEqual(parts.kinds(), [FIGURE_TITLE, PANEL_TITLE, LABEL, LEGEND])
        self.assertEqual({t.kind for t in parts.texts if t.key.endswith("Title (left)")}, {PANEL_TITLE})
        self.assertEqual(parts_of(zscore_figure)[1].kinds(), [FIGURE_TITLE, LABEL])                           # (no legend, no panel titles)
        self.assertEqual(parts.size_default(LEGEND), parts.legends[0].size)

    def test_a_line_is_one_series_with_its_band_and_the_unnamed_lines_drawn_in_its_colour(self):
        _, parts = parts_of(peth_figure)
        mean, = parts.series
        self.assertEqual((mean.key, len(mean.lines), len(mean.bands)), ("Group trace: Mean", 1, 1))                   # the SEM band goes with the mean
        _, fit = parts_of(curve_figure)
        self.assertEqual([(s.key, len(s.lines)) for s in fit.series], [("Fp1", 3), ("Fp1 fit  R2=0.910", 1)])      # (the faint stretch and the anchors are Fp1's)

    def test_reference_lines_and_shading_down_to_zero_are_not_series(self):
        _, parts = parts_of(peth_figure)
        self.assertEqual([s.key for s in parts.series], ["Group trace: Mean"])                                         # (not the red line at the event)
        _, shaded = parts_of(auc_figure)
        self.assertEqual([(s.key, s.bands) for s in shaded.series], [("line 1", [])])

    def test_what_the_drawing_gave_is_recorded_as_the_defaults(self):
        fig, parts = parts_of(curve_figure)
        self.assertEqual((parts.point_default, [g.on for g in parts.grids]), (6.0, [True]))                         # (the anchors' dots; a grid)
        self.assertEqual(parts_of(peth_figure)[1].point_default, 0.0)
        fig, parts = parts_of(compare_figure)
        legend, = parts.legends
        self.assertEqual((legend.loc, legend.size, legend.frameon), ("upper right", fig.axes[0].get_legend().get_texts()[0].get_fontsize(), True))
        self.assertTrue(parts.bold_default)

    def test_describing_changes_nothing(self):
        fig = peth_figure()
        before = png(fig)
        restyle.describe(fig)
        self.assertEqual(png(fig), before)

    def test_a_figure_with_no_legend_has_no_legend_and_one_with_nothing_has_nothing(self):
        self.assertEqual(parts_of(zscore_figure)[1].legends, [])
        parts = restyle.describe(blank_compare_figure())
        self.assertEqual(([t.key for t in parts.texts], parts.series, parts.legends), (["Figure title"], [], []))


class TestApply(unittest.TestCase):
    def applied(self, make, **changes):
        fig, parts = parts_of(make)
        edits = restyle.edited(parts, FigureEdits(), **changes)
        restyle.apply(fig, parts, edits)
        return fig, parts, edits

    def test_with_no_edits_the_figure_is_left_as_drawn_to_the_pixel(self):
        for make in (peth_figure, compare_figure, zscore_figure, curve_figure, overview_figure):
            with self.subTest(make.__name__):
                fig, parts = parts_of(make)
                before = png(fig)
                restyle.apply(fig, parts, FigureEdits())
                restyle.apply(fig, parts, FigureEdits())
                self.assertEqual(png(fig), before)

    def test_words_sizes_and_bold(self):
        fig, parts, edits = self.applied(peth_figure, texts={"Figure title": "My title", "Group trace: Y label": "z"},
                                         sizes={FIGURE_TITLE: "30", LABEL: "18"}, bold=False)
        self.assertEqual(fig._suptitle.get_text(), "My title")
        self.assertEqual((fig._suptitle.get_fontsize(), fig._suptitle.get_fontweight()), (30, "normal"))
        group = fig.axes[1]
        self.assertEqual((group.get_ylabel(), group.yaxis.label.get_fontsize(), group.xaxis.label.get_fontsize()), ("z", 18, 18))
        self.assertEqual(fig.axes[0].get_ylabel(), "Trial")                                                           # (untouched words are as drawn)
        colorbar = fig.axes[2]
        self.assertEqual((colorbar.get_ylabel(), colorbar.yaxis.label.get_fontsize()), ("Z-score", 18))                # (the colour bar's label is a label too)

    def test_a_size_changes_only_its_own_kind(self):
        fig, parts, _ = self.applied(overview_figure, sizes={PANEL_TITLE: "14"})
        axes = fig.axes
        self.assertEqual({ax.get_title(loc="left") and ax._left_title.get_fontsize() for ax in axes}, {14})
        self.assertEqual(axes[0].yaxis.label.get_fontsize(), parts.size_default(LABEL))
        self.assertEqual(fig._suptitle.get_fontsize(), parts.size_default(FIGURE_TITLE))

    def test_a_colour_goes_to_the_line_its_band_the_lines_drawn_with_it_and_the_legend(self):
        fig, parts, _ = self.applied(curve_figure, colors=[("Fp1", "#ff0000", "#0000ff")])
        ax = fig.axes[0]
        fp1 = parts.series[0]
        self.assertTrue(all(line.get_color() == "#ff0000" for line in fp1.lines))                                    # all three
        self.assertEqual(parts.series[1].lines[0].get_color(), "blue")                                               # the fit has its own row: as it was drawn
        handles = ax.get_legend().legend_handles
        self.assertEqual((to_hex(handles[0].get_color()), to_hex(handles[1].get_color())), ("#ff0000", "#0000ff"))     # the legend shows the new colour
        fig, parts, _ = self.applied(peth_figure, colors=[("Group trace: Mean", "#ff0000", "#000000")])
        mean, = parts.series
        self.assertEqual((mean.lines[0].get_color(), tuple(np.round(mean.bands[0].get_facecolor()[0][:3], 2))), ("#ff0000", (1.0, 0.0, 0.0)))

    def test_a_dot_on_every_sample_zero_for_none_and_none_for_as_drawn(self):
        fig, parts, edits = self.applied(curve_figure, point_size=4)
        self.assertEqual({(line.get_marker(), line.get_markersize()) for s in parts.series for line in s.lines}, {("o", 4.0)})
        restyle.apply(fig, parts, restyle.edited(parts, edits, point_size=0))
        self.assertEqual({line.get_marker() for s in parts.series for line in s.lines}, {"None"})
        restyle.apply(fig, parts, FigureEdits())
        self.assertEqual({(line.get_marker(), line.get_markersize()) for s in parts.series for line in s.lines}, {("None", 6.0), ("o", 6.0)})        # (the anchors' dots)

    def test_a_grid_on_the_panels_that_have_lines_and_the_drawn_one_back_again(self):
        fig, parts, edits = self.applied(peth_figure, grid=True)
        heat, group = fig.axes[0], fig.axes[1]
        self.assertEqual((heat.xaxis.get_gridlines()[0].get_visible(), group.xaxis.get_gridlines()[0].get_visible()), (False, True))
        fig, parts, edits = self.applied(curve_figure, grid=False)
        self.assertFalse(fig.axes[0].xaxis.get_gridlines()[0].get_visible())
        restyle.apply(fig, parts, FigureEdits())
        line = fig.axes[0].xaxis.get_gridlines()[0]
        self.assertEqual((line.get_visible(), line.get_linestyle(), line.get_alpha()), (True, ":", 0.5))              # as the fit drew it

    def test_the_legend_is_drawn_again_for_a_rename_a_hidden_entry_a_place_and_a_size(self):
        fig, parts, edits = self.applied(compare_figure, entries=[("A (n=3)", "Press", True), ("B (n=4)", "B (n=4)", False)], legend_loc="lower left",
                                         sizes={LEGEND: "12"})
        legend = fig.axes[0].get_legend()
        self.assertEqual(([t.get_text() for t in legend.get_texts()], legend._loc, legend.get_texts()[0].get_fontsize()), (["Press"], 3, 12))
        self.assertEqual(fig.axes[0].lines[0].get_label(), "Press")                                                  # the series is called that, so the data file is
        self.assertEqual(set(figures.figure_tables(fig)["data"]["series"]), {"Press", "B (n=4)", "Press band", "B (n=4) band"})
        restyle.apply(fig, parts, restyle.edited(parts, edits, entries=[("B (n=4)", "B (n=4)", True)], legend_loc="upper right", sizes={LEGEND: str(round(parts.legends[0].size))}))
        self.assertEqual([t.get_text() for t in fig.axes[0].get_legend().get_texts()], ["Press", "B (n=4)"])

    def test_hiding_every_entry_takes_the_legend_away_and_resetting_brings_the_drawn_one_back(self):
        fig, parts, _ = self.applied(compare_figure, entries=[("A (n=3)", "A (n=3)", False), ("B (n=4)", "B (n=4)", False)])
        self.assertIsNone(fig.axes[0].get_legend())
        restyle.apply(fig, parts, FigureEdits())
        self.assertIs(fig.axes[0].get_legend(), parts.legends[0].original)
        self.assertEqual([t.get_text() for t in fig.axes[0].get_legend().get_texts()], ["A (n=3)", "B (n=4)"])

    def test_fewer_edits_bring_everything_else_back(self):
        for make in (peth_figure, compare_figure, curve_figure, overview_figure):
            with self.subTest(make.__name__):
                fig, parts = parts_of(make)
                before = snapshot(fig)
                first, = parts.series[:1]
                restyle.apply(fig, parts, restyle.edited(
                    parts, FigureEdits(), texts={"Figure title": "Other"}, sizes={FIGURE_TITLE: "9", LABEL: "20"}, bold=False, grid=True, point_size=5, legend_loc="center",
                    colors=[(first.key, "#123456", first.default_color)], entries=[(e.key, "x", False) for lp in parts.legends for e in lp.entries][:1]))
                self.assertNotEqual(snapshot(fig), before)
                restyle.apply(fig, parts, FigureEdits())
                self.assertEqual(snapshot(fig), before)

    def test_the_figure_is_laid_out_again_when_its_words_grow_so_the_title_clears_the_axes(self):
        fig, parts, _ = self.applied(peth_figure, sizes={FIGURE_TITLE: "60"})
        fig.canvas.draw()
        title = fig._suptitle.get_window_extent()
        self.assertGreaterEqual(title.y0, max(ax.get_tightbbox().y1 for ax in fig.axes) - 1)                         # the title does not sit on the plots
        self.assertLessEqual(title.y1, fig.bbox.y1 + 1)
        self.assertEqual(fig.pyat_layout_rect, [0, 0, 1, 0.96])                                                      # (drawn into the rectangle draw.py fitted it to)

    def test_a_figure_with_a_layout_engine_of_its_own_is_left_to_it(self):
        fig, parts, _ = self.applied(overview_figure, sizes={FIGURE_TITLE: "30"}, texts={"Signal: Y label": "Signal (a.u.)"})
        self.assertEqual(fig.get_layout_engine().__class__.__name__, "TightLayoutEngine")
        fig.canvas.draw()
        self.assertEqual(fig.axes[1].get_ylabel(), "Signal (a.u.)")


class TestTheRules(unittest.TestCase):
    def test_a_text_equal_to_the_drawn_one_is_no_edit_and_empty_text_is_no_text(self):
        _, parts = parts_of(peth_figure)
        edits = restyle.edited(parts, FigureEdits(), texts={"Figure title": "Event PETH — Press", "Colour bar label": "", "No such text": "x"})
        self.assertEqual(edits.texts, {"Colour bar label": ""})
        self.assertEqual(restyle.edited(parts, edits, texts={"Colour bar label": "Z-score"}).texts, {})

    def test_a_size_is_a_whole_number_of_points_not_below_the_smallest_legible_and_what_is_not_a_number_is_left_alone(self):
        _, parts = parts_of(peth_figure)
        self.assertEqual(restyle.edited(parts, FigureEdits(), sizes={FIGURE_TITLE: "2"}).sizes, {FIGURE_TITLE: 6})
        self.assertEqual(restyle.edited(parts, FigureEdits(), sizes={FIGURE_TITLE: "big"}).sizes, {})
        kept = restyle.edited(parts, FigureEdits(sizes={LABEL: 12}), sizes={LABEL: "twelve"})
        self.assertEqual(kept.sizes, {LABEL: 12})
        self.assertEqual(restyle.edited(parts, kept, sizes={LABEL: str(round(parts.size_default(LABEL)))}).sizes, {})      # the drawn size is no edit
        self.assertEqual(restyle.edited(parts, FigureEdits(), sizes={PANEL_TITLE: "20"}).sizes, {})                       # (this figure has no panel titles)

    def test_bold_grid_and_the_legends_place_are_edits_only_when_they_are_not_as_drawn(self):
        _, parts = parts_of(curve_figure)
        self.assertEqual((restyle.edited(parts, FigureEdits(), bold=True, grid=True, legend_loc="best").bold,
                          restyle.edited(parts, FigureEdits(), grid=True).grid, restyle.edited(parts, FigureEdits(), legend_loc="best").legend_loc), (None, None, None))
        edits = restyle.edited(parts, FigureEdits(), bold=False, grid=False, legend_loc="center")
        self.assertEqual((edits.bold, edits.grid, edits.legend_loc), (False, False, "center"))

    def test_a_colour_that_is_the_drawn_one_is_no_override_and_none_takes_the_override_away(self):
        _, parts = parts_of(compare_figure)
        edits = restyle.edited(parts, FigureEdits(), colors=[("A (n=3)", "#FF0000", "#0072b2"), ("B (n=4)", "#D55E00", "#d55e00")])
        self.assertEqual(edits.colors, {"A (n=3)": "#FF0000"})
        self.assertEqual(restyle.edited(parts, edits, colors=[("A (n=3)", None, "#0072b2")]).colors, {})

    def test_the_dot_is_between_zero_and_the_largest_and_the_drawn_size_is_no_edit(self):
        _, parts = parts_of(curve_figure)
        self.assertEqual(restyle.edited(parts, FigureEdits(), point_size=99).point_size, figures.view.MAX_POINT_SIZE)
        self.assertEqual(restyle.edited(parts, FigureEdits(), point_size=-3).point_size, 0.0)
        self.assertIsNone(restyle.edited(parts, FigureEdits(point_size=3), point_size=6).point_size)                    # the anchors' own dot
        self.assertEqual(restyle.edited(parts, FigureEdits(point_size=3)).point_size, 3)                                # (left alone: as it was)

    def test_a_legend_entry_is_an_edit_only_if_it_is_renamed_or_hidden_and_an_empty_name_is_the_one_it_has(self):
        _, parts = parts_of(compare_figure)
        edits = restyle.edited(parts, FigureEdits(), entries=[("A (n=3)", "A (n=3)", True), ("B (n=4)", "  ", False), ("none", "x", True)])
        self.assertEqual(edits.legend_entries, {"B (n=4)": ("B (n=4)", False)})
        self.assertEqual(restyle.edited(parts, edits, entries=[("B (n=4)", "B (n=4)", True)]).legend_entries, {})

    def test_the_edits_given_are_never_the_ones_changed(self):
        _, parts = parts_of(peth_figure)
        edits = FigureEdits()
        restyle.edited(parts, edits, texts={"Figure title": "x"}, colors=[("Group trace: Mean", "#123456", "#000000")], sizes={LABEL: "20"})
        self.assertTrue(edits.is_empty())

    def test_what_was_edited_is_told_in_sentences_for_the_record_beside_an_export(self):
        _, parts = parts_of(peth_figure)
        self.assertEqual(restyle.edit_notes(parts, FigureEdits()), [])
        edits = restyle.edited(parts, FigureEdits(), texts={"Figure title": "Mine"}, sizes={FIGURE_TITLE: "30"}, grid=True, point_size=3,
                               colors=[("Group trace: Mean", "#ff0000", "#000000")], legend_loc="center", entries=[("Group trace: SEM", "se", False)])
        notes = restyle.edit_notes(parts, edits)
        self.assertEqual(len(notes), 7)
        self.assertIn("Edit Attributes — text (Figure title): 'Event PETH — Press' -> 'Mine'", notes)
        self.assertIn("Edit Attributes — title size: 30 pt", notes)
        self.assertIn("Edit Attributes — line colour (Group trace: Mean): #ff0000", notes)
        self.assertIn("Edit Attributes — legend entry (Group trace: SEM): called 'se', hidden", notes)


class DialogCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, factory=peth_figure):
        self.fig = factory()
        self.window = QDialog()
        self.addCleanup(self.window.close)
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.editable = EditableFigure(types.SimpleNamespace(), self.window, self.fig, self.canvas)
        self.editable.drawn()
        return FigureAttributesDialog(self.window, self.editable)

    def apply(self, tweak, factory=None):
        dlg = self.make(factory) if factory else FigureAttributesDialog(self.window, self.editable)
        tweak(dlg)
        dlg._apply()
        return dlg


class TestTheDialog(DialogCase):
    def test_it_has_a_field_for_every_text_a_size_for_each_kind_a_row_for_every_line_and_every_legend_entry(self):
        dlg = self.make()
        self.assertEqual(list(dlg.text_fields), [t.key for t in self.editable.parts.texts])
        self.assertEqual(dlg.text_fields["Figure title"].text(), "Event PETH — Press")
        self.assertEqual(list(dlg.size_fields), [FIGURE_TITLE, LABEL])                                              # (the legend's size is the legend's own)
        self.assertEqual(dlg.size_fields[FIGURE_TITLE].text(), str(round(self.editable.parts.size_default(FIGURE_TITLE))))
        self.assertEqual([row.orig for row in dlg.color_rows], ["Group trace: Mean"])
        self.assertEqual([key for key, _show, _field in dlg.entry_fields], ["Group trace: Mean", "Group trace: SEM"])
        self.assertEqual((dlg.leg_loc_combo.currentText(), dlg.leg_fs.text()), ("upper right", str(round(self.editable.parts.legends[0].size))))
        self.assertTrue(dlg.cb_bold.isChecked())
        self.assertFalse(dlg.cb_grid.isChecked())
        self.assertFalse(dlg.btn_reset.isEnabled())                                                                  # (nothing to reset yet)

    def test_a_figure_with_no_legend_has_no_legend_section_and_one_with_no_lines_has_the_lines_sections_off(self):
        dlg = self.make(zscore_figure)
        self.assertEqual((dlg.entry_fields, dlg.leg_loc_combo), ([], None))
        blank = self.make(blank_compare_figure)
        self.assertEqual((blank.color_rows, blank.points.isEnabled(), blank.cb_grid.isEnabled()), ([], False, False))

    def test_apply_with_nothing_touched_changes_nothing(self):
        dlg = self.make()
        before = png(self.fig)
        dlg._apply()
        self.assertTrue(self.editable.edits.is_empty())
        self.assertEqual(png(self.fig), before)
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)

    def test_what_is_typed_picked_and_moved_is_put_on_the_figure(self):
        def tweak(d):
            d.text_fields["Figure title"].setText("My title")
            d.text_fields["Colour bar label"].setText("")
            d.size_fields[FIGURE_TITLE].setText("30")
            d.cb_bold.setChecked(False)
            d.cb_grid.setChecked(True)
            d.color_rows[0].override = "#d62728"
            d.points.spin.setValue(3)
            d.leg_fs.setText("11")
            d.leg_loc_combo.setCurrentText("lower right")
            d.entry_fields[1][1].setChecked(False)
            d.entry_fields[0][2].setText("Average")

        self.apply(tweak, peth_figure)
        edits = self.editable.edits
        self.assertEqual((edits.texts, edits.sizes, edits.bold, edits.grid, edits.colors, edits.point_size, edits.legend_loc),
                         ({"Figure title": "My title", "Colour bar label": ""}, {FIGURE_TITLE: 30, LEGEND: 11}, False, True, {"Group trace: Mean": "#d62728"}, 3, "lower right"))
        self.assertEqual(edits.legend_entries, {"Group trace: Mean": ("Average", True), "Group trace: SEM": ("SEM", False)})
        self.assertEqual(self.fig._suptitle.get_text(), "My title")
        self.assertEqual([t.get_text() for t in self.fig.axes[1].get_legend().get_texts()], ["Average"])
        self.assertEqual(self.fig.axes[1].lines[0].get_markersize(), 3)
        self.assertEqual(self.fig.pyat_edit_notes, restyle.edit_notes(self.editable.parts, edits))

    def test_opened_again_it_shows_what_was_edited_and_reset_all_puts_the_figure_back(self):
        self.apply(lambda d: (d.text_fields["Figure title"].setText("My title"), d.points.spin.setValue(4)), peth_figure)
        again = FigureAttributesDialog(self.window, self.editable)
        self.assertEqual((again.text_fields["Figure title"].text(), again.points.spin.value()), ("My title", 4))
        self.assertTrue(again.btn_reset.isEnabled())
        again.btn_reset.click()
        self.assertTrue(self.editable.edits.is_empty())
        self.assertEqual((self.fig._suptitle.get_text(), self.fig.pyat_edit_notes), ("Event PETH — Press", []))
        self.assertEqual(FigureAttributesDialog(self.window, self.editable).text_fields["Figure title"].text(), "Event PETH — Press")

    def test_a_size_that_is_not_a_number_is_ignored_and_a_dot_left_alone_stays_as_it_was(self):
        self.apply(lambda d: (d.size_fields[LABEL].setText("lots"), d.points.spin.setValue(4)), peth_figure)
        self.assertEqual((self.editable.edits.sizes, self.editable.edits.point_size), ({}, 4))
        self.apply(lambda d: d.text_fields["Figure title"].setText("t"))                                           # (the dot was not touched this time)
        self.assertEqual(self.editable.edits.point_size, 4)
        self.apply(lambda d: d.points.btn_reset.click())
        self.assertIsNone(self.editable.edits.point_size)

    def test_a_failure_in_putting_the_edits_on_never_stops_the_window_showing_its_figure(self):
        self.make()
        logged = []
        with mock.patch.object(restyle, "describe", side_effect=RuntimeError("odd figure")),                 mock.patch.object(figure_attributes.errorlog, "error", lambda *a, **k: logged.append(a[0])), mock.patch.object(self.canvas, "draw_idle") as shown:
            self.editable.drawn()
        shown.assert_called_once()
        self.assertEqual(logged, ["Could not put the Edit Attributes edits on the figure"])
        self.assertIsNone(self.editable.parts)                                                                      # (and Edit Attributes says there is nothing to edit)

    def test_nothing_to_edit_before_the_first_drawing_says_so(self):
        errors = []
        editable = EditableFigure(types.SimpleNamespace(), QDialog(), figures.new_event_peth_figure(), mock.Mock())
        with mock.patch.object(figure_attributes, "show_error", lambda ctx, message: errors.append(message)):
            editable.edit()
        self.assertEqual(len(errors), 1)
        self.assertIn("nothing to edit", errors[0])


class OpenWindows(WorkspaceCase):
    """The real analysis windows, as tabs of the real main window (offscreen)."""

    def open(self, launch, *args):
        with mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=QUIET_TOAST), \
                mock.patch.object(event_peth, "show_window_toast", mock.Mock()), mock.patch.object(overview, "show_window_toast", mock.Mock()), \
                mock.patch.object(event_compare, "show_window_toast", mock.Mock()), mock.patch("physicsanalysis_qt.analysis.result_window.show_window_toast"):
            launch(*args)
        self.settle()
        return self.ws.page_at(self.ws.count() - 1)

    def quiet(self):
        return mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=QUIET_TOAST)

    def edit(self, page, **changes):
        editable = page.editable
        editable.set_edits(restyle.edited(editable.parts, editable.edits, **changes))

    def dialogs_opened(self):
        """Patches the dialogs' exec so a click on an Edit Attributes button records which dialog it opened instead of waiting for it."""
        opened = []
        for cls in (FigureAttributesDialog, AttributesDialog):
            patcher = mock.patch.object(cls, "exec", lambda dlg: opened.append(dlg) or 0)
            patcher.start()
            self.addCleanup(patcher.stop)
        return opened

    def toolbar_button(self):
        return next(b for b in self.ctx.win.findChildren(QPushButton) if b.text() == "Edit Attributes")


class TestEveryWindowWithAFigure(OpenWindows):
    def test_each_has_a_figure_to_edit_and_a_button_in_its_header(self):
        x = self.ctx.cache["x"]
        i1, i2 = int(np.searchsorted(x, 12.0)), int(np.searchsorted(x, 18.0))
        for name, launch, args in (("Z-Score", peth.launch_zscore_peth, (self.ctx, 20.0)), ("AUC", auc.launch_auc, (self.ctx, 20.0)), ("FFT", fft.launch_fft, (self.ctx, 20.0)),
                                   ("Curve Fit", curve_fit.launch_curve_fit, (self.ctx, None, (i1, 0), (i2, 0))), ("Event PETH", event_peth.launch_event_peth, (self.ctx,)),
                                   ("Compare Events", event_compare.launch_event_compare, (self.ctx, ["L1P¹"], (3.0, 6.0, 2.0))),
                                   ("Recording Overview", overview.launch_recording_overview, (self.ctx,))):
            with self.subTest(name):
                page = self.open(launch, *args)
                editable = page.editable
                self.assertIsNotNone(editable, name)
                self.assertIs(editable.fig, page.dialog.editable_figure.fig)
                self.assertIsNotNone(editable.parts, f"{name}: its figure was drawn, so it is described")
                self.assertTrue(editable.parts.texts)
                self.assertIsNotNone(page.header.edit_button)

    def test_a_window_with_no_figure_has_no_such_button_and_the_toolbar_button_edits_the_recording_then(self):
        page = workspace.present(self.ctx, self.dialog(), "A")
        self.assertIsNone(page.editable)
        self.assertIsNone(page.header.edit_button)
        self.assertIsNone(self.ws.front_editable())
        opened = self.dialogs_opened()
        self.toolbar_button().click()
        self.assertEqual([type(d) for d in opened], [AttributesDialog])
        self.assertEqual(self.ws.currentIndex(), 0)                                                                 # the recording was brought to the front for it


class TestTheButtons(OpenWindows):
    def test_the_toolbar_button_edits_whichever_is_in_front(self):
        opened = self.dialogs_opened()
        page = self.open(event_peth.launch_event_peth, self.ctx)
        self.toolbar_button().click()
        self.assertEqual([type(d) for d in opened], [FigureAttributesDialog])
        self.assertIs(opened[0].editable, page.editable)
        self.assertEqual(self.ws.currentIndex(), 1)                                                                 # (the window stays in front)
        self.ws.show_recording()
        self.toolbar_button().click()
        self.assertEqual([type(d) for d in opened], [FigureAttributesDialog, AttributesDialog])
        compare = self.open(event_compare.launch_event_compare, self.ctx, ["L1P¹"], (3.0, 6.0, 2.0))
        self.toolbar_button().click()
        self.assertIs(opened[-1].editable, compare.editable)                                                        # each tab has its own

    def test_the_headers_button_edits_that_window_docked_or_popped_out(self):
        opened = self.dialogs_opened()
        first = self.open(event_peth.launch_event_peth, self.ctx)
        second = self.open(overview.launch_recording_overview, self.ctx)
        first.header.edit_button.click()                                                                            # (the Event PETH is not the tab in front)
        self.assertIs(opened[-1].editable, first.editable)
        second.pop_out()
        second.header.edit_button.click()
        self.assertIs(opened[-1].editable, second.editable)
        self.assertIs(opened[-1].parentWidget(), second.dialog)                                                     # parented to the window, so it stays above it
        second.dock()
        self.assertIsNotNone(second.header.edit_button)

    def test_an_edit_is_still_there_after_a_window_is_popped_out_and_docked(self):
        page = self.open(event_peth.launch_event_peth, self.ctx)
        self.edit(page, texts={"Figure title": "Mine"})
        page.pop_out()
        page.dock()
        self.assertEqual(page.editable.fig._suptitle.get_text(), "Mine")


class TestEditsSurviveRedraws(OpenWindows):
    def test_event_peth_keeps_its_edits_through_views_trials_recalculating_and_another_event(self):
        page = self.open(event_peth.launch_event_peth, self.ctx)
        dlg = page.dialog
        self.assertFalse(hasattr(dlg, "e_title"))                                                                   # (the title is typed in Edit Attributes)
        first_event = dlg.event_name
        self.assertEqual(dlg.fig._suptitle.get_text(), f"Event PETH — {first_event}")
        self.edit(page, texts={"Group trace: Y label": "z (my units)"}, sizes={LABEL: "13"}, colors=[("Group trace: Mean", "#d62728", "#000000")], point_size=2)
        dlg._view_buttons["trials"].setChecked(True)
        self.assertEqual(dlg.fig.axes[1].get_ylabel(), "z (my units)")
        self.assertEqual(dlg.fig.axes[1].lines[0].get_markersize(), 2)                                              # (the trials' own lines have the dots too)
        dlg._view_buttons["zscore"].setChecked(True)
        dlg.trial_list.item(1).setCheckState(workspace.Qt.CheckState.Unchecked)
        mean = dlg.fig.axes[1].lines[0]
        self.assertEqual((dlg.fig.axes[1].get_ylabel(), dlg.fig.axes[1].yaxis.label.get_fontsize(), mean.get_color()), ("z (my units)", 13, "#d62728"))
        with self.quiet():
            dlg._run(dlg.event_name)                                                                                # Recalculate
        self.assertEqual(dlg.fig.axes[1].get_ylabel(), "z (my units)")
        other = next(dlg.combo_event.itemData(i) for i in range(dlg.combo_event.count()) if dlg.combo_event.itemData(i) != first_event)
        with self.quiet():
            dlg.combo_event.setCurrentIndex(dlg.combo_event.findData(other))
        self.assertEqual(dlg.event_name, other)
        self.assertEqual((dlg.fig.axes[1].get_ylabel(), dlg.fig.axes[1].lines[0].get_color()), ("z (my units)", "#d62728"))
        self.assertEqual(dlg.fig._suptitle.get_text(), f"Event PETH — {other}")                                     # the title follows the event until one is typed

    def test_a_title_typed_stays_through_another_event_and_reset_all_lets_it_follow_again(self):
        page = self.open(event_peth.launch_event_peth, self.ctx)
        dlg = page.dialog
        self.edit(page, texts={"Figure title": "Presses, rat 7"})
        other = next(dlg.combo_event.itemData(i) for i in range(dlg.combo_event.count()) if dlg.combo_event.itemData(i) != dlg.event_name)
        with self.quiet():
            dlg.combo_event.setCurrentIndex(dlg.combo_event.findData(other))
        self.assertEqual(dlg.fig._suptitle.get_text(), "Presses, rat 7")
        page.editable.reset()
        self.assertEqual(dlg.fig._suptitle.get_text(), f"Event PETH — {other}")

    def test_compare_events_keeps_its_edits_through_comparing_again_and_the_sem_bands(self):
        page = self.open(event_compare.launch_event_compare, self.ctx, ["L1P¹", "L1P⁰"], (3.0, 6.0, 2.0))
        dlg = page.dialog
        names = [s.key for s in page.editable.parts.series]
        self.assertEqual(len(names), 2)
        self.edit(page, colors=[(names[0], "#00ff00", page.editable.parts.series[0].default_color)], entries=[(names[1], "second", True)], grid=True)
        dlg.chk_sem.setChecked(False)
        with self.quiet():
            dlg._compare()
        ax = dlg.fig.axes[0]
        self.assertEqual([line.get_color() for line in ax.lines][0], "#00ff00")
        self.assertIn("second", [t.get_text() for t in ax.get_legend().get_texts()])
        self.assertTrue(ax.xaxis.get_gridlines()[0].get_visible())

    def test_the_overview_keeps_its_edits_when_panels_are_dropped_and_put_in_another_order(self):
        page = self.open(overview.launch_recording_overview, self.ctx)
        dlg = page.dialog
        self.edit(page, texts={"Figure title": "Whole session"}, sizes={PANEL_TITLE: "15"})
        dlg._tick_only(1)                                                                                           # only the Signal panel
        dlg._tick_all()
        dlg.panel_list.setCurrentRow(1)
        dlg._move(-1)                                                                                               # the Signal above the Control
        self.assertEqual(dlg.fig._suptitle.get_text(), "Whole session")
        self.assertEqual({ax._left_title.get_fontsize() for ax in dlg.fig.axes if ax.get_title(loc="left")}, {15})

    def test_curve_fit_keeps_its_edits_through_recalculating_with_another_model(self):
        x = self.ctx.cache["x"]
        page = self.open(curve_fit.launch_curve_fit, self.ctx, None, (int(np.searchsorted(x, 12.0)), 0), (int(np.searchsorted(x, 18.0)), 0))
        dlg = page.dialog
        self.edit(page, texts={"Title": "My fit"}, grid=False)
        dlg.model_combo.setCurrentIndex(1)
        with self.quiet():
            dlg._run_fit()
        self.assertEqual(dlg.sub_fig.axes[0].get_title(), "My fit")
        self.assertFalse(dlg.sub_fig.axes[0].xaxis.get_gridlines()[0].get_visible())


class TestWhatIsExported(OpenWindows):
    def test_the_figure_written_is_the_edited_one_and_its_data_says_the_new_names(self):
        page = self.open(event_compare.launch_event_compare, self.ctx, ["L1P¹", "L1P⁰"], (3.0, 6.0, 2.0))
        key = page.editable.parts.series[0].key
        self.edit(page, texts={"Figure title": "Presses and releases"}, entries=[(key, "Presses", True)])
        out = io.BytesIO()
        figures.render_figure(page.editable.fig, out, fmt="svg")
        self.assertIn("Presses and releases", out.getvalue().decode("utf-8"))
        self.assertIn("Presses", set(figures.figure_tables(page.editable.fig)["data"]["series"]))

    def test_the_record_beside_an_export_lists_the_edits(self):
        page = self.open(event_compare.launch_event_compare, self.ctx, ["L1P¹", "L1P⁰"], (3.0, 6.0, 2.0))
        written = []
        settings = {"format": "png", "dpi": 100, "transparent": False, "editable_text": True, "data_csv": False}
        with mock.patch.object(figure_export._context, "save_settings"), mock.patch.object(figure_export._context, "export_file", lambda *a, **k: written.append(k)):
            figure_export.write_export(self.ctx, page.editable.fig, "EventCompare", "", {"kind": "event_compare", "parameters": {}}, settings, {})
            self.assertEqual(written[-1]["provenance"]["notes"], ["Figure exported as PNG image at 100 dpi"])         # as drawn: nothing to add
            self.edit(page, texts={"Figure title": "Mine"}, grid=True)
            figure_export.write_export(self.ctx, page.editable.fig, "EventCompare", "", {"kind": "event_compare", "parameters": {}}, settings, {})
        notes = written[-1]["provenance"]["notes"]
        self.assertEqual(notes[0], "Figure exported as PNG image at 100 dpi")
        self.assertEqual(notes[1:], [n for n in page.editable.fig.pyat_edit_notes])
        self.assertTrue(any("'Mine'" in n for n in notes) and any("grid shown" in n for n in notes))

    def test_export_figure_starts_from_the_edited_words(self):
        page = self.open(event_compare.launch_event_compare, self.ctx, ["L1P¹", "L1P⁰"], (3.0, 6.0, 2.0))
        self.edit(page, texts={"Figure title": "Mine"})
        dialog = figure_export.FigureExportDialog(self.ctx, page.editable.fig)
        self.assertEqual({item.caption: field.text() for item, field in dialog.fields.items()}["Figure title"], "Mine")
        self.assertEqual(dialog.edits(), {})                                                                         # (and is no further edit of its own)


class TestPointsAndOpenResults(OpenWindows):
    def test_export_plot_says_where_to_get_points_and_can_resize_them_once_edit_attributes_gave_them(self):
        page = self.open(event_compare.launch_event_compare, self.ctx, ["L1P¹", "L1P⁰"], (3.0, 6.0, 2.0))
        shown = []
        with mock.patch.object(figure_export.FigureExportDialog, "exec", lambda dlg: shown.append(dlg) or 0):
            dispatch.export_figure_to_file(self.ctx, page.editable.fig, "EventCompare")
            self.edit(page, point_size=3)
            dispatch.export_figure_to_file(self.ctx, page.editable.fig, "EventCompare")
        without, with_points = shown
        self.assertFalse(without.has_points)
        self.assertIn("Edit Attributes", without.no_points_note)
        self.assertTrue(with_points.has_points)
        self.assertTrue(with_points.point_spin.parentWidget().isEnabled())

    def test_a_result_read_back_from_files_has_a_figure_to_edit_too(self):
        dlg = ResultsFigureDialog(self.ctx.win, self.ctx, peth_figure(), "Event PETH", self.tmp)
        page = workspace.present(self.ctx, dlg, "Results", recording=False)
        self.assertIs(page.editable, dlg.editable_figure)
        self.assertIsNotNone(page.header.edit_button)
        self.edit(page, texts={"Figure title": "Read back"})
        self.assertEqual(dlg.fig._suptitle.get_text(), "Read back")


class TestTheRecordingsPlotIsStillEditedAsBefore(OpenWindows):
    def test_with_the_recording_in_front_edit_attributes_is_the_recordings_dialog(self):
        opened = self.dialogs_opened()
        open_attributes_window(self.ctx)
        self.assertEqual([type(d) for d in opened], [AttributesDialog])
        self.assertEqual(self.ws.currentIndex(), 0)

    def test_without_a_workspace_it_is_the_recordings_dialog_as_it_always_was(self):
        opened = []
        ctx = types.SimpleNamespace(win=self.ctx.win)
        with mock.patch.object(attributes, "AttributesDialog", lambda parent, c: types.SimpleNamespace(exec=lambda: opened.append(parent))):
            open_attributes_window(ctx)
        self.assertEqual(opened, [self.ctx.win])


if __name__ == "__main__":
    unittest.main()
