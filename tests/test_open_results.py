"""Open Results…: a finished analysis looked at again from the files it left. The analysis engine reads them back (results.open) and the window draws
them: a group analysis in its results window, anything else as a figure of its tables. Nothing is recomputed."""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PyQt6.QtWidgets import QMenu, QPushButton

import PyATCLI as pl

from physicsanalysis_qt import figures
from physicsanalysis_qt.analysis import open_results
from physicsanalysis_qt.analysis.group import run as gui_run
from physicsanalysis_qt.context import get_export_dir
from physicsanalysis_qt.ui import toolbar

from tests.test_group_pipeline import GroupCase, spec


class OpenCase(GroupCase):
    """A group analysis that has been run (its folder holds the settings, tables, report and notes), and the windows Open Results… would show."""

    def setUp(self):
        super().setUp()
        self.tmp = self._tmp.name
        gui_run.start_group_run(self.ctx, spec(), self.out)
        (self.ran, _), = self.shown
        self.shown.clear()
        self.figure_windows, self.errors_opening = [], []

        class FigureWindow:
            def __init__(inner, parent, ctx, fig, name, directory):
                self.figure_windows.append((fig, name, directory))

            def exec(inner):
                return 1

        for target, replacement in (("physicsanalysis_qt.analysis.figure_window.ResultsFigureDialog", FigureWindow),
                                    ("physicsanalysis_qt.analysis.open_results.show_error", lambda ctx, msg, *a, **k: self.errors_opening.append(msg))):
            p = mock.patch(target, replacement)
            p.start()
            self.addCleanup(p.stop)

    def settings_file(self):
        return os.path.join(self.out, pl.GROUP_SETTINGS_FILENAME)


class TestAGroupAnalysisOpensAsItWas(OpenCase):
    def test_its_folder_opens_in_the_group_results_window_with_the_same_report(self):
        open_results.open_results(self.ctx, self.settings_file())
        self.assertEqual(self.errors_opening, [])
        (opened, folder), = self.shown
        self.assertEqual(os.path.abspath(folder), os.path.abspath(self.out))
        self.assertEqual(opened.spec.to_dict(), spec().to_dict())
        self.assertEqual(pl.group_report_text(opened), pl.group_report_text(self.ran))              # the notes and the software came back too
        np.testing.assert_allclose(opened.pairwise["difference"].to_numpy(), self.ran.pairwise["difference"].to_numpy(), rtol=0, atol=0)
        self.assertEqual(self.figure_windows, [])

    def test_the_folder_itself_does_too(self):
        open_results.open_results(self.ctx, self.out)
        self.assertEqual(len(self.shown), 1)

    def test_the_figures_are_drawn_from_what_was_read_back(self):
        open_results.open_results(self.ctx, self.settings_file())
        (opened, _), = self.shown
        self.assertLessEqual({"traces", "measures", "diagnostics", "heatmap_big"}, set(figures.build_all_figures(opened)))


class TestATableOrARecordOpensAsItsFigure(OpenCase):
    def write_window_table(self):
        t = np.linspace(-5, 5, 101)
        path = os.path.join(self.tmp, "ZScore_window.csv")
        pd.DataFrame({"Channel": "465", "time_from_center_s": t, "z_score": np.sin(t)}).to_csv(path, index=False)
        return path

    def test_a_table_is_drawn_as_the_window_drew_it(self):
        path = self.write_window_table()
        open_results.open_results(self.ctx, path)
        self.assertEqual(self.errors_opening, [])
        (fig, name, directory), = self.figure_windows
        self.assertEqual((name, directory), ("ZScore_window.csv", os.path.dirname(path)))
        self.assertEqual(len(fig.axes), 2)                                                            # a heatmap strip over the trace
        self.assertEqual(self.shown, [])

    def test_tables_nothing_can_be_drawn_from_say_so(self):
        path = os.path.join(self.tmp, "other.csv")
        pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_csv(path, index=False)
        open_results.open_results(self.ctx, path)
        self.assertEqual(self.figure_windows, [])
        self.assertEqual(len(self.errors_opening), 1)
        self.assertIn("other.csv", self.errors_opening[0])


class TestAskingForTheFile(OpenCase):
    def test_the_picker_starts_in_the_output_folder_and_what_it_returns_is_opened(self):
        self.ctx.settings["output_folder"] = self.out
        with mock.patch.object(open_results.QFileDialog, "getOpenFileName", return_value=(self.settings_file(), "")) as picker:
            open_results.open_results(self.ctx)
        self.assertEqual(picker.call_args.args[2], get_export_dir(self.ctx))
        self.assertEqual(len(self.shown), 1)

    def test_cancelling_opens_nothing_and_asks_the_engine_nothing(self):
        with mock.patch.object(open_results.QFileDialog, "getOpenFileName", return_value=("", "")), \
                mock.patch.object(open_results, "run_engine") as asked:
            open_results.open_results(self.ctx)
        asked.assert_not_called()
        self.assertEqual((self.shown, self.figure_windows, self.errors_opening), ([], [], []))

    def test_a_file_that_is_not_there_is_an_error_not_a_window(self):
        open_results.open_results(self.ctx, os.path.join(self.tmp, "gone.csv"))
        self.assertEqual((self.shown, self.figure_windows), ([], []))
        self.assertEqual(len(self.errors_opening), 1)
        self.assertIn("gone.csv", self.errors_opening[0])

    def test_a_folder_with_nothing_in_it_is_an_error_too(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        open_results.open_results(self.ctx, empty)
        self.assertEqual((self.shown, self.figure_windows), ([], []))
        self.assertEqual(len(self.errors_opening), 1)


class TestTheOpenMenu(OpenCase):
    def test_open_results_is_in_the_open_menu(self):
        bar = toolbar.build_toolbar(self.ctx)
        menu = next(b for b in bar.findChildren(QPushButton) if b.text().startswith("Open")).menu()
        self.assertIsInstance(menu, QMenu)
        self.assertIn("Open Results…", [a.text() for a in menu.actions()])


if __name__ == "__main__":
    unittest.main()
