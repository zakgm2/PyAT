"""Ctrl+Z (edit/undo.py): a text box or a highlight that was placed, deleted or moved comes back as it was — its text, its place — not as it is now.
(The snapshot used to keep the same list of text boxes and highlights as the plot, so an undo "restored" the edited one.)"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QDialog

from physicsanalysis_qt.edit import highlight, text_annotation, undo

from tests.test_gui_reproduces import WindowCase


class UndoCase(WindowCase):
    def setUp(self):
        super().setUp()
        self.ctx.cache["text_annotations"] = [{"x": 10.0, "y": 1.0, "text": "first", "fontsize": 10}, {"x": 20.0, "y": 2.0, "text": "second", "fontsize": 12}]
        self.ctx.cache["highlights"] = [{"start": 5.0, "end": 8.0, "color": "#FFEB3B"}]
        self.ctx.cache["markers"] = [{"time": 15.0, "label": "lever", "color": "green", "fontsize": 8, "label_y": 0.5}]
        self.original = {"text": [dict(t) for t in self.ctx.cache["text_annotations"]], "highlights": [dict(h) for h in self.ctx.cache["highlights"]]}

    def texts(self):
        return self.ctx.cache["text_annotations"]


class TestTextBoxes(UndoCase):
    def test_a_moved_text_box_goes_back_to_where_it_was(self):
        before = undo.snapshot(self.ctx)
        self.texts()[0].update(x=55.0, y=9.0)                                       # a drag rewrites the box's own x and y
        undo.push(self.ctx, "moved a text box", before)
        self.assertEqual(undo.undo(self.ctx), "moved a text box")
        self.assertEqual(self.texts(), self.original["text"])

    def test_a_deleted_text_box_comes_back(self):
        text_annotation.delete_text_annotation(self.ctx, self.texts()[1])
        self.assertEqual(len(self.texts()), 1)
        self.assertEqual(undo.undo(self.ctx), "deleted a text box")
        self.assertEqual(self.texts(), self.original["text"])

    def test_a_placed_text_box_goes_away(self):
        class Dialog:
            def __init__(inner, parent):
                pass

            def exec(inner):
                return QDialog.DialogCode.Accepted

            def values(inner):
                return "new box", 14

        with mock.patch.object(text_annotation, "_TextAnnotationDialog", Dialog):
            text_annotation.place_text_annotation(self.ctx, 30.0, 3.0)
        self.assertEqual(len(self.texts()), 3)
        self.assertEqual(undo.undo(self.ctx), "added a text box")
        self.assertEqual(self.texts(), self.original["text"])

    def test_several_edits_are_undone_one_at_a_time_in_reverse(self):
        for new_x in (31.0, 32.0, 33.0):
            before = undo.snapshot(self.ctx)
            self.texts()[0]["x"] = new_x
            undo.push(self.ctx, f"moved to {new_x}", before)
        self.assertEqual([undo.undo(self.ctx) for _ in range(3)], ["moved to 33.0", "moved to 32.0", "moved to 31.0"])
        self.assertEqual(self.texts()[0]["x"], 10.0)
        self.assertIsNone(undo.undo(self.ctx))

    def test_the_text_box_is_back_on_the_plot_not_just_in_the_cache(self):
        before = undo.snapshot(self.ctx)
        self.texts()[0].update(x=55.0, y=9.0)
        undo.push(self.ctx, "moved a text box", before)
        undo.undo(self.ctx)
        placed = {t["text"]: artist.get_position() for t, artist in self.ctx._text_annotation_artists}
        self.assertEqual(placed["first"], (10.0, 1.0))


class TestHighlights(UndoCase):
    def test_a_deleted_highlight_comes_back(self):
        highlight.delete_highlight(self.ctx, self.ctx.cache["highlights"][0])
        self.assertEqual(self.ctx.cache["highlights"], [])
        self.assertEqual(undo.undo(self.ctx), "deleted a highlight")
        self.assertEqual(self.ctx.cache["highlights"], self.original["highlights"])

    def test_a_highlight_that_was_added_goes_away(self):
        self.ctx._pending_highlight_color = "#FF4D94"
        highlight.apply_highlight_at_point(self.ctx, 40.0)
        highlight.apply_highlight_at_point(self.ctx, 45.0)
        self.assertEqual(len(self.ctx.cache["highlights"]), 2)
        self.assertEqual(undo.undo(self.ctx), "added a highlight")
        self.assertEqual(self.ctx.cache["highlights"], self.original["highlights"])


class TestMarkersStillUndoToo(UndoCase):
    def test_a_dragged_marker_label_goes_back_to_its_height(self):
        before = undo.snapshot(self.ctx)
        self.ctx.cache["markers"][0]["label_y"] = 0.9
        undo.push(self.ctx, "moved a marker label", before)
        undo.undo(self.ctx)
        self.assertEqual(self.ctx.cache["markers"][0]["label_y"], 0.5)


if __name__ == "__main__":
    unittest.main()
