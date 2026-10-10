"""The app's thin adapters over PyATCLI: marker names bound to the app's store renames, the saved-state
paths and what the app writes there, the loaders' signal colours, and the normalized-signal accessor. The rules
live in the library; these check the app passes it the right state and that the two layers agree about files."""

import importlib
import json
import os
import pkgutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

import PyATCLI as pl

import physicsanalysis_qt
from physicsanalysis_qt.edit import marker_labels, sidecar
from physicsanalysis_qt.edit import splice as gui_splice
from physicsanalysis_qt.analysis.event_peth import _group_markers_by_name
from physicsanalysis_qt.context import get_normalized_signal
from physicsanalysis_qt.backend.recordings import add_display_colours


def phase_marker(t, store, phase):
    return {"time": float(t), "label": store, "color": "black", "store": store, "phase": phase}


class TestStructure(unittest.TestCase):
    def test_every_module_imports(self):
        failed = []
        for m in pkgutil.walk_packages(physicsanalysis_qt.__path__, "physicsanalysis_qt."):
            try:
                importlib.import_module(m.name)
            except Exception as e:                                       # noqa: BLE001 - report them all at once
                failed.append(f"{m.name}: {type(e).__name__}: {e}")
        self.assertEqual(failed, [])

    def test_code_that_moved_to_the_library_is_not_kept_here_as_a_second_copy(self):
        for gone in ("physicsanalysis_qt.analysis.models_registry", "physicsanalysis_qt.analysis.group.scan",
                     "physicsanalysis_qt.analysis.group.recording"):
            with self.subTest(gone), self.assertRaises(ModuleNotFoundError):
                importlib.import_module(gone)
        self.assertFalse(hasattr(gui_splice, "_splice_once"))
        self.assertFalse(hasattr(gui_splice, "_spliced_store_name"))
        from physicsanalysis_qt.loading import tdt
        self.assertFalse(hasattr(tdt, "_find_tdt_subfolders"))

    def test_the_curve_fit_dialog_offers_the_librarys_models_through_the_backend(self):
        from physicsanalysis_qt import backend
        self.assertEqual(backend.api.models.curve_fit_model_names(), list(pl.CURVE_FIT_MODELS))


class TestMarkerLabels(unittest.TestCase):
    def setUp(self):
        self.ctx = SimpleNamespace(store_labels={"L1P": "Left Lever"})

    def test_they_follow_the_apps_store_renames(self):
        self.assertEqual(marker_labels.store_display_name(self.ctx, "L1P"), "Left Lever")
        self.assertEqual(marker_labels.store_display_name(self.ctx, "R1P"), "R1P")
        self.assertIsNone(marker_labels.store_display_name(self.ctx, None))
        self.assertEqual(marker_labels.marker_display_label(self.ctx, phase_marker(1, "L1P", "high")), "Left Lever¹")
        self.assertEqual(marker_labels.marker_display_label(self.ctx, phase_marker(1, "L1P", "low")), "Left Lever⁰")

    def test_a_note_keeps_its_own_text_whatever_its_store_is_called(self):
        ctx = SimpleNamespace(store_labels={"Note": "Renamed"})
        note = {"time": 5.0, "label": "Clap", "color": "black", "store": "Note"}
        self.assertEqual(marker_labels.marker_display_label(ctx, note), "Clap")

    def test_they_agree_with_the_library_exactly(self):
        for m in (phase_marker(1, "L1P", "high"), phase_marker(2, "L1P", "low"), {"time": 3.0, "label": "x", "color": "r"}):
            self.assertEqual(marker_labels.marker_display_label(self.ctx, m), pl.marker_display_label(m, self.ctx.store_labels))

    def test_event_names_come_from_the_library_grouping(self):
        cache = {"detected_markers": [phase_marker(10, "L1P", "high"), phase_marker(11, "L1P", "low")],
                 "markers": [{"time": 20.0, "label": "Clap", "color": "g"}]}
        ctx = SimpleNamespace(cache=cache, store_labels=self.ctx.store_labels)
        self.assertEqual(_group_markers_by_name(ctx), {"Left Lever¹": [10.0], "Left Lever⁰": [11.0], "Clap": [20.0]})
        self.assertEqual(_group_markers_by_name(ctx), pl.group_markers_by_name(cache, self.ctx.store_labels))


class TestSidecarAdapters(unittest.TestCase):
    """Save Changes: the engine writes (saved.write), the library reads. The context is a real one with the engine on a thread of this process,
    waiting for its answers right there."""

    @classmethod
    def setUpClass(cls):
        from PyQt6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from physicsanalysis_qt.context import AppState
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = os.path.join(self._tmp.name, "Rat7-250101")
        os.makedirs(self.folder)
        self.ctx = AppState(self.app)
        self.ctx.settings["background_loading"] = False
        self.addCleanup(lambda: self.ctx.engine.shutdown())
        self.ctx.cache = {"source_path": self.folder, "markers": []}

    def test_the_paths_are_the_libraries(self):
        self.assertEqual(sidecar.sidecar_path(self.ctx), pl.marker_sidecar_path(self.folder))

    def test_with_nothing_loaded_there_is_no_path(self):
        for cache in (None, {}, {"source_path": ""}):
            ctx = SimpleNamespace(cache=cache)
            self.assertIsNone(sidecar.sidecar_path(ctx))

    def test_markers_the_app_saves_are_the_markers_the_library_reads(self):
        markers = [{"time": 4.0, "label": "mine", "color": "green", "fontsize": 8}]
        self.ctx.cache["markers"] = markers
        with mock.patch.object(sidecar, "show_window_toast"), mock.patch.object(sidecar, "show_error") as err:
            sidecar.save_changes(self.ctx)
        err.assert_not_called()
        self.assertEqual(pl.read_saved_markers(self.folder), markers)
        self.assertIn("markers.json", os.listdir(os.path.join(self.folder, "JSON saves")))               # (reading them back is the engine's: test_loaders_engine)

    def test_splices_the_app_saves_are_the_splices_the_library_reads(self):
        splices = [{"mode": "cut_out", "start": 5.0, "end": 8.0}, {"mode": "keep_inside", "start": 1.0, "end": 50.0}]
        self.ctx._active_splices = splices
        self.ctx.original_cache = {"stands": "in"}                       # is_spliced() is "an original is being kept"
        with mock.patch.object(sidecar, "show_window_toast"), mock.patch.object(sidecar, "show_error") as err:
            sidecar.save_changes(self.ctx)
        err.assert_not_called()
        self.assertEqual(pl.read_saved_splices(self.folder), splices)

    def test_saving_with_no_splice_removes_a_stale_file(self):
        path = pl.splice_sidecar_path(self.folder)
        os.makedirs(os.path.dirname(path))
        with open(path, "w") as f:
            json.dump([{"mode": "cut_out", "start": 1.0, "end": 2.0}], f)
        with mock.patch.object(sidecar, "show_window_toast"), mock.patch.object(sidecar, "show_error"):
            sidecar.save_changes(self.ctx)
        self.assertEqual(pl.read_saved_splices(self.folder), [])


class TestSignalColours(unittest.TestCase):
    def cache(self):
        n = 50
        result = {"corr": np.zeros(n), "channels": [
            {"key": "main_driver", "label": "Main Driver (x465A)", "y": np.ones(n)},
            {"key": "isosbestic", "label": "Isosbestic (x415A)", "y": np.ones(n)},
            {"key": "some_future_channel", "label": "New", "y": np.ones(n)}]}
        return pl.make_tdt_cache("C:/d/r", {**result, "x": np.arange(50.0), "raw": np.zeros(50), "fs": 1.0})

    def test_each_option_is_the_librarys_with_a_colour_added(self):
        cache = self.cache()
        lib = {k: dict(v) for k, v in cache["signals"].items()}
        opts = add_display_colours(cache)["signals"]
        self.assertEqual(list(opts), list(lib))
        self.assertEqual({k: v["label"] for k, v in opts.items()}, {k: v["label"] for k, v in lib.items()})
        self.assertEqual(opts["normalized"]["color"], "blue")
        self.assertEqual(opts["main_driver"]["color"], "#2E7D32")                         # PyATCLI.figures.signal_color: what Export View and a script draw it in
        self.assertEqual(opts["isosbestic"]["color"], "#7B1FA2")
        self.assertEqual(opts["some_future_channel"]["color"], "#555555")                # the fallback

    def test_a_colour_already_chosen_is_kept(self):
        cache = self.cache()
        cache["signals"]["isosbestic"]["color"] = "red"
        self.assertEqual(add_display_colours(cache)["signals"]["isosbestic"]["color"], "red")

    def test_a_source_without_signals_is_left_alone(self):
        cache = {"source": "Oxysoft", "x": np.arange(3.0)}
        self.assertIs(add_display_colours(cache), cache)
        self.assertEqual(set(cache), {"source", "x"})


class TestNormalizedSignal(unittest.TestCase):
    def test_it_is_the_normalized_trace_whatever_is_plotted(self):
        signals = {"normalized": {"label": "N", "y": np.zeros(3), "color": "blue"},
                   "main_driver": {"label": "MD", "y": np.ones(3), "color": "#2E7D32"}}
        ctx = SimpleNamespace(cache={"signals": signals}, plot_signal="main_driver")
        key, label, y, color = get_normalized_signal(ctx)
        self.assertEqual((key, label, color), ("normalized", "N", "blue"))
        np.testing.assert_array_equal(y, np.zeros(3))

    def test_a_source_with_no_signals_map_is_blue_dff(self):
        ctx = SimpleNamespace(cache={"corr": np.ones(4)})
        self.assertEqual(get_normalized_signal(ctx)[:2], ("normalized", "dF/F (corrected)"))
        self.assertEqual(get_normalized_signal(ctx)[3], "blue")


if __name__ == "__main__":
    unittest.main()
