"""Export View and the plot on screen draw the main plot through figures/view.py, so what is exported is what the plot shows. These tests hold that:
Export View's figure is byte for byte what figures.build_view draws for the same recording, range and attributes read off the app's state; the files it
writes are the files `ViewExport.save` writes; both engines draw one line per planned trace; and the record of an Export View replays its data CSV
in the analysis library."""

import io
import json
import os
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pandas as pd

import PyATCLI as pl
from PyQt6.QtWidgets import QDialog

from physicsanalysis_qt import __version__, figures
from physicsanalysis_qt.export import figure_export, view_figure
from physicsanalysis_qt.plot.plotting import simple_plot

from tests.test_gui_reproduces import BUILT
from tests.test_plot_engines import PyQtGraphCase
from tests.test_view_figure import ShowsRecording, generic_cache, oxysoft_cache


def png(fig):
    out = io.BytesIO()
    fig.savefig(out, format="png", dpi=100)
    return out.getvalue()


class ParityCase(ShowsRecording):
    def direct_view(self, xlim, ylim):
        """figures.build_view for what the app has set — arguments read straight off the app's state, not through view_figure."""
        ctx = self.ctx
        widget = ctx.stacked_plot_widget
        return figures.build_view(ctx.cache, attrs=ctx.plot_attrs, signals=ctx.plot_signals, active=ctx.plot_signal, xlim=xlim, ylim=ylim,
                                  show_grid=ctx.show_grid, store_labels=ctx.store_labels,
                                  figsize=figures.view.view_figsize(widget.width(), widget.height()))

    def assert_same(self, what, xlim=None, ylim=None):
        ctx = self.ctx
        if xlim is None:
            xlim, ylim = ctx.ax.get_xlim(), ctx.ax.get_ylim()
        theirs = self.direct_view(xlim, ylim)
        ours = view_figure.build_view(ctx)
        self.assertEqual(png(ours.fig), png(theirs.fig), f"{what}: Export View and a direct build_view differ")
        pd.testing.assert_frame_equal(ours.data_table(), theirs.data_table())
        self.assertEqual(ours.markers, theirs.markers)
        self.assertEqual(ours.parameters(), theirs.parameters())


class TestExportViewIsWhatBuildViewDraws(ParityCase):
    def test_a_tdt_signal_zoomed_and_not(self):
        self.assert_same("default")
        self.ctx.ax.set_xlim(5.0, 20.0)
        self.ctx.ax.set_ylim(-1.0, 3.0)
        self.assert_same("zoomed")

    def test_overlaid_signals_with_a_colour_and_renamed_legend_entries(self):
        for key in ("main_driver", "isosbestic"):
            self.ctx.plot_signal_checkboxes[key].setChecked(True)
        self.ctx.plot_attrs["line_colors"][BUILT["main_driver"]] = "#123456"
        self.assert_same("overlay")
        self.ctx.plot_attrs["leg_entries"] = [(BUILT["normalized"], "GCaMP", True), (BUILT["main_driver"], BUILT["main_driver"], False)]
        self.ctx.plot_attrs.update(title="My title", xlabel="Elapsed (s)", ylabel="dF/F", title_fs=20, xlabel_fs=14, ylabel_fs=15, leg_fs=12,
                                   leg_loc="lower right", bold=False)
        self.ctx.show_grid = False
        self.assert_same("attributes")

    def test_markers_highlights_text_and_store_renames(self):
        self.ctx.cache["markers"] = [
            {"time": 6.0, "label": "lever", "color": "green", "fontsize": 8},
            {"time": 12.0, "label": "reward", "color": "red", "fontsize": 10, "label_y": 0.3},
            {"time": 14.0, "label": "", "color": "black", "fontsize": 8},
            {"time": 9.0, "label": "L1P", "color": "orange", "fontsize": 8, "store": "L1P", "phase": "high"}]
        self.ctx.store_labels = {"L1P": "Lever"}
        self.ctx.cache["highlights"] = [{"start": 8.0, "end": 10.0, "color": "#FFEB3B"}]
        self.ctx.cache["text_annotations"] = [{"x": 7.0, "y": 0.05, "text": "peak here", "fontsize": 11}]
        self.ctx.ax.set_xlim(0.0, 20.0)
        self.assert_same("annotated")

    def test_oxysoft_and_generic_recordings(self):
        self.show(oxysoft_cache())
        self.ctx.cache["markers"] = [{"time": 10.0, "label": "A", "color": "green", "fontsize": 8}]
        self.ctx.plot_attrs["line_colors"]["O2Hb channels"] = "#AA0000"
        self.assert_same("oxysoft")
        self.show(generic_cache())
        self.ctx.ax.set_xlim(0.0, 49.0)
        self.assert_same("generic")

    def test_the_range_read_from_the_pyqtgraph_engine(self):
        self.ctx.settings["plot_engine"] = "pyqtgraph"
        self.ctx.pg_plot_item = types.SimpleNamespace(vb=types.SimpleNamespace(viewRange=lambda: [[3.0, 9.0], [-2.0, 4.0]]))
        self.assert_same("pyqtgraph range", xlim=(3.0, 9.0), ylim=(-2.0, 4.0))

    def test_in_the_dark_theme_too(self):
        self.ctx.settings["theme"] = "dark"
        self.assert_same("dark")


class TestTheFilesAreWhatTheLibraryWrites(ParityCase):
    def export(self, **changes):
        self.ctx.settings["output_folder"] = os.path.join(self.tmp, "Out")

        def accept(dialog):
            for name, value in changes.items():
                {"format": lambda v: dialog.format_combo.setCurrentIndex(dialog.format_combo.findData(v))}[name](value)
            return QDialog.DialogCode.Accepted

        with mock.patch.object(QDialog, "exec", new=accept), mock.patch("physicsanalysis_qt.app.toasts.show_window_toast"), \
                mock.patch.object(figure_export._context, "save_settings"):
            view_figure.export_view(self.ctx)
        return os.path.join(self.tmp, "Out", "TDT", "Rat7-250101-101010 (Analysis)")

    def test_the_figure_the_data_and_the_markers_are_the_bytes_view_save_writes(self):
        self.ctx.cache["markers"] = [{"time": 11.0, "label": "lever", "color": "green", "fontsize": 8}]
        self.ctx.ax.set_xlim(10.0, 12.0)
        theirs = self.direct_view(self.ctx.ax.get_xlim(), self.ctx.ax.get_ylim())
        folder = self.export(format="pdf")
        stem = "Rat7-250101-101010_view"
        library = os.path.join(self.tmp, "direct", "view.pdf")
        theirs.save(library, software=f"PyAT {__version__}")
        for ours, same in ((f"{stem}.pdf", "view.pdf"), (f"{stem}_data.csv", "view_data.csv"), (f"{stem}_markers.csv", "view_markers.csv")):
            with open(os.path.join(folder, ours), "rb") as a, open(os.path.join(self.tmp, "direct", same), "rb") as b:
                self.assertEqual(a.read(), b.read(), ours)

    def test_the_record_replays_the_data_csv_and_names_the_view(self):
        for key in ("main_driver",):
            self.ctx.plot_signal_checkboxes[key].setChecked(True)
        self.ctx.ax.set_xlim(10.0, 12.0)
        folder = self.export()
        stem = "Rat7-250101-101010_view"
        with open(os.path.join(folder, f"{stem}.provenance.json"), encoding="utf-8") as f:
            record = json.load(f)
        self.assertEqual(record["kind"], "view")
        params = record["analysis"]["parameters"]
        self.assertEqual((params["x_range"], params["signals"]), ([10.0, 12.0], ["normalized", "main_driver"]))
        rep = pl.reproduce_record(os.path.join(folder, f"{stem}.provenance.json"), compare=[os.path.join(folder, f"{stem}_data.csv")])
        self.assertTrue(rep.ok, [c["message"] for c in rep.comparisons])
        self.assertGreater(rep.comparisons[0]["cells"], 100)
        self.assertEqual(rep.result.kind, "view")


class TestBothEnginesDrawTheLibrarysTraces(ShowsRecording):
    def test_the_matplotlib_engine_draws_every_trace_and_hovers_over_the_ones_that_snap(self):
        for case in ("tdt", "oxysoft", "generic"):
            if case == "oxysoft":
                self.show(oxysoft_cache())
            elif case == "generic":
                self.show(generic_cache())
            with self.subTest(case=case):
                traces, *_ = view_figure.view_traces(self.ctx)
                self.assertEqual(len(self.ctx._decim_lines), len(traces))
                self.assertEqual(len(self.ctx.tracker_dots), sum(t.snap for t in traces))              # a hover dot per line that is hovered


class TestThePyQtGraphEngine(PyQtGraphCase):
    def test_it_draws_one_line_per_trace_with_the_legend_the_matplotlib_engine_has(self):
        for key in ("main_driver", "isosbestic"):
            self.ctx.plot_signal_checkboxes[key].setChecked(True)
        traces, title, x_label, y_label = view_figure.view_traces(self.ctx)
        self.assertEqual(len(self.ctx.pg_lines), len(traces))
        self.assertEqual(self.ctx._legend_entries, [t.label for t in traces if t.label != "_nolegend_"])
        self.assertEqual((self.ctx._last_title, self.ctx._last_xlabel, self.ctx._last_ylabel), (title, x_label, y_label))

    def test_a_colour_override_reaches_the_line_and_the_widths_are_the_library_lines(self):
        self.ctx.plot_attrs["line_colors"][BUILT["normalized"]] = "#123456"
        simple_plot(self.ctx)
        item, _, _ = self.ctx.pg_lines[0]
        self.assertEqual(item.opts["pen"].color().name(), "#123456")
        self.assertEqual(item.opts["pen"].width(), 1)
        self.show_oxysoft()
        widths = [item.opts["pen"].width() for item, _, _ in self.ctx.pg_lines]
        self.assertEqual(widths, [1, 1, 1, 1, 2, 2])                                                    # channels thin, the means bold

    def show_oxysoft(self):
        self.ctx.cache = oxysoft_cache()
        self.ctx._data_generation += 1
        simple_plot(self.ctx)


if __name__ == "__main__":
    unittest.main()
