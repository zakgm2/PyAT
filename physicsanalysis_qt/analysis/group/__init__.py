"""
analysis/group
----------------
Group analysis ("Hypothesis Testing"): the same event-locked responses measured in every
recording of a folder and compared across markers with a mixed-effects model. The maths and the
headless pipeline live in PyATCLI (analysis/group*.py: scan_recordings, load_group_recording,
run_group_analysis, write/read_group_settings — all callable from a script); this package is the app side:

  setup_dialog.py  the step-by-step setup wizard, and launch_group_analysis() which opens it
  output.py        where the group's output folder goes (asking for one if none is set)
  run.py           runs the library's analysis on a worker thread, opens the results and saves the figures beside the tables
  (figures)        traces, heatmaps, measures and diagnostics are figures/group.py — the code Open Results draws a group analysis
                   with again from its folder, so what is opened is what was shown (the engine and the command line draw nothing)
  results_dialog.py the results window (report + figures, each with Export Plot)
"""

from .setup_dialog import launch_group_analysis

__all__ = ["launch_group_analysis"]
