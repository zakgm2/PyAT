"""A CSV exported from an analysis window is a plain table: Open Results draws it as the window did, by its columns alone (the library reads it back
with open_results; the figure is figures.build_figure's). Nothing is remembered as "the latest result": the library keeps no such thing."""

import os
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from numpy.testing import assert_allclose
from PyQt6.QtWidgets import QDialog, QPushButton

from PyATCLI.results import open_results

from physicsanalysis_qt import figures

from physicsanalysis_qt.export import figure_export
from physicsanalysis_qt.analysis import event_peth, peth, result_window

from tests.test_gui_reproduces import GuiCase

QUIET_TOAST = types.SimpleNamespace(update=lambda *a: None, finish=lambda *a: None)


class ExportingCase(GuiCase):
    def setUp(self):
        super().setUp()
        self.out = os.path.join(self.tmp, "Out")
        self.ctx.settings["output_folder"] = self.out
        self.folder_out = os.path.join(self.out, "TDT", "Rat7-250101-101010 (Analysis)")
        saved = mock.patch.object(figure_export._context, "save_settings")
        saved.start()
        self.addCleanup(saved.stop)

    def click(self, dialog, text):
        buttons = [b for b in dialog.findChildren(QPushButton) if b.text() == text]
        self.assertEqual(len(buttons), 1, f"{text!r} buttons: {len(buttons)}")
        with mock.patch("physicsanalysis_qt.app.toasts.show_window_toast"):
            buttons[0].click()

    def csvs(self):
        return sorted(f for f in os.listdir(self.folder_out) if f.endswith(".csv")) if os.path.isdir(self.folder_out) else []

    def open_dialog(self, launch, *args):
        """The real analysis dialog, with its real Export buttons, captured instead of blocking."""
        shown = []

        def exec_(dialog):
            shown.append(dialog)
            return 0
        with mock.patch.object(QDialog, "exec", new=exec_), mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=QUIET_TOAST), \
                mock.patch.object(event_peth, "show_window_toast", mock.Mock()), mock.patch.object(result_window, "show_window_toast", mock.Mock()):
            launch(*args)
        return shown[0]


def draw_csv(path):
    """The figure Open Results shows for a file: the library reads it back, the app draws its tables."""
    opened = open_results(path)
    return figures.build_figure(opened.tables, opened.kind, opened.parameters)


class TestAnExportedCsvIsDrawnLikeTheWindow(ExportingCase):
    def test_a_z_score_window_exported_is_what_open_results_draws_from_its_path(self):
        dialog = self.open_dialog(peth.launch_zscore_peth, self.ctx, 20.0)
        self.click(dialog, "Export CSV")
        (name,) = self.csvs()
        path = os.path.join(self.folder_out, name)
        fig = draw_csv(path)
        strip, ax = fig.axes                                          # the window's own figure: a heatmap strip over the trace
        exported = pd.read_csv(path)
        assert_allclose(ax.lines[0].get_ydata(), exported["z_score"].to_numpy(), rtol=0, atol=1e-9)
        self.assertEqual(fig._suptitle.get_text(), "Z-Score Analysis")

    def test_each_event_peth_view_exported_on_its_own_can_be_drawn(self):
        dialog = self.open_dialog(event_peth.launch_event_peth, self.ctx)
        dialog.e_pre.setText("3")
        dialog.e_post.setText("6")
        dialog.e_bin.setText("2")
        with mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=QUIET_TOAST),                 mock.patch.object(event_peth, "show_window_toast", mock.Mock()):
            dialog._run(dialog.event_name)
        expected_axes = {"zscore": 1, "trials": 3, "auc": 1, "peak": 1, "bins": 2}      # the trials table is the window's whole figure: heatmap, colour bar, trace
        for view, n_axes in expected_axes.items():
            with self.subTest(view=view):
                before = set(self.csvs())
                dialog._view_buttons[view].setChecked(True)
                self.click(dialog, "Export CSV")
                (new,) = set(self.csvs()) - before
                fig = draw_csv(os.path.join(self.folder_out, new))
                self.assertEqual(len(fig.axes), n_axes)                                          # (a bare table does not say which event it was)


if __name__ == "__main__":
    unittest.main()
