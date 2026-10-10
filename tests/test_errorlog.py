"""The error log (app/errorlog.py): the session header, rotation, what never appears in the log (data, names), the
global exception hook and its dialog rules, the report, and detecting that the last run did not end properly —
including real child processes that crash."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd

import PyATCLI as pl

from physicsanalysis_qt.app import errorlog

ROOT = Path(__file__).resolve().parent.parent
HOME = str(Path.home())
SEP = os.sep


class LogCase(unittest.TestCase):
    """A started log in a temp folder, with the dialog replaced by a recorder; shut down afterwards."""

    settings = {"plot_engine": "matplotlib", "theme": "light", "regression_method": "ols", "background_loading": True,
                "decimate_max_points": 2000, "output_folder": ""}

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "logs"
        self.shown = []
        self.start()

    def start(self, **kw):
        errorlog.start(app_version="9.9.9", settings=dict(kw.pop("settings", self.settings)), log_dir=self.dir,
                       install_hooks=kw.pop("install_hooks", False))
        errorlog._S.dialog_fn = self.shown.append
        self.addCleanup(errorlog.shutdown)

    def text(self):
        errorlog._S.handler.flush()
        return (self.dir / errorlog.LOG_FILENAME).read_text(encoding="utf-8")


class TestHeader(LogCase):
    def test_every_session_starts_with_what_is_running(self):
        text = self.text()
        self.assertIn("PyAT session ", text)
        for needle in ("PyAT            9.9.9", f"PyATCLI  {pl.__version__}", sys.version.split()[0],
                       f"numpy {np.__version__}", "plot_engine=matplotlib", "regression_method=ols", "output folder not set",
                       "closed normally (or this is the first run)"):
            self.assertIn(needle, text, needle)
        self.assertIn("hidden: paths appear as <path-xxxxxx> tokens", text)

    def test_the_header_is_the_first_thing_in_the_file(self):
        self.assertTrue(self.text().startswith("=" * 72))

    def test_settings_that_could_hold_a_path_are_not_listed_by_value(self):
        errorlog.shutdown()
        self.start(settings={**self.settings, "output_folder": "C:/Users/someone/secret-study"})
        text = self.text()
        self.assertIn("output folder set", text)
        self.assertNotIn("secret-study", text)

    def test_the_header_is_written_again_after_the_file_rolls_over(self):
        errorlog.shutdown()
        with mock.patch.object(errorlog, "MAX_BYTES", 3000), mock.patch.object(errorlog, "BACKUP_COUNT", 2):
            self.start()
        for i in range(120):
            errorlog.action("filler", i=i)
        files = sorted(p.name for p in self.dir.glob("pyat.log*"))
        self.assertIn("pyat.log.1", files)
        self.assertLessEqual(len(files), 3)                                  # the live file and at most 2 backups
        head = (self.dir / "pyat.log").read_text(encoding="utf-8").splitlines()
        self.assertTrue(any("continued after log rotation" in line for line in head[:3]))
        self.assertTrue(any("PyATCLI" in line for line in head[:12]))      # the versions came with it


class TestRedaction(LogCase):
    def test_a_path_becomes_a_token_that_hides_every_name_in_it(self):
        out = errorlog.scrub(f"could not read C:{SEP}Users{SEP}alice{SEP}Desktop{SEP}Rat7-250101{SEP}data.tev")
        self.assertIn("<path-", out)
        for leaked in ("alice", "Rat7", "250101", "Desktop", "data.tev"):
            self.assertNotIn(leaked, out)

    def test_a_path_under_the_home_folder_does_not_leak_its_subfolders(self):
        """Shortening the home folder to ~ before tokenising would leave ~/Desktop/Subject-01 behind."""
        path = str(Path.home() / "Desktop" / "Subject-01" / "recording.tev")
        out = errorlog.scrub(f"failed: {path}")
        for leaked in ("Subject-01", "recording.tev", "Desktop"):
            self.assertNotIn(leaked, out)
        self.assertNotIn(Path.home().name, out)

    def test_the_same_path_always_gives_the_same_token_and_different_paths_differ(self):
        a1 = errorlog.scrub("C:\\data\\RatA\\f.tev")
        a2 = errorlog.scrub("opened C:\\data\\RatA\\f.tev again")
        b = errorlog.scrub("C:\\data\\RatB\\f.tev")
        token = a1
        self.assertIn(token, a2)
        self.assertNotEqual(a1, b)

    def test_the_token_cannot_be_reversed_by_guessing_because_it_is_salted_per_install(self):
        a = errorlog.scrub("C:\\data\\Rat7\\f.tev")
        errorlog.shutdown()
        other = Path(self._tmp.name) / "other-install"
        errorlog.start(app_version="1", settings=self.settings, log_dir=other, install_hooks=False)
        self.addCleanup(errorlog.shutdown)
        self.assertNotEqual(a, errorlog.scrub("C:\\data\\Rat7\\f.tev"))
        self.assertTrue((other / ".salt").exists())

    def test_posix_and_network_paths_are_covered(self):
        for p in ("/Users/alice/data/rat7", "/home/bob/lab/rat7", "/Volumes/Lab/rat7", "\\\\server\\share\\rat7\\f.tev"):
            with self.subTest(p):
                out = errorlog.scrub(f"bad {p} here")
                self.assertIn("<path-", out)
                self.assertNotIn("rat7", out)

    def test_a_recording_name_is_hidden_even_when_it_appears_bare_in_a_message(self):
        errorlog.register_recording("C:\\data\\Subject-0042-250101")
        out = errorlog.scrub("Could not read Subject-0042-250101: truncated")
        self.assertNotIn("Subject-0042", out)
        self.assertIn("<path-", out)
        self.assertIn("truncated", out)

    def test_a_file_is_hidden_by_its_name_with_or_without_the_extension(self):
        errorlog.register_recording("C:\\data\\Participant-Zed.xlsx")
        self.assertNotIn("Participant-Zed", errorlog.scrub("table from Participant-Zed.xlsx; sheet of Participant-Zed"))

    def test_a_very_short_name_is_not_registered_it_would_hide_half_the_log(self):
        errorlog.register_recording("C:\\data\\ab")
        self.assertEqual(errorlog.scrub("a table about abstract things"), "a table about abstract things")

    def test_with_names_included_paths_stay_and_only_the_home_folder_is_shortened(self):
        errorlog.configure({**self.settings, errorlog.SETTINGS_KEY_PATHS: True})
        path = str(Path.home() / "lab" / "Rat7")
        out = errorlog.scrub(f"opened {path}")
        self.assertIn("Rat7", out)
        self.assertNotIn(Path.home().name, out.replace("~", ""))
        self.assertIn("~", out)
        self.assertIn("included in this log", errorlog.build_header())

    def test_switching_the_option_is_itself_logged(self):
        errorlog.configure({**self.settings, errorlog.SETTINGS_KEY_PATHS: True})
        errorlog.configure({**self.settings, errorlog.SETTINGS_KEY_PATHS: False})
        self.assertIn("File and folder names in the log: included", self.text())
        self.assertIn("File and folder names in the log: hidden", self.text())

    def test_a_traceback_keeps_the_apps_own_frames_and_nothing_of_the_users_folders(self):
        tb = ('Traceback (most recent call last):\n'
              '  File "C:\\Users\\bob\\Desktop\\PyAT\\physicsanalysis_qt\\analysis\\peth.py", line 52, in launch\n'
              '    x = 1\n'
              '  File "C:\\Users\\bob\\AppData\\Local\\Python\\Lib\\site-packages\\numpy\\core\\x.py", line 9, in f\n'
              '  File "C:\\Users\\bob\\Desktop\\PyATCLI\\PyATCLI\\recording.py", line 3, in g\n'
              '  File "C:\\Users\\bob\\Documents\\my script.py", line 7, in <module>\n'
              'FileNotFoundError: [Errno 2] No such file: \'C:\\\\Users\\\\bob\\\\Rat7\\\\f.tev\'')
        out = errorlog.scrub_traceback(tb)
        self.assertIn('File "physicsanalysis_qt/analysis/peth.py", line 52, in launch', out)
        self.assertIn('File "site-packages/numpy/core/x.py", line 9, in f', out)
        self.assertIn('File "PyATCLI/recording.py", line 3, in g', out)      # not PyATCLI/PyATCLI/
        self.assertIn('File "my script.py", line 7, in <module>', out)
        for leaked in ("bob", "Rat7", "f.tev", "Desktop"):
            self.assertNotIn(leaked, out)

    def test_every_log_record_is_scrubbed_even_from_code_that_does_not_know_about_it(self):
        import logging
        logging.getLogger("some.library").warning("loading C:\\Users\\carol\\study\\Rat9\\x.csv")
        self.assertNotIn("carol", self.text())
        self.assertNotIn("Rat9", self.text())
        self.assertIn("<path-", self.text())


class TestNeverLogData(LogCase):
    def test_arrays_and_tables_are_described_by_shape_only(self):
        self.assertEqual(errorlog.describe(np.zeros((3, 4))), "<ndarray shape=(3, 4) dtype=float64>")
        self.assertEqual(errorlog.describe(np.array([123456.789, 9.0])), "<ndarray shape=(2,) dtype=float64>")
        self.assertEqual(errorlog.describe(pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})), "<DataFrame 3x2>")

    def test_lists_dicts_and_objects_are_sizes_not_contents(self):
        self.assertEqual(errorlog.describe([1.5, 2.5, 3.5, 4.5, 5.5]), "<list n=5>")
        self.assertEqual(errorlog.describe(list(range(1000))), "<list n=1000>")
        self.assertEqual(errorlog.describe({"a": 1, "b": 2}), "<dict n=2>")
        self.assertEqual(errorlog.describe({1, 2, 3}), "<set n=3>")
        self.assertEqual(errorlog.describe(object()), "<object>")

    def test_scalars_and_a_short_window_are_shown_as_they_are(self):
        self.assertEqual(errorlog.describe(None), "None")
        self.assertEqual(errorlog.describe(True), "True")
        self.assertEqual(errorlog.describe(300), "300")
        self.assertEqual(errorlog.describe(0.123456789), "0.123457")
        self.assertEqual(errorlog.describe(np.float32(2.5)), "2.5")
        self.assertEqual(errorlog.describe((-10, 20.5)), "(-10, 20.5)")

    def test_a_long_string_is_cut(self):
        out = errorlog.describe("x" * 500)
        self.assertLess(len(out), 70)
        self.assertTrue(out.endswith("...'"))

    def test_a_path_parameter_is_a_token_by_its_name_or_by_looking_like_one(self):
        self.assertIn("<path-", errorlog.describe("some folder", key="source_path"))
        self.assertIn("<path-", errorlog.describe("whatever", key="folder"))
        self.assertIn("<path-", errorlog.describe("C:\\data\\x"))

    def test_words_that_merely_contain_dir_or_source_are_not_paths(self):
        self.assertEqual(errorlog.describe("absolute", key="peak_direction"), "'absolute'")
        self.assertEqual(errorlog.describe("TDT", key="source"), "'TDT'")
        self.assertEqual(errorlog.describe("TDT", key="kind"), "'TDT'")

    def test_an_action_line_carries_its_parameters_and_no_data(self):
        samples = np.random.default_rng(0).normal(size=5000) + 123456.0
        errorlog.action("analysis", tool="Event PETH", pre_s=10.0, post_s=20.0, trace=samples,
                        events=list(np.arange(300.0)), source_path="C:\\data\\Rat7")
        line = next(l for l in self.text().splitlines() if "ACTION analysis" in l)
        self.assertIn("tool='Event PETH'", line)
        self.assertIn("pre_s=10", line)
        self.assertIn("trace=<ndarray shape=(5000,) dtype=float64>", line)
        self.assertIn("events=<list n=300>", line)
        self.assertNotIn("123456", line)
        self.assertNotIn("Rat7", line)

    def test_a_loaded_recording_is_logged_by_size_and_its_name_is_registered(self):
        cache = {"source": "TDT", "source_path": "C:\\data\\Subject-0042-250101", "x": np.arange(1000) / 100.0, "fs": 100.0}
        errorlog.recording_loaded(cache)
        line = next(l for l in self.text().splitlines() if "ACTION recording_loaded" in l)
        self.assertIn("kind='TDT'", line)
        self.assertIn("n_samples=1000", line)
        self.assertIn("duration_s=9.99", line)
        self.assertNotIn("Subject-0042", errorlog.scrub("then Subject-0042-250101 failed"))


class TestExceptionHook(LogCase):
    def raise_and_catch(self, exc=None):
        exc = exc or ValueError("bad value in C:\\Users\\dave\\lab\\Rat3\\x.tev")
        try:
            raise exc
        except Exception as e:                           # noqa: BLE001
            return type(e), e, e.__traceback__

    def test_an_unhandled_exception_is_logged_with_its_stack_and_shown_once(self):
        info = errorlog.handle_exception(*self.raise_and_catch())
        text = self.text()
        self.assertIn("CRITICAL", text)
        self.assertIn("Unhandled exception in main thread", text)
        self.assertIn("ValueError", text)
        self.assertIn("raise_and_catch", text)
        for leaked in ("dave", "Rat3"):
            self.assertNotIn(leaked, text)
        self.assertEqual(self.shown, [info])
        self.assertEqual((info.type, info.source), ("ValueError", "main thread"))
        self.assertNotIn("dave", info.message)

    def test_a_report_file_is_written_even_if_no_dialog_could_be_shown(self):
        errorlog.handle_exception(*self.raise_and_catch(), show=False)
        report = (self.dir / errorlog.LAST_REPORT_FILENAME).read_text(encoding="utf-8")
        self.assertIn("PyAT problem report", report)
        self.assertIn("ValueError", report)
        self.assertEqual(self.shown, [])

    def test_the_same_error_again_is_logged_but_does_not_open_a_second_dialog(self):
        for _ in range(5):
            try:
                raise KeyError("x")
            except KeyError as e:
                errorlog.handle_exception(KeyError, e, e.__traceback__)
        self.assertEqual(len(self.shown), 1)
        self.assertEqual(self.text().count("Unhandled exception"), 5)
        self.assertIn("error dialog not shown", self.text())

    def test_at_most_three_dialogs_a_minute_and_then_again(self):
        def info(i):
            return errorlog.ErrorInfo("E", "m", "t", "s", f"sig{i}")
        self.assertEqual([errorlog._should_show(info(i), now=100.0 + i) for i in range(5)], [True, True, True, False, False])
        self.assertTrue(errorlog._should_show(info(9), now=100.0 + errorlog.DIALOG_WINDOW_S + 5))

    def test_the_same_error_may_show_again_after_a_quiet_spell(self):
        a = errorlog.ErrorInfo("E", "m", "t", "s", "same")
        self.assertTrue(errorlog._should_show(a, now=0.0))
        self.assertFalse(errorlog._should_show(a, now=errorlog.SAME_ERROR_QUIET_S - 1))
        self.assertTrue(errorlog._should_show(a, now=errorlog.SAME_ERROR_QUIET_S * 3))

    def test_no_second_dialog_while_one_is_open(self):
        errorlog._S.dialog_open = True
        self.assertFalse(errorlog._should_show(errorlog.ErrorInfo("E", "m", "t", "s", "x"), now=0.0))

    def test_a_failure_inside_the_hook_never_escapes_it(self):
        errorlog._S.dialog_fn = mock.Mock(side_effect=RuntimeError("dialog broke"))
        with mock.patch("physicsanalysis_qt.app.errorlog.traceback.print_exc"):          # the hook's last-resort print
            self.assertIsNone(errorlog.handle_exception(*self.raise_and_catch()))   # swallowed, not raised

    def test_the_hook_replaces_sys_excepthook_and_shutdown_puts_it_back(self):
        original = sys.excepthook
        errorlog.shutdown()
        self.start(install_hooks=True)
        self.assertIsNot(sys.excepthook, original)
        sys.excepthook(*self.raise_and_catch(RuntimeError("through the hook")))
        self.assertEqual(self.shown[-1].message, "through the hook")
        errorlog.shutdown()
        self.assertIs(sys.excepthook, original)

    def test_ctrl_c_goes_to_the_default_hook(self):
        errorlog.shutdown()
        self.start(install_hooks=True)
        with mock.patch.object(sys, "__excepthook__") as default:
            sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        default.assert_called_once()
        self.assertEqual(self.shown, [])

    def test_an_exception_in_a_worker_thread_is_caught_too(self):
        errorlog.shutdown()
        self.start(install_hooks=True)

        def boom():
            raise OSError("thread failure")

        t = threading.Thread(target=boom, name="loader-thread")
        t.start()
        t.join()
        self.assertEqual(self.shown[-1].type, "OSError")
        self.assertEqual(self.shown[-1].source, "thread loader-thread")

    def test_an_exception_a_worker_turns_into_a_message_still_leaves_its_traceback(self):
        try:
            raise ValueError("a load failed")
        except ValueError as e:
            errorlog.report_caught(type(e), e, e.__traceback__, "background task 'Loading TDT folder'")
        text = self.text()
        self.assertIn("Error in background task 'Loading TDT folder': a load failed", text)
        self.assertIn("test_an_exception_a_worker_turns_into_a_message", text)
        self.assertEqual(self.shown, [])                                      # no dialog: the user already gets a message

    def test_show_error_logs_the_message_with_the_traceback_that_is_in_flight(self):
        from physicsanalysis_qt.app import toasts
        ctx = type("C", (), {"win": None})()
        with mock.patch.object(toasts.QMessageBox, "critical") as box:
            try:
                raise ValueError("inside an except block")
            except ValueError:
                toasts.show_error(ctx, "Could not do the thing")
        box.assert_called_once()
        self.assertIn("ERROR", self.text())
        self.assertIn("Could not do the thing", self.text())
        self.assertIn("ValueError: inside an except block", self.text())


class TestReport(LogCase):
    def test_a_report_has_the_versions_the_error_and_the_recent_log(self):
        errorlog.action("splice", mode="cut_out", start_s=5.0, end_s=8.0)
        try:
            raise ZeroDivisionError("division by zero")
        except ZeroDivisionError as e:
            info = errorlog.handle_exception(type(e), e, e.__traceback__)
        report = errorlog.build_report(info)
        for needle in ("PyAT problem report", "does not hold your", "PyAT            9.9.9", f"PyATCLI  {pl.__version__}",
                       "--- The error", "ZeroDivisionError: division by zero", "--- Recent log",
                       "ACTION splice mode='cut_out' start_s=5 end_s=8"):
            self.assertIn(needle, report, needle)

    def test_a_report_saved_on_request_says_there_was_no_error(self):
        self.assertIn("No error is attached", errorlog.build_report())

    def test_only_this_sessions_log_is_in_it(self):
        errorlog.action("old_session_action")
        errorlog.shutdown()
        self.start()
        errorlog.action("new_session_action")
        report = errorlog.build_report()
        self.assertIn("new_session_action", report)
        self.assertNotIn("old_session_action", report)

    def test_the_recent_log_is_capped(self):
        for i in range(500):
            errorlog.action("filler", i=i)
        report = errorlog.build_report(max_log_lines=50)
        self.assertLess(report.count("ACTION filler"), 60)
        self.assertIn("i=499", report)

    def test_no_name_survives_into_a_report(self):
        errorlog.register_recording("C:\\data\\Subject-0042-250101")
        errorlog.action("open", source_path="C:\\data\\Subject-0042-250101")
        try:
            raise FileNotFoundError("No such file: C:\\data\\Subject-0042-250101\\x.tev")
        except FileNotFoundError as e:
            info = errorlog.handle_exception(type(e), e, e.__traceback__)
        report = errorlog.build_report(info)
        self.assertNotIn("Subject-0042", report)
        self.assertNotIn("250101", report)
        self.assertIn("hidden", report)

    def test_save_report_writes_the_file_and_logs_it(self):
        path = Path(self._tmp.name) / "r.txt"
        self.assertEqual(errorlog.save_report(str(path)), str(path))
        self.assertIn("PyAT problem report", path.read_text(encoding="utf-8"))
        self.assertIn("ACTION save_report", self.text())


class TestPreviousRun(LogCase):
    def test_a_normal_exit_leaves_nothing_to_report_next_time(self):
        errorlog.mark_clean_exit()
        errorlog.shutdown()
        self.start()
        self.assertFalse(errorlog._S.previous["crashed"])
        self.assertIn("Session ended normally", (self.dir / "pyat.log").read_text(encoding="utf-8"))

    def test_a_session_that_never_marked_its_exit_is_reported_next_time(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        (self.dir / f"session-{dead.pid}.lock").write_text(json.dumps({"pid": dead.pid, "session": "deadbeef"}), encoding="utf-8")
        errorlog.shutdown()
        self.start()
        self.assertTrue(errorlog._S.previous["crashed"])
        self.assertIn("did not close normally", errorlog.build_header())
        self.assertIn("The previous run did not close normally", errorlog.build_report())
        self.assertFalse((self.dir / f"session-{dead.pid}.lock").exists())      # cleared, so it is reported once

    def test_another_running_pyat_is_not_mistaken_for_a_crash(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(lambda: (child.kill(), child.wait()))
        (self.dir / f"session-{child.pid}.lock").write_text(json.dumps({"pid": child.pid}), encoding="utf-8")
        errorlog.shutdown()
        self.start()
        self.assertFalse(errorlog._S.previous["crashed"])
        self.assertTrue((self.dir / f"session-{child.pid}.lock").exists())      # left alone

    def test_a_native_crash_file_is_reported_scrubbed_and_archived(self):
        errorlog.shutdown()
        (self.dir / errorlog.NATIVE_FILENAME).write_text(
            'Windows fatal exception: access violation\n\nCurrent thread 0x1 (most recent call first):\n'
            '  File "C:\\Users\\erin\\AppData\\Local\\Python\\Lib\\site-packages\\pyqtgraph\\GraphicsScene.py", line 12 in draw\n'
            '  File "C:\\Users\\erin\\Desktop\\PyAT\\physicsanalysis_qt\\pg_engine.py", line 88 in render\n', encoding="utf-8")
        self.start()
        prev = errorlog._S.previous
        self.assertTrue(prev["crashed"])
        self.assertIn("access violation", prev["native"])
        self.assertIn("physicsanalysis_qt/pg_engine.py", prev["native"])
        self.assertNotIn("erin", prev["native"])
        self.assertEqual(len(list(self.dir.glob("native_crash.*.log"))), 1)
        report = errorlog.build_report()
        self.assertIn("Native crash (from faulthandler)", report)
        self.assertIn("native crash was recorded", errorlog.build_header())

    def test_only_the_newest_native_crash_archives_are_kept(self):
        errorlog.shutdown()
        for i in range(1, 7):
            (self.dir / f"native_crash.2026010{i}-000000.log").write_text(f"old crash {i}", encoding="utf-8")
        (self.dir / errorlog.NATIVE_FILENAME).write_text("the newest crash", encoding="utf-8")
        self.start()
        kept = sorted(p.name for p in self.dir.glob("native_crash.*.log"))
        self.assertEqual(len(kept), errorlog.KEEP_NATIVE_ARCHIVES)
        self.assertIn("the newest crash", (self.dir / kept[-1]).read_text(encoding="utf-8"))      # this one sorts last

    def test_process_liveness(self):
        self.assertTrue(errorlog._pid_alive(os.getpid()))
        self.assertFalse(errorlog._pid_alive(0))
        self.assertFalse(errorlog._pid_alive(-5))
        done = subprocess.Popen([sys.executable, "-c", "pass"])
        done.wait()
        self.assertFalse(errorlog._pid_alive(done.pid))


class TestStandardStreams(LogCase):
    def test_a_missing_stderr_is_replaced_so_stray_prints_reach_the_log(self):
        errorlog.shutdown()
        real = sys.stderr
        sys.stderr = None
        try:
            self.start(install_hooks=True)
            print("something went wrong in a library", file=sys.stderr)
            self.assertIn("stderr: something went wrong in a library", self.text())
            errorlog.shutdown()
            self.assertIsNone(sys.stderr)
        finally:
            sys.stderr = real


class TestQtSide(LogCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_the_dialog_is_raised_on_the_gui_thread_even_from_a_worker(self):
        errorlog._S.dialog_fn = None
        errorlog.attach_app(self.app)
        main = threading.get_ident()
        seen = []
        errorlog._dispatch(lambda: seen.append(threading.get_ident()))             # from the GUI thread
        t = threading.Thread(target=lambda: errorlog._dispatch(lambda: seen.append(threading.get_ident())))
        t.start()
        t.join()
        for _ in range(50):
            self.app.processEvents()
            if len(seen) == 2:
                break
        self.assertEqual(seen, [main, main])
        errorlog._S.dispatcher = None

    def test_qt_warnings_go_to_the_log_and_a_repeated_one_is_summarised(self):
        from PyQt6.QtCore import QtMsgType
        errorlog._qt_message(QtMsgType.QtDebugMsg, None, "chatter")
        for _ in range(8):
            errorlog._qt_message(QtMsgType.QtWarningMsg, None, "QFont::setPointSize: Point size <= 0 (0)")
        errorlog._qt_message(QtMsgType.QtCriticalMsg, None, "something else")
        text = self.text()
        self.assertNotIn("chatter", text)
        self.assertEqual(text.count("Qt: QFont::setPointSize"), 1)
        self.assertIn("previous message repeated 7 more times", text)
        self.assertIn("ERROR", text)

    def test_save_report_dialog_writes_where_the_user_chose(self):
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        target = str(Path(self._tmp.name) / "chosen.txt")
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(target, "")), \
                mock.patch.object(QMessageBox, "exec", return_value=0):
            self.assertEqual(errorlog.save_report_dialog(None), target)
        self.assertIn("PyAT problem report", Path(target).read_text(encoding="utf-8"))

    def test_cancelling_the_dialog_saves_nothing(self):
        from PyQt6.QtWidgets import QFileDialog
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=("", "")):
            self.assertIsNone(errorlog.save_report_dialog(None))

    def test_the_offer_after_a_bad_exit_is_only_made_when_there_was_one(self):
        from PyQt6.QtWidgets import QMessageBox
        with mock.patch.object(QMessageBox, "exec", return_value=0) as ex:
            self.assertFalse(errorlog.offer_previous_report(None))
            ex.assert_not_called()
            errorlog._S.previous = {"crashed": True, "native": "", "sessions": []}
            self.assertTrue(errorlog.offer_previous_report(None))
            ex.assert_called_once()

    def engine_ctx(self):
        """What run_engine needs of a window, waiting for the engine's answer right there, with the engine on a thread of this process."""
        import types
        from physicsanalysis_qt.backend import thread_engine
        ctx = types.SimpleNamespace(settings={"background_loading": False}, _bg_request=None, _bg_bridge=None, engine=thread_engine(), win=None)
        self.addCleanup(ctx.engine.shutdown)
        return ctx

    def test_a_failed_engine_request_is_logged_with_what_was_asked_and_why(self):
        from physicsanalysis_qt.app import background
        failures = []
        with mock.patch.object(background, "_new_toast", return_value=None):
            background.run_engine(self.engine_ctx(), "recording.open", {"path": str(Path(self._tmp.name) / "nope")}, lambda r: None,
                                  failures.append, label="Loading TDT folder")
        self.assertEqual(len(failures), 1)
        self.assertIn("does not exist", failures[0])
        self.assertIn("ACTION task_started label='Loading TDT folder'", self.text())
        self.assertIn("Error in engine request 'recording.open':", self.text())

    def test_a_successful_task_is_logged_with_how_long_it_took(self):
        from physicsanalysis_qt.app import background
        done = []
        with mock.patch.object(background, "_new_toast", return_value=None):
            background.run_engine(self.engine_ctx(), "kinds", {}, done.append, label="Splice")
        self.assertEqual(len(done), 1)
        self.assertIn("ACTION task_finished label='Splice' seconds=", self.text())

    def test_an_export_is_logged_by_file_type_and_never_by_name(self):
        from physicsanalysis_qt.context import export_file
        out = Path(self._tmp.name) / "exports"
        out.mkdir()
        ctx = type("C", (), {"settings": {}, "cache": None, "win": None})()
        with mock.patch("physicsanalysis_qt.app.toasts.show_window_toast"):
            export_file(ctx, None, "Export", "Subject-0042 PETH.png", "PNG (*.png)", lambda p: Path(p).write_bytes(b"x"),
                        dest_dir=str(out))
        line = next(l for l in self.text().splitlines() if "ACTION export" in l)
        self.assertIn("file_type='png'", line)
        self.assertNotIn("Subject-0042", line)


# ---------------------------------------------------------------------------------------------------------------
# Real processes: the crashes the hook exists for
# ---------------------------------------------------------------------------------------------------------------

CHILD_PRELUDE = textwrap.dedent("""
    import sys
    sys.path.insert(0, {root!r})
    from physicsanalysis_qt.app import errorlog
    errorlog.start(app_version="9.9.9", settings={{}}, log_dir={log_dir!r})
    errorlog._S.dialog_fn = lambda info: None          # a real dialog would block a child with no one to click it
""")


class TestRealProcesses(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name) / "logs"

    def run_child(self, body, timeout=60):
        code = CHILD_PRELUDE.format(root=str(ROOT), log_dir=str(self.dir)) + textwrap.dedent(body)
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=timeout)

    def test_an_unhandled_exception_is_logged_and_leaves_a_report_instead_of_vanishing(self):
        r = self.run_child("""
            errorlog.action("opened", source_path="C:\\\\data\\\\Rat7")
            raise RuntimeError("the app would have closed silently here")
        """)
        self.assertNotEqual(r.returncode, 0)
        log = (self.dir / "pyat.log").read_text(encoding="utf-8")
        self.assertIn("RuntimeError: the app would have closed silently here", log)
        self.assertIn("Unhandled exception in main thread", log)
        self.assertNotIn("Rat7", log)
        report = (self.dir / errorlog.LAST_REPORT_FILENAME).read_text(encoding="utf-8")
        self.assertIn("RuntimeError", report)
        self.assertIn("PyAT            9.9.9", report)

    def test_a_clean_run_leaves_no_stale_lock_and_the_next_start_sees_a_normal_exit(self):
        self.run_child("errorlog.action('did something')")
        self.assertEqual(list(self.dir.glob("session-*.lock")), [])
        errorlog.start(app_version="1", settings={}, log_dir=self.dir, install_hooks=False)
        try:
            self.assertFalse(errorlog._S.previous["crashed"])
        finally:
            errorlog.shutdown()

    def test_a_run_that_dies_without_closing_is_found_on_the_next_start(self):
        self.run_child("""
            import os
            errorlog.action('about to be killed')
            os._exit(3)                                     # no atexit, no cleanup: like a kill or a power cut
        """)
        self.assertEqual(len(list(self.dir.glob("session-*.lock"))), 1)
        errorlog.start(app_version="1", settings={}, log_dir=self.dir, install_hooks=False)
        try:
            self.assertTrue(errorlog._S.previous["crashed"])
            self.assertIn("about to be killed", (self.dir / "pyat.log").read_text(encoding="utf-8"))
        finally:
            errorlog.shutdown()

    def test_a_crash_in_native_code_is_written_by_faulthandler_and_reported_next_time(self):
        r = self.run_child("""
            import faulthandler, sys
            if sys.platform.startswith("win"):
                import ctypes
                ctypes.windll.kernel32.SetErrorMode(0x8003)  # no "stopped working" dialog from Windows
            errorlog.action('about to crash natively')
            faulthandler._sigsegv()
        """, timeout=90)
        self.assertNotEqual(r.returncode, 0)
        native = (self.dir / errorlog.NATIVE_FILENAME).read_text(encoding="utf-8", errors="replace")
        self.assertRegex(native, r"(?i)fatal|access violation|segmentation")
        errorlog.start(app_version="1", settings={}, log_dir=self.dir, install_hooks=False)
        try:
            self.assertTrue(errorlog._S.previous["crashed"])
            self.assertRegex(errorlog._S.previous["native"], r"(?i)fatal|access violation|segmentation")
            self.assertIn("Native crash (from faulthandler)", errorlog.build_report())
        finally:
            errorlog.shutdown()


if __name__ == "__main__":
    unittest.main()
