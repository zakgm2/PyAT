"""Splicing through the analysis engine (edit/splice.py): a splice is worked out by the engine and put on the recording when it answers,
undo / removing a splice / Restore Full Recording are asking for an earlier list of splices, and a recording that changed while the engine
was busy is not overwritten with a result that predates the change."""

import os
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

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


if __name__ == "__main__":
    unittest.main()
