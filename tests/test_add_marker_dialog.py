"""Add Marker's two ways of putting markers on the plot (edit/markers.py) both have a font size for the names written along them: the stores' auto-detected
markers (Add Selected) as well as the custom ones (Place Custom Markers / Start Placing)."""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from physicsanalysis_qt.edit import markers
from physicsanalysis_qt.edit.markers import AddMarkerDialog, DEFAULT_MARKER_FONT_SIZE, marker_font_size

from tests.test_gui_reproduces import WindowCase


class TestFontSizeFromWhatWasTyped(unittest.TestCase):
    def test_a_whole_number_of_points_not_below_four(self):
        self.assertEqual([marker_font_size(t) for t in ("12", " 9 ", "4", "3", "0", "-5")], [12, 9, 4, 4, 4, 4])

    def test_what_is_not_a_number_is_the_default(self):
        self.assertEqual([marker_font_size(t) for t in ("", "big", "1.5", None)], [DEFAULT_MARKER_FONT_SIZE] * 4)
        self.assertEqual(marker_font_size("big", default=11), 11)


class TestAutoDetectedMarkers(WindowCase):
    def setUp(self):
        super().setUp()
        self.ctx.cache["markers"] = []
        for name in ("show_success", "show_error"):
            patcher = mock.patch.object(markers, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.dlg = AddMarkerDialog(self.ctx)
        self.assertIsNotNone(self.dlg.store_list, "the fixture recording has a store of detected markers")
        self.dlg.store_list.item(0).setSelected(True)

    def add(self, size=None):
        if size is not None:
            self.dlg.e_auto_fontsize.setText(size)
        self.dlg._add_selected_stores()
        return self.ctx.cache["markers"]

    def test_the_dialog_offers_a_font_size_for_them_starting_at_the_size_they_have_always_had(self):
        self.assertEqual(self.dlg.e_auto_fontsize.text(), str(DEFAULT_MARKER_FONT_SIZE))
        self.assertEqual(DEFAULT_MARKER_FONT_SIZE, 8)

    def test_left_alone_they_are_written_at_eight_as_before(self):
        added = self.add()
        self.assertTrue(added)
        self.assertEqual({m["fontsize"] for m in added}, {8})
        self.assertEqual({t.get_fontsize() for _m, t in self.ctx._marker_label_artists}, {8})

    def test_the_size_chosen_is_the_size_of_every_name_that_was_added(self):
        added = self.add("14")
        self.assertEqual({m["fontsize"] for m in added}, {14})
        self.assertEqual({t.get_fontsize() for _m, t in self.ctx._marker_label_artists}, {14})

    def test_a_size_that_is_not_a_number_or_too_small_is_made_usable(self):
        self.assertEqual({m["fontsize"] for m in self.add("two")}, {8})
        self.ctx.cache["markers"] = []
        self.dlg = AddMarkerDialog(self.ctx)
        self.dlg.store_list.item(0).setSelected(True)
        self.assertEqual({m["fontsize"] for m in self.add("1")}, {4})

    def test_only_the_markers_added_get_it_the_ones_already_there_keep_theirs(self):
        self.ctx.cache["markers"] = [{"time": 1.0, "label": "mine", "color": "red", "fontsize": 20}]
        added = self.add("12")
        self.assertEqual(added[0], {"time": 1.0, "label": "mine", "color": "red", "fontsize": 20})
        self.assertEqual({m["fontsize"] for m in added[1:]}, {12})

    def test_the_font_size_of_the_custom_markers_is_its_own(self):
        self.dlg.e_auto_fontsize.setText("14")
        self.dlg.e_fontsize.setText("11")
        self.dlg._start()
        self.assertEqual(self.ctx.marker_stamp["fontsize"], 11)
        self.assertEqual(self.dlg.e_auto_fontsize.text(), "14")


if __name__ == "__main__":
    unittest.main()
