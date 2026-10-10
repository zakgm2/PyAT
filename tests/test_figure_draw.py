"""figures/draw.py: the figures of the analysis windows (Z-score, AUC, FFT, Curve Fit, Event PETH) drawn from arrays — what
PyAT's windows hold — and rebuilt from a result's tables, which is how plotlatest draws a run or a CSV. Both forms are the
one drawing code, so a figure a script saves is the figure the app shows."""

import io
import os
import tempfile
import unittest

import numpy as np
import pandas as pd
from matplotlib.figure import Figure
from numpy.testing import assert_array_equal

import PyATCLI as pl
from PyATCLI.analysis import compute_peri_event_from_trace
from physicsanalysis_qt.figures import draw

from tests.figure_fixtures import make_cache

FS = 100.0


def png(fig):
    """The figure's picture, as bytes: two figures that are the same drawing give the same bytes."""
    out = io.BytesIO()
    fig.savefig(out, format="png", dpi=100)
    return out.getvalue()


def long_lines(ax, n=2):
    """The lines with more than `n` points: the traces, not the two-point guides (axvline / axhline)."""
    return [line for line in ax.lines if len(line.get_xdata()) > n]


class DrawCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pyat-draw-")
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.cache = make_cache()

    def run_kind(self, kind, parameters=None):
        return pl.run_analysis(kind, self.cache, parameters)

    @staticmethod
    def channel(name, color, seed=0, n=200, lo=-4.0, hi=6.0):
        t = np.linspace(lo, hi, n)
        return {"channel": name, "color": color, "t": t, "z": np.sin(t + seed) * (1 + seed), "y": np.cos(t + seed) * (1 + seed)}


class TestSeveralChannels(DrawCase):
    def test_zscore_window_has_a_strip_and_a_trace_for_each_channel_and_the_time_label_once(self):
        fig = draw.zscore_window_figure([self.channel("A", "#1f77b4"), self.channel("B", "#ff7f0e", seed=1)], 4, 6)
        self.assertEqual(len(fig.axes), 4)
        self.assertEqual([len(ax.images) for ax in fig.axes], [1, 0, 1, 0])
        self.assertEqual([fig.axes[0].get_ylabel(), fig.axes[2].get_ylabel()], ["A", "B"])
        self.assertEqual([ax.get_xlabel() for ax in fig.axes], ["", "", "", "Time from Center (s)"])
        self.assertEqual(tuple(fig.get_size_inches()), (8.0, 9.0))                           # 4.5 inches a channel

    def test_the_trace_axis_is_scaled_to_the_channels_own_spread(self):
        quiet, loud = self.channel("Q", "k"), self.channel("L", "r", seed=1)
        quiet["z"], loud["z"] = quiet["z"] * 0.1, loud["z"] * 10
        fig = draw.zscore_window_figure([quiet, loud], 4, 6)
        lo_q, hi_q = fig.axes[1].get_ylim()
        lo_l, hi_l = fig.axes[3].get_ylim()
        self.assertEqual((lo_q, hi_q), (-hi_q, hi_q))
        self.assertGreater(hi_l, 20 * hi_q)                                                    # not one fixed range for both

    def test_a_sharp_peak_is_not_cut_off_by_the_trace_axis(self):
        spiky = self.channel("S", "k")
        spiky["z"] = np.sin(spiky["t"]) * 0.5
        spiky["z"][len(spiky["z"]) // 2] = 8.0                                                 # one sample, far above the rest
        spiky["z"][5] = -6.5
        fig = draw.zscore_window_figure([spiky], 4, 6)
        lo, hi = fig.axes[1].get_ylim()
        self.assertGreater(hi, 8.0)
        self.assertLess(lo, -6.5)
        self.assertEqual((lo, hi), (-hi, hi))                                                  # still centred on zero

    def test_a_trace_of_nothing_still_gets_an_axis(self):
        flat = self.channel("F", "k")
        flat["z"] = np.zeros_like(flat["t"])
        lo, hi = draw.zscore_window_figure([flat], 4, 6).axes[1].get_ylim()
        self.assertEqual((lo, hi), (-1.0, 1.0))

    def test_auc_window_has_an_axes_for_each_channel(self):
        fig = draw.auc_window_figure([self.channel("A", "#1f77b4"), self.channel("B", "#ff7f0e", seed=1)])
        self.assertEqual(len(fig.axes), 2)
        self.assertEqual([ax.get_ylabel() for ax in fig.axes], ["A", "B"])
        self.assertEqual([ax.get_xlabel() for ax in fig.axes], ["", "Time from Center (s)"])
        self.assertTrue(all(len(ax.collections) == 2 for ax in fig.axes))

    def test_auc_shades_green_where_the_signal_is_above_zero_and_red_where_it_is_below(self):
        fig = draw.auc_window_figure([self.channel("A", "k")])
        green, red = fig.axes[0].collections
        self.assertEqual([tuple(np.round(c.get_facecolor()[0][:3], 2)) for c in (green, red)], [(0.0, 0.5, 0.0), (1.0, 0.0, 0.0)])

    def test_fft_window_names_each_channel_and_runs_to_half_the_sampling_rate(self):
        freqs = np.linspace(0, FS / 2, 500)
        channels = [{"channel": n, "color": c, "freqs": freqs, "power": 1.0 / (1.0 + (freqs - f0) ** 2 * 40)}
                    for n, c, f0 in (("A", "#1f77b4", 1.0), ("B", "#ff7f0e", 3.0))]
        fig = draw.fft_window_figure(channels, FS, center=12.0, pre=5, post=7)
        self.assertEqual([ax.get_title() for ax in fig.axes], ["A", "B"])
        self.assertTrue(all(ax.get_xlim() == (0.05, FS / 2) for ax in fig.axes))
        self.assertEqual([ax.get_xlabel() for ax in fig.axes], ["", "Frequency (Hz)"])
        self.assertEqual(fig._suptitle.get_text(), "centre 12.0s  |  -5s/+7s")
        self.assertIn(f"{freqs[int(np.argmax(channels[0]['power']))]:.2f} Hz", fig.axes[0].texts[0].get_text())     # the biggest peak is named first

    def test_fft_window_without_the_window_it_was_taken_over_has_no_subtitle(self):
        freqs = np.linspace(0, FS / 2, 100)
        fig = draw.fft_window_figure([{"channel": "A", "color": "k", "freqs": freqs, "power": np.ones(100)}], FS)
        self.assertIsNone(fig._suptitle)

    def test_fft_window_of_a_channel_with_no_spectrum_is_an_empty_axes_not_an_error(self):
        fig = draw.fft_window_figure([{"channel": "A", "color": "k", "freqs": np.array([]), "power": np.array([])}], FS)
        self.assertEqual((len(fig.axes), len(fig.axes[0].lines), len(fig.axes[0].texts)), (1, 0, 0))


class TestCurveFit(DrawCase):
    @staticmethod
    def channels(fit=True, label="Signal"):
        x_ctx = np.linspace(0, 30, 301)
        x = x_ctx[100:201]
        y = np.exp(-(x - 10) / 6)
        return [{"label": label, "color": "#1f77b4", "x_ctx": x_ctx, "y_ctx": np.exp(-(x_ctx - 10) / 6), "x": x, "y": y,
                 "fit": y * 1.01 if fit else None, "r2": 0.987 if fit else None}]

    def draw(self, model="Exponential Decay (a*e^(-bx) + c)", **kw):
        fig = draw.new_curve_fit_figure()
        ax = draw.draw_curve_fit(fig, kw.pop("channels", self.channels()), model_name=model, t1=10.0, t2=20.0,
                                 view_start=0.0, view_end=30.0, **kw)
        return fig, ax

    def test_it_draws_the_signal_around_the_stretch_the_stretch_its_fit_and_the_stretch_shaded(self):
        fig, ax = self.draw()
        self.assertEqual([len(line.get_xdata()) for line in ax.lines], [301, 101, 101, 2, 2])
        self.assertEqual(len(ax.patches), 1)
        self.assertEqual([t.get_text() for t in ax.get_legend().get_texts()], ["Signal", "Signal fit  R2=0.987"])
        self.assertEqual(ax.get_title(), "Curve Fit — Exponential Decay")                     # the model's formula is not in the title
        self.assertEqual(ax.get_xlim(), (0.0, 30.0))
        self.assertEqual((ax.get_xlabel(), ax.get_ylabel()), ("Time (s)", "Signal"))
        self.assertIs(fig.axes[0], ax)

    def test_axis_labels_are_the_recordings_own(self):
        _, ax = self.draw(x_label="Time from start", y_label="Delta Concentration (uM)")
        self.assertEqual((ax.get_xlabel(), ax.get_ylabel()), ("Time from start (s)", "Delta Concentration (uM)"))

    def test_a_fit_that_failed_is_drawn_without_its_curve_and_says_nothing_of_r_squared(self):
        _, ax = self.draw(channels=self.channels(fit=False))
        self.assertEqual([len(line.get_xdata()) for line in ax.lines], [301, 101, 2, 2])
        self.assertEqual([t.get_text() for t in ax.get_legend().get_texts()], ["Signal"])

    def test_a_linear_fit_marks_the_two_ends_of_the_stretch(self):
        _, ax = self.draw(model="Linear (y = mx + b)")
        ends = [line for line in ax.lines if line.get_marker() == "o"]
        self.assertEqual(len(ends), 1)
        assert_array_equal(ends[0].get_xdata(), [10.0, 20.0])
        _, other = self.draw()
        self.assertEqual([line for line in other.lines if line.get_marker() == "o"], [])

    def test_drawing_again_replaces_what_was_there(self):
        fig, _ = self.draw()
        draw.draw_curve_fit(fig, self.channels(label="Other"), model_name="Linear (y = mx + b)", t1=10.0, t2=20.0, view_start=0.0, view_end=30.0)
        self.assertEqual(len(fig.axes), 1)
        self.assertEqual(fig.axes[0].get_title(), "Curve Fit — Linear")
        self.assertEqual(fig.axes[0].get_legend().get_texts()[0].get_text(), "Other")

    def test_a_redraw_is_the_same_picture_as_a_first_draw_whatever_the_figure_showed_before(self):
        fresh, _ = self.draw(model="Linear (y = mx + b)")
        reused, _ = self.draw()                                                              # something with other tick labels first
        draw.draw_curve_fit(reused, self.channels(), model_name="Linear (y = mx + b)", t1=10.0, t2=20.0, view_start=0.0, view_end=30.0)
        self.assertEqual(png(reused), png(fresh))

    def test_from_tables_is_the_figure_the_windows_numbers_make(self):
        result = self.run_kind("curve_fit", {"t1_s": 200.0, "t2_s": 210.0, "model": "exponential_decay"})
        fig = draw.curve_fit_from_tables(result.tables, result.parameters)
        ax = fig.axes[0]
        self.assertEqual(ax.get_ylabel(), "Amplitude")
        self.assertEqual(ax.get_xlim(), (190.0, 220.0))                                      # the stretch and the signal either side of it
        self.assertEqual(draw.curve_fit_from_tables({"x": pd.DataFrame({"a": [1]})}, {}), None)

    def test_from_tables_without_the_signal_around_it_draws_just_the_stretch(self):
        result = self.run_kind("curve_fit", {"t1_s": 200.0, "t2_s": 210.0, "model": "exponential_decay"})
        tables = {k: v for k, v in result.tables.items() if k != "context"}
        ax = draw.curve_fit_from_tables(tables, result.parameters).axes[0]
        self.assertEqual([len(line.get_xdata()) for line in ax.lines], [1001, 1001, 1001, 2, 2])

    def test_from_tables_of_a_fit_that_failed_has_no_fit_curve(self):
        result = self.run_kind("curve_fit", {"t1_s": 200.0, "t2_s": 210.0, "model": "exponential_decay"})
        tables = dict(result.tables)
        tables["curve"] = tables["curve"].assign(fit=np.nan)
        ax = draw.curve_fit_from_tables(tables, result.parameters).axes[0]
        self.assertEqual(len(long_lines(ax)), 2)
        self.assertEqual(len(ax.get_legend().get_texts()), 1)


class TestEventPeth(DrawCase):
    PRE, POST = 5.0, 8.0

    def setUp(self):
        super().setUp()
        self.t = np.linspace(-self.PRE, self.POST, 131)
        rows = [a * np.exp(-((self.t - c) ** 2) / 2) for a, c in ((1.0, 1.0), (3.0, 2.0), (2.0, 0.5), (0.5, 3.0))]
        self.matrix = np.array(rows)
        self.numbers = [1, 2, 4, 5]                                                          # trial 3 unchecked

    def draw(self, **kw):
        fig = draw.new_event_peth_figure()
        axes = draw.draw_event_peth(fig, time_axis=self.t, trial_matrix=kw.pop("matrix", self.matrix), trial_numbers=kw.pop("numbers", self.numbers),
                                    pre=self.PRE, post=self.POST, bin_s=2.0, event_name="L1P", **kw)
        return fig, axes

    def test_the_heatmap_is_labelled_with_the_trials_own_numbers(self):
        fig, (heat, line) = self.draw()
        self.assertEqual([t.get_text() for t in heat.get_yticklabels()], ["1", "2", "4", "5"])
        self.assertEqual(heat.get_ylabel(), "Trial")
        self.assertEqual(fig._suptitle.get_text(), "Event PETH — L1P")
        self.assertEqual(len(fig.axes), 3)                                                   # the heatmap, the trace and the colour bar
        self.assertEqual((heat.pyat_panel, line.pyat_panel), ("Trials heatmap", "Group trace"))
        self.assertEqual(heat.pyat_row_labels, [1, 2, 4, 5])

    def test_sorted_by_peak_the_rows_move_and_keep_their_own_numbers(self):
        fig, (heat, _) = self.draw(sort_by_peak=True)
        self.assertEqual([t.get_text() for t in heat.get_yticklabels()], ["2", "4", "1", "5"])   # biggest response first
        self.assertEqual(heat.get_ylabel(), "Trial (sorted by peak)")
        assert_array_equal(np.asarray(heat.images[0].get_array())[0], self.matrix[1])

    def test_at_most_about_ten_rows_are_labelled(self):
        matrix = np.vstack([self.matrix] * 7)[:25]
        fig, (heat, _) = self.draw(matrix=matrix, numbers=list(range(1, 26)))
        labels = [t.get_text() for t in heat.get_yticklabels()]
        self.assertEqual(labels, [str(n) for n in range(1, 26, 3)])
        self.assertLessEqual(len(labels), 10)

    def test_the_trace_is_the_mean_of_the_checked_trials_with_its_sem(self):
        _, (_, line) = self.draw()
        assert_array_equal(long_lines(line)[0].get_ydata(), self.matrix.mean(axis=0))
        self.assertEqual(len(line.collections), 1)
        self.assertEqual([t.get_text() for t in line.get_legend().get_texts()], ["Mean", "SEM"])
        self.assertEqual(line.get_ylabel(), "Z-Score (Normalized)")
        self.assertEqual(line.get_xlim(), (-self.PRE, self.POST))

    def test_the_trials_view_draws_every_trial_in_its_own_colour_and_has_no_legend(self):
        _, (_, line) = self.draw(view="trials")
        traces = long_lines(line)
        self.assertEqual(len(traces), 4)
        self.assertEqual([t.get_label() for t in traces], ["Trial 1", "Trial 2", "Trial 4", "Trial 5"])
        self.assertEqual(len({t.get_color() for t in traces}), 4)
        self.assertIsNone(line.get_legend())
        self.assertEqual(len(line.collections), 0)                                           # no mean +/- SEM here

    def test_the_auc_view_shades_the_mean_green_and_red(self):
        _, (_, line) = self.draw(view="auc")
        self.assertEqual(len(line.collections), 3)                                           # the SEM band and the two areas

    def test_the_peak_view_marks_the_means_peak(self):
        _, (_, line) = self.draw(view="peak")
        mean = self.matrix.mean(axis=0)
        peak = compute_peri_event_from_trace(self.t, mean, self.POST, 2.0)
        marked = line.collections[-1].get_offsets()[0]
        self.assertEqual((float(marked[0]), float(marked[1])), (peak["latency"], peak["peak_amplitude"]))
        self.assertIn("Peak", [t.get_text() for t in line.get_legend().get_texts()])

    def test_the_bins_view_marks_where_each_bin_starts(self):
        _, (_, line) = self.draw(view="bins")
        starts = [b["bin_start"] for b in compute_peri_event_from_trace(self.t, self.matrix.mean(axis=0), self.POST, 2.0)["mean_bins"]]
        marks = [l for l in line.lines if l.get_linewidth() == 0.5]
        self.assertEqual(sorted(float(m.get_xdata()[0]) for m in marks), sorted(starts))
        self.assertGreater(len(starts), 1)

    def test_no_trials_checked_says_so_and_still_draws_the_empty_trace(self):
        fig, (heat, line) = self.draw(matrix=np.zeros((0, len(self.t))), numbers=[])
        self.assertEqual([t.get_text() for t in heat.texts], ["No trials selected"])
        self.assertEqual(len(heat.images), 0)
        self.assertEqual(len(fig.axes), 2)                                                   # no colour bar without a heatmap
        self.assertIsNone(heat.pyat_row_labels)

    def test_a_title_of_its_own_replaces_the_default(self):
        fig, _ = self.draw(title="Figure 3C")
        self.assertEqual(fig._suptitle.get_text(), "Figure 3C")

    def test_a_redraw_is_the_same_picture_as_a_first_draw_whatever_the_figure_showed_before(self):
        fresh, _ = self.draw(view="auc", sort_by_peak=True)
        reused, _ = self.draw(view="trials")
        draw.draw_event_peth(reused, time_axis=self.t, trial_matrix=self.matrix, trial_numbers=self.numbers, pre=self.PRE, post=self.POST,
                             bin_s=2.0, view="auc", sort_by_peak=True, event_name="L1P")
        self.assertEqual(png(reused), png(fresh))

    def test_the_figure_can_be_made_by_any_factory(self):
        made = []
        draw.event_peth_from_tables(self.run_kind("event_peth", {"event": "L1P¹", "pre_s": 5, "post_s": 8}).tables, {"event": "L1P¹"},
                                    figure=lambda **kw: made.append(Figure(**kw)) or made[-1])
        self.assertEqual(len(made), 1)
        self.assertEqual(len(made[0].axes), 3)

    def test_from_tables_reads_the_trials_numbers_and_the_window_back(self):
        result = self.run_kind("event_peth", {"event": "L1P¹", "pre_s": 10, "post_s": 20, "selected_trials": [1, 2, 4, 5]})
        fig = draw.event_peth_from_tables(result.tables, result.parameters)
        heat = fig.axes[0]
        self.assertEqual([t.get_text() for t in heat.get_yticklabels()], ["1", "2", "4", "5"])
        self.assertEqual(heat.get_xlim(), (-10.0, 20.0))
        self.assertEqual(fig._suptitle.get_text(), "Event PETH — L1P¹")

    def test_from_tables_ignores_a_table_that_has_a_channel_column(self):
        trials = pd.DataFrame({"Channel": ["a"], "Trial": [1], "time_from_event_s": [0.0], "z_score": [1.0]})
        self.assertIsNone(draw.event_peth_from_tables({"t": trials}, {}))


class TestTablesAreTheSameAsTheirCsvs(DrawCase):
    """What was written to a file and read back draws the same picture as the result in memory — so plotting a CSV is
    plotting the run."""

    def through_csv(self, result):
        out = {}
        for name, table in result.tables.items():
            path = os.path.join(self.tmp, f"{name}.csv")
            table.to_csv(path, index=False)
            out[name] = pd.read_csv(path, encoding="utf-8-sig", float_precision="round_trip")
        return out

    def test_every_analysis_window(self):
        cases = (("zscore_window", {"center_s": 200.0, "pre_s": 10, "post_s": 20}, draw.zscore_window_from_tables),
                 ("auc_window", {"center_s": 200.0, "pre_s": 5, "post_s": 10}, draw.auc_window_from_tables),
                 ("fft_window", {"center_s": 200.0, "pre_s": 10, "post_s": 10}, draw.fft_window_from_tables),
                 ("curve_fit", {"t1_s": 200.0, "t2_s": 210.0, "model": "exponential_decay"}, draw.curve_fit_from_tables),
                 ("event_peth", {"event": "L1P¹", "pre_s": 10, "post_s": 20}, draw.event_peth_from_tables))
        for kind, params, build in cases:
            with self.subTest(kind=kind):
                result = self.run_kind(kind, params)
                self.assertEqual(png(build(result.tables, result.parameters)), png(build(self.through_csv(result), result.parameters)))

    def test_a_table_belonging_to_another_analysis_is_not_drawn_by_these(self):
        foreign = {"t": pd.DataFrame({"apples": [1.0], "pears": [2.0]})}
        for build in (draw.zscore_window_from_tables, draw.auc_window_from_tables, draw.fft_window_from_tables,
                      draw.curve_fit_from_tables, draw.event_peth_from_tables):
            self.assertIsNone(build(foreign, {}), build.__name__)

    def test_the_window_comes_from_the_parameters_or_else_from_how_far_the_data_reaches(self):
        result = self.run_kind("zscore_window", {"center_s": 200.0, "pre_s": 10, "post_s": 20})
        asked = draw.zscore_window_from_tables(result.tables, result.parameters).axes[-1].get_xlim()
        t = result.tables["window"]["time_from_center_s"]
        reached = draw.zscore_window_from_tables(result.tables, {}).axes[-1].get_xlim()
        self.assertEqual(asked, (-10.0, 20.0))
        self.assertEqual(reached, (float(t.min()), float(t.max())))

    def test_the_fft_axis_runs_to_half_the_sampling_rate_given_or_the_top_of_the_spectrum(self):
        result = self.run_kind("fft_window", {"center_s": 200.0, "pre_s": 10, "post_s": 10})
        top = float(result.tables["spectrum"]["frequency_hz"].max())
        self.assertEqual(draw.fft_window_from_tables(result.tables, {}).axes[0].get_xlim(), (0.05, top))
        self.assertEqual(draw.fft_window_from_tables(result.tables, {"fs": 10.0}).axes[0].get_xlim(), (0.05, 5.0))


if __name__ == "__main__":
    unittest.main()
