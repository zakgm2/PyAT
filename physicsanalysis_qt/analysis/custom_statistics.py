"""
analysis/custom_statistics.py
--------------------------------
"Custom Statistics" picker — the home for dataset-specific analysis
tools that don't belong under the Analysis button (which is reserved
for things that work on any loaded source, analyzing whichever
signal the "Plot:" dropdown currently shows: FFT, AUC, Curve Fit,
Z-Score — see analysis/dispatch.py. Custom tools here instead always
analyze the corrected/normalized signal regardless of what's displayed.
Replaces the old
"Advanced Analysis ▾" toolbar menu with a proper picker window so a
dataset with no applicable custom tool can say so explicitly instead of
just not showing a menu.

Adding a future custom tool means adding one entry to _CUSTOM_TOOLS, not
new UI plumbing.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QPushButton

from .event_peth import launch_event_peth
from .peak_finder import launch_peak_finder
from ..app.window_fit import fit_to_screen

_CUSTOM_TOOLS = [
    {
        "label": "Event PETH (Z-score all occurrences)…",
        "tooltip": "Pick an event/marker name — Z-scores every occurrence of it "
                   "against its own baseline, stacks them as a heatmap, and plots "
                   "the trial-averaged trace, so you can check consistency across trials.",
        "requires_source": "TDT",
        "launch": launch_event_peth,
    },
    {
        "label": "Find Significant Peaks…",
        "tooltip": "Check every event type at once for an aligned neural peak (or "
                   "scan the whole recording blind) — see a summary of which event "
                   "types actually line up with a real response before adding anything.",
        "requires_source": "TDT",
        "launch": launch_peak_finder,
    },
]


def _empty_state_message(ctx, source):
    if ctx.cache is None:
        return "No data loaded.\n\nOpen a TDT recording to use these tools."
    return (f"No custom statistics for {source} data.\n\n"
            "These tools are TDT-only for now.")


def launch_custom_statistics(ctx):
    source = ctx.cache.get('source') if ctx.cache else None
    tools = [t for t in _CUSTOM_TOOLS if t["requires_source"] in (None, source)]

    dlg = QDialog(ctx.win)
    dlg.setWindowTitle("Custom Statistics")
    fit_to_screen(dlg, 420, 240 if tools else 160)
    layout = QVBoxLayout(dlg)

    if not tools:
        msg = QLabel(_empty_state_message(ctx, source))
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet("color: gray;")
        layout.addWidget(msg)
    else:
        for tool in tools:
            btn = QPushButton(tool["label"])
            btn.setToolTip(tool["tooltip"])

            def _pick(_checked=False, launch=tool["launch"]):
                dlg.accept()  # close the picker before opening a second modal dialog
                launch(ctx)

            btn.clicked.connect(_pick)
            layout.addWidget(btn)

    layout.addStretch(1)
    btn_close = QPushButton("Close")
    btn_close.clicked.connect(dlg.reject)
    layout.addWidget(btn_close)

    dlg.exec()
