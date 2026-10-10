"""The app does not import the analysis library: it asks `backend.api` (backend/ports.py says what it may ask), and backend/library.py is the one place
that knows the library's names. This test keeps it that way, and keeps the migration honest.

STILL_DIRECT is the modules that import the library anyway, each with why: it is empty, and it should stay that way. A module that imports the
library and is not listed fails (route it through backend.api — ports.py and library.py), and a listed module that no longer imports it fails too
(take it off the list). backend/ itself is the boundary (library.py, and the engine's own pipes and arrays) and is not scanned."""

import ast
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "physicsanalysis_qt")
LIBRARY = "PyATCLI"

STILL_DIRECT = {}          # (nothing: every window asks backend.api. A module that has to import the library for now goes here, with the reason.)


def imports_library(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and node.module.split(".")[0] == LIBRARY:
            return True
        if isinstance(node, ast.Import) and any(a.name.split(".")[0] == LIBRARY for a in node.names):
            return True
    return False


def modules_importing_the_library():
    found = set()
    for folder, dirs, files in os.walk(PACKAGE):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "backend", "assets")]       # backend/ is where the boundary is
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8") as f:
                    if imports_library(ast.parse(f.read())):
                        found.add(os.path.relpath(path, PACKAGE).replace(os.sep, "/"))
    return found


class TestTheBoundary(unittest.TestCase):
    def test_only_the_listed_modules_import_the_library_and_the_list_only_gets_shorter(self):
        found = modules_importing_the_library()
        new = sorted(found - set(STILL_DIRECT))
        self.assertEqual(new, [], "these import the analysis library directly; ask it through backend.api instead (add to backend/ports.py "
                                  "and backend/library.py what they need)")
        stale = sorted(set(STILL_DIRECT) - found)
        self.assertEqual(stale, [], "these no longer import the library: take them off STILL_DIRECT in tests/test_backend_boundary.py")

    def test_the_ports_import_no_library(self):
        with open(os.path.join(PACKAGE, "backend", "ports.py"), encoding="utf-8") as f:
            self.assertFalse(imports_library(ast.parse(f.read())), "ports.py is what the app asks for, written from the app's side: it must not import the library")


if __name__ == "__main__":
    unittest.main()
