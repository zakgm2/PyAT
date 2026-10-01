"""
analysis/text_annotation.py
------------------------------
Text tool: click the plot to place a free text box there, asked fresh each time (unlike markers'
configure-once-then-stamp-repeatedly pattern — two text boxes usually say different things).
Non-destructive, saved/restored like markers/highlights. Each placed box can be dragged
(right-click and hold, see interaction.py/pg_engine.py) to a new (x, y), or deleted (a plain
right-click that doesn't turn into a drag).
"""

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QSpinBox, QPushButton

from .. import undo
from ..toasts import show_error, show_window_toast

DEFAULT_FONT_SIZE = 10


class _TextAnnotationDialog(QDialog):
    """Content + font size for one text box."""

    def __init__(self, parent, initial_text="", initial_fontsize=DEFAULT_FONT_SIZE):
        super().__init__(parent)
        self.setWindowTitle("Add Text")
        self.setModal(True)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Text:"))
        self.e_text = QLineEdit(initial_text)
        layout.addWidget(self.e_text)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Font size:"))
        self.spin_size = QSpinBox()
        self.spin_size.setRange(6, 72)
        self.spin_size.setValue(initial_fontsize)
        size_row.addWidget(self.spin_size)
        size_row.addStretch(1)
        layout.addLayout(size_row)

        btn_row = QHBoxLayout()
        btn_ok = QPushButton("OK")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        self.e_text.setFocus()

    def values(self):
        return self.e_text.text().strip(), self.spin_size.value()


def toggle_text_mode(ctx):
    """Arms one-shot text placement — click the plot once to place a box (a dialog asks for the
    text + font size), and mode turns itself back off right after, whether that click placed a
    box or the dialog was cancelled. Not a stays-on toggle like Add Marker's Snipping-Tool
    style — one click of this button is one text box, matching Splice/Highlighter's own
    pick-then-one-shot convention. Clicking the button again while already armed cancels it
    (nothing placed) rather than leaving it stuck on."""
    if ctx.text_mode:
        _set_text_mode(ctx, False)
        show_window_toast(ctx, "Text placement cancelled")
        return

    if ctx.cache is None:
        show_error(ctx, "Load a recording first.")
        return

    _set_text_mode(ctx, True)
    show_window_toast(ctx, "Click the plot to place a text box")


def _set_text_mode(ctx, armed):
    ctx.text_mode = armed
    if armed:
        ctx.btn_text_tool.setStyleSheet("background-color: #FFD54F;")
        ctx.btn_text_tool.setToolTip("Placing text — click the plot to place one box")
    else:
        ctx.btn_text_tool.setStyleSheet("")
        ctx.btn_text_tool.setToolTip(
            "Text — click the plot to place a text box there (font size adjustable); "
            "right-click and hold on one to drag it, right-click without holding to delete it.")


def place_text_annotation(ctx, x, y):
    """Called on a click in text mode, with (x, y) already in data coordinates — asks for the
    text/font size, then appends it. One-shot: mode turns itself off right after, placed or not
    (cancelled, or left blank — no point placing an empty box)."""
    dlg = _TextAnnotationDialog(ctx.win)
    accepted = dlg.exec() == QDialog.DialogCode.Accepted
    _set_text_mode(ctx, False)
    if not accepted:
        return
    text, fontsize = dlg.values()
    if not text:
        return
    before = undo.snapshot(ctx)
    ctx.cache.setdefault('text_annotations', []).append(
        {"x": x, "y": y, "text": text, "fontsize": fontsize})
    undo.push(ctx, "added a text box", before)
    from ..plotting import simple_plot
    simple_plot(ctx)


def delete_text_annotation(ctx, annotation):
    """Removes one text annotation (by identity). Returns True if found and removed."""
    from ..plotting import simple_plot

    items = ctx.cache.get('text_annotations', [])
    for i, t in enumerate(items):
        if t is annotation:
            before = undo.snapshot(ctx)
            items.pop(i)
            undo.push(ctx, "deleted a text box", before)
            simple_plot(ctx)
            return True
    return False
