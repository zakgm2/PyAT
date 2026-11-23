"""
ui/workspace.py
---------------
The main window's plot area as tabs along the bottom, like the sheets of a spreadsheet: the recording is always the first, and each analysis
window (Z-Score, AUC, FFT, Curve Fit, Event PETH, Compare Events, Recording Overview, Peak Finder, Measure Intervals, Open Results, a group
analysis's results) opens as another tab beside it instead of a window over it. The recording stays one click away, so what an analysis showed can be
set beside the plot it came from, and the main window's own tools are at hand.

An analysis tab can be pulled apart — "Pop out" in its header, a double-click or a drag of its tab out of the tab strip, or a drag of its header
away from the window — and then is a window of its own as it used to be; its header then says "Dock", and clicking it, or dragging the header onto
the strip along the bottom of the main window (which lights up to say so), puts it back as a tab. A window is the same window in both places:
popping out and docking move it, nothing is redrawn, and whatever was typed or ticked in it is still there.

    present(ctx, dialog, title)     shows an analysis window as a tab (the way every analysis window opens); without a main window (a script, a
                                    test) it is shown the old way, as a dialog that waits to be closed
    ctx.workspace                   the Workspace; ctx.workspace.show_recording() brings the recording to the front

A window that has a figure (Z-Score, AUC, FFT, Curve Fit, Event PETH, Compare Events, Recording Overview, Open Results) can be edited like the recording's
plot: its header has an Edit Attributes button (popped out or docked), and the Edit Attributes button of the main window edits the figure of the tab in front
(edit/figure_attributes.py). A window says so by having an `editable_figure`.

Any number can be open. The strip scrolls when the tabs do not fit, a window opened a second time under the same name is numbered ("Event PETH (2)") so
the tabs can be told apart, the windows popped out are cascaded instead of stacked, and the ☰ at the end of the strip lists every window, docked or not, to
go to one directly (the recording is the first entry, so it is never lost off the end of the strip). Nothing is ever closed to make room: past MANY_PAGES
windows a note says each holds its results in memory, and that is all.

An analysis window belongs to the recording it was computed from: when another recording is opened, or a splice changes this one, the windows computed from
the old one are closed (with a note), because what they would recalculate or export would not be what they show. Windows that show a finished result read
back from files (Open Results, a group analysis's results) do not belong to a recording and stay.
"""

import json
import sys

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QGuiApplication, QMouseEvent
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QPushButton, QTabBar, QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from ..app.toasts import show_window_toast

RECORDING_TAB = 0
TAB_TEXT_MAX = 30               # characters of a tab's name before it is cut short (its tooltip has the whole of it)
DETACH_PX = 24                  # how far the pointer must leave the tab strip, dragging a tab, for the tab to come out as a window
DRAG_START_PX = 24              # how far a docked window's header is dragged before the window comes out
DROP_ZONE_PX = 44               # the height of the strip along the bottom of the workspace that a dragged window docks onto
MANY_PAGES = 15                 # windows open at once from which a note says each holds its results in memory (none is ever closed for the person)
CASCADE_PX = 30                 # a window popped out with nowhere in particular to go opens this far below and right of the one before ...
CASCADE_STEPS = 10              # ... for this many, then starts over, so none is placed off the screen
MENU_TITLE_MAX = 90             # characters of a window's name in the ☰ list


FOLLOW_MS = 8                   # how often a window pulled out of the tab strip catches up with the pointer


def pointer_position():
    """Where the pointer is, in screen coordinates."""
    return QCursor.pos()


def left_button_down():
    """Whether the left mouse button is held, whichever window the press began in. (Qt only hears of a release over one of its own windows; the
    system knows. On Windows the physical button is asked, the one a left-handed setting has swapped for the right.)"""
    if sys.platform == "win32":
        import ctypes
        user32 = ctypes.windll.user32
        swapped = bool(user32.GetSystemMetrics(23))                        # SM_SWAPBUTTON
        return bool(user32.GetAsyncKeyState(0x02 if swapped else 0x01) & 0x8000)
    return bool(QGuiApplication.mouseButtons() & Qt.MouseButton.LeftButton)


def _short(title):
    return title if len(title) <= TAB_TEXT_MAX else title[:TAB_TEXT_MAX - 1] + "…"


class _TabBar(QTabBar):
    """A tab bar whose analysis tabs can be dragged out of it (or double-clicked) to become windows."""

    detach_requested = pyqtSignal(int, QPoint, bool)       # (tab, where the pointer is in screen coordinates, whether it is being dragged: the window then follows it)

    def __init__(self):
        super().__init__()
        self._pressed_at = None

    def mousePressEvent(self, event):
        self._pressed_at = event.position().toPoint() if event.button() == Qt.MouseButton.LeftButton else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pressed_at is not None and event.buttons() & Qt.MouseButton.LeftButton:
            tab = self.tabAt(self._pressed_at)
            y = event.position().y()
            if tab > RECORDING_TAB and (y < -DETACH_PX or y > self.height() + DETACH_PX):
                self._pressed_at = None
                release = QMouseEvent(QEvent.Type.MouseButtonRelease, event.position(), event.globalPosition(), Qt.MouseButton.LeftButton,
                                      Qt.MouseButton.NoButton, event.modifiers())
                super().mouseReleaseEvent(release)          # ends the tab bar's own drag (the tab goes back where it was)
                self.detach_requested.emit(tab, event.globalPosition().toPoint(), True)
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressed_at = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        tab = self.tabAt(event.position().toPoint())
        if tab > RECORDING_TAB:
            self.detach_requested.emit(tab, event.globalPosition().toPoint(), False)
            return
        super().mouseDoubleClickEvent(event)


class _PointerFollower(QObject):
    """A window that has just been pulled out of the main window, with the button still down, goes on being dragged: the press belongs to the tab strip
    (or the header the window came from), not to the new window, so nothing tells it where the pointer goes. This asks the pointer where it is, many
    times a second, and keeps the window at the same place under it until the button is let go — then it docks, if that was over the strip along the
    bottom of the main window, and otherwise stays where it was dropped."""

    def __init__(self, page, offset):
        super().__init__(page)
        self.page = page
        self.offset = offset                                  # where the pointer is on the window, from its top-left corner
        self.timer = QTimer(self)
        self.timer.setInterval(FOLLOW_MS)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.active = True                                    # (a plain flag: the timer itself is gone once the follower is)

    def tick(self):
        if not self.active:
            return
        where = pointer_position()
        workspace = self.page.workspace
        if left_button_down():
            self.page.move(where - self.offset)
            workspace.show_drop_hint(workspace.in_drop_zone(where))
        else:
            self.stop()
            workspace.show_drop_hint(False)
            if self.page.floating and workspace.in_drop_zone(where):
                self.page.dock()

    def stop(self):
        self.active = False
        self.timer.stop()


class _PageHeader(QWidget):
    """The strip above an analysis window: its name, and the button that pops it out (or docks it). Dragging it pulls a docked window out of the
    main window, and moves a floating one — onto the strip along the bottom of the main window to dock it."""

    def __init__(self, page, title):
        super().__init__()
        self.page = page
        self._grab = None
        self._origin = None
        self.setFixedHeight(30)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setObjectName("analysisPageHeader")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 2, 6, 2)
        self.grip = QLabel("⠿")
        row.addWidget(self.grip)
        self.title = QLabel(title)
        self.title.setStyleSheet("font-weight: bold;")
        row.addWidget(self.title, stretch=1)
        self.edit_button = None
        if page.editable is not None:                                                        # a window with a figure of its own to edit
            self.edit_button = QToolButton()
            self.edit_button.setAutoRaise(True)
            self.edit_button.setCursor(Qt.CursorShape.ArrowCursor)
            self.edit_button.setText("Edit Attributes")
            self.edit_button.setToolTip("Titles, labels, colours, points and the legend of this window's figure")
            self.edit_button.clicked.connect(page.edit_attributes)
            row.addWidget(self.edit_button)
        self.button = QToolButton()
        self.button.setAutoRaise(True)
        self.button.setCursor(Qt.CursorShape.ArrowCursor)
        self.button.clicked.connect(page.toggle_floating)
        row.addWidget(self.button)
        self.set_floating(False)

    def set_floating(self, floating):
        if floating:
            self.button.setText("⇲ Dock")
            self.button.setToolTip("Put this window back in the main window as a tab (or drag this strip onto the tab strip along the bottom of the main window)")
            self.setToolTip("Drag onto the tab strip along the bottom of the main window to dock it")
        else:
            self.button.setText("⧉ Pop out")
            self.button.setToolTip("Make this a window of its own (or drag this strip, or its tab, away)")
            self.setToolTip("Drag away from the window to pop this out")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._grab = event.globalPosition().toPoint()
            self._origin = self.page.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._grab is None:
            return
        here = event.globalPosition().toPoint()
        workspace = self.page.workspace
        if self.page.floating:
            self.page.move(self._origin + (here - self._grab))
            workspace.show_drop_hint(workspace.in_drop_zone(here))
        elif (here - self._grab).manhattanLength() >= DRAG_START_PX:
            offset = QPoint(self.width() // 4, self.height() // 2)
            self._grab = None
            self.releaseMouse()
            self.page.pop_out(at=here - offset)                                              # comes out under the pointer ...
            self.page.follow_pointer(offset)                                                 # ... and stays under it until the button is let go

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self._grab is None:
            return
        self._grab = None
        self.releaseMouse()
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        workspace = self.page.workspace
        workspace.show_drop_hint(False)
        if self.page.floating and workspace.in_drop_zone(event.globalPosition().toPoint()):
            self.page.dock()


class AnalysisPage(QWidget):
    """One analysis window — the QDialog its module built, as it was — inside a header strip, either docked (a tab of the workspace) or
    floating (a window of its own, owned by the main window so it stays above it)."""

    def __init__(self, workspace, dialog, title, recording):
        super().__init__()
        self.workspace = workspace
        self.dialog = dialog
        self.title = title
        self.floating = False
        self._follower = None
        self.basis = workspace.basis() if recording else None          # what it was computed from (None: a result read back from files)
        self.preferred_size = dialog.size()                            # what its module sized it to: the size it has as a window
        dialog.setParent(self, Qt.WindowType.Widget)                   # the dialog stops being a window: it is this page's contents
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = _PageHeader(self, title)
        layout.addWidget(self.header)
        layout.addWidget(dialog, stretch=1)
        dialog.show()
        dialog.installEventFilter(self)
        dialog.windowTitleChanged.connect(self._retitled)
        self.setWindowTitle(dialog.windowTitle() or title)

    def _retitled(self, text):
        self.setWindowTitle(text)
        index = self.workspace.indexOf(self)
        if index >= 0:
            self.workspace.setTabToolTip(index, text)

    def eventFilter(self, obj, event):
        # Esc stops what the engine is doing for the main window (ui/main_window.py); in a tab it must not also close the analysis.
        if obj is self.dialog and not self.floating and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            return True
        return super().eventFilter(obj, event)

    def follow_pointer(self, offset):
        """Keeps this (floating) window under the pointer, `offset` from its top-left corner, until the left button is let go (_PointerFollower)."""
        self.stop_following()
        self._follower = _PointerFollower(self, offset)

    def stop_following(self):
        if self._follower is not None:
            self._follower.stop()
            self._follower.deleteLater()
            self._follower = None

    def toggle_floating(self):
        self.dock() if self.floating else self.pop_out()

    @property
    def editable(self):
        """The figure of this window that Edit Attributes can edit (edit/figure_attributes.py's EditableFigure), or None if it has none."""
        return getattr(self.dialog, "editable_figure", None)

    def edit_attributes(self):
        if self.editable is not None:
            self.editable.edit()

    def export_plot(self):
        """Presses the window's own Export Plot, which opens the Export Figure dialog on its figure (what the toolbar's Export View does with this window in
        front). False if the window has no figure to export."""
        for name in ("btn_export", "btn_plot"):
            button = getattr(self.dialog, name, None)
            if button is not None and button.isEnabled():
                button.click()
                return True
        return False

    def menu_label(self):
        """How the ☰ list names this window: its tab's name and, when the window's own title says more, that."""
        window = self.dialog.windowTitle()
        text = self.title if not window or window == self.title else f"{self.title}  ·  {window}"
        return text if len(text) <= MENU_TITLE_MAX else text[:MENU_TITLE_MAX - 1] + "…"

    def bring_to_front(self):
        """Goes to this window: its tab is selected, or its window is raised (and restored, if it was minimised)."""
        if self.floating:
            if self.isMinimized():
                self.showNormal()
            self.show()
            self.raise_()
            self.activateWindow()
        else:
            self.workspace.setCurrentWidget(self)

    def pop_out(self, at=None):
        """Becomes a window of its own, with the size its module gave it, at `at` (screen coordinates) or beside where it was."""
        if self.floating:
            return
        workspace = self.workspace
        index = workspace.indexOf(self)
        if index >= 0:
            workspace.removeTab(index)
        self.floating = True
        self.setParent(workspace.ctx.win, Qt.WindowType.Window)
        self.header.set_floating(True)
        self.resize(self.preferred_size)
        if at is None:
            frame = workspace.ctx.win.frameGeometry()
            out = sum(1 for page in workspace.pages if page.floating and page is not self)           # (already floating: each is a step further on)
            step = CASCADE_PX * (out % CASCADE_STEPS)
            at = QPoint(frame.left() + 60 + step, frame.top() + 60 + step)
        self.move(at)
        self.show()
        self.raise_()
        self.activateWindow()
        workspace.setCurrentIndex(min(max(index - 1, RECORDING_TAB), workspace.count() - 1))
        workspace.pages_changed.emit()

    def dock(self):
        """Goes back into the main window as the last tab, and comes to the front."""
        if not self.floating:
            return
        self.stop_following()
        self.preferred_size = self.size()                              # popped out again, it has the size it was left at
        self.floating = False
        self.hide()
        self.setWindowFlags(Qt.WindowType.Widget)
        self.header.set_floating(False)
        self.workspace.add_tab(self)
        self.workspace.show_drop_hint(False)

    def closeEvent(self, event):
        self.stop_following()
        if self.floating:
            self.dialog.reject()                                       # closing its window closes the analysis, as it always did
        event.accept()


class Workspace(QTabWidget):
    """The plot area: the recording, then one tab per open analysis window."""

    pages_changed = pyqtSignal()

    def __init__(self, ctx, recording_widget):
        super().__init__()
        self.ctx = ctx
        self.pages = []
        self._recording = recording_widget
        bar = _TabBar()
        self.setTabBar(bar)
        self.setTabPosition(QTabWidget.TabPosition.South)
        self.setDocumentMode(True)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setTabBarAutoHide(True)                                   # no strip until there is something beside the recording
        self.addTab(recording_widget, "Recording")
        bar.setTabButton(RECORDING_TAB, QTabBar.ButtonPosition.RightSide, None)         # the recording is not closed
        bar.setTabButton(RECORDING_TAB, QTabBar.ButtonPosition.LeftSide, None)
        bar.setTabToolTip(RECORDING_TAB, "The recording: its plot and the tools beside it")
        self.tabCloseRequested.connect(self._close_tab)
        bar.tabMoved.connect(self._keep_recording_first)
        bar.detach_requested.connect(self._detach)
        bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        bar.customContextMenuRequested.connect(self._tab_menu)

        self._hint = QLabel("Release to dock this window here as a tab", self)
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._hint.setStyleSheet("background-color: rgba(30, 110, 200, 200); color: white; font-weight: bold; border-radius: 4px;")
        self._hint.hide()

        self._warned = False
        self._windows = QToolButton()                                  # the ☰ at the end of the strip: every window, to go to one directly
        self._windows.setAutoRaise(True)
        self._windows.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._windows.setToolTip("Every open analysis window: pick one to go to it")
        self._windows_menu = QMenu(self._windows)
        self._windows_menu.aboutToShow.connect(self._fill_windows_menu)
        self._windows.setMenu(self._windows_menu)
        self.setCornerWidget(self._windows, Qt.Corner.BottomRightCorner)
        self._windows.hide()
        self.pages_changed.connect(self._pages_changed)

    # --- the pages

    def unique_title(self, title):
        """`title`, or — if an open window already has it — numbered: "Event PETH (2)", the first number not in use."""
        taken = {page.title for page in self.pages}
        if title not in taken:
            return title
        number = 2
        while f"{title} ({number})" in taken:
            number += 1
        return f"{title} ({number})"

    def basis(self):
        """What the recording is now, for telling whether a window was computed from it: which recording (not which engine holds it: that changes when
        the engine is reconnected after a cancel) and which splices."""
        ctx = self.ctx
        return (ctx.recording_serial, json.dumps(ctx._active_splices, sort_keys=True, default=str))

    def add_page(self, dialog, title, recording=True, floating=False):
        """Makes `dialog` (a QDialog an analysis module built) a tab named `title` and brings it to the front — or, with `floating`, a window of its
        own. The page goes when the dialog is accepted or rejected (its Done / Close button, its tab's X, its window's X once popped out)."""
        page = AnalysisPage(self, dialog, self.unique_title(title), recording)
        self.pages.append(page)
        dialog.finished.connect(lambda _result, p=page: self.remove_page(p))
        if floating:
            page.pop_out()
        else:
            self.add_tab(page)
        return page

    def add_tab(self, page):
        index = self.addTab(page, _short(page.title))
        self.setTabToolTip(index, page.dialog.windowTitle() or page.title)
        self.setCurrentIndex(index)
        self.pages_changed.emit()

    def remove_page(self, page):
        if page not in self.pages:
            return
        self.pages.remove(page)
        page.stop_following()
        index = self.indexOf(page)
        if index >= 0:
            self.removeTab(index)
            page.setParent(None)
        page.hide()
        page.dialog.removeEventFilter(page)
        self.pages_changed.emit()

    def _pages_changed(self):
        """The ☰ shows how many windows are open (and only while there is a strip to show it on); past MANY_PAGES, once, a note says what that costs."""
        count = len(self.pages)
        self._windows.setText(f"☰ {count}")
        self._windows.setVisible(self.count() > 1)
        if count >= MANY_PAGES and not self._warned:
            self._warned = True
            show_window_toast(self.ctx, f"{count} analysis windows are open. None is closed for you, but each keeps its results in memory: "
                                        "close the ones you are done with.")
        elif count <= MANY_PAGES // 2:
            self._warned = False

    def _fill_windows_menu(self):
        """The ☰ list: the recording, then the windows in the order of their tabs, then the ones popped out (marked ⧉)."""
        menu = self._windows_menu
        menu.clear()
        current = self.currentWidget()
        recording = menu.addAction("Recording")
        recording.setCheckable(True)
        recording.setChecked(current is self._recording)
        recording.triggered.connect(self.show_recording)
        docked = [page for page in (self.page_at(i) for i in range(self.count())) if page is not None]
        out = [page for page in self.pages if page.floating]
        if docked or out:
            menu.addSeparator()
        for page in docked + out:
            action = menu.addAction(("⧉ " if page.floating else "") + page.menu_label().replace("&", "&&"))
            action.setCheckable(not page.floating)
            action.setChecked(page is current)
            action.triggered.connect(lambda _checked=False, page=page: page.bring_to_front())

    def page_at(self, index):
        widget = self.widget(index)
        return widget if isinstance(widget, AnalysisPage) else None

    def front_page(self):
        """The analysis window in front, or None if the recording is."""
        return self.page_at(self.currentIndex())

    def front_editable(self):
        """The figure of the tab in front, if it is an analysis window that has one to edit; None for the recording and for a window with none."""
        page = self.front_page()
        return page.editable if page is not None else None

    def show_recording(self):
        """The recording to the front (what its tools need: they act on the plot, which has to be the one on screen)."""
        if self.currentIndex() != RECORDING_TAB:
            self.setCurrentIndex(RECORDING_TAB)

    def check_basis(self):
        """Closes the windows computed from a recording that is no longer the one on screen (or its splices no longer the same)."""
        now = self.basis()
        stale = [p for p in self.pages if p.basis is not None and p.basis != now]
        for page in stale:
            page.dialog.reject()
        if stale:
            show_window_toast(self.ctx, f"Closed {len(stale)} analysis window{'s' if len(stale) != 1 else ''}: the recording changed")

    # --- tabs

    def _close_tab(self, index):
        page = self.page_at(index)
        if page is not None:
            page.dialog.reject()

    def _keep_recording_first(self, _from, _to):
        """The tabs can be dragged into another order, but the recording stays first."""
        index = self.indexOf(self._recording)
        if index != RECORDING_TAB:
            self.tabBar().moveTab(index, RECORDING_TAB)

    def _detach(self, index, where, dragging=False):
        page = self.page_at(index)
        if page is not None:
            offset = QPoint(80, 14)

            def come_out():                                                            # (after the mouse event that asked for it is done)
                page.pop_out(at=where - offset)
                if dragging and left_button_down():                                    # a drag goes on with the pointer; a double-click is done
                    page.follow_pointer(offset)

            QTimer.singleShot(0, come_out)

    def _tab_menu(self, pos):
        index = self.tabBar().tabAt(pos)
        page = self.page_at(index)
        if page is None:
            return
        menu = QMenu(self)
        menu.addAction("Pop out into a window", page.pop_out)
        menu.addAction("Close", page.dialog.reject)
        menu.exec(self.tabBar().mapToGlobal(pos))

    # --- docking by dragging

    def drop_zone(self):
        """The strip along the bottom of the workspace, in screen coordinates, that a window dragged onto it docks into."""
        rect = QRect(self.mapToGlobal(QPoint(0, 0)), self.size())
        return QRect(rect.left(), rect.bottom() - DROP_ZONE_PX + 1, rect.width(), DROP_ZONE_PX)

    def in_drop_zone(self, global_pos):
        return self.drop_zone().contains(global_pos)

    def show_drop_hint(self, show):
        if show:
            self._hint.setGeometry(4, self.height() - DROP_ZONE_PX - 2, self.width() - 8, DROP_ZONE_PX - 4)
            self._hint.raise_()
        self._hint.setVisible(show)


def present(ctx, dialog, title, recording=True, floating=None):
    """Shows an analysis window `dialog` as a tab of the main window, named `title`. `recording` is False for a result read back from files, which
    belongs to no recording and so stays when the recording changes. `floating` opens it as a window of its own instead; left out, that is so while
    an Analysis tool is armed to go on through trials (the plot has to stay on screen to be clicked again). With no main window (a script, a test)
    the dialog is shown as a dialog and this waits until it is closed, as the analysis windows always did."""
    workspace = getattr(ctx, "workspace", None)
    if workspace is None:
        dialog.exec()
        return None
    if floating is None:
        floating = bool(getattr(ctx, "analysis_mode", None)) and bool(getattr(ctx, "analysis_persist", False))
    return workspace.add_page(dialog, title, recording, floating)


class RecordingTools(QObject):
    """The buttons that act on the recording's plot (the tool column at the left, Reload, Analysis, the Plot menu) do what they do to the plot on screen.
    With an analysis window in front they do nothing but say so: they used to bring the recording to the front and act, which took the person away from
    what they were looking at. (Edit Attributes and Export View are not among them: they act on the window in front, whichever that is — see
    edit/attributes.py and the toolbar.)"""

    PRESSES = (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.MouseButtonRelease)
    KEYS = (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter)

    def __init__(self, workspace):
        super().__init__(workspace)
        self.workspace = workspace

    def watch(self, *widgets):
        for widget in widgets:
            widget.installEventFilter(self)

    @staticmethod
    def name_of(widget):
        """What to call the button in the message: its name if it has words, else the start of its tooltip (the tool column's buttons are symbols)."""
        text = (getattr(widget, "text", lambda: "")() or "").strip().rstrip("…")
        if text and any(c.isalpha() for c in text):
            return text
        tip = (widget.toolTip() or "").strip()
        return (tip.split(chr(10))[0].split(" — ")[0] or "That tool") if tip else "That tool"

    def eventFilter(self, obj, event):
        if self.workspace.currentIndex() == RECORDING_TAB:
            return False
        kind = event.type()
        if kind in self.PRESSES or (kind == QEvent.Type.KeyPress and event.key() in self.KEYS):
            if kind in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick, QEvent.Type.KeyPress):
                show_window_toast(self.workspace.ctx, f"{self.name_of(obj)} works on the recording's plot — switch to the Recording tab to use it.")
            return True                                                                   # (the button is not pressed: no click, no menu)
        return False
