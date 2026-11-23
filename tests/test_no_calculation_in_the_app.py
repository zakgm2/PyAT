"""The app shows what the analysis library works out; it does not work out statistics of its own. (tests/test_backend_boundary.py keeps the app from importing
the library outside backend/; this keeps calculations from creeping back into the windows, where a script and the command line could not reach them.)

What is checked, over every module of the app:
  - no statistics package is imported (scipy, statsmodels, scikit-learn, the statistics module);
  - no call of a statistic by name (mean, std, median, percentile, correlation, a fit, an integral, ...) — except the ones in ALLOWED, each with the reason.

What is not a calculation: arranging a picture (the extent of a colour scale, where bars sit), finding the sample nearest the pointer, formatting a number as
text, a Qt widget's own value. Those are the app's. A number that goes into a table, a file or a figure's data is the library's."""

import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "physicsanalysis_qt")

STATISTICS = {"mean", "nanmean", "std", "nanstd", "median", "nanmedian", "var", "nanvar", "percentile", "nanpercentile", "quantile", "corrcoef", "polyfit",
              "trapz", "trapezoid", "average", "cov"}
PACKAGES = {"scipy", "statsmodels", "sklearn", "statistics"}

# {module: {statistic: why it is drawing, not a result}}
ALLOWED = {
    "figures/draw.py": {"nanpercentile": "the extent of a heatmap's colour scale (the 98th percentile of what is shown), chosen for the picture"},
    "figures/panels.py": {"percentile": "the extent of a heatmap's colour scale (the 98th percentile of what is shown), chosen for the picture"},
}


def uses(tree):
    """[(line, what)] of the statistics packages imported and the statistics called in a module."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, f"import {a.name}") for a in node.names if a.name.split(".")[0] in PACKAGES]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and node.module.split(".")[0] in PACKAGES:
            found.append((node.lineno, f"import {node.module}"))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in STATISTICS:
            found.append((node.lineno, node.func.attr))
    return found


def offenders():
    out = []
    for folder, dirs, files in os.walk(PACKAGE):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "assets")]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            relative = os.path.relpath(path, PACKAGE).replace(os.sep, "/")
            with open(path, encoding="utf-8") as f:
                for line, what in uses(ast.parse(f.read())):
                    if what not in ALLOWED.get(relative, {}):
                        out.append(f"{relative}:{line} {what}")
    return out


class TestNoCalculationInTheApp(unittest.TestCase):
    def test_no_window_or_figure_works_out_a_statistic_of_its_own(self):
        self.assertEqual(offenders(), [], "this is a calculation: make it a function of the analysis library and ask for it through backend.api "
                                          "(backend/ports.py, backend/library.py); a statistic that only sets how a picture is drawn goes in ALLOWED, with why")

    def test_the_allowed_ones_are_still_used(self):
        for relative, statistics in ALLOWED.items():
            with open(os.path.join(PACKAGE, *relative.split("/")), encoding="utf-8") as f:
                seen = {what for _, what in uses(ast.parse(f.read()))}
            for statistic in statistics:
                self.assertIn(statistic, seen, f"{relative} no longer calls {statistic}: take it off ALLOWED")

    def test_the_check_sees_what_it_is_for(self):
        tree = ast.parse("import scipy.stats as st\nimport numpy as np\nx = np.mean(a)\ny = a.std(ddof=1)\nz = np.percentile(a, 5)\nw = np.abs(a).argmin()\n")
        self.assertEqual([what for _, what in uses(tree)], ["import scipy.stats", "mean", "std", "percentile"])


if __name__ == "__main__":
    unittest.main()
