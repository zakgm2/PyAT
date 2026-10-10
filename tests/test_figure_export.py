"""Exporting a figure for a manuscript (export/figure_export.py; the writing itself is figures.render): the dialog
that asks, the app naming itself in what it writes, and the whole flow: edited labels reach the
file and the data CSV and not the live figure, the choices are remembered, and the provenance record lists everything."""

import ast
import glob
import json
import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from PIL import Image
from PyQt6.QtWidgets import QDialog

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
        opened.assert_called_once_with(self.ctx, fig, "EventPETH", "L1P", provenance={"kind": "x"})

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
