"""
physicsanalysis_qt
-------------------
PyQt6 implementation of PyAT (Python Analysis Tool). Split by concern:

  context.py          - shared AppState object passed to every function
  fonts.py             - golden-ratio figure font sizing
  toasts.py            - toast/error/success notifications
  window_fit.py        - keeps windows/dialogs within the screen on small displays
  sidecar.py           - marker .json save/load
  markers.py           - Add/Edit Marker dialog + placement/lookup
  plotting.py          - simple_plot(), attribute re-application, view export
  interaction.py       - zoom/pan/hover/rect-select/resize
  attributes.py        - Edit Attributes dialog
  color_picker.py      - hue/saturation + darkness color picker (per-trace line colors)
  loaders/             - TDT, Oxysoft, generic tabular, PT2 file loading
  analysis/            - Analysis picker, Curve Fit, PETH, FFT, AUC windows + click dispatch
  ui/                  - toolbar + main window assembly

Entry point: run_qt.py / run_qt.pyw at the repo root (kept byte-identical
to each other — see either file's own docstring for why there are two).
"""

# Single source of truth for a packaged/frozen build, which has no
# pyproject.toml on disk to read (see update_check.py's local_version()).
# Bump this together with pyproject.toml's version field on every release
# — see Deployment Steps.md.
__version__ = "3.2.0"
