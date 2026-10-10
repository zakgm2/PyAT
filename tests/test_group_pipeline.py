"""The app's side of a group analysis: PyATCLI's run_group_analysis plus the figures the app draws and saves
next to the tables, and the settings file the setup wizard writes (the library's, with the app's name and version)."""

import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtWidgets import QApplication, QWidget

import PyATCLI as pl
from PyATCLI import analyses
from PyATCLI.analysis.group import GroupSpec

from physicsanalysis_qt import __version__, figures
from physicsanalysis_qt.context import AppState
from physicsanalysis_qt.analysis.group import run as gui_run
from physicsanalysis_qt.analysis.group.output import resolve_group_dir


def simulated_loader(n_sub=6, seed=0):
    """Stand-in recordings: 'big' events respond twice as strongly as 'small' ones."""
    rng = np.random.default_rng(seed)
    data = {}
    amp = {"big": 2.0, "small": 1.0}
    for s in range(n_sub):
        gain = rng.lognormal(0, 0.3)
        events = {m: [round(float(e), 2) for e in np.sort(rng.uniform(30, 270, 12))] for m in amp}
        x = np.arange(30_000) / 100.0
        y = 0.02 + 0.005 * rng.standard_normal(len(x))
        for m, times in events.items():
            for e in times:
                d = x - e
                y = y + np.where(d >= 0, gain * amp[m] * np.exp(-np.clip(d, 0, None) / 1.5), 0.0)
        data[f"f{s}"] = {"x": x, "y": y, "fs": 100.0, "groups": events, "n_splices": 0, "warnings": []}

    def load(folder, regression_method, store_labels, progress):
        return dict(data[folder])

    return load


def spec(n_sub=6):
    return GroupSpec(group_name="G", subjects=[{"subject": f"S{i}", "folder": f"f{i}"} for i in range(n_sub)],
                     markers=["big", "small"], metrics=["auc", "peak"], smooth_seconds=0.5)


class GroupCase(unittest.TestCase):
    """A group analysis the way the app runs it: asked of the analysis engine (here on a thread of the test process, which lets the stand-in
    recordings reach it), the answer read back into results."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.out = os.path.join(self._tmp.name, "G")
        real = analyses.run_group_analysis
        patcher = mock.patch.object(analyses, "run_group_analysis",
                                    lambda spec, out_dir=None, progress=None, **k: real(spec, out_dir=out_dir, progress=progress, load=simulated_loader(), **k))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ctx = AppState(self.app)
        self.ctx.settings["background_loading"] = False                    # the engine's answer is waited for right there
        self.ctx.win = QWidget()                                           # the progress toast hangs off the main window
        self.addCleanup(self.ctx.win.deleteLater)
        self.addCleanup(lambda: self.ctx.engine.shutdown())
        self.toasts, self.errors, self.shown = [], [], []
        for name, sink in (("show_window_toast", self.toasts), ("show_error", self.errors)):
            p = mock.patch.object(gui_run, name, lambda ctx, msg, *a, _sink=sink, **k: _sink.append(msg))
            p.start()
            self.addCleanup(p.stop)

        class Dialog:
            def __init__(inner, parent, ctx, results, group_dir):
                self.shown.append((results, group_dir))
                inner.figures = figures.build_all_figures(results)          # what the real dialog does: it draws them once, the run saves them

            def exec(inner):
                return 1

        p = mock.patch("physicsanalysis_qt.analysis.group.results_dialog.GroupResultsDialog", Dialog)
        p.start()
        self.addCleanup(p.stop)


class TestStartGroupRun(GroupCase):
    def test_the_results_dialog_gets_the_analysis_with_its_tables_report_and_figures(self):
        gui_run.start_group_run(self.ctx, spec(), self.out)
        self.assertEqual(self.errors, [])
        (results, group_dir), = self.shown
        self.assertEqual(group_dir, self.out)
        self.assertEqual(results.spec.group_name, "G")
        original = pl.run_group_analysis(spec(), load=simulated_loader())
        self.assertEqual(pl.group_report_text(results), pl.group_report_text(original))
        np.testing.assert_allclose(results.pairwise["difference"].to_numpy(), original.pairwise["difference"].to_numpy())
        names = {os.path.basename(p) for p in results.files}
        self.assertIn("analysis_report.txt", names)
        for stem in ("figure_traces", "figure_measures", "figure_diagnostics", "figure_heatmap_big", "figure_heatmap_small"):
            for ext in ("png", "pdf"):
                self.assertIn(f"{stem}.{ext}", names, f"{stem}.{ext}")
        self.assertTrue(all(os.path.isfile(p) for p in results.files))
        self.assertTrue(any("Group analysis finished" in t for t in self.toasts))

    def test_the_figures_the_dialog_draws_come_from_the_rebuilt_results(self):
        from physicsanalysis_qt.figures import build_all_figures
        gui_run.start_group_run(self.ctx, spec(), self.out)
        (results, _), = self.shown
        figures = build_all_figures(results)
        self.assertEqual({"traces", "measures", "diagnostics"} <= set(figures), True)

    def test_the_run_saves_the_wizards_settings_with_the_scans_it_was_set_up_from(self):
        scans = [{"folder": f"f{i}", "block_name": f"B{i}", "start_time": "2025-01-01T10:00:00", "groups": {"big": [1.0, 2.0]},
                  "n_splices": 0, "n_saved_markers": 0} for i in range(6)]
        gui_run.start_group_run(self.ctx, spec(), self.out, scans=scans)
        path = os.path.join(self.out, pl.GROUP_SETTINGS_FILENAME)
        self.assertTrue(os.path.isfile(path))
        saved, doc = pl.read_group_settings(path)
        self.assertEqual(saved.to_dict(), spec().to_dict())
        self.assertEqual(doc["app"]["name"], "PyAT")
        self.assertEqual(len(doc["recordings"]), 6)

    def test_a_run_that_fails_still_leaves_the_settings(self):
        with mock.patch.object(analyses, "run_group_analysis", side_effect=RuntimeError("could not load S0")):
            gui_run.start_group_run(self.ctx, spec(), self.out, scans=[])
        self.assertTrue(os.path.isfile(os.path.join(self.out, pl.GROUP_SETTINGS_FILENAME)))

    def test_a_failure_says_so_and_where_the_settings_are(self):
        bad = spec()
        bad.markers = ["nope"]
        with mock.patch.object(analyses, "run_group_analysis", side_effect=RuntimeError("could not load S0")):
            gui_run.start_group_run(self.ctx, bad, self.out)
        self.assertEqual(self.shown, [])
        self.assertEqual(len(self.errors), 1)
        self.assertIn("could not be completed", self.errors[0])
        self.assertIn("could not load S0", self.errors[0])
        self.assertIn(os.path.join(self.out, "analysis_settings.json"), self.errors[0])


class TestScanningTheRecordings(GroupCase):
    def test_the_wizard_opens_on_what_the_engine_found(self):
        from physicsanalysis_qt.analysis.group import setup_dialog
        from tests.recordings import make_tdt_folder, patch_tdt_reader
        patcher = patch_tdt_reader()
        self.addCleanup(patcher.stop)
        folders = [make_tdt_folder(self._tmp.name, f"Rat{i}-250101-10101{i}") for i in range(2)]
        opened = []

        class Wizard:
            def __init__(inner, parent, ctx, scans, base_path, store_labels):
                opened.append((scans, base_path, store_labels))

            def exec(inner):
                return 0

        with mock.patch.object(setup_dialog, "GroupSetupDialog", Wizard), mock.patch.object(setup_dialog, "show_error", lambda ctx, m: self.errors.append(m)):
            setup_dialog.launch_group_analysis(self.ctx, folders, self._tmp.name)
        self.assertEqual(self.errors, [])
        (scans, base, labels), = opened
        self.assertEqual(base, self._tmp.name)
        self.assertEqual([s["name"] for s in scans], ["Rat0-250101-101010", "Rat1-250101-101011"])
        self.assertIn("L1P¹", scans[0]["groups"])
        self.assertTrue(all(s["error"] is None for s in scans))

    def test_none_readable_is_an_error_not_a_wizard(self):
        from physicsanalysis_qt.analysis.group import setup_dialog
        os.makedirs(os.path.join(self._tmp.name, "Rat0-250101-101010"))                    # not a tank
        opened = []
        with mock.patch.object(setup_dialog, "GroupSetupDialog", lambda *a, **k: opened.append(a)), \
                mock.patch.object(setup_dialog, "show_error", lambda ctx, m: self.errors.append(m)):
            setup_dialog.launch_group_analysis(self.ctx, [os.path.join(self._tmp.name, "Rat0-250101-101010")], self._tmp.name)
        self.assertEqual(opened, [])
        self.assertIn("None of the recordings could be read", self.errors[0])


class TestSettingsFileWrittenByTheApp(unittest.TestCase):
    def test_it_names_the_app_and_its_version_beside_the_librarys(self):
        with tempfile.TemporaryDirectory() as d:
            path = pl.write_group_settings(os.path.join(d, "G"), spec(2), [], app={"name": "PyAT", "version": __version__})
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        self.assertEqual(doc["app"], {"name": "PyAT", "version": __version__, "library_version": pl.__version__})

    def test_a_group_name_already_run_gets_a_numbered_folder(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = type("Ctx", (), {"settings": {"output_folder": d}})()
            first = resolve_group_dir(ctx, None, "My group")
            self.assertEqual(first, os.path.join(d, "Group Analysis", "My group"))
            pl.write_group_settings(first, spec(2), [])
            self.assertEqual(resolve_group_dir(ctx, None, "My group"), os.path.join(d, "Group Analysis", "My group (2)"))


if __name__ == "__main__":
    unittest.main()
