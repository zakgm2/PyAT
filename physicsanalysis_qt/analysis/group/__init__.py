"""
analysis/group
----------------
Group analysis ("Hypothesis Testing"): the same event-locked responses measured in every
recording of a folder and compared across markers with a mixed-effects model. The maths lives
in PhysicsLibrary (analysis/group.py); this package is the app side:

  scan.py          what each recording contains (markers, length), built the way Event PETH builds them
  setup_dialog.py  the step-by-step setup wizard, and launch_group_analysis() which opens it
  output.py        the group's output folder and its saved settings
  recording.py     loads one recording exactly as the app loads it (dF/F, saved splices, saved markers)
  run.py           runs the whole analysis and writes the tables, report and figures
  plots.py         the figures (traces, heatmaps, measures, diagnostics)
  results_dialog.py the results window (report + figures, each with Export Plot)
"""

from .setup_dialog import launch_group_analysis

__all__ = ["launch_group_analysis"]
