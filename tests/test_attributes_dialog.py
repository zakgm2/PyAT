"""Edit Graph Attributes: what the dialog's Apply leaves behind. The rules are figures/attributes.py's (and the recording's, for naming signals); these
tests make edits through the real dialog on a plotted recording and say what the plot's attributes and the recording's signal names are afterwards, and
that the app's other ways of editing the same things (the legend double-click, retyping the title, the Rename Signals dialog) use the same rules."""

import copy
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import PyATCLI as pl

from physicsanalysis_qt import context, figures
from physicsanalysis_qt.backend import api
from physicsanalysis_qt.edit import attributes, signal_names
from physicsanalysis_qt.edit.attributes import AttributesDialog
from physicsanalysis_qt.plot import interaction
from physicsanalysis_qt.plot.plotting import simple_plot

from tests.test_gui_reproduces import BUILT
from tests.test_view_figure import ShowsRecording, oxysoft_cache

N, M, I = BUILT["normalized"], BUILT["main_driver"], BUILT["isosbestic"]


class DialogCase(ShowsRecording):
    def tick(self, *keys):
        for key in keys:
            self.ctx.plot_signal_checkboxes[key].setChecked(True)

    def entry(self, dlg, name):
        return next(w for w in dlg.entry_widgets if w[2] == name)

    def row(self, dlg, name):
        return next(r for r in dlg.color_rows if r.orig == name)

    def apply(self, tweak):
        """Opens the dialog, lets `tweak(dialog)` fill it in and presses Apply. Returns the errors the app showed."""
        dlg = AttributesDialog(self.ctx.win, self.ctx)
        tweak(dlg)
        errors = []
        with mock.patch.object(attributes, "show_error", side_effect=lambda c, message: errors.append(message)):
            dlg._apply()
        return errors

    def edits(self):
        """The legend entries that are an edit: the dialog writes a row for every entry, and a row that says what it is, shown, is no edit."""
        return [tuple(e) for e in (self.ctx.plot_attrs["leg_entries"] or []) if tuple(e) != (e[0], e[0], True)]

    def names(self):
        return pl.current_signal_labels(self.ctx.cache)


class TestApply(DialogCase):
    def test_text_sizes_bold_and_the_legend_place(self):
        def tweak(d):
            d.e_title.setText("My title")
            d.e_title_fs.setText("20")
            d.e_xlabel.setText("Elapsed (s)")
            d.e_xlabel_fs.setText("3")
            d.e_ylabel_fs.setText("abc")
            d.e_leg_fs.setText("12")
            d.leg_loc_combo.setCurrentText("best")
            d.cb_bold.setChecked(False)
        self.assertEqual(self.apply(tweak), [])
        a = self.ctx.plot_attrs
        self.assertEqual((a["title"], a["xlabel"], a["ylabel"]), ("My title", "Elapsed (s)", None))
        self.assertEqual((a["title_fs"], a["xlabel_fs"], a["ylabel_fs"], a["leg_fs"]), (20, figures.attributes.MIN_FONT_SIZE, 16, 12))      # too small: the least; not a number: as it was
        self.assertEqual((a["leg_loc"], a["bold"]), ("best", False))
        self.assertEqual(self.edits(), [])

    def test_the_plots_own_text_is_no_override(self):
        auto = self.ctx._last_title
        self.assertEqual(self.apply(lambda d: d.e_title.setText(auto)), [])
        self.assertIsNone(self.ctx.plot_attrs["title"])

    def test_a_signals_legend_entry_renames_the_signal_and_a_colour_and_a_hidden_entry(self):
        self.tick("main_driver", "isosbestic")

        def tweak(d):
            self.entry(d, N)[1].setText("GCaMP")
            self.entry(d, M)[0].setChecked(False)
            r = self.row(d, I)
            r.override = "#123456"
            r._refresh()
        self.assertEqual(self.apply(tweak), [])
        self.assertEqual(self.names()["normalized"], "GCaMP")
        self.assertEqual(self.edits(), [(M, M, False)])                                     # the renamed signal is just called that; the hidden one is the edit
        self.assertEqual(self.ctx.plot_attrs["line_colors"], {I: "#123456"})

    def test_two_signals_can_swap_names(self):
        self.tick("isosbestic")
        self.ctx.plot_attrs["line_colors"][I] = "#123456"

        def tweak(d):
            self.entry(d, N)[1].setText(I)
            self.entry(d, I)[1].setText(N)
        self.assertEqual(self.apply(tweak), [])
        self.assertEqual((self.names()["normalized"], self.names()["isosbestic"]), (I, N))
        self.assertEqual(self.ctx.plot_attrs["line_colors"], {N: "#123456"})                  # the colour went with the signal

    def test_a_shared_name_is_refused_and_nothing_changes(self):
        self.tick("main_driver")
        before, names = copy.deepcopy(self.ctx.plot_attrs), self.names()
        errors = self.apply(lambda d: (self.entry(d, M)[1].setText(N), d.e_title.setText("Not applied")))
        self.assertEqual(len(errors), 1)
        self.assertIn("Two signals can't both be called", errors[0])
        self.assertEqual(self.ctx.plot_attrs, before)                                         # not even the title: a refused rename changes nothing
        self.assertEqual(self.names(), names)

    def test_a_colour_that_is_the_default_is_no_override_and_reset_clears_it(self):
        def tweak(d):
            r = self.row(d, N)
            r.override = "#123456"
            r._refresh()
        self.assertEqual(self.apply(tweak), [])
        self.assertEqual(self.ctx.plot_attrs["line_colors"], {N: "#123456"})
        self.assertEqual(self.apply(lambda d: self.row(d, N)._reset()), [])
        self.assertEqual(self.ctx.plot_attrs["line_colors"], {})

    def test_a_channel_group_and_a_marker_are_legend_edits_only(self):
        self.show(oxysoft_cache())
        self.ctx.cache["markers"] = [{"time": 10.0, "label": "A", "color": "green", "fontsize": 8}]
        simple_plot(self.ctx)
        names = self.names()

        def tweak(d):
            self.entry(d, "O2Hb channels")[1].setText("Oxygenated")
            self.entry(d, "A")[1].setText("Marker A")
            r = self.row(d, "HHb channels")
            r.override = "#00AA00"
            r._refresh()
        self.assertEqual(self.apply(tweak), [])
        self.assertEqual(self.edits(), [("O2Hb channels", "Oxygenated", True), ("A", "Marker A", True)])
        self.assertEqual(self.ctx.plot_attrs["line_colors"], {"HHb channels": "#00AA00"})
        self.assertEqual(self.names(), names)                                                  # no signal was renamed


class TestTheAppsOtherWaysUseTheSameRules(DialogCase):
    def test_a_double_click_on_the_legend_is_the_rename_rule(self):
        self.tick("main_driver")
        simple_plot(self.ctx)
        expected = copy.deepcopy(self.ctx.plot_attrs)
        figures.attributes.rename_legend_entry(expected, list(self.ctx._legend_entries), M, "465 nm")
        interaction._rename_legend_entry(self.ctx, M, "465 nm")
        self.assertEqual(self.ctx.plot_attrs, expected)
        self.assertIn((M, "465 nm", True), self.edits())

    def test_retyping_a_title_follows_the_override_rule(self):
        context.set_text_override(self.ctx, "title", "My title")
        self.assertEqual(self.ctx.plot_attrs["title"], "My title")
        context.set_text_override(self.ctx, "title", self.ctx._last_title)
        self.assertIsNone(self.ctx.plot_attrs["title"])

    def test_the_rename_signals_dialog_refuses_what_the_recording_refuses(self):
        self.assertEqual(signal_names.name_problem({"a": "x", "b": "x"}), api.recording.name_problem({"a": "x", "b": "x"}))
        with self.assertRaisesRegex(ValueError, "Two signals can't both be called"):
            signal_names.apply_signal_renames(self.ctx, {"main_driver": N}, redraw=False)

    def test_the_engines_and_the_dialog_start_from_the_same_defaults(self):
        self.assertEqual(context.default_plot_attrs(), figures.default_plot_attrs())
        self.assertEqual(AttributesDialog.LEG_LOCS, figures.view.LEGEND_LOCATIONS)


if __name__ == "__main__":
    unittest.main()
