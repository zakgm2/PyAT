"""The main window's plot area as tabs (ui/workspace.py): the recording first, then each analysis window as another tab along the bottom, which can be
popped out into a window of its own and docked back, by a button or by dragging; and the windows computed from a recording close when it changes."""

import os
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QPushButton, QTabBar, QTabWidget, QVBoxLayout

from physicsanalysis_qt.analysis import event_peth, overview, peth
from physicsanalysis_qt.ui import workspace

from tests.test_draw_exported_csv import QUIET_TOAST
from tests.test_gui_reproduces import GuiCase

LEFT = Qt.MouseButton.LeftButton
NONE = Qt.MouseButton.NoButton
REAL_LEFT_BUTTON_DOWN = workspace.left_button_down                  # (before any test replaces it)


def mouse(kind, local, global_pos, button=LEFT, buttons=LEFT):
    return QMouseEvent(kind, QPointF(local), QPointF(global_pos), button, buttons, Qt.KeyboardModifier.NoModifier)


def press(widget, local, global_pos):
    widget.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, local, global_pos))


def move(widget, local, global_pos):
    widget.mouseMoveEvent(mouse(QEvent.Type.MouseMove, local, global_pos, button=NONE))


def release(widget, local, global_pos):
    widget.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, local, global_pos, buttons=NONE))


def press_only(button):
    """The press of a click and not its release (which is what runs the button: Analysis and Export View open dialogs that wait)."""
    centre = button.rect().center()
    QApplication.sendEvent(button, mouse(QEvent.Type.MouseButtonPress, centre, button.mapToGlobal(centre)))
    button.setDown(False)


class WorkspaceCase(GuiCase):
    """The recording in the real main window (offscreen), shown."""

    def setUp(self):
        super().setUp()
        from physicsanalysis_qt.ui.main_window import build_main_window
        build_main_window(self.ctx)
        self.addCleanup(self.ctx.win.close)
        self.ctx.win.show()
        QApplication.processEvents()
        self.ws = self.ctx.workspace
        self.toasts = []
        patcher = mock.patch.object(workspace, "show_window_toast", lambda ctx, message, *a, **k: self.toasts.append(message))
        patcher.start()
        self.addCleanup(patcher.stop)
        # No test here may depend on the real mouse. On Windows left_button_down() asks the system whether the physical button is held, so a click made
        # anywhere on the machine while the suite runs (it takes minutes) made a tab pulled out of the strip look like a drag in progress: the pointer-
        # follower then carried the new window to the offscreen cursor, and the test saw it at -68 instead of where the tab was let go. The button is up,
        # and the pointer over the plot, unless a test says otherwise (TestAWindowPulledOutKeepsFollowingThePointer patches both again for itself).
        for name, value in (("left_button_down", lambda: False), ("pointer_position", lambda: self.ws.mapToGlobal(QPoint(10, 10)))):
            patcher = mock.patch.object(workspace, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def dialog(self, title="Test window"):
        """A window the way the analysis modules build them: a QDialog with a field, and a Done button that accepts it."""
        dlg = QDialog(self.ctx.win)
        dlg.setWindowTitle(title)
        dlg.resize(520, 380)
        layout = QVBoxLayout(dlg)
        dlg.field = QLineEdit()
        layout.addWidget(dlg.field)
        layout.addWidget(QLabel("results"))
        done = QPushButton("Done")
        done.clicked.connect(dlg.accept)
        layout.addWidget(done)
        dlg.done = done
        return dlg

    def settle(self):
        QTest.qWait(5)
        QApplication.processEvents()


class TestTheTabs(WorkspaceCase):
    def test_with_nothing_open_the_plot_area_is_as_it_was(self):
        self.assertIsInstance(self.ws, QTabWidget)
        self.assertEqual(self.ws.count(), 1)
        self.assertIs(self.ws.widget(0), self.ctx.stacked_plot_widget)
        self.assertEqual(self.ws.tabText(0), "Recording")
        self.assertFalse(self.ws.tabBar().isVisible())                                          # no strip until there is something beside the recording
        self.assertEqual(self.ws.tabPosition(), QTabWidget.TabPosition.South)

    def test_a_window_opens_as_a_tab_beside_the_recording_and_comes_to_the_front(self):
        dlg = self.dialog("Z-Score — Rat7 | centre 20.0s | -5s/+8s")
        page = workspace.present(self.ctx, dlg, "Z-Score 20.0s")
        self.settle()
        self.assertEqual(self.ws.count(), 2)
        self.assertEqual(self.ws.currentIndex(), 1)
        self.assertEqual(self.ws.tabText(1), "Z-Score 20.0s")
        self.assertEqual(self.ws.tabToolTip(1), "Z-Score — Rat7 | centre 20.0s | -5s/+8s")
        self.assertTrue(self.ws.tabBar().isVisible())
        self.assertIs(self.ws.page_at(1), page)
        self.assertIs(dlg.parentWidget(), page)
        self.assertFalse(dlg.isWindow())                                                        # the window's contents now, not a window
        self.assertTrue(dlg.isVisible())

    def test_the_recording_tab_cannot_be_closed_or_moved(self):
        workspace.present(self.ctx, self.dialog(), "A")
        bar = self.ws.tabBar()
        self.assertIsNone(bar.tabButton(0, QTabBar.ButtonPosition.RightSide))
        self.assertIsNotNone(bar.tabButton(1, QTabBar.ButtonPosition.RightSide))
        workspace.present(self.ctx, self.dialog(), "B")
        bar.moveTab(0, 2)                                                                       # dragged to the end
        self.assertIs(self.ws.widget(0), self.ctx.stacked_plot_widget)
        self.assertEqual([self.ws.tabText(i) for i in range(3)], ["Recording", "A", "B"] if self.ws.tabText(1) == "A" else ["Recording", "B", "A"])

    def test_a_long_name_is_cut_short_in_the_tab_but_whole_in_the_tooltip(self):
        title = "Event PETH — a very long event name that goes on and on"
        workspace.present(self.ctx, self.dialog(title), title)
        self.assertEqual(len(self.ws.tabText(1)), workspace.TAB_TEXT_MAX)
        self.assertTrue(self.ws.tabText(1).endswith("…"))
        self.assertEqual(self.ws.tabToolTip(1), title)

    def test_the_tabs_tooltip_follows_the_windows_title(self):
        dlg = self.dialog("first")
        workspace.present(self.ctx, dlg, "Event PETH")
        dlg.setWindowTitle("Event PETH — L1P¹ (7 trials)")
        self.assertEqual(self.ws.tabToolTip(1), "Event PETH — L1P¹ (7 trials)")

    def test_the_windows_own_done_button_closes_its_tab_and_the_strip_goes_again(self):
        dlg = self.dialog()
        workspace.present(self.ctx, dlg, "A")
        self.settle()
        dlg.done.click()
        self.settle()
        self.assertEqual(self.ws.count(), 1)
        self.assertEqual(self.ws.currentIndex(), 0)
        self.assertFalse(self.ws.tabBar().isVisible())
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.ws.pages, [])

    def test_the_tabs_x_rejects_the_window_like_closing_it_always_did(self):
        dlg = self.dialog()
        workspace.present(self.ctx, dlg, "A")
        self.ws.tabCloseRequested.emit(1)
        self.assertEqual(dlg.result(), QDialog.DialogCode.Rejected)
        self.assertEqual(self.ws.count(), 1)
        self.ws.tabCloseRequested.emit(0)                                                       # (the recording is not closed)
        self.assertEqual(self.ws.count(), 1)

    def test_esc_does_not_close_a_docked_analysis_it_is_for_stopping_the_engine(self):
        dlg = self.dialog()
        page = workspace.present(self.ctx, dlg, "A")
        QTest.keyClick(dlg, Qt.Key.Key_Escape)
        self.assertEqual(self.ws.count(), 2)
        page.pop_out()
        QTest.keyClick(dlg, Qt.Key.Key_Escape)                                                  # as a window of its own it is a dialog again
        self.settle()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Rejected)

    def test_several_windows_are_several_tabs_and_each_closes_on_its_own(self):
        a, b = self.dialog("A"), self.dialog("B")
        workspace.present(self.ctx, a, "A")
        workspace.present(self.ctx, b, "B")
        self.assertEqual([self.ws.tabText(i) for i in range(3)], ["Recording", "A", "B"])
        self.assertEqual(self.ws.currentIndex(), 2)
        a.done.click()
        self.assertEqual([self.ws.tabText(i) for i in range(2)], ["Recording", "B"])

    def test_without_a_main_window_the_dialog_is_shown_the_old_way(self):
        ctx = types.SimpleNamespace(workspace=None)
        dlg = self.dialog()
        with mock.patch.object(QDialog, "exec", return_value=0) as shown:
            self.assertIsNone(workspace.present(ctx, dlg, "A"))
        shown.assert_called_once_with()


class TestPoppingOutAndDockingBack(WorkspaceCase):
    def test_pop_out_makes_a_window_of_its_own_and_dock_puts_it_back_as_it_was(self):
        dlg = self.dialog("Compare Events")
        page = workspace.present(self.ctx, dlg, "Compare Events")
        dlg.field.setText("typed before")
        self.settle()
        page.header.button.click()                                                              # ⧉ Pop out
        self.settle()
        self.assertTrue(page.floating)
        self.assertTrue(page.isWindow())
        self.assertTrue(page.isVisible())
        self.assertIs(page.parentWidget(), self.ctx.win)                                        # owned by the main window: stays above it
        self.assertEqual(self.ws.count(), 1)
        self.assertEqual(self.ws.currentIndex(), 0)
        self.assertEqual(page.header.button.text(), "⇲ Dock")
        self.assertEqual((page.width(), page.height()), (520, 380))                             # the size its module gave it
        self.assertEqual(page.windowTitle(), "Compare Events")
        page.header.button.click()                                                              # ⇲ Dock
        self.settle()
        self.assertFalse(page.floating)
        self.assertFalse(page.isWindow())
        self.assertEqual(self.ws.count(), 2)
        self.assertIs(self.ws.currentWidget(), page)
        self.assertEqual(page.header.button.text(), "⧉ Pop out")
        self.assertIs(page.dialog, dlg)                                                         # the same window: nothing was redrawn or rebuilt
        self.assertEqual(dlg.field.text(), "typed before")

    def test_closing_the_floating_window_closes_the_analysis(self):
        dlg = self.dialog()
        page = workspace.present(self.ctx, dlg, "A")
        page.pop_out()
        page.close()
        self.settle()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Rejected)
        self.assertEqual(self.ws.pages, [])
        self.assertFalse(page.isVisible())

    def test_the_windows_own_done_button_closes_a_floating_one_too(self):
        dlg = self.dialog()
        page = workspace.present(self.ctx, dlg, "A")
        page.pop_out()
        dlg.done.click()
        self.settle()
        self.assertEqual(self.ws.pages, [])
        self.assertFalse(page.isVisible())

    def test_popped_out_again_it_has_the_size_it_was_left_at(self):
        page = workspace.present(self.ctx, self.dialog(), "A")
        page.pop_out()
        page.resize(700, 500)
        page.dock()
        page.pop_out()
        self.assertEqual((page.width(), page.height()), (700, 500))

    def test_a_window_can_be_popped_out_and_docked_again_and_again(self):
        page = workspace.present(self.ctx, self.dialog(), "A")
        for _ in range(3):
            page.pop_out()
            page.dock()
        self.assertEqual(self.ws.count(), 2)
        self.assertFalse(page.floating)

    def test_the_tabs_menu_can_pop_out_too(self):
        page = workspace.present(self.ctx, self.dialog(), "A")
        with mock.patch.object(workspace.QMenu, "exec") as menu:
            self.ws._tab_menu(self.ws.tabBar().tabRect(1).center())
        menu.assert_called_once()
        self.assertFalse(page.floating)                                                         # (it only offers: the action does the rest)

    def test_a_window_opens_already_popped_out_while_a_tool_is_armed_to_go_on_through_trials(self):
        self.ctx.analysis_mode, self.ctx.analysis_persist = "AUC", True
        page = workspace.present(self.ctx, self.dialog(), "AUC 20.0s")                          # the plot has to stay on screen to be clicked again
        self.assertTrue(page.floating)
        self.assertEqual(self.ws.count(), 1)
        self.ctx.analysis_persist = False
        self.assertFalse(workspace.present(self.ctx, self.dialog(), "AUC 25.0s").floating)


class TestDraggingToPullApartAndPutTogether(WorkspaceCase):
    def test_dragging_a_tab_out_of_the_strip_makes_it_a_window(self):
        page = workspace.present(self.ctx, self.dialog(), "A")
        self.settle()
        bar = self.ws.tabBar()
        start = bar.tabRect(1).center()
        press(bar, start, bar.mapToGlobal(start))
        inside = QPoint(start.x() + 30, start.y())
        move(bar, inside, bar.mapToGlobal(inside))
        self.assertFalse(page.floating)                                                         # along the strip it is only reordered
        outside = QPoint(start.x(), -3 * workspace.DETACH_PX)                                  # dragged up, onto the plot
        move(bar, outside, bar.mapToGlobal(outside))
        self.settle()
        self.assertTrue(page.floating)
        self.assertEqual(self.ws.count(), 1)
        where = bar.mapToGlobal(outside) - QPoint(80, 14)                                       # where the pointer left the strip
        self.assertEqual(page.pos().x(), where.x())
        self.assertLessEqual(abs(page.pos().y() - where.y()), 40)                               # (the offscreen platform shifts a window by its title bar)
        release(bar, outside, bar.mapToGlobal(outside))

    def test_the_recording_tab_cannot_be_dragged_out(self):
        workspace.present(self.ctx, self.dialog(), "A")
        bar = self.ws.tabBar()
        start = bar.tabRect(0).center()
        press(bar, start, bar.mapToGlobal(start))
        far = QPoint(start.x(), bar.height() + 100)
        move(bar, far, bar.mapToGlobal(far))
        self.settle()
        self.assertEqual(self.ws.count(), 2)
        self.assertEqual(len([p for p in self.ws.pages if p.floating]), 0)
        release(bar, far, bar.mapToGlobal(far))

    def test_double_clicking_a_tab_pops_it_out(self):
        page = workspace.present(self.ctx, self.dialog(), "A")
        self.settle()
        bar = self.ws.tabBar()
        at = bar.tabRect(1).center()
        bar.mouseDoubleClickEvent(mouse(QEvent.Type.MouseButtonDblClick, at, bar.mapToGlobal(at)))
        self.settle()
        self.assertTrue(page.floating)

    def test_dragging_a_docked_windows_header_away_pulls_it_out_under_the_pointer(self):
        page = workspace.present(self.ctx, self.dialog(), "A")
        self.settle()
        header = page.header
        start = QPoint(40, 10)
        origin = header.mapToGlobal(start)
        press(header, start, origin)
        move(header, start, origin + QPoint(5, 5))
        self.assertFalse(page.floating)                                                         # a small movement is not a drag
        far = origin + QPoint(120, 90)
        move(header, start, far)
        self.assertTrue(page.floating)
        self.assertEqual(self.ws.count(), 1)
        release(header, start, far)
        self.assertTrue(page.floating)
        self.assertFalse(self.ws._hint.isVisible())

    def test_a_floating_window_follows_its_header_and_docks_when_let_go_over_the_strip_that_lights_up(self):
        page = workspace.present(self.ctx, self.dialog(), "A")
        page.pop_out(at=QPoint(200, 200))
        self.settle()
        header = page.header
        grab = QPoint(30, 10)
        here = header.mapToGlobal(grab)
        press(header, grab, here)
        elsewhere = here + QPoint(40, 25)
        move(header, grab, elsewhere)
        self.assertEqual(page.pos(), QPoint(240, 225))                                          # it went with the pointer
        self.assertFalse(self.ws._hint.isVisible())                                             # (over the plot: nothing to dock onto)
        release(header, grab, elsewhere)
        self.assertTrue(page.floating)                                                          # let go over the plot: it stays a window
        press(header, grab, elsewhere)
        zone = self.ws.drop_zone().center()
        move(header, grab, zone)
        self.assertTrue(self.ws._hint.isVisible())                                              # the strip says so
        self.assertIn("dock", self.ws._hint.text())
        release(header, grab, zone)
        self.settle()
        self.assertFalse(page.floating)
        self.assertFalse(self.ws._hint.isVisible())
        self.assertIs(self.ws.currentWidget(), page)

    def test_the_drop_zone_is_the_strip_along_the_bottom_of_the_workspace(self):
        zone = self.ws.drop_zone()
        whole = self.ws.rect().translated(self.ws.mapToGlobal(QPoint(0, 0)))
        self.assertEqual((zone.left(), zone.right(), zone.bottom()), (whole.left(), whole.right(), whole.bottom()))
        self.assertEqual(zone.height(), workspace.DROP_ZONE_PX)
        self.assertTrue(self.ws.in_drop_zone(zone.center()))
        self.assertFalse(self.ws.in_drop_zone(whole.center()))


class TestAWindowPulledOutKeepsFollowingThePointer(WorkspaceCase):
    """Pulling a tab (or a docked window's header) out of the main window with the button down is one drag: the new window stays under the pointer
    until the button is let go, and docks if that is over the strip along the bottom."""

    def setUp(self):
        super().setUp()
        self.pointer = QPoint(400, 300)
        self.down = True
        for name, value in (("pointer_position", lambda: self.pointer), ("left_button_down", lambda: self.down)):
            patcher = mock.patch.object(workspace, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def pull_out_a_tab(self):
        page = workspace.present(self.ctx, self.dialog(), "A")
        self.settle()
        bar = self.ws.tabBar()
        start = bar.tabRect(1).center()
        press(bar, start, bar.mapToGlobal(start))
        away = QPoint(start.x(), -3 * workspace.DETACH_PX)
        self.pointer = bar.mapToGlobal(away)
        move(bar, away, self.pointer)
        self.settle()
        return page

    def test_the_window_goes_where_the_pointer_goes_after_it_has_come_out(self):
        page = self.pull_out_a_tab()
        self.assertTrue(page.floating)
        follower = page._follower
        self.assertTrue(follower.active)                                                        # the button is still down: the drag goes on
        for where in (QPoint(500, 250), QPoint(620, 330), QPoint(300, 410)):
            self.pointer = where
            follower.tick()
            self.assertEqual(page.pos(), where - QPoint(80, 14))                                 # always at the same place under the pointer
        self.assertFalse(self.ws._hint.isVisible())

    def test_letting_go_over_the_plot_leaves_it_where_it_is_and_the_following_stops(self):
        page = self.pull_out_a_tab()
        follower = page._follower
        self.pointer = QPoint(520, 260)
        follower.tick()
        self.down = False
        follower.tick()
        self.assertTrue(page.floating)
        self.assertFalse(follower.active)
        before = page.pos()
        self.pointer = QPoint(100, 100)
        follower.tick()                                                                         # (a stopped follower no longer moves it)
        self.assertEqual(page.pos(), before)

    def test_letting_go_over_the_strip_along_the_bottom_docks_it_and_the_strip_lights_up_on_the_way(self):
        page = self.pull_out_a_tab()
        follower = page._follower
        self.pointer = self.ws.drop_zone().center()
        follower.tick()
        self.assertTrue(self.ws._hint.isVisible())
        self.down = False
        follower.tick()
        self.settle()
        self.assertFalse(page.floating)
        self.assertFalse(self.ws._hint.isVisible())
        self.assertIs(self.ws.currentWidget(), page)

    def test_a_double_click_pops_it_out_without_a_drag_to_follow(self):
        page = workspace.present(self.ctx, self.dialog(), "A")
        self.settle()
        self.assertTrue(self.down)                                                              # (the second press is still down at that moment: it must not be followed,
        bar = self.ws.tabBar()                                                                  # or letting go over the tab strip would dock it again)
        at = bar.tabRect(1).center()
        bar.mouseDoubleClickEvent(mouse(QEvent.Type.MouseButtonDblClick, at, bar.mapToGlobal(at)))
        self.settle()
        self.assertTrue(page.floating)
        self.assertIsNone(page._follower)

    def test_a_docked_windows_header_pulled_away_is_followed_too(self):
        page = workspace.present(self.ctx, self.dialog(), "A")
        self.settle()
        header = page.header
        offset = QPoint(header.width() // 4, header.height() // 2)                              # (what the window is held by, as it is when pulled)
        start = QPoint(40, 10)
        origin = header.mapToGlobal(start)
        press(header, start, origin)
        self.pointer = origin + QPoint(120, 90)
        move(header, start, self.pointer)
        self.assertTrue(page.floating)
        follower = page._follower
        self.assertTrue(follower.active)
        self.pointer = QPoint(450, 320)
        follower.tick()
        self.assertEqual(page.pos(), self.pointer - offset)
        release(header, start, self.pointer)                                                    # (the header no longer owns the drag: nothing else moves it)
        self.assertTrue(page.floating)
        self.assertTrue(follower.active)

    def test_docking_or_closing_it_ends_the_following(self):
        page = self.pull_out_a_tab()
        follower = page._follower
        page.dock()
        self.assertIsNone(page._follower)
        self.assertFalse(follower.active)
        page.pop_out()
        page.follow_pointer(QPoint(10, 10))
        follower = page._follower
        page.dialog.reject()
        self.settle()
        self.assertFalse(follower.active)

    def test_off_windows_qts_own_idea_of_the_buttons_is_used(self):
        with mock.patch.object(workspace.sys, "platform", "linux"):
            with mock.patch.object(workspace.QGuiApplication, "mouseButtons", return_value=Qt.MouseButton.LeftButton):
                self.assertTrue(REAL_LEFT_BUTTON_DOWN())
            with mock.patch.object(workspace.QGuiApplication, "mouseButtons", return_value=Qt.MouseButton.NoButton):
                self.assertFalse(REAL_LEFT_BUTTON_DOWN())


class TestWindowsBelongToTheirRecording(WorkspaceCase):
    def test_another_recording_closes_the_windows_computed_from_the_old_one_but_not_results_read_back(self):
        computed, read_back = self.dialog("computed"), self.dialog("read back")
        workspace.present(self.ctx, computed, "A")
        workspace.present(self.ctx, read_back, "B", recording=False)
        self.ctx.recording_serial += 1
        self.ctx._data_generation += 1
        self.settle()
        self.assertEqual(computed.result(), QDialog.DialogCode.Rejected)
        self.assertEqual(self.ws.count(), 2)
        self.assertEqual(self.ws.tabText(1), "B")
        self.assertEqual(self.toasts, ["Closed 1 analysis window: the recording changed"])

    def test_a_splice_closes_them_too(self):
        dlgs = [self.dialog("a"), self.dialog("b")]
        for i, dlg in enumerate(dlgs):
            workspace.present(self.ctx, dlg, f"W{i}")
        self.ctx._active_splices = [{"mode": "cut_out", "start": 7.0, "end": 8.5}]
        self.ctx._data_generation += 1
        self.settle()
        self.assertEqual(self.ws.count(), 1)
        self.assertEqual(self.toasts, ["Closed 2 analysis windows: the recording changed"])

    def test_a_floating_window_closes_with_the_rest(self):
        page = workspace.present(self.ctx, self.dialog(), "A")
        page.pop_out()
        self.ctx.recording_serial += 1
        self.ctx._data_generation += 1
        self.settle()
        self.assertFalse(page.isVisible())
        self.assertEqual(self.ws.pages, [])

    def test_a_change_that_is_not_to_the_recording_closes_nothing(self):
        dlg = self.dialog()
        workspace.present(self.ctx, dlg, "A")
        self.ctx._data_generation += 1                                                          # what ticking another signal in the Plot menu does
        self.settle()
        self.assertEqual(self.ws.count(), 2)
        self.assertEqual(self.toasts, [])


class TestTheRecordingsToolsAnswerOnlyOnTheRecording(WorkspaceCase):
    """The buttons that act on the recording's plot, with an analysis window in front: a message, and nothing else (they used to bring the recording to the front)."""

    def setUp(self):
        super().setUp()
        self.buttons = {b.text(): b for b in self.ctx.win.findChildren(QPushButton)}
        self.rescale = self.buttons["⛶"]
        self.clicks = []
        for name in ("Reload", "Analysis"):
            self.buttons[name].clicked.connect(lambda _c=False, name=name: self.clicks.append(name))
        self.rescale.clicked.connect(lambda _c=False: self.clicks.append("Rescale"))

    def test_with_an_analysis_tab_in_front_a_tool_of_the_plot_says_so_and_does_nothing(self):
        workspace.present(self.ctx, self.dialog(), "A")
        self.assertEqual(self.ws.currentIndex(), 1)
        QTest.mouseClick(self.rescale, LEFT)
        self.assertEqual(self.ws.currentIndex(), 1)                                             # (still on the analysis tab: not taken to the recording)
        self.assertEqual(self.clicks, [])                                                       # and the tool did not run
        self.assertEqual(len(self.toasts), 1)
        self.assertIn("Recording tab", self.toasts[0])

    def test_with_the_recording_in_front_they_work_as_ever_and_say_nothing(self):
        QTest.mouseClick(self.rescale, LEFT)
        self.assertEqual(self.clicks, ["Rescale"])
        self.assertEqual(self.toasts, [])

    def test_the_message_names_the_button(self):
        workspace.present(self.ctx, self.dialog(), "A")
        for name in ("Reload", "Analysis"):
            self.toasts.clear()
            press_only(self.buttons[name])
            self.assertEqual(self.ws.currentIndex(), 1, name)
            self.assertTrue(self.toasts[0].startswith(name), self.toasts)
        self.assertEqual(self.clicks, [])
        self.toasts.clear()
        QTest.mouseClick(self.rescale, LEFT)
        self.assertFalse(self.toasts[0].startswith("⛶"))                                        # a symbol is no name: the start of its tooltip is used
        self.assertEqual(self.toasts[0].split(" works")[0], workspace.RecordingTools.name_of(self.rescale))

    def test_the_keyboard_cannot_press_them_either(self):
        workspace.present(self.ctx, self.dialog(), "A")
        self.buttons["Reload"].setFocus()
        for key in (Qt.Key.Key_Space, Qt.Key.Key_Return):
            self.toasts.clear()
            QTest.keyClick(self.buttons["Reload"], key)
            self.assertEqual(len(self.toasts), 1, key)
        self.assertEqual(self.clicks, [])
        self.assertEqual(self.ws.currentIndex(), 1)

    def test_a_double_click_and_the_release_are_swallowed_too(self):
        workspace.present(self.ctx, self.dialog(), "A")
        QTest.mouseDClick(self.rescale, LEFT)
        self.assertEqual(self.clicks, [])
        self.assertEqual(self.ws.currentIndex(), 1)

    def test_back_on_the_recording_tab_they_run(self):
        workspace.present(self.ctx, self.dialog(), "A")
        self.ws.show_recording()
        QTest.mouseClick(self.rescale, LEFT)
        self.assertEqual(self.clicks, ["Rescale"])

    def test_the_buttons_that_act_on_the_window_in_front_or_open_one_of_their_own_are_not_held_back(self):
        for name in ("Export View", "Edit Attributes", "Custom Statistics"):
            self.assertIn(name, self.buttons)
        workspace.present(self.ctx, self.dialog(), "A")
        for name in ("Export View", "Edit Attributes", "Custom Statistics"):
            self.toasts.clear()
            press_only(self.buttons[name])
            self.assertEqual(self.ws.currentIndex(), 1, name)
            self.assertEqual(self.toasts, [], name)                                             # (no "works on the recording" for these)


class TestTheRealAnalysisWindowsOpenAsTabs(WorkspaceCase):
    def open(self, launch, *args):
        with mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=QUIET_TOAST), \
                mock.patch.object(event_peth, "show_window_toast", mock.Mock()), mock.patch("physicsanalysis_qt.analysis.result_window.show_window_toast"), \
                mock.patch.object(overview, "show_window_toast", mock.Mock()):
            launch(*args)
        self.settle()

    def test_a_z_score_window_is_a_tab_named_for_where_it_was_taken(self):
        self.open(peth.launch_zscore_peth, self.ctx, 20.0)
        self.assertEqual(self.ws.count(), 2)
        self.assertEqual(self.ws.tabText(1), "Z-Score 20.0s")
        self.assertIn("centre 20.0s", self.ws.tabToolTip(1))
        page = self.ws.page_at(1)
        self.assertTrue(any(b.text() == "Export Plot" for b in page.findChildren(QPushButton)))
        next(b for b in page.findChildren(QPushButton) if b.text() == "Done").click()
        self.settle()
        self.assertEqual(self.ws.count(), 1)

    def test_event_peth_and_the_recording_overview_are_tabs_too_and_pop_out_with_their_state(self):
        self.open(event_peth.launch_event_peth, self.ctx)
        self.open(overview.launch_recording_overview, self.ctx)
        self.assertEqual([self.ws.tabText(i) for i in range(3)], ["Recording", "Event PETH", "Recording Overview"])
        page = self.ws.page_at(1)
        dlg = page.dialog
        dlg.e_bin.setText("2.5")
        page.pop_out()
        page.dock()
        self.assertEqual(dlg.e_bin.text(), "2.5")                                               # what was typed in is still there
        self.assertEqual(self.ws.tabText(self.ws.count() - 1), "Event PETH")
        self.assertEqual(len(self.ws.pages), 2)


class TestAnyNumberOfWindows(WorkspaceCase):
    """Opening a great many windows must neither break the plot area nor lose any of them: the strip scrolls, the names stay apart, the popped-out
    windows do not pile up, every window can be reached from the ☰ list, and nothing is closed to make room."""

    def open_many(self, n, title="Event PETH", **kw):
        return [workspace.present(self.ctx, self.dialog(f"{title} — window {i}"), title, **kw) for i in range(n)]

    def tab_names(self):
        return [self.ws.tabText(i) for i in range(self.ws.count())]

    def test_eighty_windows_all_stay_open_in_the_order_they_were_opened_and_the_recording_stays_first(self):
        pages = self.open_many(80)
        self.settle()
        self.assertEqual((self.ws.count(), len(self.ws.pages)), (81, 80))                       # no limit, and none closed to make room
        self.assertIs(self.ws.widget(0), self.ctx.stacked_plot_widget)
        self.assertEqual([self.ws.page_at(i) for i in range(1, 81)], pages)
        self.assertTrue(all(page.dialog.isVisible() or page is not self.ws.currentWidget() for page in pages))
        self.assertEqual(self.ws.currentIndex(), 80)                                            # the newest is in front
        self.assertTrue(self.ws.tabBar().usesScrollButtons())                                   # what does not fit is scrolled to, not cut off
        self.assertFalse(any("Closed" in message for message in self.toasts))

    def test_windows_with_the_same_name_are_numbered_so_the_tabs_can_be_told_apart(self):
        self.open_many(3)
        self.assertEqual(self.tab_names(), ["Recording", "Event PETH", "Event PETH (2)", "Event PETH (3)"])
        self.assertEqual([self.ws.page_at(i).title for i in (1, 2, 3)], ["Event PETH", "Event PETH (2)", "Event PETH (3)"])
        self.assertEqual(self.ws.page_at(2).header.title.text(), "Event PETH (2)")               # the window's own strip says the same
        self.ws.page_at(2).dialog.reject()
        workspace.present(self.ctx, self.dialog(), "Event PETH")
        self.assertEqual(self.tab_names(), ["Recording", "Event PETH", "Event PETH (3)", "Event PETH (2)"])   # the number that is free is the one used
        self.assertEqual(len(set(self.tab_names())), 4)

    def test_eighty_with_one_name_have_eighty_different_names(self):
        self.open_many(80)
        names = self.tab_names()
        self.assertEqual(len(set(names)), 81)
        self.assertEqual(names[-1], "Event PETH (80)")

    def test_a_name_that_is_already_numbered_is_numbered_further_not_confused(self):
        workspace.present(self.ctx, self.dialog(), "Z-Score 20.0s")
        workspace.present(self.ctx, self.dialog(), "Z-Score 20.0s")
        workspace.present(self.ctx, self.dialog(), "Z-Score 20.0s (2)")                            # what a person might have called one
        self.assertEqual(self.tab_names(), ["Recording", "Z-Score 20.0s", "Z-Score 20.0s (2)", "Z-Score 20.0s (2) (2)"])

    def test_closing_in_any_order_leaves_the_others_as_they_were(self):
        pages = self.open_many(30)
        self.settle()
        for page in (pages[14], pages[0], pages[29], pages[7], pages[8]):
            page.dialog.reject()
        left = [p for i, p in enumerate(pages) if i not in (14, 0, 29, 7, 8)]
        self.assertEqual(self.ws.pages, left)
        self.assertEqual([self.ws.page_at(i) for i in range(1, self.ws.count())], left)
        self.assertEqual(self.ws.count(), 26)
        self.assertTrue(all(p.dialog.result() == 0 for p in left))                              # (none of the others was rejected by the closing)
        for page in left:
            page.dialog.reject()
        self.assertEqual((self.ws.count(), self.ws.pages), (1, []))
        self.assertFalse(self.ws.tabBar().isVisible())

    def test_the_x_on_a_tab_closes_that_one_even_after_the_tabs_were_dragged_into_another_order(self):
        pages = self.open_many(12)
        self.settle()
        bar = self.ws.tabBar()
        bar.moveTab(10, 2)                                                                      # dragged to the front
        moved = pages[9]
        self.assertIs(self.ws.page_at(2), moved)
        bar.tabCloseRequested.emit(2)
        self.assertEqual(moved.dialog.result(), QDialog.DialogCode.Rejected)
        self.assertNotIn(moved, self.ws.pages)
        self.assertEqual(len(self.ws.pages), 11)
        self.assertTrue(all(p.dialog.result() == 0 for p in pages if p is not moved))
        self.assertIs(self.ws.widget(0), self.ctx.stacked_plot_widget)

    def test_popping_out_and_docking_forty_windows_loses_none_and_leaves_the_strip_right(self):
        pages = self.open_many(40)
        self.settle()
        for page in pages:
            page.pop_out()
        self.assertEqual((self.ws.count(), len(self.ws.pages)), (1, 40))
        self.assertTrue(all(p.floating and p.isVisible() for p in pages))
        for page in pages:
            page.dock()
        self.settle()
        self.assertEqual((self.ws.count(), len(self.ws.pages)), (41, 40))
        self.assertEqual([self.ws.page_at(i) for i in range(1, 41)], pages)
        self.assertTrue(all(not p.floating for p in pages))

    def test_a_great_many_windows_popped_out_are_cascaded_not_stacked(self):
        pages = self.open_many(12)
        for page in pages:
            page.pop_out()
        self.settle()
        spots = [(p.pos().x(), p.pos().y()) for p in pages]
        self.assertEqual(len(set(spots[:workspace.CASCADE_STEPS])), workspace.CASCADE_STEPS)      # each is a step on from the one before
        for (x0, y0), (x1, y1) in zip(spots, spots[1:workspace.CASCADE_STEPS]):
            self.assertAlmostEqual(x1 - x0, workspace.CASCADE_PX, delta=3)
            self.assertAlmostEqual(y1 - y0, workspace.CASCADE_PX, delta=3)
        self.assertEqual(spots[workspace.CASCADE_STEPS], spots[0])                              # then it starts over: none goes off the screen

    def test_the_list_at_the_end_of_the_strip_shows_how_many_and_only_while_there_is_a_strip(self):
        self.assertFalse(self.ws._windows.isVisible())
        pages = self.open_many(3)
        self.settle()
        self.assertTrue(self.ws._windows.isVisible())
        self.assertEqual(self.ws._windows.text(), "☰ 3")
        pages[0].dialog.reject()
        self.assertEqual(self.ws._windows.text(), "☰ 2")
        for page in pages[1:]:
            page.dialog.reject()
        self.settle()
        self.assertFalse(self.ws._windows.isVisible())

    def menu_actions(self):
        self.ws._fill_windows_menu()
        return [a for a in self.ws._windows_menu.actions() if not a.isSeparator()]

    def test_the_list_has_the_recording_and_every_window_and_going_to_one_selects_it(self):
        pages = self.open_many(25)
        self.settle()
        actions = self.menu_actions()
        self.assertEqual(len(actions), 26)
        self.assertEqual(actions[0].text(), "Recording")
        self.assertEqual([a.isChecked() for a in actions].count(True), 1)
        self.assertTrue(actions[-1].isChecked())                                                # the one in front
        self.assertEqual(actions[1].text(), "Event PETH  ·  Event PETH — window 0")
        actions[3].trigger()                                                                    # a window far off the strip's visible end
        self.assertIs(self.ws.currentWidget(), pages[2])
        self.menu_actions()[0].trigger()                                                        # the recording is never lost off the end of the strip
        self.assertEqual(self.ws.currentIndex(), 0)

    def test_a_window_that_is_popped_out_is_in_the_list_marked_and_going_to_it_raises_it(self):
        pages = self.open_many(3)
        pages[1].pop_out()
        self.settle()
        actions = self.menu_actions()
        self.assertEqual([a.text().startswith("⧉ ") for a in actions], [False, False, False, True])      # (the recording, two tabs, then the window)
        with mock.patch.object(pages[1], "raise_") as raised, mock.patch.object(pages[1], "activateWindow") as activated:
            actions[-1].trigger()
        raised.assert_called_once()
        activated.assert_called_once()
        self.assertTrue(pages[1].isVisible())

    def test_a_long_name_is_cut_in_the_list_and_an_ampersand_is_not_a_shortcut(self):
        workspace.present(self.ctx, self.dialog("Peaks — " + "very long " * 30), "Peaks")
        workspace.present(self.ctx, self.dialog("Mean & SD"), "Mean & SD")
        actions = self.menu_actions()
        self.assertLessEqual(len(actions[1].text()), workspace.MENU_TITLE_MAX)
        self.assertTrue(actions[1].text().endswith("…"))
        self.assertEqual(actions[2].text(), "Mean && SD")                                        # (shown as one &)

    def test_past_many_windows_a_note_says_what_it_costs_once_and_nothing_is_closed(self):
        self.open_many(workspace.MANY_PAGES - 1)
        self.assertEqual(self.toasts, [])
        self.open_many(1, title="Another")
        notes = [m for m in self.toasts if "analysis windows are open" in m]
        self.assertEqual(len(notes), 1)
        self.assertIn("None is closed for you", notes[0])
        self.assertIn(str(workspace.MANY_PAGES), notes[0])
        self.open_many(5, title="More")
        self.assertEqual(len([m for m in self.toasts if "analysis windows are open" in m]), 1)    # once, not on every window after it
        self.assertEqual(len(self.ws.pages), workspace.MANY_PAGES + 5)

    def test_the_note_comes_again_after_most_of_the_windows_were_closed(self):
        pages = self.open_many(workspace.MANY_PAGES)
        for page in pages[:-3]:
            page.dialog.reject()
        self.open_many(workspace.MANY_PAGES, title="Again")
        self.assertEqual(len([m for m in self.toasts if "analysis windows are open" in m]), 2)

    def test_a_recording_change_with_a_great_many_windows_closes_those_computed_from_it_and_says_so_once(self):
        computed = self.open_many(30)
        kept = self.open_many(5, title="Results", recording=False)
        self.settle()
        self.toasts.clear()
        self.ctx.recording_serial += 1
        self.ctx._data_generation += 1
        self.settle()
        self.assertTrue(all(p.dialog.result() == QDialog.DialogCode.Rejected for p in computed))
        self.assertEqual(self.ws.pages, kept)                                                   # results read back from files stay
        self.assertEqual(self.ws.count(), 6)
        self.assertEqual([m for m in self.toasts if "Closed" in m], ["Closed 30 analysis windows: the recording changed"])


if __name__ == "__main__":
    unittest.main()
