"""
The shipped exe is built by PyInstaller, which bundles what it can find by reading the code. matplotlib's savefig()
imports the backend for a file format by name when it is called, so the spec has to name the vector backends itself;
if it does not, every PDF and SVG export fails in the exe (and only there: from source the backends are always
importable, so nothing else would notice).
"""

import ast
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


if __name__ == "__main__":
    unittest.main()
