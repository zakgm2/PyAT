"""figures/group.py: the figures of a group analysis — mean traces, a heatmap per marker, the measures, the model diagnostics — drawn from the
results in memory or from the results rebuilt from a run's tables (api.group.results_from_tables), so a group analysis run in another session is
drawn with the code the window draws it with."""

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd
from matplotlib.collections import PathCollection

from PyATCLI import analyses as A
from PyATCLI.analysis.group import run as group_run
from PyATCLI.analysis.group.rebuild import results_from_tables

from physicsanalysis_qt import figures
from physicsanalysis_qt.figures import group as G

from tests.figure_fixtures import simulated_loader, simulated_spec


def png(fig):
    out = io.BytesIO()
    fig.savefig(out, format="png", dpi=100)
    return out.getvalue()


class GroupCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pyat-groupfig-")
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        load, _ = simulated_loader()
        runner = lambda spec, out_dir=None, progress=None: group_run.run_group_analysis(spec, out_dir=out_dir, progress=progress, load=load)
        with mock.patch.object(A, "run_group_analysis", side_effect=runner):
            self.result, self.raw = A.run_group_from_spec(simulated_spec())
        self.tables, self.parameters = self.result.tables, self.result.parameters


class TestTheFigures(GroupCase):
    def test_the_figures_there_are(self):
        results = results_from_tables(self.tables, self.parameters)
        self.assertEqual(G.group_figure_names(results), ["traces", "heatmap_big", "heatmap_small", "measures", "diagnostics"])
        self.assertEqual(list(G.build_all_figures(results)), ["traces", "heatmap_big", "heatmap_small", "measures", "diagnostics"])

    def test_a_figure_rebuilt_from_the_tables_is_the_one_built_from_the_results_in_memory(self):
        every = G.build_all_figures(self.raw)                                                # what the app draws, from the run itself
        for name in G.group_figure_names(self.raw):
            with self.subTest(name=name):
                self.assertEqual(png(G.figure_from_tables(self.tables, self.parameters, which=name)), png(every[name]))

    def test_the_default_is_the_mean_traces(self):
        self.assertEqual(png(G.figure_from_tables(self.tables, self.parameters)), png(G.figure_from_tables(self.tables, self.parameters, which="traces")))

    def test_an_unknown_figure_names_the_known_ones(self):
        with self.assertRaisesRegex(ValueError, "No figure 'bars'.*traces, heatmap_big, heatmap_small, measures, diagnostics"):
            G.figure_from_tables(self.tables, self.parameters, which="bars")
        with self.assertRaisesRegex(ValueError, "No figure 'heatmap_nobody'"):
            G.figure_from_tables(self.tables, self.parameters, which="heatmap_nobody")

    def test_with_no_model_fitted_there_are_no_diagnostics(self):
        tables = {k: v for k, v in self.tables.items() if k not in ("models", "diagnostics")}
        results = results_from_tables(tables, self.parameters)
        self.assertNotIn("diagnostics", G.group_figure_names(results))
        self.assertIsNone(G.build_diagnostics_figure(results))
        with self.assertRaisesRegex(figures.NothingToPlot, "no model diagnostics"):
            G.figure_from_tables(tables, self.parameters, which="diagnostics")

    def test_a_marker_nobody_has_data_for_has_no_heatmap(self):
        traces = self.tables["mean_traces"]
        tables = {**self.tables, "mean_traces": traces[traces["marker"] != "small"]}
        names = G.group_figure_names(results_from_tables(tables, self.parameters))
        self.assertIn("heatmap_big", names)
        self.assertNotIn("heatmap_small", names)

    def test_with_no_traces_the_trace_figure_says_so(self):
        tables = {k: v for k, v in self.tables.items() if k != "mean_traces"}
        fig = G.figure_from_tables(tables, self.parameters)
        self.assertEqual([t.get_text() for t in fig.axes[0].texts], ["No trials to trace."])

    def test_the_title_is_set_the_way_each_figure_holds_it(self):
        results = results_from_tables(self.tables, self.parameters)
        traces, measures = G.build_trace_figure(results), G.build_measures_figure(results)
        self.assertEqual(G.figure_title_text(traces), "G: mean response")                    # an axes' title
        self.assertEqual(G.figure_title_text(measures), "G: measures by marker")             # a figure's
        G.set_figure_title_text(traces, "Figure 4")
        G.set_figure_title_text(measures, "Figure 5")
        self.assertEqual((traces.axes[0].get_title(), measures._suptitle.get_text()), ("Figure 4", "Figure 5"))


class TestTheMeasures(GroupCase):
    def results(self):
        return results_from_tables(self.tables, self.parameters)

    def test_one_measure_alone_fills_the_figure(self):
        fig = G.build_measures_figure(self.results(), measure="peak")
        self.assertEqual([ax.get_title() for ax in fig.axes], ["Peak amplitude"])

    def test_the_subject_dots_can_be_left_out(self):
        fig = G.build_measures_figure(self.results(), G.MeasuresDisplayOptions(show_samples=False))
        for ax in fig.axes:
            self.assertEqual([c for c in ax.collections if isinstance(c, PathCollection)], [])
        self.assertEqual(len(fig.axes[0].patches), 2)

    def test_markers_given_the_same_label_share_one_bar_and_no_comparison(self):
        options = G.MeasuresDisplayOptions(marker_labels={"big": "Both", "small": "Both"})
        fig = G.build_measures_figure(self.results(), options)
        for ax in fig.axes:
            self.assertEqual(len(ax.patches), 1)
            self.assertEqual([t.get_text() for t in ax.get_xticklabels()], ["Both"])
            self.assertEqual(len(ax.texts), 0)                                               # the model never saw this grouping: no p-value

    def test_a_marker_can_be_given_a_name_of_its_own(self):
        fig = G.build_measures_figure(self.results(), G.MeasuresDisplayOptions(marker_labels={"big": "Large"}))
        self.assertEqual([t.get_text() for t in fig.axes[0].get_xticklabels()], ["Large", "small"])

    def test_the_bars_are_drawn_in_grey_shades_the_dots_in_colour(self):
        fig = G.build_measures_figure(self.results())
        faces = [tuple(np.round(p.get_facecolor()[:3], 2)) for p in fig.axes[0].patches]
        self.assertTrue(all(r == g == b for r, g, b in faces), faces)


class TestSavingTheFigures(GroupCase):
    def test_each_figure_is_saved_as_png_and_pdf_with_the_data_behind_it(self):
        results = results_from_tables(self.tables, self.parameters)
        figs = {"traces": G.build_trace_figure(results), "measures": G.build_measures_figure(results)}
        out = os.path.join(self.tmp, "figs")
        paths = G.save_figures(figs, out, software="Test 1.0")
        names = sorted(os.path.basename(p) for p in paths)
        self.assertEqual(names, ["figure_measures.pdf", "figure_measures.png", "figure_measures_data.csv",
                                 "figure_traces.pdf", "figure_traces.png", "figure_traces_data.csv"])
        self.assertEqual(Path(out, "figure_traces.pdf").read_bytes()[:5], b"%PDF-")
        self.assertEqual(Path(out, "figure_traces.png").read_bytes()[:8], bytes([137, 80, 78, 71, 13, 10, 26, 10]))
        self.assertIn(b"Test 1.0", Path(out, "figure_traces.png").read_bytes())                  # whose figure it is, in the file
        data = pd.read_csv(Path(out, "figure_traces_data.csv"))
        self.assertGreater(len(data), 0)


class TestEveryFigureComesWithItsData(GroupCase):
    def test_the_files_next_to_a_group_runs_figures_say_what_was_drawn(self):
        results = results_from_tables(self.tables, self.parameters)
        built = G.build_all_figures(results)
        out = os.path.join(self.tmp, "figs")
        files = G.save_figures(built, out, software="Test 1.0")
        names = {os.path.basename(p) for p in files}
        for expected in ("figure_traces_data.csv", "figure_measures_data.csv", "figure_diagnostics_data.csv",
                         "figure_heatmap_big_image_1.csv", "figure_heatmap_small_image_1.csv"):
            self.assertIn(expected, names)
        read = lambda name: pd.read_csv(os.path.join(out, name))
        traces = read("figure_traces_data.csv")
        self.assertEqual(sorted(traces["kind"].unique()), ["band", "line"])
        self.assertEqual(sorted(traces["series"].unique()), ["big  (n=6)", "big  (n=6) band", "small  (n=6)", "small  (n=6) band"])
        heat = read("figure_heatmap_big_image_1.csv")
        self.assertEqual(list(heat["row"]), [f"S{i}" for i in range(6)])                   # a row per subject, by name
        measures = read("figure_measures_data.csv")
        self.assertEqual(sorted(measures[measures["kind"] == "bar"]["x_tick"].unique()), ["big", "small"])
        pdf = Path(out, "figure_traces.pdf").read_bytes()
        self.assertIn(b"FontFile2", pdf)                                                   # the fonts are embedded as TrueType (editable), not Type 3
        self.assertNotIn(b"/Type3", pdf)
        for fig in built.values():
            fig.clf()


class TestFromTablesThatAreNotAGroup(GroupCase):
    def test_tables_that_are_not_a_group_analysis_are_no_figure(self):
        self.assertIsNone(G.figure_from_tables({"x": pd.DataFrame({"a": [1]})}))

    def test_tables_keyed_by_the_csv_they_were_written_to_draw_the_same_figure(self):
        from PyATCLI.analysis.group.report import CSV_NAMES
        by_file = {os.path.splitext(CSV_NAMES.get(name, name))[0]: table for name, table in self.tables.items()}
        self.assertEqual(png(G.figure_from_tables(by_file, self.parameters, which="measures")),
                         png(G.figure_from_tables(self.tables, self.parameters, which="measures")))


if __name__ == "__main__":
    unittest.main()
