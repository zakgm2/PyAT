"""The main plot's engines: matplotlib and PyQtGraph (VisPy is gone), and double-clicking the PyQtGraph plot's title or an
axis label to rename it — the same gesture, dialogs and stored text the matplotlib engine has."""

import glob
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QApplication

from physicsanalysis_qt import context
from physicsanalysis_qt.app import options
from physicsanalysis_qt.plot import pg_interaction
from physicsanalysis_qt.edit import signal_names
from physicsanalysis_qt.plot.plotting import simple_plot
from physicsanalysis_qt.ui.main_window import switch_plot_engine

from tests.test_gui_reproduces import WindowCase

ROOT = Path(__file__).resolve().parent.parent


class TestVisPyIsGone(unittest.TestCase):
    def test_no_module_imports_it_and_its_files_are_gone(self):
        self.assertFalse((ROOT / "physicsanalysis_qt" / "vispy_engine.py").exists())
        self.assertFalse((ROOT / "physicsanalysis_qt" / "vispy_interaction.py").exists())
        offenders = []
        for path in glob.glob(str(ROOT / "**" / "*.py*"), recursive=True):
            if not path.endswith((".py", ".pyw")) or os.sep + "tests" + os.sep in path:
                continue
            with open(path, encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    if re.match(r"\s*(import|from)\s+vispy", line):
                        offenders.append(f"{os.path.relpath(path, ROOT)}:{n}")
        self.assertEqual(offenders, [])

    def test_it_is_not_a_dependency_or_a_bundled_extra(self):
        for name in ("pyproject.toml", "requirements.txt", "PhysicsAnalysis.spec"):
            self.assertNotIn("vispy", (ROOT / name).read_text(encoding="utf-8").lower(), name)

    def test_the_options_dialog_offers_the_two_engines_that_exist(self):
        self.assertEqual(list(options._ENGINE_LABELS), ["matplotlib", "pyqtgraph"])
        self.assertEqual(context.PLOT_ENGINES, ("matplotlib", "pyqtgraph"))

    def test_a_settings_file_that_still_says_vispy_opens_on_the_default_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            for saved, expected in (("vispy", "matplotlib"), ("pyqtgraph", "pyqtgraph"), ("matplotlib", "matplotlib"),
                                    ("nonsense", "matplotlib"), (None, "matplotlib")):
                path.write_text(json.dumps({"plot_engine": saved, "theme": "dark"}), encoding="utf-8")
                with mock.patch.object(context, "_SETTINGS_PATH", path):
                    settings = context.load_settings()
                self.assertEqual(settings["plot_engine"], expected, saved)
                self.assertEqual(settings["theme"], "dark")                                  # the rest of the file still loads


class TestTheOverrideRule(WindowCase):
    def test_text_that_is_just_the_automatic_text_is_no_override(self):
        auto = self.ctx._last_title
        context.set_text_override(self.ctx, "title", "My title")
        self.assertEqual(self.ctx.plot_attrs["title"], "My title")
        context.set_text_override(self.ctx, "title", auto)
        self.assertIsNone(self.ctx.plot_attrs["title"])

    def test_each_of_the_three_keys_compares_with_its_own_automatic_text(self):
        for key, auto in (("title", self.ctx._last_title), ("xlabel", self.ctx._last_xlabel), ("ylabel", self.ctx._last_ylabel)):
            context.set_text_override(self.ctx, key, auto)
            self.assertIsNone(self.ctx.plot_attrs[key], key)
            context.set_text_override(self.ctx, key, auto + "!")
            self.assertEqual(self.ctx.plot_attrs[key], auto + "!")


class PyQtGraphCase(WindowCase):
    """The recording in the real main window with the PyQtGraph engine up and shown (geometry needs a shown window)."""

    def setUp(self):
        super().setUp()
        self.ctx.settings["plot_engine"] = "pyqtgraph"
        switch_plot_engine(self.ctx)
        self.ctx.win.resize(1000, 700)
        self.ctx.win.show()
        self.app.processEvents()
        simple_plot(self.ctx)
        self.app.processEvents()
        self.plot_item = self.ctx.pg_plot_item

    def elements(self):
        return {"title": self.plot_item.titleLabel.item, "xlabel": self.plot_item.getAxis("bottom").label,
                "ylabel": self.plot_item.getAxis("left").label}

    def click(self, graphics_item=None, double=False, scene_point=None):
        """What the mouse sends for a click (or double-click) on `graphics_item`'s centre: press, release and — for a
        double-click, which Qt delivers as a press, a release, then a double-click event — the rest."""
        widget = self.ctx.pg_widget
        center = widget.mapFromScene(scene_point if scene_point is not None else graphics_item.sceneBoundingRect().center())
        viewport = widget.viewport()
        left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton

        def send(kind, buttons):
            event = QMouseEvent(kind, QPointF(center), QPointF(viewport.mapToGlobal(center)), left, buttons, Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(viewport, event)
        send(QEvent.Type.MouseButtonPress, left)
        send(QEvent.Type.MouseButtonRelease, none)
        if double:
            send(QEvent.Type.MouseButtonDblClick, left)
            send(QEvent.Type.MouseButtonRelease, none)
        self.app.processEvents()

    def rename_dialog(self, answer, ok=True):
        return mock.patch.object(pg_interaction.QInputDialog, "getText", return_value=(answer, ok))


class TestDoubleClickToRename(PyQtGraphCase):
    def test_the_title_and_each_axis_label_can_be_found_and_have_their_set_text(self):
        found = {key: pg_interaction._text_element_at(self.ctx, item.sceneBoundingRect().center())
                 for key, item in self.elements().items()}
        self.assertEqual(found["title"], ("title", self.ctx._last_title))
        self.assertEqual(found["xlabel"], ("xlabel", "Time (s)"))
        self.assertEqual(found["ylabel"], ("ylabel", "Amplitude"))              # not the "(x0.001)" its widget adds for the scale

    def test_empty_space_beside_the_title_and_the_plot_itself_are_not_text(self):
        title = self.elements()["title"].sceneBoundingRect()
        beside = QPointF(title.left() - 20, title.center().y())
        self.assertIsNone(pg_interaction._text_element_at(self.ctx, beside))
        inside_plot = self.ctx.pg_viewbox.sceneBoundingRect().center()
        self.assertIsNone(pg_interaction._text_element_at(self.ctx, inside_plot))

    def test_double_clicking_the_title_renames_it(self):
        with self.rename_dialog("My GCaMP trace") as asked:
            self.click(self.elements()["title"], double=True)
        asked.assert_called_once()
        self.assertEqual(asked.call_args.kwargs["text"], self.ctx._last_title)          # prefilled with what it says now
        self.assertEqual(asked.call_args.args[1:3], ("Rename Title", "Title:"))
        self.assertEqual(self.ctx.plot_attrs["title"], "My GCaMP trace")
        self.assertEqual(self.plot_item.titleLabel.text, "My GCaMP trace")

    def test_double_clicking_an_axis_label_renames_it(self):
        for key, getter, answer, prefilled in (("xlabel", lambda: self.plot_item.getAxis("bottom").labelText, "Elapsed (s)", "Time (s)"),
                                               ("ylabel", lambda: self.plot_item.getAxis("left").labelText, "ΔF/F", "Amplitude")):
            with self.subTest(key=key), self.rename_dialog(answer) as asked:
                self.click(self.elements()[key], double=True)
                self.assertEqual(asked.call_args.kwargs["text"], prefilled)
                self.assertEqual(self.ctx.plot_attrs[key], answer)
                self.assertEqual(getter(), answer)

    def test_the_new_text_survives_a_redraw_and_leaves_the_data_and_the_view_alone(self):
        before_range = self.ctx.pg_viewbox.viewRange()
        lines = [(fx, fy) for _item, fx, fy in self.ctx.pg_lines]
        with self.rename_dialog("Kept"):
            self.click(self.elements()["title"], double=True)
        simple_plot(self.ctx)
        self.assertEqual(self.plot_item.titleLabel.text, "Kept")
        self.assertEqual(self.ctx.pg_viewbox.viewRange(), before_range)
        self.assertEqual(len(self.ctx.pg_lines), len(lines))

    def test_cancelling_or_clearing_the_text_changes_nothing(self):
        auto = self.ctx._last_title
        for answer, ok in (("ignored", False), ("", True), ("   ", True)):
            with self.subTest(answer=answer, ok=ok), self.rename_dialog(answer, ok):
                self.click(self.elements()["title"], double=True)
                self.assertIsNone(self.ctx.plot_attrs["title"])
                self.assertEqual(self.plot_item.titleLabel.text, auto)

    def test_retyping_the_automatic_text_keeps_the_title_following_the_signals_name(self):
        with self.rename_dialog(self.ctx._last_title):
            self.click(self.elements()["title"], double=True)
        self.assertIsNone(self.ctx.plot_attrs["title"])
        signal_names.apply_signal_renames(self.ctx, {"normalized": "GCaMP dF/F"})
        self.assertTrue(self.plot_item.titleLabel.text.startswith("GCaMP dF/F"))

    def test_a_title_the_user_wrote_stays_when_the_signal_is_renamed(self):
        with self.rename_dialog("Figure 1A"):
            self.click(self.elements()["title"], double=True)
        signal_names.apply_signal_renames(self.ctx, {"normalized": "GCaMP dF/F"})
        self.assertEqual(self.plot_item.titleLabel.text, "Figure 1A")

    def test_edit_graph_attributes_shows_the_renamed_title(self):
        from physicsanalysis_qt.edit.attributes import AttributesDialog
        with self.rename_dialog("Figure 1A"):
            self.click(self.elements()["title"], double=True)
        self.assertEqual(AttributesDialog(self.ctx.win, self.ctx).e_title.text(), "Figure 1A")


class TestClicksOnTheTextAreNotClicksOnTheData(PyQtGraphCase):
    def test_a_double_click_on_the_title_does_not_start_an_analysis(self):
        with mock.patch("physicsanalysis_qt.analysis.dispatch.analysis_type") as analysis, self.rename_dialog("x", ok=False):
            self.click(self.elements()["title"], double=True)
        analysis.assert_not_called()

    def test_a_double_click_in_the_plot_still_starts_one(self):
        with mock.patch("physicsanalysis_qt.analysis.dispatch.analysis_type") as analysis:
            self.click(scene_point=self.ctx.pg_viewbox.sceneBoundingRect().center(), double=True)
        analysis.assert_called_once()

    def test_single_clicks_on_a_label_do_not_place_a_marker_or_anchor_a_fit(self):
        self.ctx.marker_mode = True
        with mock.patch.object(pg_interaction, "place_marker") as placed:
            for key in ("title", "xlabel", "ylabel"):
                self.click(self.elements()[key])
        placed.assert_not_called()
        self.ctx.marker_mode = False
        self.ctx.analysis_mode = "Curve Fit"
        for key in ("title", "xlabel", "ylabel"):
            self.click(self.elements()[key])
        self.assertEqual(self.ctx.slope_clicks, [])

    def test_a_single_click_in_the_plot_in_marker_mode_still_places_a_marker(self):
        self.ctx.marker_mode = True
        with mock.patch.object(pg_interaction, "place_marker") as placed:
            self.click(scene_point=self.ctx.pg_viewbox.sceneBoundingRect().center())
        placed.assert_called_once()


class TestDoubleClickOnTheLegend(PyQtGraphCase):
    """A double-click on a legend row renames that entry, as it does on the matplotlib engine."""

    def row(self, index=0):
        return self.plot_item.legend.items[index]

    def shown(self):
        return [label.text for _sample, label in self.plot_item.legend.items]

    def test_double_clicking_the_text_of_an_entry_renames_it(self):
        current = self.shown()[0]
        with self.rename_dialog("GCaMP") as asked:
            self.click(self.row()[1], double=True)
        asked.assert_called_once()
        self.assertEqual(asked.call_args.args[1:3], ("Rename Legend Entry", "Label:"))
        self.assertEqual(asked.call_args.kwargs["text"], current)                      # prefilled with what it says now
        self.assertEqual(self.ctx.plot_attrs["leg_entries"], [(current, "GCaMP", True)])
        self.assertEqual(self.shown(), ["GCaMP"])

    def test_double_clicking_the_lines_sample_does_too(self):
        with self.rename_dialog("Sample"):
            self.click(self.row()[0], double=True)
        self.assertEqual(self.shown(), ["Sample"])

    def test_the_new_name_survives_a_redraw_and_the_edit_dialog_shows_it(self):
        from physicsanalysis_qt.edit.attributes import AttributesDialog
        with self.rename_dialog("Kept"):
            self.click(self.row()[1], double=True)
        simple_plot(self.ctx)
        self.assertEqual(self.shown(), ["Kept"])
        dialog = AttributesDialog(self.ctx.win, self.ctx)
        self.assertIn("Kept", [w[1].text() for w in dialog.entry_widgets])

    def test_only_the_entry_double_clicked_is_renamed(self):
        for key in ("main_driver", "isosbestic"):
            self.ctx.plot_signal_checkboxes[key].setChecked(True)
        self.app.processEvents()
        before = self.shown()
        self.assertEqual(len(before), 3)
        with self.rename_dialog("Control"):
            self.click(self.row(2)[1], double=True)
        self.assertEqual(self.shown(), [before[0], before[1], "Control"])

    def test_cancelling_or_clearing_the_text_changes_nothing(self):
        before = self.shown()
        for answer, ok in (("ignored", False), ("", True), ("   ", True)):
            with self.subTest(answer=answer, ok=ok), self.rename_dialog(answer, ok):
                self.click(self.row()[1], double=True)
                self.assertIsNone(self.ctx.plot_attrs["leg_entries"])
                self.assertEqual(self.shown(), before)

    def test_a_click_on_the_legend_is_not_a_click_on_the_data(self):
        self.ctx.marker_mode = True
        with mock.patch("physicsanalysis_qt.analysis.dispatch.analysis_type") as analysis, mock.patch.object(pg_interaction, "place_marker") as placed,                 self.rename_dialog("x", ok=False):
            self.click(self.row()[1])                          # one click: no marker
            self.click(self.row()[1], double=True)             # two: no analysis either
        placed.assert_not_called()
        analysis.assert_not_called()


class TestDraggingATextBoxOnPyQtGraph(PyQtGraphCase):
    """Right-click and hold on a text box drags it; Ctrl+Z puts it back where it was."""

    class Drag:
        """What pyqtgraph hands the view box for a right-button drag: where it started, where the pointer is now."""
        def __init__(self, viewbox, start, now, is_start=False, is_finish=False):
            self._down, self._pos = viewbox.mapFromView(QPointF(*start)), viewbox.mapFromView(QPointF(*now))
            self._start, self._finish = is_start, is_finish

        def button(self):
            return Qt.MouseButton.RightButton

        def isStart(self):
            return self._start

        def isFinish(self):
            return self._finish

        def buttonDownPos(self):
            return self._down

        def pos(self):
            return self._pos

        def accept(self):
            pass

    def setUp(self):
        super().setUp()
        (x0, x1), (y0, y1) = self.ctx.pg_viewbox.viewRange()
        self.home = ((x0 + x1) / 2, (y0 + y1) / 2)
        self.target = (x0 + 0.25 * (x1 - x0), y0 + 0.75 * (y1 - y0))
        self.ctx.cache["text_annotations"] = [{"x": self.home[0], "y": self.home[1], "text": "note", "fontsize": 10}]
        simple_plot(self.ctx)

    def drag(self):
        vb = self.ctx.pg_viewbox
        vb.mouseDragEvent(self.Drag(vb, self.home, self.home, is_start=True))
        vb.mouseDragEvent(self.Drag(vb, self.home, self.target, is_finish=True))

    def position(self):
        (annotation,) = self.ctx.cache["text_annotations"]
        return annotation["x"], annotation["y"]

    def test_the_drag_moves_the_box(self):
        self.drag()
        self.assertAlmostEqual(self.position()[0], self.target[0], places=6)
        self.assertAlmostEqual(self.position()[1], self.target[1], places=6)

    def test_undo_puts_it_back_where_it_was_and_on_the_plot(self):
        from physicsanalysis_qt.edit import undo
        self.drag()
        self.assertEqual(undo.undo(self.ctx), "moved a text box")
        self.app.processEvents()
        self.assertEqual(self.position(), self.home)
        (annotation, item), = self.ctx._text_annotation_items
        self.assertEqual(annotation["x"], self.home[0])
        self.assertAlmostEqual(item.pos().x(), self.home[0], places=6)              # the item on the plot, not just the number
        self.assertAlmostEqual(item.pos().y(), self.home[1], places=6)

    def test_undo_twice_does_not_go_past_the_start(self):
        from physicsanalysis_qt.edit import undo
        self.drag()
        self.assertEqual(undo.undo(self.ctx), "moved a text box")
        self.assertIsNone(undo.undo(self.ctx))
        self.assertEqual(self.position(), self.home)



if __name__ == "__main__":
    unittest.main()
