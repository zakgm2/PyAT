"""
physicsanalysis_qt
-------------------
PyQt6 implementation of PyAT (Python Analysis Tool): the windows, the plotting and the
exports. Computation is not here: loading and processing recordings, splicing, event naming
and grouping, every analysis and the whole group-analysis pipeline live in PyATCLI, and
this package calls them — which is why a script using the library gets the numbers the app shows.
The slow ones (opening a recording, a splice's dF/F re-fit, Event PETH, Peak Finder, group analysis,
the text field study) do not even run in this process: they run in the analysis engine, a second
process (`python -m PyATCLI serve`) that the window sends requests to, so the window cannot
freeze while they work and a crash in a library cannot take it down (see backend/). What stays
here is what has to be on screen or in a user's hands. Split by concern:

  context.py          - shared AppState object passed to every function (ctx.engine, ctx.recording_id)
  splash.py           - the loading screen (it reads assets/ beside itself, so it stays here)

  app/                - the application around the windows
      background.py     run_engine: a request to the engine whose answer and progress reach the GUI thread, with a
                        progress toast (Esc cancels it)
      toasts.py         toast / error / success notifications, and the progress toast
      errorlog.py       the rotating session log, the crash dialog and the saved problem report
      options.py        the Options dialog and settings
      update_check.py   the GitHub update check
      citation.py       the status bar's citation button: the app's citation in APA, MLA, Chicago, Harvard, Vancouver, IEEE, BibTeX, RIS
      theme.py          light / dark theme
      window_fit.py     keeps windows/dialogs within the screen on small displays
  backend/            - the way to the engine: engine_client.py (the process, requests, progress, cancel, restart),
                        runner.py (how the library is launched; CliRun for a one-shot command), recordings.py
                        (the recording the engine hands back, its arrays memory-mapped from its files, and how a
                        request names the loaded recording), errors.py; and ports.py / library.py, the boundary with the analysis
                        code: ports.py is what the app asks for, library.py the one module that answers with PyATCLI. A
                        window imports `backend.api`, never the library (tests/test_backend_boundary.py fails if one does); contract.py
                        is what the app needs of the engine, checked against its `ready` message so a mismatched library is refused
  loading/            - the Open dialogs (TDT, Oxysoft, generic tabular, PT2); they ask the engine to open the file
                        (loading/common.py) and keep the result in ctx.cache
  plot/               - the main plot, in either engine
      plotting.py       the matplotlib engine: simple_plot(), attribute re-application
      pg_engine.py      the PyQtGraph engine
      interaction.py, pg_interaction.py   zoom/pan/hover/rect-select per engine
      plot_signal.py    the toolbar's "Plot:" dropdown (which of a recording's signals to draw)
      fonts.py          golden-ratio figure font sizing
  edit/               - changing what is shown, without touching the recording on disk, and keeping the changes
      markers.py        Add/Edit Marker dialogs and placement/lookup
      marker_labels.py  marker names, bound to the app's store renames (rules: PyATCLI markers.py)
      splice.py         Splice (trim / cut out) orchestration; highlight.py the Highlighter; text_annotation.py the Text tool
      attributes.py     Edit Attributes dialog; color_picker.py per-trace line colors
      signal_names.py   renaming a recording's signals (Plot menu, Edit Attributes), kept with the recording
      sidecar.py        Save Changes: asks the engine to write markers, highlights, text annotations, signal names and splices next to a recording
      undo.py           Ctrl+Z for marker, splice, highlight and text-box edits
  analysis/           - the Analysis picker and each tool's window (Z-Score, FFT, AUC, Curve Fit, Event
                        PETH, Peak Finder, Measure Intervals), and analysis/group/ (Group Analysis);
                        windows.py is how the click analyses ask the engine (request_analysis) and read its tables
  export/             - getting figures and files out
      outputs.py        where an export lands: <Output>/<data type>/<recording>/
      export_provenance.py   asks the engine for the .provenance.json beside every export (layout: PyATCLI provenance.py)
      figure_export.py  the Export Figure dialog every figure goes through (format, dpi, editable labels, preview)
      view_figure.py    Export View, the main plot redrawn (what it draws and which lines the plot has: figures/view.py;
                        here: reading the range from the engine on screen, the widget's proportions, the Plot menu's signals)
  figures/            - everything that draws, and writes a drawing to a file: draw.py (the analysis windows' figures), group.py (a group
                        analysis's), panels.py, from_tables.py (the figure for a finished analysis's tables: Open Results), view.py (the main
                        plot's lines and Export View), attributes.py (Edit Graph Attributes' rules), render.py / data.py / labels.py (PNG/TIFF/
                        PDF/SVG with the data CSV and editable words), style.py. They draw from the numbers the library writes
  fieldstudy/         - the text-field study: open_study.py (the Open dialog), results.py and validation.py (the results
                        viewers), config.py (its local settings)
  ui/                 - toolbar + main window assembly

Entry point: run_qt.py (run_qt.pyw, the windowed launcher the packaged app is built from, just runs it), at the repo root.
"""

# Single source of truth for a packaged/frozen build, which has no
# pyproject.toml on disk to read (see app/update_check.py's local_version()).
# Bump this together with pyproject.toml's version field on every release
# — see Deployment Steps.md.
__version__ = "4.1.0"

# The day this version was released; its year is the year in the citation the status bar's citation button copies.
# Bump it with __version__ (tests/test_citation.py checks both against CITATION.cff).
__release_date__ = "2026-11-02"
