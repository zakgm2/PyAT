"""Compare Events (analysis/event_compare.py): the average Z-score of several events overlaid. The window shows what the library's `event_compare`
gives for the ticked events, its two tables are what Export CSV writes, the figure is the one Open Results draws from them, and the record
beside an export replays it."""

import os
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from numpy.testing import assert_allclose
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QPushButton

import PyATCLI as pl
from PyATCLI import provenance as pv
from PyATCLI import reproduce as R

from physicsanalysis_qt import figures
from physicsanalysis_qt.analysis import custom_statistics, event_compare, event_peth

from tests.test_draw_exported_csv import ExportingCase, QUIET_TOAST, draw_csv
from tests.test_gui_reproduces import GuiCase, TOL

BOTH = ["L1P¹", "L1P⁰"]                                              # the fixture's press onsets and releases: 7 of each
WINDOW = (3.0, 6.0, 2.0)


class OpenCompare:
    """Opens the real Compare Events window on the fixture recording; its export buttons and toasts are the test's own (self.rec, self.toasts)."""

    def open(self, events=BOTH, window=WINDOW, patch_exports=True):
        self.toasts, self.errors = [], []
        for name, sink in (("show_window_toast", self.toasts), ("show_error", self.errors)):
            patcher = mock.patch.object(event_compare, name, lambda ctx, msg, *a, _sink=sink, **k: _sink.append(msg))
            patcher.start()
            self.addCleanup(patcher.stop)
        shown = []
        if patch_exports:
            self.modules(event_compare)                                                  # the Recorder takes what the window hands the export buttons
            self.exec_side_effect = lambda dialog: shown.append(dialog) or 0
        else:
            patcher = mock.patch.object(QDialog, "exec", new=lambda dialog: shown.append(dialog) or 0)
            patcher.start()
            self.addCleanup(patcher.stop)
        with mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=QUIET_TOAST):
            event_compare.launch_event_compare(self.ctx, list(events), window)
            self.dlg = shown[0]
        return self.dlg

    def tick(self, dlg, *names):
        for i in range(dlg.event_list.count()):
            item = dlg.event_list.item(i)
            item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in names else Qt.CheckState.Unchecked)

    def compare(self, dlg):
        with mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=QUIET_TOAST):
            dlg.btn_compare.click()

    def drawn_lines(self, dlg):
        """(label, x, y) of each event's line: not the reference lines at 0."""
        ax = dlg.fig.axes[0]
        return [(line.get_label(), line.get_xdata(), line.get_ydata()) for line in ax.lines if not line.get_label().startswith("_")]


class TestTheWindow(OpenCompare, GuiCase):
    def test_it_is_opened_with_the_given_events_ticked_and_compared_in_the_given_window(self):
        dlg = self.open()
        self.assertEqual(dlg._ticked(), sorted(BOTH))
        self.assertEqual((dlg.e_pre.text(), dlg.e_post.text(), dlg.e_bin.text()), ("3", "6", "2"))
        self.assertEqual(self.errors, [])
        self.assertEqual(sorted(dlg.tables), ["summary", "traces"])
        self.assertEqual([e["event"] for e in dlg.events], sorted(BOTH))

    def test_each_events_line_is_its_mean_z_score_labelled_with_its_trials(self):
        dlg = self.open()
        lines = self.drawn_lines(dlg)
        self.assertEqual([label for label, _, _ in lines], [f"{name} (n=7)" for name in sorted(BOTH)])
        for event, (_, x, y) in zip(sorted(BOTH), lines):
            peth = pl.run_analysis("event_peth", self.ctx.cache, {"event": event, "pre_s": 3, "post_s": 6, "bin_s": 2})   # Event PETH's own trace for it
            assert_allclose(y, peth.tables["mean_sem"]["mean"].to_numpy(), rtol=0, atol=1e-12)
            assert_allclose(x, peth.tables["mean_sem"]["time_from_event_s"].to_numpy(), rtol=0, atol=1e-12)
        ax = dlg.fig.axes[0]
        self.assertEqual(tuple(ax.get_xlim()), (-3.0, 6.0))
        self.assertEqual(ax.get_ylabel(), "Z-Score (Normalized)")
        self.assertEqual(ax.get_xlabel(), "Time from Event (s)")

    def test_the_sem_is_a_band_around_each_line_unless_switched_off(self):
        dlg = self.open()
        self.assertEqual(len(dlg.fig.axes[0].collections), 2)
        dlg.chk_sem.setChecked(False)
        self.assertEqual(len(dlg.fig.axes[0].collections), 0)
        self.assertEqual(len(self.drawn_lines(dlg)), 2)

    def test_the_title_is_automatic_until_one_is_typed_in_edit_attributes_and_stays_through_a_redraw(self):
        dlg = self.open()
        self.assertFalse(hasattr(dlg, "e_title"))                                        # (the window has no title field of its own: Edit Attributes is where it is typed)
        editable = dlg.editable_figure
        self.assertEqual(dlg.fig._suptitle.get_text(), "Compare Events — L1P¹ vs L1P⁰")
        editable.set_edits(figures.restyle.edited(editable.parts, editable.edits, texts={"Figure title": "Press vs release"}))
        self.assertEqual(dlg.fig._suptitle.get_text(), "Press vs release")
        dlg.chk_sem.setChecked(False)                                                    # the window draws its figure again: the title is the one typed
        self.assertEqual(dlg.fig._suptitle.get_text(), "Press vs release")
        editable.reset()
        self.assertEqual(dlg.fig._suptitle.get_text(), "Compare Events — L1P¹ vs L1P⁰")

    def test_the_summary_below_has_a_row_per_event(self):
        dlg = self.open()
        text = dlg.lbl_summary.text().splitlines()
        self.assertEqual(len(text), 4)                                                   # header, two events, the window
        self.assertTrue(text[0].startswith("Event"))
        self.assertTrue(text[1].startswith("L1P¹"))
        self.assertTrue(text[2].startswith("L1P⁰"))
        self.assertEqual(text[3], "Window: -3s / +6s around each event, 2s bins")
        row = dlg.tables["summary"].set_index("Event").loc["L1P¹"]
        self.assertIn(f"{row['Peak Amplitude']:.2f}", text[1])

    def test_nothing_is_run_until_events_are_ticked_and_the_figure_says_so(self):
        dlg = self.open(events=[])
        self.assertEqual(dlg.tables, {})
        self.assertIsNone(dlg._provenance())
        self.assertEqual([t.get_text() for t in dlg.fig.axes[0].texts], ["Tick the events to compare,\nthen press Compare"])
        self.assertEqual(dlg.fig._suptitle.get_text(), "Compare Events")
        self.compare(dlg)
        self.assertEqual(self.errors, ["Tick at least one event to compare."])
        self.assertEqual(dlg._csv_rows(), [])

    def test_changing_the_ticks_and_pressing_compare_runs_it_again_in_place(self):
        dlg = self.open()
        self.tick(dlg, "L1P¹")
        self.assertEqual(len(self.drawn_lines(dlg)), 2)                                  # not until Compare is pressed
        self.compare(dlg)
        self.assertEqual([label for label, _, _ in self.drawn_lines(dlg)], ["L1P¹ (n=7)"])
        self.assertEqual(dlg._provenance()["parameters"]["events"], ["L1P¹"])
        self.assertEqual(dlg.fig._suptitle.get_text(), "Compare Events — L1P¹")
        dlg._set_all_ticked(True)
        self.compare(dlg)
        self.assertEqual(len(self.drawn_lines(dlg)), 2)
        dlg._set_all_ticked(False)
        self.assertEqual(dlg._ticked(), [])

    def test_changing_the_window_changes_what_is_compared(self):
        dlg = self.open()
        dlg.e_pre.setText("2")
        dlg.e_post.setText("4")
        dlg.e_bin.setText("1")
        self.compare(dlg)
        self.assertEqual(tuple(dlg.fig.axes[0].get_xlim()), (-2.0, 4.0))
        params = dlg._provenance()["parameters"]
        self.assertEqual((params["pre_s"], params["post_s"], params["bin_s"]), (2.0, 4.0, 1.0))
        self.assertTrue(dlg.lbl_summary.text().endswith("1s bins"))
        dlg.e_pre.setText("nonsense")                                                    # a field that is not a number falls back to the window setting
        self.assertEqual(dlg._read_window()[0], 5.0)

    def test_what_is_exported_is_what_is_on_screen_not_what_is_ticked_since(self):
        dlg = self.open()
        self.tick(dlg, "L1P¹")
        self.assertEqual(dlg._provenance()["parameters"]["events"], sorted(BOTH))

    def test_an_older_library_without_the_analysis_is_told_what_to_do(self):
        dlg = self.open()
        self.errors.clear()

        def refuse(ctx, kind, params, on_result, label=None, on_error=None):
            on_error("Unknown analysis 'event_compare'; expected one of zscore_window, event_peth")

        with mock.patch.object(event_compare, "request_analysis", refuse):
            dlg.btn_compare.click()
        self.assertEqual(self.errors, [event_compare.NEEDS_NEWER_LIBRARY])
        self.assertTrue(dlg.btn_compare.isEnabled())

    def test_another_failure_is_reported_with_its_message_and_the_button_is_free_again(self):
        dlg = self.open()
        self.errors.clear()
        with mock.patch.object(event_compare, "request_analysis", lambda ctx, kind, params, on_result, label=None, on_error=None: on_error("boom")):
            dlg.btn_compare.click()
        self.assertEqual(self.errors, ["Compare Events failed: boom"])
        self.assertTrue(dlg.btn_compare.isEnabled())

    def test_a_request_that_could_not_start_frees_the_button(self):
        dlg = self.open()
        with mock.patch.object(event_compare, "request_analysis", lambda *a, **k: None):
            dlg.btn_compare.click()
        self.assertTrue(dlg.btn_compare.isEnabled())

    def test_it_needs_a_tdt_recording_with_events(self):
        self.modules(event_compare)
        errors = []
        with mock.patch.object(event_compare, "show_error", lambda ctx, msg: errors.append(msg)):
            self.ctx.cache = {**self.ctx.cache, "source": "Oxysoft"}
            event_compare.launch_event_compare(self.ctx)
            self.ctx.cache = {**self.ctx.cache, "source": "TDT", "markers": [], "detected_markers": []}
            event_compare.launch_event_compare(self.ctx)
        self.assertEqual(errors, ["Compare Events is only available for TDT data.", "No events found in this recording."])


class TestWhatIsExported(OpenCompare, GuiCase):
    def test_each_table_exports_what_the_library_gives_for_what_the_window_ran(self):
        dlg = self.open()
        prov = dlg._provenance()
        self.assertEqual(prov["kind"], "event_compare")
        self.assertEqual(prov["parameters"]["events"], sorted(BOTH))
        self.assertEqual({name: len(times) for name, times in prov["parameters"]["event_groups"].items()}, {"L1P¹": 7, "L1P⁰": 7})
        for label, table in dlg.TABLES:
            with self.subTest(table):
                dlg.table_combo.setCurrentIndex(dlg.table_combo.findData(table))
                header, rows = self.rec.csv_table(0)
                self.assert_same_export(header, rows, self.lib_table(prov, table), f"compare_{table}")

    def test_the_export_buttons_are_the_shared_ones_with_this_windows_name_and_record(self):
        dlg = self.open()
        kw = self.rec.csv[0]
        self.assertEqual(kw["csv_default_name"](), "EventCompare_traces")
        dlg.table_combo.setCurrentIndex(dlg.table_combo.findData("summary"))
        self.assertEqual(kw["csv_default_name"](), "EventCompare_summary")
        self.assertEqual(kw["provenance"](), dlg._provenance())
        self.assertEqual(kw["get_clipboard_text"](), dlg.lbl_summary.text())
        dlg.btn_export.click()
        fig = self.rec.figures[-1]
        self.assertEqual(fig["prefix"], "EventCompare")
        self.assertEqual(fig["provenance"], dlg._provenance())
        self.assertIs(fig["fig"], dlg.fig)

    def test_the_figure_is_the_one_open_results_draws_from_the_same_tables(self):
        dlg = self.open()
        again = figures.build_figure(dlg.tables, "event_compare", dlg._provenance()["parameters"])
        pd.testing.assert_frame_equal(figures.figure_tables(dlg.fig)["data"], figures.figure_tables(again)["data"])
        self.assertEqual(again._suptitle.get_text(), dlg.fig._suptitle.get_text())

    def test_the_data_csv_of_the_figure_has_a_line_and_a_band_per_event(self):
        dlg = self.open()
        data = figures.figure_tables(dlg.fig)["data"]
        self.assertEqual(sorted(set(data["kind"])), ["band", "line"])
        self.assertEqual(sorted(set(data[data["kind"] == "line"]["series"])), ["L1P¹ (n=7)", "L1P⁰ (n=7)"])
        self.assertEqual(sorted(set(data[data["kind"] == "band"]["series"])), ["L1P¹ (n=7) band", "L1P⁰ (n=7) band"])


class TestEndToEnd(OpenCompare, ExportingCase):
    """The real Export CSV: the file, the record beside it, Open Results drawing it, and the library replaying it."""

    def export(self, dlg, table):
        dlg.table_combo.setCurrentIndex(dlg.table_combo.findData(table))
        before = set(self.csvs())
        self.click(dlg, "Export CSV")
        (new,) = set(self.csvs()) - before
        return os.path.join(self.folder_out, new)

    def test_an_exported_trace_table_is_drawn_by_open_results_as_the_window_drew_it(self):
        dlg = self.open(patch_exports=False)
        path = self.export(dlg, "traces")
        fig = draw_csv(path)
        exported = pd.read_csv(path)
        self.assertEqual(list(exported.columns), ["Event", "time_from_event_s", "mean", "sem", "n"])
        lines = [line for line in fig.axes[0].lines if not line.get_label().startswith("_")]
        self.assertEqual([line.get_label() for line in lines], [f"{name} (n=7)" for name in sorted(BOTH)])
        for line in lines:
            rows = exported[exported["Event"] == line.get_label().split(" (")[0]]
            assert_allclose(line.get_ydata(), rows["mean"].to_numpy(), rtol=0, atol=1e-5)
        self.assertEqual(fig._suptitle.get_text(), "Compare Events — L1P¹ vs L1P⁰")
        self.assertEqual(tuple(fig.axes[0].get_xlim()), (-3.0, 6.0))                       # the window is in the record beside the file

    def test_each_exported_table_is_replayed_from_its_record_alone(self):
        dlg = self.open(patch_exports=False)
        for table in ("traces", "summary"):
            with self.subTest(table):
                path = self.export(dlg, table)
                record = pv.sidecar_path_for(path)
                rec = pv.read_record(record)
                self.assertEqual(rec["kind"], "event_compare")
                self.assertEqual(rec["analysis"]["parameters"]["events"], sorted(BOTH))
                rep = R.reproduce(record, compare=[path], tolerance=TOL, strict=True)
                self.assertTrue(rep.ok, rep.comparisons)
                self.assertEqual(rep.warnings, [])
                self.assertEqual(rep.comparisons[0]["table"], table)

    def test_an_exported_summary_is_drawn_by_open_results_as_peaks_and_areas(self):
        dlg = self.open(patch_exports=False)
        fig = draw_csv(self.export(dlg, "summary"))
        self.assertEqual(len(fig.axes), 2)
        self.assertEqual([t.get_text() for t in fig.axes[1].get_xticklabels()], sorted(BOTH))

    def test_a_summary_with_a_splice_and_a_renamed_event_is_replayed_too(self):
        self.ctx = self.make_ctx(splices=[{"mode": "cut_out", "start": 7.0, "end": 8.5}])
        self.ctx.store_labels = {"L1P": "Lever"}
        self.ctx.settings["output_folder"] = self.out
        dlg = self.open(events=["Lever¹", "Lever⁰"], patch_exports=False)
        path = self.export(dlg, "summary")
        rec = pv.read_record(pv.sidecar_path_for(path))
        self.assertEqual(rec["recording"]["splices"], [{"mode": "cut_out", "start": 7.0, "end": 8.5}])
        self.assertEqual(rec["analysis"]["parameters"]["events"], ["Lever¹", "Lever⁰"])
        os.remove(os.path.join(self.folder, "JSON saves", "splice.json"))                  # undone afterwards: the record still knows
        rep = R.reproduce(pv.sidecar_path_for(path), compare=[path], tolerance=TOL, strict=True)
        self.assertTrue(rep.ok, rep.comparisons)


class TestWhereItIsReachedFrom(OpenCompare, GuiCase):
    def test_custom_statistics_lists_it_for_tdt_only(self):
        tool = next(t for t in custom_statistics._CUSTOM_TOOLS if t["launch"] is event_compare.launch_event_compare)
        self.assertEqual(tool["requires_source"], "TDT")
        self.assertIn("Compare Events", tool["label"])

    def test_event_peths_button_opens_it_with_that_event_and_that_window(self):
        self.modules(event_peth)
        dialogs = []
        with mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=QUIET_TOAST):
            self.exec_side_effect = lambda dlg: dialogs.append(dlg) or 0
            event_peth.launch_event_peth(self.ctx)
            dlg = dialogs[0]
            dlg.e_pre.setText("3")
            dlg.e_post.setText("6")
            dlg.e_bin.setText("2")
            dlg._run(dlg.event_name)
        buttons = [b for b in dlg.findChildren(QPushButton) if b.text() == "Compare events…"]
        self.assertEqual(len(buttons), 1)
        with mock.patch.object(event_peth, "launch_event_compare") as launched:
            buttons[0].click()
        launched.assert_called_once_with(self.ctx, [dlg.event_name], (3.0, 6.0, 2.0))

    def test_it_opens_from_that_call_with_the_event_ticked_and_compared(self):
        dlg = self.open(events=["L1P¹"], window=(3.0, 6.0, 2.0))
        self.assertEqual(dlg._ticked(), ["L1P¹"])
        self.assertEqual([label for label, _, _ in self.drawn_lines(dlg)], ["L1P¹ (n=7)"])


class TestTheDrawing(unittest.TestCase):
    """figures.draw_event_compare from arrays, and event_compare_from_tables from tables."""

    @staticmethod
    def events(n=3, samples=50):
        t = np.linspace(-2, 4, samples)
        return [{"event": f"E{i}", "t": t, "mean": np.sin(t + i), "sem": np.full(samples, 0.1), "n": 4 + i} for i in range(n)]

    def test_each_event_gets_the_next_colour_in_the_palette_and_wraps(self):
        fig = figures.new_event_compare_figure()
        ax = figures.draw_event_compare(fig, events=self.events(10), pre=2, post=4)
        colors = [line.get_color() for line in ax.lines if not line.get_label().startswith("_")]
        self.assertEqual(colors, [figures.draw.COMPARE_COLORS[i % 8] for i in range(10)])

    def test_the_title_names_up_to_three_events_then_counts_them(self):
        self.assertEqual(figures.compare_title(self.events(2)), "Compare Events — E0 vs E1")
        self.assertEqual(figures.compare_title(self.events(3)), "Compare Events — E0 vs E1 vs E2")
        self.assertEqual(figures.compare_title(self.events(4)), "Compare Events (4 events)")

    def test_it_is_redrawn_from_scratch_each_time(self):
        fig = figures.new_event_compare_figure()
        figures.draw_event_compare(fig, events=self.events(3), pre=2, post=4)
        figures.draw_event_compare(fig, events=self.events(1), pre=2, post=4)
        self.assertEqual(len(fig.axes), 1)
        self.assertEqual(len([line for line in fig.axes[0].lines if not line.get_label().startswith("_")]), 1)

    def test_events_come_back_from_a_traces_table_in_their_order_and_a_table_that_is_not_one_is_not_drawn(self):
        rows = [[name, float(t), float(m), 0.1, 5] for name in ("B", "A") for t, m in zip(range(4), range(4))]
        traces = pd.DataFrame(rows, columns=["Event", "time_from_event_s", "mean", "sem", "n"])
        events = figures.compare_events_from_tables({"traces": traces})
        self.assertEqual([e["event"] for e in events], ["B", "A"])
        self.assertEqual(events[0]["n"], 5)
        fig = figures.event_compare_from_tables({"traces": traces}, {})
        self.assertEqual(tuple(fig.axes[0].get_xlim()), (0.0, 3.0))                      # no window recorded: how far the data reaches
        self.assertIsNone(figures.compare_events_from_tables({"x": pd.DataFrame({"a": [1]})}))
        self.assertIsNone(figures.event_compare_from_tables({"x": pd.DataFrame({"a": [1]})}, {}))

    def test_build_figure_picks_it_for_a_traces_table_and_keeps_a_given_title(self):
        traces = pd.DataFrame([["A", 0.0, 1.0, 0.1, 3], ["A", 1.0, 2.0, 0.1, 3]], columns=["Event", "time_from_event_s", "mean", "sem", "n"])
        fig = figures.build_figure({"traces": traces}, "event_compare", {"pre_s": 1.0, "post_s": 2.0})
        self.assertEqual(fig._suptitle.get_text(), "Compare Events — A")
        self.assertEqual(figures.build_figure({"traces": traces}, "event_compare", {}, title="Mine")._suptitle.get_text(), "Mine")

    def test_a_summary_table_alone_is_drawn_as_a_plain_panel_figure(self):
        summary = pd.DataFrame([["A", 5, 5, 1.0, 0.5, 2.0, 2.0, 0.0]], columns=["Event", "Occurrences", "Trials", "Peak Amplitude", "Time-to-Peak (s)",
                                                                              "Total AUC", "Positive AUC", "Negative AUC"])
        fig = figures.build_figure({"summary": summary}, "event_compare", {})
        self.assertEqual(len(fig.axes), 2)                                               # the peaks, then the areas
        self.assertEqual([t.get_text() for t in fig.axes[1].get_xticklabels()], ["A"])


if __name__ == "__main__":
    unittest.main()
