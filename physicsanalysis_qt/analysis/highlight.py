"""
analysis/highlight.py
------------------------
Highlighter tool: pick one of 5 standard colors, click twice on the plot, and the range between
is shaded. Non-destructive (stored separately from the recording, like markers/splices), stacks
(each new one is independent — several can overlap), saved to a sidecar and restored on load.

Flow mirrors Splice exactly: pick a color first (small dialog, no time fields), then click twice
directly on the plot — matplotlib's click-vs-drag distinction (interaction.py's on_press/
on_release, via ctx.press_x/press_y) reuses the same pattern Splice/Curve Fit already use;
PyQtGraph has no drag-vs-pan ambiguity to resolve for a left-click, so pg_interaction.py's branch
is a plain two-click accumulator, same as its own Splice branch.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QRadioButton, QButtonGroup,
)

from .. import undo
from ..toasts import show_error, show_window_toast

# 5 standard highlighter colors — vivid names, drawn at HIGHLIGHT_ALPHA so any of them reads as
# a translucent highlight rather than an opaque block.
HIGHLIGHT_COLORS = {
    "Yellow": "#FFEB3B",
    "Green":  "#8BC34A",
    "Pink":   "#FF4D94",
    "Orange": "#FF9800",
    "Blue":   "#29B6F6",
}
HIGHLIGHT_ALPHA = 0.35


class _HighlightColorDialog(QDialog):
    """Just the color choice — no time fields, same shape as Splice's own mode picker."""

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.color = None
        self.setWindowTitle("Highlighter")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(
            "Works on a copy — the original recording is untouched.\n"
            "Pick a color, then click two points on the graph to mark the range."
        ))

        color_row = QHBoxLayout()
        self.color_group = QButtonGroup(self)
        for i, (name, hexcode) in enumerate(HIGHLIGHT_COLORS.items()):
            rb = QRadioButton(name)
            rb.setStyleSheet(f"color: {hexcode}; font-weight: bold;")
            if i == 0:
                rb.setChecked(True)
            self.color_group.addButton(rb, i)
            color_row.addWidget(rb)
        layout.addLayout(color_row)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("Start Clicking…")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self._accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _accept(self):
        idx = self.color_group.checkedId()
        names = list(HIGHLIGHT_COLORS)
        self.color = HIGHLIGHT_COLORS[names[idx if idx >= 0 else 0]]
        self.accept()


def start_highlight_flow(ctx):
    """Entry point for the sidebar's highlighter icon: asks the color first, then hands control
    to the plot for two clicks (apply_highlight_at_point, below, once it has both)."""
    if ctx.cache is None:
        show_error(ctx, "Load a recording first.")
        return False

    dlg = _HighlightColorDialog(ctx.win, ctx)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return False

    ctx._pending_highlight_color = dlg.color
    ctx.slope_clicks.clear()
    ctx.highlight_click_mode = True
    show_window_toast(ctx, "Click two points on the graph to mark the range")
    return True


def apply_highlight_at_point(ctx, x):
    """Called once per click while highlight_click_mode is on; creates the highlight on the
    second click, exactly like apply_splice_at_points but with no re-fit to wait on."""
    from ..plotting import simple_plot

    ctx.slope_clicks.append(x)
    if len(ctx.slope_clicks) < 2:
        show_window_toast(ctx, f"Point {len(ctx.slope_clicks)}: {x:.2f}s")
        return

    t1, t2 = ctx.slope_clicks
    ctx.slope_clicks.clear()
    ctx.highlight_click_mode = False
    start, end = sorted((t1, t2))

    before = undo.snapshot(ctx)
    ctx.cache.setdefault('highlights', []).append(
        {"start": start, "end": end, "color": ctx._pending_highlight_color})
    undo.push(ctx, "added a highlight", before)
    simple_plot(ctx)
    show_window_toast(ctx, f"Highlighted {start:.1f}s–{end:.1f}s")


def delete_highlight(ctx, highlight):
    """Removes one highlight (by identity, not value — two highlights can have the same
    start/end/color). Returns True if it was found and removed."""
    from ..plotting import simple_plot

    highlights = ctx.cache.get('highlights', [])
    for i, h in enumerate(highlights):
        if h is highlight:
            before = undo.snapshot(ctx)
            highlights.pop(i)
            undo.push(ctx, "deleted a highlight", before)
            simple_plot(ctx)
            return True
    return False


def find_highlight_at(ctx, x):
    """The highlight (dict) containing time x, or None — last-added wins if more than one
    overlaps there, since that's the one drawn on top."""
    if ctx.cache is None:
        return None
    for h in reversed(ctx.cache.get('highlights', [])):
        if h['start'] <= x <= h['end']:
            return h
    return None
