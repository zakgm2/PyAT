"""The Export View button (ui/toolbar.py): Ctrl+Shift+S is its shortcut, its tooltip says so, the space bar does not press it, and with an analysis window in
front it exports that window's figure."""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QPushButton

from physicsanalysis_qt.ui import toolbar, workspace

from tests.test_workspace import WorkspaceCase

CTRL_SHIFT = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
ANIMATED_CLICK_MS = 250                           # (a button's shortcut presses it with an animated click, which lands 100 ms later: wait it out inside the mock)


class TestExportViewShortcut(WorkspaceCase):
    def setUp(self):
        super().setUp()
        self.button = self.ctx.btn_export_view

    def test_the_shortcut_is_ctrl_shift_s(self):
        self.assertEqual(self.button.shortcut(), QKeySequence("Ctrl+Shift+S"))
        self.assertEqual(toolbar.EXPORT_VIEW_SHORTCUT, "Ctrl+Shift+S")

    def test_the_tooltip_tells_the_shortcut(self):
        self.assertIn("Ctrl+Shift+S", self.button.toolTip())
        self.assertIn("Export View", self.button.toolTip())

    def test_the_shortcut_exports_the_view(self):
        with mock.patch.object(toolbar, "export_canvas_action") as exported:
            QTest.keyClick(self.ctx.win, Qt.Key.Key_S, CTRL_SHIFT)
            QTest.qWait(ANIMATED_CLICK_MS)
        exported.assert_called_once_with(self.ctx)

    def test_the_button_still_works_with_the_mouse(self):
        with mock.patch.object(toolbar, "export_canvas_action") as exported:
            self.button.click()
        exported.assert_called_once_with(self.ctx)

    def test_the_space_bar_does_not_press_it_again_after_a_click(self):
        self.assertEqual(self.button.focusPolicy(), Qt.FocusPolicy.NoFocus)
        with mock.patch.object(toolbar, "export_canvas_action") as exported:
            QTest.mouseClick(self.button, Qt.MouseButton.LeftButton)
            self.assertEqual(exported.call_count, 1)
            self.assertFalse(self.button.hasFocus())                                              # (a click leaves no focus on it for the space bar to press)
            QTest.keyClick(QApplication.focusWidget() or self.ctx.win, Qt.Key.Key_Space)
            QTest.qWait(ANIMATED_CLICK_MS)
        self.assertEqual(exported.call_count, 1)



class TestExportViewIsOfTheWindowInFront(WorkspaceCase):
    """With an analysis window in front, Export View (the button and Ctrl+Shift+S) exports that window's figure through its own Export Plot, and is never
    the recording's plot behind it."""

    def setUp(self):
        super().setUp()
        self.button = self.ctx.btn_export_view
        self.dlg = self.dialog()
        self.exported = []
        self.dlg.btn_export = QPushButton("Export Plot")
        self.dlg.layout().addWidget(self.dlg.btn_export)
        self.dlg.btn_export.clicked.connect(lambda: self.exported.append("window"))
        workspace.present(self.ctx, self.dlg, "A")
        self.assertEqual(self.ctx.workspace.currentIndex(), 1)

    def test_the_button_presses_the_windows_own_export_plot(self):
        with mock.patch.object(toolbar, "export_canvas_action") as recording:
            self.button.click()
        self.assertEqual(self.exported, ["window"])
        recording.assert_not_called()
        self.assertEqual(self.ctx.workspace.currentIndex(), 1)                                    # (and the tab did not change)

    def test_so_does_the_shortcut(self):
        with mock.patch.object(toolbar, "export_canvas_action") as recording:
            QTest.keyClick(self.ctx.win, Qt.Key.Key_S, CTRL_SHIFT)
            QTest.qWait(ANIMATED_CLICK_MS)
        self.assertEqual(self.exported, ["window"])
        recording.assert_not_called()

    def test_a_window_without_a_figure_says_so_and_exports_nothing(self):
        del self.dlg.btn_export
        messages = []
        with mock.patch.object(toolbar, "export_canvas_action") as recording,                 mock.patch.object(toolbar, "show_window_toast", lambda ctx, message, *a, **k: messages.append(message)):
            self.button.click()
        recording.assert_not_called()
        self.assertEqual(messages, ["This window has no figure to export."])

    def test_a_windows_export_that_is_off_is_not_pressed(self):
        self.dlg.btn_export.setEnabled(False)
        messages = []
        with mock.patch.object(toolbar, "show_window_toast", lambda ctx, message, *a, **k: messages.append(message)):
            self.button.click()
        self.assertEqual(self.exported, [])
        self.assertEqual(len(messages), 1)

    def test_a_curve_fit_or_results_window_names_its_button_btn_plot(self):
        del self.dlg.btn_export
        self.dlg.btn_plot = QPushButton("Export Plot")
        self.dlg.btn_plot.clicked.connect(lambda: self.exported.append("btn_plot"))
        self.button.click()
        self.assertEqual(self.exported, ["btn_plot"])

    def test_back_on_the_recording_it_is_the_recordings_plot_again(self):
        self.ctx.workspace.show_recording()
        with mock.patch.object(toolbar, "export_canvas_action") as recording:
            self.button.click()
        recording.assert_called_once_with(self.ctx)
        self.assertEqual(self.exported, [])


if __name__ == "__main__":
    unittest.main()
