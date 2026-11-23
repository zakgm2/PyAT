"""Recording Overview (analysis/overview.py): the whole recording's traces one above another, with the Z-score of the whole recording. The window shows
what the library's `recording_overview` gives, Export CSV writes every sample of it with a record that replays it, and Open Results draws the file
again as the window drew it."""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from numpy.testing import assert_allclose
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QShortcut
from PyQt6.QtWidgets import QDialog, QMenu, QPushButton, QSizePolicy

from PyATCLI import provenance as pv
from PyATCLI import reproduce as R

from physicsanalysis_qt import figures
from physicsanalysis_qt.analysis import custom_statistics, overview

from tests.test_draw_exported_csv import ExportingCase, QUIET_TOAST, draw_csv
from tests.test_gui_reproduces import GuiCase, TOL

PANELS = ["Control", "Signal", "Control Fit", "Z-Score", "ΔF/F"]


def overview_table(n=20_000, seed=0):
    rng = np.random.default_rng(seed)
    t = np.arange(n) / 100.0
    return pd.DataFrame({"time_s": t, "Control": 5 + 0.1 * rng.standard_normal(n), "Signal": 10 + 0.3 * rng.standard_normal(n),
                         "Control Fit": 10 + 0.05 * rng.standard_normal(n), "Z-Score": rng.standard_normal(n), "ΔF/F": 0.03 * rng.standard_normal(n)})


class TestTheFigure(unittest.TestCase):
    def test_only_a_table_with_a_zscore_column_is_an_overview(self):
        table = overview_table(100)
        self.assertEqual([name for name, _ in figures.overview_panels(table)], PANELS)
        self.assertIsNone(figures.overview_panels(table.drop(columns="time_s")))
        chosen = table[["time_s", "Signal", "Control"]]                                            # a choice of the panels, in any order, with no Z-Score among them
        self.assertEqual([name for name, _ in figures.overview_panels(chosen)], ["Signal", "Control"])
        self.assertIsNone(figures.overview_panels(table[["time_s", "Signal"]]))                   # one panel is not recognised as an overview's: it is drawn as any table is
        processed = pd.DataFrame({"time_s": [0.0, 1.0], "normalized": [1.0, 2.0], "main_driver": [3.0, 4.0]})
        self.assertIsNone(figures.overview_panels(processed))                                      # (the processed traces' table is drawn in one set of axes)
        other = pd.DataFrame({"time_s": [0.0, 1.0], "Mean O2Hb": [1.0, 2.0], "Z-Score (Mean O2Hb)": [-1.0, 1.0]})
        self.assertEqual([name for name, _ in figures.overview_panels(other)], ["Mean O2Hb", "Z-Score (Mean O2Hb)"])

    def test_each_panel_has_its_own_axes_one_above_another_sharing_the_time_axis(self):
        table = overview_table()
        fig = figures.new_recording_overview_figure()
        axes = figures.draw_recording_overview(fig, time=table["time_s"].to_numpy(), panels=figures.overview_panels(table))
        self.assertEqual(len(axes), 5)
        self.assertEqual([ax.get_title(loc="left") for ax in axes], PANELS)                     # each named in bold above its top-left corner
        self.assertEqual([ax.get_ylabel() for ax in axes], PANELS)
        self.assertEqual(axes[-1].get_xlabel(), "Time (s)")
        self.assertEqual(tuple(axes[0].get_xlim()), (0.0, table["time_s"].iloc[-1]))             # the whole recording
        self.assertTrue(all(axes[0].get_shared_x_axes().joined(axes[0], ax) for ax in axes))
        self.assertEqual(fig._suptitle.get_text(), "Recording Overview")
        tops = [ax.get_position().y1 for ax in axes]
        self.assertEqual(tops, sorted(tops, reverse=True))                                          # in the order of the table, from the top

    def test_the_fit_is_drawn_on_the_signal_it_is_fitted_to(self):
        table = overview_table()
        fig = figures.new_recording_overview_figure()
        axes = figures.draw_recording_overview(fig, time=table["time_s"].to_numpy(), panels=figures.overview_panels(table))
        fit_panel = axes[2]
        self.assertEqual([line.get_label() for line in fit_panel.lines], ["Signal", "Control fit"])
        self.assertEqual(len(axes[0].lines), 1)

    def test_a_long_recording_is_drawn_from_its_peaks_and_dips_not_every_sample(self):
        n = 1_000_000
        y = np.random.default_rng(4).standard_normal(n)
        y[123_456] = 40.0                                                                      # a spike
        y[765_432] = -35.0                                                                     # and a dip
        x = np.arange(n) / 1000.0
        fig = figures.new_recording_overview_figure()
        (ax,) = figures.draw_recording_overview(fig, time=x, panels=[("Z-Score", y)])
        (line,) = ax.lines
        xs, ys = line.get_xdata(), line.get_ydata()
        self.assertLess(len(xs), 6000)
        self.assertEqual((ys.max(), ys.min()), (40.0, -35.0))                                  # neither is lost
        self.assertTrue(np.all(np.diff(xs) > 0))
        self.assertEqual(xs[-1], x[-1])
        short_x, short_y = figures.draw._thin(x[:5000], y[:5000])                            # a short trace is drawn as it is
        self.assertEqual(len(short_x), 5000)

    def test_with_no_panel_ticked_the_figure_says_so(self):
        fig = figures.new_recording_overview_figure()
        (ax,) = figures.draw_recording_overview(fig, time=overview_table(50)["time_s"].to_numpy(), panels=[])
        self.assertEqual([t.get_text() for t in ax.texts], ["Tick at least one panel"])
        self.assertFalse(ax.axison)

    def test_the_title_says_how_the_zscore_was_taken(self):
        self.assertEqual(figures.overview_title({}), "Recording Overview")
        self.assertEqual(figures.overview_title({"signal": "normalized", "method": "standard"}), "Recording Overview — Z-score (standard)")
        self.assertEqual(figures.overview_title({"signal": "main_driver", "method": "robust"}), "Recording Overview — Z-score of main_driver (robust)")

    def test_the_figure_data_names_each_panel(self):
        table = overview_table(200)
        fig = figures.new_recording_overview_figure()
        figures.draw_recording_overview(fig, time=table["time_s"].to_numpy(), panels=figures.overview_panels(table))
        data = figures.figure_tables(fig)["data"]
        self.assertEqual(list(dict.fromkeys(data["panel"])), PANELS)

    def test_open_results_draws_the_same_figure_from_the_tables_and_from_a_csv_of_them(self):
        table = overview_table()
        params = {"signal": "normalized", "method": "robust", "max_points": 0}
        fig = figures.build_figure({"overview": table}, "recording_overview", params)
        self.assertEqual(len(fig.axes), 5)
        self.assertEqual(fig._suptitle.get_text(), "Recording Overview — Z-score (robust)")
        again = figures.build_figure({"anything": table.copy()}, None, {})                       # by its columns alone, as an exported file is
        self.assertEqual(len(again.axes), 5)
        self.assertEqual(again._suptitle.get_text(), "Recording Overview")

    def test_a_retitle_is_honoured(self):
        fig = figures.build_figure({"overview": overview_table(300)}, "recording_overview", {"method": "standard"}, title="Rat 7, session 2")
        self.assertEqual(fig._suptitle.get_text(), "Rat 7, session 2")


class OpenOverview:
    """Opens the real Recording Overview window on the fixture recording (40 s at 1 kHz, both streams)."""

    def open(self):
        self.shown = []
        with mock.patch.object(QDialog, "exec", new=lambda dlg: self.shown.append(dlg) or 0), \
                mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=QUIET_TOAST), \
                mock.patch.object(overview, "show_window_toast", mock.Mock()):
            overview.launch_recording_overview(self.ctx)
        self.dlg = self.shown[0]
        return self.dlg


class TestTheWindow(OpenOverview, GuiCase):
    def test_it_opens_on_the_whole_recording_with_a_panel_for_each_trace(self):
        dlg = self.open()
        self.assertEqual(dlg.windowTitle(), "Recording Overview — Rat7-250101-101010")
        self.assertEqual([ax.get_title(loc="left") for ax in dlg.fig.axes], PANELS)
        table = dlg.tables["overview"]
        self.assertEqual(list(table.columns), ["time_s", *PANELS])
        self.assertLessEqual(len(table), overview.DRAW_ROWS + 10)                               # (thinned for drawing: 40,000 samples)
        self.assertEqual(table["time_s"].iloc[0], 0.0)
        self.assertEqual(dlg.params, {"signal": "normalized", "method": "standard", "max_points": overview.DRAW_ROWS})
        self.assertEqual(dlg.summary["n_samples"], 40_000)
        text = dlg.lbl_summary.text()
        self.assertTrue(text.startswith("Z-Score of Normalized (dF/F) (standard): mean "))
        self.assertIn("40,000 samples over 40.0 s", text)
        self.assertEqual(dlg.fig._suptitle.get_text(), "Recording Overview — Z-score (standard)")

    def test_the_zscore_is_over_the_whole_recording(self):
        dlg = self.open()
        dff = self.ctx.cache["signals"]["normalized"]["y"]
        z = dlg.tables["overview"]["Z-Score"].to_numpy()
        self.assertEqual(float(z.max()), float((dff.max() - dff.mean()) / dff.std()))           # every sample counts, though not every sample is a row
        self.assertAlmostEqual(dlg.summary["zscore_mean"], float(dff.mean()), places=9)

    def test_picking_the_signal_or_the_method_and_updating_z_scores_again_in_place(self):
        dlg = self.open()
        before = dlg.tables["overview"]["Z-Score"].to_numpy().copy()
        dlg.method_combo.setCurrentIndex(dlg.method_combo.findData("robust"))
        dlg.signal_combo.setCurrentIndex(dlg.signal_combo.findData("main_driver"))
        with mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=QUIET_TOAST):
            dlg.btn_update.click()
        self.assertEqual(dlg.params, {"signal": "main_driver", "method": "robust", "max_points": overview.DRAW_ROWS})
        self.assertFalse(np.array_equal(dlg.tables["overview"]["Z-Score"].to_numpy()[: len(before)], before[: len(dlg.tables["overview"])]))
        self.assertTrue(dlg.lbl_summary.text().startswith("Z-Score of Main Driver (x465A) (robust)"))
        self.assertEqual(dlg.fig._suptitle.get_text(), "Recording Overview — Z-score of main_driver (robust)")
        self.assertTrue(dlg.btn_update.isEnabled())
        self.assertEqual(len(dlg.fig.axes), 5)                                                   # redrawn in the same figure

    def test_a_library_without_the_analysis_says_how_to_update_it(self):
        errors = []
        with mock.patch.object(overview, "show_error", lambda ctx, message: errors.append(message)), \
                mock.patch.object(overview, "request_analysis", lambda ctx, kind, params, ok, label=None, on_error=None, **kw: on_error(
                    "Unknown analysis 'recording_overview'; the analyses are: zscore_window")):
            overview.launch_recording_overview(self.ctx)
        self.assertEqual(errors, [overview.NEEDS_NEWER_LIBRARY])

    def test_without_a_recording_it_says_so(self):
        self.ctx.cache = None
        errors = []
        with mock.patch.object(overview, "show_error", lambda ctx, message: errors.append(message)):
            overview.launch_recording_overview(self.ctx)
        self.assertEqual(errors, ["Open a recording first."])

    def test_it_is_a_custom_statistics_tool_for_any_recording(self):
        tool = next(t for t in custom_statistics._CUSTOM_TOOLS if t["launch"] is overview.launch_recording_overview)
        self.assertIsNone(tool["requires_source"])
        self.assertIn("Recording Overview", tool["label"])


class TestChoosingThePanels(OpenOverview, GuiCase):
    """Which panels are shown, and in what order: a list beside the plot (tick, drag, Up and Down), drawn again at once and remembered."""

    def titles(self, dlg):
        return [ax.get_title(loc="left") for ax in dlg.fig.axes]

    def names(self, dlg):
        return [dlg.panel_list.item(i).text() for i in range(dlg.panel_list.count())]

    def tick(self, dlg, name, ticked):
        item = next(dlg.panel_list.item(i) for i in range(dlg.panel_list.count()) if dlg.panel_list.item(i).text() == name)
        item.setCheckState(Qt.CheckState.Checked if ticked else Qt.CheckState.Unchecked)

    def test_it_opens_with_every_panel_ticked_in_the_recordings_order(self):
        dlg = self.open()
        self.assertEqual(self.names(dlg), PANELS)
        self.assertEqual(dlg._selected(), PANELS)
        self.assertIsNone(dlg._panels_param())                                                  # all, in the recording's order: what is asked for by default
        self.assertEqual(dlg._provenance()["parameters"], dlg.params)
        self.assertEqual(self.titles(dlg), PANELS)

    def test_unticking_a_panel_takes_it_out_of_the_plot_at_once_without_asking_the_engine(self):
        dlg = self.open()
        with mock.patch.object(overview, "request_analysis") as asked:
            self.tick(dlg, "Control", False)
            self.tick(dlg, "Control Fit", False)
        asked.assert_not_called()
        self.assertEqual(self.titles(dlg), ["Signal", "Z-Score", "ΔF/F"])
        self.assertEqual(dlg._panels_param(), ["Signal", "Z-Score", "ΔF/F"])
        self.assertEqual(dlg._provenance()["parameters"]["panels"], ["Signal", "Z-Score", "ΔF/F"])
        self.assertEqual(len(dlg.fig.axes), 3)

    def test_two_panels_is_enough_and_the_figure_is_drawn_from_just_those(self):
        dlg = self.open()
        for name in ("Control", "Control Fit", "ΔF/F"):
            self.tick(dlg, name, False)
        self.assertEqual(self.titles(dlg), ["Signal", "Z-Score"])
        self.assertEqual(dlg.fig.axes[-1].get_xlabel(), "Time (s)")                              # (the time axis is on the last one)
        data = figures.figure_tables(dlg.fig)["data"]
        self.assertEqual(list(dict.fromkeys(data["panel"])), ["Signal", "Z-Score"])

    def test_moving_a_panel_up_and_down_puts_the_panels_in_another_order_and_the_plot_follows(self):
        dlg = self.open()
        dlg.panel_list.setCurrentRow(3)                                                          # Z-Score
        dlg._move(-1)
        dlg._move(-1)
        self.assertEqual(self.names(dlg), ["Control", "Z-Score", "Signal", "Control Fit", "ΔF/F"])
        self.assertEqual(self.titles(dlg), ["Control", "Z-Score", "Signal", "Control Fit", "ΔF/F"])
        self.assertEqual(dlg._panels_param(), ["Control", "Z-Score", "Signal", "Control Fit", "ΔF/F"])
        self.assertEqual(dlg.panel_list.currentRow(), 1)
        dlg._move(1)
        self.assertEqual(self.names(dlg), ["Control", "Signal", "Z-Score", "Control Fit", "ΔF/F"])
        dlg.panel_list.setCurrentRow(0)
        dlg._move(-1)                                                                       # (nowhere to go: nothing happens)
        dlg.panel_list.setCurrentRow(4)
        dlg._move(1)
        self.assertEqual(self.names(dlg), ["Control", "Signal", "Z-Score", "Control Fit", "ΔF/F"])

    def test_dragging_a_panel_in_the_list_reorders_it_too(self):
        dlg = self.open()
        model = dlg.panel_list.model()
        model.moveRow(model.index(0, 0).parent(), 4, model.index(0, 0).parent(), 0)             # what a drop does: the last row to the top
        self.assertEqual(self.names(dlg), ["ΔF/F", "Control", "Signal", "Control Fit", "Z-Score"])
        self.assertEqual(self.titles(dlg), ["ΔF/F", "Control", "Signal", "Control Fit", "Z-Score"])
        self.assertEqual(dlg.panel_list.item(0).checkState(), Qt.CheckState.Checked)             # (it keeps its tick)

    def test_only_the_ticked_ones_are_drawn_in_the_order_of_the_list(self):
        dlg = self.open()
        self.tick(dlg, "Signal", False)
        dlg.panel_list.setCurrentRow(4)                                                          # ΔF/F, to the top
        for _ in range(4):
            dlg._move(-1)
        self.assertEqual(self.titles(dlg), ["ΔF/F", "Control", "Control Fit", "Z-Score"])
        self.assertEqual(dlg._selected(), ["ΔF/F", "Control", "Control Fit", "Z-Score"])

    def test_show_all_ticks_every_panel_again_and_keeps_the_order(self):
        dlg = self.open()
        for name in ("Control", "Signal"):
            self.tick(dlg, name, False)
        dlg._tick_all()
        self.assertEqual(self.titles(dlg), PANELS)

    def test_the_list_is_the_only_control_there_are_no_buttons_for_it(self):
        dlg = self.open()
        side = dlg.panel_list.parentWidget()
        self.assertEqual(side.findChildren(QPushButton), [])                                     # (the window's own buttons are not in the panel column)
        for gone in ("btn_up", "btn_down", "btn_all"):
            self.assertFalse(hasattr(dlg, gone), gone)

    def test_alt_up_and_alt_down_move_the_selected_panel(self):
        dlg = self.open()
        shortcuts = {s.key().toString(): s for s in dlg.panel_list.findChildren(QShortcut)}
        self.assertEqual(sorted(shortcuts), ["Alt+Down", "Alt+Up"])
        dlg.panel_list.setCurrentRow(3)
        shortcuts["Alt+Up"].activated.emit()
        self.assertEqual(self.names(dlg), ["Control", "Signal", "Z-Score", "Control Fit", "ΔF/F"])
        shortcuts["Alt+Down"].activated.emit()
        shortcuts["Alt+Down"].activated.emit()
        self.assertEqual(self.names(dlg), ["Control", "Signal", "Control Fit", "ΔF/F", "Z-Score"])
        self.assertEqual(self.titles(dlg), ["Control", "Signal", "Control Fit", "ΔF/F", "Z-Score"])

    def menu_of(self, dlg, row):
        """The right-click menu on `row` of the list (not run: its actions are what is looked at, and triggered)."""
        seen = []
        point = dlg.panel_list.visualItemRect(dlg.panel_list.item(row)).center()
        with mock.patch.object(QMenu, "exec", new=lambda menu, *a: seen.append(menu)):
            dlg._panel_menu(QPoint(point))
        return {action.text(): action for action in seen[0].actions() if action.text()}

    def test_right_click_offers_move_show_only_and_show_all(self):
        dlg = self.open()
        actions = self.menu_of(dlg, 0)
        self.assertEqual(list(actions), ["Move up", "Move down", "Show only this panel", "Show all panels"])
        self.assertFalse(actions["Move up"].isEnabled())                                         # (the first has nowhere to go up)
        self.assertTrue(actions["Move down"].isEnabled())
        self.assertFalse(self.menu_of(dlg, 4)["Move down"].isEnabled())
        actions = self.menu_of(dlg, 3)                                                           # Z-Score: it becomes the selected one
        self.assertEqual(dlg.panel_list.currentRow(), 3)
        actions["Move up"].trigger()
        self.assertEqual(self.names(dlg), ["Control", "Signal", "Z-Score", "Control Fit", "ΔF/F"])
        self.menu_of(dlg, 4)["Show only this panel"].trigger()
        self.assertEqual(dlg._selected(), ["ΔF/F"])
        self.assertEqual(self.titles(dlg), ["ΔF/F"])
        self.menu_of(dlg, 0)["Show all panels"].trigger()
        self.assertEqual(dlg._selected(), self.names(dlg))
        self.assertEqual(len(dlg.fig.axes), 5)

    def test_a_panel_that_is_not_ticked_is_greyed_and_the_list_is_only_as_tall_as_its_panels(self):
        dlg = self.open()
        self.tick(dlg, "Signal", False)
        ticked, unticked = dlg.panel_list.item(0).foreground().color(), dlg.panel_list.item(1).foreground().color()
        self.assertNotEqual(ticked, unticked)
        self.tick(dlg, "Signal", True)
        self.assertEqual(dlg.panel_list.item(1).foreground().color(), ticked)
        rows = dlg.panel_list.count() * dlg.panel_list.sizeHintForRow(0)
        self.assertEqual(dlg.panel_list.sizePolicy().verticalPolicy(), QSizePolicy.Policy.Maximum)           # never taller than its panels need
        self.assertGreaterEqual(dlg.panel_list.sizeHint().height(), rows)
        self.assertLess(dlg.panel_list.sizeHint().height(), rows + 30)

    def test_nothing_ticked_says_so_and_cannot_be_exported(self):
        self.modules(overview)
        dlg = self.open()
        for name in PANELS:
            self.tick(dlg, name, False)
        self.assertEqual(len(dlg.fig.axes), 1)
        self.assertEqual([t.get_text() for t in dlg.fig.axes[0].texts], ["Tick at least one panel"])
        errors = []
        with mock.patch.object(overview, "show_error", lambda ctx, message: errors.append(message)), mock.patch.object(overview, "request_analysis") as asked:
            dlg.btn_export.click()
            dlg.btn_csv.click()
        self.assertEqual(errors, ["Tick at least one panel to export."] * 2)
        asked.assert_not_called()
        self.assertEqual(self.rec.figures, [])

    def test_the_choice_is_remembered_and_comes_back_in_the_next_window(self):
        dlg = self.open()
        self.tick(dlg, "Control", False)
        dlg.panel_list.setCurrentRow(3)
        for _ in range(3):
            dlg._move(-1)
        self.assertEqual(self.ctx.settings["overview_panels"], ["Z-Score", "Signal", "Control Fit", "ΔF/F"])
        again = self.open()
        self.assertEqual(self.names(again), ["Z-Score", "Signal", "Control Fit", "ΔF/F", "Control"])     # the ticked ones in their order, then the rest
        self.assertEqual(again._selected(), ["Z-Score", "Signal", "Control Fit", "ΔF/F"])
        self.assertEqual(self.titles(again), ["Z-Score", "Signal", "Control Fit", "ΔF/F"])

    def test_a_remembered_choice_that_does_not_fit_the_recording_is_ignored(self):
        for remembered in ("Signal", ["Gone", "Also gone"], [3, None], {"a": 1}):
            with self.subTest(remembered=remembered):
                self.ctx.settings["overview_panels"] = remembered
                dlg = self.open()
                self.assertEqual(dlg._selected(), PANELS)
                self.assertEqual(self.titles(dlg), PANELS)
        self.ctx.settings["overview_panels"] = ["Z-Score", "Gone", "Signal"]                     # names it has are kept, the others skipped
        self.assertEqual(self.open()._selected(), ["Z-Score", "Signal"])

    def test_updating_the_zscore_keeps_the_choice(self):
        dlg = self.open()
        self.tick(dlg, "Control", False)
        dlg.method_combo.setCurrentIndex(dlg.method_combo.findData("robust"))
        with mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=QUIET_TOAST):
            dlg.btn_update.click()
        self.assertEqual(self.titles(dlg), ["Signal", "Control Fit", "Z-Score", "ΔF/F"])
        self.assertEqual(dlg.params["method"], "robust")
        self.assertNotIn("panels", dlg.params)                                                   # (the engine is asked for every panel: the list chooses what is drawn)
        self.assertEqual(dlg._provenance()["parameters"]["panels"], ["Signal", "Control Fit", "Z-Score", "ΔF/F"])

    def test_export_plot_hands_over_the_panels_that_are_shown_as_its_record(self):
        self.modules(overview)
        dlg = self.open()
        self.tick(dlg, "Control", False)
        dlg.btn_export.click()
        record = self.rec.figures[-1]["provenance"]
        self.assertEqual(record["parameters"]["panels"], ["Signal", "Control Fit", "Z-Score", "ΔF/F"])
        self.assertEqual(record["parameters"]["method"], "standard")


class TestWhatIsExported(OpenOverview, GuiCase):
    def test_export_plot_hands_over_the_figure_and_what_is_on_screen_as_its_record(self):
        self.modules(overview)
        dlg = self.open()
        dlg.btn_export.click()
        fig = self.rec.figures[-1]
        self.assertEqual(fig["prefix"], "RecordingOverview")
        self.assertIs(fig["fig"], dlg.fig)
        self.assertEqual(fig["provenance"], {"kind": "recording_overview", "parameters": dlg.params})

    def test_copy_puts_the_summary_on_the_clipboard(self):
        dlg = self.open()
        with mock.patch.object(overview, "show_window_toast", mock.Mock()):
            dlg.btn_copy.click()
        self.assertEqual(self.app.clipboard().text(), dlg.lbl_summary.text())


class TestEndToEnd(OpenOverview, ExportingCase):
    """The real Export CSV: every sample in the file, the record beside it, Open Results drawing it, and the library replaying it."""

    def export(self, dlg):
        before = set(self.csvs())
        self.click(dlg, "Export CSV")
        (new,) = set(self.csvs()) - before
        return os.path.join(self.folder_out, new)

    def test_the_file_has_every_sample_not_the_thinned_picture(self):
        dlg = self.open()
        path = self.export(dlg)
        exported = pd.read_csv(path)
        self.assertEqual(list(exported.columns), ["time_s", *PANELS])
        self.assertEqual(len(exported), 40_000)
        assert_allclose(exported["time_s"].to_numpy(), self.ctx.cache["x"], rtol=0, atol=1e-9)
        dff = self.ctx.cache["signals"]["normalized"]["y"]
        assert_allclose(exported["ΔF/F"].to_numpy(), dff, rtol=0, atol=1e-9)
        self.assertAlmostEqual(exported["Z-Score"].mean(), 0.0, places=6)
        self.assertAlmostEqual(exported["Z-Score"].std(ddof=0), 1.0, places=6)

    def test_its_record_replays_it(self):
        dlg = self.open()
        path = self.export(dlg)
        record = pv.sidecar_path_for(path)
        rec = pv.read_record(record)
        self.assertEqual(rec["kind"], "recording_overview")
        self.assertEqual(rec["analysis"]["parameters"], {"signal": "normalized", "method": "standard", "max_points": 0})
        rep = R.reproduce(record, compare=[path], tolerance=TOL, strict=True)
        self.assertTrue(rep.ok, rep.comparisons)
        self.assertEqual(rep.warnings, [])

    def test_the_file_has_the_panels_that_are_shown_in_their_order_and_its_record_replays_it(self):
        dlg = self.open()
        dlg.panel_list.setCurrentRow(3)                                                          # Z-Score, up to the top
        for _ in range(3):
            dlg._move(-1)
        for name in ("Control", "Control Fit", "ΔF/F"):
            item = next(dlg.panel_list.item(i) for i in range(dlg.panel_list.count()) if dlg.panel_list.item(i).text() == name)
            item.setCheckState(Qt.CheckState.Unchecked)
        path = self.export(dlg)
        exported = pd.read_csv(path)
        self.assertEqual(list(exported.columns), ["time_s", "Z-Score", "Signal"])
        self.assertEqual(len(exported), 40_000)                                                  # every sample, of just those
        record = pv.sidecar_path_for(path)
        self.assertEqual(pv.read_record(record)["analysis"]["parameters"]["panels"], ["Z-Score", "Signal"])
        rep = R.reproduce(record, compare=[path], tolerance=TOL, strict=True)
        self.assertTrue(rep.ok, rep.comparisons)
        fig = draw_csv(path)
        self.assertEqual([ax.get_title(loc="left") for ax in fig.axes], ["Z-Score", "Signal"])
        two = pd.read_csv(path, usecols=["time_s", "Signal", "Z-Score"])[["time_s", "Signal"]]   # (a choice with no Z-Score among it is still an overview)
        self.assertEqual([name for name, _ in figures.overview_panels(two.assign(Control=two["Signal"]))], ["Signal", "Control"])

    def test_open_results_draws_the_exported_file_as_the_window_drew_it(self):
        dlg = self.open()
        path = self.export(dlg)
        fig = draw_csv(path)
        self.assertEqual([ax.get_title(loc="left") for ax in fig.axes], PANELS)
        self.assertEqual(fig._suptitle.get_text(), "Recording Overview")                           # a bare table does not say how its Z-score was taken ...
        self.assertEqual(draw_csv(pv.sidecar_path_for(path))._suptitle.get_text(), "Recording Overview — Z-score (standard)")   # ... its record does
        line = fig.axes[3].lines[0]
        self.assertLess(len(line.get_xdata()), 6000)                                               # 40,000 samples, drawn from their peaks and dips
        self.assertEqual(line.get_ydata().max(), pd.read_csv(path)["Z-Score"].max())


if __name__ == "__main__":
    unittest.main()
