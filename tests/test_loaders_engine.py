"""Opening a recording through the analysis engine: the loaders (TDT folder, Oxysoft export, generic table) in the real main window
(offscreen), with the engine running on a thread of the test process. What the window shows after a load is what the library's
load_recording gives a script, with the recording's saved changes on it — and the window is told so the way it always was."""

import os
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtWidgets import QApplication

import PyATCLI as pl

from physicsanalysis_qt.edit import undo
from physicsanalysis_qt.backend.errors import BackendError
from physicsanalysis_qt.backend.recordings import recording_ref
from physicsanalysis_qt.context import AppState
from physicsanalysis_qt.loading import common, generic, oxysoft, tdt
from physicsanalysis_qt.ui import toolbar
from physicsanalysis_qt.ui.main_window import build_main_window

from tests.recordings import make_tdt_folder, patch_tdt_reader, write_csv, write_oxysoft


class LoaderCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name
        patcher = patch_tdt_reader()
        self.addCleanup(patcher.stop)
        self.ctx = AppState(self.app)
        self.ctx.settings["background_loading"] = True
        build_main_window(self.ctx)
        self.addCleanup(self.ctx.win.close)
        self.addCleanup(lambda: self.ctx.engine.shutdown())
        self.toasts, self.errors = [], []
        for module in (common, tdt, oxysoft, generic):
            if hasattr(module, "show_window_toast"):
                self.patch(module, "show_window_toast", lambda ctx, msg, *a, **k: self.toasts.append(msg))
            if hasattr(module, "show_error"):
                self.patch(module, "show_error", lambda ctx, msg, *a, **k: self.errors.append(msg))

    def patch(self, module, name, value):
        patcher = mock.patch.object(module, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def spin(self, done, timeout=60):
        end = time.monotonic() + timeout
        while not done() and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertTrue(done(), "timed out waiting")

    def settle(self):
        """Until the engine request the window has running is answered and delivered."""
        self.spin(lambda: self.ctx._bg_request is None and self.ctx._bg_bridge is None)

    def tdt_folder(self, name="Rat7-250101-101010"):
        return make_tdt_folder(self.tmp, name)

    def plotted(self):
        return len(self.ctx.ax.lines)


class TestTdtFolder(LoaderCase):
    def test_a_folder_is_read_in_the_engine_and_shown(self):
        folder = self.tdt_folder()
        tdt._load_folder(self.ctx, folder)
        self.assertIsNone(self.ctx.cache)                                                    # asynchronous: nothing yet
        self.settle()
        self.assertEqual(self.errors, [])
        ctx = self.ctx
        self.assertEqual((ctx.cache["source"], ctx.cache["store"]), ("TDT", "Rat7-250101-101010"))
        self.assertEqual(set(ctx.cache["signals"]), {"normalized", "main_driver", "isosbestic"})
        self.assertTrue(all(s["color"] for s in ctx.cache["signals"].values()))
        self.assertIsNotNone(ctx.recording_id)
        self.assertEqual(ctx.recording_generation, ctx.engine.generation)
        self.assertEqual((ctx.plot_signal, ctx._active_splices, ctx.original_cache), ("normalized", [], None))
        self.assertGreater(self.plotted(), 0)
        self.assertTrue(any("motion correction kept" in t and "OLS" in t for t in self.toasts), self.toasts)

    def test_it_is_the_recording_a_script_gets(self):
        folder = self.tdt_folder()
        tdt._load_folder(self.ctx, folder)
        self.settle()
        reference = pl.load_recording(folder)["cache"]
        np.testing.assert_array_equal(self.ctx.cache["x"], reference["x"])
        np.testing.assert_array_equal(self.ctx.cache["corr"], reference["corr"])
        self.assertEqual(self.ctx.cache["detected_markers"], reference["detected_markers"])

    def test_the_regression_method_is_the_one_in_the_options(self):
        self.ctx.settings["regression_method"] = "huber"
        tdt._load_folder(self.ctx, self.tdt_folder())
        self.settle()
        self.assertTrue(any("HUBER" in t for t in self.toasts), self.toasts)

    def test_saved_changes_come_back_with_it(self):
        folder = self.tdt_folder()
        pl.saved_state.add_splice(folder, "cut_out", 5.0, 8.0)
        pl.saved_state.add_marker(folder, 12.0, label="Lever")
        pl.saved_state.write_saved_signal_labels(folder, {"normalized": "GCaMP"})
        pl.saved_state.write_saved_annotations(folder, "highlights.json", [{"start": 1.0, "end": 2.0, "color": "yellow"}])
        tdt._load_folder(self.ctx, folder)
        self.settle()
        ctx = self.ctx
        self.assertEqual(ctx._active_splices, [{"mode": "cut_out", "start": 5.0, "end": 8.0}])
        self.assertIsNotNone(ctx.original_cache)
        self.assertGreater(len(ctx.original_cache["x"]), len(ctx.cache["x"]))                # the full recording is what Restore brings back
        self.assertEqual([m["label"] for m in ctx.cache["markers"]], ["Lever"])
        self.assertEqual(ctx.cache["highlights"], [{"start": 1.0, "end": 2.0, "color": "yellow"}])
        self.assertEqual(ctx._signal_renames, {"normalized": "GCaMP"})
        self.assertEqual(ctx.cache["signals"]["normalized"]["label"], "GCaMP")
        self.assertEqual(ctx.original_cache["signals"]["normalized"]["label"], "GCaMP")
        self.assertIn("Restored 1 splice", self.toasts)
        self.assertIn("Markers restored (1)", self.toasts)
        self.assertEqual(ctx.cache["store"], pl.spliced_store_name(ctx.original_cache["store"], ctx._active_splices))
        self.assertNotEqual(ctx.cache["store"], ctx.original_cache["store"])

    def test_a_folder_that_is_not_a_recording_is_an_error_message(self):
        os.makedirs(os.path.join(self.tmp, "empty"))
        with mock.patch.object(pl, "detect_format", return_value=mock.Mock(**{"name": "TDT"})):
            tdt._load_folder(self.ctx, os.path.join(self.tmp, "empty"))
            self.settle()
        self.assertEqual(len(self.errors), 1)
        self.assertIsNone(self.ctx.cache)

    def test_reload_reads_the_disk_again(self):
        folder = self.tdt_folder()
        tdt._load_folder(self.ctx, folder)
        self.settle()
        first = self.ctx.recording_id
        self.assertEqual(self.ctx.cache["markers"], [])
        pl.saved_state.add_marker(folder, 12.0, label="Lever")                               # changed on disk since it was opened
        toolbar._reload_current(self.ctx)
        self.settle()
        self.assertNotEqual(self.ctx.recording_id, first)
        self.assertEqual([m["label"] for m in self.ctx.cache["markers"]], ["Lever"])
        self.assertEqual([r["id"] for r in self.ctx.engine.call("recording.list", timeout=30)["open"]], [self.ctx.recording_id])

    def test_a_second_recording_replaces_the_first_and_the_engine_lets_go_of_it(self):
        tdt._load_folder(self.ctx, self.tdt_folder("RatA-250101-101010"))
        self.settle()
        first = self.ctx.recording_id
        before = undo.snapshot(self.ctx)
        undo.push(self.ctx, "something", before)
        self.assertTrue(undo.can_undo(self.ctx))
        tdt._load_folder(self.ctx, self.tdt_folder("RatB-250101-101010"))
        self.settle()
        self.assertEqual(self.ctx.cache["store"], "RatB-250101-101010")
        self.assertNotEqual(self.ctx.recording_id, first)
        self.assertFalse(undo.can_undo(self.ctx))                                            # Ctrl+Z never swaps one recording for another
        open_now = [r["id"] for r in self.ctx.engine.call("recording.list", timeout=30)["open"]]
        self.assertEqual(open_now, [self.ctx.recording_id])

    def test_the_reference_a_request_names_the_recording_by(self):
        tdt._load_folder(self.ctx, self.tdt_folder())
        self.settle()
        self.ctx.cache["markers"] = [{"time": 3.0, "label": "mine"}]
        self.ctx._signal_renames = {"normalized": "GCaMP"}
        ref = recording_ref(self.ctx)
        self.assertEqual(ref["id"], self.ctx.recording_id)
        self.assertEqual((ref["splices"], ref["markers"], ref["signal_labels"]), ([], [{"time": 3.0, "label": "mine"}], {"normalized": "GCaMP"}))
        self.assertNotIn("highlights", ref)
        result = self.ctx.engine.call("run", {"kind": "auc_window", "recording": ref, "parameters": {"center_s": 10.0, "pre_s": 3.0, "post_s": 3.0}},
                                      timeout=60)
        self.assertEqual(result["kind"], "auc_window")

    def test_a_restarted_engine_means_the_recording_is_gone_and_the_window_is_told(self):
        tdt._load_folder(self.ctx, self.tdt_folder())
        self.settle()
        self.ctx.engine.restart()
        with self.assertRaises(BackendError) as caught:
            recording_ref(self.ctx)
        self.assertEqual(caught.exception.code, "no_recording")


class TestOxysoftFile(LoaderCase):
    def test_an_export_is_read_in_the_engine_and_shown(self):
        path = os.path.join(self.tmp, "session.txt")
        write_oxysoft(path)
        oxysoft._load_single_file(self.ctx, path)
        self.settle()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.ctx.cache["source"], "Oxysoft")
        self.assertEqual(self.ctx.cache["o2hb"].shape, (1, 600))
        self.assertGreater(self.plotted(), 0)
        self.assertIn("File: session.txt", self.toasts)

    def test_saved_markers_and_splices_come_back(self):
        path = os.path.join(self.tmp, "session.txt")
        write_oxysoft(path)
        pl.saved_state.add_splice(path, "keep_inside", 10.0, 40.0)
        pl.saved_state.add_marker(path, 20.0, label="Lever")
        oxysoft._load_single_file(self.ctx, path)
        self.settle()
        self.assertEqual(len(self.ctx._active_splices), 1)
        self.assertLess(len(self.ctx.cache["x"]), 600)
        self.assertEqual(len(self.ctx.original_cache["x"]), 600)
        self.assertEqual([m["label"] for m in self.ctx.cache["markers"]], ["Lever"])


class TestGenericTable(LoaderCase):
    def setUp(self):
        super().setUp()
        self.path = os.path.join(self.tmp, "table.csv")
        write_csv(self.path)

    def drive(self, choose):
        """Runs the loader with the picker dialog replaced by `choose(dialog)`, which plays the person's part."""
        seen = {}

        def exec_(dlg):
            seen["dialog"] = dlg
            choose(dlg)
            return 1

        with mock.patch.object(generic.GenericLoaderDialog, "exec", exec_):
            generic._load_generic_path(self.ctx, self.path)
            self.spin(lambda: "dialog" in seen or self.errors)
            self.settle()
        return seen.get("dialog")

    def test_the_picker_shows_what_the_engine_read(self):
        shown = {}

        def look(dlg):
            shown.update(tables=[dlg.tbl_list.item(i).text() for i in range(dlg.tbl_list.count())], x=[dlg.x_combo.itemText(i) for i in range(dlg.x_combo.count())],
                         y=[dlg.y_list.item(i).text() for i in range(dlg.y_list.count())], preview=dlg.preview.toPlainText())

        self.drive(look)
        self.assertEqual(shown["x"], ["time", "left", "right"])
        self.assertEqual(shown["y"], ["time", "left", "right"])
        self.assertTrue(shown["preview"].startswith("time\tleft\tright"))
        self.assertEqual(len(shown["preview"].splitlines()), 2 + 8)                          # header, rule, eight rows

    def test_loading_a_table_with_the_chosen_columns(self):
        self.drive(lambda dlg: dlg._do_load())                                               # the defaults: the first column is X, the rest are Y
        self.assertEqual(self.errors, [])
        self.assertEqual(self.ctx.cache["source"], "Generic")
        self.assertEqual(set(self.ctx.cache["y_columns"]), {"left", "right"})
        self.assertEqual(self.ctx.cache["x_label"], "time")
        self.assertEqual(len(self.ctx.cache["x"]), 200)
        self.assertGreater(self.plotted(), 0)
        self.assertTrue(any(t.startswith("Loaded: ") for t in self.toasts), self.toasts)

    def test_only_the_y_columns_picked_are_loaded(self):
        def pick(dlg):
            dlg.y_list.clearSelection()
            dlg.y_list.item(2).setSelected(True)                                             # "right"
            dlg._do_load()

        self.drive(pick)
        self.assertEqual(set(self.ctx.cache["y_columns"]), {"right"})

    def test_no_y_column_is_a_message_not_a_load(self):
        def pick(dlg):
            dlg.y_list.clearSelection()
            with mock.patch.object(generic, "show_error", lambda ctx, msg: self.errors.append(msg)):
                dlg._do_load()

        self.drive(pick)
        self.assertEqual(self.errors, ["Select at least one Y column."])
        self.assertIsNone(self.ctx.cache)

    def test_a_file_that_cannot_be_parsed_is_an_error_message(self):
        self.path = os.path.join(self.tmp, "broken.xlsx")
        with open(self.path, "wb") as f:
            f.write(b"this is not a workbook")
        self.drive(lambda dlg: None)
        self.assertEqual(len(self.errors), 1)
        self.assertIn("Could not parse file", self.errors[0])

    def test_a_file_with_no_table_in_it_says_so(self):
        with open(self.path, "w") as f:
            f.write("")
        self.drive(lambda dlg: None)
        self.assertEqual(self.errors, ["No usable tabular data found in this file."])

    def test_saved_markers_come_back(self):
        pl.saved_state.add_marker(self.path, 3.0, label="Lever")
        self.drive(lambda dlg: dlg._do_load())
        self.assertEqual([m["label"] for m in self.ctx.cache["markers"]], ["Lever"])


if __name__ == "__main__":
    unittest.main()
