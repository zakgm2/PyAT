"""PyAT on an install that lacks an optional package of PyATCLI (`tdt` for TDT tanks, `openpyxl` for Excel workbooks): the window still opens, every other format still
loads, and a file that needs the missing package gets a message that says which one and how to install it.

These need a PyATCLI that has the optional extras (PyATCLI/_optional.py); on an older one the packages were imported at load time and cannot be hidden."""

import importlib.util
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from physicsanalysis_qt.context import AppState
from physicsanalysis_qt.loading import generic, oxysoft, tdt
from physicsanalysis_qt.ui.main_window import build_main_window

from tests.recordings import write_oxysoft
from tests.test_loaders_engine import LoaderCase

HAS_EXTRAS = importlib.util.find_spec("PyATCLI._optional") is not None


def without(*modules):
    """The named packages behave as if they were not installed (`import x` raises ModuleNotFoundError); the engine of these tests runs in this process."""
    return mock.patch.dict(sys.modules, {name: None for name in modules})


@unittest.skipUnless(HAS_EXTRAS, "needs a PyATCLI with the optional extras")
class TestAMissingPackage(LoaderCase):
    def test_the_window_opens_without_any_of_them(self):
        ctx = AppState(self.app)
        with without("tdt", "openpyxl", "sentence_transformers"):
            build_main_window(ctx)
        self.addCleanup(ctx.win.close)
        self.addCleanup(lambda: ctx.engine.shutdown())
        self.assertIsNotNone(ctx.win)

    def test_a_tdt_folder_without_the_tdt_package_says_which_package(self):
        folder = self.tdt_folder()
        with without("tdt"):
            tdt._load_folder(self.ctx, folder)
            self.settle()
        self.assertIsNone(self.ctx.cache)
        self.assertEqual(len(self.errors), 1, self.errors)
        self.assertIn("'tdt'", self.errors[0])
        self.assertIn('pip install "PyATCLI[tdt]"', self.errors[0])

    def test_the_other_formats_still_open_without_the_tdt_package(self):
        path = os.path.join(self.tmp, "session.txt")
        write_oxysoft(path)
        with without("tdt"):
            oxysoft._load_single_file(self.ctx, path)
            self.settle()
        self.assertEqual(self.errors, [])
        self.assertEqual(self.ctx.cache["source"], "Oxysoft")

    def test_an_excel_file_without_openpyxl_says_which_package(self):
        path = os.path.join(self.tmp, "book.xlsx")
        with open(path, "wb") as f:
            f.write(b"PK")
        with without("openpyxl"):
            generic._load_generic_path(self.ctx, path)
            self.spin(lambda: self.errors)
            self.settle()
        self.assertEqual(len(self.errors), 1, self.errors)
        self.assertIn('pip install "PyATCLI[excel]"', self.errors[0])


if __name__ == "__main__":
    unittest.main()
