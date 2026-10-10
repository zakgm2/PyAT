"""
analysis/curve_fit.py
------------------------
Curve Fit dialog: two anchor points on the main plot define a segment,
fit any registered model to it, view R^2/params. Copy/Export CSV go
through dispatch.py's shared add_stats_export_buttons (same as AUC/FFT/
Z-Score/Event PETH), and Export Plot through the shared
export_figure_to_file — this dialog is actually where that Copy/CSV
pattern originated, but had drifted to its own hand-rolled copy; now
back on the shared implementation.

The fit itself is the analysis engine's (the library's curve_fit, see windows.py): Recalculate Fit asks it again with the model and the
window the dialog has, and the dialog draws and exports what comes back.
"""

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton, QLineEdit,
)

from ..app import errorlog
from ..app.toasts import show_error
from .analysis_picker import add_done_button, disarm_analysis
from .dispatch import add_stats_export_buttons, export_figure_to_file, get_window
from ..backend import api
from .. import figures
from .result_window import report_label
from .windows import UNKNOWN_COLOR, channel_colors, channel_groups, column, request_analysis
from ..app.window_fit import fit_to_screen


class CurveFitDialog(QDialog):
    def __init__(self, parent, ctx, source_line, p1_tuple, p2_tuple):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Curve Fit")
        fit_to_screen(self, 720, 680)
        self.last_fit_results = []
        self._closed = False
        self.finished.connect(lambda *_: setattr(self, "_closed", True))        # an answer for a dialog that is gone is dropped

        p1_idx = p1_tuple[0]
        p2_idx = p2_tuple[0]
        self.i1, self.i2 = sorted([p1_idx, p2_idx])

        ax = ctx.ax
        raw_xlbl = ax.get_xlabel() or ctx.plot_attrs.get("xlabel") or ""
        raw_ylbl = ax.get_ylabel() or ctx.plot_attrs.get("ylabel") or ""
        self.clean_xlbl = str(raw_xlbl).replace(" (s)", "").replace("(s)", "").strip() or "Time"
        self.clean_ylbl = str(raw_ylbl).strip() or "Signal"

        self.x_data = ctx.cache['x']

        layout = QVBoxLayout(self)

        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(api.models.curve_fit_model_names())
        ctrl.addWidget(self.model_combo)

        self.recalc_btn = QPushButton("Recalculate Fit")
        self.recalc_btn.setDefault(True)
        self.recalc_btn.clicked.connect(self._run_fit)
        ctrl.addWidget(self.recalc_btn)

        ctrl.addWidget(QLabel("Window (s):"))
        pre, post = get_window(ctx)
        self.win_entry = QLineEdit(str(int(pre + post)))
        self.win_entry.setFixedWidth(50)
        ctrl.addWidget(self.win_entry)
        ctrl.addStretch(1)
        layout.addLayout(ctrl)

        self.result_lbl = report_label("Results will appear here after fitting.")
        layout.addWidget(self.result_lbl)

        self.sub_fig = figures.new_curve_fit_figure()
        self.sub_ax = None                       # made by each draw (figures.draw_curve_fit)
        self.sub_canvas = FigureCanvasQTAgg(self.sub_fig)
        layout.addWidget(self.sub_canvas, stretch=1)

        btn_row = QHBoxLayout()
        add_stats_export_buttons(
            ctx, self, btn_row,
            get_clipboard_text=lambda: self.result_lbl.text(),
            csv_default_name=lambda: f"CurveFit_{ctx.cache['store']}",
            csv_header=["Channel", "Model", "Parameter", "Value", "R2", "t1 (s)", "t2 (s)", "dt (s)"],
            get_csv_rows=self._csv_rows,
            provenance=self._provenance,
        )
        btn_plot = QPushButton("Export Plot")
        btn_plot.clicked.connect(lambda: export_figure_to_file(ctx, self.sub_fig, "CurveFit", provenance=self._provenance()))
        btn_row.addWidget(btn_plot)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close)
        add_done_button(ctx, self, btn_row)
        layout.addLayout(btn_row)

        self._run_fit()

    def _run_fit(self):
        """Asks the engine for the fit of the model chosen to the stretch between the two anchor points; _show_fit draws it when it comes."""
        model_name = self.model_combo.currentText()
        try:
            win_sec = max(1.0, float(self.win_entry.text()))
        except ValueError:
            win_sec = 30.0
        t1, t2 = float(self.x_data[self.i1]), float(self.x_data[self.i2])
        self.recalc_btn.setEnabled(False)
        started = request_analysis(
            self.ctx, "curve_fit", {"t1_s": t1, "t2_s": t2, "model": model_name, "signal": self.ctx.plot_signal, "window_s": win_sec},
            lambda result: self._show_fit(result, model_name, t1, t2), label="Fitting the curve", on_error=self._fit_failed)
        if started is None and not self._closed:
            self.recalc_btn.setEnabled(True)

    def _fit_failed(self, message):
        if self._closed:
            return
        self.recalc_btn.setEnabled(True)
        show_error(self.ctx, message)

    def _show_fit(self, result, model_name, t1, t2):
        if self._closed:
            return
        self.recalc_btn.setEnabled(True)
        colors = channel_colors(self.ctx)
        fits = result.tables["fit"]
        curve = result.tables["curve"]
        context = result.tables["context"]
        wide = {name: rows for name, rows in channel_groups(context)}
        view_start, view_end = result.summary["view"]
        lines_text = []
        fit_rows = []
        fig_channels = []

        for lname, rows in channel_groups(curve):
            y_seg = column(rows, "value")
            fit = column(rows, "fit")
            ok = bool(np.isfinite(fit).any())
            channel_fit = fits[fits["Channel"] == lname]
            r2 = float(channel_fit["R2"].iloc[0]) if len(channel_fit) else None
            context_rows = wide.get(lname, rows)
            fig_channels.append({
                "label": lname, "color": colors.get(lname, UNKNOWN_COLOR),
                "x_ctx": column(context_rows, "time_s"), "y_ctx": column(context_rows, "value"),
                "x": column(rows, "time_s"), "y": y_seg, "fit": fit if ok else None, "r2": r2 if ok else None})
            delta_x = t2 - t1
            delta_y = float(y_seg[-1] - y_seg[0])
            header = (
                f"[{lname}]\n"
                f"   P1: ({t1:.2f}s, {float(y_seg[0]):.4f})"
                f"  |  P2: ({t2:.2f}s, {float(y_seg[-1]):.4f})\n"
                f"   d{self.clean_xlbl}: {delta_x:.3f} s"
                f"  |  d{self.clean_ylbl}: {delta_y:.5f}\n"
            )

            if ok and len(channel_fit):
                names = list(channel_fit["Parameter"])
                values = [float(v) for v in channel_fit["Value"]]
                param_str = "   ".join(f"{n} = {v:.4g}" for n, v in zip(names, values))
                entry = header + f"   {param_str}\n   R2 = {r2:.4f}"
                fit_rows.append({
                    "channel": lname, "model": model_name, "param_names": names,
                    "param_values": values, "r2": r2,
                    "t1": t1, "t2": t2,
                })
            else:
                why = next((n.split("fit failed: ", 1)[1] for n in result.notes if n.startswith(f"{lname}: fit failed: ")), "no fit")
                entry = header + f"   Fit failed: {why}"

            lines_text.append(entry)

        # The figure is figures/draw.py's, the same one Open Results draws from the exported CSV
        self.sub_ax = figures.draw_curve_fit(
            self.sub_fig, fig_channels, model_name=model_name, t1=t1, t2=t2, view_start=view_start, view_end=view_end,
            x_label=self.clean_xlbl, y_label=self.clean_ylbl)
        self.sub_canvas.draw()

        divider = "\n" + "-" * 60 + "\n"
        self.result_lbl.setText(divider.join(lines_text) or "No data found.")
        self.last_fit_results = fit_rows

    def _provenance(self):
        """What was fitted — the two times (snapped to samples), the model, the signal — as an analyses.py curve_fit."""
        return {"kind": "curve_fit", "parameters": {
            "t1_s": float(self.x_data[self.i1]), "t2_s": float(self.x_data[self.i2]),
            "model": self.model_combo.currentText(), "signal": self.ctx.plot_signal}}

    def _csv_rows(self):
        rows = []
        for row in self.last_fit_results:
            for pname, pval in zip(row["param_names"], row["param_values"]):
                rows.append([row["channel"], row["model"], pname, f"{pval:.6g}", f"{row['r2']:.4f}",
                             f"{row['t1']:.4f}", f"{row['t2']:.4f}", f"{row['t2'] - row['t1']:.4f}"])
        return rows


def launch_curve_fit(ctx, source_line, p1_tuple, p2_tuple):
    disarm_analysis(ctx)  # an armed Analysis tool is good for one run (unless it's set to persist)
    errorlog.action("analysis", tool="Curve Fit")
    dlg = CurveFitDialog(ctx.win, ctx, source_line, p1_tuple, p2_tuple)
    dlg.exec()
