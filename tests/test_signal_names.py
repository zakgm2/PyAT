"""Naming a recording's signals (edit/signal_names.py): a name given once replaces the library's built one everywhere that
signal shows up — legend, Plot menu, title, analyses, exports, provenance — survives splicing and Ctrl+Z, is saved with
the recording and comes back on the next load, and can't be made ambiguous."""

import json
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import PyATCLI as pl
from PyATCLI import provenance as pv

from physicsanalysis_qt.edit import signal_names, sidecar, undo
from physicsanalysis_qt.analysis import peth
from physicsanalysis_qt.loading import common as loader_common, tdt
from physicsanalysis_qt.edit.attributes import AttributesDialog
from physicsanalysis_qt.plot.plotting import simple_plot

from tests.test_gui_reproduces import BUILT, WindowCase



class TestRenaming(WindowCase):
    def test_the_recording_starts_with_the_library_names(self):
        self.assertEqual(self.labels(), BUILT)

    def test_a_new_name_replaces_the_built_one_in_the_data_the_menu_the_legend_and_the_title(self):
        done = signal_names.apply_signal_renames(self.ctx, {"normalized": "GCaMP dF/F"})
        self.assertEqual(done, {"normalized": "GCaMP dF/F"})
        self.assertEqual(self.labels()["normalized"], "GCaMP dF/F")
        self.assertEqual(self.labels()["main_driver"], BUILT["main_driver"])                 # the others are left alone
        self.assertEqual(self.menu_texts()[0], "GCaMP dF/F")
        self.assertEqual(self.ctx.plot_signal_button.text(), "Plot: GCaMP dF/F")
        self.assertEqual(self.legend_texts(), ["GCaMP dF/F"])
        self.assertTrue(self.ctx.ax.get_title().startswith("GCaMP dF/F"))
        self.assertEqual(self.ctx._signal_renames, {"normalized": "GCaMP dF/F"})

    def test_the_data_is_the_same_arrays_not_copies(self):
        before = self.ctx.cache["signals"]["main_driver"]["y"]
        signal_names.apply_signal_renames(self.ctx, {"main_driver": "465"}, redraw=False)
        self.assertIs(self.ctx.cache["signals"]["main_driver"]["y"], before)

    def test_ticked_boxes_stay_ticked(self):
        self.ctx.plot_signal_checkboxes["main_driver"].setChecked(True)
        signal_names.apply_signal_renames(self.ctx, {"normalized": "dF/F"})
        ticked = {k for k, b in self.ctx.plot_signal_checkboxes.items() if b.isChecked()}
        self.assertEqual(ticked, {"normalized", "main_driver"})
        self.assertEqual(self.ctx.plot_signal_button.text(), "Plot: 2 signals")

    def test_nothing_to_do_changes_nothing(self):
        for renames in ({}, {"normalized": ""}, {"normalized": "   "}, {"normalized": BUILT["normalized"]}, {"nope": "x"}):
            with self.subTest(renames=renames):
                self.assertEqual(signal_names.apply_signal_renames(self.ctx, renames, redraw=False), {})
        self.assertEqual(self.labels(), BUILT)
        self.assertEqual(self.ctx._signal_renames, {})

    def test_surrounding_spaces_are_dropped(self):
        signal_names.apply_signal_renames(self.ctx, {"normalized": "  dF/F  "}, redraw=False)
        self.assertEqual(self.labels()["normalized"], "dF/F")

    def test_two_signals_cannot_share_a_name_and_nothing_changes(self):
        with self.assertRaises(ValueError) as caught:
            signal_names.apply_signal_renames(self.ctx, {"normalized": "Same", "main_driver": "Same"}, redraw=False)
        self.assertIn("Same", str(caught.exception))
        with self.assertRaises(ValueError):
            signal_names.apply_signal_renames(self.ctx, {"normalized": BUILT["isosbestic"]}, redraw=False)
        self.assertEqual(self.labels(), BUILT)
        self.assertEqual(self.ctx._signal_renames, {})

    def test_two_signals_can_swap_names(self):
        signal_names.apply_signal_renames(self.ctx, {"main_driver": BUILT["isosbestic"], "isosbestic": BUILT["main_driver"]}, redraw=False)
        self.assertEqual(self.labels()["main_driver"], BUILT["isosbestic"])
        self.assertEqual(self.labels()["isosbestic"], BUILT["main_driver"])

    def test_a_colour_override_and_a_legend_edit_follow_the_trace_to_its_new_name(self):
        attrs = self.ctx.plot_attrs
        attrs["line_colors"].update({BUILT["normalized"]: "#123456", BUILT["main_driver"]: "#abcdef"})
        attrs["leg_entries"] = [(BUILT["normalized"], "Shown differently", False), ("not a signal", "x", True)]
        signal_names.apply_signal_renames(self.ctx, {"normalized": "dF/F"}, redraw=False)
        self.assertEqual(attrs["line_colors"], {"dF/F": "#123456", BUILT["main_driver"]: "#abcdef"})
        self.assertEqual(attrs["leg_entries"], [("dF/F", "dF/F", False), ("not a signal", "x", True)])

    def test_the_new_name_is_drawn_in_the_colour_the_trace_had(self):
        self.ctx.plot_attrs["line_colors"][BUILT["normalized"]] = "#123456"
        simple_plot(self.ctx)
        signal_names.apply_signal_renames(self.ctx, {"normalized": "dF/F"})
        line = next(l for l in self.ctx.ax.lines if l.get_label() == "dF/F")
        self.assertEqual(line.get_color(), "#123456")


class TestNamesTravelWithTheRecording(WindowCase):
    def splice_it(self, start, end):
        """A cut-out through the engine (the test context waits for its requests), reported by on_done."""
        from physicsanalysis_qt.edit import splice
        done = []
        with mock.patch.object(splice, "show_window_toast"):
            splice.apply_splice(self.ctx, pl.MODE_CUT_OUT, start, end, announce=False, on_done=done.append)
        self.assertEqual(done, [True])
        return splice

    def make_splice(self):
        return self.splice_it(10.0, 12.0)

    def test_a_splice_made_after_a_rename_keeps_it_and_so_does_restoring_the_full_recording(self):
        signal_names.apply_signal_renames(self.ctx, {"main_driver": "465 nm"}, redraw=False)
        splice = self.make_splice()
        self.assertEqual(self.labels()["main_driver"], "465 nm")
        self.assertEqual(pl.current_signal_labels(self.ctx.original_cache)["main_driver"], "465 nm")
        with mock.patch.object(splice, "show_window_toast"):
            splice.restore_full_recording(self.ctx)
        self.assertEqual(self.labels()["main_driver"], "465 nm")

    def test_a_rename_made_while_spliced_is_there_when_the_splice_is_removed(self):
        splice = self.make_splice()
        self.make_second_splice(splice)
        signal_names.apply_signal_renames(self.ctx, {"isosbestic": "405 nm"}, redraw=False)
        done = []
        with mock.patch.object(splice, "show_window_toast"):
            splice.remove_splice(self.ctx, 1, on_done=done.append)                  # replays from the original
        self.assertEqual(done, [True])
        self.assertEqual(self.labels()["isosbestic"], "405 nm")
        self.assertEqual(len(self.ctx._active_splices), 1)

    def make_second_splice(self, splice):
        self.splice_it(20.0, 22.0)

    def test_ctrl_z_does_not_bring_the_old_name_back(self):
        self.make_splice()
        signal_names.apply_signal_renames(self.ctx, {"main_driver": "465 nm"}, redraw=False)
        with mock.patch("physicsanalysis_qt.plot.plotting.simple_plot"):                  # undo redraws; the redraw is not what is tested
            undo.undo(self.ctx)                                                      # back to before the splice
        self.assertIsNone(self.ctx.original_cache)
        self.assertEqual(self.labels()["main_driver"], "465 nm")

    def test_an_analysis_and_its_export_use_the_new_name_and_the_library_agrees(self):
        signal_names.apply_signal_renames(self.ctx, {"isosbestic": "Control (405)"}, redraw=False)
        self.ctx.plot_signal = "isosbestic"
        self.modules(peth)
        peth.launch_zscore_peth(self.ctx, 20.0)
        header, rows = self.rec.csv_table()
        prov = self.rec.csv[0]["provenance"]
        self.assertEqual({r[0] for r in rows}, {"Control (405)"})
        self.assert_same_export(header, rows, self.lib_table(prov, "window"), "renamed")

    def test_the_provenance_record_names_the_signals_as_the_figure_did(self):
        signal_names.apply_signal_renames(self.ctx, {"normalized": "GCaMP dF/F"}, redraw=False)
        state = pv.recording_state(self.ctx.cache)
        self.assertEqual(state["signal_labels"]["normalized"], "GCaMP dF/F")


class TestSavedWithTheRecording(WindowCase):
    def path(self):
        return pl.signal_labels_path(self.folder)

    def test_save_changes_writes_the_names_and_the_library_reads_them_back(self):
        signal_names.apply_signal_renames(self.ctx, {"normalized": "ΔF/F (GCaMP)", "isosbestic": "405"}, redraw=False)
        with mock.patch.object(sidecar, "show_window_toast"):
            sidecar.save_changes(self.ctx)
        with open(self.path(), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"normalized": "ΔF/F (GCaMP)", "isosbestic": "405"})
        self.assertEqual(pl.read_saved_signal_labels(self.folder), {"normalized": "ΔF/F (GCaMP)", "isosbestic": "405"})
        scripted = pl.load_recording(self.folder)["cache"]                          # a script sees what the app showed
        self.assertEqual(pl.current_signal_labels(scripted)["normalized"], "ΔF/F (GCaMP)")
        self.assertEqual(pl.current_signal_labels(scripted)["main_driver"], BUILT["main_driver"])

    def test_nothing_is_written_before_save_changes(self):
        signal_names.apply_signal_renames(self.ctx, {"normalized": "dF/F"}, redraw=False)
        self.assertFalse(os.path.exists(self.path()))

    def test_the_next_load_restores_the_names_before_a_splice_replays(self):
        signal_names.apply_signal_renames(self.ctx, {"main_driver": "465 nm"}, redraw=False)
        with mock.patch.object(sidecar, "show_window_toast"):
            sidecar.save_changes(self.ctx)
        fresh = self.make_ctx(splices=[{"mode": pl.MODE_CUT_OUT, "start": 10.0, "end": 12.0}])      # opened by the engine, as Open does
        self.assertEqual(pl.current_signal_labels(fresh.cache)["main_driver"], "465 nm")
        self.assertEqual(pl.current_signal_labels(fresh.original_cache)["main_driver"], "465 nm")   # so Restore Full Recording keeps it
        self.assertLess(len(fresh.cache["x"]), len(fresh.original_cache["x"]))                       # and the splice was replayed on it
        self.assertEqual(fresh._signal_renames, {"main_driver": "465 nm"})

    def test_a_saved_name_for_a_signal_the_recording_lacks_is_ignored(self):
        os.makedirs(os.path.dirname(self.path()), exist_ok=True)
        with open(self.path(), "w", encoding="utf-8") as f:
            json.dump({"normalized": "dF/F", "gone": "x"}, f)
        fresh = self.make_ctx()
        self.assertEqual(fresh._signal_renames, {"normalized": "dF/F"})

    def test_saving_with_no_names_removes_a_stale_file(self):
        os.makedirs(os.path.dirname(self.path()), exist_ok=True)
        with open(self.path(), "w", encoding="utf-8") as f:
            json.dump({"normalized": "old"}, f)
        self.ctx._signal_renames = {}
        sidecar.save_changes(self.ctx)
        self.assertFalse(os.path.exists(self.path()))

    def test_a_damaged_file_is_reported_not_swallowed(self):
        os.makedirs(os.path.dirname(self.path()), exist_ok=True)
        with open(self.path(), "w", encoding="utf-8") as f:
            f.write("[1, 2]")
        with mock.patch.object(loader_common, "show_error") as err, mock.patch.object(loader_common, "show_window_toast"):
            tdt._load_folder(self.ctx, self.folder)                                  # Open: the engine reads the recording and says what it could not read
        err.assert_called_once()
        self.assertIn("signal names could not be read", err.call_args.args[1])
        self.assertEqual(self.labels(), BUILT)


class TestTheDialogs(WindowCase):
    def test_the_plot_menu_offers_rename_signals(self):
        self.assertIn("Rename signals…", [a.text() for a in self.ctx.plot_signal_menu.actions()])

    def test_the_rename_dialog_shows_the_current_names_and_applies_the_edits(self):
        dlg = signal_names.SignalNamesDialog(self.ctx)
        self.assertEqual({k: e.text() for k, e in dlg.edits.items()}, BUILT)
        dlg.edits["main_driver"].setText("465 nm")
        dlg.edits["isosbestic"].setText("405 nm")
        dlg._accept()
        self.assertEqual(self.labels()["main_driver"], "465 nm")
        self.assertEqual(self.labels()["isosbestic"], "405 nm")
        self.assertEqual(self.labels()["normalized"], BUILT["normalized"])
        self.assertEqual(dlg.result(), dlg.DialogCode.Accepted)

    def test_a_clashing_name_keeps_the_dialog_open_and_changes_nothing(self):
        dlg = signal_names.SignalNamesDialog(self.ctx)
        dlg.edits["main_driver"].setText("Same")
        dlg.edits["isosbestic"].setText("Same")
        with mock.patch.object(signal_names, "show_error") as err:
            dlg._accept()
        err.assert_called_once()
        self.assertNotEqual(dlg.result(), dlg.DialogCode.Accepted)
        self.assertEqual(self.labels(), BUILT)

    def test_renaming_a_legend_entry_in_edit_graph_attributes_renames_the_signal(self):
        dlg = AttributesDialog(self.ctx.win, self.ctx)
        (cb, le, orig), = dlg.entry_widgets
        self.assertEqual(orig, BUILT["normalized"])
        le.setText("GCaMP dF/F")
        dlg._apply()
        self.assertEqual(self.labels()["normalized"], "GCaMP dF/F")
        self.assertEqual(self.legend_texts(), ["GCaMP dF/F"])
        self.assertEqual(self.menu_texts()[0], "GCaMP dF/F")
        self.assertIsNone(self.ctx.plot_attrs["title"])                              # the title still follows the signal's name
        self.assertTrue(self.ctx.ax.get_title().startswith("GCaMP dF/F"))
        self.assertEqual(self.ctx._signal_renames, {"normalized": "GCaMP dF/F"})

    def test_applying_without_editing_pins_nothing_and_renames_nothing(self):
        dlg = AttributesDialog(self.ctx.win, self.ctx)
        dlg._apply()
        self.assertIsNone(self.ctx.plot_attrs["title"])
        self.assertIsNone(self.ctx.plot_attrs["xlabel"])
        self.assertEqual(self.labels(), BUILT)
        self.assertEqual(self.ctx._signal_renames, {})

    def test_a_title_the_user_typed_is_kept_and_does_not_follow_a_later_rename(self):
        dlg = AttributesDialog(self.ctx.win, self.ctx)
        dlg.e_title.setText("My figure")
        dlg._apply()
        self.assertEqual(self.ctx.plot_attrs["title"], "My figure")
        signal_names.apply_signal_renames(self.ctx, {"normalized": "dF/F"})
        self.assertEqual(self.ctx.ax.get_title(), "My figure")

    def test_a_legend_entry_that_is_not_a_signal_stays_a_legend_edit(self):
        self.ctx.cache["markers"] = [{"time": 5.0, "label": "lever", "color": "green", "fontsize": 8}]
        simple_plot(self.ctx)
        dlg = AttributesDialog(self.ctx.win, self.ctx)
        origs = [orig for _cb, _le, orig in dlg.entry_widgets]
        marker = next(o for o in origs if o not in BUILT.values())
        dlg.entry_widgets[origs.index(marker)][1].setText("Lever press")
        dlg._apply()
        self.assertEqual(self.labels(), BUILT)                                      # no signal was renamed
        self.assertEqual(self.ctx._signal_renames, {})
        self.assertIn(("{}".format(marker), "Lever press", True), self.ctx.plot_attrs["leg_entries"])
        self.assertIn("Lever press", self.legend_texts())


if __name__ == "__main__":
    unittest.main()
