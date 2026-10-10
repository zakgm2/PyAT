"""Export View (export/view_figure.py): the main plot redrawn as a publication figure. It has to be what the plot shows —
the same traces (checked against what the matplotlib engine actually draws, for every kind of recording), the range
in view, the edited title/labels/legend, the markers in view — on a white page whatever the theme, with a data CSV of
every sample in view."""

import json
import os
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pandas as pd
from numpy.testing import assert_array_equal
from PyQt6.QtWidgets import QDialog

import PyATCLI as pl
from PyATCLI import viewplan

from physicsanalysis_qt.export import figure_export, view_figure
from physicsanalysis_qt.plot.plot_signal import refresh_plot_signal_options
from physicsanalysis_qt.plot.plotting import simple_plot

from tests.test_gui_reproduces import BUILT, WindowCase


def oxysoft_cache():
    t = np.arange(600) / 10.0
    rng = np.random.default_rng(1)
    dataset = types.SimpleNamespace(
        metadata={"n_channels": 2, "fit_factor_mean": 91.25}, num_channels=4, signals=rng.normal(size=(4, 600)),
        folder_name="NIRS-1", num_samples=len(t), sample_rate=10.0, events=[{"sample": 100, "label": "A"}])
    return pl.make_oxysoft_cache("nirs.txt", dataset)


def generic_cache():
    t = np.arange(50.0)
    a = np.sin(t / 5)
    b = np.cos(t / 5)
    b[10:14] = np.nan
    table = types.SimpleNamespace(headers=["Time (s)", "Left", "Right"], data=np.column_stack([t, a, b]), name="Sheet1")
    return pl.make_generic_cache("table.csv", table)


class ShowsRecording(WindowCase):
    def show(self, cache):
        self.ctx.cache = cache
        self.ctx._data_generation += 1
        refresh_plot_signal_options(self.ctx)
        simple_plot(self.ctx)

    def assert_matches_the_engine(self):
        """view_traces says what simple_plot drew: same lines, in order, same data, colour, width, alpha, name."""
        traces, title, x_label, y_label = view_figure.view_traces(self.ctx)
        drawn = self.ctx._decim_lines
        self.assertEqual(len(traces), len(drawn))
        for t, (line, full_x, full_y) in zip(traces, drawn):
            self.assertEqual(t.label, line.get_label())
            self.assertEqual(t.color, line.get_color())
            self.assertEqual(t.lw, line.get_linewidth())
            self.assertEqual(t.alpha, line.get_alpha() if line.get_alpha() is not None else 1.0)
            assert_array_equal(t.x, full_x)
            assert_array_equal(t.y, full_y)
        self.assertEqual((title, x_label, y_label), (self.ctx._last_title, self.ctx._last_xlabel, self.ctx._last_ylabel))
        return traces


class TestSameTracesAsTheEngine(ShowsRecording):
    def test_a_tdt_signal(self):
        traces = self.assert_matches_the_engine()
        self.assertEqual([t.label for t in traces], [BUILT["normalized"]])

    def test_each_tdt_signal_on_its_own(self):
        boxes = self.ctx.plot_signal_checkboxes
        for key in ("main_driver", "isosbestic"):
            with self.subTest(key=key):
                boxes[key].setChecked(True)
                for other in boxes:
                    if other != key:
                        boxes[other].setChecked(False)
                self.assertEqual(self.ctx.plot_signals, {key})
                self.assert_matches_the_engine()

    def test_several_tdt_signals_overlaid(self):
        for key in ("main_driver", "isosbestic"):
            self.ctx.plot_signal_checkboxes[key].setChecked(True)
        traces = self.assert_matches_the_engine()
        self.assertEqual(len(traces), 3)
        self.assertTrue(view_figure.view_traces(self.ctx)[1].startswith("Overlay (3)"))

    def test_a_renamed_signal_and_a_colour_override(self):
        from physicsanalysis_qt.edit import signal_names
        self.ctx.plot_attrs["line_colors"][BUILT["normalized"]] = "#123456"
        simple_plot(self.ctx)
        signal_names.apply_signal_renames(self.ctx, {"normalized": "GCaMP dF/F"})
        traces = self.assert_matches_the_engine()
        self.assertEqual((traces[0].label, traces[0].color), ("GCaMP dF/F", "#123456"))

    def test_an_oxysoft_recording(self):
        self.show(oxysoft_cache())
        traces = self.assert_matches_the_engine()
        self.assertEqual(traces[0].label, "O2Hb channels")
        self.assertEqual(sum(t.label == "_nolegend_" for t in traces), 2)                    # the other channel of each group
        self.assertIn("Mean O2Hb  [FF: 91.2%]", [t.label for t in traces])

    def test_a_generic_table_with_gaps(self):
        self.show(generic_cache())
        traces = self.assert_matches_the_engine()
        right = next(t for t in traces if t.label == "Right")
        self.assertEqual(len(right.x), 46)                                                    # the NaN rows are not drawn ...
        self.assertEqual(len(right.y_full), 50)                                               # ... but the data CSV has them as gaps


class TestTheFigure(ShowsRecording):
    def test_it_shows_the_range_in_view_of_the_matplotlib_engine(self):
        self.ctx.ax.set_xlim(5.0, 20.0)
        self.ctx.ax.set_ylim(-1.0, 3.0)
        view = view_figure.build_view(self.ctx)
        self.assertEqual(view.xlim, (5.0, 20.0))
        self.assertEqual(view.fig.axes[0].get_xlim(), (5.0, 20.0))
        self.assertEqual(view.fig.axes[0].get_ylim(), (-1.0, 3.0))

    def test_the_range_of_the_pyqtgraph_engine_is_read_from_it(self):
        self.ctx.settings["plot_engine"] = "pyqtgraph"
        self.ctx.pg_plot_item = types.SimpleNamespace(vb=types.SimpleNamespace(viewRange=lambda: [[3.0, 9.0], [-2.0, 4.0]]))
        self.assertEqual(view_figure.view_range(self.ctx), ((3.0, 9.0), (-2.0, 4.0)))

    def test_with_nothing_to_read_the_range_is_the_whole_recording(self):
        self.ctx.ax = None
        (lo, hi), ylim = view_figure.view_range(self.ctx)
        self.assertLess(lo, 0.0)
        self.assertGreater(hi, float(self.ctx.cache["x"][-1]))
        self.assertIsNone(ylim)

    def test_title_labels_and_legend_are_the_ones_the_user_set(self):
        attrs = self.ctx.plot_attrs
        attrs.update(title="My title", xlabel="Elapsed (s)", ylabel="ΔF/F", title_fs=20, xlabel_fs=14, ylabel_fs=15, leg_fs=12, leg_loc="lower right")
        attrs["leg_entries"] = [(BUILT["normalized"], "GCaMP", True)]
        ax = view_figure.build_view(self.ctx).fig.axes[0]
        self.assertEqual((ax.get_title(), ax.get_xlabel(), ax.get_ylabel()), ("My title", "Elapsed (s)", "ΔF/F"))
        self.assertEqual(ax.title.get_fontsize(), 20)
        self.assertEqual([t.get_text() for t in ax.get_legend().get_texts()], ["GCaMP"])
        self.assertEqual(ax.get_legend()._loc, 4)                                             # "lower right"

    def test_a_hidden_legend_entry_is_not_in_the_legend_but_its_line_is_drawn(self):
        self.ctx.plot_attrs["leg_entries"] = [(BUILT["normalized"], BUILT["normalized"], False)]
        ax = view_figure.build_view(self.ctx).fig.axes[0]
        self.assertIsNone(ax.get_legend())
        self.assertTrue(any(line.get_label() == BUILT["normalized"] for line in ax.lines))

    def test_the_automatic_title_follows_the_signals_name(self):
        ax = view_figure.build_view(self.ctx).fig.axes[0]
        self.assertTrue(ax.get_title().startswith(BUILT["normalized"]))
        self.assertEqual((ax.get_xlabel(), ax.get_ylabel()), ("Time (s)", "Amplitude"))

    def test_it_is_a_white_page_with_black_text_in_the_dark_theme_too(self):
        self.ctx.settings["theme"] = "dark"
        fig = view_figure.build_view(self.ctx).fig
        self.assertEqual(tuple(fig.get_facecolor()), (1.0, 1.0, 1.0, 1.0))
        ax = fig.axes[0]
        self.assertEqual(matplotlib_color(ax.title.get_color()), (0.0, 0.0, 0.0))
        self.assertEqual(tuple(ax.get_facecolor()), (1.0, 1.0, 1.0, 1.0))

    def test_only_the_markers_in_view_are_drawn_and_listed(self):
        self.ctx.cache["markers"] = [
            {"time": 6.0, "label": "lever", "color": "green", "fontsize": 8},
            {"time": 12.0, "label": "reward", "color": "red", "fontsize": 8},
            {"time": 30.0, "label": "late", "color": "blue", "fontsize": 8}]
        self.ctx.ax.set_xlim(5.0, 15.0)
        view = view_figure.build_view(self.ctx)
        ax = view.fig.axes[0]
        legend = [t.get_text() for t in ax.get_legend().get_texts()]
        self.assertIn("lever", legend)
        self.assertIn("reward", legend)
        self.assertNotIn("late", legend)
        self.assertEqual([m[:2] for m in view.markers], [(6.0, "lever"), (12.0, "reward")])
        self.assertEqual(sum(1 for t in ax.texts if t.get_text().strip() in ("lever", "reward", "late")), 2)

    def test_highlights_and_text_notes_come_along(self):
        self.ctx.cache["highlights"] = [{"start": 8.0, "end": 10.0, "color": "yellow"}, {"start": 35.0, "end": 36.0, "color": "red"}]
        self.ctx.cache["text_annotations"] = [{"x": 7.0, "y": 0.5, "text": "peak here", "fontsize": 11}]
        self.ctx.ax.set_xlim(0.0, 20.0)
        ax = view_figure.build_view(self.ctx).fig.axes[0]
        self.assertEqual(len(ax.patches), 1)                                                  # only the highlight in view
        self.assertIn("peak here", [t.get_text() for t in ax.texts])

    def test_the_grid_follows_the_setting(self):
        self.ctx.show_grid = True
        self.assertTrue(any(line.get_visible() for line in view_figure.build_view(self.ctx).fig.axes[0].get_xgridlines()))
        self.ctx.show_grid = False
        self.assertFalse(any(line.get_visible() for line in view_figure.build_view(self.ctx).fig.axes[0].get_xgridlines()))

    def test_a_long_recording_is_thinned_to_the_limit_without_losing_its_peaks(self):
        n = 300_000
        x = np.arange(n) / 1000.0
        y = np.sin(x)
        y[123_456] = 50.0                                                                     # one narrow spike
        self.ctx.cache["x"] = x
        self.ctx.cache["signals"]["normalized"]["y"] = y
        self.ctx.cache["corr"] = y
        self.ctx.ax.set_xlim(0.0, float(x[-1]))
        with mock.patch.object(view_figure, "EXPORT_MAX_POINTS", 20_000):
            line = next(l for l in view_figure.build_view(self.ctx).fig.axes[0].lines if l.get_label() == BUILT["normalized"])
        self.assertLessEqual(len(line.get_xdata()), 20_001)
        self.assertEqual(float(np.max(line.get_ydata())), 50.0)


def matplotlib_color(color):
    from matplotlib.colors import to_rgb
    return tuple(to_rgb(color))


class TestTheDataCsv(ShowsRecording):
    def test_it_holds_every_sample_in_view_one_column_per_trace(self):
        self.ctx.plot_signal_checkboxes["main_driver"].setChecked(True)
        self.ctx.ax.set_xlim(10.0, 12.0)
        view = view_figure.build_view(self.ctx)
        table = view.data_table()
        x = self.ctx.cache["x"]
        inside = (x >= 10.0) & (x <= 12.0)
        self.assertEqual(list(table.columns), ["time_s", BUILT["normalized"], BUILT["main_driver"]])
        self.assertEqual(len(table), int(inside.sum()))
        assert_array_equal(table["time_s"].to_numpy(), x[inside])
        assert_array_equal(table[BUILT["main_driver"]].to_numpy(), self.ctx.cache["signals"]["main_driver"]["y"][inside])
        assert_array_equal(table[BUILT["normalized"]].to_numpy(), self.ctx.cache["signals"]["normalized"]["y"][inside])

    def test_a_long_view_is_not_thinned_in_the_csv_though_the_drawing_is(self):
        self.ctx.ax.set_xlim(0.0, 39.0)
        with mock.patch.object(view_figure, "EXPORT_MAX_POINTS", 500):
            view = view_figure.build_view(self.ctx)
            drawn = next(l for l in view.fig.axes[0].lines if l.get_label() == BUILT["normalized"])
            self.assertLessEqual(len(drawn.get_xdata()), 502)
        self.assertGreater(len(view.data_table()), 38_000)

    def test_oxysoft_channels_get_names_of_their_own(self):
        self.show(oxysoft_cache())
        self.ctx.ax.set_xlim(0.0, 10.0)
        columns = list(view_figure.build_view(self.ctx).data_table().columns)
        self.assertEqual(columns[:5], ["time_s", "O2Hb ch1", "HHb ch1", "O2Hb ch2", "HHb ch2"])
        self.assertIn("Mean O2Hb  [FF: 91.2%]", columns)

    def test_a_generic_table_keeps_its_gaps_and_its_own_x_name(self):
        self.show(generic_cache())
        self.ctx.ax.set_xlim(0.0, 49.0)
        table = view_figure.build_view(self.ctx).data_table()
        self.assertEqual(list(table.columns), ["Time (s)", "Left", "Right"])
        self.assertEqual(int(table["Right"].isna().sum()), 4)
        self.assertEqual(len(table), 50)

    def test_the_files_are_the_data_and_the_markers_in_view(self):
        self.ctx.cache["markers"] = [{"time": 11.0, "label": "lever", "color": "green", "fontsize": 8}]
        self.ctx.ax.set_xlim(10.0, 12.0)
        view = view_figure.build_view(self.ctx)
        base = os.path.join(self.tmp, "out")
        paths = view.write_data(base)
        self.assertEqual([os.path.basename(p) for p in paths], ["out_data.csv", "out_markers.csv"])
        self.assertEqual(len(pd.read_csv(paths[0])), len(view.data_table()))
        markers = pd.read_csv(paths[1])
        self.assertEqual(list(markers.columns), ["time_s", "label", "color"])
        self.assertEqual(markers.iloc[0].tolist(), [11.0, "lever", "green"])

    def test_no_marker_file_when_none_is_in_view(self):
        self.ctx.cache["markers"] = [{"time": 30.0, "label": "late", "color": "blue", "fontsize": 8}]
        self.ctx.ax.set_xlim(10.0, 12.0)
        paths = view_figure.build_view(self.ctx).write_data(os.path.join(self.tmp, "out"))
        self.assertEqual([os.path.basename(p) for p in paths], ["out_data.csv"])

    def test_two_traces_with_the_same_name_do_not_overwrite_each_other(self):
        view = view_figure.build_view(self.ctx)
        view.plan.traces.append(viewplan.Trace("dup", view.x, view.x * 2, view.traces[0].csv_name, y_full=view.x * 2))       # (the library's planned line)
        self.assertEqual(list(view.data_table().columns), ["time_s", BUILT["normalized"], f"{BUILT['normalized']} (2)"])


class TestExportView(ShowsRecording):
    """Export View end to end: the dialog (accepted with what each test sets), then the files in the Output folder."""

    def export(self, **changes):
        self.ctx.settings["output_folder"] = os.path.join(self.tmp, "Out")

        def accept(dialog):
            for name, value in changes.items():
                {"format": lambda v: dialog.format_combo.setCurrentIndex(dialog.format_combo.findData(v)),
                 "dpi": dialog.dpi_spin.setValue, "data": dialog.cb_data.setChecked}[name](value)
            return QDialog.DialogCode.Accepted

        with mock.patch.object(QDialog, "exec", new=accept), mock.patch("physicsanalysis_qt.app.toasts.show_window_toast"), \
                mock.patch.object(figure_export._context, "save_settings"):
            view_figure.export_view(self.ctx)
        folder = os.path.join(self.tmp, "Out", "TDT", "Rat7-250101-101010 (Analysis)")
        return folder, sorted(n for n in os.listdir(folder) if not n.startswith("."))       # (.pyat_source.json marks the folder's recording)

    def test_a_png_with_its_data_and_its_record(self):
        self.ctx.cache["markers"] = [{"time": 11.0, "label": "lever", "color": "green", "fontsize": 8}]
        self.ctx.ax.set_xlim(10.0, 12.0)
        folder, names = self.export()
        stem = "Rat7-250101-101010_view"
        self.assertEqual(names, [f"{stem}.png", f"{stem}.provenance.json", f"{stem}_data.csv", f"{stem}_markers.csv"])
        with open(os.path.join(folder, f"{stem}.provenance.json"), encoding="utf-8") as f:
            record = json.load(f)
        self.assertEqual(record["kind"], "view")
        self.assertEqual(record["analysis"]["parameters"]["x_range"], [10.0, 12.0])
        self.assertEqual(record["analysis"]["parameters"]["signals"], ["normalized"])
        self.assertEqual({o["name"] for o in record["outputs"]}, {f"{stem}.png", f"{stem}_data.csv", f"{stem}_markers.csv"})
        self.assertTrue(any("PNG image at 300 dpi" in note for note in record["notes"]))

    def test_a_vector_pdf_has_no_png_and_no_data_when_unticked(self):
        folder, names = self.export(format="pdf", data=False)
        self.assertEqual(names, ["Rat7-250101-101010_view.pdf", "Rat7-250101-101010_view.provenance.json"])
        with open(os.path.join(folder, names[0]), "rb") as f:
            self.assertEqual(f.read(5), b"%PDF-")


if __name__ == "__main__":
    unittest.main()
