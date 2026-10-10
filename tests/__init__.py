"""
Automated tests for the PyAT app layer (physicsanalysis_qt). The computation behind it is PyATCLI's and is
tested there; these cover what is left in the app: that its adapters hand the library the right things and
get its answers back unchanged, that what the app saves is what the library reads, and that nothing is
imported from a place it no longer lives.

Run from the repository root (PyATCLI installed, editable or not):

    python -m unittest discover -s tests -v

Nothing here opens a window: no QApplication is created, and nothing writes the real
~/.physicsanalysis/settings.json (a test that touches Options must patch save_settings).
"""

import gc
import os
import sys
import unittest

# The app reads and analyses through the analysis engine, a second process (backend/). The tests run it on a thread of the test process
# instead, over the same pipes and the same JSON: fast, and a patched tank reader or loader reaches it. The few tests of the process itself
# (test_backend.py) build their own client.
os.environ.setdefault("PYAT_ENGINE", "inprocess")

# Every operation says which keys of its answer are always there (PyATCLI's ENGINE_CONTRACT.json). With this on, the engine fails loudly when one
# is missing, so a library that stops promising what the app reads fails the test that asked, not a window later.
os.environ.setdefault("PYATCLI_CHECK_RESULTS", "1")

# ...which has one consequence. The engine thread allocates like any other, so Python's cyclic garbage collector can run ON it, and it frees
# whatever is garbage by then: the windows and dialogs of tests that have finished (a Qt object in a reference cycle is only ever freed by
# the collector). Qt objects must be destroyed on the thread that owns them, and one freed from the engine thread crashes the process with
# an access violation, at a moment that depends on how much has been allocated since (so a change that only adds work to the engine can
# bring it on). In the app the engine is a process and none of this can happen. So every test ends with a collection on the main thread,
# when its windows have been closed: nothing is left for the engine thread to free.
_run_one_test = unittest.TestCase.run


def _run_then_collect(self, result=None):
    try:
        return _run_one_test(self, result)
    finally:
        if "PyQt6.QtWidgets" in sys.modules:                    # (no windows, no garbage that can hurt)
            gc.collect()


unittest.TestCase.run = _run_then_collect
