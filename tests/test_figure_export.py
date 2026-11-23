"""Exporting a figure for a manuscript (export/figure_export.py; the writing itself is figures.render): the dialog
that asks, the app naming itself in what it writes, and the whole flow: edited labels reach the
file and the data CSV and not the live figure, the choices are remembered, and the provenance record lists everything."""

import ast
import glob
import io
import json
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PIL import Image
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QPushButton

from matplotlib.figure import Figure

from physicsanalysis_qt import figures

from physicsanalysis_qt import __version__, analysis
from physicsanalysis_qt.export import figure_export
from physicsanalysis_qt.analysis import dispatch

from tests.test_gui_reproduces import GuiCase


def event_like_figure():
    """The shape of the Event PETH figure: a heatmap with a colour bar above a mean trace with its SEM band."""
    fig = Figure()
    heat, line = fig.subplots(2, 1)
    im = heat.imshow(np.arange(12.0).reshape(3, 4), aspect="auto", extent=[-2, 2, 3.5, 0.5])
    heat.set_ylabel("Trial")
    heat.pyat_panel = "Trials heatmap"
    fig.colorbar(im, ax=heat, label="Z-score")
    x = np.linspace(-2, 2, 20)
    line.plot(x, np.sin(x), label="Mean")
    line.fill_between(x, np.sin(x) - 0.1, np.sin(x) + 0.1, alpha=0.2, label="SEM")
    line.set_xlabel("Time from Event (s)")
    line.set_ylabel("Z-Score (Mode)")
    line.legend()
    line.pyat_panel = "Group trace"
    fig.suptitle("Event PETH — L1P")
    return fig


class TestRememberedSettings(GuiCase):
    def test_a_fresh_install_starts_with_the_defaults(self):
        self.assertEqual(figure_export.remembered_settings(self.ctx), figure_export.DEFAULTS)
        self.assertEqual(figure_export.DEFAULTS, {"format": "png", "dpi": 300, "transparent": False, "editable_text": True, "data_csv": True})

    def test_what_was_saved_comes_back(self):
        saved = {"format": "svg", "dpi": 600, "transparent": True, "editable_text": False, "data_csv": False}
        self.ctx.settings["figure_export"] = dict(saved)
        self.assertEqual(figure_export.remembered_settings(self.ctx), saved)

    def test_nonsense_in_the_settings_file_is_ignored_value_by_value(self):
        self.ctx.settings["figure_export"] = {"format": "bmp", "dpi": 5, "transparent": "yes", "editable_text": False, "extra": 1}
        self.assertEqual(figure_export.remembered_settings(self.ctx), {**figure_export.DEFAULTS, "editable_text": False})
        self.ctx.settings["figure_export"] = {"dpi": 5000}
        self.assertEqual(figure_export.remembered_settings(self.ctx)["dpi"], 300)
        self.ctx.settings["figure_export"] = "not a dict at all"
        self.assertEqual(figure_export.remembered_settings(self.ctx), figure_export.DEFAULTS)

    def test_the_setting_is_one_of_the_apps_known_settings_so_it_is_saved_and_loaded(self):
        from physicsanalysis_qt import context
        self.assertIn("figure_export", context.default_settings())


class TestDialog(GuiCase):
    def dialog(self, fig=None, **kw):
        return figure_export.FigureExportDialog(self.ctx, fig or event_like_figure(), **kw)

    def test_it_opens_on_the_defaults_and_offers_every_label(self):
        dlg = self.dialog()
        self.assertEqual(dlg.settings(), figure_export.DEFAULTS)
        self.assertEqual([i.caption for i in dlg.fields][:2], ["Figure title", "Trials heatmap: Y label"])
        self.assertEqual(dlg.edits(), {})

    def test_it_opens_on_the_last_choices(self):
        self.ctx.settings["figure_export"] = {"format": "pdf", "dpi": 600, "transparent": True, "editable_text": False, "data_csv": False}
        dlg = self.dialog()
        self.assertEqual(dlg.settings(), {"format": "pdf", "dpi": 600, "transparent": True, "editable_text": False, "data_csv": False})

    def test_only_the_fields_that_were_changed_are_edits(self):
        dlg = self.dialog()
        item = next(i for i in dlg.fields if i.caption == "Group trace: Y label")
        dlg.fields[item].setText("Z (a.u.)")
        self.assertEqual(dlg.edits(), {item: "Z (a.u.)"})
        dlg.fields[item].setText(item.text)
        self.assertEqual(dlg.edits(), {})

    def test_the_text_option_only_applies_to_vector_formats(self):
        dlg = self.dialog()
        for key, enabled in (("png", False), ("pdf", True), ("svg", True), ("tiff", False)):
            dlg.format_combo.setCurrentIndex(dlg.format_combo.findData(key))
            self.assertEqual(dlg.cb_editable.isEnabled(), enabled, key)

    def test_the_preview_is_drawn_and_says_how_big_the_file_will_be(self):
        dlg = self.dialog()
        self.assertFalse(dlg.preview.pixmap().isNull())
        w_in, h_in = dlg._preview_size_in
        self.assertIn(f"{round(w_in * 300)} × {round(h_in * 300)} px at 300 dpi", dlg.size_label.text())
        dlg.dpi_spin.setValue(600)
        self.assertIn(f"{round(w_in * 600)} × {round(h_in * 600)} px at 600 dpi", dlg.size_label.text())
        dlg.format_combo.setCurrentIndex(dlg.format_combo.findData("pdf"))
        self.assertTrue(dlg.size_label.text().endswith("vector"))
        self.assertIn(f"{w_in * 25.4:.0f} × {h_in * 25.4:.0f} mm", dlg.size_label.text())

    def test_changing_a_label_redraws_the_preview_a_moment_later(self):
        dlg = self.dialog()
        item = next(iter(dlg.fields))
        dlg.fields[item].setText("something else")
        self.assertTrue(dlg._timer.isActive())

    def test_a_preview_that_fails_does_not_stop_an_export(self):
        with mock.patch.object(figures, "render_figure", side_effect=RuntimeError("no renderer")), \
                mock.patch.object(figure_export.errorlog, "error") as logged:
            dlg = self.dialog()
        self.assertEqual(dlg.preview.text(), "(no preview)")
        self.assertEqual(dlg.size_label.text(), "")
        logged.assert_called()

    def test_a_figure_with_no_words_has_no_label_section(self):
        from matplotlib.figure import Figure
        fig = Figure()
        fig.subplots().plot([0, 1], [0, 1])
        dlg = self.dialog(fig)
        self.assertEqual(dlg.fields, {})
        self.assertEqual(dlg.edits(), {})

    def test_a_figure_with_no_data_to_save_hides_the_option(self):
        dlg = self.dialog(has_data=False)
        self.assertFalse(dlg.settings()["data_csv"])


class TestSizeControls(GuiCase):
    """The Size group: sliders (and boxes) for the width and height, off by default, not remembered."""

    def dialog(self, size=None, **kw):
        fig = event_like_figure()
        if size:
            fig.set_size_inches(*size)
        return figure_export.FigureExportDialog(self.ctx, fig, **kw)

    def test_it_starts_off_showing_the_size_the_figure_has_on_screen(self):
        dlg = self.dialog(size=(7.4, 5.1))
        self.assertFalse(dlg.cb_size.isChecked())
        self.assertFalse(dlg.size_controls.isEnabled())
        self.assertIsNone(dlg.custom_size())
        self.assertNotIn("size", dlg.settings())
        self.assertEqual((dlg.width_spin.value(), dlg.height_spin.value()), (7.4, 5.1))
        self.assertEqual((dlg.width_slider.value(), dlg.height_slider.value()), (74, 51))

    def test_a_figure_bigger_or_smaller_than_the_sliders_reach_starts_at_their_end(self):
        dlg = self.dialog(size=(45.0, 0.4))
        self.assertEqual((dlg.width_spin.value(), dlg.height_spin.value()), (30.0, 1.0))

    def test_switching_it_on_enables_the_sliders_and_the_choice_carries_the_size(self):
        dlg = self.dialog(size=(7.0, 5.0))
        dlg.cb_size.setChecked(True)
        self.assertTrue(dlg.size_controls.isEnabled())
        self.assertEqual(dlg.settings()["size"], (7.0, 5.0))
        dlg.cb_size.setChecked(False)
        self.assertNotIn("size", dlg.settings())

    def test_a_slider_moves_its_box_and_a_box_moves_its_slider(self):
        dlg = self.dialog(size=(7.0, 5.0))
        dlg.cb_size.setChecked(True)
        dlg.width_slider.setValue(120)
        self.assertEqual(dlg.width_spin.value(), 12.0)
        self.assertEqual(dlg.height_spin.value(), 5.0)                                   # the other dimension is its own
        dlg.height_spin.setValue(3.25)
        self.assertEqual(dlg.height_slider.value(), 32)                                  # the slider moves in tenths of an inch
        self.assertEqual(dlg.settings()["size"], (12.0, 3.25))                           # the box keeps the hundredths

    def test_the_limits_are_one_to_thirty_inches(self):
        dlg = self.dialog(size=(7.0, 5.0))
        dlg.cb_size.setChecked(True)
        dlg.width_slider.setValue(10_000)
        dlg.height_slider.setValue(-5)
        self.assertEqual(dlg.settings()["size"], (30.0, 1.0))

    def test_keep_proportions_moves_the_other_dimension_with_it(self):
        dlg = self.dialog(size=(8.0, 4.0))
        dlg.cb_size.setChecked(True)
        dlg.cb_keep.setChecked(True)
        dlg.width_slider.setValue(120)
        self.assertEqual(dlg.settings()["size"], (12.0, 6.0))
        dlg.height_spin.setValue(3.0)
        self.assertEqual(dlg.settings()["size"], (6.0, 3.0))
        dlg.cb_keep.setChecked(False)
        dlg.width_slider.setValue(100)
        self.assertEqual(dlg.settings()["size"], (10.0, 3.0))                            # free again

    def test_the_shape_kept_is_the_one_it_has_when_the_box_is_ticked(self):
        dlg = self.dialog(size=(8.0, 4.0))
        dlg.cb_size.setChecked(True)
        dlg.width_slider.setValue(60)
        dlg.height_slider.setValue(60)                                                   # a square, set by hand
        dlg.cb_keep.setChecked(True)
        dlg.width_slider.setValue(90)
        self.assertEqual(dlg.settings()["size"], (9.0, 9.0))

    def test_a_kept_shape_stops_where_the_other_dimension_reaches_its_limit(self):
        dlg = self.dialog(size=(8.0, 4.0))
        dlg.cb_size.setChecked(True)
        dlg.cb_keep.setChecked(True)
        dlg.width_slider.setValue(300)                                                   # 30 in wide would be 15 in tall: fine
        self.assertEqual(dlg.settings()["size"], (30.0, 15.0))
        dlg.height_slider.setValue(300)                                                  # 30 in tall would be 60 in wide: stops at 30 wide
        self.assertEqual(dlg.settings()["size"], (30.0, 15.0))
        dlg.width_slider.setValue(10)                                                    # 1 in wide would be 0.5 in tall: stops at 1 tall
        self.assertEqual(dlg.settings()["size"], (2.0, 1.0))

    def test_as_shown_puts_the_sliders_back(self):
        dlg = self.dialog(size=(7.0, 5.0))
        dlg.cb_size.setChecked(True)
        dlg.width_slider.setValue(200)
        dlg.height_slider.setValue(20)
        dlg.btn_as_shown.click()
        self.assertEqual(dlg.settings()["size"], (7.0, 5.0))
        dlg.cb_keep.setChecked(True)
        dlg.width_slider.setValue(140)
        self.assertEqual(dlg.settings()["size"], (14.0, 10.0))                           # and its shape is the figure's again

    def test_the_label_says_the_exact_pixels_and_follows_the_sliders_the_dpi_and_the_format(self):
        dlg = self.dialog(size=(7.0, 5.0))
        dlg.cb_size.setChecked(True)
        dlg.width_slider.setValue(33)
        dlg.height_slider.setValue(23)
        self.assertIn("990 × 690 px at 300 dpi  (3.30 × 2.30 in, 84 × 58 mm)", dlg.size_label.text())
        dlg.dpi_spin.setValue(600)
        self.assertIn("1980 × 1380 px at 600 dpi", dlg.size_label.text())
        dlg.format_combo.setCurrentIndex(dlg.format_combo.findData("pdf"))
        self.assertEqual(dlg.size_label.text(), "3.30 × 2.30 in (84 × 58 mm), vector")

    def test_the_preview_is_drawn_at_the_size_set(self):
        dlg = self.dialog(size=(7.0, 5.0))
        dlg.cb_size.setChecked(True)
        dlg.width_slider.setValue(120)
        dlg.height_slider.setValue(40)
        dlg._render_preview()
        w, h = dlg._preview_size_in
        self.assertAlmostEqual(w, 12.0, delta=0.02)
        self.assertAlmostEqual(h, 4.0, delta=0.02)
        self.assertFalse(dlg.preview.pixmap().isNull())

    def test_moving_a_slider_redraws_the_preview_a_moment_later(self):
        dlg = self.dialog(size=(7.0, 5.0))
        dlg.cb_size.setChecked(True)
        dlg._timer.stop()
        dlg.width_slider.setValue(100)
        self.assertTrue(dlg._timer.isActive())
        dlg._timer.stop()
        dlg.btn_as_shown.click()
        self.assertTrue(dlg._timer.isActive())

    def test_the_preview_is_redrawn_while_a_slider_is_dragged_not_only_when_it_stops(self):
        dlg = self.dialog(size=(7.0, 5.0))
        dlg.cb_size.setChecked(True)
        dlg._timer.stop()
        with mock.patch.object(figures, "render_figure", wraps=figures.render_figure) as draw:
            for step in range(40):                                                       # a steady drag: a change every 25 ms for a second
                dlg.width_slider.setValue(70 + step)
                QTest.qWait(25)
            drawn_while_dragging = draw.call_count
            QTest.qWait(700)                                                             # let go
        self.assertGreaterEqual(drawn_while_dragging, 1)                                 # (waiting for a pause would draw nothing yet)
        w, h = dlg._preview_size_in                                                      # and wherever the drag ended is what is drawn once it is over
        self.assertAlmostEqual(w, 10.9, delta=0.02)
        self.assertFalse(dlg._timer.isActive())

    def test_a_drawing_that_is_already_due_is_not_pushed_back_by_the_next_move(self):
        dlg = self.dialog(size=(7.0, 5.0))
        dlg.cb_size.setChecked(True)
        dlg._timer.stop()
        dlg._last_draw_ms = 0.0
        timer = dlg._timer = mock.Mock()
        timer.isActive.return_value = False
        dlg.width_slider.setValue(100)
        timer.start.assert_called_once_with(figure_export.LIVE_PREVIEW_MS)               # nothing due: one is scheduled
        timer.start.reset_mock()
        timer.isActive.return_value = True
        timer.remainingTime.return_value = 20
        dlg.width_slider.setValue(101)
        dlg.height_slider.setValue(60)
        timer.start.assert_not_called()                                                  # it will show the latest size when it comes
        timer.remainingTime.return_value = 250                                           # a title being typed is due much later:
        dlg.width_slider.setValue(102)
        timer.start.assert_called_once_with(figure_export.LIVE_PREVIEW_MS)               # the slider's drawing is brought forward

    def test_the_wait_between_drawings_follows_how_long_a_drawing_takes(self):
        dlg = self.dialog(size=(7.0, 5.0))
        dlg.cb_size.setChecked(True)
        self.assertGreater(dlg._last_draw_ms, 0.0)                                       # measured when the preview is drawn
        dlg._timer.stop()
        timer = dlg._timer = mock.Mock()
        timer.isActive.return_value = False
        for took, wait in ((5.0, figure_export.LIVE_PREVIEW_MS), (100.0, 200), (200.0, 400), (5000.0, figure_export.LIVE_PREVIEW_MAX_MS)):
            dlg._last_draw_ms = took
            timer.start.reset_mock()
            dlg.width_slider.setValue(dlg.width_slider.value() + 1)
            timer.start.assert_called_once_with(wait)

    def test_typing_in_a_box_or_a_label_still_waits_for_a_pause(self):
        dlg = self.dialog(size=(7.0, 5.0))
        dlg.cb_size.setChecked(True)
        dlg._timer.stop()
        item = next(iter(dlg.fields))
        dlg.fields[item].setText("something else")
        self.assertTrue(dlg._timer.isActive())
        self.assertEqual(dlg._timer.interval(), figure_export.TYPING_PREVIEW_MS)

    def test_too_many_pixels_is_said_and_cannot_be_exported_until_it_is_made_smaller(self):
        dlg = self.dialog(size=(7.0, 5.0))
        dlg.cb_size.setChecked(True)
        dlg.dpi_spin.setValue(1200)
        dlg.width_slider.setValue(300)
        dlg.height_slider.setValue(300)
        self.assertTrue(dlg.size_label.text().startswith("Too large: 1296 megapixels"))
        self.assertFalse(dlg.export_button.isEnabled())
        dlg.format_combo.setCurrentIndex(dlg.format_combo.findData("pdf"))               # a vector file has no pixels to run out of
        self.assertTrue(dlg.export_button.isEnabled())
        dlg.format_combo.setCurrentIndex(dlg.format_combo.findData("png"))
        self.assertFalse(dlg.export_button.isEnabled())
        dlg.dpi_spin.setValue(300)
        self.assertTrue(dlg.export_button.isEnabled())
        self.assertFalse(dlg.size_label.text().startswith("Too large"))
        dlg.dpi_spin.setValue(1200)
        dlg.cb_size.setChecked(False)                                                    # not setting a size: the figure as it is
        self.assertTrue(dlg.export_button.isEnabled())

    def test_the_size_is_not_one_of_the_remembered_choices(self):
        dlg = self.dialog(size=(7.0, 5.0))
        dlg.cb_size.setChecked(True)
        dlg.width_slider.setValue(120)
        self.assertEqual({k: dlg.settings()[k] for k in figure_export.DEFAULTS}, figure_export.DEFAULTS)
        self.assertEqual(figure_export.remembered_settings(self.ctx), figure_export.DEFAULTS)


class TestPointSizeControls(GuiCase):
    """The Points group: a slider (and a box) for how large the points are drawn; 100% is as drawn, and it is not remembered."""

    def dialog(self, fig=None):
        from tests.test_figure_render import points_figure
        return figure_export.FigureExportDialog(self.ctx, fig or points_figure())

    def test_it_starts_as_drawn_and_adds_nothing_to_the_choices(self):
        dlg = self.dialog()
        self.assertTrue(dlg.has_points)
        self.assertEqual((dlg.point_slider.value(), dlg.point_spin.value()), (100, 100))
        self.assertIsNone(dlg.custom_point_scale())
        self.assertNotIn("point_scale", dlg.settings())
        self.assertEqual({k: dlg.settings()[k] for k in figure_export.DEFAULTS}, figure_export.DEFAULTS)

    def test_a_slider_moves_its_box_and_a_box_moves_its_slider_and_the_choice_carries_the_size(self):
        dlg = self.dialog()
        dlg.point_slider.setValue(150)
        self.assertEqual(dlg.point_spin.value(), 150)
        self.assertEqual(dlg.settings()["point_scale"], 1.5)
        dlg.point_spin.setValue(40)
        self.assertEqual(dlg.point_slider.value(), 40)
        self.assertEqual(dlg.settings()["point_scale"], 0.4)
        dlg.btn_points_reset.click()
        self.assertEqual((dlg.point_slider.value(), dlg.point_spin.value()), (100, 100))
        self.assertNotIn("point_scale", dlg.settings())

    def test_the_range_is_a_tenth_to_five_times(self):
        dlg = self.dialog()
        self.assertEqual((dlg.point_slider.minimum(), dlg.point_slider.maximum()), (10, 500))
        dlg.point_spin.setValue(9999)
        self.assertEqual(dlg.point_spin.value(), 500)

    def test_moving_it_redraws_the_preview_a_moment_later_and_the_preview_has_the_larger_points(self):
        dlg = self.dialog()
        dlg._timer.stop()
        dlg.point_slider.setValue(300)
        self.assertTrue(dlg._timer.isActive())
        with mock.patch.object(figures, "render_figure", wraps=figures.render_figure) as draw:
            dlg._render_preview()
        self.assertEqual(draw.call_args.kwargs["point_scale"], 3.0)

    def test_a_figure_with_no_points_says_so_and_leaves_the_control_alone(self):
        dlg = self.dialog(event_like_figure())
        self.assertFalse(dlg.has_points)
        self.assertFalse(dlg.point_slider.parentWidget().isEnabled())
        dlg.point_spin.setValue(300)
        self.assertIsNone(dlg.custom_point_scale())                                              # (nothing to change: nothing is asked of the file)
        self.assertNotIn("point_scale", dlg.settings())

    def test_the_figure_on_screen_is_not_changed_by_looking_at_it_with_other_points(self):
        from tests.test_figure_render import sizes_of
        fig = __import__("tests.test_figure_render", fromlist=["points_figure"]).points_figure()
        before = sizes_of(fig)
        dlg = self.dialog(fig)
        dlg.point_slider.setValue(400)
        dlg._render_preview()
        self.assertEqual(sizes_of(fig), before)


class TestCopyToClipboard(GuiCase):
    """Copy to Clipboard: the figure goes on the clipboard as an image, drawn as a PNG file would be, and no file is written."""

    def setUp(self):
        super().setUp()
        self.toasts, self.errors = [], []
        for name, sink in (("show_window_toast", self.toasts), ("show_error", self.errors)):
            patcher = mock.patch.object(figure_export, name, lambda ctx, message, *a, _sink=sink, **k: _sink.append(message))
            patcher.start()
            self.addCleanup(patcher.stop)
        QApplication.clipboard().clear()

    def dialog(self, fig=None):
        return figure_export.FigureExportDialog(self.ctx, fig or event_like_figure())

    @staticmethod
    def clipboard_image():
        return QApplication.clipboard().image()

    def test_the_dialog_has_the_button_beside_export(self):
        dlg = self.dialog()
        self.assertEqual([b.text() for b in dlg.findChildren(QPushButton)][-3:], ["Export", "Copy to Clipboard", "Cancel"])
        self.assertTrue(dlg.copy_button.isEnabled())
        self.assertTrue(self.clipboard_image().isNull())

    def test_it_puts_the_figure_on_the_clipboard_at_the_resolution_chosen_and_closes_without_exporting(self):
        fig = event_like_figure()
        dlg = self.dialog(fig)
        dlg.dpi_spin.setValue(150)
        dlg.copy_button.click()
        image = self.clipboard_image()
        out = io.BytesIO()
        figures.render_figure(fig, out, fmt="png", dpi=150)
        self.assertEqual((image.width(), image.height()), Image.open(io.BytesIO(out.getvalue())).size)         # the size a 150 dpi PNG file would be
        self.assertEqual(dlg.result(), QDialog.DialogCode.Rejected)                                              # (closed: nothing is exported)
        self.assertEqual(self.toasts, [f"Figure copied to the clipboard ({image.width()} × {image.height()} px)"])
        self.assertEqual(self.errors, [])

    def test_it_is_a_png_whatever_the_format_chosen_and_follows_the_size_the_point_size_and_the_transparent_background(self):
        dlg = self.dialog()
        dlg.format_combo.setCurrentIndex(dlg.format_combo.findData("pdf"))
        dlg.dpi_spin.setValue(100)
        dlg.cb_size.setChecked(True)
        dlg.cb_keep.setChecked(False)
        dlg.width_spin.setValue(4.0)
        dlg.height_spin.setValue(3.0)
        dlg.cb_transparent.setChecked(True)
        dlg.copy_button.click()
        image = self.clipboard_image()
        self.assertEqual((image.width(), image.height()), (400, 300))
        self.assertTrue(image.hasAlphaChannel())
        self.assertEqual(image.pixelColor(2, 2).alpha(), 0)                                                       # transparent where nothing is drawn

    def test_what_was_typed_in_the_dialog_is_in_the_image_and_the_figure_on_screen_is_not_touched(self):
        fig = event_like_figure()
        plain = self.dialog(fig)
        plain.copy_button.click()
        before = self.clipboard_image().copy()
        QApplication.clipboard().clear()
        edited = self.dialog(fig)
        item = next(i for i in edited.fields if i.caption == "Figure title")
        edited.fields[item].setText("A different title")
        edited.copy_button.click()
        self.assertNotEqual(self.clipboard_image(), before)
        self.assertEqual(fig._suptitle.get_text(), item.text)

    def test_through_export_figure_nothing_is_written_when_it_is_copied(self):
        fig = event_like_figure()
        with mock.patch.object(figure_export.FigureExportDialog, "exec", lambda dlg: dlg.copy_button.click() or dlg.result()),                 mock.patch.object(figure_export, "write_export") as write:
            figure_export.export_figure(self.ctx, fig, "EventPETH", "L1P")
        write.assert_not_called()
        self.assertFalse(self.clipboard_image().isNull())

    def test_a_figure_that_cannot_be_drawn_says_so_leaves_the_dialog_open_and_the_clipboard_alone(self):
        QApplication.clipboard().setText("what was there")
        dlg = self.dialog()
        with mock.patch.object(figures, "render_figure", side_effect=RuntimeError("no memory")),                 mock.patch.object(figure_export.errorlog, "error"):
            dlg.copy_button.click()
        self.assertEqual(self.errors, ["Could not copy the figure: no memory"])
        self.assertEqual(self.toasts, [])
        self.assertEqual(dlg.result(), 0)
        self.assertEqual(QApplication.clipboard().text(), "what was there")

    def test_a_size_with_too_many_pixels_cannot_be_copied_and_a_vector_format_does_not_get_round_that(self):
        dlg = self.dialog()
        dlg.cb_size.setChecked(True)
        dlg.dpi_spin.setValue(1200)
        dlg.width_slider.setValue(300)
        dlg.height_slider.setValue(300)
        self.assertFalse(dlg.copy_button.isEnabled())
        dlg.format_combo.setCurrentIndex(dlg.format_combo.findData("pdf"))                                       # (Export is allowed: a PDF has no pixels to run out of)
        self.assertTrue(dlg.export_button.isEnabled())
        dlg.copy_button.click()                                                                                  # ... but the clipboard gets a picture, and it is too large
        self.assertEqual(len(self.errors), 1)
        self.assertIn("megapixels", self.errors[0])
        self.assertTrue(self.clipboard_image().isNull())


class TestExportFlow(GuiCase):
    """export_figure() with the dialog accepted (after the test sets what it wants), writing into an Output folder."""

    def setUp(self):
        super().setUp()
        self.out = os.path.join(self.tmp, "Out")
        self.ctx.settings["output_folder"] = self.out
        self.fig = event_like_figure()
        self.saved = mock.patch.object(figure_export._context, "save_settings")
        self.save_settings = self.saved.start()
        self.addCleanup(self.saved.stop)

    def run_export(self, accept=True, tweak=None, **kw):
        def exec_(dialog):
            if tweak:
                tweak(dialog)
            return QDialog.DialogCode.Accepted if accept else QDialog.DialogCode.Rejected
        with mock.patch.object(QDialog, "exec", new=exec_), mock.patch("physicsanalysis_qt.app.toasts.show_window_toast"):
            figure_export.export_figure(self.ctx, self.fig, "EventPETH", "L1P", **kw)
        folder = os.path.join(self.out, "TDT", "Rat7-250101-101010 (Analysis)")
        return folder, sorted(n for n in (os.listdir(folder) if os.path.isdir(folder) else []) if not n.startswith("."))

    def set_pdf_and_edit(self, dialog):
        dialog.format_combo.setCurrentIndex(dialog.format_combo.findData("pdf"))
        dialog.cb_transparent.setChecked(True)
        item = next(i for i in dialog.fields if i.caption == "Group trace: Y label")
        dialog.fields[item].setText("Z (a.u.)")
        legend = next(i for i in dialog.fields if i.text == "Mean")
        dialog.fields[legend].setText("Average")

    def test_the_figure_its_data_and_its_record_are_written_together(self):
        folder, names = self.run_export(tweak=self.set_pdf_and_edit, provenance={"kind": "event_peth", "parameters": {"event": "L1P"}})
        self.assertEqual(len(names), 4, names)
        pdf = next(n for n in names if n.endswith(".pdf"))
        stem = pdf[:-4]
        self.assertTrue(stem.startswith("EventPETH_Rat7-250101-101010_L1P_"))
        self.assertEqual(names, sorted([f"{stem}.pdf", f"{stem}.provenance.json", f"{stem}_data.csv", f"{stem}_image_1.csv"]))
        with open(os.path.join(folder, f"{stem}.pdf"), "rb") as f:
            self.assertEqual(f.read(5), b"%PDF-")

    def test_the_data_csv_says_what_the_edited_figure_says_and_the_live_figure_is_untouched(self):
        folder, names = self.run_export(tweak=self.set_pdf_and_edit)
        data = pd.read_csv(os.path.join(folder, next(n for n in names if n.endswith("_data.csv"))))
        self.assertEqual(set(data["y_label"]), {"Z (a.u.)"})
        self.assertEqual(sorted(data["series"].unique()), ["Average", "SEM"])
        image = pd.read_csv(os.path.join(folder, next(n for n in names if n.endswith("_image_1.csv"))))
        self.assertEqual(list(image["panel"].unique()), ["Trials heatmap"])
        self.assertEqual(self.fig.axes[1].get_ylabel(), "Z-Score (Mode)")                      # the figure on screen is as it was
        self.assertEqual([t.get_text() for t in self.fig.axes[1].get_legend().get_texts()], ["Mean", "SEM"])

    def test_the_record_keeps_the_analysis_lists_every_file_and_notes_the_edits(self):
        folder, names = self.run_export(tweak=self.set_pdf_and_edit, provenance={"kind": "event_peth", "parameters": {"event": "L1P"}})
        with open(os.path.join(folder, next(n for n in names if n.endswith(".provenance.json"))), encoding="utf-8") as f:
            record = json.load(f)
        self.assertEqual((record["kind"], record["analysis"]["parameters"]), ("event_peth", {"event": "L1P"}))
        self.assertEqual({o["name"] for o in record["outputs"]}, {n for n in names if not n.endswith(".provenance.json")})
        self.assertIn("Figure exported as PDF (vector), text kept as editable text, transparent background", record["notes"])
        self.assertIn("Label edited (Group trace: Y label): 'Z-Score (Mode)' -> 'Z (a.u.)'", record["notes"])
        self.assertIn("Label edited (Group trace: Legend 1): 'Mean' -> 'Average'", record["notes"])

    def test_the_point_size_reaches_the_file_and_the_record_and_not_the_figure_on_screen(self):
        from tests.test_figure_render import points_figure, sizes_of
        self.fig = points_figure()
        before = sizes_of(self.fig)

        def tweak(dialog):
            dialog.point_spin.setValue(200)

        folder, names = self.run_export(tweak=tweak, provenance={"kind": "event_peth", "parameters": {"event": "L1P"}})
        png = next(n for n in names if n.endswith(".png"))
        self.assertTrue(any(n.endswith(".provenance.json") for n in names))
        with open(os.path.join(folder, next(n for n in names if n.endswith(".provenance.json"))), encoding="utf-8") as f:
            record = json.load(f)
        self.assertTrue(any("points drawn at 200% of their size" in note for note in record["notes"]), record["notes"])
        plain = os.path.join(self.tmp, "plain.png")
        figures.save_figure(self.fig, plain, dpi=300, data=False)
        with open(plain, "rb") as a, open(os.path.join(folder, png), "rb") as b:
            self.assertNotEqual(a.read(), b.read())                                              # larger points: another picture
        self.assertEqual(sizes_of(self.fig), before)

    def test_the_files_are_the_ones_save_figure_writes_for_the_same_choices(self):
        """What the dialog writes and what figures.save_figure writes for a script are one thing, byte for byte."""
        folder, names = self.run_export(tweak=self.set_pdf_and_edit)
        pdf = next(n for n in names if n.endswith(".pdf"))
        stem = pdf[:-4]
        same = os.path.join(self.tmp, "script", "same.pdf")
        figures.save_figure(self.fig, same, fmt="pdf", transparent=True, labels={"Z-Score (Mode)": "Z (a.u.)", "Mean": "Average"},
                            software=f"PyAT {__version__}")
        for ours, theirs in ((f"{stem}.pdf", "same.pdf"), (f"{stem}_data.csv", "same_data.csv"), (f"{stem}_image_1.csv", "same_image_1.csv")):
            with open(os.path.join(folder, ours), "rb") as a, open(os.path.join(self.tmp, "script", theirs), "rb") as b:
                self.assertEqual(a.read(), b.read(), ours)

    def set_size(self, width, height, dpi=None):
        def tweak(dialog):
            dialog.cb_size.setChecked(True)
            dialog.width_spin.setValue(width)
            dialog.height_spin.setValue(height)
            if dpi:
                dialog.dpi_spin.setValue(dpi)
            dialog.cb_data.setChecked(False)
        return tweak

    def test_a_size_that_was_set_is_the_files_size_and_is_said_in_its_record(self):
        folder, names = self.run_export(tweak=self.set_size(6.0, 4.25, dpi=200), provenance={"kind": "event_peth", "parameters": {"event": "L1P"}})
        with Image.open(os.path.join(folder, next(n for n in names if n.endswith(".png")))) as image:
            self.assertEqual(image.size, (1200, 850))
        with open(os.path.join(folder, next(n for n in names if n.endswith(".provenance.json"))), encoding="utf-8") as f:
            record = json.load(f)
        self.assertIn("Figure exported as PNG image at 200 dpi, size set to 6.00 x 4.25 in", record["notes"])

    def test_the_size_is_not_remembered_for_the_next_figure(self):
        self.run_export(tweak=self.set_size(6.0, 4.25))
        self.assertEqual(self.ctx.settings["figure_export"], {"format": "png", "dpi": 300, "transparent": False, "editable_text": True, "data_csv": False})

    def test_the_figure_on_screen_is_left_as_it_was(self):
        before = ([tuple(ax.get_position().bounds) for ax in self.fig.axes], tuple(self.fig.get_size_inches()))
        self.run_export(tweak=self.set_size(3.0, 9.0))
        self.assertEqual(([tuple(ax.get_position().bounds) for ax in self.fig.axes], tuple(self.fig.get_size_inches())), before)

    def test_the_dialog_and_save_figure_write_the_same_bytes_at_a_set_size(self):
        folder, names = self.run_export(tweak=self.set_size(5.5, 3.5))
        png = next(n for n in names if n.endswith(".png"))
        same = os.path.join(self.tmp, "script", "same.png")
        figures.save_figure(self.fig, same, size=(5.5, 3.5), data=False, software=f"PyAT {__version__}")
        with open(os.path.join(folder, png), "rb") as a, open(same, "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_a_vector_file_has_the_page_size_that_was_set(self):
        def tweak(dialog):
            self.set_size(5.0, 3.0)(dialog)
            dialog.format_combo.setCurrentIndex(dialog.format_combo.findData("pdf"))
        folder, names = self.run_export(tweak=tweak)
        with open(os.path.join(folder, next(n for n in names if n.endswith(".pdf"))), "rb") as f:
            self.assertRegex(f.read().decode("latin-1"), r"/MediaBox \[ ?0 0 360 216 ?\]")

    def test_the_choices_are_remembered_and_saved(self):
        self.run_export(tweak=self.set_pdf_and_edit)
        self.assertEqual(self.ctx.settings["figure_export"], {"format": "pdf", "dpi": 300, "transparent": True, "editable_text": True, "data_csv": True})
        self.save_settings.assert_called_once_with(self.ctx.settings)

    def test_cancelling_writes_nothing_and_remembers_nothing(self):
        folder, names = self.run_export(accept=False, tweak=self.set_pdf_and_edit)
        self.assertEqual(names, [])
        self.assertEqual(self.ctx.settings["figure_export"], {})
        self.save_settings.assert_not_called()

    def test_without_the_data_option_only_the_figure_and_its_record(self):
        folder, names = self.run_export(tweak=lambda d: d.cb_data.setChecked(False))
        self.assertEqual([os.path.splitext(n)[1] for n in names], [".png", ".json"])             # the figure and its record

    def test_a_png_is_the_default_and_is_a_real_png_at_300_dpi(self):
        folder, names = self.run_export(tweak=lambda d: d.cb_data.setChecked(False))
        with Image.open(os.path.join(folder, next(n for n in names if n.endswith(".png")))) as image:
            self.assertAlmostEqual(image.info["dpi"][0], 300, delta=0.5)
            self.assertEqual(image.info["Software"], f"PyAT {__version__}")                     # the app names itself in what it writes

    def test_a_writer_of_its_own_replaces_the_generic_data_export(self):
        calls = []

        def writer(base):
            path = f"{base}_mine.csv"
            with open(path, "w", encoding="utf-8") as f:
                f.write("a\n1\n")
            calls.append(base)
            return [path]
        folder, names = self.run_export(data_writer=writer)
        self.assertEqual(len(calls), 1)
        self.assertTrue(any(n.endswith("_mine.csv") for n in names))
        self.assertFalse(any(n.endswith("_data.csv") for n in names))

    def test_a_name_of_its_own_and_a_destination_of_its_own(self):
        dest = os.path.join(self.tmp, "Group")
        os.makedirs(dest)
        with mock.patch.object(QDialog, "exec", new=lambda d: QDialog.DialogCode.Accepted), \
                mock.patch("physicsanalysis_qt.app.toasts.show_window_toast"):
            figure_export.export_figure(self.ctx, self.fig, "Group", stem="figure_traces_102030", dest_dir=dest)
        self.assertEqual(sorted(n for n in os.listdir(dest)), [
            "figure_traces_102030.png", "figure_traces_102030.provenance.json",
            "figure_traces_102030_data.csv", "figure_traces_102030_image_1.csv"])

    def test_the_repeat_export_is_not_overwritten(self):
        self.run_export()
        folder, names = self.run_export()
        self.assertEqual(sum(n.endswith(".png") for n in names), 2)


class TestAnalysisWindowsUseIt(GuiCase):
    def test_export_plot_in_an_analysis_window_opens_the_figure_dialog(self):
        fig = event_like_figure()
        with mock.patch.object(dispatch, "export_figure") as opened:
            dispatch.export_figure_to_file(self.ctx, fig, "EventPETH", "L1P", provenance={"kind": "x"})
        opened.assert_called_once_with(self.ctx, fig, "EventPETH", "L1P", provenance={"kind": "x"}, no_points_note=figure_export.EDIT_POINTS_NOTE)

    def test_the_app_writes_no_figure_by_a_plain_savefig_only_through_figures_render(self):
        root = os.path.dirname(os.path.dirname(analysis.__file__))
        offenders = []
        for path in glob.glob(os.path.join(root, "**", "*.py"), recursive=True):
            with open(path, encoding="utf-8") as f:
                tree = ast.parse(f.read())
            if os.path.relpath(path, root) == os.path.join("figures", "render.py"):         # the one place a figure is written
                continue
            offenders += [f"{os.path.relpath(path, root)}:{node.lineno}" for node in ast.walk(tree)
                          if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "savefig"]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
