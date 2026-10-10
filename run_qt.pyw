"""
PyAT (Python Analysis Tool) — windowed entry point
--------------------------------------------------
Double-clicking this file (or the shortcut to it) starts the app without a console window, and it is the script the packaged build is made
from (PhysicsAnalysis.spec). Everything is in run_qt.py, which this runs: it used to be a second copy that had to be kept byte-identical.
"""

from run_qt import main

if __name__ == "__main__":
    main()
