"""background.run_engine: the Qt side of a request to the analysis engine — its answer and progress reach the GUI thread after the call has
returned, errors arrive as messages, one request at a time, a cancel, and the synchronous mode of the Options dialog."""

import os
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

from PyATCLI.engine import store as engine_store

from physicsanalysis_qt.app import background
from physicsanalysis_qt.app.toasts import ProgressToast
from physicsanalysis_qt.backend import thread_engine
from physicsanalysis_qt.context import AppState

from tests.recordings import write_csv


class FakeToast:
    def __init__(self):
        self.updates, self.finished = [], 0

    def update(self, fraction, message=""):
        self.updates.append((fraction, message))

    def finish(self, *_):
        self.finished += 1


class TestTheProgressToastEndsFull(unittest.TestCase):
    """A bar that vanishes at whatever it last showed looks like the action failed: one that reached 100% stays up for a moment."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.ctx = AppState(self.app)
        self.ctx.win = QWidget()
        self.ctx.win.resize(900, 600)
        self.addCleanup(self.ctx.win.deleteLater)

    def spin(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.005)

    def toast(self):
        toast = ProgressToast(self.ctx, "Fitting the curve", delay_ms=0)
        self.ctx._progress_toast = toast
        toast.start()
        toast.update(0.0, "Running curve fit")
        return toast

    def test_it_shows_100_percent_for_a_moment_and_then_goes(self):
        toast = self.toast()
        self.assertTrue(toast.snapshot()["visible"])
        toast.update(1.0, "Done")
        toast.finish()
        shown = toast.snapshot()
        self.assertTrue(shown["visible"])
        self.assertEqual((shown["percent"], shown["detail"]), ("100%", "Done"))
        self.spin(0.8)
        self.assertFalse(toast.snapshot()["visible"])
        self.assertIsNone(self.ctx._progress_toast)

    def test_one_that_did_not_get_there_goes_at_once(self):
        toast = self.toast()
        toast.update(0.4, "Working")
        toast.finish()
        self.assertFalse(toast.snapshot()["visible"])

    def test_finishing_twice_is_harmless(self):
        toast = self.toast()
        toast.update(1.0, "Done")
        toast.finish()
        toast.finish()
        self.spin(0.6)
        self.assertFalse(toast.snapshot()["visible"])


class RunEngineCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.csv = os.path.join(self._tmp.name, "table.csv")
        write_csv(self.csv)
        self.ctx = AppState(self.app)
        self.ctx.settings["background_loading"] = True
        self.ctx.win = QWidget()
        self.addCleanup(self.ctx.win.deleteLater)
        self.ctx._engine = thread_engine()
        self.addCleanup(self.ctx._engine.shutdown)
        self.got, self.failed, self.threads = [], [], []

    def ok(self, result):
        self.threads.append(threading.get_ident())
        self.got.append(result)

    def bad(self, message):
        self.threads.append(threading.get_ident())
        self.failed.append(message)

    def spin(self, done, timeout=30):
        end = time.monotonic() + timeout
        while not done() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertTrue(done(), "timed out waiting")


class TestRunEngine(RunEngineCase):
    def test_the_answer_comes_after_the_call_has_returned_on_the_gui_thread(self):
        request = background.run_engine(self.ctx, "recording.open", {"path": self.csv}, self.ok, self.bad)
        self.assertIsNotNone(request)
        self.assertEqual(self.got, [])                                                      # never inside the call
        self.spin(lambda: self.got or self.failed)
        self.assertEqual(self.failed, [])
        self.assertEqual(self.got[0]["path"], self.csv)
        self.assertEqual(self.threads, [threading.get_ident()])
        self.assertIsNone(self.ctx._bg_request)
        self.assertIsNone(self.ctx._bg_bridge)

    def test_a_request_started_while_the_previous_answer_is_on_its_way_is_not_forgotten(self):
        release = threading.Event()

        def slow(path, progress=None, **options):
            release.wait(30)
            raise ValueError("released")

        first = background.run_engine(self.ctx, "kinds", {}, self.ok, self.bad)
        first.result(30)                                                                    # answered by the engine, not yet delivered to the window
        with mock.patch.object(engine_store, "load_recording", slow):
            second = background.run_engine(self.ctx, "recording.open", {"path": self.csv}, self.ok, self.bad)
            self.assertIsNotNone(second)                                                    # the first is done: this is allowed
            self.spin(lambda: self.got)                                                     # the first answer reaches the window ...
            self.assertIs(self.ctx._bg_request, second)                                     # ... and does not make it forget the second
            self.assertIsNotNone(self.ctx._bg_bridge)
            release.set()
            self.spin(lambda: self.failed)
        self.assertEqual(self.failed, ["released"])
        self.assertIsNone(self.ctx._bg_request)
        self.assertIsNone(self.ctx._bg_bridge)

    def test_an_answer_that_is_already_in_still_waits_for_the_event_loop(self):
        self.ctx._engine.wait_ready(30)
        request = background.run_engine(self.ctx, "kinds", {}, self.ok, self.bad)
        request.result(30)                                                                  # the engine has answered
        self.assertEqual(self.got, [])                                                      # the window has not been told yet
        self.spin(lambda: self.got)

    def test_the_toast_follows_the_progress_and_goes_before_the_answer_is_handled(self):
        toast = FakeToast()
        order = []
        with mock.patch.object(background, "_new_toast", return_value=toast):
            background.run_engine(self.ctx, "recording.open", {"path": self.csv},
                                  lambda r: order.append(("success", toast.finished)), self.bad, label="Loading")
            self.spin(lambda: order)
        self.assertTrue(toast.updates)
        self.assertEqual(toast.updates[-1][0], 1.0)
        self.assertEqual(order, [("success", 1)])                                           # the toast was finished first

    def test_a_request_that_reports_no_progress_of_its_own_still_ends_the_toast_full(self):
        toast = FakeToast()
        with mock.patch.object(background, "_new_toast", return_value=toast):
            background.run_engine(self.ctx, "kinds", {}, self.ok, self.bad, label="Fitting the curve")
            self.spin(lambda: self.got)
        self.assertEqual(toast.updates[-1][0], 1.0)

    def test_a_failure_arrives_as_the_message_the_person_reads(self):
        background.run_engine(self.ctx, "recording.open", {"path": os.path.join(self._tmp.name, "nope.csv")}, self.ok, self.bad)
        self.spin(lambda: self.got or self.failed)
        self.assertEqual(self.got, [])
        self.assertIn("nope.csv", self.failed[0])
        self.assertIn("does not exist", self.failed[0])
        self.assertIsNone(self.ctx._bg_request)

    def test_a_failure_without_a_handler_is_not_an_error(self):
        background.run_engine(self.ctx, "no.such.operation", {}, self.ok)
        self.spin(lambda: self.ctx._bg_request is None and self.ctx._bg_bridge is None)

    def test_an_engine_that_cannot_start_is_a_failure_too(self):
        from physicsanalysis_qt.backend import BackendError, EngineClient

        def refuse():
            raise BackendError("no engine here", code="engine_unavailable")

        self.ctx._engine = EngineClient(refuse)
        background.run_engine(self.ctx, "kinds", {}, self.ok, self.bad)
        self.spin(lambda: self.failed)
        self.assertEqual(self.failed, ["no engine here"])

    def test_only_one_request_at_a_time(self):
        release = threading.Event()

        def slow(path, progress=None, **options):
            release.wait(30)
            raise ValueError("released")

        with mock.patch.object(engine_store, "load_recording", slow), mock.patch.object(background, "show_window_toast") as toast:
            first = background.run_engine(self.ctx, "recording.open", {"path": self.csv}, self.ok, self.bad)
            second = background.run_engine(self.ctx, "kinds", {}, self.ok, self.bad)
            self.assertIsNotNone(first)
            self.assertIsNone(second)
            self.assertIn("already running", toast.call_args[0][1])
            release.set()
            self.spin(lambda: self.failed)
        self.assertEqual(self.failed, ["released"])
        self.assertIsNotNone(background.run_engine(self.ctx, "kinds", {}, self.ok, self.bad))      # free again
        self.spin(lambda: self.got)

    def test_a_request_can_be_cancelled_and_that_is_a_toast_not_an_error_box(self):
        started = threading.Event()
        failures = []

        def slow(path, progress=None, **options):
            for _ in range(2000):
                started.set()
                progress(0.1, "reading")
                time.sleep(0.005)

        with mock.patch.object(engine_store, "load_recording", slow), mock.patch.object(background, "show_window_toast") as toast:
            background.run_engine(self.ctx, "recording.open", {"path": self.csv}, self.ok, self.bad, on_failure=failures.append)
            self.assertTrue(started.wait(30))
            self.assertTrue(background.cancel_running(self.ctx))
            self.spin(lambda: failures)
        self.assertEqual((self.got, self.failed), ([], []))
        self.assertTrue(failures[0].cancelled)
        toast.assert_called_with(self.ctx, "Cancelled")
        self.assertFalse(background.cancel_running(self.ctx))                               # nothing left to cancel

    def test_cancelling_without_a_failure_handler_never_reaches_on_error(self):
        started = threading.Event()

        def slow(path, progress=None, **options):
            for _ in range(2000):
                started.set()
                progress(0.1, "reading")
                time.sleep(0.005)

        with mock.patch.object(engine_store, "load_recording", slow), mock.patch.object(background, "show_window_toast"):
            background.run_engine(self.ctx, "recording.open", {"path": self.csv}, self.ok, self.bad)
            self.assertTrue(started.wait(30))
            background.cancel_running(self.ctx)
            self.spin(lambda: self.ctx._bg_request is None and self.ctx._bg_bridge is None)
        self.assertEqual((self.got, self.failed), ([], []))

    def test_a_caller_can_ask_for_the_error_itself(self):
        errors = []
        background.run_engine(self.ctx, "recording.open", {"path": os.path.join(self._tmp.name, "nope.csv")}, self.ok, on_failure=errors.append)
        self.spin(lambda: errors)
        self.assertEqual((errors[0].code, self.failed), ("not_found", []))


class TestRequestsBesideTheOneThePersonWaitsFor(RunEngineCase):
    """Save Changes and the provenance record beside an export (exclusive=False): neither held up by a running request nor holding one up."""

    def test_it_is_not_refused_while_an_exclusive_request_runs_and_does_not_block_the_next(self):
        release = threading.Event()

        def slow(path, progress=None, **options):
            release.wait(30)
            raise ValueError("released")

        with mock.patch.object(engine_store, "load_recording", slow), mock.patch.object(background, "show_window_toast") as toast:
            first = background.run_engine(self.ctx, "recording.open", {"path": self.csv}, self.ok, self.bad)
            beside = background.run_engine(self.ctx, "kinds", {}, self.ok, self.bad, exclusive=False)
            self.assertIsNotNone(first)
            self.assertIsNotNone(beside)
            toast.assert_not_called()                                                       # nothing was refused
            self.assertIs(self.ctx._bg_request, first)                                      # and the one the person waits for is still that
            release.set()
            self.spin(lambda: self.got and self.failed)
        self.assertEqual(self.failed, ["released"])
        self.assertEqual(len(self.got), 1)
        self.assertEqual(self.ctx._bg_extra, set())

    def test_an_exclusive_request_is_not_refused_because_one_runs_beside_it(self):
        release = threading.Event()

        def slow(path, progress=None, **options):
            release.wait(30)
            raise ValueError("released")

        with mock.patch.object(engine_store, "load_recording", slow):
            background.run_engine(self.ctx, "recording.open", {"path": self.csv}, self.ok, self.bad, exclusive=False)
            exclusive = background.run_engine(self.ctx, "kinds", {}, self.ok, self.bad)
            self.assertIsNotNone(exclusive)                                                 # (it waits its turn in the engine, not in the window)
            release.set()
            self.spin(lambda: self.got and self.failed)

    def test_escape_cancels_what_is_waited_for_not_what_runs_beside_it(self):
        started = threading.Event()
        failures = []

        def slow(path, progress=None, **options):
            for _ in range(2000):
                started.set()
                progress(0.1, "reading")
                time.sleep(0.005)

        with mock.patch.object(engine_store, "load_recording", slow), mock.patch.object(background, "show_window_toast"):
            background.run_engine(self.ctx, "recording.open", {"path": self.csv}, self.ok, self.bad, exclusive=False, on_failure=failures.append)
            self.assertTrue(started.wait(30))
            self.assertFalse(background.cancel_running(self.ctx))                           # nothing the person waits for is running
            self.ctx.engine.shutdown()                                                      # (stop the slow one the hard way)
            self.spin(lambda: failures)

    def test_its_failure_is_delivered_too(self):
        errors = []
        background.run_engine(self.ctx, "no.such.operation", {}, self.ok, errors.append, exclusive=False)
        self.spin(lambda: errors)
        self.assertIn("no.such.operation", errors[0])
        self.assertEqual(self.ctx._bg_extra, set())


class TestRunEngineSynchronously(RunEngineCase):
    def setUp(self):
        super().setUp()
        self.ctx.settings["background_loading"] = False

    def test_the_answer_is_in_before_the_call_returns(self):
        request = background.run_engine(self.ctx, "recording.open", {"path": self.csv}, self.ok, self.bad)
        self.assertEqual(len(self.got), 1)
        self.assertEqual(self.failed, [])
        self.assertIsNotNone(request)
        self.assertIsNone(self.ctx._bg_request)

    def test_progress_reaches_the_toast_on_this_thread(self):
        toast = FakeToast()
        with mock.patch.object(background, "_new_toast", return_value=toast):
            background.run_engine(self.ctx, "recording.open", {"path": self.csv}, self.ok, self.bad, label="Loading")
        self.assertTrue(toast.updates)
        self.assertEqual(toast.finished, 1)

    def test_a_failure_is_a_message_here_too(self):
        background.run_engine(self.ctx, "recording.open", {"path": os.path.join(self._tmp.name, "nope.csv")}, self.ok, self.bad)
        self.assertEqual(self.got, [])
        self.assertIn("does not exist", self.failed[0])


if __name__ == "__main__":
    unittest.main()
