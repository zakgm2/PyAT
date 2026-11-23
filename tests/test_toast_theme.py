"""The toasts follow the theme (app/toasts.py): dark on the light theme, as they always were, and white with dark text on the dark theme, where a #333
toast would vanish into the window (45, 45, 45). The window toast, the progress toast and the pinned panel are all made of the same colours."""

import os
import types
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QLabel, QMainWindow, QPushButton, QWidget

from physicsanalysis_qt.app import toasts
from physicsanalysis_qt.app.theme import apply_theme


class ToastCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, theme):
        apply_theme(self.app, theme)
        self.addCleanup(apply_theme, self.app, "light")
        win = QMainWindow()
        win.setCentralWidget(QWidget())
        win.resize(700, 420)
        win.show()
        self.addCleanup(win.close)
        return types.SimpleNamespace(win=win, settings={"theme": theme, "background_loading": False}, _toast=None, _toast_timer=None,
                                     _toast_repositioner=None, _pinned_panel=None)

    @staticmethod
    def inside(widget):
        """The colour of the widget's padding (a spot with no text on it): a pixel just in from its top edge, midway across."""
        return widget.grab().toImage().pixelColor(widget.width() // 2, 4).name()


class TestWindowToast(ToastCase):
    def test_dark_on_the_light_theme_and_white_on_the_dark_one(self):
        for theme, background, text in (("light", "#333333", "white"), ("dark", "#ffffff", "#222222")):
            with self.subTest(theme):
                ctx = self.make(theme)
                toasts.show_window_toast(ctx, "Event PETH: 7 trial(s)")
                toast = ctx._toast
                self.assertEqual(self.inside(toast), background)
                label = toast.findChild(QLabel)
                self.assertIn(f"color: {text}", label.styleSheet())
                toasts._close_toast(ctx)

    def test_it_is_told_apart_from_a_dark_window_by_more_than_its_colour(self):
        ctx = self.make("dark")
        toasts.show_window_toast(ctx, "x")
        edge = ctx._toast.grab().toImage().pixelColor(ctx._toast.width() // 2, 0).name()
        self.assertEqual(edge, "#1f1f1f")                                                       # a dark edge: an analysis tab's figure is white on the dark theme too, and the toast is white
        toasts._close_toast(ctx)
        ctx = self.make("light")
        toasts.show_window_toast(ctx, "x")
        self.assertEqual(ctx._toast.grab().toImage().pixelColor(ctx._toast.width() // 2, 0).name(), "#8a8a8a")      # (and a grey one on the light one, for over something dark)
        toasts._close_toast(ctx)

    def test_a_theme_it_does_not_know_is_the_light_one(self):
        ctx = self.make("light")
        ctx.settings["theme"] = "sepia"
        self.assertIs(toasts.toast_colors(ctx), toasts._ON_LIGHT)
        ctx.settings.pop("theme")
        self.assertIs(toasts.toast_colors(ctx), toasts._ON_LIGHT)


class TestPinnedPanelAndProgressToast(ToastCase):
    def test_the_pinned_panel_is_white_on_the_dark_theme_and_its_button_is_as_it_was(self):
        for theme, background in (("light", "#333333"), ("dark", "#ffffff")):
            with self.subTest(theme):
                ctx = self.make(theme)
                toasts.show_pinned_panel(ctx, "Click the plot", "Done", lambda: None)
                self.assertEqual(self.inside(ctx._pinned_panel), background)
                self.assertIn("#FFD54F", ctx._pinned_panel.findChild(QPushButton).styleSheet())
                toasts.hide_pinned_panel(ctx)

    def test_the_progress_toast_is_white_on_the_dark_theme_with_dark_text_and_a_light_track(self):
        for theme, background, text, track in (("light", "#333333", "white", "#555"), ("dark", "#ffffff", "#222222", "#d9d9d9")):
            with self.subTest(theme):
                ctx = self.make(theme)
                progress = toasts.ProgressToast(ctx, "Computing Event PETH", on_cancel=lambda: None)
                toast = progress._build()
                toast.show()
                self.assertEqual(self.inside(toast), background)
                sheet = toast.styleSheet()
                self.assertIn(f"color: {text}", sheet)
                self.assertIn(f"QProgressBar {{ background-color: {track}", sheet)
                self.assertIn("#FFD54F" if theme == "light" else "#F9A825", sheet)               # (the bar's colour is readable on white too)
                self.assertTrue(progress._cancel_btn.styleSheet())
                toast.hide()
                toast.deleteLater()


if __name__ == "__main__":
    unittest.main()
