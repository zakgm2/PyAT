"""The pipeline in the window: its options are settings (Options -> Pipeline options…, applied with OK like the motion-correction method, to the recording on
screen and to everything opened afterwards) and Copy pipeline, at the bottom of the window, writes down what a recording was processed with. The engine is a real
one (on a thread of this process) and the recording is a real TDT folder, so what is checked is what a person gets: the recording on screen is the recording a
script gets with the same options."""

import glob
import os
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtWidgets import QApplication, QDialog, QGroupBox, QToolButton

import PyATCLI as pl
from PyATCLI import pipeline as library_pipeline
from PyATCLI.engine import store as engine_store

from physicsanalysis_qt import __version__, context
from physicsanalysis_qt.app import options, pipeline_dialog
from physicsanalysis_qt.backend import api
from physicsanalysis_qt.backend.recordings import recording_ref
from physicsanalysis_qt.loading import common, tdt

from tests.test_moved_to_engine import WindowCase

APP = {"name": "PyAT", "version": __version__}
ACCEPTED = QDialog.DialogCode.Accepted


class PipelineCase(WindowCase):
    def setUp(self):
        super().setUp()
        for module in (pipeline_dialog, common, options):
            for name, sink in (("show_error", self.errors), ("show_window_toast", self.toasts)):
                if hasattr(module, name):
                    self.patch(module, name, lambda ctx, msg, *a, _s=sink, **k: _s.append(msg))
        saver = mock.patch.object(context, "save_settings")                    # (a test must not write the real settings file)
        self.saved_settings = saver.start()
        self.addCleanup(saver.stop)
        self.ctx.settings["save_provenance"] = False
        self.ctx.settings["pipeline"] = {}                                      # (whatever the settings file of whoever runs the tests holds)
        self.ctx.settings["regression_method"] = "ols"

    def options_dialog(self):
        return options.OptionsDialog(self.ctx.win, self.ctx)

    def choose(self, dialog, edit):
        """Presses "Pipeline options…" in the Options dialog, makes `edit(picker)` in the window that opens, and Applies it (when `edit` returns None)."""
        def fake_exec(picker):
            edit(picker)
            picker.btn_apply.click()
            return ACCEPTED if picker.result() == ACCEPTED else QDialog.DialogCode.Rejected

        with mock.patch.object(pipeline_dialog.PipelineDialog, "exec", fake_exec):
            dialog._choose_pipeline()

    def apply_cutoff(self, hz):
        dlg = self.options_dialog()
        self.choose(dlg, lambda picker: picker.editors["denoise.cutoff_hz"].spin.setValue(hz))
        dlg._apply()
        self.settle()
        self.assertEqual(self.errors, [])

    def requests(self, op=None):
        names = [c.args[0] for c in self._request.call_args_list]
        return [n for n in names if op is None or n == op]

    def watch_requests(self):
        patcher = mock.patch.object(self.ctx.engine, "request", wraps=self.ctx.engine.request)
        self._request = patcher.start()
        self.addCleanup(patcher.stop)

    def open_text(self):
        self.dialogs.clear()
        pipeline_dialog.open_pipeline_text(self.ctx)
        self.settle()
        return self.dialogs[-1] if self.dialogs else None

    def settle_all(self):
        self.spin(lambda: self.ctx._bg_request is None and self.ctx._bg_bridge is None and not self.ctx._bg_extra)

    def methods_text(self):
        return self.ctx.engine.call("methods.text", {"recording": recording_ref(self.ctx), "app": APP}, timeout=60)


class TestWhatTheRecordingWasProcessedWith(PipelineCase):
    def test_opening_a_recording_puts_every_option_in_force_on_the_context(self):
        self.assertEqual(self.ctx.recording_pipeline, library_pipeline.defaults())

    def test_a_recording_that_was_replaced_takes_its_options_with_it_and_a_source_the_engine_does_not_hold_has_none(self):
        from physicsanalysis_qt.backend.recordings import forget
        forget(self.ctx)
        self.assertEqual(self.ctx.recording_pipeline, {})


class TestOptionEditor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def options(self):
        return [o for step in library_pipeline.describe()["steps"] for o in step["options"]]

    def test_every_option_the_library_declares_can_be_shown_and_answers_with_its_default_exactly(self):
        for option in self.options():
            with self.subTest(option["name"]):
                editor = pipeline_dialog.OptionEditor(option, option["default"])
                self.assertEqual(editor.value(), option["default"])
                self.assertIs(type(editor.value()), type(option["default"]))

    def test_a_box_that_was_edited_answers_with_what_it_holds_in_the_kind_of_number_the_option_is(self):
        by_name = {o["name"]: o for o in self.options()}
        editor = pipeline_dialog.OptionEditor(by_name["denoise.cutoff_hz"], 5.0)
        editor.spin.setValue(8.0)
        self.assertEqual(editor.value(), 8.0)
        self.assertIsInstance(editor.value(), float)
        editor = pipeline_dialog.OptionEditor(by_name["denoise.order"], 2)
        editor.spin.setValue(4)
        self.assertEqual(editor.value(), 4)
        self.assertIsInstance(editor.value(), int)
        editor = pipeline_dialog.OptionEditor(by_name["denoise.enabled"], True)
        editor.check.setChecked(False)
        self.assertIs(editor.value(), False)
        editor = pipeline_dialog.OptionEditor(by_name["dff.f0_method"], "double_exponential")
        editor.combo.setCurrentIndex(editor.combo.findData("linear"))
        self.assertEqual(editor.value(), "linear")

    def test_a_time_that_may_be_left_unset_is_set_by_its_check_box(self):
        option = next(o for o in self.options() if o["kind"] == "seconds_or_none")
        editor = pipeline_dialog.OptionEditor(option, None)
        self.assertFalse(editor.spin.isEnabled())
        self.assertIsNone(editor.value())
        editor.check.setChecked(True)
        self.assertTrue(editor.spin.isEnabled())
        editor.spin.setValue(12.5)
        self.assertEqual(editor.value(), 12.5)
        editor.check.setChecked(False)
        self.assertIsNone(editor.value())
        editor = pipeline_dialog.OptionEditor(option, 30.0)
        self.assertTrue(editor.check.isChecked())
        self.assertEqual(editor.spin.value(), 30.0)

    def test_an_option_nobody_touched_keeps_its_exact_value_whatever_the_box_shows(self):
        option = next(o for o in self.options() if o["name"] == "denoise.cutoff_hz")
        editor = pipeline_dialog.OptionEditor(option, 0.123456)
        self.assertEqual(editor.spin.value(), 0.123)                       # (three decimals are shown)
        self.assertEqual(editor.value(), 0.123456)                         # (and what is saved is not rounded to them)

    def test_setting_a_value_is_not_an_edit(self):
        option = next(o for o in self.options() if o["name"] == "denoise.cutoff_hz")
        editor = pipeline_dialog.OptionEditor(option, 8.0)
        seen = []
        editor.edited.connect(lambda: seen.append(1))
        editor.set_value(5.0)
        self.assertEqual((seen, editor.value()), ([], 5.0))


class TestSummarize(unittest.TestCase):
    def test_what_options_says_about_the_choice(self):
        self.assertEqual(pipeline_dialog.summarize({}), "All options at their defaults")
        self.assertEqual(pipeline_dialog.summarize({"denoise.cutoff_hz": 8.0}), "1 option changed: denoise.cutoff_hz")
        many = {"a.x": 1, "b.x": 1, "c.x": 1, "d.x": 1, "e.x": 1}
        self.assertEqual(pipeline_dialog.summarize(many), "5 options changed: a.x, b.x, c.x and 2 more")


class TestSummarizeWithTheMotionCorrectionMethod(unittest.TestCase):
    def test_the_method_is_said_when_it_is_not_ols(self):
        self.assertEqual(pipeline_dialog.summarize({}, "ols"), "All options at their defaults")
        self.assertEqual(pipeline_dialog.summarize({}, "huber"), "HUBER regression")
        self.assertEqual(pipeline_dialog.summarize({"a.x": 1}, "ransac"), "1 option changed: a.x; RANSAC regression")


class TestThePipelineWindow(unittest.TestCase):
    """The window of every choice, made from the library's description (the real backend)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, **values):
        description = api.pipeline.describe()
        return pipeline_dialog.PipelineDialog(None, description, {**description["defaults"], **values})

    def test_it_shows_every_option_of_every_step_that_has_one(self):
        dlg = self.make()
        self.assertEqual(set(dlg.editors), set(library_pipeline.defaults()))
        expected = [s["title"] if not s["sources"] else f"{s['title']} ({' and '.join(s['sources'])} recordings only)"
                    for s in library_pipeline.describe()["steps"] if s["options"]]
        self.assertEqual([g.title() for g in dlg.findChildren(QGroupBox)], expected)

    def test_a_step_that_only_applies_to_tdt_says_so_in_its_title(self):
        dlg = self.make()
        titles = [g.title() for g in dlg.findChildren(QGroupBox)]
        self.assertIn("Low-pass filter (TDT recordings only)", titles)
        self.assertIn("Smoothing", titles)

    def test_the_boxes_start_at_the_values_given_and_changed_is_only_what_is_not_the_default(self):
        dlg = self.make(**{"denoise.cutoff_hz": 7.0, "dff.f0_method": "linear"})
        self.assertEqual(dlg.editors["denoise.cutoff_hz"].spin.value(), 7.0)
        self.assertEqual(dlg.editors["dff.f0_method"].combo.currentData(), "linear")
        self.assertEqual(dlg.changed(), {"denoise.cutoff_hz": 7.0, "dff.f0_method": "linear"})
        self.assertEqual(self.make().changed(), {})

    def test_the_note_counts_what_is_not_at_the_default(self):
        dlg = self.make()
        self.assertEqual(dlg.note.text(), "0 options not at the default.")
        dlg.editors["denoise.cutoff_hz"].spin.setValue(8.0)
        self.assertEqual(dlg.note.text(), "1 option not at the default.")

    def test_reset_puts_every_box_back_to_its_default(self):
        dlg = self.make(**{"denoise.cutoff_hz": 7.0})
        dlg.btn_reset.click()
        self.assertEqual(dlg.values(), library_pipeline.defaults())
        self.assertEqual(dlg.editors["denoise.cutoff_hz"].spin.value(), 5.0)

    def test_the_motion_correction_method_is_chosen_here_with_the_steps_own_options(self):
        dlg = self.make()
        box = next(g for g in dlg.findChildren(QGroupBox) if g.title().startswith("Motion correction"))
        self.assertTrue(box.isAncestorOf(dlg.combo_regression))
        self.assertEqual([dlg.combo_regression.itemData(i) for i in range(dlg.combo_regression.count())], ["ols", "ransac", "huber"])
        self.assertEqual(dlg.regression_method(), "ols")
        self.assertEqual(pipeline_dialog.PipelineDialog(None, api.pipeline.describe(), library_pipeline.defaults(), "huber").regression_method(), "huber")

    def test_the_method_has_a_place_even_when_the_description_has_no_motion_step(self):
        from tests.fake_backend import FakeBackend
        description = FakeBackend().pipeline.describe()                             # (a denoise step and a smoothing step)
        dlg = pipeline_dialog.PipelineDialog(None, description, description["defaults"], "ransac")
        self.assertEqual(dlg.regression_method(), "ransac")
        self.assertIn("Motion correction (TDT recordings only)", [g.title() for g in dlg.findChildren(QGroupBox)])

    def test_the_note_and_reset_know_about_the_method(self):
        dlg = pipeline_dialog.PipelineDialog(None, api.pipeline.describe(), library_pipeline.defaults(), "huber")
        self.assertEqual(dlg.note.text(), "0 options not at the default; HUBER regression.")
        dlg.btn_reset.click()
        self.assertEqual(dlg.regression_method(), "ols")
        self.assertEqual(dlg.note.text(), "0 options not at the default.")

    def test_apply_accepts_what_the_library_can_use(self):
        dlg = self.make()
        dlg.editors["denoise.cutoff_hz"].spin.setValue(8.0)
        dlg.btn_apply.click()
        self.assertEqual(dlg.result(), ACCEPTED)
        self.assertTrue(dlg.problem.isHidden())

    def test_apply_says_why_and_stays_when_the_library_cannot_use_what_is_chosen(self):
        dlg = self.make()
        dlg.editors["motion.exclude_start_s"].check.setChecked(True)               # a stretch to leave out needs its end too
        dlg.btn_apply.click()
        self.assertNotEqual(dlg.result(), ACCEPTED)
        self.assertFalse(dlg.problem.isHidden())
        self.assertIn("given together", dlg.problem.text())
        dlg.editors["motion.exclude_end_s"].check.setChecked(True)
        dlg.editors["motion.exclude_end_s"].spin.setValue(5.0)
        self.assertTrue(dlg.problem.isHidden())                                    # (the reason goes away as the choice is changed)
        dlg.btn_apply.click()
        self.assertEqual(dlg.result(), ACCEPTED)


class TestTheOptionsDialogHasThePipeline(PipelineCase):
    def test_it_has_a_group_with_what_is_chosen_and_a_button(self):
        dlg = self.options_dialog()
        self.assertIn("Processing Pipeline", [g.title() for g in dlg.findChildren(QGroupBox)])
        self.assertEqual(dlg.lbl_pipeline.text(), "All options at their defaults")
        self.assertEqual(dlg.btn_pipeline.text(), "Pipeline options…")

    def test_the_summary_follows_what_is_in_the_settings(self):
        self.ctx.settings["pipeline"] = {"denoise.cutoff_hz": 8.0}
        self.assertEqual(self.options_dialog().lbl_pipeline.text(), "1 option changed: denoise.cutoff_hz")
        self.ctx.settings["regression_method"] = "huber"
        self.assertEqual(self.options_dialog().lbl_pipeline.text(), "1 option changed: denoise.cutoff_hz; HUBER regression")

    def test_the_motion_correction_method_is_no_longer_a_group_of_its_own_in_options(self):
        dlg = self.options_dialog()
        self.assertNotIn("Motion Correction (TDT)", [g.title() for g in dlg.findChildren(QGroupBox)])
        self.assertFalse(hasattr(dlg, "combo_regression"))
        self.assertEqual(dlg.regression_choice, "ols")

    def test_the_method_chosen_in_the_pipeline_window_is_kept_by_the_dialog_until_ok(self):
        dlg = self.options_dialog()
        self.choose(dlg, lambda picker: picker.combo_regression.setCurrentIndex(picker.combo_regression.findData("ransac")))
        self.assertEqual(dlg.regression_choice, "ransac")
        self.assertEqual(dlg.pipeline_choice, {})
        self.assertEqual(dlg.lbl_pipeline.text(), "RANSAC regression")
        self.assertEqual(self.ctx.settings["regression_method"], "ols")            # (nothing is settled until OK)

    def test_the_window_opens_on_the_method_that_is_chosen(self):
        self.ctx.settings["regression_method"] = "huber"
        dlg = self.options_dialog()
        seen = []
        with mock.patch.object(pipeline_dialog.PipelineDialog, "exec", lambda picker: seen.append(picker.regression_method()) or QDialog.DialogCode.Rejected):
            dlg._choose_pipeline()
        self.assertEqual(seen, ["huber"])

    def test_choosing_in_the_window_is_kept_by_the_dialog_until_ok(self):
        dlg = self.options_dialog()
        self.choose(dlg, lambda picker: picker.editors["denoise.order"].spin.setValue(3))
        self.assertEqual(dlg.pipeline_choice, {"denoise.order": 3})
        self.assertEqual(dlg.lbl_pipeline.text(), "1 option changed: denoise.order")
        self.assertEqual(self.ctx.settings["pipeline"], {})                        # (nothing is settled until OK)
        self.saved_settings.assert_not_called()

    def test_cancelling_the_window_keeps_what_was_chosen_before(self):
        self.ctx.settings["pipeline"] = {"denoise.order": 3}
        dlg = self.options_dialog()
        with mock.patch.object(pipeline_dialog.PipelineDialog, "exec", lambda picker: QDialog.DialogCode.Rejected):
            dlg._choose_pipeline()
        self.assertEqual(dlg.pipeline_choice, {"denoise.order": 3})

    def test_the_window_opens_on_what_is_chosen(self):
        self.ctx.settings["pipeline"] = {"denoise.cutoff_hz": 8.0}
        dlg = self.options_dialog()
        seen = []
        with mock.patch.object(pipeline_dialog.PipelineDialog, "exec", lambda picker: seen.append(picker.values()) or QDialog.DialogCode.Rejected):
            dlg._choose_pipeline()
        self.assertEqual(seen[0]["denoise.cutoff_hz"], 8.0)
        self.assertEqual(seen[0]["denoise.order"], 2)


class TestOkAppliesThePipeline(PipelineCase):
    def test_ok_reads_the_recording_again_with_the_options_and_it_is_the_recording_a_script_gets(self):
        before = np.array(self.ctx.cache["corr"])
        self.assertFalse(pipeline_dialog.holds_unsaved_work(self.ctx))
        self.apply_cutoff(8.0)
        self.assertEqual(self.ctx.settings["pipeline"], {"denoise.cutoff_hz": 8.0})
        self.saved_settings.assert_called_with(self.ctx.settings)
        self.assertEqual(self.ctx.recording_pipeline["denoise.cutoff_hz"], 8.0)
        reference = pl.load_recording(self.folder, pipeline={"denoise.cutoff_hz": 8.0})["cache"]
        np.testing.assert_array_equal(self.ctx.cache["corr"], reference["corr"])
        self.assertFalse(np.array_equal(self.ctx.cache["corr"], before))
        self.assertEqual(self.toasts[-1], "Pipeline options applied")

    def test_what_is_chosen_applies_to_anything_opened_afterwards(self):
        self.ctx.settings["pipeline"] = {"denoise.cutoff_hz": 8.0}
        tdt._load_folder(self.ctx, self.folder)
        self.settle()
        self.assertEqual(self.ctx.recording_pipeline["denoise.cutoff_hz"], 8.0)
        self.assertEqual(self.ctx.recording_load["pipeline"], {"denoise.cutoff_hz": 8.0})

    def test_a_choice_the_library_no_longer_has_is_left_out_not_sent(self):
        self.ctx.settings["pipeline"] = {"old.gone": 1, "denoise.cutoff_hz": 8.0}
        self.assertEqual(common.pipeline_settings(self.ctx), {"denoise.cutoff_hz": 8.0})
        tdt._load_folder(self.ctx, self.folder)
        self.settle()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.ctx.recording_pipeline["denoise.cutoff_hz"], 8.0)

    def test_ok_with_nothing_changed_reads_nothing_again(self):
        self.watch_requests()
        dlg = self.options_dialog()
        dlg._apply()
        self.settle()
        self.assertEqual(self.requests("recording.open"), [])

    def test_with_unsaved_work_on_screen_it_asks_first_and_no_changes_nothing(self):
        self.ctx.cache["markers"] = [{"time": 5.0, "label": "mine", "color": "red", "fontsize": 8}]
        self.watch_requests()
        dlg = self.options_dialog()
        self.choose(dlg, lambda picker: picker.editors["denoise.order"].spin.setValue(3))
        with mock.patch.object(options, "confirm_reload", return_value=False) as ask:
            dlg._apply()
            self.settle()
        ask.assert_called_once()
        self.assertEqual(self.requests("recording.open"), [])
        self.assertEqual(self.ctx.settings["pipeline"], {})
        self.saved_settings.assert_not_called()
        self.assertEqual(len(self.ctx.cache["markers"]), 1)

    def test_yes_reads_it_again_as_reload_does_and_what_was_never_saved_is_gone(self):
        self.ctx.cache["markers"] = [{"time": 5.0, "label": "mine", "color": "red", "fontsize": 8}]
        dlg = self.options_dialog()
        self.choose(dlg, lambda picker: picker.editors["denoise.order"].spin.setValue(3))
        with mock.patch.object(options, "confirm_reload", return_value=True):
            dlg._apply()
            self.settle()
        self.assertEqual(self.ctx.recording_pipeline["denoise.order"], 3)
        self.assertEqual(self.ctx.cache["markers"], [])

    def test_a_recording_that_cannot_be_processed_with_the_options_puts_the_old_ones_back_and_says_why(self):
        cache = self.ctx.cache

        def refuse(path, progress=None, **opts):
            raise ValueError("these options do not suit this recording")

        dlg = self.options_dialog()
        self.choose(dlg, lambda picker: picker.editors["denoise.order"].spin.setValue(3))
        with mock.patch.object(engine_store, "load_recording", refuse):
            dlg._apply()
            self.settle()
        self.assertTrue(any("do not suit this recording" in e and "not kept" in e for e in self.errors), self.errors)
        self.assertEqual(self.ctx.settings["pipeline"], {})                        # (so the next open is not refused for them)
        self.assertIs(self.ctx.cache, cache)
        self.assertEqual(self.saved_settings.call_count, 2)                        # (saved with them, then without)

    def test_back_to_the_defaults_reads_it_again_without_them(self):
        original = np.array(self.ctx.cache["corr"])
        self.apply_cutoff(8.0)
        dlg = self.options_dialog()
        self.choose(dlg, lambda picker: picker.btn_reset.click())
        dlg._apply()
        self.settle()
        self.assertEqual(self.ctx.settings["pipeline"], {})
        self.assertEqual(self.ctx.recording_pipeline, library_pipeline.defaults())
        np.testing.assert_array_equal(self.ctx.cache["corr"], original)

    def test_a_new_motion_correction_method_and_new_options_are_one_reload_not_two(self):
        self.watch_requests()
        dlg = self.options_dialog()
        self.choose(dlg, lambda picker: picker.editors["denoise.cutoff_hz"].spin.setValue(8.0))
        dlg.regression_choice = "huber"                                            # (what the Pipeline window gave back)
        dlg._apply()
        self.settle()
        self.assertEqual(self.requests("recording.open"), ["recording.open"])
        self.assertEqual((self.ctx.recording_method, self.ctx.recording_pipeline["denoise.cutoff_hz"]), ("huber", 8.0))

    def test_ok_with_only_a_new_method_reloads_the_tdt_recording_with_it(self):
        self.watch_requests()
        dlg = self.options_dialog()
        self.choose(dlg, lambda picker: picker.combo_regression.setCurrentIndex(picker.combo_regression.findData("huber")))
        dlg._apply()
        self.settle()
        self.assertEqual(self.ctx.settings["regression_method"], "huber")
        self.assertEqual(self.ctx.recording_method, "huber")
        self.assertEqual(self.requests("recording.open"), ["recording.open"])

    def test_a_table_is_read_again_without_asking_which_columns(self):
        self.ctx.cache["source"] = "Generic"
        self.ctx.recording_load = {"table": "Sheet1", "x_column": "t", "y_columns": ["a"], "pipeline": {"smoothing.window_s": 2.0}}
        self.ctx.settings["pipeline"] = {"smoothing.window_s": 1.0}
        with mock.patch.object(common, "open_recording") as opened:
            common.reopen_current(self.ctx)
        self.assertEqual(opened.call_args.kwargs["load"], {"table": "Sheet1", "x_column": "t", "y_columns": ["a"]})        # (open_recording adds what Options chose)

    def test_a_tdt_recording_is_read_again_with_the_method_set_in_options(self):
        self.ctx.recording_load = {"regression_method": "ols"}
        self.ctx.settings["regression_method"] = "huber"
        with mock.patch.object(common, "open_recording") as opened:
            common.reopen_current(self.ctx)
        self.assertEqual(opened.call_args.kwargs["load"], {"regression_method": "huber"})

    def test_with_nothing_loaded_it_does_nothing(self):
        self.ctx.cache = None
        with mock.patch.object(common, "open_recording") as opened:
            self.assertIsNone(common.reopen_current(self.ctx))
        opened.assert_not_called()

    def test_a_reconnected_engine_has_the_recording_with_the_options_that_are_on_screen(self):
        self.apply_cutoff(8.0)
        self.ctx.engine.restart()
        common.reconnect_recording(self.ctx)
        self.settle()
        self.assertEqual(self.methods_text()["options"]["denoise.cutoff_hz"], 8.0)


class TestTheGroupAnalysisUsesThem(PipelineCase):
    """The Hypothesis Testing wizard: its smoothing and baseline start from the pipeline options, its settings carry them, and the engine runs the group with them."""

    def setUp(self):
        super().setUp()
        from physicsanalysis_qt.analysis.group import setup_dialog
        self.setup_dialog = setup_dialog
        self.other = self.tdt_folder("Rat8-250101-101011")
        scans = pl.scan_recordings([self.folder, self.other], self.tmp)
        for sc, name in zip(scans, pl.default_subject_names([self.folder, self.other], self.tmp)):
            sc["subject"] = name
        self.scans = scans

    def wizard(self):
        return self.setup_dialog.GroupSetupDialog(self.ctx.win, self.ctx, self.scans, self.tmp)

    def test_without_options_it_starts_from_the_librarys_defaults_and_has_no_pipeline(self):
        wizard = self.wizard()
        window = wizard.pages[2]
        self.assertEqual((window.smooth.value(), window.b0.value(), window.b1.value()), (0.5, -10.0, -6.0))
        self.assertEqual(wizard.build_spec().pipeline, {})
        self.assertEqual(wizard.build_spec().regression_method, "ols")

    def test_the_smoothing_and_the_baseline_start_from_what_the_options_say(self):
        self.ctx.settings["pipeline"] = {"smoothing.window_s": 1.0, "zscore.baseline_end_s": -2.0, "denoise.cutoff_hz": 8.0}
        wizard = self.wizard()
        window = wizard.pages[2]
        self.assertEqual((window.smooth.value(), window.b0.value(), window.b1.value()), (1.0, -10.0, -2.0))
        spec = wizard.build_spec()
        self.assertEqual(spec.pipeline, {"smoothing.window_s": 1.0, "zscore.baseline_end_s": -2.0, "denoise.cutoff_hz": 8.0})
        self.assertEqual((spec.smooth_seconds, spec.baseline), (1.0, (-10.0, -2.0)))

    def test_what_is_typed_in_the_wizard_wins_and_reset_goes_back_to_where_it_started(self):
        self.ctx.settings["pipeline"] = {"smoothing.window_s": 1.0}
        wizard = self.wizard()
        window = wizard.pages[2]
        window.smooth.setValue(0.2)
        self.assertEqual(wizard.build_spec().smooth_seconds, 0.2)
        window._reset()
        self.assertEqual(window.smooth.value(), 1.0)                               # (the options', not the library's 0.5)

    def test_the_motion_correction_method_still_comes_from_the_settings(self):
        self.ctx.settings["regression_method"] = "ransac"
        self.assertEqual(self.wizard().build_spec().regression_method, "ransac")

    def test_the_review_says_what_the_pipeline_is(self):
        text = self.setup_dialog._pipeline_text
        self.assertEqual(text(SimpleNamespace(pipeline={})), "default pipeline options")
        self.assertEqual(text(SimpleNamespace(pipeline={"a.x": 1})), "1 pipeline option changed")
        self.assertEqual(text(SimpleNamespace(pipeline={"a.x": 1, "b.x": 2})), "2 pipeline options changed")

    def test_the_engine_runs_the_group_with_them(self):
        def run(**fields):
            spec = api.group.new_settings(group_name="G", subjects=[{"subject": "A", "folder": self.folder}, {"subject": "B", "folder": self.other}],
                                          markers=["L1P¹"], pre=3.0, post=4.0, baseline=(-3.0, -1.0), response=(0.0, 4.0), metrics=["auc"], smooth_seconds=0.0, **fields)
            out = os.path.join(self.tmp, f"out{len(os.listdir(self.tmp))}")
            answer = self.ctx.engine.call("group.run", {"settings": spec.to_dict(), "out": out, "tables": "inline"}, timeout=120)
            return answer, spec

        plain, _ = run()
        filtered, spec = run(pipeline={"denoise.cutoff_hz": 0.05})
        self.assertEqual(filtered["spec"]["pipeline"], {"denoise.cutoff_hz": 0.05})
        self.assertEqual(plain["spec"]["pipeline"], {})
        a, b = plain["table_data"]["trials"]["data"]["baseline_sd"], filtered["table_data"]["trials"]["data"]["baseline_sd"]
        self.assertNotEqual(a, b)                                                   # (the trials were cut from a differently filtered dF/F)


class TestSaveChangesDoesNotPinTheOptions(PipelineCase):
    def test_they_are_settings_like_the_regression_method_so_nothing_is_written_beside_the_recording(self):
        from physicsanalysis_qt.edit import sidecar
        self.apply_cutoff(8.0)
        with mock.patch.object(sidecar, "show_window_toast"):
            sidecar.save_changes(self.ctx)
            self.settle_all()
        self.assertFalse(os.path.exists(pl.saved_state.pipeline_sidecar_path(self.folder)))


class TestCopyPipeline(PipelineCase):
    def test_the_button_is_at_the_bottom_of_the_window_and_opens_it(self):
        button = self.ctx.btn_copy_pipeline
        self.assertIsInstance(button, QToolButton)
        self.assertEqual(button.text(), "Copy pipeline")
        self.assertIs(button.parent(), self.ctx.status_bar)
        with mock.patch("physicsanalysis_qt.ui.main_window.open_pipeline_text") as opened:
            button.click()
        opened.assert_called_once_with(self.ctx)

    def test_it_shows_the_paragraph_the_engine_writes_for_the_recording_on_screen(self):
        dlg = self.open_text()
        self.assertIsInstance(dlg, pipeline_dialog.PipelineTextDialog)
        text = self.methods_text()["text"]
        self.assertEqual(dlg.text.toPlainText(), text)
        self.assertIn("PyAT", text)                                          # (the program is named, as the engine was told)
        self.assertIn("Butterworth", text)
        self.assertTrue(dlg.text.isReadOnly())

    def test_the_paragraph_says_what_was_chosen(self):
        self.apply_cutoff(8.0)
        self.assertIn("8 Hz", self.open_text().text.toPlainText())

    def test_copy_puts_it_on_the_clipboard(self):
        dlg = self.open_text()
        QApplication.clipboard().setText("")
        dlg.btn_copy.click()
        self.assertEqual(QApplication.clipboard().text(), dlg.text.toPlainText())
        self.assertEqual(self.toasts[-1], "Pipeline text copied")

    def test_save_as_text_writes_it_into_the_recordings_output_folder(self):
        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        self.ctx.settings["output_folder"] = out
        dlg = self.open_text()
        dlg.btn_save.click()
        self.settle_all()
        saved = glob.glob(os.path.join(out, "**", "Pipeline_*.txt"), recursive=True)
        self.assertEqual(len(saved), 1, saved)
        with open(saved[0], encoding="utf-8") as f:
            self.assertEqual(f.read(), dlg.text.toPlainText() + "\n")

    def test_with_no_recording_there_is_no_window_and_no_request(self):
        self.ctx.recording_id = None
        self.watch_requests()
        self.assertIsNone(pipeline_dialog.open_pipeline_text(self.ctx))
        self.assertEqual(self.requests(), [])
        self.assertIn("open one first", self.toasts[-1])

    def test_an_engine_that_lost_the_recording_is_a_message_not_a_window(self):
        self.ctx.engine.restart()
        self.assertIsNone(self.open_text())
        self.assertTrue(any("no longer has this recording" in e for e in self.errors), self.errors)


class TestHoldsUnsavedWork(unittest.TestCase):
    def ctx(self, cache=None, splices=(), renames=None):
        return SimpleNamespace(cache={"markers": [], **(cache or {})}, _active_splices=list(splices), _signal_renames=renames or {})

    def test_a_recording_as_it_opened_has_none(self):
        self.assertFalse(pipeline_dialog.holds_unsaved_work(self.ctx()))
        self.assertFalse(pipeline_dialog.holds_unsaved_work(SimpleNamespace(cache=None, _active_splices=[], _signal_renames={})))

    def test_anything_the_person_put_on_it_counts(self):
        for what in ({"cache": {"markers": [{"time": 1.0}]}}, {"cache": {"highlights": [{}]}}, {"cache": {"text_annotations": [{}]}},
                     {"splices": [{"mode": "cut_out"}]}, {"renames": {"normalized": "GCaMP"}}):
            with self.subTest(what):
                self.assertTrue(pipeline_dialog.holds_unsaved_work(self.ctx(**what)))


if __name__ == "__main__":
    unittest.main()
