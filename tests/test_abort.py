"""Stopping a long task for good: the progress toast's Cancel button (which becomes Stop now), Esc, and the engine process that is ended when the engine
does not stop on being asked — so the work stops at once and its memory goes back to the system — and the recording on screen being opened again in the
new engine."""

import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QPushButton, QWidget

from physicsanalysis_qt.app import background
from physicsanalysis_qt.app.toasts import ProgressToast
from physicsanalysis_qt.backend import engine_client
from physicsanalysis_qt.backend.engine_client import EngineClient, ProcessTransport
from physicsanalysis_qt.backend.errors import BackendError
from physicsanalysis_qt.backend.recordings import recording_ref
from physicsanalysis_qt.context import AppState
from physicsanalysis_qt.loading import common

from tests.test_gui_reproduces import GuiCase, WindowCase

SLEEPER = "import time; time.sleep(300)"           # an "engine" that never answers: a task that has no end


def sleeping_engine():
    return EngineClient(lambda: ProcessTransport([sys.executable, "-c", SLEEPER]))


class TestEndingTheEngine(unittest.TestCase):
    def setUp(self):
        self.client = sleeping_engine()
        self.addCleanup(self.client.shutdown)

    def test_the_request_fails_as_cancelled_and_the_process_is_gone(self):
        request = self.client.request("kinds")
        process = self.client._link.transport.proc
        self.assertIsNone(process.poll())
        self.assertTrue(self.client.abort(request))
        with self.assertRaises(BackendError) as caught:
            request.result(30)
        self.assertTrue(caught.exception.cancelled)
        self.assertTrue(caught.exception.engine_ended)
        process.wait(30)
        self.assertIsNotNone(process.poll())                                                   # ended, not asked politely: it never listened
        self.assertFalse(self.client.running)

    def test_what_waited_behind_it_fails_and_says_why(self):
        first, behind = self.client.request("a"), self.client.request("b")
        self.client.abort(first)
        with self.assertRaises(BackendError):
            first.result(30)
        with self.assertRaises(BackendError) as caught:
            behind.result(30)
        self.assertEqual(caught.exception.code, "engine_stopped")
        self.assertIn("ended to cancel a task", str(caught.exception))
        self.assertTrue(caught.exception.engine_ended)
        self.assertFalse(caught.exception.cancelled)

    def test_there_is_nothing_to_stop_once_a_request_is_over(self):
        request = self.client.request("kinds")
        self.client.abort(request)
        with self.assertRaises(BackendError):
            request.result(30)
        self.assertFalse(self.client.abort(request))

    def test_the_next_request_starts_a_new_engine_which_has_forgotten_the_recordings(self):
        first = self.client.request("kinds")
        generation = self.client.generation
        self.client.abort(first)
        with self.assertRaises(BackendError):
            first.result(30)
        second = self.client.request("kinds")
        self.assertEqual(self.client.generation, generation + 1)
        self.assertTrue(self.client.running)
        self.client.abort(second)

    def test_the_data_folder_of_the_ended_engine_is_removed_unless_something_still_maps_it(self):
        folder = tempfile.mkdtemp(prefix="pyat-dead-engine-")
        self.addCleanup(shutil.rmtree, folder, True)
        with open(os.path.join(folder, "x.npy"), "wb") as f:
            f.write(b"data")
        request = self.client.request("kinds")
        self.client._link.ready = {"data_dir": folder}                                         # what an engine says when it starts
        with mock.patch.object(engine_client.shutil, "rmtree"):                                 # (in use: a window maps its files)
            self.client.abort(request)
            with self.assertRaises(BackendError):
                request.result(30)
            self.assertTrue(os.path.isdir(folder))
            self.assertEqual(self.client._dead_dirs, [folder])
        self.client.sweep_dead_dirs()                                                           # once nothing maps them
        self.assertFalse(os.path.isdir(folder))
        self.assertEqual(self.client._dead_dirs, [])

    def test_a_normal_shutdown_leaves_nothing_to_remove(self):
        self.client.request("kinds")
        self.client.shutdown()
        self.assertEqual(self.client._dead_dirs, [])


class QtCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.ctx = AppState(self.app)
        self.ctx.settings["background_loading"] = True
        self.ctx.win = QWidget()
        self.ctx.win.resize(900, 600)
        self.addCleanup(self.ctx.win.deleteLater)
        self.ctx._engine = sleeping_engine()
        self.addCleanup(self.ctx._engine.shutdown)
        self.failures, self.reconnects = [], []
        for name, target in (("show_window_toast", mock.patch.object(background, "show_window_toast")),
                             ("reconnect", mock.patch.object(common, "reconnect_recording", lambda ctx: self.reconnects.append(ctx)))):
            target.start()
            self.addCleanup(target.stop)

    def spin(self, done, timeout=30):
        end = time.monotonic() + timeout
        while not done() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertTrue(done(), "timed out waiting")

    def run_slow(self, **kw):
        return background.run_engine(self.ctx, "kinds", {}, lambda r: None, lambda m: None, label="A long task", on_failure=self.failures.append, **kw)

    def the_toast(self):
        self.spin(lambda: self.ctx._progress_toast is not None and self.ctx._progress_toast.snapshot()["visible"] or self.ctx._progress_toast is None
                  or self.app.processEvents() or False, timeout=3)
        return self.ctx._progress_toast


class TestCancelThenStop(QtCase):
    def test_the_first_cancel_asks_and_says_so_and_the_second_ends_the_engine(self):
        request = self.run_slow()
        self.assertTrue(background.cancel_running(self.ctx))
        self.assertTrue(request.stopping)
        self.assertTrue(self.ctx.engine.running)                                                # asked, not ended
        self.assertEqual(self.failures, [])
        self.assertTrue(background.cancel_running(self.ctx))                                    # asked again: now
        self.spin(lambda: self.failures)
        self.assertTrue(self.failures[0].cancelled)
        self.assertTrue(self.failures[0].engine_ended)
        self.assertEqual(self.reconnects, [self.ctx])                                           # the recording on screen is opened again
        self.assertFalse(background.cancel_running(self.ctx))                                   # nothing left to stop

    def test_one_the_engine_does_not_stop_is_ended_after_a_few_seconds_by_itself(self):
        with mock.patch.object(background, "STOP_AFTER_S", 0.05):
            self.run_slow()
            background.cancel_running(self.ctx)
            self.spin(lambda: self.failures)
        self.assertTrue(self.failures[0].engine_ended)
        self.assertEqual(len(self.reconnects), 1)

    def test_one_that_stops_when_asked_is_left_alone_and_the_engine_goes_on(self):
        request = self.run_slow()
        with mock.patch.object(background, "STOP_AFTER_S", 0.05):
            background.cancel_running(self.ctx)
            request.future.set_exception(BackendError("cancelled", code="cancelled"))           # what an engine that noticed the cancel answers
            self.spin(lambda: self.failures)
            time.sleep(0.2)
            self.app.processEvents()
        self.assertFalse(self.failures[0].engine_ended)
        self.assertEqual(self.reconnects, [])
        self.assertTrue(self.ctx.engine.running)

    def test_an_engine_ended_by_something_else_is_not_a_cancel_and_reconnects_nothing(self):
        request = self.run_slow()
        self.ctx.engine._link.transport.kill()
        self.spin(lambda: self.failures)
        self.assertFalse(self.failures[0].cancelled)                                            # (this engine never said it was ready: "could not start")
        self.assertFalse(self.failures[0].engine_ended)
        self.assertEqual(self.reconnects, [])
        del request

    def test_a_request_running_beside_the_one_waited_for_is_not_stopped_by_esc(self):
        self.run_slow(exclusive=False)
        self.assertFalse(background.cancel_running(self.ctx))
        self.assertTrue(self.ctx.engine.running)


class TestTheToastsButton(QtCase):
    def shown(self):
        toast = None
        end = time.monotonic() + 5
        while time.monotonic() < end:
            self.app.processEvents()
            toast = self.ctx._progress_toast
            if toast is not None and toast.snapshot()["visible"]:
                return toast
            time.sleep(0.01)
        self.fail("the toast never appeared")

    def buttons(self, toast):
        return toast._widget.findChildren(QPushButton)

    def test_a_task_the_person_waits_for_has_a_cancel_button_that_stops_it_and_then_ends_it(self):
        request = self.run_slow()
        toast = self.shown()
        (button,) = self.buttons(toast)
        self.assertEqual((button.text(), toast.snapshot()["button"]), ("Cancel", "Cancel"))
        self.assertFalse(toast._widget.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))     # (a click has to reach it)
        button.click()
        self.assertTrue(request.stopping)
        shown = toast.snapshot()
        self.assertTrue(shown["stopping"])
        self.assertEqual((button.text(), shown["detail"]), ("Stop now", "Stopping…  Stop now ends it at once"))
        self.assertTrue(self.ctx.engine.running)
        button.click()                                                                          # Stop now
        self.spin(lambda: self.failures)
        self.assertTrue(self.failures[0].engine_ended)
        self.spin(lambda: self.ctx._progress_toast is None)                                     # the toast goes with the task

    def test_a_task_that_runs_beside_it_has_no_button_and_stays_click_through(self):
        self.run_slow(exclusive=False)
        toast = self.shown()
        self.assertEqual(self.buttons(toast), [])
        self.assertIsNone(toast.snapshot()["button"])
        self.assertTrue(toast._widget.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))

    def test_a_toast_with_no_one_to_cancel_to_is_the_plain_one(self):
        toast = ProgressToast(self.ctx, "Reading", delay_ms=0)
        self.ctx._progress_toast = toast
        toast.start()
        toast.update(0.2, "Working")
        self.assertEqual(self.buttons(toast), [])
        self.assertTrue(toast._widget.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        toast.finish()

    def test_pressing_cancel_calls_what_it_was_given(self):
        pressed = []
        toast = ProgressToast(self.ctx, "Reading", delay_ms=0, on_cancel=lambda: pressed.append(1))
        self.ctx._progress_toast = toast
        toast.start()
        toast.update(0.2, "Working")
        self.buttons(toast)[0].click()
        self.assertEqual(pressed, [1])
        toast.finish()

    def test_the_button_is_still_there_when_another_toast_took_the_slot_and_it_came_back(self):
        toast = ProgressToast(self.ctx, "Reading", delay_ms=0, on_cancel=lambda: None)
        self.ctx._progress_toast = toast
        toast.start()
        toast.update(0.2, "Working")
        toast.stopping()
        self.assertEqual(toast.snapshot()["button"], "Stop now")
        toast.finish()


class TestTheRecordingIsReconnected(GuiCase):
    """After the engine was ended, the recording on screen is opened again in the new one (the window keeps its cache and edits)."""

    def test_analyses_work_again_without_a_reload_and_nothing_on_screen_changed(self):
        ctx = self.ctx
        cache, serial, markers = ctx.cache, ctx.recording_serial, list(ctx.cache["markers"])
        ctx.cache["markers"] = markers + [{"time": 12.0, "label": "mine", "color": "green", "fontsize": 8}]      # an edit nobody saved
        ctx.engine.restart()                                                                     # what ending the engine amounts to
        with self.assertRaises(BackendError) as caught:
            recording_ref(ctx)
        self.assertEqual(caught.exception.code, "no_recording")
        old_id = ctx.recording_id
        with mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=None), mock.patch.object(common, "show_window_toast"):
            common.reconnect_recording(ctx)
        self.assertFalse(ctx._reconnecting)
        ref = recording_ref(ctx)                                                                 # no error: the engine has it again
        self.assertEqual(ref["id"], ctx.recording_id)
        self.assertEqual(ctx.recording_generation, ctx.engine.generation)
        self.assertIsNot(ctx.recording_id, None)
        self.assertIs(ctx.cache, cache)                                                          # the same dataset on screen
        self.assertEqual(ctx.recording_serial, serial)                                           # the same recording (analysis windows stay)
        self.assertEqual(ctx.cache["markers"][-1]["label"], "mine")                              # and the unsaved marker is still there, and still sent
        self.assertEqual(ref["markers"][-1]["label"], "mine")
        del old_id

    def test_a_failure_to_reconnect_is_said_and_the_recording_stays_on_screen(self):
        ctx = self.ctx
        ctx.cache["source_path"] = os.path.join(self.tmp, "gone")
        ctx.engine.restart()
        errors = []
        with mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=None), mock.patch.object(common, "show_error", lambda c, m: errors.append(m)):
            common.reconnect_recording(ctx)
        self.assertFalse(ctx._reconnecting)
        self.assertIn("could not be reconnected", errors[0])
        self.assertIn("Use Reload", errors[0])
        self.assertIsNotNone(ctx.cache)
        with self.assertRaises(BackendError):
            recording_ref(ctx)                                                                   # an analysis says to reload, as it always did

    def test_nothing_is_reconnected_when_no_recording_is_open(self):
        ctx = self.ctx
        ctx.cache, ctx.recording_id = None, None
        with mock.patch.object(common, "run_engine") as asked:
            common.reconnect_recording(ctx)
        asked.assert_not_called()

    def test_the_options_a_recording_was_opened_with_are_asked_for_again(self):
        ctx = self.ctx
        ctx.recording_load = {"regression_method": "huber"}
        with mock.patch.object(common, "run_engine") as asked:
            common.reconnect_recording(ctx)
        params = asked.call_args[0][2]
        self.assertTrue(ctx.recording_pipeline)                                                  # (the recording on screen was made with these)
        self.assertEqual(params["load"], {"regression_method": "huber", "pipeline": ctx.recording_pipeline})
        self.assertEqual((params["path"], params["fresh"]), (ctx.cache["source_path"], False))
        self.assertIsNone(ctx.recording_generation)                                              # until it is back, an analysis is told so
        ctx._reconnecting = False

    def test_a_recording_with_no_options_known_asks_for_none(self):
        ctx = self.ctx
        ctx.recording_load = {"regression_method": "huber"}
        ctx.recording_pipeline = {}
        with mock.patch.object(common, "run_engine") as asked:
            common.reconnect_recording(ctx)
        self.assertEqual(asked.call_args[0][2]["load"], {"regression_method": "huber"})
        ctx._reconnecting = False



class TestTheLoadOptionsAreRemembered(WindowCase):
    def test_opening_a_recording_remembers_how_it_was_opened(self):
        ctx = self.ctx
        serial = ctx.recording_serial
        with mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=None):
            common.open_recording(ctx, self.folder, load={"regression_method": "ransac"}, label="Loading")
        self.assertEqual(ctx.recording_load, {"regression_method": "ransac"})
        self.assertEqual(ctx.recording_method, "ransac")
        self.assertEqual(ctx.recording_serial, serial + 1)                                       # another recording (analysis windows from the old one go)


if __name__ == "__main__":
    unittest.main()
