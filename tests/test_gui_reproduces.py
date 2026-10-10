"""The claim behind the scripting API: what the app exports, PyATCLI reproduces from the record the app wrote.

These tests drive the real analysis dialogs (offscreen), capture exactly the CSV rows they would export and the
provenance they hand to the export funnel, and check them against PyATCLI's analyses run on the same
recording with the recorded parameters — column for column, number for number. The last tests do it end to end:
the app's own export_file writes the CSV and its record, and `reproduce` replays the record from the recording's files."""

import csv
import json
import os
import tempfile
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

import tdt
from matplotlib.figure import Figure
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton

import PyATCLI as pl
from PyATCLI import provenance as pv
from PyATCLI import reproduce as R
from PyATCLI.analyses import run_analysis

from physicsanalysis_qt import context
from physicsanalysis_qt.export import export_provenance
from physicsanalysis_qt.analysis import auc, curve_fit, event_peth, fft, intervals, peak_finder, peth, result_window
from physicsanalysis_qt.analysis.window_settings import init_window_settings
from physicsanalysis_qt.backend.recordings import adopt, opened_from_wire
from physicsanalysis_qt.plot.plot_signal import refresh_plot_signal_options
from physicsanalysis_qt.plot.plotting import simple_plot
from physicsanalysis_qt.ui.main_window import build_main_window

TOL = 1e-4


def fake_block(n=40_000, fs=1000.0, seed=3):
    """The tdt SDK's read_block for a 40 s recording with 7 L1P presses (onsets) and a response after each."""
    rng = np.random.default_rng(seed)
    t = np.arange(n) / fs
    base = 60 + 30 * np.exp(-t / 10)
    onsets = np.array([5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 34.0])
    resp = sum(np.where(t >= e, 0.15 * np.exp(-np.clip(t - e, 0, None) / 1.5), 0.0) for e in onsets)
    f415 = (0.5 * base * (1 + 0.02 * np.sin(t)) + rng.normal(0, 0.1, n)).astype(np.float32)
    f465 = (base * (1 + 0.02 * np.sin(t)) * (1 + resp) + rng.normal(0, 0.1, n)).astype(np.float32)
    heads = tdt.StructType()
    heads.stores = {"L1P_": types.SimpleNamespace(type_str="epocs", name="L1P/"), "x465A": types.SimpleNamespace(type_str="streams", name="x465A")}
    data = tdt.StructType()
    data.streams = {"x465A": types.SimpleNamespace(data=f465, fs=fs), "x415A": types.SimpleNamespace(data=f415, fs=fs)}
    data.scalars = tdt.StructType()
    data.epocs = tdt.StructType()

    def read_block(path, headers=None, evtype=None, store=None, verbose=None):
        if isinstance(headers, int) and headers == 1:
            return heads
        if store is not None:
            block = tdt.StructType()
            block.epocs = tdt.StructType()
            block.epocs["L1P_"] = types.SimpleNamespace(name="L1P", onset=onsets, offset=onsets + 0.4)
            return block
        return data

    return read_block


class Recorder:
    """Stands in for dispatch.add_stats_export_buttons / export_figure_to_file: remembers what a dialog hands them."""

    def __init__(self):
        self.csv = []
        self.figures = []

    def add_stats(self, ctx, parent, layout, **kw):
        self.csv.append(kw)
        return None, None

    def export_figure(self, ctx, fig, prefix, tracking="", provenance=None):
        self.figures.append({"prefix": prefix, "provenance": provenance, "fig": fig})

    @staticmethod
    def resolve(value):
        return value() if callable(value) else value

    def csv_table(self, index=-1):
        """The CSV a click on Export CSV would write, as (header, rows)."""
        kw = self.csv[index]
        return self.resolve(kw["csv_header"]), kw["get_csv_rows"]()


class GuiCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name
        for name, target in (("block", mock.patch.object(tdt, "read_block", fake_block())),
                             ("settings", mock.patch.object(context, "load_settings", side_effect=context.default_settings)),
                             ("save", mock.patch.object(context, "save_settings"))):
            target.start()
            self.addCleanup(target.stop)
        self.folder = os.path.join(self.tmp, "Rat7-250101-101010")
        os.makedirs(self.folder)
        with open(os.path.join(self.folder, "Rat7-250101-101010.Tbk"), "wb") as f:
            f.write(b"block header")
        for name in ("critical", "warning", "information", "question"):
            def blocked(parent, title, text, *a, _name=name, **k):
                raise AssertionError(f"QMessageBox.{_name}({title!r}, {text!r}) would have blocked the test")
            p = mock.patch.object(QMessageBox, name, side_effect=blocked)
            p.start()
            self.addCleanup(p.stop)
        self.ctx = self.make_ctx()
        self.rec = Recorder()

    def make_ctx(self, splices=None):
        os.makedirs(os.path.join(self.folder, "JSON saves"), exist_ok=True)
        if splices is not None:
            with open(os.path.join(self.folder, "JSON saves", "splice.json"), "w") as f:
                json.dump(splices, f)
        ctx = context.AppState(self.app)
        ctx.settings["background_loading"] = False                   # an engine request is waited for right there
        self.addCleanup(lambda: ctx.engine.shutdown())
        adopt(ctx, opened_from_wire(ctx.engine.call("recording.open", {"path": self.folder, "fresh": True}, timeout=60)))   # as Open does
        init_window_settings(ctx)
        ctx.window_pre, ctx.window_post = 5.0, 8.0
        return ctx

    def modules(self, *mods):
        """Patch the helpers every analysis module imports by name, so the dialogs hand their exports to the recorder."""
        for m in (*mods, result_window):                      # (the Z-Score, AUC and FFT windows are result_window's)
            for name, repl in (("add_stats_export_buttons", self.rec.add_stats), ("export_figure_to_file", self.rec.export_figure),
                               ("show_window_toast", mock.Mock())):
                if hasattr(m, name):
                    p = mock.patch.object(m, name, repl)
                    p.start()
                    self.addCleanup(p.stop)
        self.exec_side_effect = self.click_export_plot
        self.exec_calls = []

        def exec_(dlg):
            self.exec_calls.append(dlg)
            return self.exec_side_effect(dlg)

        p = mock.patch.object(QDialog, "exec", new=exec_)
        p.start()
        self.addCleanup(p.stop)

    @staticmethod
    def click_export_plot(dlg):
        """What patching QDialog.exec does instead of blocking: press the dialog's Export Plot button."""
        for b in dlg.findChildren(QPushButton):
            if b.text() == "Export Plot":
                b.click()
        return 0

    def lib_table(self, provenance, name, store_labels=None):
        """The library's table for what a dialog said it ran."""
        return run_analysis(provenance["kind"], self.ctx.cache, provenance["parameters"], store_labels=store_labels or self.ctx.store_labels).tables[name]

    def assert_same_export(self, header, rows, table, what):
        path = os.path.join(self.tmp, f"{what}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)
        c = R.compare_table(path, table, tolerance=TOL, rounded=True)      # the app's CSVs are written with fixed decimals
        self.assertTrue(c["ok"], f"{what}: {c['message']}")
        self.assertGreater(c["cells"], 0, what)


BUILT = {"normalized": "Normalized (dF/F)", "main_driver": "Main Driver (x465A)", "isosbestic": "Isosbestic (x415A)"}


class WindowCase(GuiCase):
    """The recording shown in the real main window (offscreen, matplotlib engine)."""

    def setUp(self):
        super().setUp()
        build_main_window(self.ctx)
        self.addCleanup(self.ctx.win.close)
        refresh_plot_signal_options(self.ctx)
        simple_plot(self.ctx)

    def labels(self):
        return pl.current_signal_labels(self.ctx.cache)

    def legend_texts(self):
        legend = self.ctx.ax.get_legend()
        return [t.get_text() for t in legend.get_texts()] if legend else []

    def menu_texts(self):
        return [b.text() for b in self.ctx.plot_signal_checkboxes.values()]


class TestClickTriggeredDialogs(GuiCase):
    def test_zscore_window(self):
        self.modules(peth)
        peth.launch_zscore_peth(self.ctx, 20.0)
        header, rows = self.rec.csv_table()
        prov = self.rec.csv[0]["provenance"]
        self.assertEqual(prov["kind"], "zscore_window")
        self.assertEqual(prov["parameters"], {"center_s": 20.0, "pre_s": 5.0, "post_s": 8.0, "signal": "normalized"})
        self.assertEqual(self.rec.figures[0]["provenance"], prov)
        self.assert_same_export(header, rows, self.lib_table(prov, "window"), "zscore")

    def test_zscore_of_the_isosbestic_signal_uses_that_signals_name(self):
        self.ctx.plot_signal = "isosbestic"
        self.modules(peth)
        peth.launch_zscore_peth(self.ctx, 20.0)
        header, rows = self.rec.csv_table()
        prov = self.rec.csv[0]["provenance"]
        self.assertEqual(prov["parameters"]["signal"], "isosbestic")
        self.assertEqual({r[0] for r in rows}, {self.ctx.cache["signals"]["isosbestic"]["label"]})
        self.assert_same_export(header, rows, self.lib_table(prov, "window"), "zscore_iso")

    def test_auc_window(self):
        self.modules(auc)
        auc.launch_auc(self.ctx, 25.0)
        header, rows = self.rec.csv_table()
        prov = self.rec.csv[0]["provenance"]
        self.assertEqual(prov["kind"], "auc_window")
        self.assert_same_export(header, rows, self.lib_table(prov, "auc"), "auc")

    def test_fft_window(self):
        self.modules(fft)
        fft.launch_fft(self.ctx, 20.0)
        header, rows = self.rec.csv_table()
        prov = self.rec.csv[0]["provenance"]
        self.assertEqual(prov["kind"], "fft_window")
        self.assertGreater(len(rows), 0)
        self.assert_same_export(header, rows, self.lib_table(prov, "peaks"), "fft")

    def test_the_figure_export_carries_the_same_provenance_as_the_csv(self):
        for launch, module, prefix in ((lambda: peth.launch_zscore_peth(self.ctx, 20.0), peth, "ZScore"),
                                       (lambda: auc.launch_auc(self.ctx, 20.0), auc, "AUC"),
                                       (lambda: fft.launch_fft(self.ctx, 20.0), fft, "FFT")):
            with self.subTest(prefix):
                self.rec = Recorder()
                self.modules(module)
                launch()
                self.assertEqual(self.rec.figures[-1]["prefix"], prefix)
                self.assertEqual(self.rec.figures[-1]["provenance"], self.rec.csv[-1]["provenance"])
                self.assertIn("center_s", self.rec.figures[-1]["provenance"]["parameters"])

    def test_curve_fit(self):
        self.modules(curve_fit)
        self.ctx.ax = Figure().add_subplot()
        with mock.patch.object(curve_fit, "disarm_analysis"):
            x = self.ctx.cache["x"]
            curve_fit.launch_curve_fit(self.ctx, None, (int(np.searchsorted(x, 12.0)), 0), (int(np.searchsorted(x, 18.0)), 0))
        header, rows = self.rec.csv_table()
        prov = self.rec.resolve(self.rec.csv[0]["provenance"])
        self.assertEqual(prov["kind"], "curve_fit")
        self.assertEqual(prov["parameters"]["model"], "Linear  (y = mx + b)")
        self.assertAlmostEqual(prov["parameters"]["t1_s"], 12.0, places=2)
        self.assertEqual(self.rec.figures[0]["provenance"], prov)
        self.assertGreater(len(rows), 0)
        self.assert_same_export(header, rows, self.lib_table(prov, "fit"), "curve_fit")


class OpenEventPeth:
    """Opens the real Event PETH dialog on the fixture recording (window 3 s before, 6 s after, 2 s bins)."""

    def open(self):
        self.modules(event_peth)
        dialogs = []
        with mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=types.SimpleNamespace(update=lambda *a: None, finish=lambda *a: None)):
            self.exec_side_effect = lambda self_: dialogs.append(self_) or 0
            event_peth.launch_event_peth(self.ctx)
        self.dlg = dialogs[0]
        self.dlg.e_pre.setText("3")
        self.dlg.e_post.setText("6")
        self.dlg.e_bin.setText("2")
        with mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=types.SimpleNamespace(update=lambda *a: None, finish=lambda *a: None)):
            self.dlg._run(self.dlg.event_name)
        return self.dlg

    def view(self, dlg, view):
        dlg._view_buttons[view].setChecked(True)
        return self.rec.csv_table(0)



class TestEventPeth(OpenEventPeth, GuiCase):
    def test_every_view_exports_what_the_library_gives(self):
        dlg = self.open()
        prov = dlg._provenance()
        self.assertEqual(prov["kind"], "event_peth")
        self.assertEqual(prov["parameters"]["event"], "L1P¹")
        self.assertEqual(prov["parameters"]["selected_trials"], [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(len(prov["parameters"]["event_times"]), 7)
        for view in ("zscore", "trials", "auc", "peak", "bins"):
            with self.subTest(view):
                header, rows = self.view(dlg, view)
                self.assert_same_export(header, rows, self.lib_table(dlg._provenance(), view), f"peth_{view}")

    def test_with_trials_unchecked_the_group_and_the_checked_column_still_agree(self):
        dlg = self.open()
        from PyQt6.QtCore import Qt
        for i in (1, 4):
            dlg.trial_list.item(i).setCheckState(Qt.CheckState.Unchecked)
        prov = dlg._provenance()
        self.assertEqual(prov["parameters"]["selected_trials"], [1, 3, 4, 6, 7])
        for view in ("zscore", "trials", "auc", "peak", "bins"):
            with self.subTest(view):
                header, rows = self.view(dlg, view)
                self.assert_same_export(header, rows, self.lib_table(prov, view), f"peth_unchecked_{view}")

    def test_the_figure_export_carries_the_current_selection(self):
        dlg = self.open()
        from PyQt6.QtCore import Qt
        dlg.trial_list.item(0).setCheckState(Qt.CheckState.Unchecked)
        dlg.btn_export.click()
        fig = self.rec.figures[-1]
        self.assertEqual(fig["prefix"], "EventPETH")
        self.assertEqual(fig["provenance"]["parameters"]["selected_trials"], [2, 3, 4, 5, 6, 7])


class TestEventPethFigure(OpenEventPeth, GuiCase):
    """The heatmap's trial axis: rows centred on their trial number, labelled with the trial's own number."""

    def heat(self, dlg):
        return dlg.ax_heat.images[0], [t.get_text() for t in dlg.ax_heat.get_yticklabels()], list(dlg.ax_heat.get_yticks())

    def test_row_k_is_centred_on_k_so_the_first_trial_is_1_not_0(self):
        dlg = self.open()
        im, labels, ticks = self.heat(dlg)
        self.assertEqual(tuple(im.get_extent()), (-3.0, 6.0, 7.5, 0.5))                    # 7 trials: rows span 0.5-1.5, 1.5-2.5, ... 6.5-7.5
        self.assertEqual(ticks, [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(labels, ["1", "2", "3", "4", "5", "6", "7"])
        self.assertEqual(dlg.ax_heat.get_ylim(), (7.5, 0.5))                         # trial 1 at the top
        self.assertEqual(dlg.ax_heat.get_ylabel(), "Trial")

    def test_unchecked_trials_leave_the_remaining_ones_their_own_numbers(self):
        from PyQt6.QtCore import Qt
        dlg = self.open()
        for i in (2, 4):
            dlg.trial_list.item(i).setCheckState(Qt.CheckState.Unchecked)
        im, labels, ticks = self.heat(dlg)
        self.assertEqual(tuple(im.get_extent()[2:]), (5.5, 0.5))
        self.assertEqual(ticks, [1, 2, 3, 4, 5])
        self.assertEqual(labels, ["1", "2", "4", "6", "7"])                         # not 1..5

    def test_sorted_by_peak_the_labels_are_the_trials_in_that_order(self):
        dlg = self.open()
        dlg.sort_combo.setCurrentText(dlg.SORT_PEAK_AMPLITUDE)
        matrix = dlg.peth_result["trial_matrix"]
        expected = [str(j + 1) for j in np.argsort(np.abs(matrix).max(axis=1))[::-1]]
        _, labels, _ = self.heat(dlg)
        self.assertEqual(labels, expected)
        self.assertNotEqual(expected, [str(i) for i in range(1, 8)])                # the fixture's trials really are reordered by peak
        self.assertEqual(dlg.ax_heat.get_ylabel(), "Trial (sorted by peak)")

    def test_many_trials_get_about_ten_labels_not_one_per_row(self):
        self.ctx.cache["markers"] = [{"time": 4.0 + j, "label": "many", "color": "green", "fontsize": 8} for j in range(30)]
        dlg = self.open()
        with mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=types.SimpleNamespace(update=lambda *a: None, finish=lambda *a: None)):
            dlg.combo_event.setCurrentIndex(dlg.combo_event.findData("many"))              # picking an event re-runs it
        _, labels, ticks = self.heat(dlg)
        self.assertEqual(dlg.peth_result["trial_matrix"].shape[0], 30)
        self.assertLessEqual(len(ticks), 11)
        self.assertEqual(labels[0], "1")
        numbers = [int(t) for t in labels]
        self.assertEqual(numbers, sorted(numbers))
        self.assertEqual(ticks, list(range(1, 31, 3)))                              # every 3rd row of 30

    def test_no_trials_selected_has_no_axis_labels_to_get_wrong(self):
        dlg = self.open()
        dlg._set_all_trials_checked(False)
        self.assertEqual(list(dlg.ax_heat.get_yticks()), [])


class TestPeakFinderAndIntervals(GuiCase):
    def run_finder(self, scope, **fields):
        self.modules(peak_finder)

        def exec_(dlg):
            if isinstance(dlg, peak_finder._PeakFinderDialog):
                dlg.combo_scope.setCurrentText(scope)
                dlg.spin_z.setValue(fields.get("z", 2.0))
                for k, v in fields.items():
                    if k == "event":
                        dlg.combo_event_name.setCurrentIndex(dlg.combo_event_name.findData(v))
                dlg._accept()
                return QDialog.DialogCode.Accepted
            return 0

        self.exec_side_effect = exec_
        with mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=types.SimpleNamespace(update=lambda *a: None, finish=lambda *a: None)), \
                mock.patch("physicsanalysis_qt.plot.plotting.simple_plot"):
            peak_finder.launch_peak_finder(self.ctx)

    def test_all_events_of_one_name(self):
        self.run_finder(peak_finder.SCOPE_ALL_SAME_NAME, event="L1P¹", z=1.5)
        header, rows = self.rec.csv_table(0)
        prov = self.rec.csv[0]["provenance"]
        self.assertEqual((prov["kind"], prov["parameters"]["scope"], prov["parameters"]["event"]), ("peak_finder", "all_same_name", "L1P¹"))
        self.assert_same_export(header, rows, self.lib_table(prov, "alignment"), "peaks_same_name")

    def test_scanning_every_event_type(self):
        self.run_finder(peak_finder.SCOPE_SCAN_ALL_TYPES, z=1.5)
        header, rows = self.rec.csv_table(0)
        prov = self.rec.csv[0]["provenance"]
        self.assertEqual(prov["parameters"]["scope"], "scan_all")
        self.assertIn("L1P¹", prov["parameters"]["event_groups"])
        self.assert_same_export(header, rows, self.lib_table(prov, "scan"), "peaks_scan")

    def test_event_intervals(self):
        self.ctx.cache["markers"] = list(self.ctx.cache["detected_markers"][:8])
        self.modules(intervals)
        dlgs = []
        self.exec_side_effect = lambda d: dlgs.append(d) or 0
        intervals.launch_intervals(self.ctx)
        captured = {}

        def fake_export(ctx, parent, title, name, flt, write_fn, **kw):
            path = os.path.join(self.tmp, "intervals.csv")
            write_fn(path)
            captured.update(kw, path=path)

        with mock.patch.object(intervals, "export_file", fake_export):
            dlgs[0]._export_csv()
        prov = captured["provenance"]
        self.assertEqual(prov["kind"], "event_intervals")
        table = self.lib_table(prov, "intervals")
        c = R.compare_table(captured["path"], table, tolerance=1e-5, rounded=True)
        self.assertTrue(c["ok"], c["message"])
        self.assertEqual(len(prov["parameters"]["markers"]), 8)


def write_two_columns(path):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("a,b" + chr(10) + "1,2" + chr(10))


class TestExportFunnel(GuiCase):
    def export(self, spec=None, name="x.csv", **kw):
        out = os.path.join(self.tmp, "exports")
        os.makedirs(out, exist_ok=True)
        with mock.patch("physicsanalysis_qt.app.toasts.show_window_toast"):
            context.export_file(self.ctx, None, "Export", name, "CSV (*.csv)",
                                write_two_columns, dest_dir=out, provenance=spec, **kw)
        return os.path.join(out, name)

    def test_every_export_gets_a_record_beside_it(self):
        path = self.export({"kind": "zscore_window", "parameters": {"center_s": 1.0}})
        rec = pv.read_record(pv.sidecar_path_for(path))
        self.assertEqual((rec["kind"], rec["analysis"]["parameters"]), ("zscore_window", {"center_s": 1.0}))
        self.assertEqual(rec["software"]["app"]["name"], "PyAT")
        self.assertEqual(rec["software"]["library"], pl.__version__)
        self.assertEqual(rec["outputs"], [pv.output_entry(path)])
        self.assertEqual(rec["source"]["path"], os.path.abspath(self.folder))
        self.assertEqual(rec["recording"]["source_type"], "TDT")
        self.assertEqual(rec["recording"]["regression_method"], "ols")
        self.assertEqual(rec["pipeline"]["denoise"]["cutoff_hz"], 5)

    def test_an_export_with_no_description_still_records_the_recording_and_the_software(self):
        path = self.export(None, name="plain.csv")
        rec = pv.read_record(pv.sidecar_path_for(path))
        self.assertEqual(rec["kind"], "table")
        path = self.export(None, name="shot.png")
        self.assertEqual(pv.read_record(pv.sidecar_path_for(path))["kind"], "figure")

    def test_the_splices_names_and_store_renames_in_effect_are_recorded(self):
        self.ctx = self.make_ctx(splices=[{"mode": "cut_out", "start": 12.0, "end": 14.0}])
        self.ctx.store_labels = {"L1P": "Lever"}
        from physicsanalysis_qt.edit import signal_names
        signal_names.apply_signal_renames(self.ctx, {"main_driver": "GCaMP (465 nm)"}, redraw=False)       # (the engine is told the names with every request)
        rec = pv.read_record(pv.sidecar_path_for(self.export({"kind": "zscore_window", "parameters": {}})))
        r = rec["recording"]
        self.assertEqual(r["splices"], [{"mode": "cut_out", "start": 12.0, "end": 14.0}])
        self.assertEqual(r["store_labels"], {"L1P": "Lever"})
        self.assertEqual(r["signal_labels"]["main_driver"], "GCaMP (465 nm)")
        self.assertEqual(r["base_store"], "Rat7-250101-101010")

    def test_the_record_holds_no_recording_data(self):
        path = self.export({"kind": "zscore_window", "parameters": {"center_s": 1.0}})
        size = os.path.getsize(pv.sidecar_path_for(path))
        self.assertLess(size, 12_000)                                                     # a 40,000-sample recording, counts and hashes only

    def test_the_option_turns_it_off(self):
        self.ctx.settings["save_provenance"] = False
        path = self.export({"kind": "zscore_window", "parameters": {}})
        self.assertTrue(os.path.exists(path))
        self.assertFalse(os.path.exists(pv.sidecar_path_for(path)))

    def test_a_failure_writing_the_record_never_fails_the_export(self):
        with mock.patch.object(export_provenance, "write_beside", side_effect=OSError("disk full")):
            path = self.export({"kind": "zscore_window", "parameters": {}})
        self.assertTrue(os.path.exists(path))

    def test_the_recording_fingerprint_is_remembered_while_the_folder_is_unchanged(self):
        from PyATCLI.ops import records
        records._fingerprints.clear()                                            # (the engine remembers it)
        with mock.patch.object(records.provenance, "file_fingerprint", wraps=pl.file_fingerprint) as fp:
            self.export({"kind": "table", "parameters": {}}, name="a.csv")
            self.export({"kind": "table", "parameters": {}}, name="b.csv")
        self.assertEqual(fp.call_count, 1)

    def test_a_recording_that_is_not_in_the_cache_can_be_named_by_the_caller(self):
        self.ctx.cache = None
        path = self.export({"kind": "pt2"}, name="img.png", recording_source=self.folder)
        rec = pv.read_record(pv.sidecar_path_for(path))
        self.assertEqual(rec["source"]["name"], "Rat7-250101-101010")
        self.assertNotIn("recording", rec)


class TestEndToEnd(GuiCase):
    """The app's own export, then the library replaying it from the recording's files."""

    def write_exports(self, header, rows, prov):
        out = os.path.join(self.tmp, "exports")
        os.makedirs(out, exist_ok=True)
        path_holder = {}

        def write(path):
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(header)
                w.writerows(rows)
            path_holder["csv"] = path

        with mock.patch("physicsanalysis_qt.app.toasts.show_window_toast"):
            context.export_file(self.ctx, None, "Export", "export.csv", "CSV", write, dest_dir=out, provenance=prov)
        return path_holder["csv"], pv.sidecar_path_for(path_holder["csv"])

    def test_a_zscore_export_is_reproduced_from_its_record(self):
        self.modules(peth)
        peth.launch_zscore_peth(self.ctx, 20.0)
        header, rows = self.rec.csv_table()
        csv_path, record = self.write_exports(header, rows, self.rec.csv[0]["provenance"])
        rep = R.reproduce(record, compare=[csv_path], tolerance=TOL, strict=True)
        self.assertTrue(rep.ok, rep.comparisons)
        self.assertEqual(rep.warnings, [])

    def test_an_event_peth_export_with_splices_and_unchecked_trials_is_reproduced_from_its_record(self):
        self.ctx = self.make_ctx(splices=[{"mode": "cut_out", "start": 7.0, "end": 8.5}])
        self.assertEqual(len(self.ctx._active_splices), 1)
        self.modules(event_peth)
        dialogs = []
        stub = types.SimpleNamespace(update=lambda *a: None, finish=lambda *a: None)
        with mock.patch("physicsanalysis_qt.app.background._new_toast", return_value=stub):
            self.exec_side_effect = lambda d: dialogs.append(d) or 0
            event_peth.launch_event_peth(self.ctx)
            dlg = dialogs[0]
            dlg.e_pre.setText("3")
            dlg.e_post.setText("6")
            dlg._run(dlg.event_name)
        from PyQt6.QtCore import Qt
        dlg.trial_list.item(2).setCheckState(Qt.CheckState.Unchecked)
        dlg._view_buttons["auc"].setChecked(True)
        header, rows = self.rec.csv_table(0)
        csv_path, record = self.write_exports(header, rows, dlg._provenance())      # what Export CSV hands export_file
        rec = pv.read_record(record)
        self.assertEqual(rec["recording"]["splices"], [{"mode": "cut_out", "start": 7.0, "end": 8.5}])
        self.assertEqual(rec["analysis"]["parameters"]["selected_trials"], [1, 2, 4, 5, 6, 7])
        os.remove(os.path.join(self.folder, "JSON saves", "splice.json"))                  # undone afterwards: the record still knows
        rep = R.reproduce(record, compare=[csv_path], tolerance=TOL, strict=True)
        self.assertTrue(rep.ok, rep.comparisons)
        self.assertEqual(rep.comparisons[0]["table"], "auc")


if __name__ == "__main__":
    unittest.main()
