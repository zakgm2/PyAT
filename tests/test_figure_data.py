"""The data behind a figure (figures/data.py): exactly what is drawn comes out as rows, read from the artists —
lines, bands, bars, points, error bars, heatmaps — with reference lines, hover artists and invisible things left out."""

import os
import tempfile
import unittest

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from numpy.testing import assert_array_equal

from physicsanalysis_qt.figures import data as fd


def new_fig(nrows=1, ncols=1, **kw):
    fig = Figure(**kw)
    axes = fig.subplots(nrows, ncols, squeeze=False)
    return fig, axes.ravel()


class TestLines(unittest.TestCase):
    def test_a_line_is_its_points_named_by_its_label_with_the_axis_labels(self):
        fig, (ax,) = new_fig()
        x, y = np.linspace(0, 10, 50), np.sin(np.linspace(0, 10, 50))
        ax.plot(x, y, label="Mean")
        ax.set_xlabel("Time from Event (s)")
        ax.set_ylabel("Z-Score")
        ax.set_title("Event PETH")
        t = fd.figure_tables(fig)["data"]
        self.assertEqual(list(t.columns), fd.DATA_COLUMNS)
        self.assertEqual(len(t), 50)
        self.assertEqual(set(t["series"]), {"Mean"})
        self.assertEqual(set(t["kind"]), {"line"})
        self.assertEqual(set(t["panel"]), {"Event PETH"})
        self.assertEqual(set(t["x_label"]), {"Time from Event (s)"})
        self.assertEqual(set(t["y_label"]), {"Z-Score"})
        assert_array_equal(t["x"].to_numpy(), x)
        assert_array_equal(t["y"].to_numpy(), y)
        self.assertTrue(t["y_lower"].isna().all())

    def test_unlabelled_lines_get_numbered_names(self):
        fig, (ax,) = new_fig()
        for k in range(3):
            ax.plot([0, 1, 2], [k, k + 1, k + 2])
        ax.plot([0, 1, 2], [9, 9, 9], label="_nolegend_")
        self.assertEqual(sorted(set(fd.figure_tables(fig)["data"]["series"])), ["line 1", "line 2", "line 3", "line 4"])

    def test_reference_lines_are_not_data(self):
        fig, (ax,) = new_fig()
        ax.plot([0, 1, 2, 3], [5, 6, 7, 8], label="signal")
        ax.axvline(0, color="red", linestyle="--")
        ax.axhline(2.5)
        self.assertEqual(set(fd.figure_tables(fig)["data"]["series"]), {"signal"})

    def test_hidden_and_animated_artists_are_left_out(self):
        fig, (ax,) = new_fig()
        ax.plot([0, 1], [1, 2], label="shown")
        ln, = ax.plot([0, 1, 2], [3, 4, 5], label="hidden")
        ln.set_visible(False)
        ax.plot([0, 1, 2], [3, 4, 5], label="hover tracker", animated=True)
        self.assertEqual(set(fd.figure_tables(fig)["data"]["series"]), {"shown"})

    def test_a_line_keeps_nan_gaps(self):
        fig, (ax,) = new_fig()
        ax.plot([0, 1, 2, 3], [1.0, np.nan, 3.0, 4.0])
        t = fd.figure_tables(fig)["data"]
        self.assertEqual(len(t), 4)
        self.assertTrue(np.isnan(t["y"].iloc[1]))

    def test_two_point_lines_that_are_real_data_are_kept(self):
        fig, (ax,) = new_fig()
        ax.plot([0, 1], [0, 5], label="a slope between two points")
        self.assertEqual(len(fd.figure_tables(fig)["data"]), 2)


class TestBands(unittest.TestCase):
    def test_a_fill_between_band_comes_back_as_its_two_boundaries_exactly(self):
        fig, (ax,) = new_fig()
        x = np.linspace(0, 5, 40)
        mean = np.sin(x)
        sem = 0.1 + 0.05 * np.cos(x) ** 2
        ax.plot(x, mean, label="Mean")
        ax.fill_between(x, mean - sem, mean + sem, label="SEM")
        t = fd.figure_tables(fig)["data"]
        band = t[t["kind"] == "band"]
        self.assertEqual(len(band), 40)
        self.assertEqual(set(band["series"]), {"SEM"})
        assert_array_equal(band["x"].to_numpy(), x)
        assert_array_equal(band["y_lower"].to_numpy(), mean - sem)
        assert_array_equal(band["y_upper"].to_numpy(), mean + sem)
        self.assertTrue(band["y"].isna().all())

    def test_a_band_in_pieces_gives_each_piece(self):
        fig, (ax,) = new_fig()
        x = np.arange(10.0)
        ax.fill_between(x, np.sin(x) - 1, np.sin(x) + 1, where=(x < 3) | (x > 6), label="regions")
        band = fd.figure_tables(fig)["data"]
        self.assertGreater(len(band), 0)
        self.assertEqual(set(band["kind"]), {"band"})

    def test_shading_a_trace_down_to_zero_is_not_a_second_series(self):
        fig, (ax,) = new_fig()
        x = np.linspace(0, 4, 30)
        y = np.sin(x * 2)
        ax.plot(x, y, label="Mean")
        ax.fill_between(x, y, 0, where=(y >= 0), color="green", alpha=0.25)
        ax.fill_between(x, y, 0, where=(y <= 0), color="red", alpha=0.25)
        ax.fill_between(x, y, 1.5)                                                      # to any constant
        t = fd.figure_tables(fig)["data"]
        self.assertEqual(set(t["kind"]), {"line"})
        self.assertEqual(len(t), 30)


class TestBarsPointsErrorbars(unittest.TestCase):
    def test_bars_are_centre_height_bottom_and_top(self):
        fig, (ax,) = new_fig()
        ax.bar([0, 1, 2], [3.0, 4.5, 2.0], width=0.5, label="AUC")
        t = fd.figure_tables(fig)["data"]
        self.assertEqual(set(t["kind"]), {"bar"})
        assert_array_equal(t["x"].to_numpy(), [0, 1, 2])
        assert_array_equal(t["y"].to_numpy(), [3.0, 4.5, 2.0])
        assert_array_equal(t["y_lower"].to_numpy(), [0, 0, 0])
        assert_array_equal(t["y_upper"].to_numpy(), [3.0, 4.5, 2.0])

    def test_scatter_points(self):
        fig, (ax,) = new_fig()
        ax.scatter([1.0, 2.0, 3.0], [4.0, 5.0, 6.0], label="subjects")
        t = fd.figure_tables(fig)["data"]
        self.assertEqual(set(t["kind"]), {"points"})
        assert_array_equal(t["x"].to_numpy(), [1, 2, 3])
        assert_array_equal(t["y"].to_numpy(), [4, 5, 6])

    def test_errorbars_give_the_point_and_the_ends_of_its_bar_not_a_second_line(self):
        fig, (ax,) = new_fig()
        ax.errorbar([0.0, 1.0, 2.0], [3.0, 4.0, 5.0], yerr=[0.5, 0.25, 1.0], capsize=3, label="mean ± SEM")
        t = fd.figure_tables(fig)["data"]
        self.assertEqual(set(t["kind"]), {"errorbar"})
        self.assertEqual(len(t), 3)
        assert_array_equal(t["y"].to_numpy(), [3, 4, 5])
        assert_array_equal(t["y_lower"].to_numpy(), [2.5, 3.75, 4.0])
        assert_array_equal(t["y_upper"].to_numpy(), [3.5, 4.25, 6.0])

    def test_errorbars_with_no_marker_line_still_give_their_bars(self):
        fig, (ax,) = new_fig()
        ax.errorbar([0.0, 1.0], [3.0, 4.0], yerr=[0.5, 1.0], fmt="none", label="sem")
        t = fd.figure_tables(fig)["data"]
        self.assertEqual(len(t), 2)
        assert_array_equal(t["x"].to_numpy(), [0, 1])
        self.assertTrue(t["y"].isna().all())
        assert_array_equal(t["y_lower"].to_numpy(), [2.5, 3.0])
        assert_array_equal(t["y_upper"].to_numpy(), [3.5, 5.0])

    def test_horizontal_only_errorbars_are_not_taken_for_y_errors(self):
        fig, (ax,) = new_fig()
        ax.errorbar([0.0, 1.0], [3.0, 4.0], xerr=[0.5, 0.5], label="x only")
        t = fd.figure_tables(fig)["data"]
        self.assertTrue(t["y_lower"].isna().all() and t["y_upper"].isna().all())
        assert_array_equal(t["y"].to_numpy(), [3, 4])

    def test_a_grouped_bar_chart_with_error_bars_and_dots_like_the_measures_figure(self):
        fig, (ax,) = new_fig()
        ax.bar([0, 1], [2.0, 3.0], width=0.55)
        ax.errorbar([0, 1], [2.0, 3.0], yerr=[0.3, 0.4], capsize=4)
        ax.scatter([0.05, -0.05, 1.02], [1.8, 2.2, 3.1])
        t = fd.figure_tables(fig)["data"]
        self.assertEqual(sorted(t["kind"].unique()), ["bar", "errorbar", "points"])
        self.assertEqual(t["kind"].value_counts().to_dict(), {"points": 3, "bar": 2, "errorbar": 2})


class TestCategoriesAndExtras(unittest.TestCase):
    def grouped(self):
        fig, (ax,) = new_fig()
        ax.bar([0, 1], [2.0, 3.0], width=0.55)
        ax.errorbar([0, 1], [2.0, 3.0], yerr=[0.3, 0.4], fmt="none")
        ax.scatter([0.1, -0.1, 1.05, 0.5], [1.8, 2.2, 3.1, 9.0])
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["big", "small"])
        return fig

    def test_bars_and_error_bars_on_a_categorical_axis_carry_their_group_names(self):
        t = fd.figure_tables(self.grouped())["data"]
        for kind in ("bar", "errorbar"):
            self.assertEqual(list(t[t["kind"] == kind]["x_tick"]), ["big", "small"], kind)

    def test_a_jittered_dot_belongs_to_the_category_it_sits_beside_and_a_stray_one_to_none(self):
        t = fd.figure_tables(self.grouped())["data"]
        self.assertEqual(list(t[t["kind"] == "points"]["x_tick"]), ["big", "big", "small", ""])

    def test_a_numeric_axis_has_no_category_names(self):
        fig, (ax,) = new_fig()
        ax.plot([0, 1, 2], [3, 4, 5])
        ax.set_xticks([0, 1, 2])
        self.assertEqual(set(fd.figure_tables(fig)["data"]["x_tick"]), {""})

    def test_a_band_is_named_for_the_line_it_surrounds_so_a_renamed_line_renames_it(self):
        fig, (ax,) = new_fig()
        x = np.linspace(0, 1, 10)
        ax.plot(x, x, color="#1f77b4", label="big  (n=6)")
        ax.fill_between(x, x - 0.1, x + 0.1, color="#1f77b4", alpha=0.25, linewidth=0)
        ax.plot(x, -x, color="#d62728", label="small")
        ax.fill_between(x, -x - 0.1, -x + 0.1, color="#d62728", alpha=0.25, linewidth=0)
        t = fd.figure_tables(fig)["data"]
        self.assertEqual(sorted(t["series"].unique()), ["big  (n=6)", "big  (n=6) band", "small", "small band"])

    def test_a_band_with_no_line_of_its_colour_gets_a_numbered_name(self):
        fig, (ax,) = new_fig()
        x = np.linspace(0, 1, 10)
        ax.fill_between(x, x - 0.1, x + 0.1, color="#123456", alpha=0.25)
        self.assertEqual(set(fd.figure_tables(fig)["data"]["series"]), {"band 1"})

    def test_decoration_is_not_data(self):
        fig, (ax,) = new_fig()
        ax.plot([0, 1, 2], [3, 4, 5], label="signal")
        bracket, = ax.plot([0, 0, 1, 1], [6, 6.5, 6.5, 6])
        bracket.pyat_skip = True
        self.assertEqual(set(fd.figure_tables(fig)["data"]["series"]), {"signal"})

    def test_a_figure_can_report_what_its_artists_do_not_say_like_a_box_plots_statistics(self):
        fig, (ax,) = new_fig()
        parts = ax.boxplot([[1.0, 2.0, 3.0, 4.0, 5.0]], positions=[0], showfliers=False)
        for artists in parts.values():
            for artist in artists:
                artist.pyat_skip = True
        ax.pyat_series = [{"series": "big", "kind": "box", "x": 0.0, "y": 3.0, "y_lower": 2.0, "y_upper": 4.0}]
        ax.set_xticks([0])
        ax.set_xticklabels(["big"])
        t = fd.figure_tables(fig)["data"]
        self.assertEqual(len(t), 1)
        row = t.iloc[0]
        self.assertEqual((row["series"], row["kind"], row["x_tick"], row["y"], row["y_lower"], row["y_upper"]),
                         ("big", "box", "big", 3.0, 2.0, 4.0))

    def test_a_flat_two_point_line_in_data_coordinates_is_data_not_a_reference_line(self):
        fig, (ax,) = new_fig()
        ax.plot([0, 5], [2, 2], label="flat")
        self.assertEqual(len(fd.figure_tables(fig)["data"]), 2)

    def test_a_line_drawn_in_axes_coordinates_is_not_data(self):
        fig, (ax,) = new_fig()
        ax.plot([0, 1], [0.9, 0.9], transform=ax.transAxes)
        ax.plot([0, 1], [1, 2], label="data")
        self.assertEqual(set(fd.figure_tables(fig)["data"]["series"]), {"data"})


class TestImages(unittest.TestCase):
    def test_a_heatmap_is_a_grid_with_its_row_and_column_positions(self):
        fig, (ax,) = new_fig()
        z = np.arange(12.0).reshape(3, 4)
        ax.imshow(z, extent=[-2.0, 2.0, 3.5, 0.5], aspect="auto")                   # rows centred on 1, 2, 3; columns on -1.5 .. 1.5
        tables = fd.figure_tables(fig)
        self.assertEqual(list(tables), ["image_1"])
        t = tables["image_1"]
        self.assertEqual(list(t.columns), ["panel", "row_position", "-1.5", "-0.5", "0.5", "1.5"])
        assert_array_equal(t["row_position"].to_numpy(), [1.0, 2.0, 3.0])
        assert_array_equal(t[["-1.5", "-0.5", "0.5", "1.5"]].to_numpy(), z)
        self.assertNotIn("data", tables)

    def test_a_figure_can_label_its_rows_and_they_come_out_in_display_order(self):
        fig, (ax,) = new_fig()
        ax.imshow(np.eye(3), extent=[0, 3, 3.5, 0.5], aspect="auto")
        ax.pyat_row_labels = [7, 2, 5]                                               # e.g. trials, sorted by peak
        t = fd.figure_tables(fig)["image_1"]
        self.assertEqual(list(t["row"]), [7, 2, 5])
        self.assertEqual(list(t.columns)[:3], ["panel", "row", "row_position"])

    def test_labels_of_the_wrong_length_are_ignored(self):
        fig, (ax,) = new_fig()
        ax.imshow(np.eye(3), extent=[0, 3, 3.5, 0.5], aspect="auto")
        ax.pyat_row_labels = [1, 2]
        self.assertNotIn("row", fd.figure_tables(fig)["image_1"].columns)

    def test_a_heatmap_with_a_trace_beneath_it_gives_both(self):
        fig, (heat, line) = new_fig(2, 1)
        heat.imshow(np.ones((2, 5)), extent=[0, 5, 2.5, 0.5], aspect="auto")
        line.plot(np.arange(5.0), np.arange(5.0) ** 2, label="Mean")
        tables = fd.figure_tables(fig)
        self.assertEqual(sorted(tables), ["data", "image_1"])
        self.assertEqual(set(tables["data"]["panel"]), {"panel 2"})

    def test_a_colorbar_is_not_mistaken_for_data(self):
        fig, (ax,) = new_fig()
        im = ax.imshow(np.arange(6.0).reshape(2, 3), aspect="auto")
        fig.colorbar(im, ax=ax)
        self.assertEqual(sorted(fd.figure_tables(fig)), ["image_1"])


class TestPanels(unittest.TestCase):
    def test_each_axes_is_a_panel_named_by_its_title_or_its_number(self):
        fig, (a, b) = new_fig(2, 1)
        a.plot([0, 1], [0, 1], label="x")
        a.set_title("Left channel")
        b.plot([0, 1], [1, 0], label="x")
        t = fd.figure_tables(fig)["data"]
        self.assertEqual(sorted(set(t["panel"])), ["Left channel", "panel 2"])

    def test_a_figure_that_plots_nothing_has_no_tables_and_writes_no_files(self):
        fig, _ = new_fig()
        self.assertEqual(fd.figure_tables(fig), {})
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(fd.write_figure_data(fig, os.path.join(d, "x")), [])
            self.assertEqual(os.listdir(d), [])

    def test_the_same_figure_gives_the_same_tables_twice(self):
        fig, (ax,) = new_fig()
        ax.plot([0, 1, 2], [3, 4, 5], label="a")
        pd.testing.assert_frame_equal(fd.figure_tables(fig)["data"], fd.figure_tables(fig)["data"])


class TestWriting(unittest.TestCase):
    def test_files_are_named_after_the_base_and_hold_full_precision(self):
        fig, (heat, line) = new_fig(2, 1)
        heat.imshow(np.full((2, 3), 1 / 3), extent=[0, 3, 2.5, 0.5], aspect="auto")
        line.plot([0.0, 1.0], [1 / 3, 2 / 3], label="Mean")
        with tempfile.TemporaryDirectory() as d:
            paths = fd.write_figure_data(fig, os.path.join(d, "Event PETH"))
            self.assertEqual(sorted(os.path.basename(p) for p in paths), ["Event PETH_data.csv", "Event PETH_image_1.csv"])
            back = pd.read_csv(os.path.join(d, "Event PETH_data.csv"))
            self.assertEqual(back["y"].iloc[0], 1 / 3)                                  # not rounded to 6 digits
            self.assertEqual(list(back.columns), fd.DATA_COLUMNS)

    def test_non_ascii_labels_survive(self):
        fig, (ax,) = new_fig()
        ax.plot([0, 1], [0, 1], label="L1P¹")
        ax.set_ylabel("ΔF/F (%)")
        with tempfile.TemporaryDirectory() as d:
            (path,) = fd.write_figure_data(fig, os.path.join(d, "f"))
            back = pd.read_csv(path, encoding="utf-8")
        self.assertEqual(set(back["series"]), {"L1P¹"})
        self.assertEqual(set(back["y_label"]), {"ΔF/F (%)"})


if __name__ == "__main__":
    unittest.main()
