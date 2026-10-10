"""The text field study through the analysis engine: opening a study folder (embeddings and similarity per participant) and the statistical
validation of its field pairs — both run in the engine, with the language model replaced by a stand-in, and arrive as the tables the windows
show."""

import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd
from PyQt6.QtWidgets import QApplication, QWidget

from physicsanalysis_qt.fieldstudy import validation as field_study_validation
from physicsanalysis_qt.context import AppState
from physicsanalysis_qt.fieldstudy import open_study as text_field_study

from tests.recordings import patch_embedding_model, write_study

CONFIG = {"text_fields": ["q1", "q2", "q3"], "paired_fields": [["q1", "q2", "pair12"]], "delta_pair": ["q1", "q3"], "file_glob": "P-*.json", "min_words": 5}


class StudyCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = self._tmp.name
        write_study(self.folder)
        patcher = patch_embedding_model()
        self.addCleanup(patcher.stop)
        self.ctx = AppState(self.app)
        self.ctx.settings["background_loading"] = False
        self.ctx.win = QWidget()
        self.addCleanup(self.ctx.win.deleteLater)
        self.addCleanup(lambda: self.ctx.engine.shutdown())
        self.toasts, self.errors = [], []
        for module in (text_field_study, field_study_validation):
            if hasattr(module, "show_window_toast"):
                p = mock.patch.object(module, "show_window_toast", lambda ctx, msg, *a, **k: self.toasts.append(msg))
                p.start()
                self.addCleanup(p.stop)
            p = mock.patch.object(module, "show_error", lambda ctx, msg, *a, **k: self.errors.append(msg))
            p.start()
            self.addCleanup(p.stop)


class TestOpeningAStudy(StudyCase):
    def test_the_study_is_a_table_with_a_row_per_participant(self):
        shown = []
        with mock.patch("physicsanalysis_qt.fieldstudy.results.launch_field_study_results", lambda ctx: shown.append(ctx.study_data)):
            text_field_study._load_field_study_folder(self.ctx, self.folder, CONFIG)
        self.assertEqual(self.errors, [])
        df = self.ctx.study_data
        self.assertEqual(len(df), 14)
        self.assertEqual((self.ctx.study_data_path, self.ctx.study_data_config), (self.folder, CONFIG))
        for column in ("participant_id", "sim_pair12", "delta_magnitude"):
            self.assertIn(column, df.columns)
        self.assertEqual(df["participant_id"].tolist(), [f"P{i:02d}" for i in range(14)])
        self.assertIs(shown[0], df)
        self.assertIn("Loaded 14 subject(s)", self.toasts)

    def test_it_is_what_the_library_makes(self):
        import PyATCLI as pl
        with mock.patch("physicsanalysis_qt.fieldstudy.results.launch_field_study_results"):
            text_field_study._load_field_study_folder(self.ctx, self.folder, CONFIG)
        want = pl.run_field_study_pipeline(self.folder, text_fields=CONFIG["text_fields"], delta_pair=("q1", "q3"),
                                           paired_fields=[("q1", "q2", "pair12")], min_words=5)
        fixed = [c for c in want.columns if not c.startswith(("null_", "pvalue_", "effect_size_"))]     # (the permutation null is random)
        self.assertIn("sim_pair12", fixed)
        pd.testing.assert_frame_equal(self.ctx.study_data[fixed], want[fixed], check_dtype=False, check_exact=False)

    def test_a_folder_that_is_not_a_study_is_an_error_message(self):
        empty = os.path.join(self.folder, "empty")
        os.makedirs(empty)
        text_field_study._load_field_study_folder(self.ctx, empty, CONFIG)
        self.assertEqual(len(self.errors), 1)
        self.assertIsNone(self.ctx.study_data)


class TestValidatingAStudy(StudyCase):
    def setUp(self):
        super().setUp()
        self.ctx.study_data = pd.DataFrame({"participant_id": ["P00"]})
        self.ctx.study_data_path = self.folder
        self.ctx.study_data_config = CONFIG

    def test_the_summary_has_a_row_per_pair_with_numbers_as_numbers(self):
        shown = []

        class Dialog:
            def __init__(inner, ctx, df):
                shown.append(df)

            def exec(inner):
                return 1

        with mock.patch.object(field_study_validation, "ValidationSummaryDialog", Dialog):
            field_study_validation.launch_field_study_validation(self.ctx)
        self.assertEqual(self.errors, [])
        (df,) = shown
        self.assertEqual(len(df), 1)
        self.assertTrue(0.0 <= float(df["p_value_fdr"].iloc[0]) <= 1.0)
        self.assertEqual(field_study_validation._verdict(float(df["p_value_fdr"].iloc[0]), float(df["ci_lower"].iloc[0])).__class__, str)

    def test_no_study_loaded_is_a_message(self):
        self.ctx.study_data = None
        field_study_validation.launch_field_study_validation(self.ctx)
        self.assertIn("No text field study loaded", self.errors[0])


if __name__ == "__main__":
    unittest.main()
