"""What the app may rely on from a backend (backend/ports.py), checked against the real one (PyATCLI's) and against a fake. The same tests run
on both, so the fake cannot drift from the real thing, and nothing in the app can come to depend on something only the real one does."""

import inspect
import os
import tempfile
import typing
import unittest

import numpy as np
import pandas as pd

from physicsanalysis_qt import backend
from physicsanalysis_qt.backend import ports
from physicsanalysis_qt.backend.library import PyATCLIBackend

from tests.fake_backend import FakeBackend


class BackendContract:
    """Mixin: the tests every backend must pass. Subclasses say which one (make_backend)."""

    def setUp(self):
        self.b = self.make_backend()

    def test_it_has_every_member_of_every_port_and_its_methods_take_what_the_port_says(self):
        """The ports are Protocols, which nothing checks at run time: this does. Each member a port lists is there, and each method has the
        parameters (names, order, which are optional) the port gives it."""
        def members(proto):
            names = getattr(typing, "get_protocol_members", None)
            return set(names(proto)) if names else set(getattr(proto, "__protocol_attrs__", ()))

        def shape(fn, skip_self):
            params = list(inspect.signature(fn).parameters.values())[1 if skip_self else 0:]
            return [(p.name, p.kind, p.default is not inspect.Parameter.empty) for p in params]

        wanted = {**typing.get_type_hints(ports.Backend), "": ports.Backend}                       # the ports, and Backend's own members
        for attr, proto in wanted.items():
            impl = getattr(self.b, attr) if attr else self.b
            for name in sorted(members(proto)):
                if attr == "" and name in typing.get_type_hints(ports.Backend):
                    continue                                                                          # (a port, checked as itself)
                with self.subTest(port=attr or "backend", member=name):
                    self.assertTrue(hasattr(impl, name), f"{type(impl).__name__} lacks {name}")
                    declared = getattr(proto, name, None)
                    if inspect.isfunction(declared):
                        self.assertEqual(shape(getattr(impl, name), False), shape(declared, True), f"{attr}.{name}: parameters differ from the port's")

    def test_what_the_highlighter_and_text_tool_start_from(self):
        saved = self.b.saved
        self.assertTrue(saved.highlight_colors)
        self.assertTrue(all(isinstance(k, str) and isinstance(v, str) for k, v in saved.highlight_colors.items()))
        self.assertTrue(0 < saved.highlight_alpha <= 1)
        self.assertGreater(saved.default_text_font_size, 0)

    def test_a_new_marker_is_a_fresh_dict_each_time(self):
        first = self.b.saved.default_marker()
        first["label"] = "changed"
        self.assertNotEqual(self.b.saved.default_marker().get("label"), "changed")

    def test_the_two_splice_modes_are_different_words(self):
        r = self.b.recording
        self.assertIsInstance(r.splice_cut_out, str)
        self.assertNotEqual(r.splice_cut_out, r.splice_keep_inside)

    def test_there_are_curve_fit_models_to_pick_from(self):
        names = self.b.models.curve_fit_model_names()
        self.assertTrue(names)
        self.assertTrue(all(isinstance(n, str) for n in names))
        self.assertEqual(len(names), len(set(names)))

    def test_markers_are_named_and_tidied(self):
        m = self.b.markers
        self.assertIsInstance(m.store_display_name("_465A", {}), str)
        self.assertEqual(m.store_display_name("_465A", {"_465A": "Main"}), "Main")
        self.assertIsInstance(m.marker_display_label({"label": "Lever", "store": "L1P"}, {}), str)
        self.assertEqual(list(m.debounce_events([0.0, 0.1, 5.0], 1.0)), [0.0, 5.0])

    def test_the_group_choices_are_labelled(self):
        g = self.b.group
        for keys, labels in ((g.metrics, g.metric_labels), (g.corrections, g.correction_labels)):
            self.assertTrue(keys)
            self.assertTrue(set(keys) <= set(labels), "every choice offered has the words it is shown with")
        self.assertTrue(g.signals and g.peak_directions)
        self.assertIsInstance(g.settings_filename, str)

    def test_group_settings_start_with_defaults_and_take_what_is_given(self):
        g = self.b.group
        defaults = g.new_settings()
        self.assertGreater(defaults.pre, 0)
        self.assertGreater(defaults.post, 0)
        self.assertEqual(len(defaults.baseline), 2)
        self.assertEqual(len(defaults.response), 2)
        self.assertIn(defaults.signal, g.signals)
        self.assertIn(defaults.peak_direction, g.peak_directions)
        self.assertIn(defaults.correction, g.corrections)
        given = g.new_settings(group_name="G", pre=3.0, signal=g.signals[-1])
        self.assertEqual((given.group_name, given.pre, given.signal), ("G", 3.0, g.signals[-1]))
        self.assertEqual(g.new_settings().pre, defaults.pre)                                   # (nothing is shared between calls)

    def test_group_settings_say_what_is_wrong_in_words_and_save_as_a_dict(self):
        settings = self.b.group.new_settings()
        self.assertIsInstance(list(settings.problems()), list)
        self.assertIsInstance(list(settings.window_problems()), list)
        self.assertTrue(all(isinstance(p, str) for p in settings.problems()))
        saved = settings.to_dict()
        self.assertIsInstance(saved, dict)
        self.assertEqual(saved["pre"], settings.pre)

    # ---- naming signals
    def test_two_signals_cannot_share_a_name(self):
        r = self.b.recording
        self.assertIsInstance(r.name_problem({"a": "x", "b": "x"}), str)
        self.assertIsNone(r.name_problem({"a": "x", "b": "y"}))

    def test_a_rename_is_planned_without_changing_the_recording(self):
        r = self.b.recording
        cache = {"signals": {"a": {"label": "A", "y": np.zeros(3)}, "b": {"label": "B", "y": np.zeros(3)}}}
        self.assertEqual(r.plan_signal_renames(cache, {"a": "GCaMP"}), {"a": "GCaMP"})
        self.assertEqual(cache["signals"]["a"]["label"], "A")

    # ---- what the main plot shows
    def test_the_plot_has_lines_a_range_and_numbers_for_its_csv(self):
        v = self.b.view
        lo, hi = v.padded_xlim(np.array([0.0, 10.0]))
        self.assertLessEqual(lo, 0.0)
        self.assertGreaterEqual(hi, 10.0)
        x = np.arange(20.0)
        cache = {"source": "TDT", "store": "Rec", "x": x, "fs": 1.0, "markers": [], "signals": {"normalized": {"label": "Normalized (dF/F)", "y": np.sin(x)}}}
        traces, title, x_label, y_label = v.view_traces(cache)
        self.assertEqual(len(traces), 1)
        self.assertTrue(all(isinstance(t, str) for t in (title, x_label, y_label)))
        plan = v.plan_view(cache, attributes={"title": "mine"})
        self.assertEqual(plan.parameters()["attributes"], {"title": "mine"})
        self.assertTrue(len(plan.traces) >= 1 and plan.xlim[0] < plan.xlim[1])

    # ---- Group Analysis results from their tables
    def test_tables_that_are_not_a_group_analysis_are_no_results(self):
        self.assertIsNone(self.b.group.results_from_tables({"something": pd.DataFrame({"a": [1]})}))
        self.assertIsInstance(self.b.group.measure_units("auc", "dff"), str)

    # ---- the arithmetic Event PETH redoes
    def test_the_mean_and_sem_of_trials(self):
        mean, sem = self.b.stats.group_stats(np.array([[1.0, 2.0], [3.0, 4.0]]))
        np.testing.assert_allclose(mean, [2.0, 3.0])
        np.testing.assert_allclose(sem, [1.0, 1.0])

    def test_the_peaks_of_a_spectrum_and_a_signal_binned_for_a_heatmap(self):
        freqs = np.linspace(0.0, 5.0, 200)
        power = np.exp(-((freqs - 1.2) ** 2) / 0.01)
        self.assertIsInstance(list(self.b.stats.find_fft_peaks(freqs, power, n_peaks=2)), list)
        self.assertGreater(len(self.b.stats.bin_for_heatmap(np.arange(1000.0))), 0)

    def test_the_area_under_a_flat_trace(self):
        auc = self.b.stats.auc_from_trace(np.array([0.0, 1.0, 2.0]), np.array([1.0, 1.0, 1.0]))
        self.assertAlmostEqual(auc["total_auc"], 2.0)

    # ---- where an export lands
    def test_folder_names_are_safe_and_paths_are_never_overwritten(self):
        o = self.b.outputs
        self.assertNotIn("/", o.safe_folder_name("a/b"))
        self.assertIsInstance(o.source_marker_filename, str)
        with tempfile.TemporaryDirectory() as d:
            self.assertTrue(o.group_dir(d, "G").startswith(d))
            self.assertTrue(o.recording_dir(d, "TDT", os.path.join(d, "rec1")).startswith(d))
            path = os.path.join(d, "x.csv")
            self.assertEqual(o.unique_path(path), path)
            open(path, "w").close()
            self.assertNotEqual(o.unique_path(path), path)

    def test_markers_are_grouped_by_name(self):
        self.assertIsInstance(self.b.markers.group_by_name({"markers": [], "store_labels": {}}, {}), dict)

    def test_the_versions_the_error_log_starts_with(self):
        v = self.b.software_versions({"name": "PyAT", "version": "9.9.9"})
        self.assertIn("library", v)
        self.assertEqual(v["app"]["version"], "9.9.9")
        self.assertIn("python", v)


class TestThePyATCLIBackend(BackendContract, unittest.TestCase):
    def make_backend(self):
        return PyATCLIBackend()

    def test_it_is_the_one_the_app_makes_by_default(self):
        self.assertIsInstance(backend.make_backend(), PyATCLIBackend)


class TestTheFakeBackend(BackendContract, unittest.TestCase):
    def make_backend(self):
        return FakeBackend()


class TestSwappingTheBackend(unittest.TestCase):
    def setUp(self):
        self.previous = backend.use(FakeBackend())
        self.addCleanup(backend.use, self.previous)

    def test_api_follows_whichever_backend_is_in_use(self):
        self.assertEqual(backend.api.group.settings_filename, "fake_settings.json")
        backend.use(PyATCLIBackend())
        self.assertNotEqual(backend.api.group.settings_filename, "fake_settings.json")

    def test_a_window_that_asks_the_interface_gets_the_fakes_answers(self):
        from physicsanalysis_qt.edit import marker_labels
        ctx = type("Ctx", (), {"store_labels": {"L1P": "Lever"}})()
        self.assertEqual(marker_labels.store_display_name(ctx, "L1P"), "Lever")
        self.assertEqual(marker_labels.marker_display_label(ctx, {"label": "x"}), "fake:x")        # PyATCLI would not say that

    def test_use_none_makes_the_real_one_again(self):
        backend.use(None)
        self.assertIsInstance(backend.current(), PyATCLIBackend)


if __name__ == "__main__":
    unittest.main()
