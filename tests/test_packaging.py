"""
The shipped exe is built by PyInstaller, which bundles what it can find by reading the code. matplotlib's savefig()
imports the backend for a file format by name when it is called, so the spec has to name the vector backends itself;
if it does not, every PDF and SVG export fails in the exe (and only there: from source the backends are always
importable, so nothing else would notice).
"""

import ast
import importlib.util
import os
import re
import unittest

from physicsanalysis_qt.figures import render

SPEC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "PhysicsAnalysis.spec")


def hidden_imports():
    with open(SPEC, encoding="utf-8") as f:
        found = re.search(r"hiddenimports=(\[[^\]]*\])", f.read())
    assert found, "PhysicsAnalysis.spec has no hiddenimports list"
    return set(ast.literal_eval(found.group(1)))


class TestSpecBundlesTheFigureBackends(unittest.TestCase):
    def test_every_vector_format_has_its_backend_named(self):
        hidden = hidden_imports()
        for fmt in render.VECTOR_FORMATS:
            self.assertIn(f"matplotlib.backends.backend_{fmt}", hidden,
                          f"PhysicsAnalysis.spec must list matplotlib.backends.backend_{fmt} in hiddenimports "
                          f"or exporting {fmt.upper()} fails in the packaged app")

    def test_the_backends_it_names_exist_in_the_installed_matplotlib(self):
        import importlib
        for name in hidden_imports():
            if name.startswith("matplotlib."):
                importlib.import_module(name)


def spec_excludes():
    with open(SPEC, encoding="utf-8") as f:
        found = re.search(r"excludes=(\[[^\]]*\])", f.read())
    assert found, "PhysicsAnalysis.spec has no excludes list"
    return set(ast.literal_eval(found.group(1)))


@unittest.skipUnless(importlib.util.find_spec("PyATCLI._optional"), "needs a PyATCLI with the optional extras")
class TestSpecBundlesTheReadersPyATCLILoadsByName(unittest.TestCase):
    """PyATCLI imports the readers of its file types by name when a file is opened, so PyInstaller cannot see them: without them named in the spec the shipped
    exe opens no TDT tank and no Excel workbook (and nothing from a source run would show it)."""

    def test_every_reader_a_release_has_is_named_and_the_language_model_is_left_out_on_purpose(self):
        from PyATCLI import _optional
        hidden, excluded = hidden_imports(), spec_excludes()
        for extra, modules in _optional.EXTRAS.items():
            for module in modules:
                if extra == "fieldstudy":
                    self.assertIn(_optional.top_level(module), excluded, f"{module} (the {extra} extra) is not bundled on purpose: it must be in the spec's excludes")
                else:
                    self.assertIn(module, hidden, f"PhysicsAnalysis.spec must list {module} (the {extra} extra) in hiddenimports or the exe cannot read that file type")


if __name__ == "__main__":
    unittest.main()
