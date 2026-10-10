"""
app/theme.py
------------
Light/dark mode: a QPalette swap (Fusion style) for every Qt widget in
the app, plus matching colors for the matplotlib figure/axes (Qt's
palette doesn't reach into matplotlib's own rendering).
"""

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

MPL_COLORS = {
    "light": {"figure": "#ffffff", "axes": "#ffffff", "text": "#000000", "grid": "#b0b0b0"},
    "dark":  {"figure": "#2b2b2b", "axes": "#2b2b2b", "text": "#e8e8e8", "grid": "#5a5a5a"},
}


def _dark_palette():
    palette = QPalette()
    window = QColor(45, 45, 45)
    base = QColor(35, 35, 35)
    text = QColor(230, 230, 230)
    disabled = QColor(127, 127, 127)
    highlight = QColor(75, 110, 175)

    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.AlternateBase, window)
    palette.setColor(QPalette.ColorRole.ToolTipBase, text)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, window)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.BrightText, QColor("red"))
    palette.setColor(QPalette.ColorRole.Link, highlight)
    palette.setColor(QPalette.ColorRole.Highlight, highlight)
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("black"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled)
    return palette


def apply_theme(app: QApplication, theme: str):
    if theme == "dark":
        app.setStyle("Fusion")
        app.setPalette(_dark_palette())
    else:
        app.setStyle("Fusion")
        app.setPalette(app.style().standardPalette())


def mpl_colors(theme: str):
    return MPL_COLORS.get(theme, MPL_COLORS["light"])
