"""figures/attributes.py: Edit Graph Attributes — the rules that turn what is typed or picked into the attributes a plot keeps (automatic text is no
override, sizes of at least 6, a legend entry renamed or hidden, a colour per line) and the Apply the dialog calls. (The rules for naming a signal are the
recording's: the library's tests/test_signal_names.py. PyAT's tests/test_attributes_dialog.py runs the real dialog.)"""

import copy
import unittest

from physicsanalysis_qt.figures import attributes as A
from physicsanalysis_qt.figures import view as V

NORMALIZED, MAIN = "Normalized (dF/F)", "Main Driver (x465A)"


class TestTheRules(unittest.TestCase):
    def test_text_that_is_just_the_automatic_text_is_no_override(self):
        attrs = V.default_plot_attrs()
        A.set_text_override(attrs, "title", "My title", "Auto title")
        self.assertEqual(attrs["title"], "My title")
        A.set_text_override(attrs, "title", "Auto title", "Auto title")
        self.assertIsNone(attrs["title"])

    def test_a_size_is_a_whole_number_of_points_of_at_least_six_and_nonsense_is_ignored(self):
        self.assertEqual([A.clamp_size(v, 16) for v in ("20", 20, "3", 0, "abc", "", None, "12.5")], [20, 20, 6, 6, 16, 16, 16, 16])

    def test_legend_edits_and_rows(self):
        attrs = V.default_plot_attrs()
        self.assertEqual(A.legend_edits(attrs), {})
        attrs["leg_entries"] = [("a", "A", True), ("b", "b", False)]
        self.assertEqual(A.legend_edits(attrs), {"a": ("A", True), "b": ("b", False)})
        self.assertEqual(A.legend_rows(attrs, ["a", "b", "c"]), [("a", "A", True), ("b", "b", False), ("c", "c", True)])

    def test_a_double_click_renames_the_entry_shown_like_that_and_keeps_whether_it_is_shown(self):
        attrs = V.default_plot_attrs()
        attrs["leg_entries"] = [("a", "A", True), ("b", "b", False)]
        self.assertTrue(A.rename_legend_entry(attrs, ["a", "b", "c"], "A", "Alpha"))
        self.assertEqual(attrs["leg_entries"], [("a", "Alpha", True), ("b", "b", False), ("c", "c", True)])
        self.assertTrue(A.rename_legend_entry(attrs, ["a", "b", "c"], "b", "Beta"))
        self.assertEqual(attrs["leg_entries"][1], ("b", "Beta", False))
        before = list(attrs["leg_entries"])
        self.assertFalse(A.rename_legend_entry(attrs, ["a", "b", "c"], "nothing like it", "x"))
        self.assertEqual(attrs["leg_entries"], before)

    def test_a_colour_is_filed_under_the_lines_name_and_the_default_is_no_override(self):
        attrs = V.default_plot_attrs()
        self.assertTrue(A.set_line_color(attrs, NORMALIZED, "#123456", "blue"))
        self.assertEqual(attrs["line_colors"], {NORMALIZED: "#123456"})
        self.assertFalse(A.set_line_color(attrs, NORMALIZED, "#123456", "blue"))               # unchanged
        self.assertTrue(A.set_line_color(attrs, NORMALIZED, "#0000FF", "blue"))                # the default, written another way: back to the default
        self.assertEqual(attrs["line_colors"], {})
        A.set_line_color(attrs, NORMALIZED, "red", "blue")
        self.assertTrue(A.set_line_color(attrs, NORMALIZED, None))
        self.assertEqual(attrs["line_colors"], {})
        self.assertFalse(A.set_line_color(attrs, NORMALIZED, None))

    def test_a_colour_and_a_legend_edit_follow_their_signal_to_its_new_name_and_two_can_swap(self):
        attrs = V.default_plot_attrs()
        attrs["line_colors"] = {"a": "red", "b": "blue", "marker": "green"}
        attrs["leg_entries"] = [("a", "a", False), ("b", "b", True), ("marker", "Lever", True)]
        A.migrate_names(attrs, {"a": "b", "b": "a"})
        self.assertEqual(attrs["line_colors"], {"b": "red", "a": "blue", "marker": "green"})
        self.assertEqual(attrs["leg_entries"], [("b", "b", False), ("a", "a", True), ("marker", "Lever", True)])


class TestApply(unittest.TestCase):
    AUTO = {"title": "Auto — Rec", "xlabel": "Time (s)", "ylabel": "Amplitude"}

    def apply(self, attrs=None, rename=None, **kw):
        attrs = attrs if attrs is not None else V.default_plot_attrs()
        kw.setdefault("auto", self.AUTO)
        kw.setdefault("own_names", [])
        return attrs, A.apply_edits(attrs, rename=rename or (lambda wanted: wanted), **kw)

    def test_texts_sizes_the_legend_and_bold(self):
        attrs, result = self.apply(texts={"title": " My title ", "xlabel": "Time (s)", "ylabel": ""}, sizes={"title_fs": "20", "xlabel_fs": "abc", "ylabel_fs": "2"},
                                   leg_fs="3", leg_loc="best", bold=False)
        self.assertEqual((attrs["title"], attrs["xlabel"], attrs["ylabel"]), ("My title", None, None))     # the automatic text and no text are no edit
        self.assertEqual((attrs["title_fs"], attrs["xlabel_fs"], attrs["ylabel_fs"], attrs["leg_fs"]), (20, 16, 6, 6))
        self.assertEqual((attrs["leg_loc"], attrs["bold"]), ("best", False))
        self.assertEqual((result.changes, result.renamed, result.colors_changed), ({}, {}, False))

    def test_nothing_given_changes_nothing(self):
        attrs, result = self.apply()
        self.assertEqual(attrs, V.default_plot_attrs())

    def test_legend_rows_become_the_entries_and_a_blank_text_keeps_the_name(self):
        attrs, _ = self.apply(own_names=["a", "b"], entries=[("a", "Alpha", True), ("b", "", False)])
        self.assertEqual(attrs["leg_entries"], [("a", "Alpha", True), ("b", "b", False)])

    def test_a_legend_entry_that_is_a_signals_name_renames_the_signal_and_is_then_just_called_that(self):
        asked = []

        attrs = V.default_plot_attrs()
        attrs["line_colors"] = {NORMALIZED: "#123456"}

        def rename(wanted):                                       # what the hook does: names the signals, and the attributes' names follow
            asked.append(wanted)
            changes = {k: v.strip() for k, v in wanted.items()}
            A.migrate_names(attrs, {NORMALIZED: changes["normalized"]})
            return changes

        signals = {"normalized": {"label": NORMALIZED}, "main_driver": {"label": MAIN}}
        _, result = self.apply(attrs, rename=rename, own_names=[NORMALIZED, MAIN, "lever"], signals=signals,
                               entries=[(NORMALIZED, " GCaMP ", True), (MAIN, MAIN, False), ("lever", "Lever press", True)],
                               colors=[(NORMALIZED, "#654321", "blue"), ("lever", None, "#808080")])
        self.assertEqual(asked, [{"normalized": " GCaMP "}])                                      # the marker's entry and the unchanged one are not signals' renames
        self.assertEqual((result.changes, result.renamed), ({"normalized": "GCaMP"}, {NORMALIZED: "GCaMP"}))
        self.assertEqual(attrs["leg_entries"], [("GCaMP", "GCaMP", True), (MAIN, MAIN, False), ("lever", "Lever press", True)])
        self.assertEqual(attrs["line_colors"], {"GCaMP": "#654321"})                               # the colour is filed under the new name
        self.assertTrue(result.colors_changed)

    def test_a_rename_that_is_refused_changes_nothing_at_all(self):
        def refuse(wanted):
            raise ValueError("Two signals can't both be called \"x\".")

        attrs = V.default_plot_attrs()
        before = copy.deepcopy(attrs)
        with self.assertRaisesRegex(ValueError, "both be called"):
            self.apply(attrs, rename=refuse, own_names=[NORMALIZED], signals={"normalized": {"label": NORMALIZED}}, texts={"title": "My title"},
                       sizes={"title_fs": "20"}, bold=False, entries=[(NORMALIZED, "x", True)])
        self.assertEqual(attrs, before)

    def test_only_the_colours_listed_are_touched(self):
        attrs = V.default_plot_attrs()
        attrs["line_colors"] = {"other dataset": "red"}
        _, result = self.apply(attrs, colors=[("a", "green", "blue"), ("b", None, "blue")])
        self.assertEqual(attrs["line_colors"], {"other dataset": "red", "a": "green"})
        self.assertTrue(result.colors_changed)


if __name__ == "__main__":
    unittest.main()
