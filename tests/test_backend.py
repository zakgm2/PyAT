"""The way to the analysis code (backend/): the engine as a child process and as a thread, requests and their progress, errors that say what
they are, an engine that dies and starts again, one-shot runs of the command line, and the recording the window maps from the engine's files.
The engine itself, and every operation, is tested in PyATCLI; these cover the app's side of the pipe."""

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np
from numpy.testing import assert_array_equal

import PyATCLI as pl
from PyATCLI.engine import store as engine_store

from physicsanalysis_qt.backend import BackendError, CliRun, EngineClient, run_cli, thread_engine
from physicsanalysis_qt.backend import recordings
from physicsanalysis_qt.backend.engine_client import ProcessTransport

from tests.recordings import make_tdt_folder, patch_tdt_reader, write_csv, write_oxysoft


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name
        self.csv = os.path.join(self.tmp, "table.csv")
        self.oxy = os.path.join(self.tmp, "session.txt")
        write_csv(self.csv)
        write_oxysoft(self.oxy)

    def engine(self):
        engine = thread_engine()
        self.addCleanup(engine.shutdown)
        return engine


class TestThreadEngine(Case):
    def test_it_says_what_it_can_do(self):
        engine = self.engine()
        ready = engine.wait_ready(30)
        self.assertEqual(ready["protocol"], 1)
        self.assertIn("recording.open", engine.operations)
        self.assertTrue(engine.running)

    def test_a_request_gets_its_progress_and_its_result(self):
        engine = self.engine()
        seen = []
        request = engine.request("recording.open", {"path": self.oxy}, on_progress=lambda f, m: seen.append((f, m)))
        wired = request.result(30)
        self.assertEqual(wired["path"], self.oxy)
        self.assertEqual(wired["splices"], [])
        self.assertTrue(seen)
        self.assertEqual(seen[-1][0], 1.0)
        self.assertEqual([f for f, _ in seen], sorted(f for f, _ in seen))                  # progress never goes back

    def test_what_comes_back_is_the_recording_with_its_arrays_mapped(self):
        engine = self.engine()
        opened = recordings.opened_from_wire(engine.call("recording.open", {"path": self.oxy}, timeout=30))
        reference = pl.load_recording(self.oxy)["cache"]
        self.assertEqual((opened.cache["source"], opened.cache["fs"]), ("Oxysoft", reference["fs"]))
        assert_array_equal(opened.cache["x"], reference["x"])
        assert_array_equal(opened.cache["o2hb"], reference["o2hb"])
        self.assertIsInstance(opened.cache["x"], np.memmap)
        opened.cache["x"][0] = -1.0                                                          # an edit stays in the window
        again = recordings.opened_from_wire(engine.call("recording.open", {"path": self.oxy}, timeout=30))
        self.assertEqual(again.cache["x"][0], reference["x"][0])

    def test_a_tdt_recording_gets_its_display_colours(self):
        patcher = patch_tdt_reader()
        self.addCleanup(patcher.stop)
        folder = make_tdt_folder(self.tmp, "Rat7-250101-101010")
        opened = recordings.opened_from_wire(self.engine().call("recording.open", {"path": folder}, timeout=30))
        self.assertEqual(set(opened.cache["signals"]), {"normalized", "main_driver", "isosbestic"})
        for key, sig in opened.cache["signals"].items():
            self.assertTrue(sig["color"], key)
        self.assertIs(opened.cache["corr"], opened.cache["signals"]["normalized"]["y"])

    def test_opening_hands_over_what_the_saved_state_restored(self):
        pl.saved_state.add_marker(self.oxy, 5.0, label="Lever")
        pl.saved_state.add_splice(self.oxy, "cut_out", 10.0, 20.0)
        opened = recordings.opened_from_wire(self.engine().call("recording.open", {"path": self.oxy}, timeout=30))
        self.assertEqual(opened.splices, [{"mode": "cut_out", "start": 10.0, "end": 20.0}])
        self.assertEqual(opened.restored["markers"], 1)
        self.assertIsNotNone(opened.original_cache)
        self.assertGreater(len(opened.original_cache["x"]), len(opened.cache["x"]))

    def test_an_error_says_what_it_is(self):
        engine = self.engine()
        with self.assertRaises(BackendError) as caught:
            engine.call("recording.open", {"path": os.path.join(self.tmp, "nope.txt")}, timeout=30)
        self.assertEqual(caught.exception.code, "not_found")
        self.assertIn("nope.txt", str(caught.exception))
        with self.assertRaises(BackendError) as caught:
            engine.call("no.such.operation", timeout=30)
        self.assertEqual(caught.exception.code, "unknown_operation")
        with self.assertRaises(BackendError) as caught:
            engine.call("recording.view", {"id": "r99"}, timeout=30)
        self.assertEqual(caught.exception.code, "no_recording")
        self.assertTrue(caught.exception.hint)
        self.assertIn(caught.exception.hint, str(caught.exception))
        self.assertTrue(engine.running)                                                       # one request's error is not the engine's end

    def test_things_json_cannot_hold_are_refused_before_they_are_sent(self):
        with self.assertRaises(BackendError) as caught:
            self.engine().call("recording.open", {"path": object()}, timeout=30)
        self.assertEqual(caught.exception.code, "bad_parameter")

    def test_numpy_values_and_paths_are_sent_as_numbers_and_text(self):
        engine = self.engine()
        opened = engine.call("recording.open", {"path": __import__("pathlib").Path(self.oxy)}, timeout=30)
        spliced = engine.call("recording.splice", {"id": opened["id"], "mode": "cut_out", "start": np.float64(10.0), "end": np.float32(20.0),
                                                   "markers": [{"time": np.float64(5.0), "label": "a"}, {"time": 50.0, "label": "b"}]}, timeout=30)
        self.assertEqual(spliced["splices"], [{"mode": "cut_out", "start": 10.0, "end": 20.0}])
        self.assertEqual([m["label"] for m in spliced["markers"]], ["a", "b"])
        self.assertEqual(spliced["markers"][0]["time"], 5.0)                                  # before the cut: where it was
        self.assertLess(spliced["markers"][1]["time"], 50.0)                                  # after it: moved up by the 10 s cut out

    def test_requests_are_answered_in_order(self):
        engine = self.engine()
        first = engine.request("recording.open", {"path": self.oxy})
        second = engine.request("recording.list")
        third = engine.request("kinds")
        self.assertEqual(first.result(30)["id"], "r1")
        self.assertEqual(second.result(30)["open"][0]["id"], "r1")                           # it was open by the time the list was asked
        self.assertTrue(third.result(30))

    def test_a_request_can_be_cancelled_while_it_runs(self):
        engine = self.engine()
        started = threading.Event()

        def slow_load(path, progress=None, **options):
            for _ in range(2000):
                started.set()
                progress(0.1, "reading")                                                     # raises Cancelled once the engine was asked to stop
                time.sleep(0.005)
            raise AssertionError("never cancelled")

        with mock.patch.object(engine_store, "load_recording", slow_load):
            request = engine.request("recording.open", {"path": self.oxy})
            self.assertTrue(started.wait(30))
            request.cancel()
            with self.assertRaises(BackendError) as caught:
                request.result(30)
        self.assertTrue(caught.exception.cancelled)
        self.assertEqual(engine.call("recording.list", timeout=30), {"open": []})            # nothing was left half open

    def test_listeners_that_fail_do_not_end_the_engine(self):
        engine = self.engine()

        def bad(fraction, message):
            raise RuntimeError("a bug in the window")

        self.assertTrue(engine.request("recording.open", {"path": self.oxy}, on_progress=bad).result(30))
        self.assertTrue(engine.running)

    def test_requests_racing_the_engine_ending_all_get_an_answer(self):
        engine = self.engine()
        engine.wait_ready(30)
        requests, started = [], threading.Event()

        def spam():
            started.set()
            for _ in range(300):
                requests.append(engine.request("kinds"))

        thread = threading.Thread(target=spam)
        thread.start()
        started.wait(30)
        engine._link.transport.close_input()                                                # the engine ends (its input closes) mid-stream
        thread.join(60)
        self.assertFalse(thread.is_alive())
        for request in requests:
            request.future.exception(timeout=60)                                            # an answer or an error; never a hang

    def test_shutdown_ends_it_and_a_later_request_starts_another(self):
        engine = self.engine()
        engine.call("recording.open", {"path": self.oxy}, timeout=30)
        first = engine.generation
        engine.shutdown()
        self.assertFalse(engine.running)
        self.assertEqual(engine.call("recording.list", timeout=30), {"open": []})            # a new engine: the recording is gone
        self.assertEqual(engine.generation, first + 1)


class TestAsAProcess(Case):
    """The real thing: a second Python process, over its standard input and output."""

    def setUp(self):
        super().setUp()
        self.client = EngineClient(app_version="test")
        self.addCleanup(self.client.shutdown)

    def test_a_child_process_opens_a_recording_and_maps_it(self):
        ready = self.client.wait_ready()
        self.assertNotEqual(ready["pid"], os.getpid())
        self.assertEqual(ready["library"], pl.__version__)
        seen = []
        wired = self.client.call("recording.open", {"path": self.csv}, timeout=60, on_progress=lambda f, m: seen.append(f))
        opened = recordings.opened_from_wire(wired)
        reference = pl.load_recording(self.csv)["cache"]
        assert_array_equal(opened.cache["x"], reference["x"])
        assert_array_equal(opened.cache["y_columns"]["left"], reference["y_columns"]["left"])
        self.assertTrue(seen)

    def test_an_analysis_on_the_open_recording_by_its_id(self):
        wired = self.client.call("recording.open", {"path": self.csv}, timeout=60)
        opened = recordings.opened_from_wire(wired)
        result = self.client.call("run", {"kind": "auc_window", "recording": {"id": opened.id, "markers": []},
                                          "parameters": {"center_s": 10.0, "pre_s": 3.0, "post_s": 3.0}, "tables": "inline"}, timeout=60)
        self.assertEqual(result["kind"], "auc_window")
        self.assertTrue(result["tables"])

    def test_the_engine_dying_fails_what_waited_and_the_next_request_restarts_it(self):
        self.client.wait_ready()
        wired = self.client.call("recording.open", {"path": self.csv}, timeout=60)
        generation = self.client.generation
        self.client._link.transport.proc.kill()
        deadline = time.monotonic() + 20
        while self.client.running and time.monotonic() < deadline:
            time.sleep(0.05)
        with self.assertRaises(BackendError) as caught:
            self.client.call("recording.view", {"id": wired["id"]}, timeout=60)               # sent to a dead engine, or answered by the new one
        self.assertIn(caught.exception.code, ("engine_stopped", "no_recording"))
        self.assertEqual(self.client.call("recording.list", timeout=60), {"open": []})        # the new engine has nothing open
        self.assertEqual(self.client.generation, generation + 1)

    def test_an_engine_that_cannot_start_says_why(self):
        code = "import sys; sys.stderr.write('No module named PyATCLI' + chr(10))"
        client = EngineClient(lambda: ProcessTransport([sys.executable, "-c", code]))
        self.addCleanup(client.shutdown)
        with self.assertRaises(BackendError) as caught:
            client.call("kinds", timeout=60)
        self.assertEqual(caught.exception.code, "engine_unavailable")
        self.assertIn("No module named PyATCLI", str(caught.exception))


class TestOneShotRuns(Case):
    def test_a_command_gives_its_json_result(self):
        result = run_cli(["info"], timeout=60)
        self.assertEqual(result["library"], pl.__version__)
        self.assertEqual(result["protocol"], 1)

    def test_a_run_reports_progress_and_the_files_it_wrote(self):
        events = []
        out = os.path.join(self.tmp, "out")
        result = run_cli(["run", "auc_window", self.csv, "-p", "center_s=10", "-p", "pre_s=3", "-p", "post_s=3", "--out", out],
                         on_event=events.append, timeout=60)
        self.assertEqual(result["kind"], "auc_window")
        self.assertTrue(any(f.endswith(".provenance.json") for f in result["files"]))
        self.assertTrue(all(os.path.isfile(f) for f in result["files"]))
        self.assertIn("progress", {e["event"] for e in events})

    def test_a_failure_is_a_backend_error_with_the_clis_own_code(self):
        with self.assertRaises(BackendError) as caught:
            run_cli(["run", "auc_window", os.path.join(self.tmp, "nope.csv"), "-p", "center_s=1", "--out", self.tmp], timeout=60)
        self.assertEqual(caught.exception.code, "not_found")

    def test_a_bad_parameter_is_one_too(self):
        with self.assertRaises(BackendError) as caught:
            run_cli(["run", "auc_window", self.csv, "-p", "centre=30", "--out", self.tmp], timeout=60)
        self.assertEqual(caught.exception.code, "bad_parameter")

    def test_a_run_can_be_cancelled(self):
        sleeper = [sys.executable, "-c", "import time; time.sleep(120)"]
        with mock.patch("physicsanalysis_qt.backend.runner.library_command", return_value=sleeper):
            run = CliRun(["run"]).start()
            time.sleep(0.3)
            run.cancel()
            with self.assertRaises(BackendError) as caught:
                run.result(30)
        self.assertTrue(caught.exception.cancelled)

    def test_a_program_that_is_not_the_library_is_a_bad_reply_not_a_hang(self):
        with mock.patch("physicsanalysis_qt.backend.runner.library_command", return_value=[sys.executable, "-c", "print('hello')"]):
            with self.assertRaises(BackendError) as caught:
                run_cli(["info"], timeout=30)
        self.assertEqual(caught.exception.code, "bad_reply")


if __name__ == "__main__":
    unittest.main()
