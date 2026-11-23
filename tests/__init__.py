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

import faulthandler
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
#
# The same hazard has a second form, on the main thread: a window in a reference cycle (a test's context object holds the toast's event filter, which holds
# the context) is destroyed whenever the collector happens to run, and if that is in the middle of a Qt call that is walking the widgets (QApplication.setStyle,
# which every theme change makes) the process dies, silently, at a point that depends on how many objects Python had allocated by then: so on the CI's Python
# 3.12 and not on the 3.14 it is developed on. So the collector never runs by itself during the tests; what is garbage is collected between tests, here.
gc.disable()
_run_one_test = unittest.TestCase.run


def _keep_the_native_crash_report():
    """A crash in native code (Qt) leaves nothing in a CI log unless faulthandler is on and writes to stderr. The error log's own tests switch it to a file, or
    off, so it is put back after every test: the next crash prints the Python stack of every thread."""
    try:
        if sys.__stderr__ is not None:
            faulthandler.enable(file=sys.__stderr__, all_threads=True)
    except Exception:                                           # noqa: BLE001 - a diagnostic, never a reason for a test to fail
        pass


def _run_then_collect(self, result=None):
    try:
        return _run_one_test(self, result)
    finally:
        if "PyQt6.QtWidgets" in sys.modules:                    # (no windows, no garbage that can hurt)
            gc.collect()
        _keep_the_native_crash_report()


_keep_the_native_crash_report()
unittest.TestCase.run = _run_then_collect
