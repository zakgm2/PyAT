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

    def test_a_new_marker_has_a_time_a_name_a_colour_and_a_size(self):
        marker = self.b.saved.new_marker(12.5, label="Lick", color="#FF0000", fontsize=10)
        self.assertEqual(marker, {"time": 12.5, "label": "Lick", "color": "#FF0000", "fontsize": 10})
        plain = self.b.saved.new_marker(3)
        self.assertEqual(plain["time"], 3.0)
        self.assertTrue(plain["label"] and plain["color"] and plain["fontsize"])                   # (what is left out is the default)
        with self.assertRaises(ValueError):
            self.b.saved.new_marker("soon")

    def test_a_new_highlight_runs_from_the_earlier_time_to_the_later_one(self):
        colour = next(iter(self.b.saved.highlight_colors.values()))
        self.assertEqual(self.b.saved.new_highlight(9, 4, colour), {"start": 4.0, "end": 9.0, "color": colour})
        with self.assertRaises(ValueError):
            self.b.saved.new_highlight(5, 5, colour)                                               # (nothing between two equal times)

    def test_a_new_text_box_has_to_say_something(self):
        box = self.b.saved.new_text_annotation(10, 2.5, "  hello ", 12)
        self.assertEqual((box["x"], box["y"], box["text"], box["fontsize"]), (10.0, 2.5, "hello", 12))
        with self.assertRaises(ValueError):
            self.b.saved.new_text_annotation(10, 2.5, "   ")

    def test_trimming_the_ends_leaves_the_range_between_them(self):
        x = [0.0, 10.0, 20.0, 40.0]
        self.assertEqual(self.b.recording.trim_range(x, 5.0, 3.0), (5.0, 37.0))
        for first, last in ((0.0, 0.0), (-1.0, 2.0), (20.0, 20.0)):
            with self.assertRaises(ValueError, msg=(first, last)):
                self.b.recording.trim_range(x, first, last)

    def test_a_duration_is_said_in_seconds_then_minutes(self):
        self.assertEqual(self.b.recording.describe_duration(44.0), "44 s")
        self.assertEqual(self.b.recording.describe_duration(150.0), "2.5 min")

    def test_a_groups_values_have_a_mean_a_spread_and_quartiles(self):
        s = self.b.group.summary_stats([1.0, 2.0, 4.0, 8.0, 16.0])
        self.assertEqual(s["n"], 5)
        self.assertAlmostEqual(s["mean"], 6.2)
        self.assertEqual(set(s), {"n", "mean", "sem", "q1", "median", "q3"})
        self.assertEqual(self.b.group.summary_stats([])["n"], 0)

    def test_the_points_of_a_normal_qq_plot_and_its_line(self):
        qq = self.b.group.normal_qq([0.5, -1.0, 2.0, 0.1, -0.3])
        self.assertEqual(set(qq), {"theoretical", "ordered", "slope", "intercept"})
        self.assertEqual(len(qq["theoretical"]), len(qq["ordered"]))

    def test_a_p_value_is_written_as_stars(self):
        self.assertEqual(self.b.group.significance_stars(float("nan")), "")
        self.assertEqual(self.b.group.significance_stars(0.7), "ns")
        self.assertTrue(self.b.group.significance_stars(0.0001).startswith("*"))

    def test_markers_are_pooled_into_one_value_per_subject_for_a_group(self):
        import pandas as pd
        means = pd.DataFrame([{"measure": "auc", "subject": "s1", "marker": "A", "mean": 1.0}])
        out = self.b.group.pooled_subject_values(means, "auc", {"A": ["A"], "Z": ["Z"]})
        self.assertEqual(list(out), ["A", "Z"])                                                   # (every label, in the order given)

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

    def test_bins_are_named_by_their_edges_with_decimals_enough_to_tell_them_apart(self):
        def edges(width, n):
            return [{"bin_start": k * width, "bin_end": (k + 1) * width, "mean": 0.0} for k in range(n)]
        self.assertEqual(self.b.stats.bin_ranges(edges(1.0, 3)), ["0.0-1.0", "1.0-2.0", "2.0-3.0"])
        self.assertEqual(self.b.stats.bin_ranges(edges(0.05, 3)), ["0.00-0.05", "0.05-0.10", "0.10-0.15"])
        names = self.b.stats.bin_ranges(edges(0.01, 2000))
        self.assertEqual((len(set(names)), names[0], names[-1]), (2000, "0.00-0.01", "19.99-20.00"))
        self.assertEqual(self.b.stats.bin_ranges([]), [])

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

    # ---- the processing pipeline's choices
    def test_the_pipelines_choices_come_as_data_the_options_window_can_show(self):
        described = self.b.pipeline.describe()
        self.assertIsInstance(described["steps"], list)
        names = []
        for step in described["steps"]:
            self.assertTrue({"name", "title", "sources", "options"} <= set(step))
            self.assertTrue(step["sources"] is None or isinstance(step["sources"], list))
            for option in step["options"]:
                self.assertTrue({"name", "key", "kind", "default", "label", "doc", "choices", "minimum", "maximum", "unit"} <= set(option), option)
                self.assertIn(option["kind"], ("choice", "bool", "float", "int", "seconds_or_none"))
                self.assertTrue(option["name"].startswith(step["name"] + "."))
                names.append(option["name"])
        self.assertEqual(sorted(described["defaults"]), sorted(names))                     # every option has a default, and nothing else does
        for step in described["steps"]:
            for option in step["options"]:
                self.assertEqual(described["defaults"][option["name"]], option["default"])

    def test_it_says_why_a_set_of_pipeline_options_cannot_be_used(self):
        pipeline = self.b.pipeline
        self.assertIsNone(pipeline.problem({}))
        self.assertIsNone(pipeline.problem(pipeline.describe()["defaults"]))
        reason = pipeline.problem({"no.such.option": 1})
        self.assertIsInstance(reason, str)
        self.assertIn("no.such.option", reason)

    def test_group_settings_carry_the_pipeline_options_and_start_the_smoothing_from_them(self):
        g = self.b.group
        self.assertEqual(g.new_settings().pipeline, {})
        seeded = g.new_settings(pipeline={"smoothing.window_s": 1.5})
        self.assertEqual(seeded.pipeline, {"smoothing.window_s": 1.5})
        self.assertEqual(seeded.smooth_seconds, 1.5)
        self.assertEqual(g.new_settings(pipeline={"smoothing.window_s": 1.5}, smooth_seconds=0.2).smooth_seconds, 0.2)         # (what is given is used)
        self.assertEqual(g.new_settings(pipeline={"smoothing.window_s": 1.5}).to_dict()["pipeline"], {"smoothing.window_s": 1.5})

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
