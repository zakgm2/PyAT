"""Splicing through the analysis engine (edit/splice.py): a splice is worked out by the engine and put on the recording when it answers,
undo / removing a splice / Restore Full Recording are asking for an earlier list of splices, and a recording that changed while the engine
was busy is not overwritten with a result that predates the change."""

import os
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtWidgets import QDialog

import PyATCLI as pl

from physicsanalysis_qt.edit import undo
from physicsanalysis_qt.edit import splice

from tests.test_gui_reproduces import WindowCase


class SpliceCase(WindowCase):
    def setUp(self):
        super().setUp()
        self.toasts, self.errors, self.done = [], [], []
        for name, sink in (("show_window_toast", self.toasts), ("show_error", self.errors)):
            patcher = mock.patch.object(splice, name, lambda ctx, msg, *a, _sink=sink, **k: _sink.append(msg))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.ctx.cache["markers"] = [self.marker(5.0, "early"), self.marker(20.0, "mid"), self.marker(30.0, "late")]

    @staticmethod
    def marker(time_s, label):
        return {**pl.saved_state.DEFAULT_MARKER, "time": time_s, "label": label}

    def cut(self, start, end):
        self.done.clear()
        splice.apply_splice(self.ctx, pl.MODE_CUT_OUT, start, end, on_done=self.done.append)
        self.settle()
        return self.done[-1] if self.done else None

    def settle(self, timeout=60):
        """Until the request the window has running is answered and delivered (none is, with the test context's synchronous requests)."""
        end = time.monotonic() + timeout
        while (self.ctx._bg_request is not None or self.ctx._bg_bridge is not None) and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()

    def labels_of(self, cache):
        return [m["label"] for m in cache["markers"]]


class TestApplying(SpliceCase):
    def test_a_cut_is_applied_on_the_recording_the_engine_hands_back(self):
        full = self.ctx.cache
        self.assertTrue(self.cut(10.0, 15.0))
        ctx = self.ctx
        self.assertEqual(ctx._active_splices, [{"mode": "cut_out", "start": 10.0, "end": 15.0}])
        self.assertIs(ctx.original_cache, full)                                              # kept, for Restore Full Recording
        self.assertLess(len(ctx.cache["x"]), len(full["x"]))
        self.assertAlmostEqual(len(full["x"]) - len(ctx.cache["x"]), 5000, delta=2)
        self.assertEqual(ctx.cache["store"], pl.spliced_store_name(full["store"], ctx._active_splices))
        self.assertTrue(any(t.startswith("Cut out 10.0s–15.0s") and "OLS dF/F recomputed" in t for t in self.toasts), self.toasts)

    def test_it_is_the_recording_a_script_gets_from_the_same_splice(self):
        full = pl.load_recording(self.folder)["cache"]
        self.cut(10.0, 15.0)
        reference = pl.apply_splice({**full, "markers": [dict(m) for m in self.ctx.original_cache["markers"]]}, pl.MODE_CUT_OUT, 10.0, 15.0)
        np.testing.assert_array_equal(self.ctx.cache["x"], reference["x"])
        np.testing.assert_allclose(self.ctx.cache["corr"], reference["corr"])
        self.assertEqual(self.ctx.cache["markers"], reference["markers"])
        self.assertEqual(self.ctx.cache["detected_markers"], reference["detected_markers"])

    def test_the_markers_are_the_windows_own_moved_through_the_splice(self):
        self.cut(10.0, 15.0)
        self.assertEqual(self.labels_of(self.ctx.cache), ["early", "mid", "late"])
        times = [m["time"] for m in self.ctx.cache["markers"]]
        self.assertEqual(times[0], 5.0)
        self.assertAlmostEqual(times[1], 15.0, delta=0.01)                                   # 20 s, 5 s cut out before it
        self.assertAlmostEqual(times[2], 25.0, delta=0.01)

    def test_highlights_text_boxes_and_names_given_in_the_window_are_kept(self):
        self.ctx.cache["highlights"] = [{"start": 1.0, "end": 2.0, "color": "yellow"}]
        self.ctx._signal_renames = {"main_driver": "GCaMP"}
        pl.apply_signal_labels(self.ctx.cache, self.ctx._signal_renames)
        self.cut(10.0, 15.0)
        self.assertEqual(self.ctx.cache["highlights"], [{"start": 1.0, "end": 2.0, "color": "yellow"}])
        self.assertNotIn("text_annotations", self.ctx.cache)
        self.assertEqual(self.ctx.cache["signals"]["main_driver"]["label"], "GCaMP")
        self.assertTrue(all(s["color"] for s in self.ctx.cache["signals"].values()))

    def test_keep_inside_works_too(self):
        splice.apply_splice(self.ctx, pl.MODE_KEEP_INSIDE, 10.0, 20.0, on_done=self.done.append)
        self.settle()
        self.assertEqual(self.done, [True])
        self.assertAlmostEqual(self.ctx.cache["x"][-1] - self.ctx.cache["x"][0], 10.0, delta=0.01)
        self.assertEqual(self.labels_of(self.ctx.cache), ["mid"])

    def test_splices_stack(self):
        self.cut(10.0, 15.0)
        self.cut(20.0, 22.0)
        self.assertEqual(len(self.ctx._active_splices), 2)
        self.assertEqual(len(self.ctx.original_cache["x"]), 40_000)                           # still the recording as recorded
        self.assertAlmostEqual(len(self.ctx.cache["x"]), 40_000 - 5000 - 2000, delta=3)

    def test_a_range_that_leaves_too_little_is_refused_and_changes_nothing(self):
        before = self.ctx.cache
        self.assertFalse(self.cut(-1.0, 100.0))
        self.assertEqual(self.errors, ["Can't cut that range — at least 2 samples need to remain."])
        self.assertIs(self.ctx.cache, before)
        self.assertEqual((self.ctx._active_splices, self.ctx.original_cache), ([], None))
        self.assertFalse(undo.can_undo(self.ctx))

    def test_a_recording_the_engine_does_not_hold_is_an_error_message(self):
        self.ctx.recording_id = None
        self.assertFalse(self.cut(10.0, 15.0))
        self.assertEqual(len(self.errors), 1)
        self.assertIn("not held by the analysis engine", self.errors[0])


class TestUndoAndRestore(SpliceCase):
    def test_ctrl_z_brings_back_the_recording_as_it_was_and_needs_no_engine(self):
        before = self.ctx.cache
        self.cut(10.0, 15.0)
        with mock.patch("physicsanalysis_qt.plot.plotting.simple_plot"), mock.patch.object(self.ctx.engine, "request") as request:
            self.assertEqual(undo.undo(self.ctx), "applied a splice")
        request.assert_not_called()
        self.assertIs(self.ctx.cache["x"], before["x"])                                      # the same arrays, mapped once
        self.assertEqual(self.ctx.cache["store"], before["store"])
        self.assertEqual(self.labels_of(self.ctx.cache), ["early", "mid", "late"])
        self.assertEqual((self.ctx._active_splices, self.ctx.original_cache), ([], None))

    def test_restore_full_recording_is_local_too(self):
        full = self.ctx.cache
        self.cut(10.0, 15.0)
        with mock.patch.object(self.ctx.engine, "request") as request:
            splice.restore_full_recording(self.ctx)
        request.assert_not_called()
        self.assertIs(self.ctx.cache, full)
        self.assertEqual((self.ctx._active_splices, self.ctx.original_cache), ([], None))
        self.assertIn("Restored full recording", self.toasts)

    def test_splicing_again_after_an_undo_is_the_engines_remembered_variant(self):
        self.cut(10.0, 15.0)
        with mock.patch("physicsanalysis_qt.plot.plotting.simple_plot"):
            undo.undo(self.ctx)
        started = time.monotonic()
        self.cut(10.0, 15.0)
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertEqual(len(self.ctx._active_splices), 1)


class TestRemoving(SpliceCase):
    def test_removing_one_replays_the_rest_from_the_original(self):
        self.cut(10.0, 15.0)
        self.cut(20.0, 22.0)
        done = []
        splice.remove_splice(self.ctx, 0, on_done=done.append)
        self.settle()
        self.assertEqual(done, [True])
        self.assertEqual(self.ctx._active_splices, [{"mode": "cut_out", "start": 20.0, "end": 22.0}])
        self.assertAlmostEqual(len(self.ctx.cache["x"]), 40_000 - 2000, delta=3)
        self.assertEqual(self.ctx.cache["store"], pl.spliced_store_name(self.ctx.original_cache["store"], self.ctx._active_splices))
        self.assertIn("Removed splice — 1 remaining", self.toasts)
        self.assertEqual(self.labels_of(self.ctx.cache), ["early", "mid", "late"])             # the original's markers, moved through what is left
        self.assertAlmostEqual(self.ctx.cache["markers"][2]["time"], 28.0, delta=0.01)

    def test_removing_the_last_one_is_a_restore(self):
        full = self.ctx.cache
        self.cut(10.0, 15.0)
        done = []
        self.assertTrue(splice.remove_splice(self.ctx, 0, on_done=done.append))
        self.assertEqual(done, [True])
        self.assertIs(self.ctx.cache, full)

    def test_removing_what_does_not_exist_is_nothing(self):
        done = []
        self.assertFalse(splice.remove_splice(self.ctx, 3, on_done=done.append))
        self.assertEqual(done, [False])

    def test_removal_can_be_undone(self):
        self.cut(10.0, 15.0)
        self.cut(20.0, 22.0)
        splice.remove_splice(self.ctx, 0)
        self.settle()
        with mock.patch("physicsanalysis_qt.plot.plotting.simple_plot"):
            self.assertEqual(undo.undo(self.ctx), "removed a splice")
        self.assertEqual(len(self.ctx._active_splices), 2)


class TestTheManager(SpliceCase):
    def test_removing_from_the_dialog_refreshes_its_list(self):
        self.cut(10.0, 15.0)
        self.cut(20.0, 22.0)
        dlg = splice._SpliceManagerDialog(self.ctx.win, self.ctx)
        self.assertEqual(dlg.list_widget.count(), 2)
        dlg.list_widget.setCurrentRow(0)
        dlg._remove_selected()
        self.settle()
        self.assertEqual(dlg.list_widget.count(), 1)
        self.assertTrue(dlg.isEnabled())
        dlg.deleteLater()


class TestWhileTheEngineWorks(SpliceCase):
    def setUp(self):
        super().setUp()
        self.ctx.settings["background_loading"] = True                                       # the answer comes later, as it does for a person

    def test_a_marker_placed_while_it_works_is_not_overwritten(self):
        before = self.ctx.cache
        splice.apply_splice(self.ctx, pl.MODE_CUT_OUT, 10.0, 15.0, on_done=self.done.append)
        self.assertEqual(self.done, [])                                                      # not answered yet
        self.ctx.cache["markers"].append(self.marker(7.0, "placed meanwhile"))
        self.settle()
        self.assertEqual(self.done, [False])
        self.assertEqual(self.errors, [splice.CHANGED_MEANWHILE])
        self.assertIs(self.ctx.cache, before)
        self.assertEqual(self.ctx._active_splices, [])
        self.assertIn("placed meanwhile", self.labels_of(self.ctx.cache))

    def test_a_splice_with_nothing_changed_meanwhile_is_applied_when_it_answers(self):
        splice.apply_splice(self.ctx, pl.MODE_CUT_OUT, 10.0, 15.0, on_done=self.done.append)
        self.assertEqual(self.ctx._active_splices, [])
        self.settle()
        self.assertEqual(self.done, [True])
        self.assertEqual(len(self.ctx._active_splices), 1)

    def test_only_one_request_at_a_time_so_a_second_splice_waits_its_turn(self):
        first = splice.apply_splice(self.ctx, pl.MODE_CUT_OUT, 10.0, 15.0, on_done=self.done.append)
        second = splice.apply_splice(self.ctx, pl.MODE_CUT_OUT, 20.0, 22.0, on_done=self.done.append)
        self.assertIsNotNone(first)
        self.assertIsNone(second)                                                            # refused with a toast, not queued behind it
        self.settle()
        self.assertEqual(len(self.ctx._active_splices), 1)


class TestTrimTheEnds(SpliceCase):
    def trim(self, first, last):
        self.done.clear()
        splice.trim_ends(self.ctx, first, last, on_done=self.done.append)
        self.settle()
        return self.done[-1] if self.done else None

    def test_both_ends_are_taken_off_in_one_splice(self):
        full = self.ctx.cache
        self.assertTrue(self.trim(5.0, 3.0))
        spliced = self.ctx.cache
        self.assertEqual(self.ctx._active_splices, [{"mode": "keep_inside", "start": 5.0, "end": float(full["x"][-1]) - 3.0}])
        self.assertAlmostEqual(spliced["x"][0], 5.0, delta=0.002)
        self.assertAlmostEqual(spliced["x"][-1], 36.999, delta=0.002)                         # the original times are kept
        self.assertAlmostEqual(len(spliced["x"]), 32_000, delta=3)
        self.assertIs(self.ctx.original_cache, full)
        self.assertTrue(any(t.startswith("Trimmed the first 5 s and the last 3 s, ") and "dF/F recomputed" in t for t in self.toasts), self.toasts)
        self.assertEqual(self.labels_of(spliced), ["early", "mid", "late"])                   # 5 s, 20 s and 30 s are all inside 5–37

    def test_one_end_only(self):
        self.assertTrue(self.trim(8.0, 0.0))
        self.assertAlmostEqual(self.ctx.cache["x"][0], 8.0, delta=0.002)
        self.assertAlmostEqual(self.ctx.cache["x"][-1], 39.999, delta=0.002)
        self.assertTrue(any(t.startswith("Trimmed the first 8 s, ") for t in self.toasts), self.toasts)
        self.assertEqual(self.labels_of(self.ctx.cache), ["mid", "late"])                     # the marker at 5 s went with the start
        self.assertTrue(self.trim(0.0, 12.0))
        self.assertAlmostEqual(self.ctx.cache["x"][-1], 39.999 - 12.0, delta=0.002)
        self.assertTrue(any(t.startswith("Trimmed the last 12 s, ") for t in self.toasts), self.toasts)
        self.assertEqual(self.labels_of(self.ctx.cache), ["mid"])

    def test_it_is_the_recording_a_script_gets_from_the_same_keep_inside(self):
        full = pl.load_recording(self.folder)["cache"]
        self.trim(5.0, 3.0)
        start, end = self.ctx._active_splices[0]["start"], self.ctx._active_splices[0]["end"]
        reference = pl.apply_splice({**full, "markers": [dict(m) for m in self.ctx.original_cache["markers"]]}, pl.MODE_KEEP_INSIDE, start, end)
        np.testing.assert_array_equal(self.ctx.cache["x"], reference["x"])
        np.testing.assert_allclose(self.ctx.cache["corr"], reference["corr"])
        self.assertEqual(self.ctx.cache["markers"], reference["markers"])

    def test_it_stacks_on_an_earlier_splice_and_is_undone_with_one_ctrl_z(self):
        self.cut(10.0, 15.0)
        shown = self.ctx.cache
        self.assertTrue(self.trim(2.0, 0.0))
        self.assertEqual(len(self.ctx._active_splices), 2)
        self.assertAlmostEqual(self.ctx._active_splices[1]["start"], float(shown["x"][0]) + 2.0)
        with mock.patch("physicsanalysis_qt.plot.plotting.simple_plot"):
            self.assertEqual(undo.undo(self.ctx), "applied a splice")
        self.assertEqual(len(self.ctx._active_splices), 1)
        self.assertIs(self.ctx.cache["x"], shown["x"])

    def test_the_whole_recording_or_nothing_is_a_message_and_changes_nothing(self):
        before = self.ctx.cache
        self.assertFalse(self.trim(0.0, 0.0))
        self.assertFalse(self.trim(25.0, 25.0))
        self.assertEqual(len(self.errors), 2)
        self.assertIn("how much", self.errors[0])
        self.assertIn("whole recording (40 s long)", self.errors[1])
        self.assertIs(self.ctx.cache, before)
        self.assertEqual((self.ctx._active_splices, self.ctx.original_cache), ([], None))

    def test_leaving_fewer_than_two_samples_is_the_splices_own_message(self):
        self.assertFalse(self.trim(0.0005, 39.9975))                                          # about one sample's worth of recording left
        self.assertEqual(self.errors, ["That range doesn't contain enough samples to analyze."])
        self.assertEqual(self.ctx._active_splices, [])


class TestTheTrimChoiceInTheDialog(SpliceCase):
    def dialog(self):
        dialog = splice._SpliceModePickerDialog(self.ctx.win, self.ctx)
        self.addCleanup(dialog.deleteLater)
        return dialog

    def choose(self, first=0.0, last=0.0, unit="seconds"):
        """Opens the picker with the third choice made and `first` and `last` typed, then accepts it (what Trim does)."""
        def exec_(dialog):
            dialog.rb_trim.setChecked(True)
            dialog.unit.setCurrentText(unit)
            dialog.sp_first.setValue(first)
            dialog.sp_last.setValue(last)
            dialog._accept()
            return QDialog.DialogCode.Accepted

        with mock.patch.object(splice._SpliceModePickerDialog, "exec", exec_):
            started = splice.start_splice_flow(self.ctx)
        self.settle()
        return started

    def test_the_picker_offers_the_third_choice_and_starts_on_cut_out(self):
        dialog = self.dialog()
        self.assertTrue(dialog.rb_cut.isChecked())
        self.assertFalse(dialog.trim_box.isEnabled())
        self.assertEqual(dialog.btn_ok.text(), "Start Clicking…")
        self.assertEqual([dialog.unit.itemText(i) for i in range(dialog.unit.count())], ["seconds", "minutes"])

    def test_choosing_it_changes_the_button_and_says_how_much_will_remain(self):
        dialog = self.dialog()
        dialog.rb_trim.setChecked(True)
        self.assertTrue(dialog.trim_box.isEnabled())
        self.assertEqual(dialog.btn_ok.text(), "Trim")
        self.assertFalse(dialog.btn_ok.isEnabled())                                           # nothing typed yet
        self.assertIn("how much", dialog.summary.text())
        dialog.sp_first.setValue(5.0)
        dialog.sp_last.setValue(3.0)
        self.assertTrue(dialog.btn_ok.isEnabled())
        self.assertEqual(dialog.summary.text(), "32 s of the 40 s shown will remain.")
        dialog.sp_last.setValue(40.0)
        self.assertFalse(dialog.btn_ok.isEnabled())
        self.assertIn("whole recording", dialog.summary.text())
        dialog.rb_keep.setChecked(True)                                                       # back to a clicking choice
        self.assertEqual((dialog.btn_ok.text(), dialog.btn_ok.isEnabled(), dialog.summary.text()), ("Start Clicking…", True, ""))

    def test_the_unit_switch_reads_the_same_numbers_as_minutes(self):
        dialog = self.dialog()
        dialog.rb_trim.setChecked(True)
        dialog.sp_first.setValue(0.25)
        dialog.sp_last.setValue(0.1)
        self.assertEqual(dialog._amounts(), (0.25, 0.1))
        dialog.unit.setCurrentText("minutes")
        first, last = dialog._amounts()
        self.assertAlmostEqual(first, 15.0)
        self.assertAlmostEqual(last, 6.0)
        self.assertEqual(dialog.summary.text(), "19 s of the 40 s shown will remain.")        # and the summary follows the switch

    def test_accepting_it_trims_without_waiting_for_clicks(self):
        self.ctx.splice_click_mode = True                                                     # a clicking flow left waiting is over
        self.assertTrue(self.choose(5.0, 3.0))
        self.assertFalse(self.ctx.splice_click_mode)
        self.assertEqual(len(self.ctx._active_splices), 1)
        self.assertAlmostEqual(self.ctx._active_splices[0]["start"], 5.0)

    def test_minutes_are_converted_to_seconds_for_the_splice(self):
        self.assertTrue(self.choose(0.1, 0.0, unit="minutes"))
        self.assertAlmostEqual(self.ctx._active_splices[0]["start"], 6.0)
        self.assertTrue(any(t.startswith("Trimmed the first 6 s, ") for t in self.toasts), self.toasts)

    def test_the_clicking_choices_still_wait_for_two_clicks(self):
        def exec_(dialog):
            dialog.rb_keep.setChecked(True)
            dialog._accept()
            return QDialog.DialogCode.Accepted

        with mock.patch.object(splice._SpliceModePickerDialog, "exec", exec_):
            self.assertTrue(splice.start_splice_flow(self.ctx))
        self.assertTrue(self.ctx.splice_click_mode)
        self.assertEqual(self.ctx._pending_splice_mode, pl.MODE_KEEP_INSIDE)
        self.assertEqual(self.ctx._active_splices, [])

    def test_a_table_is_told_its_x_column_is_read_as_seconds(self):
        self.assertTrue(self.dialog().generic_note.isHidden())                                # a TDT recording is in seconds
        self.ctx.cache = {**self.ctx.cache, "source": "Generic", "x_label": "Time"}
        note = self.dialog().generic_note
        self.assertFalse(note.isHidden())
        self.assertIn("Time", note.text())
        self.assertIn("seconds", note.text())


if __name__ == "__main__":
    unittest.main()
