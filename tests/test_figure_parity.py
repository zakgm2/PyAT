"""The picture PyAT's analysis windows show is the picture Open Results draws from the files they left.

The windows draw through figures.draw (analysis/peth.py, auc.py, fft.py, curve_fit.py, event_peth.py call
draw.zscore_window_figure, ... draw_event_peth), from the arrays they hold; Open Results draws a result's tables with the
same module's *_from_tables functions. These tests open the real windows (offscreen), draw what they draw, run the same analysis
through the engine's `run_analysis`, and require the two pictures to be identical, byte for byte — so a figure opened from disk can
never drift from the figure that was on the screen."""

import io
import os
import types
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6.QtCore import Qt

import PyATCLI as pl

from physicsanalysis_qt.backend.recordings import adopt, opened_from_wire
from physicsanalysis_qt.analysis import auc, curve_fit, fft, peth
from physicsanalysis_qt.figures import draw

from tests.test_gui_reproduces import GuiCase, OpenEventPeth
from tests.recordings import write_oxysoft


def png(fig):
    out = io.BytesIO()
    fig.savefig(out, format="png", dpi=100)
    return out.getvalue()


class ParityCase(OpenEventPeth, GuiCase):
    def assert_same(self, on_screen, drawn, what):
        self.assertEqual(png(on_screen), png(drawn), f"{what}: the window's figure and the one drawn from its tables differ")

    def window_figure(self, module, launch, *args):
        self.modules(module)
        self.rec.figures.clear()
        launch(self.ctx, *args)
        return self.rec.figures[-1]["fig"]


class TestSinglePointWindows(ParityCase):
    def test_zscore_auc_and_fft_on_a_tdt_recording_and_an_oxysoft_one(self):
        builders = {"zscore": (peth, peth.launch_zscore_peth, "zscore_window", draw.zscore_window_from_tables),
                    "auc": (auc, auc.launch_auc, "auc_window", draw.auc_window_from_tables),
                    "fft": (fft, fft.launch_fft, "fft_window", draw.fft_window_from_tables)}
        for source, center in (("TDT", 20.0), ("Oxysoft", 30.0)):
            if source == "Oxysoft":                                       # the engine opens it, as Open does: the windows ask the engine
                path = os.path.join(self.tmp, "session.txt")
                write_oxysoft(path)
                adopt(self.ctx, opened_from_wire(self.ctx.engine.call("recording.open", {"path": path, "fresh": True}, timeout=60)))
                self.ctx.window_pre, self.ctx.window_post = 5.0, 8.0
            cache = self.ctx.cache
            for name, (module, launch, kind, from_tables) in builders.items():
                with self.subTest(window=name, source=source):
                    on_screen = self.window_figure(module, launch, center)
                    result = pl.run_analysis(kind, cache, {"center_s": center, "pre_s": self.ctx.window_pre, "post_s": self.ctx.window_post})
                    self.assert_same(on_screen, from_tables(result.tables, result.parameters), f"{name} window ({source})")


class TestCurveFit(ParityCase):
    def test_every_model_and_the_first_draw(self):
        dialogs = []
        self.modules(curve_fit)
        self.exec_side_effect = lambda d: dialogs.append(d) or 0
        self.ctx.ax = types.SimpleNamespace(get_xlabel=lambda: "Time (s)", get_ylabel=lambda: "Amplitude")      # what the real plot says
        x = self.ctx.cache["x"]
        i1, i2 = int(np.searchsorted(x, 15.0)), int(np.searchsorted(x, 19.0))
        curve_fit.launch_curve_fit(self.ctx, None, (i1, float(x[i1])), (i2, float(x[i2])))
        dlg = dialogs[-1]
        models = [dlg.model_combo.itemText(i) for i in range(dlg.model_combo.count())]
        self.assertGreaterEqual(len(models), 6)
        for model in models:
            dlg.model_combo.setCurrentText(model)
            dlg._run_fit()
            with self.subTest(model=model):
                result = pl.run_analysis("curve_fit", self.ctx.cache, {"t1_s": float(x[i1]), "t2_s": float(x[i2]), "model": model, "window_s": 13.0})
                self.assert_same(dlg.sub_fig, draw.curve_fit_from_tables(result.tables, result.parameters, y_label="Amplitude"), f"curve fit ({model})")


class TestEventPeth(ParityCase):
    def test_every_view_with_every_trial_and_with_some_unchecked_and_sorted(self):
        dlg = self.open()
        for suffix, selected, sort in (("all trials", None, False), ("trials 1,3,4,6,7 sorted by peak", [1, 3, 4, 6, 7], True)):
            if selected is not None:
                for i in (1, 4):
                    dlg.trial_list.item(i).setCheckState(Qt.CheckState.Unchecked)
                dlg.sort_combo.setCurrentText(dlg.SORT_PEAK_AMPLITUDE)
            result = pl.run_analysis("event_peth", self.ctx.cache, {"event": "L1P¹", "pre_s": 3.0, "post_s": 6.0, "bin_s": 2.0, "selected_trials": selected})
            for view in draw.EVENT_PETH_VIEWS:
                with self.subTest(view=view, trials=suffix):
                    dlg._view_buttons[view].setChecked(True)
                    self.assert_same(dlg.fig, draw.event_peth_from_tables(result.tables, result.parameters, view=view, sort_by_peak=sort), f"Event PETH {view}, {suffix}")

    def test_a_title_typed_into_the_window(self):
        dlg = self.open()
        for i in (1, 4):
            dlg.trial_list.item(i).setCheckState(Qt.CheckState.Unchecked)
        dlg.e_title.setText("A title of my own")
        dlg.e_title.editingFinished.emit()
        dlg._view_buttons["bins"].setChecked(True)
        result = pl.run_analysis("event_peth", self.ctx.cache, {"event": "L1P¹", "pre_s": 3.0, "post_s": 6.0, "bin_s": 2.0, "selected_trials": [1, 3, 4, 6, 7]})
        self.assert_same(dlg.fig, draw.event_peth_from_tables(result.tables, result.parameters, view="bins", title="A title of my own"), "Event PETH, titled")

    def test_the_window_draws_the_same_picture_again_after_other_views(self):
        """A redraw must not depend on what the window showed before (matplotlib's tight layout remembers its last axes)."""
        dlg = self.open()
        dlg._view_buttons["zscore"].setChecked(True)
        first = png(dlg.fig)
        for view in ("trials", "bins", "peak"):
            dlg._view_buttons[view].setChecked(True)
        dlg._view_buttons["zscore"].setChecked(True)
        self.assertEqual(png(dlg.fig), first)


if __name__ == "__main__":
    unittest.main()
