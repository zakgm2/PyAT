"""What the window used to do itself and now asks the engine for, driven the way a person drives it (asynchronously, in the real main window):
the click analyses (Z-Score, AUC, FFT, Curve Fit, Measure Intervals), choosing a folder to open, the PT2 viewer, the text field study's folder,
Save Changes and Undo All Changes, the provenance record beside an export, and the group analysis' settings file."""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtWidgets import QDialog, QFileDialog, QMessageBox

import PyATCLI as pl
from PyATCLI.engine import store as engine_store

from physicsanalysis_qt.app import background
from physicsanalysis_qt import context
from physicsanalysis_qt.edit import sidecar
from physicsanalysis_qt.analysis import auc, curve_fit, fft, intervals, peth
from physicsanalysis_qt.edit import splice
from physicsanalysis_qt.analysis import windows
from physicsanalysis_qt.loading import pt2, tdt
from physicsanalysis_qt.fieldstudy import open_study as text_field_study
from physicsanalysis_qt.ui import edit_toolbar

from tests.recordings import make_tdt_folder, write_study
from tests.test_loaders_engine import LoaderCase


class WindowCase(LoaderCase):
    """A TDT recording on screen, asynchronously, and the dialogs captured instead of blocking."""

    def setUp(self):
        super().setUp()
        self.folder = self.tdt_folder()
        tdt._load_folder(self.ctx, self.folder)
        self.settle()
        self.assertIsNotNone(self.ctx.cache)
        self.dialogs = []
        patcher = mock.patch.object(QDialog, "exec", lambda dlg: self.dialogs.append(dlg) or 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ctx.window_pre, self.ctx.window_post = 3.0, 4.0
        self.toasts.clear()
        for module in (windows, splice, sidecar, curve_fit, auc, fft, peth, intervals):
            for name, sink in (("show_error", self.errors), ("show_window_toast", self.toasts)):
                if hasattr(module, name):
                    self.patch(module, name, lambda ctx, msg, *a, _s=sink, **k: _s.append(msg))

    def labels(self, dlg):
        return [l.text() for l in dlg.findChildren(__import__("PyQt6.QtWidgets", fromlist=["QLabel"]).QLabel)]


class TestClickAnalyses(WindowCase):
    def test_the_window_opens_when_the_engine_has_answered_not_before(self):
        peth.launch_zscore_peth(self.ctx, 10.0)
        self.assertEqual(self.dialogs, [])                                                    # asked, not yet answered
        self.settle()
        self.assertEqual(len(self.dialogs), 1)
        self.assertEqual(self.errors, [])

    def test_each_window_shows_what_the_library_computes(self):
        for launch, kind, table, column in ((peth.launch_zscore_peth, "zscore_window", "window", "z_score"),
                                            (auc.launch_auc, "auc_window", "auc", "Total AUC"),
                                            (fft.launch_fft, "fft_window", "spectrum", "power")):
            with self.subTest(kind):
                self.dialogs.clear()
                with mock.patch.object(sidecar, "show_error"):
                    launch(self.ctx, 10.0)
                    self.settle()
                dlg = self.dialogs[-1]
                text = " ".join(self.labels(dlg))
                self.assertIn("Normalized (dF/F)", text)
                result = pl.run_analysis(kind, self.ctx.cache, {"center_s": 10.0, "pre_s": 3.0, "post_s": 4.0, "signal": "normalized"})
                self.assertGreater(len(result.tables[table]), 0)

    def test_the_signal_the_plot_menu_shows_is_the_one_analysed(self):
        self.ctx.plot_signal = "isosbestic"
        peth.launch_zscore_peth(self.ctx, 10.0)
        self.settle()
        self.assertIn(self.ctx.cache["signals"]["isosbestic"]["label"], " ".join(self.labels(self.dialogs[-1])))

    def test_a_window_with_no_data_in_it_is_an_error_message_and_no_window(self):
        peth.launch_zscore_peth(self.ctx, 5000.0)                                             # far past the end of a 20 s recording
        self.settle()
        self.assertEqual(self.dialogs, [])
        self.assertEqual(len(self.errors), 1)
        self.assertIn("Not enough data", self.errors[0])

    def test_an_answer_for_a_recording_that_has_been_replaced_is_dropped(self):
        peth.launch_zscore_peth(self.ctx, 10.0)
        self.ctx._data_generation += 1                                                        # another file opened, a splice applied ...
        self.settle()
        self.assertEqual(self.dialogs, [])
        self.assertTrue(any("changed while the analysis ran" in t for t in self.toasts), self.toasts)

    def test_a_second_click_while_one_is_running_is_refused_not_queued(self):
        release = __import__("threading").Event()

        def slow(path, progress=None, **options):
            release.wait(30)

        first = windows.request_analysis(self.ctx, "zscore_window", {"center_s": 10.0}, lambda r: None)
        self.assertIsNotNone(first)
        with mock.patch.object(background, "show_window_toast") as toast:
            second = windows.request_analysis(self.ctx, "zscore_window", {"center_s": 11.0}, lambda r: None)
        self.assertIsNone(second)
        self.assertIn("already running", toast.call_args[0][1])
        self.settle()

    def test_a_recording_the_engine_lost_is_a_message_to_reload(self):
        self.ctx.engine.restart()
        peth.launch_zscore_peth(self.ctx, 10.0)
        self.assertEqual(self.dialogs, [])
        self.assertEqual(len(self.errors), 1)
        self.assertIn("restarted", self.errors[0])

    def test_the_names_given_in_the_window_are_the_ones_the_analysis_uses(self):
        from physicsanalysis_qt.edit import signal_names
        signal_names.apply_signal_renames(self.ctx, {"normalized": "GCaMP"}, redraw=False)
        auc.launch_auc(self.ctx, 10.0)
        self.settle()
        self.assertIn("GCaMP", " ".join(self.labels(self.dialogs[-1])))

    def test_an_oxysoft_recording_is_analysed_by_its_mean_channels(self):
        from tests.recordings import write_oxysoft
        path = os.path.join(self.tmp, "session.txt")
        write_oxysoft(path)
        from physicsanalysis_qt.loading import oxysoft
        with mock.patch.object(oxysoft, "show_window_toast"):
            oxysoft._load_single_file(self.ctx, path)
            self.settle()
        auc.launch_auc(self.ctx, 30.0)
        self.settle()
        text = " ".join(self.labels(self.dialogs[-1]))
        self.assertIn("Mean O2Hb", text)
        self.assertIn("Mean HHb", text)


class TestCurveFitDialog(WindowCase):
    def open_dialog(self):
        from matplotlib.figure import Figure
        self.ctx.ax = Figure().add_subplot()
        x = self.ctx.cache["x"]
        with mock.patch.object(curve_fit, "disarm_analysis"):
            curve_fit.launch_curve_fit(self.ctx, None, (int(np.searchsorted(x, 8.0)), 0), (int(np.searchsorted(x, 12.0)), 0))
        self.settle()
        return self.dialogs[-1]

    def test_the_dialog_fits_when_it_opens(self):
        dlg = self.open_dialog()
        self.assertIn("R2 =", dlg.result_lbl.text())
        self.assertGreater(len(dlg.last_fit_results), 0)
        self.assertTrue(dlg.recalc_btn.isEnabled())

    def test_recalculating_asks_again_with_the_model_chosen_and_disables_the_button_meanwhile(self):
        dlg = self.open_dialog()
        before = dlg.result_lbl.text()
        dlg.model_combo.setCurrentIndex(1)
        dlg._run_fit()
        self.assertFalse(dlg.recalc_btn.isEnabled())
        self.settle()
        self.assertTrue(dlg.recalc_btn.isEnabled())
        self.assertNotEqual(dlg.result_lbl.text(), before)
        self.assertEqual(dlg.last_fit_results[0]["model"], dlg.model_combo.currentText())

    def test_closing_the_dialog_before_the_answer_comes_is_harmless(self):
        dlg = self.open_dialog()
        dlg._run_fit()
        dlg.finished.emit(0)                                                                  # (what closing it does)
        self.settle()
        self.assertEqual(self.errors, [])

    def test_a_fit_that_fails_is_reported_in_the_dialog(self):
        dlg = self.open_dialog()
        flat = next(i for i in range(dlg.model_combo.count()) if "Exponential" in dlg.model_combo.itemText(i))
        dlg.model_combo.setCurrentIndex(flat)
        with mock.patch("PyATCLI.analyses.fit_model_to_segment", return_value={"success": False, "error": "no convergence"}):
            dlg._run_fit()
            self.settle()
        self.assertIn("Fit failed: no convergence", dlg.result_lbl.text())
        self.assertEqual(dlg.last_fit_results, [])


class TestMeasureIntervals(WindowCase):
    def test_the_intervals_are_the_librarys_for_the_markers_on_the_plot(self):
        self.ctx.cache["markers"] = [{**pl.saved_state.DEFAULT_MARKER, "time": t, "label": "m", "store": "S", "phase": ""} for t in (2.0, 5.0, 9.0)]
        intervals.launch_intervals(self.ctx)
        self.settle()
        dlg = self.dialogs[-1]
        self.assertEqual([round(r["time"], 3) for r in dlg.rows], [2.0, 5.0, 9.0])
        self.assertEqual([r["dt_store"] for r in dlg.rows], [None, 3.0, 4.0])
        self.assertEqual([r["dt_global"] for r in dlg.rows], [None, 3.0, 4.0])
        self.assertEqual({r["phase"] for r in dlg.rows}, {""})

    def test_without_markers_it_says_so_and_asks_nothing(self):
        self.ctx.cache["markers"] = []
        intervals.launch_intervals(self.ctx)
        self.assertEqual(self.dialogs, [])
        self.assertEqual(self.errors, ["No markers currently on the plot to measure."])


class TestOpeningAFolder(LoaderCase):
    def pick(self, path):
        return mock.patch.object(QFileDialog, "getExistingDirectory", return_value=path)

    def test_a_tdt_block_is_opened_at_once(self):
        folder = self.tdt_folder()
        with self.pick(folder):
            tdt.open_folder(self.ctx)
            self.assertIsNone(self.ctx.cache)                                                 # the engine is looking
            self.settle()
        self.assertEqual(self.ctx.cache["store"], os.path.basename(folder))

    def test_a_folder_holding_one_block_opens_it(self):
        cohort = os.path.join(self.tmp, "cohort")
        block = make_tdt_folder(os.path.join(cohort, "A"), "Rat1-250101-101010")
        with self.pick(cohort):
            tdt.open_folder(self.ctx)
            self.settle()
        self.assertEqual(self.ctx.cache["source_path"], block)

    def test_a_folder_holding_several_asks_what_to_do(self):
        cohort = os.path.join(self.tmp, "cohort")
        found = [make_tdt_folder(cohort, f"Rat{i}-250101-10101{i}") for i in range(3)]
        with self.pick(cohort), mock.patch.object(tdt, "_prompt_multi_tdt") as prompt:
            tdt.open_folder(self.ctx)
            self.settle()
        prompt.assert_called_once()
        ctx, listed, base = prompt.call_args.args
        self.assertEqual((sorted(listed), base), (sorted(found), cohort))
        self.assertIsNone(self.ctx.cache)

    def test_a_folder_with_nothing_in_it_is_an_error(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        with self.pick(empty):
            tdt.open_folder(self.ctx)
            self.settle()
        self.assertEqual(self.errors, ["No TDT folders found in the selected directory."])

    def test_cancelling_the_dialog_asks_nothing(self):
        with self.pick(""), mock.patch.object(self.ctx.engine, "request") as request:
            tdt.open_folder(self.ctx)
        request.assert_not_called()


class TestPt2Viewer(LoaderCase):
    def test_the_engine_reads_the_image_and_the_viewer_shows_it(self):
        img = np.arange(256, dtype=np.float32).reshape(16, 16) + 1.0
        path = os.path.join(self.tmp, "scan.pt2")
        with open(path, "wb") as fh:
            fh.write(b"header-bytes" + b"LAER" + img.astype("<f4").tobytes())
        shown = []
        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(path, "")), \
                mock.patch.object(pt2, "PT2ViewerDialog") as viewer:
            viewer.return_value.exec = lambda: shown.append(viewer.call_args)
            pt2.launch_pt2_viewer(self.ctx)
            self.assertEqual(shown, [])
            self.settle()
        np.testing.assert_array_equal(viewer.call_args.args[3], pl.load_pt2(path))

    def test_a_file_that_is_not_an_image_is_a_message(self):
        path = os.path.join(self.tmp, "bad.pt2")
        with open(path, "wb") as fh:
            fh.write(b"nothing")
        with mock.patch.object(QFileDialog, "getOpenFileName", return_value=(path, "")), mock.patch.object(pt2, "show_error") as err:
            pt2.launch_pt2_viewer(self.ctx)
            self.settle()
        err.assert_called_once()
        self.assertIn("LAER", err.call_args.args[1])


class TestFieldStudyFolder(LoaderCase):
    def test_the_engine_lists_the_fields_for_the_compare_dialog(self):
        folder = os.path.join(self.tmp, "study")
        os.makedirs(folder)
        write_study(folder)
        with mock.patch.object(QFileDialog, "getExistingDirectory", return_value=folder), \
                mock.patch.object(text_field_study, "CompareFieldsDialog") as dialog:
            dialog.return_value.exec.return_value = QDialog.DialogCode.Rejected
            text_field_study.open_field_study_folder(self.ctx)
            self.settle()
        self.assertEqual(dialog.call_args.args[1:], (folder, ["participant_id", "q1", "q2", "q3"]))

    def test_a_folder_without_participant_files_is_a_message(self):
        folder = os.path.join(self.tmp, "nothing")
        os.makedirs(folder)
        with mock.patch.object(QFileDialog, "getExistingDirectory", return_value=folder), \
                mock.patch.object(text_field_study, "show_error") as err:
            text_field_study.open_field_study_folder(self.ctx)
            self.settle()
        err.assert_called_once()
        self.assertIn("No files matching", err.call_args.args[1])


class TestSaveChanges(WindowCase):
    def settle_all(self):
        end = __import__("time").monotonic() + 60
        while (self.ctx._bg_request is not None or self.ctx._bg_bridge is not None or self.ctx._bg_extra) and __import__("time").monotonic() < end:
            self.app.processEvents()
            __import__("time").sleep(0.005)
        self.app.processEvents()

    def test_everything_is_written_in_one_request_and_one_toast_says_what(self):
        ctx = self.ctx
        ctx.cache["markers"] = [{**pl.saved_state.DEFAULT_MARKER, "time": 5.0, "label": "Lever"}]
        ctx.cache["highlights"] = [{"start": 1.0, "end": 2.0, "color": "yellow"}]
        ctx.cache["text_annotations"] = [{"x": 3.0, "y": 0.1, "text": "peak", "fontsize": 10}]
        ctx._signal_renames = {"normalized": "GCaMP"}
        with mock.patch.object(ctx.engine, "request", wraps=ctx.engine.request) as request:
            sidecar.save_changes(ctx)
            self.settle_all()
        self.assertEqual([c.args[0] for c in request.call_args_list], ["saved.write"])
        self.assertEqual([m["label"] for m in pl.read_saved_markers(self.folder)], ["Lever"])
        self.assertEqual(pl.read_saved_annotations(self.folder, "highlights.json"), [{"start": 1.0, "end": 2.0, "color": "yellow"}])
        self.assertEqual(pl.read_saved_annotations(self.folder, "text_annotations.json")[0]["text"], "peak")
        self.assertEqual(pl.read_saved_signal_labels(self.folder), {"normalized": "GCaMP"})
        self.assertEqual(pl.read_saved_splices(self.folder), [])
        self.assertEqual(self.toasts[-1], "Changes saved -> JSON saves/ (1 marker, 1 signal name, 1 highlight, 1 text box)")

    def test_a_splice_is_saved_with_it_and_a_removed_one_takes_its_file_away(self):
        splice_done = []
        splice.apply_splice(self.ctx, "cut_out", 5.0, 8.0, announce=False, on_done=splice_done.append)
        self.settle()
        sidecar.save_changes(self.ctx)
        self.settle_all()
        self.assertEqual(pl.read_saved_splices(self.folder), [{"mode": "cut_out", "start": 5.0, "end": 8.0}])
        self.assertIn("1 splice", self.toasts[-1])
        splice.restore_full_recording(self.ctx)
        sidecar.save_changes(self.ctx)
        self.settle_all()
        self.assertFalse(os.path.exists(pl.splice_sidecar_path(self.folder)))

    def test_saving_does_not_wait_for_a_load_and_a_load_does_not_wait_for_saving(self):
        release = __import__("threading").Event()

        def slow(path, progress=None, **options):
            release.wait(30)
            raise ValueError("released")

        with mock.patch.object(engine_store, "load_recording", slow):
            background.run_engine(self.ctx, "recording.open", {"path": self.folder}, lambda r: None, lambda m: None)   # a load the person waits for
            sidecar.save_changes(self.ctx)                                                       # Save Changes in the meantime: not refused
            self.assertFalse(any("already running" in t for t in self.toasts))
            release.set()
            self.settle_all()
        self.assertTrue(os.path.isfile(pl.marker_sidecar_path(self.folder)))

    def test_nothing_is_saved_for_a_recording_with_no_path(self):
        self.ctx.cache["source_path"] = ""
        with mock.patch.object(self.ctx.engine, "request") as request:
            sidecar.save_changes(self.ctx)
        request.assert_not_called()
        self.assertIn("No source file/folder path", self.errors[-1])

    def test_a_write_that_fails_is_reported(self):
        with mock.patch("PyATCLI.saved_state.write_saved_markers", side_effect=OSError("disk full")):
            sidecar.save_changes(self.ctx)
            self.settle_all()
        self.assertTrue(any("Could not save changes" in e and "disk full" in e for e in self.errors), self.errors)

    def test_undo_all_clears_the_folder_then_reads_the_recording_again(self):
        pl.saved_state.add_marker(self.folder, 5.0, label="Lever")
        tdt._load_folder(self.ctx, self.folder)
        self.settle()
        self.assertEqual([m["label"] for m in self.ctx.cache["markers"]], ["Lever"])
        first = self.ctx.recording_id
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            edit_toolbar._on_undo_all_clicked(self.ctx)
            self.settle_all()
            self.settle()
        self.assertEqual(os.listdir(os.path.join(self.folder, "JSON saves")), [])
        self.assertNotEqual(self.ctx.recording_id, first)
        self.assertEqual(self.ctx.cache["markers"], [])

    def test_undo_all_says_no_and_does_nothing_when_the_person_does(self):
        pl.saved_state.add_marker(self.folder, 5.0, label="Lever")
        with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No), \
                mock.patch.object(self.ctx.engine, "request") as request:
            edit_toolbar._on_undo_all_clicked(self.ctx)
        request.assert_not_called()
        self.assertTrue(os.path.isfile(pl.marker_sidecar_path(self.folder)))


class TestTheProvenanceRecordBesideAnExport(WindowCase):
    def export(self, name="Out.csv", provenance=None, **kw):
        written = {}

        def write(path):
            with open(path, "w") as f:
                f.write("a,b" + chr(10) + "1,2" + chr(10))
            written["path"] = path

        with mock.patch("physicsanalysis_qt.app.toasts.show_window_toast"), mock.patch.object(context, "get_export_dir", return_value=self.tmp), \
                mock.patch.object(QFileDialog, "getSaveFileName", return_value=(os.path.join(self.tmp, name), "")):
            context.export_file(self.ctx, None, "Export", name, "CSV (*.csv)", write, provenance=provenance, **kw)
        return written["path"]

    def wait_for_the_record(self, path):
        record = pl.sidecar_path_for(path)
        end = __import__("time").monotonic() + 60
        while not os.path.exists(record) and __import__("time").monotonic() < end:
            self.app.processEvents()
            __import__("time").sleep(0.01)
        return record

    def test_the_export_does_not_wait_for_the_record_and_the_record_arrives(self):
        path = self.export(provenance={"kind": "zscore_window", "parameters": {"center_s": 10.0, "signal": "normalized"}})
        record = pl.sidecar_path_for(path)
        self.assertTrue(os.path.exists(path))
        self.wait_for_the_record(path)
        doc = pl.read_record(record)
        self.assertEqual(doc["kind"], "zscore_window")
        self.assertEqual(doc["recording"]["source_type"], "TDT")
        self.assertEqual(doc["software"]["app"]["name"], "PyAT")

    def test_with_the_record_turned_off_the_engine_is_not_asked_and_nothing_is_remembered(self):
        self.ctx.settings["save_provenance"] = False
        with mock.patch.object(self.ctx.engine, "request", wraps=self.ctx.engine.request) as request:
            path = self.export("Latest.csv", provenance={"kind": "table", "parameters": {}})
            end = __import__("time").monotonic() + 5
            while self.ctx._bg_extra and __import__("time").monotonic() < end:
                self.app.processEvents()
        self.assertFalse(os.path.exists(pl.sidecar_path_for(path)))
        self.assertNotIn("provenance.write", [c.args[0] for c in request.call_args_list])

    def test_an_export_from_another_source_is_described_by_that_source_only(self):
        study = os.path.join(self.tmp, "study")
        os.makedirs(study)
        write_study(study)
        path = self.export("Study.csv", provenance={"kind": "table"}, recording_source=study)
        self.wait_for_the_record(path)
        doc = pl.read_record(pl.sidecar_path_for(path))
        self.assertEqual(doc["source"]["name"], "study")
        self.assertNotIn("recording", doc)                                                    # not the recording that happens to be open


if __name__ == "__main__":
    unittest.main()
