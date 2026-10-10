"""figures/from_tables.py: the figure for a finished analysis's tables — what Open Results shows — chosen from the table's columns, so the CSVs PyAT
exports draw like the engine's own tables. The pictures are the ones PyAT's windows draw (figures/draw.py, group.py), so these tests look at what the
figures hold; the pixel-for-pixel comparison with the windows is in test_figure_parity.py. (Reading a result back from disk is the library's:
PyATCLI.results.open_results; its tests are the library's.)"""

import os
import tempfile
import unittest
from unittest import mock

import numpy as np
import pandas as pd
from matplotlib.collections import PathCollection
from numpy.testing import assert_allclose, assert_array_equal

import PyATCLI as pl
from PyATCLI import reproduce as R
from PyATCLI.results import open_results

from physicsanalysis_qt import figures

from tests.figure_fixtures import EVENTS, make_cache


def draw_result(result, **options):
    """The figure for an AnalysisResult (as the engine's `run` returns it)."""
    return figures.build_figure(result.tables, result.kind, result.parameters, **options)


def draw_path(source, **options):
    """The figure Open Results shows for a file or folder: the library reads it back, the app draws its tables. A DataFrame or dict of them is drawn as it is."""
    if isinstance(source, pd.DataFrame):
        return figures.build_figure({"table": source}, None, {}, **options)
    if isinstance(source, dict):
        return figures.build_figure(source, None, {}, **options)
    opened = open_results(source)
    return figures.build_figure(opened.tables, opened.kind, opened.parameters, **options)


class FiguresCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pyatcli-figures-")
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.cache = make_cache()
        self.last = None

    def run_kind(self, kind, parameters=None):
        self.last = pl.run_analysis(kind, self.cache, parameters)
        return self.last

    def plot(self, **kwargs):
        """The figure for the result a test made last."""
        return draw_result(self.last, **kwargs)

    @staticmethod
    def lines(ax):
        return [line for line in ax.lines if len(line.get_xdata()) > 1]

    def z_trace(self, fig):
        """The z-score trace a Z-score window figure draws: the first long line on its last axes (the strip above is an image)."""
        return self.lines(fig.axes[-1])[0].get_ydata()

    def assert_is_the_z_trace_of(self, fig, result, **kw):
        assert_allclose(self.z_trace(fig), result.tables["window"]["z_score"].to_numpy(), rtol=0, atol=1e-12, **kw)


class TestEveryAnalysisHasAPicture(FiguresCase):
    def test_zscore_window_is_a_heatmap_strip_over_the_trace(self):
        result = self.run_kind("zscore_window", {"center_s": 200.0, "pre_s": 10, "post_s": 20})
        fig = self.plot()
        strip, ax = fig.axes
        trace = self.lines(ax)[0]
        assert_array_equal(trace.get_ydata(), result.tables["window"]["z_score"].to_numpy())
        assert_array_equal(trace.get_xdata(), result.tables["window"]["time_from_center_s"].to_numpy())
        self.assertEqual((ax.get_xlabel(), ax.get_ylabel()), ("Time from Center (s)", "Z-Score"))
        self.assertEqual(ax.get_xlim(), (-10.0, 20.0))                                   # the window it was asked for
        self.assertEqual(strip.get_ylabel(), "Normalized (dF/F)")                           # the strip is named for the signal
        self.assertEqual(len(strip.images), 1)
        self.assertEqual(fig._suptitle.get_text(), "Z-Score Analysis")

    def test_auc_window_is_the_trace_with_the_area_shaded_green_above_zero_and_red_below(self):
        result = self.run_kind("auc_window", {"center_s": 200.0, "pre_s": 5, "post_s": 10})
        fig = self.plot()
        (ax,) = fig.axes
        self.assertEqual(len(ax.collections), 2)
        assert_array_equal(self.lines(ax)[0].get_ydata(), result.tables["window"]["value"].to_numpy())
        self.assertEqual(ax.get_xlabel(), "Time from Center (s)")
        self.assertEqual(fig._suptitle.get_text(), "AUC")

    def test_fft_window_is_the_spectrum_with_its_top_peaks_named_in_hz_and_bpm(self):
        from PyATCLI.analysis import find_fft_peaks
        result = self.run_kind("fft_window", {"center_s": 200.0, "pre_s": 10, "post_s": 10})
        fig = self.plot()
        (ax,) = fig.axes
        spectrum = self.lines(ax)[0]
        assert_array_equal(spectrum.get_ydata(), result.tables["spectrum"]["power"].to_numpy())
        peaks = find_fft_peaks(spectrum.get_xdata(), spectrum.get_ydata(), n_peaks=3)
        self.assertEqual(len(ax.texts), len(peaks))
        self.assertTrue(all("Hz" in t.get_text() and "bpm" in t.get_text() for t in ax.texts))
        self.assertEqual(fig._suptitle.get_text(), "centre 200.0s  |  -10s/+10s")        # where the window was
        self.assertEqual(ax.get_title(), "Normalized (dF/F)")

    def test_curve_fit_is_the_signal_around_the_fitted_stretch_the_stretch_and_its_fit(self):
        result = self.run_kind("curve_fit", {"t1_s": 200.0, "t2_s": 210.0, "model": "exponential_decay"})
        (ax,) = self.plot().axes
        around, data, fit = self.lines(ax)[:3]
        assert_array_equal(around.get_ydata(), result.tables["context"]["value"].to_numpy())
        assert_array_equal(data.get_ydata(), result.tables["curve"]["value"].to_numpy())
        assert_array_equal(fit.get_ydata(), result.tables["curve"]["fit"].to_numpy())
        self.assertRegex(ax.get_legend().get_texts()[1].get_text(), r"fit  R2=0\.\d{3}")
        self.assertEqual(ax.get_title(), "Curve Fit — Exponential Decay")
        self.assertEqual(len(ax.patches), 1)                                                # the fitted stretch, shaded

    def test_event_peth_is_every_trial_as_a_heatmap_above_the_mean_and_sem(self):
        result = self.run_kind("event_peth", {"event": "L1P¹", "pre_s": 10, "post_s": 20})
        fig = self.plot()
        heat, band = fig.axes[0], fig.axes[1]
        image = heat.images[0]
        trials = result.tables["trials"]
        expected = trials.pivot_table(index="Trial", columns="time_from_event_s", values="z_score", sort=True).to_numpy()
        assert_array_equal(np.asarray(image.get_array()), expected)
        n = expected.shape[0]
        self.assertEqual(n, len(EVENTS))
        self.assertEqual(tuple(image.get_extent()[2:]), (n + 0.5, 0.5))                           # row k is centred on k: trial 1 reads 1
        self.assertEqual([t.get_text() for t in heat.get_yticklabels()], [str(i) for i in range(1, n + 1)])
        self.assertEqual(heat.get_ylabel(), "Trial")
        mean = self.lines(band)[0]
        assert_array_equal(mean.get_ydata(), result.tables["mean_sem"]["mean"].to_numpy())
        self.assertEqual(len(band.collections), 1)                                         # the SEM band
        self.assertEqual(fig._suptitle.get_text(), "Event PETH — L1P¹")

    def test_peak_finder_over_the_whole_recording_is_the_peaks_over_time(self):
        result = self.run_kind("peak_finder", {"scope": "whole", "z_threshold": 3.0})
        (ax,) = self.plot().axes
        self.assertGreater(len(result.tables["peaks"]), 0)
        self.assertEqual(sum(len(line.get_xdata()) for line in ax.lines if line.get_marker() == "o"), len(result.tables["peaks"]))

    def test_peak_finder_near_events_says_how_many_had_a_peak(self):
        self.run_kind("peak_finder", {"scope": "all_same_name", "event": "L1P¹", "pre_s": 2, "post_s": 8})
        (ax,) = self.plot().axes
        self.assertRegex(ax.get_title(), r"\d+ of 5 events had a peak near them")

    def test_peak_finder_scanning_every_event_is_a_hit_rate_per_event(self):
        result = self.run_kind("peak_finder", {"scope": "scan_all", "pre_s": 2, "post_s": 8})
        fig = self.plot()
        bars = [p for ax in fig.axes for p in ax.patches]
        self.assertEqual(len(bars), len(result.tables["scan"]))

    def test_event_intervals_are_the_time_since_the_previous_marker(self):
        self.cache["markers"] = [{"time": t, "label": "L1P", "color": "g", "store": "L1P"} for t in (10.0, 25.0, 31.0)]
        result = self.run_kind("event_intervals")
        (ax,) = self.plot().axes
        self.assertEqual(ax.get_ylabel(), "Time since previous (s)")
        self.assertEqual(len(result.tables["intervals"]), 3)

    def test_process_is_the_processed_traces(self):
        result = self.run_kind("process")
        (ax,) = self.plot().axes
        self.assertEqual(len(ax.lines), len(result.tables["trace"].columns) - 1)

    def test_every_registered_analysis_can_be_plotted(self):
        params = {"zscore_window": {"center_s": 200.0}, "auc_window": {"center_s": 200.0}, "fft_window": {"center_s": 200.0},
                  "curve_fit": {"t1_s": 200.0, "t2_s": 205.0}, "event_peth": {"event": "L1P¹"}, "peak_finder": {}, "process": {}}
        for kind in pl.kinds():
            if kind == "event_intervals":
                self.cache["markers"] = [{"time": 10.0, "label": "x", "color": "g", "store": "x"}]
            with self.subTest(kind=kind):
                result = pl.run_analysis(kind, self.cache, params.get(kind))
                fig = draw_result(result)
                self.assertGreaterEqual(len(fig.axes), 1)


class TestWhichResultIsPlotted(FiguresCase):
    def test_naming_a_result_plots_that_one(self):
        first = self.run_kind("zscore_window", {"center_s": 100.0})
        second = self.run_kind("zscore_window", {"center_s": 200.0})
        self.assertFalse(np.array_equal(first.tables["window"]["z_score"], second.tables["window"]["z_score"]))
        self.assert_is_the_z_trace_of(draw_result(first), first)
        self.assert_is_the_z_trace_of(draw_result(second), second)

    def test_a_title_of_your_own(self):
        self.run_kind("zscore_window", {"center_s": 100.0})
        self.assertEqual(self.plot(title="Figure 2B")._suptitle.get_text(), "Figure 2B")

    def test_a_run_that_wrote_files_is_plotted_from_them(self):
        result = self.run_kind("event_peth", {"event": "L1P¹", "pre_s": 10, "post_s": 20})
        out = os.path.join(self.tmp, "out")
        R.write_result(result, out, "Rec_event_peth")
        fig = draw_path(out)                                                        # the folder, as a later session would be pointed at it
        self.assertEqual(len(fig.axes), 3)
        assert_allclose(fig.axes[1].lines[0].get_ydata(), result.tables["mean_sem"]["mean"].to_numpy(), rtol=0, atol=1e-12)



class TestPointingAtSomething(FiguresCase):
    def written(self, kind="event_peth", parameters=None, stem="Rec_event_peth"):
        result = self.run_kind(kind, parameters or {"event": "L1P¹", "pre_s": 10, "post_s": 20})
        out = os.path.join(self.tmp, "out")
        paths = R.write_result(result, out, stem)
        from PyATCLI import provenance as pv
        record = pv.build_record(kind, result.parameters, outputs=paths)
        record_path = pv.write_record(os.path.join(out, f"{stem}.provenance.json"), record)
        return result, out, paths, record_path

    def test_a_table_file_is_plotted_by_its_columns_whoever_wrote_it(self):
        result, out, paths, _ = self.written("zscore_window", {"center_s": 200.0}, "Rec")
        csv = next(p for p in paths if p.endswith("_window.csv"))
        self.assertEqual(len(draw_path(csv).axes), 2)
        rounded = os.path.join(self.tmp, "pyat_export.csv")                                # PyAT writes fixed decimals
        result.tables["window"].round(4).to_csv(rounded, index=False)
        fig = draw_path(rounded)
        assert_allclose(self.z_trace(fig), result.tables["window"]["z_score"].round(4).to_numpy())

    def test_a_provenance_record_plots_the_tables_it_lists(self):
        _, _, _, record = self.written()
        fig = draw_path(record)
        self.assertEqual(len(fig.axes), 3)
        self.assertEqual(fig._suptitle.get_text(), "Event PETH — L1P¹")

    def test_a_folder_plots_its_newest_record(self):
        older, out, _, _ = self.written("zscore_window", {"center_s": 100.0}, "older")
        newer, _, _, _ = self.written("zscore_window", {"center_s": 150.0}, "newer")
        os.utime(os.path.join(out, "older.provenance.json"), (1, 1))
        self.assert_is_the_z_trace_of(draw_path(out), newer)

    def test_a_dataframe_or_a_dict_of_them(self):
        result = self.run_kind("event_peth", {"event": "L1P¹", "pre_s": 10, "post_s": 20})
        self.assertEqual(len(draw_path(result.tables["mean_sem"]).axes), 1)
        self.assertEqual(len(draw_path({"a": result.tables["mean_sem"], "b": result.tables["trials"]}).axes), 3)

    def test_a_table_it_does_not_know_says_what_it_does(self):
        with self.assertRaisesRegex(figures.NothingToPlot, "not ones PyAT knows.*apples, pears"):
            draw_path(pd.DataFrame({"apples": ["a"], "pears": ["b"]}))

    def test_a_folder_of_tables_with_no_record_plots_its_tables(self):
        result = self.run_kind("zscore_window", {"center_s": 200.0})
        folder = os.path.join(self.tmp, "tables")
        os.makedirs(folder)
        result.tables["window"].to_csv(os.path.join(folder, "window.csv"), index=False)
        self.assert_is_the_z_trace_of(draw_path(folder), result)



class TestEachEventPethViewOnItsOwn(FiguresCase):
    """PyAT exports one table per Event PETH view; each is plotted alone, as it was exported."""

    def setUp(self):
        super().setUp()
        self.result = self.run_kind("event_peth", {"event": "L1P¹", "pre_s": 10, "post_s": 20, "selected_trials": [1, 2, 4, 5]})

    def plot_csv(self, name):
        path = os.path.join(self.tmp, f"{name}.csv")
        self.result.tables[name].to_csv(path, index=False)
        return draw_path(path)

    def test_the_group_trace(self):
        (ax,) = self.plot_csv("zscore").axes
        assert_array_equal(self.lines(ax)[0].get_ydata(), self.result.tables["zscore"]["z_score"].to_numpy())

    def test_the_trial_heatmap(self):
        fig = self.plot_csv("trials")
        n = self.result.tables["trials"]["Trial"].nunique()
        self.assertEqual(fig.axes[0].images[0].get_array().shape[0], n)
        self.assertEqual([t.get_text() for t in fig.axes[0].get_yticklabels()], ["1", "2", "4", "5"])      # the checked trials, by number

    def test_the_per_trial_auc_with_the_unchecked_trials_faded_and_the_group_in_the_title(self):
        (ax,) = self.plot_csv("auc").axes
        self.assertEqual(len(ax.patches), 2 * len(EVENTS))                                                  # a positive and a negative bar per trial
        alphas = sorted({round(p.get_alpha(), 2) for p in ax.patches})
        self.assertEqual(alphas, [0.3, 0.85])
        self.assertIn("Group (checked trials): total", ax.get_title())

    def test_the_per_trial_peaks(self):
        (ax,) = self.plot_csv("peak").axes
        self.assertEqual(len(ax.patches), len(EVENTS))
        self.assertRegex(ax.get_title(), r"Group \(checked trials\): peak .* at \+")

    def test_the_trial_by_bin_means(self):
        fig = self.plot_csv("bins")
        image = fig.axes[0].images[0]
        n_bins = len([c for c in self.result.tables["bins"].columns if c.startswith("Bin ")])
        self.assertEqual(image.get_array().shape, (len(EVENTS) + 1, n_bins))                               # a row per trial and one for the group
        self.assertEqual(fig.axes[0].get_yticklabels()[-1].get_text(), "Group")

    def test_the_whole_result_is_still_just_the_heatmap_and_the_mean(self):
        self.assertEqual(len(self.plot().axes), 3)                                                    # not a panel for every table


class TestGroupAnalysis(FiguresCase):
    def run_group(self, out_dir=None):
        from PyATCLI import analyses as A
        from PyATCLI.analysis.group import run as group_run
        from tests.figure_fixtures import simulated_loader, simulated_spec
        load, _ = simulated_loader()
        runner = lambda spec, out_dir=None, progress=None: group_run.run_group_analysis(spec, out_dir=out_dir, progress=progress, load=load)
        with mock.patch.object(A, "run_group_analysis", side_effect=runner):
            result, raw = A.run_group_from_spec(simulated_spec(), out_dir=out_dir)
        self.last = result
        return result, raw

    def test_the_result_carries_its_mean_traces(self):
        result, raw = self.run_group()
        self.assertIn("mean_traces", result.tables)
        self.assertEqual(list(result.tables["mean_traces"].columns), ["marker", "subject", "n_trials", "time", "value"])

    def test_it_is_the_mean_trace_of_every_marker_with_its_sem(self):
        result, raw = self.run_group()
        fig = self.plot()
        (traces,) = fig.axes
        self.assertEqual(traces.get_title(), "G: mean response")
        self.assertEqual([t.get_text() for t in traces.get_legend().get_texts()][:2], ["big  (n=6)", "small  (n=6)"])
        expected = np.mean([raw.traces[f"S{i}"]["big"]["mean"] for i in range(6)], axis=0)
        assert_allclose(self.lines(traces)[0].get_ydata(), expected, rtol=0, atol=1e-12)
        self.assertEqual(len(traces.collections), 2)                                       # a SEM band per marker

    def test_each_heatmap_has_a_row_per_subject_named_for_it(self):
        _, raw = self.run_group()
        for marker in ("big", "small"):
            ax = self.plot(which=f"heatmap_{marker}").axes[0]
            self.assertEqual(ax.images[0].get_array().shape, (6, len(raw.trace_grid)))
            self.assertEqual([t.get_text() for t in ax.get_yticklabels()], [f"S{i}" for i in range(6)])
            self.assertEqual(ax.get_title(), f"G: {marker}")

    def test_each_measure_is_a_bar_per_marker_with_a_dot_per_subject_and_the_comparison_in_stars(self):
        _, raw = self.run_group()
        fig = self.plot(which="measures")
        self.assertEqual(fig._suptitle.get_text(), "G: measures by marker")
        self.assertEqual(len(fig.axes), 2)
        for ax, title in zip(fig.axes, ("AUC", "Peak amplitude")):
            self.assertEqual(ax.get_title(), title)
            self.assertEqual(len(ax.patches), 2)
            self.assertEqual([len(c.get_offsets()) for c in ax.collections if isinstance(c, PathCollection)], [6, 6])
            self.assertRegex(ax.texts[0].get_text(), r"^(\*+|ns)$")
        sub = raw.subject_means
        bars = fig.axes[0].patches
        self.assertAlmostEqual(bars[0].get_height(), sub[(sub["measure"] == "auc") & (sub["marker"] == "big")]["mean"].mean(), places=10)

    def test_the_diagnostics_are_residuals_and_a_q_q_plot_per_measure(self):
        self.run_group()
        fig = self.plot(which="diagnostics")
        self.assertEqual([ax.get_title() for ax in fig.axes],
                         ["AUC: residuals", "AUC: Q-Q", "Peak amplitude: residuals", "Peak amplitude: Q-Q"])

    def test_a_figure_that_is_not_there_names_the_ones_that_are(self):
        self.run_group()
        with self.assertRaisesRegex(ValueError, "No figure 'heatmap_huge'.*traces, heatmap_big, heatmap_small, measures, diagnostics"):
            self.plot(which="heatmap_huge")

    def test_a_group_written_to_a_folder_is_plotted_from_the_folder(self):
        out = os.path.join(self.tmp, "G")
        self.run_group(out_dir=out)
        self.assertEqual(self.plot().axes[0].get_title(), "G: mean response")
        self.assertEqual(draw_path(out, which="measures").axes[0].get_title(), "AUC")   # or the folder it was written to, named

    def test_a_group_folder_with_its_settings_is_plotted_under_the_group_s_own_name(self):
        from tests.figure_fixtures import simulated_spec
        out = os.path.join(self.tmp, "G")
        self.run_group(out_dir=out)
        self.assertEqual(draw_path(out).axes[0].get_title(), "Group analysis: mean response")     # tables alone: the spec is inferred
        pl.write_group_settings(out, simulated_spec(), [])                                           # what the app and `group --out` leave beside them
        self.assertEqual(draw_path(out).axes[0].get_title(), "G: mean response")



class TestWhatCanBeAskedOfAFigure(FiguresCase):
    def test_an_event_peth_view_changes_the_group_trace(self):
        self.run_kind("event_peth", {"event": "L1P¹", "pre_s": 10, "post_s": 20})
        trials = self.plot(view="trials").axes[1]
        self.assertEqual(len([line for line in trials.lines if len(line.get_xdata()) > 2]), len(EVENTS))     # every trial's own trace
        self.assertEqual(len(self.plot(view="auc").axes[1].collections), 3)                              # the SEM band and the two areas
        self.assertEqual(len(self.plot().axes[1].collections), 1)                                        # zscore, the default

    def test_sorting_by_peak_reorders_the_heatmap_and_keeps_the_trial_numbers(self):
        self.run_kind("event_peth", {"event": "L1P¹", "pre_s": 10, "post_s": 20})
        plain, sorted_ = self.plot(sort="trial").axes[0], self.plot(sort="peak").axes[0]
        self.assertEqual(sorted_.get_ylabel(), "Trial (sorted by peak)")
        self.assertEqual(sorted(t.get_text() for t in sorted_.get_yticklabels()), sorted(t.get_text() for t in plain.get_yticklabels()))
        self.assertFalse(np.array_equal(np.asarray(plain.images[0].get_array()), np.asarray(sorted_.images[0].get_array())))

    def test_a_title_of_your_own_is_part_of_the_event_peth_drawing(self):
        self.run_kind("event_peth", {"event": "L1P¹", "pre_s": 10, "post_s": 20})
        self.assertEqual(self.plot(title="Figure 2B", view="peak").get_suptitle(), "Figure 2B")

    def test_a_view_or_sort_it_does_not_know_is_refused(self):
        self.run_kind("event_peth", {"event": "L1P¹", "pre_s": 10, "post_s": 20})
        with self.assertRaisesRegex(ValueError, "view must be one of zscore, trials, auc, peak, bins, not 'sideways'"):
            self.plot(view="sideways")
        with self.assertRaisesRegex(ValueError, "sort must be .trial. or .peak., not 'up'"):
            self.plot(sort="up")

    def test_view_sort_and_which_are_ignored_by_what_they_do_not_apply_to(self):
        self.run_kind("zscore_window", {"center_s": 200.0})
        plain = self.plot()
        fig = self.plot(view="trials", sort="peak")
        self.assertEqual((len(fig.axes), fig._suptitle.get_text()), (len(plain.axes), "Z-Score Analysis"))

    def test_build_figure_makes_a_figure_from_tables_with_any_factory(self):
        result = self.run_kind("event_peth", {"event": "L1P¹", "pre_s": 10, "post_s": 20})
        made = []
        from matplotlib.figure import Figure

        def factory(**kw):
            made.append(Figure(**kw))
            return made[-1]

        fig = figures.build_figure(result.tables, "event_peth", result.parameters, figure=factory)
        self.assertIs(fig, made[0])
        self.assertEqual(len(fig.axes), 3)




if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
