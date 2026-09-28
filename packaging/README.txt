PyAT (Python Analysis Tool)
===========================

A general-purpose desktop app for loading, plotting, and analyzing
physics/neuroscience lab data - with a current focus on fiber photometry.

WHAT IT OPENS
-------------
  - TDT (Tucker-Davis Technologies) fiber photometry recordings
  - Oxysoft / Artinis NIRS exports
  - Generic tabular data (Excel, CSV, TSV, plain text)
  - Terranova Prospa EFNMR/MRI .pt2 images
  - Grouped text-field studies (one JSON file per subject)

GETTING STARTED
----------------
Open menu (top left) -> pick the format you're loading -> select a file
or folder. The main plot appears once it's loaded; the toolbar and the
icon sidebar on the left cover most of what you'll want to do from
there (adding/editing markers, splicing out an artifact, rescaling the
view, exporting the current view as an image).

KEY FEATURES
------------
  - Three interchangeable plot engines (Options -> Plot Engine):
    matplotlib (CPU), PyQtGraph (fast, handles large recordings well),
    and VisPy (GPU/OpenGL-native, still experimental).
  - Event markers: auto-detected from TDT epoc stores, or add your own
    manually. Splice Recording lets you non-destructively trim or cut
    out a time range (e.g. a motion artifact) without touching the
    original file.
  - Analysis tools: Curve Fit, FFT, Z-Score PETH, Event PETH
    (GuPPy-style stacked heatmap across every occurrence of an event),
    Find Significant Peaks, and Measure Intervals.
  - Text field study analysis: compare free-text survey responses
    across subjects using sentence embeddings, with a permutation-test
    significance check. (Requires the optional sentence-transformers
    Python package, which isn't bundled with this build - install it
    yourself with `pip install sentence-transformers` if you want this
    one feature; everything else works without it.)
  - Progress toasts: anything slow (loading a recording, splicing out
    an artifact, the analysis runs) shows a live percentage in the
    bottom-right corner while it works.
  - Dark mode, an Options dialog (default folder, render decimation,
    background loading, plot engine), and settings that persist
    between launches.

UPDATES
-------
The app checks GitHub on launch for a newer version and will tell you
if one's available, with a link to download it - it won't install
anything automatically, just let you know.

LICENSE
-------
PyAT is free software, released under the GNU Affero General Public
License v3.0 (AGPL-3.0). The full license text is in LICENSE.txt, next
to this file; the complete source code is in the repository below.

Full changelog and source: https://github.com/zakgm2/PyAT
