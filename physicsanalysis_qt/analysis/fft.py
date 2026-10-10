"""
analysis/fft.py
---------------
FFT viewer window — one axis per channel (Oxysoft's O2Hb/HHb/optional tHb, or the single TDT/Generic signal). Same click-triggered dispatch
as AUC/Z-Score (double-click near a point after picking "FFT" from the toolbar's Analysis button). Generic/double-click tools like this one
deliberately analyze whichever signal the "Plot:" dropdown currently shows (get_active_signal) rather than always the normalized signal —
that's reserved for the dataset-specific tools under Custom Statistics (Event PETH, Find Significant Peaks), which always analyze the
corrected/normalized signal regardless of what's on screen.

The analysis is the analysis engine's (the library's fft_window, see windows.py). This module prints what comes back and draws it; the
window itself is result_window.py's.
"""

from .. import figures
from .result_window import run_click_analysis, show_result_window
from .windows import UNKNOWN_COLOR, channel_colors, channel_groups, column


def launch_fft(ctx, center_t):
    run_click_analysis(ctx, center_t, "FFT", "fft_window", _show_fft)


def _show_fft(ctx, center_t, pre, post, result):
    fs = ctx.cache['fs']
    colors = channel_colors(ctx)
    peak_table = result.tables["peaks"]

    last_fft_results = []  # [{"channel": str, "peaks": [{"freq_hz","power","bpm"}, ...], "freqs", "power", "color"}, ...]
    for name, rows in channel_groups(result.tables["spectrum"]):
        found = peak_table[peak_table["Channel"] == name]
        last_fft_results.append({
            "channel": name, "color": colors.get(name, UNKNOWN_COLOR), "freqs": column(rows, "frequency_hz"), "power": column(rows, "power"),
            "peaks": [{"freq_hz": float(p["Frequency (Hz)"]), "bpm": float(p["BPM"]), "power": float(p["Power"])} for _, p in found.iterrows()]})

    fig = figures.fft_window_figure(
        [{"channel": r["channel"], "color": r["color"], "freqs": r["freqs"], "power": r["power"]} for r in last_fft_results],
        fs, center_t, pre, post)

    blocks = []
    for r in last_fft_results:
        if not r["peaks"]:
            blocks.append(f"[{r['channel']}]\n  No significant peaks found.")
            continue
        peak_lines = "\n".join(
            f"  Peak {i + 1}: {p['freq_hz']:.2f} Hz ({p['bpm']:.0f} bpm)  power={p['power']:.4f}"
            for i, p in enumerate(r["peaks"])
        )
        blocks.append(f"[{r['channel']}]\n{peak_lines}")

    show_result_window(
        ctx, center_t, pre, post, name="FFT", prefix="FFT", kind="fft_window", fig=fig, report="\n\n".join(blocks),
        csv_header=["Channel", "Peak Rank", "Frequency (Hz)", "BPM", "Power"],
        csv_rows=lambda: [
            [r["channel"], i + 1, f"{p['freq_hz']:.4f}", f"{p['bpm']:.1f}", f"{p['power']:.4f}"]
            for r in last_fft_results for i, p in enumerate(r["peaks"])
        ],
    )
