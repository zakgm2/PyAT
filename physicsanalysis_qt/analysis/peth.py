"""
analysis/peth.py
-------------------
Z-Score window analysis — same click-triggered dispatch as FFT/AUC
(double-click near a point after picking "Z-Score" from the toolbar's
Analysis button). Not a PETH (peri-event time histogram, which averages
many occurrences of one event) — this analyzes a single clicked point;
see analysis/event_peth.py for the real multi-trial version. Mirrors
auc.py's per-source branching (Oxysoft dual/triple-channel vs.
TDT/Generic single-channel). Generic/double-click tools like this one
deliberately analyze whichever signal the "Plot:" dropdown currently
shows (get_active_signal) rather than always the normalized signal —
that's reserved for the dataset-specific tools under Custom Statistics
(Event PETH, Find Significant Peaks), which always analyze the
corrected/normalized signal regardless of what's on screen.
"""

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QPushButton

import PhysicsLibrary as pl

from ..context import get_active_signal
from ..fonts import fig_font_sizes
from ..toasts import show_error, show_window_toast
from .analysis_picker import add_done_button
from .dispatch import add_stats_export_buttons, export_figure_to_file, get_window
from ..window_fit import fit_to_screen


def launch_zscore_peth(ctx, center_t):
    if ctx.cache is None:
        return
    pre, post = get_window(ctx)
    cache = ctx.cache

    channels = []  # (label, y, color)
    if cache.get('source') == 'Oxysoft':
        o2hb = pl.mean_channels(cache['o2hb'])
        hhb = pl.mean_channels(cache['hhb'])
        channels.append(('Mean O2Hb', o2hb, '#CC0000'))
        channels.append(('Mean HHb', hhb, '#0033CC'))
        if 'thb' in cache:
            thb = pl.mean_channels(cache['thb'])
            channels.append(('Mean tHb', thb, '#228B22'))
    elif 'corr' in cache or 'raw' in cache:
        # TDT (and any other single-signal cache carrying corr/raw) —
        # whichever signal the "Plot:" dropdown currently displays.
        _, label, y, color = get_active_signal(ctx)
        channels.append((label, y, color))
    else:
        # Generic source: no 'signals'/'corr'/'raw' — same first-column
        # fallback fft.py/auc.py use for a Generic multi-column file.
        y = next(iter(cache['y_columns'].values()))
        channels.append(('Signal', y, '#2196F3'))

    fs = cache['fs']
    results = []
    for label, y, color in channels:
        clean_signal = pl.smooth_signal(y, fs)
        slice_x, z_seg = pl.get_zscore_slice(cache['x'], clean_signal, center_t, pre=pre, post=post)
        if z_seg is None or len(z_seg) == 0:
            continue
        peak_idx = int(np.argmax(np.abs(z_seg)))
        results.append({
            "channel": label, "color": color, "slice_x": slice_x, "z_seg": z_seg,
            "peak_z": float(z_seg[peak_idx]), "peak_rel_t": float(slice_x[peak_idx] - center_t),
        })

    if not results:
        show_error(ctx, "Not enough data in this window to compute a Z-score.")
        return

    dlg = QDialog(ctx.win)
    dlg.setWindowTitle(
        f"Z-Score Analysis — {cache['store']}  |  centre {center_t:.1f}s  |  -{pre:.0f}s/+{post:.0f}s"
    )
    fit_to_screen(dlg, 700, 650)
    layout = QVBoxLayout(dlg)

    n = len(results)
    fig = Figure(figsize=(8, 4.5 * n), dpi=100)
    axes = fig.subplots(2 * n, 1, gridspec_kw={'height_ratios': [1, 2] * n})
    tfs, lfs = 12, 10
    for i, r in enumerate(results):
        ax_heat, ax_line = axes[2 * i], axes[2 * i + 1]
        z_binned = pl.bin_for_heatmap(r['z_seg'])
        # Scaled to this channel's own z-score spread rather than a fixed range, so a quiet
        # recording isn't washed out and a big responder isn't clipped.
        scale = np.nanpercentile(np.abs(r['z_seg']), 98) or 1.0
        ax_heat.imshow(z_binned.reshape(1, -1), aspect='auto', cmap='YlGnBu_r',
                       extent=[-pre, post, 0, 1], vmin=-scale, vmax=scale, interpolation='bilinear')
        ax_heat.set_yticks([])
        tfs, lfs, _ = fig_font_sizes(fig)
        ax_heat.set_ylabel(r['channel'], fontweight='bold', fontsize=lfs)

        ax_line.plot(r['slice_x'] - center_t, r['z_seg'], color=r['color'], linewidth=1.5)
        ax_line.axvline(0, color='red', linestyle='--', alpha=0.8)
        ax_line.set_xlim([-pre, post])
        ax_line.set_ylim([-scale, scale])
        ax_line.set_ylabel("Z-Score", fontweight='bold', fontsize=lfs)
    axes[-1].set_xlabel("Time from Center (s)", fontweight='bold', fontsize=lfs)

    fig.suptitle("Z-Score Analysis", fontsize=tfs, fontweight='bold')
    fig.tight_layout(rect=[0, 0.03, 1, 0.97])

    canvas = FigureCanvasQTAgg(fig)
    layout.addWidget(canvas)

    result_lbl = QLabel()
    result_lbl.setFont(QFont("Consolas", 9))
    result_lbl.setWordWrap(True)
    result_lbl.setFrameShape(QFrame.Shape.Panel)
    result_lbl.setStyleSheet("background-color: white; color: black; padding: 8px;")
    blocks = [
        f"[{r['channel']}]\n  Peak Z-score:  {r['peak_z']:.4f} at t = {r['peak_rel_t']:+.2f}s"
        for r in results
    ]
    blocks.append(f"Window: -{pre:.1f}s / +{post:.1f}s around {center_t:.2f}s")
    result_lbl.setText("\n\n".join(blocks))
    layout.addWidget(result_lbl)

    btn_row = QHBoxLayout()
    add_stats_export_buttons(
        ctx, dlg, btn_row,
        get_clipboard_text=lambda: result_lbl.text(),
        csv_default_name=f"ZScore_{cache['store']}_{int(center_t)}s",
        csv_header=["Channel", "time_from_center_s", "z_score"],
        get_csv_rows=lambda: [
            [r["channel"], f"{t - center_t:.4f}", f"{z:.4f}"]
            for r in results for t, z in zip(r['slice_x'], r['z_seg'])
        ],
    )
    btn_export = QPushButton("Export Plot")
    btn_export.clicked.connect(lambda: export_figure_to_file(ctx, fig, "ZScore", f"{int(center_t)}s"))
    btn_row.addWidget(btn_export)
    add_done_button(ctx, dlg, btn_row)
    layout.addLayout(btn_row)

    show_window_toast(ctx, f"Z-Score computed at {center_t:.1f}s")
    dlg.exec()
