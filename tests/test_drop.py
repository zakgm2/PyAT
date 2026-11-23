"""Drag and drop (loading/drop.py): a file or folder dropped on the main window opens like the Open menu opens it, whichever widget it lands on."""

import os
import shutil
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PyQt6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QImage, QRegion
from PyQt6.QtWidgets import QApplication, QDialog, QWidget

from physicsanalysis_qt.loading import drop, generic, tdt

from tests.recordings import make_tdt_folder, write_csv, write_oxysoft
from tests.test_loaders_engine import LoaderCase


def mime_for(*paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return mime


def send_drop(widget, mime):
    """A drag entering `widget` and then dropping, the order Qt delivers them in (it sends a drop only to the widget that accepted the drag). `mime` must stay
    alive while the events are used: an event does not own its mime data."""
    enter = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, enter)
    event = QDropEvent(QPointF(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)
    return event


class TestExplain(unittest.TestCase):
    """The words the overlay shows over a drag (the status bar's are drop.describe)."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

    def path(self, name, folder=False):
        path = os.path.join(self.tmp, name)
        os.makedirs(path) if folder else open(path, "w").close()
        return path

    def test_what_can_be_opened_is_named_with_its_kind(self):
        for name, kind in (("a.csv", "table"), ("b.xlsx", "table"), ("c.txt", "text file"), ("d.pt2", ".pt2 image"), ("e.provenance.json", "saved results")):
            self.assertEqual(drop.explain([self.path(name)]), (True, "Drop to open", f"{name} ({kind})"))
        self.assertEqual(drop.explain([self.path("Rat7-250101-101010", folder=True)]), (True, "Drop to open", "Rat7-250101-101010 (TDT folder)"))

    def test_a_file_that_cannot_be_opened_is_refused_and_the_overlay_says_what_can(self):
        ok, title, detail = drop.explain([self.path("recording.mat")])
        self.assertFalse(ok)
        self.assertIn("cannot be opened", title)
        self.assertIn("recording.mat", detail)
        self.assertIn("TDT folder", detail)

    def test_several_folders_say_they_will_be_asked(self):
        ok, title, detail = drop.explain([self.path("A-250101-101010", folder=True), self.path("B-250102-101010", folder=True)])
        self.assertTrue(ok)
        self.assertEqual(title, "Drop to open 2 folders")
        self.assertIn("Single Experiment or Group Analysis", detail)

    def test_other_extra_items_are_said_to_be_skipped(self):
        ok, _, detail = drop.explain([self.path("a.csv"), self.path("b.csv"), self.path("c.csv")])
        self.assertTrue(ok)
        self.assertIn("2 more", detail)
        self.assertIn("skipped", detail)


class TestClassify(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

    def test_files_are_told_apart_by_their_names_not_their_case(self):
        for name, kind in (("a.csv", "table"), ("B.TSV", "table"), ("c.xlsx", "table"), ("d.xls", "table"), ("e.dat", "table"), ("f.txt", "text"),
                           ("g.pt2", "pt2"), ("G.PT2", "pt2"), ("Rat7 PETH.provenance.json", "results"), ("analysis_settings.json", "results"),
                           ("recording.mat", None), ("notes.docx", None), ("block.tev", None)):
            self.assertEqual(drop.classify(os.path.join(self.tmp, name)), kind, name)

    def test_a_folder_is_a_folder_unless_it_holds_a_group_analysis(self):
        folder = os.path.join(self.tmp, "Rat7-250101-101010")
        os.makedirs(folder)
        self.assertEqual(drop.classify(folder), "folder")
        with open(os.path.join(folder, "analysis_settings.json"), "w") as f:
            f.write("{}")
        self.assertEqual(drop.classify(folder), "results")

    def test_only_local_files_count(self):
        mime = QMimeData()
        mime.setUrls([QUrl("https://example.com/data.csv"), QUrl.fromLocalFile(os.path.join(self.tmp, "a.csv"))])
        self.assertEqual([os.path.normpath(p) for p in drop.local_paths(mime)], [os.path.normpath(os.path.join(self.tmp, "a.csv"))])
        self.assertEqual(drop.local_paths(QMimeData()), [])


class DropCase(LoaderCase):
    def setUp(self):
        super().setUp()
        self.patch(drop, "show_error", lambda ctx, msg, *a, **k: self.errors.append(msg))
        self.patch(drop, "show_window_toast", lambda ctx, msg, *a, **k: self.toasts.append(msg))

    def wait_for_a_recording(self):
        self.spin(lambda: self.ctx.cache is not None or self.errors)

    def drive_the_picker(self, path):
        """Drops `path`, with the table and column picker replaced by one that just records that it opened."""
        seen = {}

        def exec_(dlg):
            seen["dialog"] = dlg
            return 1

        with mock.patch.object(generic.GenericLoaderDialog, "exec", exec_):
            drop.open_dropped(self.ctx, [path])
            self.spin(lambda: "dialog" in seen or self.errors)
            self.settle()
        return seen.get("dialog")


class TestDroppingOpensWhatTheOpenMenuOpens(DropCase):
    def test_a_tdt_folder_is_loaded(self):
        folder = self.tdt_folder()
        self.assertEqual(drop.open_dropped(self.ctx, [folder]), "folder")
        self.wait_for_a_recording()
        self.assertEqual(self.errors, [])
        self.assertIsNotNone(self.ctx.cache)
        self.assertEqual(self.ctx.last_dir, folder)
        self.assertGreater(self.plotted(), 0)

    def test_an_oxysoft_export_is_told_from_other_text_by_the_engine_and_loaded(self):
        path = os.path.join(self.tmp, "session.txt")
        write_oxysoft(path)
        self.assertEqual(drop.open_dropped(self.ctx, [path]), "text")
        self.wait_for_a_recording()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.ctx.cache["source"], "Oxysoft")
        self.assertIn("File: session.txt", self.toasts)

    def test_other_text_goes_to_the_table_picker(self):
        path = os.path.join(self.tmp, "table.txt")
        write_csv(path)
        self.assertIsNotNone(self.drive_the_picker(path))
        self.assertEqual(self.errors, [])

    def test_a_csv_goes_to_the_table_picker(self):
        path = os.path.join(self.tmp, "table.csv")
        write_csv(path)
        dialog = self.drive_the_picker(path)
        self.assertIsNotNone(dialog)
        self.assertEqual(dialog.path, path)
        self.assertEqual(self.ctx.last_dir, self.tmp)

    def test_a_pt2_image_goes_to_the_viewer(self):
        path = os.path.join(self.tmp, "image.pt2")
        with mock.patch.object(drop.pt2, "open_pt2_path") as opened:
            self.assertEqual(drop.open_dropped(self.ctx, [path]), "pt2")
        opened.assert_called_once_with(self.ctx, path)

    def test_a_results_file_and_a_group_analysis_folder_open_results(self):
        record = os.path.join(self.tmp, "Event PETH_L1P.provenance.json")
        folder = os.path.join(self.tmp, "Sucrose")
        os.makedirs(folder)
        settings = os.path.join(folder, "analysis_settings.json")
        with open(settings, "w") as f:
            f.write("{}")
        with mock.patch.object(drop, "open_results") as opened:
            drop.open_dropped(self.ctx, [record])
            drop.open_dropped(self.ctx, [folder])
        self.assertEqual([c.kwargs["path"] for c in opened.call_args_list], [record, settings])

    def test_a_file_the_program_does_not_open_says_what_can_be_dropped(self):
        path = os.path.join(self.tmp, "recording.mat")
        self.assertIsNone(drop.open_dropped(self.ctx, [path]))
        self.assertEqual(len(self.errors), 1)
        self.assertIn("Cannot open recording.mat", self.errors[0])
        self.assertIn("a TDT folder", self.errors[0])
        self.assertIsNone(self.ctx.cache)

    def test_several_items_open_the_first_and_say_how_many_were_left(self):
        first, second = os.path.join(self.tmp, "a.csv"), os.path.join(self.tmp, "b.csv")
        write_csv(first)
        shutil.copy(first, second)
        seen = {}
        with mock.patch.object(generic.GenericLoaderDialog, "exec", lambda dlg: seen.setdefault("dialog", dlg) and 1):
            drop.open_dropped(self.ctx, [first, second])
            self.spin(lambda: "dialog" in seen or self.errors)
            self.settle()
        self.assertEqual(seen["dialog"].path, first)
        self.assertTrue(any("1 other item(s) skipped" in t for t in self.toasts), self.toasts)

    def test_an_empty_drop_does_nothing(self):
        self.assertIsNone(drop.open_dropped(self.ctx, []))
        self.assertEqual((self.errors, self.toasts), ([], []))

    def test_a_reader_that_is_not_installed_is_a_message_like_it_is_from_the_open_menu(self):
        """The drop goes through the same loaders, so a missing package reads the same (needs a PyATCLI with the optional extras)."""
        import importlib.util
        import sys
        if importlib.util.find_spec("PyATCLI._optional") is None:
            self.skipTest("needs a PyATCLI with the optional extras")
        folder = self.tdt_folder()
        self.patch(sys, "modules", {**sys.modules, "tdt": None})
        drop.open_dropped(self.ctx, [folder])
        self.wait_for_a_recording()
        self.assertEqual(len(self.errors), 1, self.errors)
        self.assertIn('pip install "PyATCLI[tdt]"', self.errors[0])


class TestSeveralFoldersDropped(DropCase):
    """Folders dropped together are all searched for recordings, and more than one gets what a parent folder holding several gets: the Single Experiment or
    Group Analysis question (the first folder alone used to be opened and the rest dropped)."""

    @staticmethod
    def same(a, b):
        return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))

    def drop_and_wait_for_the_question(self, *folders):
        with mock.patch.object(tdt, "_prompt_multi_tdt") as prompt:
            self.assertEqual(drop.open_dropped(self.ctx, list(folders)), "folders")
            self.spin(lambda: prompt.called or self.errors)
            self.settle()
        return prompt

    def test_two_tdt_folders_ask_single_experiment_or_group_analysis(self):
        a, b = self.tdt_folder("RatA-250101-101010"), self.tdt_folder("RatB-250102-101010")
        prompt = self.drop_and_wait_for_the_question(b, a)                           # dropped in this order
        self.assertEqual(self.errors, [])
        prompt.assert_called_once()
        (ctx, found, base_path), kwargs = prompt.call_args
        self.assertIs(ctx, self.ctx)
        self.assertTrue(all(self.same(x, y) for x, y in zip(found, [a, b])), found)        # sorted, whatever the order of the drag
        self.assertTrue(self.same(base_path, self.tmp), base_path)                    # what they share: their parent folder, as when that is picked
        self.assertTrue(kwargs["dropped"])

    def test_group_analysis_is_offered_the_dropped_recordings(self):
        a, b = self.tdt_folder("RatA-250101-101010"), self.tdt_folder("RatB-250102-101010")

        def choose_group_analysis(dlg):
            dlg.mode = "hypothesis"
            return tdt.QDialog.DialogCode.Accepted

        with mock.patch.object(tdt._MultiTDTModeDialog, "exec", choose_group_analysis),                 mock.patch("physicsanalysis_qt.analysis.group.launch_group_analysis") as launch:
            drop.open_dropped(self.ctx, [a, b])
            self.spin(lambda: launch.called or self.errors)
        launch.assert_called_once()
        ctx, folders, base_path = launch.call_args.args
        self.assertEqual(len(folders), 2)
        self.assertTrue(self.same(base_path, self.tmp))

    def test_single_experiment_analysis_opens_the_one_picked(self):
        a, b = self.tdt_folder("RatA-250101-101010"), self.tdt_folder("RatB-250102-101010")

        def choose_single(dlg):
            dlg.mode = "single"
            return tdt.QDialog.DialogCode.Accepted

        def pick_the_second(dlg):
            dlg.chosen = dlg.folders[1]
            return tdt.QDialog.DialogCode.Accepted

        with mock.patch.object(tdt._MultiTDTModeDialog, "exec", choose_single), mock.patch.object(tdt._TDTFolderPickerDialog, "exec", pick_the_second),                 mock.patch.object(tdt, "_load_folder") as load:
            drop.open_dropped(self.ctx, [a, b])
            self.spin(lambda: load.called or self.errors)
        self.assertEqual(self.errors, [])
        load.assert_called_once()
        self.assertTrue(self.same(load.call_args.args[1], b), load.call_args)

    def test_a_parent_folder_and_a_block_inside_it_are_not_counted_twice(self):
        cohort = os.path.join(self.tmp, "cohort")
        os.makedirs(cohort)
        x, y = make_tdt_folder(cohort, "RatX-250101-101010"), make_tdt_folder(cohort, "RatY-250102-101010")
        z = self.tdt_folder("RatZ-250103-101010")
        prompt = self.drop_and_wait_for_the_question(cohort, x, z)
        found = prompt.call_args.args[1]
        self.assertEqual(len(found), 3, found)
        for folder in (x, y, z):
            self.assertTrue(any(self.same(folder, f) for f in found), folder)

    def test_one_recording_among_the_dropped_folders_is_just_opened(self):
        a = self.tdt_folder("RatA-250101-101010")
        empty = os.path.join(self.tmp, "notes")
        os.makedirs(empty)
        with mock.patch.object(tdt, "_prompt_multi_tdt") as prompt:
            drop.open_dropped(self.ctx, [empty, a])
            self.wait_for_a_recording()
        prompt.assert_not_called()
        self.assertEqual(self.errors, [])
        self.assertIsNotNone(self.ctx.cache)

    def test_no_recordings_in_the_dropped_folders_is_a_message(self):
        first, second = os.path.join(self.tmp, "one"), os.path.join(self.tmp, "two")
        os.makedirs(first)
        os.makedirs(second)
        prompt = self.drop_and_wait_for_the_question(first, second)
        prompt.assert_not_called()
        self.assertEqual(self.errors, ["No TDT folders found in the dropped folders."])

    def test_the_status_bar_says_how_many_folders_would_open(self):
        a, b = self.tdt_folder("RatA-250101-101010"), self.tdt_folder("RatB-250102-101010")
        self.assertEqual(drop.describe([a, b]), "Drop to open 2 folders (Single Experiment or Group Analysis)")

    def test_a_folder_with_a_file_is_still_the_first_item_only(self):
        a = self.tdt_folder("RatA-250101-101010")
        table = os.path.join(self.tmp, "table.csv")
        write_csv(table)
        with mock.patch.object(tdt, "_prompt_multi_tdt") as prompt:
            drop.open_dropped(self.ctx, [a, table])
            self.wait_for_a_recording()
        prompt.assert_not_called()
        self.assertTrue(any("1 other item(s) skipped" in m for m in self.toasts), self.toasts)


class TestTheWindowTakesTheDrop(DropCase):
    def test_the_window_accepts_drops(self):
        self.assertTrue(self.ctx.win.acceptDrops())

    def test_a_drop_on_the_window_opens_it(self):
        with mock.patch.object(drop, "open_dropped") as opened:
            mime = mime_for(self.tmp)
            event = send_drop(self.ctx.win, mime)
        self.assertEqual(opened.call_count, 1)
        ctx, paths = opened.call_args.args
        self.assertIs(ctx, self.ctx)
        self.assertEqual([os.path.normpath(p) for p in paths], [os.path.normpath(self.tmp)])           # Qt writes C:/... on Windows, as the file dialogs do
        self.assertTrue(event.isAccepted())

    def test_a_drop_on_either_plot_is_taken_too(self):
        """A QGraphicsView accepts drops itself, so without the application-level filter the window would never be offered them."""
        for widget in (self.ctx.canvas, self.ctx.pg_widget, self.ctx.pg_widget.viewport()):
            with mock.patch.object(drop, "open_dropped") as opened:
                mime = mime_for(self.tmp)
                send_drop(widget, mime)
            self.assertEqual(opened.call_count, 1, type(widget).__name__)

    def test_a_drag_over_the_window_says_what_dropping_would_open_and_leaving_clears_it(self):
        mime = mime_for(os.path.join(self.tmp, "a.csv"))                                     # an event does not own its mime data
        enter = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.ctx.win, enter)
        self.assertTrue(enter.isAccepted())
        self.assertIn("Drop to open a.csv", self.ctx.status_bar.currentMessage())
        QApplication.sendEvent(self.ctx.win, QDragLeaveEvent())
        self.assertEqual(self.ctx.status_bar.currentMessage(), "")

    def test_a_drag_of_an_unsupported_file_says_so_before_it_is_dropped(self):
        mime = mime_for(os.path.join(self.tmp, "x.mat"))
        enter = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.ctx.win, enter)
        self.assertIn("Cannot open x.mat", self.ctx.status_bar.currentMessage())

    def test_a_drag_that_carries_no_files_is_left_alone(self):
        mime = QMimeData()
        mime.setText("just some text")
        with mock.patch.object(drop, "open_dropped") as opened:
            send_drop(self.ctx.win, mime)
        opened.assert_not_called()

    def test_a_dialogs_own_drops_are_not_taken(self):
        dialog = QDialog(self.ctx.win)
        dialog.setAcceptDrops(True)
        self.addCleanup(dialog.deleteLater)
        with mock.patch.object(drop, "open_dropped") as opened:
            mime = mime_for(self.tmp)
            send_drop(dialog, mime)
        opened.assert_not_called()


class TestWhatTheWindowShows(DropCase):
    """ui/drop_overlay.py: a card that says files can be dropped while nothing is loaded, and a veil with a dashed frame over the plot area during a drag."""

    def setUp(self):
        super().setUp()
        self.ctx.win.show()
        self.spin(lambda: self.ctx.drop_overlay.isVisible(), timeout=5)
        self.overlay = self.ctx.drop_overlay

    def drag_over(self, *paths):
        self.mime = mime_for(*paths)                                                         # an event does not own its mime data
        enter = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, self.mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.ctx.win, enter)
        self.app.processEvents()

    def leave(self):
        QApplication.sendEvent(self.ctx.win, QDragLeaveEvent())
        self.app.processEvents()

    def corner_alpha(self):
        """How opaque the overlay is at its top-left corner: 0 for the card (it only covers the middle), more for the veil."""
        image = QImage(self.overlay.size(), QImage.Format.Format_ARGB32)
        image.fill(0)                                                                        # transparent: only what the overlay paints shows
        self.overlay.render(image, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
        return image.pixelColor(2, 2).alpha()

    def test_an_empty_window_invites_a_drop(self):
        self.assertTrue(self.overlay.isVisible())
        self.assertFalse(self.overlay.dragging)
        self.assertIn("Drag a file or folder here", self.overlay.hint[0])
        self.assertEqual(self.corner_alpha(), 0)

    def test_it_covers_the_plot_area_and_lets_the_mouse_through(self):
        stack = self.ctx.stacked_plot_widget
        self.assertIs(self.overlay.parentWidget(), stack)
        self.assertTrue(self.overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.assertEqual(self.overlay.geometry(), stack.rect())
        self.ctx.win.resize(self.ctx.win.width() + 120, self.ctx.win.height() + 60)
        self.spin(lambda: self.overlay.geometry() == stack.rect(), timeout=5)
        self.assertEqual(self.overlay.geometry(), stack.rect())

    def test_it_stays_on_top_when_the_other_plot_engine_is_shown(self):
        stack = self.ctx.stacked_plot_widget
        for engine in (self.ctx.pg_widget, self.ctx.canvas, self.ctx.pg_widget):
            stack.setCurrentWidget(engine)
            self.assertIs(stack.children()[-1], self.overlay)                                # the last child is the top of the stacking order

    def test_a_drag_veils_the_plot_area_and_says_what_dropping_would_open(self):
        path = os.path.join(self.tmp, "a.csv")
        write_csv(path)
        self.drag_over(path)
        self.assertTrue(self.overlay.dragging)
        self.assertEqual(self.overlay._drag, (True, "Drop to open", "a.csv (table)"))
        self.assertGreater(self.corner_alpha(), 100)
        self.leave()
        self.assertFalse(self.overlay.dragging)
        self.assertTrue(self.overlay.isVisible())                                           # nothing is loaded: the card is back
        self.assertEqual(self.corner_alpha(), 0)

    def test_a_drag_of_a_file_that_cannot_be_opened_is_shown_refused(self):
        self.drag_over(os.path.join(self.tmp, "x.mat"))
        self.assertFalse(self.overlay._drag[0])
        self.assertIn("cannot be opened", self.overlay._drag[1])
        self.assertGreater(self.corner_alpha(), 100)

    def test_a_drag_that_carries_no_files_shows_nothing(self):
        mime = QMimeData()
        mime.setText("just some text")
        enter = QDragEnterEvent(QPoint(10, 10), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.ctx.win, enter)
        self.assertFalse(self.overlay.dragging)

    def test_dropping_ends_the_drag_display(self):
        with mock.patch.object(drop, "open_dropped"):
            mime = mime_for(self.tmp)
            self.drag_over(self.tmp)
            self.assertTrue(self.overlay.dragging)
            send_drop(self.ctx.win, mime)
        self.assertFalse(self.overlay.dragging)

    def test_the_card_goes_away_when_a_recording_is_loaded_and_a_drag_still_shows(self):
        folder = self.tdt_folder()
        drop.open_dropped(self.ctx, [folder])
        self.wait_for_a_recording()
        self.spin(lambda: not self.overlay.isVisible(), timeout=10)
        self.assertEqual(self.errors, [])
        self.assertFalse(self.overlay.isVisible())
        self.drag_over(os.path.join(self.tmp, "a.csv"))
        self.assertTrue(self.overlay.isVisible())
        self.leave()
        self.assertFalse(self.overlay.isVisible())

    def test_the_card_stays_when_the_load_fails(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        drop.open_dropped(self.ctx, [empty])
        self.spin(lambda: self.errors, timeout=10)
        self.assertTrue(self.errors)
        self.assertTrue(self.overlay.isVisible())


if __name__ == "__main__":
    unittest.main()
