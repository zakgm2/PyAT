"""Dragging the matplotlib plot (plot/interaction.py, plot/canvas.py): a draw renders the figure once, the plot on screen during a right-button drag is always the
plot drawn (not a picture of it moved), and the canvas paints matplotlib's buffer as it is.

The slowness this answers: a full draw takes tens of milliseconds, and it was done twice (matplotlib's RectangleSelector draws the canvas again after every
draw while an animated artist — the hover marker — is visible) at every step of a pan. A moved picture of the plot was tried to hide the rest of the cost and
dropped: where the data came into view it showed nothing, and the legend and axis numbers of the moment the button went down, until the next real draw."""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from matplotlib.backend_bases import MouseEvent
from PyQt6.QtWidgets import QApplication

from physicsanalysis_qt.plot import interaction, plotting
from physicsanalysis_qt.plot.canvas import PictureCanvas
from physicsanalysis_qt.plot.plot_signal import refresh_plot_signal_options
from physicsanalysis_qt.plot.plotting import simple_plot

from tests.test_workspace import WorkspaceCase


class PlotShown(WorkspaceCase):
    """The recording plotted by the matplotlib engine in the real main window (offscreen, shown, so the canvas has its size)."""

    def setUp(self):
        super().setUp()
        refresh_plot_signal_options(self.ctx)
        for key in self.ctx.plot_signal_checkboxes:
            self.ctx.plot_signal_checkboxes[key].setChecked(True)                      # all three lines: the hover marker has dots to show
        simple_plot(self.ctx)
        QApplication.processEvents()
        self.canvas, self.ax = self.ctx.canvas, self.ctx.ax

    def event(self, kind, x, y, button=3):
        return MouseEvent(kind, self.canvas, x, y, button=button)

    def centre(self):
        box = self.ax.get_window_extent()
        return (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2

    def buffer(self):
        return np.asarray(self.canvas.buffer_rgba()).copy()

    def count_renders(self):
        """A list that grows by one at each render of the figure."""
        renders = []
        real = type(self.canvas.figure).draw
        patcher = mock.patch.object(self.canvas.figure, "draw", lambda renderer, _real=real: (renders.append(1), _real(self.canvas.figure, renderer))[1], create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        return renders


class TestOneRenderPerDraw(PlotShown):
    def test_a_draw_renders_the_figure_once_not_twice(self):
        renders = self.count_renders()
        self.canvas.draw()
        self.assertEqual(len(renders), 1)

    def test_it_stays_once_with_the_hover_marker_on_screen(self):
        x, y = self.centre()
        interaction.on_motion(self.ctx, self.event("motion_notify_event", x, y, button=None))
        self.assertTrue(any(dot.get_visible() for dot in self.ctx.tracker_dots))                 # (the marker is shown while the pointer is over the plot)
        renders = self.count_renders()
        self.canvas.draw()
        self.assertEqual(len(renders), 1)
        self.assertFalse(any(dot.get_visible() for dot in self.ctx.tracker_dots))                # a full draw does not have it in it: it is not marked visible
        self.assertFalse(self.ctx.connecting_line.get_visible())

    def test_the_marker_is_not_visible_until_the_pointer_is_over_the_plot(self):
        self.assertEqual(len(self.ctx.tracker_dots), 3)
        self.assertFalse(any(dot.get_visible() for dot in self.ctx.tracker_dots) or self.ctx.connecting_line.get_visible())
        self.assertTrue(all(dot.get_animated() for dot in self.ctx.tracker_dots))                # (still drawn by blit, on top, as the pointer moves)

    def test_a_plot_built_without_drawing_it_has_the_marker_hidden_too(self):
        simple_plot(self.ctx, draw_now=False)                                                     # (no draw yet: nothing has hidden it but how it was made)
        self.assertFalse(any(dot.get_visible() for dot in self.ctx.tracker_dots) or self.ctx.connecting_line.get_visible())

    def test_the_marker_keeps_showing_after_the_blit_background_is_taken_again(self):
        x, y = self.centre()
        interaction.on_motion(self.ctx, self.event("motion_notify_event", x, y, button=None))
        interaction._refresh_hover_bg(self.ctx)                                                   # (what Edit Attributes does after Apply)
        self.assertTrue(all(dot.get_visible() for dot in self.ctx.tracker_dots))
        self.assertTrue(self.ctx.connecting_line.get_visible())


class TestThePicture(PlotShown):
    def test_it_is_the_picture_matplotlib_would_paint(self):
        self.canvas.draw()
        fast = self.canvas.grab().toImage()
        with mock.patch.object(PictureCanvas, "paintEvent", PictureCanvas.__mro__[1].paintEvent):
            normal = self.canvas.grab().toImage()
        self.assertEqual(fast.size(), normal.size())
        self.assertEqual(fast, normal)

    def test_a_canvas_whose_buffer_is_not_its_size_paints_the_matplotlib_way(self):
        self.canvas.draw()
        with mock.patch.object(PictureCanvas.__mro__[1], "paintEvent") as normal, mock.patch.object(self.canvas, "_draw_idle"):
            self.canvas.resize(self.canvas.width() + 37, self.canvas.height())                    # (the figure is resized when matplotlib hears of it: the buffer lags;
            self.canvas.paintEvent(mock.Mock())                                                   #  and the draw that would catch it up is not done here)
        normal.assert_called()

    def test_a_draw_that_was_asked_for_is_done_before_the_painting(self):
        self.ax.set_xlim(100, 160)
        self.canvas.draw_idle()
        self.canvas.repaint()
        shown = self.buffer()
        self.canvas.draw()
        np.testing.assert_array_equal(shown, self.buffer())                                       # (what was painted is the plot as it is now)


class TestTheDrag(PlotShown):
    def press(self):
        x, y = self.centre()
        interaction.on_press(self.ctx, self.event("button_press_event", x, y))
        return x, y

    def test_the_view_ends_where_the_pointer_took_it(self):
        self.ax.set_xlim(0, 300)
        self.ax.set_ylim(-5, 60)
        box = self.ax.get_window_extent()
        x, y = self.press()
        for i in range(1, 31):
            interaction.on_motion(self.ctx, self.event("motion_notify_event", x + i * 7, y + i * 1.5))
        interaction.on_release(self.ctx, self.event("button_release_event", x + 210, y + 45))
        left, right = self.ax.get_xlim()
        bottom, top = self.ax.get_ylim()
        self.assertAlmostEqual(left, -210 / box.width * 300, places=6)                            # the pointer went 210 px right: the data went with it
        self.assertAlmostEqual(right - left, 300, places=6)
        self.assertAlmostEqual(bottom, -5 - 45 / box.height * 65, places=6)

    def test_the_plot_is_asked_for_at_each_step_far_enough_from_the_last_and_not_in_between(self):
        x, y = self.press()
        with mock.patch.object(self.canvas, "draw_idle") as asked, mock.patch.object(interaction.time, "monotonic") as clock:
            clock.return_value = 100.0
            interaction.on_motion(self.ctx, self.event("motion_notify_event", x + 5, y))
            self.assertEqual(asked.call_count, 1)
            clock.return_value = 100.0 + interaction._PAN_MIN_FRAME_INTERVAL / 4                  # too soon: the limits change, nothing more is asked
            interaction.on_motion(self.ctx, self.event("motion_notify_event", x + 10, y))
            self.assertEqual(asked.call_count, 1)
            clock.return_value = 100.0 + interaction._PAN_MIN_FRAME_INTERVAL * 2
            interaction.on_motion(self.ctx, self.event("motion_notify_event", x + 15, y))
            self.assertEqual(asked.call_count, 2)
        interaction.on_release(self.ctx, self.event("button_release_event", x + 15, y))

    def test_what_is_on_screen_during_the_drag_is_the_plot_drawn_with_the_new_axis_numbers_and_nothing_missing(self):
        self.ax.set_xlim(300, 360)
        self.canvas.draw()
        x, y = self.press()
        interaction.on_motion(self.ctx, self.event("motion_notify_event", x + 200, y))
        QApplication.processEvents()                                                              # (the draw that was asked for is done)
        shown = self.buffer()
        self.canvas.draw()
        np.testing.assert_array_equal(shown, self.buffer())                                       # not a moved picture: the numbers, the legend and the data are the new ones
        self.assertLess(self.ax.get_xlim()[0], 300)
        interaction.on_release(self.ctx, self.event("button_release_event", x + 200, y))

    def test_a_drag_does_not_draw_at_every_step(self):
        renders = self.count_renders()
        x, y = self.press()
        for i in range(1, 61):
            interaction.on_motion(self.ctx, self.event("motion_notify_event", x + i * 3, y))
        self.assertEqual(len(renders), 0)                                                         # (nothing is drawn inside the motion handler: draw_idle waits for the loop)
        QApplication.processEvents()
        self.assertLessEqual(len(renders), 2)
        interaction.on_release(self.ctx, self.event("button_release_event", x + 180, y))

    def test_the_traces_are_thinned_once_for_each_frame_asked_for_not_for_each_pointer_move(self):
        """Thinning three traces of a million samples to the range in view takes longer than a frame; the pan changes the range at every pointer move."""
        x, y = self.press()
        ticks = iter(range(1, 10_000))
        with mock.patch.object(plotting, "update_decimated_lines") as thinned, mock.patch.object(self.canvas, "draw_idle") as asked,                 mock.patch.object(interaction.time, "monotonic", side_effect=lambda: next(ticks) / 600):                    # (one step in ten is a frame's time after the last asked for)
            for i in range(1, 61):
                interaction.on_motion(self.ctx, self.event("motion_notify_event", x + i * 3, y))
            during = thinned.call_count
            self.assertEqual(during, asked.call_count)                                            # thinned for each frame asked for
            self.assertGreaterEqual(during, 2)
            self.assertLess(during, 30)                                                           # and not for each of the 60 moves
            interaction.on_release(self.ctx, self.event("button_release_event", x + 180, y))
            self.assertEqual(thinned.call_count, during + 1)                                      # once more where it ended

    def test_a_change_of_range_that_is_not_a_pan_thins_the_traces_at_once(self):
        with mock.patch.object(plotting, "update_decimated_lines") as thinned:
            self.ax.set_xlim(100, 160)
        thinned.assert_called()

    def test_after_the_drag_the_traces_are_thinned_to_the_range_it_ended_on_including_its_right_hand_end(self):
        self.ax.set_xlim(10, 30)
        x, y = self.press()
        for i in range(1, 21):
            interaction.on_motion(self.ctx, self.event("motion_notify_event", x + i * 5, y))     # (faster than frames are asked for: the last moves are not thinned for)
        interaction.on_release(self.ctx, self.event("button_release_event", x + 100, y))
        left, right = self.ax.get_xlim()
        self.assertLess(left, 10)
        for line, _full_x, _full_y in self.ctx._decim_lines:
            shown = np.asarray(line.get_xdata())
            self.assertLessEqual(shown[0], left + 0.2)
            self.assertGreaterEqual(shown[-1], right - 0.2)                                       # the line reaches both edges of what is in view

    def test_when_the_button_is_let_go_the_screen_is_the_plot_drawn_properly(self):
        x, y = self.press()
        for i in range(1, 21):
            interaction.on_motion(self.ctx, self.event("motion_notify_event", x + i * 7, y))
        interaction.on_release(self.ctx, self.event("button_release_event", x + 140, y))
        self.assertFalse(self.ctx.is_dragging)
        shown = self.buffer()
        self.canvas.draw()
        np.testing.assert_array_equal(shown, self.buffer())                                       # (what is on screen is what a draw gives)


if __name__ == "__main__":
    unittest.main()
