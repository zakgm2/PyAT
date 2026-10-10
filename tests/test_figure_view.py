"""figures/view.py: Export View — a recording's main plot redrawn as a publication figure (the traces, markers, highlights, text boxes, title, labels and
legend, in the range asked for) — and how the main plot's lines are styled. What the plot shows (which lines, their numbers, the range, the markers in it)
is the analysis library's view plan; its tests are the library's (tests/test_view.py there)."""

import os
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
from numpy.testing import assert_array_equal

from physicsanalysis_qt.figures import view as V

from tests.figure_fixtures import generic_cache, make_cache, oxysoft_cache

NORMALIZED, MAIN = "Normalized (dF/F)", "Main Driver (x465A)"


class TestTraces(unittest.TestCase):
    def test_a_tdt_recording_shows_its_normalized_trace_by_default(self):
        traces, title, x_label, y_label = V.view_traces(make_cache())
        (t,) = traces
        self.assertEqual((t.label, t.color, t.lw, t.alpha, t.csv_name), (NORMALIZED, "blue", 1.5, 0.8, NORMALIZED))
        self.assertEqual((title, x_label, y_label), (f"{NORMALIZED} — Rec", "Time (s)", "Amplitude"))

    def test_a_signal_with_no_colour_of_its_own_gets_the_apps(self):
        cache = make_cache()
        cache["signals"]["isosbestic"] = {"label": "Isosbestic (x415A)", "y": cache["corr"]}
        cache["signals"]["red"] = {"label": "Red (x560)", "y": cache["corr"]}
        colours = {k: V.view_traces(cache, signals=[k])[0][0].color for k in cache["signals"]}
        self.assertEqual(colours, {"normalized": "blue", "main_driver": "#2E7D32", "isosbestic": "#7B1FA2", "red": "#555555"})

    def test_a_colour_the_cache_carries_wins(self):
        cache = make_cache()
        cache["signals"]["normalized"]["color"] = "purple"
        self.assertEqual(V.view_traces(cache)[0][0].color, "purple")

    def test_one_signal_ticked_shows_that_one_and_two_are_overlaid_in_the_recordings_order(self):
        cache = make_cache()
        (t,) = V.view_traces(cache, signals=["main_driver"])[0]
        self.assertEqual(t.label, MAIN)
        traces, title, _, _ = V.view_traces(cache, signals=["main_driver", "normalized"])
        self.assertEqual([t.label for t in traces], [NORMALIZED, MAIN])
        self.assertEqual(title, "Overlay (2) — Rec")

    def test_a_signal_the_recording_does_not_have_falls_back_to_the_first(self):
        (t,) = V.view_traces(make_cache(), signals=["isosbestic"])[0]
        self.assertEqual(t.label, NORMALIZED)

    def test_a_colour_override_is_filed_under_the_lines_own_name_and_the_default_is_kept(self):
        (t,) = V.view_traces(make_cache(), line_colors={NORMALIZED: "#123456"})[0]
        self.assertEqual((t.color, t.default_color, t.key), ("#123456", "blue", NORMALIZED))

    def test_a_source_with_no_signals_map_shows_its_corrected_trace(self):
        cache = make_cache()
        del cache["signals"]
        (t,) = V.view_traces(cache)[0]
        self.assertEqual((t.label, t.color), ("dF/F (corrected)", "blue"))
        assert_array_equal(t.y, cache["corr"])

    def test_an_oxysoft_recording_has_a_faint_line_per_channel_and_a_bold_mean_per_group(self):
        traces, title, x_label, y_label = V.view_traces(oxysoft_cache(thb=True))
        self.assertEqual([t.label for t in traces],
                         ["O2Hb channels", "HHb channels", "_nolegend_", "_nolegend_", "Mean O2Hb  [FF: 91.2%]", "Mean HHb  [FF: 91.2%]", "Mean tHb  [FF: 91.2%]"])
        channels, means = traces[:4], traces[4:]
        self.assertTrue(all((t.lw, t.alpha, t.snap) == (0.8, 0.5, False) for t in channels))
        self.assertTrue(all((t.lw, t.alpha, t.snap) == (2.0, 1.0, True) for t in means))
        self.assertEqual([t.color for t in channels], ["#FF9999", "#99BBFF", "#FF9999", "#99BBFF"])
        self.assertEqual([t.key for t in channels], ["O2Hb channels", "HHb channels"] * 2)               # a group's lines follow the group's colour
        self.assertEqual([t.csv_name for t in channels], ["O2Hb ch1", "HHb ch1", "O2Hb ch2", "HHb ch2"])
        self.assertEqual((title, y_label), ("NIRS — NIRS-1", "Delta Concentration (uM)"))

    def test_one_override_colours_every_line_of_a_channel_group(self):
        traces = V.view_traces(oxysoft_cache(), line_colors={"O2Hb channels": "#AA0000"})[0]
        self.assertEqual([t.color for t in traces[:4]], ["#AA0000", "#99BBFF", "#AA0000", "#99BBFF"])

    def test_a_generic_table_draws_each_column_without_its_gaps_and_keeps_them_in_the_data(self):
        traces, title, x_label, y_label = V.view_traces(generic_cache())
        right = next(t for t in traces if t.label == "Right")
        self.assertEqual((len(right.x), len(right.y_full)), (46, 50))
        self.assertEqual((right.marker, right.markersize, right.lw), ("o", 4, 1.8))
        self.assertEqual((title, x_label, y_label), ("Sheet1", "Time (s)", "Value"))
        self.assertEqual([t.color for t in traces], ["#CC0000", "#0033CC"])


class TestAttributes(unittest.TestCase):
    def test_the_defaults_are_the_apps(self):
        a = V.default_plot_attrs()
        self.assertEqual((a["title"], a["title_fs"], a["xlabel_fs"], a["ylabel_fs"], a["leg_fs"], a["leg_loc"], a["bold"], a["line_colors"]),
                         (None, 24, 16, 16, 14, "upper left", True, {}))
        self.assertIsNot(V.default_plot_attrs()["line_colors"], a["line_colors"])                 # nobody's edits leak into the next one

    def test_changes_go_on_top_and_are_checked(self):
        a = V.plot_attrs(title="T", leg_loc="best", line_colors={"x": "#123456"}, leg_entries=[["a", "b", 1]])
        self.assertEqual((a["title"], a["leg_loc"], a["leg_entries"]), ("T", "best", [("a", "b", True)]))
        for bad, message in ((dict(nope=1), "unknown plot attribute 'nope'"), (dict(leg_loc="middle"), "leg_loc must be one of upper left"),
                             (dict(title_fs="big"), "title_fs is a font size"), (dict(leg_fs=0), "leg_fs is a font size"),
                             (dict(line_colors={"x": "not a colour"}), "the colour for 'x' is not a colour"),
                             (dict(leg_entries=[("a",)]), "leg_entries is a list of")):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, message):
                V.plot_attrs(**bad)


class TestTheFigure(unittest.TestCase):
    def setUp(self):
        self.cache = make_cache()
        self.cache["markers"] = []                    # the fixture's one note is not what these tests are about

    def ax(self, **kw):
        return V.build_view(self.cache, **kw).fig.axes[0]

    def test_the_automatic_text_is_the_signals_and_the_recordings(self):
        ax = self.ax()
        self.assertEqual((ax.get_title(), ax.get_xlabel(), ax.get_ylabel()), (f"{NORMALIZED} — Rec", "Time (s)", "Amplitude"))
        self.assertEqual(ax.title.get_fontweight(), "bold")
        self.assertEqual((ax.title.get_fontsize(), ax.xaxis.label.get_fontsize()), (24, 16))

    def test_a_title_and_labels_of_your_own_and_their_sizes(self):
        ax = self.ax(attrs=dict(title="My title", xlabel="Elapsed (s)", ylabel="ΔF/F", title_fs=20, xlabel_fs=14, ylabel_fs=15, bold=False))
        self.assertEqual((ax.get_title(), ax.get_xlabel(), ax.get_ylabel()), ("My title", "Elapsed (s)", "ΔF/F"))
        self.assertEqual((ax.title.get_fontsize(), ax.xaxis.label.get_fontsize(), ax.yaxis.label.get_fontsize()), (20, 14, 15))
        self.assertEqual(ax.title.get_fontweight(), "normal")

    def test_a_tiny_font_size_is_kept_readable(self):
        ax = self.ax(attrs=dict(title_fs=2, xlabel_fs=2, leg_fs=2))
        self.assertEqual((ax.title.get_fontsize(), ax.xaxis.label.get_fontsize(), ax.get_legend().get_texts()[0].get_fontsize()), (8, 6, 5))

    def test_the_legend_names_the_lines_and_can_be_renamed_hidden_and_moved(self):
        self.assertEqual([t.get_text() for t in self.ax().get_legend().get_texts()], [NORMALIZED])
        ax = self.ax(signals=["normalized", "main_driver"], attrs=dict(leg_entries=[(NORMALIZED, "GCaMP", True), (MAIN, MAIN, False)], leg_loc="lower right"))
        self.assertEqual([t.get_text() for t in ax.get_legend().get_texts()], ["GCaMP"])
        self.assertEqual(ax.get_legend()._loc, 4)
        self.assertEqual(sum(1 for line in ax.lines if line.get_label() == MAIN), 1)                 # a hidden entry's line is still drawn
        hidden = self.ax(attrs=dict(leg_entries=[(NORMALIZED, NORMALIZED, False)]))
        self.assertIsNone(hidden.get_legend())

    def test_a_colour_override_is_the_lines_colour(self):
        line = next(l for l in self.ax(attrs=dict(line_colors={NORMALIZED: "#123456"})).lines if l.get_label() == NORMALIZED)
        self.assertEqual(line.get_color(), "#123456")

    def test_the_range_is_the_one_asked_for_or_all_of_the_recording_with_a_little_room(self):
        ax = self.ax(xlim=(40.0, 80.0), ylim=(-1.0, 3.0))
        self.assertEqual((ax.get_xlim(), ax.get_ylim()), ((40.0, 80.0), (-1.0, 3.0)))
        lo, hi = self.ax().get_xlim()
        x = self.cache["x"]
        self.assertAlmostEqual(lo, x[0] - 0.02 * (x[-1] - x[0]))
        self.assertAlmostEqual(hi, x[-1] + 0.02 * (x[-1] - x[0]))
        self.assertEqual(self.ax(xlim=(80.0, 40.0)).get_xlim(), (40.0, 80.0))                       # either way round

    def test_it_is_a_white_page_with_black_text(self):
        fig = V.build_view(self.cache).fig
        self.assertEqual(tuple(fig.get_facecolor()), (1.0, 1.0, 1.0, 1.0))

    def test_the_grid_and_the_size(self):
        self.assertTrue(any(l.get_visible() for l in self.ax().get_xgridlines()))
        self.assertFalse(any(l.get_visible() for l in self.ax(show_grid=False).get_xgridlines()))
        self.assertEqual(tuple(V.build_view(self.cache).fig.get_size_inches()), (10.0, 5.5))
        self.assertEqual(tuple(V.build_view(self.cache, figsize=(6, 4)).fig.get_size_inches()), (6.0, 4.0))
        self.assertEqual(V.view_figsize(1000, 400), (10.0, 4.0))
        self.assertEqual(V.view_figsize(1000, 100), (10.0, 3.5))                                      # kept between 0.35 and 0.9 of the width
        self.assertEqual(V.view_figsize(0, 0), (10.0, 5.5))

    def test_only_the_markers_in_view_are_drawn_and_listed_under_their_shown_names(self):
        self.cache["markers"] = [{"time": 60.0, "label": "lever", "color": "green", "fontsize": 8},
                                 {"time": 70.0, "label": "L1P", "color": "red", "fontsize": 8, "store": "L1P", "phase": "high"},
                                 {"time": 200.0, "label": "late", "color": "blue", "fontsize": 8}]
        view = V.build_view(self.cache, xlim=(50.0, 100.0), store_labels={"L1P": "Lever"})
        legend = [t.get_text() for t in view.fig.axes[0].get_legend().get_texts()]
        self.assertIn("lever", legend)
        self.assertIn("Lever¹", legend)
        self.assertNotIn("late", legend)
        self.assertEqual([m[:2] for m in view.markers], [(60.0, "lever"), (70.0, "Lever¹")])

    def test_a_marker_with_no_name_is_a_tick_and_a_repeated_name_is_in_the_legend_once(self):
        self.cache["markers"] = [{"time": 60.0, "label": "", "color": "black", "fontsize": 8}, {"time": 61.0, "label": "a", "color": "red", "fontsize": 8},
                                 {"time": 62.0, "label": "a", "color": "red", "fontsize": 8}]
        ax = V.build_view(self.cache, xlim=(50.0, 100.0)).fig.axes[0]
        self.assertEqual([t.get_text() for t in ax.get_legend().get_texts()].count("a"), 1)
        self.assertEqual(sum(1 for t in ax.texts if t.get_text().strip() == "a"), 2)               # but each is labelled on the plot

    def test_a_dragged_label_height_is_kept(self):
        self.cache["markers"] = [{"time": 60.0, "label": "low", "color": "green", "fontsize": 8, "label_y": 0.2}]
        (label,) = [t for t in V.build_view(self.cache, xlim=(50.0, 100.0)).fig.axes[0].texts if t.get_text().strip() == "low"]
        self.assertEqual((label.get_position()[1], label.get_va()), (0.2, "bottom"))

    def test_highlights_in_view_and_text_boxes_come_along(self):
        self.cache["highlights"] = [{"start": 60.0, "end": 70.0, "color": "#FFEB3B"}, {"start": 200.0, "end": 210.0, "color": "#FF4D94"}]
        self.cache["text_annotations"] = [{"x": 65.0, "y": 0.5, "text": "peak here", "fontsize": 11}]
        ax = V.build_view(self.cache, xlim=(50.0, 100.0)).fig.axes[0]
        self.assertEqual(len(ax.patches), 1)
        self.assertEqual(ax.patches[0].get_alpha(), 0.35)
        self.assertIn("peak here", [t.get_text() for t in ax.texts])

    def test_a_long_recording_is_thinned_without_losing_its_peaks(self):
        n = 300_000
        x = np.arange(n) / 1000.0
        y = np.sin(x)
        y[123_456] = 50.0
        self.cache.update(x=x, corr=y, raw=y)
        self.cache["signals"]["normalized"]["y"] = y
        line = next(l for l in V.build_view(self.cache, max_points=20_000).fig.axes[0].lines if l.get_label() == NORMALIZED)
        self.assertLessEqual(len(line.get_xdata()), 20_001)
        self.assertEqual(float(np.max(line.get_ydata())), 50.0)
        with mock.patch.object(V, "EXPORT_MAX_POINTS", 5_000):
            line = next(l for l in V.build_view(self.cache).fig.axes[0].lines if l.get_label() == NORMALIZED)
        self.assertLessEqual(len(line.get_xdata()), 5_001)

    def test_the_decimation_keeps_the_extremes_of_every_bin(self):
        x = np.arange(1000.0)
        y = np.zeros(1000)
        y[500], y[501] = 7.0, -7.0
        dx, dy = V.min_max_decimate(x, y, (0, 999), max_points=100)
        self.assertLessEqual(len(dx), 100)
        self.assertEqual((dy.max(), dy.min()), (7.0, -7.0))
        dx, dy = V.min_max_decimate(x, y, (100, 200), max_points=5000)                             # little enough: the visible stretch, a sample beyond each edge
        self.assertEqual((dx[0], dx[-1]), (99.0, 201.0))

    def test_the_figure_can_be_made_by_any_factory(self):
        made = []

        def factory(**kw):
            from matplotlib.figure import Figure
            made.append(Figure(**kw))
            return made[-1]

        self.assertIs(V.build_view(self.cache, figure=factory).fig, made[0])

    def test_a_degenerate_range_does_not_break_the_default_view(self):
        self.cache["x"] = np.array([5.0])
        lo, hi = V.padded_xlim(self.cache["x"])
        self.assertEqual((lo, hi), (4.0, 6.0))


class TestTheDrawnViewAndItsFiles(unittest.TestCase):
    def make_tmp(self):
        import shutil
        import tempfile
        tmp = tempfile.mkdtemp(prefix="pyat-view-")
        self.addCleanup(shutil.rmtree, tmp, True)
        return tmp

    def test_the_csv_is_not_thinned_though_the_drawing_is(self):
        view = V.build_view(make_cache(), xlim=(0.0, 300.0), max_points=500)
        drawn = next(l for l in view.fig.axes[0].lines if l.get_label() == NORMALIZED)
        self.assertLessEqual(len(drawn.get_xdata()), 502)
        self.assertEqual(len(view.data_table()), 30_000)

    def test_save_writes_the_figure_the_data_and_the_markers_as_export_figure_does(self):
        cache = make_cache()
        cache["markers"] = [{"time": 11.0, "label": "lever", "color": "green", "fontsize": 8}]
        tmp = self.make_tmp()
        view = V.build_view(cache, xlim=(10.0, 12.0))
        written = view.save(os.path.join(tmp, "fig.pdf"), software="Test 1.0")
        self.assertEqual([os.path.basename(p) for p in written], ["fig.pdf", "fig_data.csv", "fig_markers.csv"])
        self.assertEqual(Path(written[0]).read_bytes()[:5], b"%PDF-")
        self.assertEqual(len(pd.read_csv(written[1])), len(view.data_table()))
        self.assertEqual([os.path.basename(p) for p in view.save(os.path.join(tmp, "b.png"), data=False)], ["b.png"])

    def test_renamed_words_reach_the_file_and_not_the_figure(self):
        tmp = self.make_tmp()
        view = V.build_view(make_cache(), xlim=(10.0, 12.0))
        (path,) = view.save(os.path.join(tmp, "fig.svg"), data=False, labels={"Time (s)": "Elapsed (s)"})
        self.assertIn("Elapsed (s)", Path(path).read_text(encoding="utf-8"))
        self.assertEqual(view.fig.axes[0].get_xlabel(), "Time (s)")

    def test_a_planned_view_has_no_figure_to_save(self):
        with self.assertRaisesRegex(ValueError, "planned, not drawn"):
            V.plan_view(make_cache()).save("x.png")


if __name__ == "__main__":
    unittest.main()
