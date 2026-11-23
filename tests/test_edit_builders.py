"""A marker, a highlight and a text box are made by the analysis library's own builders (backend.api.saved.new_marker, new_highlight, new_text_annotation), so
what the window stamps on a plot is what a script stamps, with the same checks: the two times of a highlight in order and different, a colour that is a colour,
a text box that says something."""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QDialog

from physicsanalysis_qt.edit import highlight, markers, text_annotation

from tests.test_workspace import WorkspaceCase


class TestMarkers(WorkspaceCase):
    def test_a_marker_is_stamped_with_a_time_a_name_a_colour_and_a_size(self):
        self.ctx.marker_stamp = {"label": "Lick", "color": "#FF0000", "fontsize": 11}
        before = len(self.ctx.cache["markers"])
        markers.place_marker(self.ctx, 12.25)
        self.assertEqual(len(self.ctx.cache["markers"]), before + 1)
        self.assertEqual(self.ctx.cache["markers"][-1], {"time": 12.25, "label": "Lick", "color": "#FF0000", "fontsize": 11})

    def test_it_is_the_librarys_own_marker(self):
        with mock.patch.object(markers.api.saved, "new_marker", wraps=markers.api.saved.new_marker) as made:
            markers.place_marker(self.ctx, 3.0)
        made.assert_called_once()
        self.assertEqual(made.call_args.args[0], 3.0)


class TestHighlights(WorkspaceCase):
    def click_twice(self, first, second):
        self.ctx._pending_highlight_color = next(iter(highlight.HIGHLIGHT_COLORS.values()))
        self.ctx.slope_clicks.clear()
        with mock.patch.object(highlight, "show_error") as error, mock.patch.object(highlight, "show_window_toast"):
            highlight.apply_highlight_at_point(self.ctx, first)
            highlight.apply_highlight_at_point(self.ctx, second)
        return error

    def test_the_two_clicks_in_either_order_make_one_highlight_from_the_earlier_to_the_later(self):
        before = len(self.ctx.cache.get("highlights", []))
        error = self.click_twice(20.0, 10.0)
        error.assert_not_called()
        made = self.ctx.cache["highlights"]
        self.assertEqual(len(made), before + 1)
        self.assertEqual((made[-1]["start"], made[-1]["end"]), (10.0, 20.0))
        self.assertEqual(made[-1]["color"], self.ctx._pending_highlight_color)

    def test_two_clicks_on_the_same_point_make_no_highlight_and_say_why(self):
        before = list(self.ctx.cache.get("highlights", []))
        error = self.click_twice(15.0, 15.0)
        error.assert_called_once()
        self.assertIn("different times", error.call_args.args[1])
        self.assertEqual(self.ctx.cache.get("highlights", []), before)
        self.assertFalse(self.ctx.highlight_click_mode)                                           # (and the mode is off: the person starts again)

    def test_a_colour_that_is_not_one_makes_no_highlight_and_says_so(self):
        self.ctx._pending_highlight_color = "chartreuse-ish"
        self.ctx.slope_clicks.clear()
        before = list(self.ctx.cache.get("highlights", []))
        with mock.patch.object(highlight, "show_error") as error, mock.patch.object(highlight, "show_window_toast"):
            highlight.apply_highlight_at_point(self.ctx, 1.0)
            highlight.apply_highlight_at_point(self.ctx, 2.0)
        error.assert_called_once()
        self.assertEqual(self.ctx.cache.get("highlights", []), before)


class TestTextBoxes(WorkspaceCase):
    def place(self, text, size):
        dialog = mock.Mock()
        dialog.exec.return_value = QDialog.DialogCode.Accepted
        dialog.values.return_value = (text, size)
        with mock.patch.object(text_annotation, "_TextAnnotationDialog", return_value=dialog), \
                mock.patch.object(text_annotation, "_set_text_mode"), mock.patch.object(text_annotation, "show_error") as error:
            text_annotation.place_text_annotation(self.ctx, 7.5, 1.25)
        return error

    def test_a_text_box_is_placed_where_it_was_clicked(self):
        before = len(self.ctx.cache.get("text_annotations", []))
        self.place("hello", 12).assert_not_called()
        made = self.ctx.cache["text_annotations"]
        self.assertEqual(len(made), before + 1)
        self.assertEqual(made[-1], {"x": 7.5, "y": 1.25, "text": "hello", "fontsize": 12})

    def test_a_size_the_library_does_not_allow_places_nothing_and_says_so(self):
        before = list(self.ctx.cache.get("text_annotations", []))
        error = self.place("hello", 3)
        error.assert_called_once()
        self.assertEqual(self.ctx.cache.get("text_annotations", []), before)


if __name__ == "__main__":
    unittest.main()
