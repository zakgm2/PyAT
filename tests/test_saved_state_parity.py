"""What the app saves and what a script saves (PyATCLI.saved_state) are the same files, so an edit made in either shows up in
the other: Save Changes writes the bytes the library writes, and the app restores what the library wrote — the same markers,
highlights, text boxes, signal names and splices that opening the recording from a script gives."""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

import PyATCLI as pl
from PyATCLI import saved_state as S

from physicsanalysis_qt.edit import sidecar
from physicsanalysis_qt.loading import common, tdt

from tests.test_gui_reproduces import GuiCase, WindowCase


class ParityCase(GuiCase):
    def read(self, path):
        with open(path, "rb") as f:
            return f.read()

    def app_writes_library_writes(self, save_in_app, library_path, write_in_library):
        """The file the app's Save Changes writes, and then the one the library writes for the same content, in the same place."""
        with mock.patch("physicsanalysis_qt.edit.sidecar.show_window_toast"), mock.patch("physicsanalysis_qt.edit.splice.show_window_toast"):
            save_in_app()
        by_app = self.read(library_path)
        os.remove(library_path)
        write_in_library()
        return by_app, self.read(library_path)


class TestSaveChangesWritesWhatTheLibraryWrites(ParityCase):
    def test_markers(self):
        self.ctx.cache["markers"] = [{"time": 12.5, "label": "Lever ¹", "color": "red", "fontsize": 8}, {"time": 3.25, "label": "Clap", "color": "green", "fontsize": 10}]
        app, library = self.app_writes_library_writes(lambda: sidecar.save_changes(self.ctx), sidecar.sidecar_path(self.ctx),
                                                      lambda: S.write_saved_markers(self.folder, self.ctx.cache["markers"]))
        self.assertEqual(app, library)

    def test_highlights_and_text_boxes(self):
        self.ctx.cache["highlights"] = [{"start": 1.0, "end": 2.0, "color": "#FFEB3B"}]
        self.ctx.cache["text_annotations"] = [{"x": 5.0, "y": 0.5, "text": "peak µ", "fontsize": 10}]
        for save, key, filename in ((sidecar.save_changes, "highlights", "highlights.json"), (sidecar.save_changes, "text_annotations", "text_annotations.json")):
            with self.subTest(file=filename):
                path = pl.annotation_sidecar_path(self.folder, filename)
                app, library = self.app_writes_library_writes(lambda: save(self.ctx), path,
                                                              lambda: S.write_saved_annotations(self.folder, filename, self.ctx.cache[key]))
                self.assertEqual(app, library)

    def test_signal_names(self):
        self.ctx._signal_renames = {"main_driver": "GCaMP µ", "isosbestic": "Control"}
        app, library = self.app_writes_library_writes(lambda: sidecar.save_changes(self.ctx), pl.signal_labels_path(self.folder),
                                                      lambda: S.write_saved_signal_labels(self.folder, self.ctx._signal_renames))
        self.assertEqual(app, library)

    def test_splices(self):
        self.ctx._active_splices = [{"mode": "cut_out", "start": 10.0, "end": 12.0}]
        self.ctx.original_cache = dict(self.ctx.cache)                                    # is_spliced(): there is an original to go back to
        app, library = self.app_writes_library_writes(lambda: sidecar.save_changes(self.ctx), pl.splice_sidecar_path(self.folder),
                                                      lambda: S.write_saved_splices(self.folder, self.ctx._active_splices))
        self.assertEqual(app, library)

    def test_no_names_or_splices_remove_the_files_in_both(self):
        S.write_saved_signal_labels(self.folder, {"main_driver": "x"})
        self.ctx._signal_renames = {}
        with mock.patch("physicsanalysis_qt.edit.sidecar.show_window_toast"):
            sidecar.save_changes(self.ctx)
        self.assertFalse(os.path.exists(pl.signal_labels_path(self.folder)))
        S.write_saved_splices(self.folder, [{"mode": "cut_out", "start": 1.0, "end": 2.0}])
        self.ctx._active_splices = []
        self.ctx.original_cache = None
        with mock.patch("physicsanalysis_qt.edit.sidecar.show_window_toast"):
            sidecar.save_changes(self.ctx)
        self.assertFalse(os.path.exists(pl.splice_sidecar_path(self.folder)))

    def test_undo_all_clears_what_the_library_would_clear(self):
        S.add_marker(self.folder, 12.5)
        S.add_highlight(self.folder, 1, 2)
        sidecar.clear_json_saves(self.ctx)
        self.assertEqual(sorted(os.listdir(os.path.join(self.folder, "JSON saves"))), [])
        self.assertEqual(S.clear_saved_state(self.folder), [])


class TestTheAppRestoresWhatAScriptSaved(WindowCase, ParityCase):
    """Edits made with saved_state, then the app opens the recording (Open: the analysis engine reads it and puts the saved changes on) and
    what it shows is what opening the recording from a script gives."""

    def test_markers_highlights_text_names_and_a_splice(self):
        S.add_marker(self.folder, 12.5, label="Lever", color="red")
        S.add_highlight(self.folder, 2, 4, "Pink")
        S.add_text(self.folder, 5, 0.25, "peak", 12)
        S.rename_signals(self.folder, {"main_driver": "GCaMP"})
        S.add_splice(self.folder, "cut_out", 10.0, 12.0)

        script = pl.load_recording(self.folder)
        ctx = self.ctx                                   # opened before any of this was saved, with the main window up
        self.assertEqual((ctx._active_splices, ctx.cache["markers"]), ([], []))
        with mock.patch.object(common, "show_window_toast"), mock.patch.object(tdt, "show_window_toast"):
            tdt._load_folder(ctx, self.folder)           # (waits for the engine: the test context loads synchronously)

        self.assertEqual(ctx.cache["markers"], script["cache"]["markers"])
        self.assertEqual(ctx.cache["highlights"], script["cache"]["highlights"])
        self.assertEqual(ctx.cache["text_annotations"], script["cache"]["text_annotations"])
        self.assertEqual(ctx._active_splices, script["splices"])
        np.testing.assert_allclose(ctx.cache["x"], script["cache"]["x"])
        np.testing.assert_allclose(ctx.original_cache["x"], script["original_cache"]["x"])
        self.assertEqual(ctx.cache["signals"]["main_driver"]["label"], "GCaMP")
        self.assertEqual(script["cache"]["signals"]["main_driver"]["label"], "GCaMP")
        self.assertEqual(ctx._signal_renames, {"main_driver": "GCaMP"})
        self.assertEqual(ctx.cache["markers"][0]["label"], "Lever")


if __name__ == "__main__":
    unittest.main()
