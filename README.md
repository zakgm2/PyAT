# PyAT — Python Analysis Tool

A general-purpose PyQt6 desktop application for loading, plotting, and analysing time-series and tabular lab data — CSV/Excel, curve fitting, FFT, peri-event analysis — with a current focus on fibre photometry.

Supports TDT fibre photometry recordings, Oxysoft / Artinis NIRS exports, generic tabular data (Excel, CSV, TSV, plain text), Terranova Prospa EFNMR/MRI `.pt2` images, and grouped-text-field studies (one JSON file per subject, e.g. a survey with several free-text responses).

Built on [PyATCLI](https://github.com/zakgm2/PyATCLI) (`pip install PyATCLI`; called PhysicsLibrary before PyAT 4.0.0) — the analysis library, engine and command line, which computes and writes the numbers. This repo is the window layer: it asks the engine for them and draws everything.

The main plot can render with **matplotlib** (CPU) or **PyQtGraph** (fast CPU-side decimation, handles large recordings much better) — switch anytime in **Options**. FFT/PETH/Curve Fit/PT2 windows always use matplotlib regardless of the main-plot engine.

> A tkinter version of this GUI existed prior to v2.2.0 and has been removed — the PyQt6 version now has full feature parity plus the GPU engine, Options dialog, and background loading. Its history remains in `git log -- PhysicsAnalysisGUI.py` if ever needed.

---

## Features

- **Multi-format loading** — TDT tank folders, Oxysoft `.txt` exports, any Excel/CSV/TSV file, Terranova `.pt2` EFNMR/MRI images, and text field study folders, via a unified open menu
- **Sub-table detection** — automatically finds multiple side-by-side tables in a single Excel sheet
- **Interactive plot** — scroll to zoom, right-click drag to pan, rectangle select to zoom into a region, resize-safe
- **Hover snap** — tracker dots snap to the nearest plotted line and display exact values
- **Curve fitting** — click two points to fit a model (linear, exponential, Gaussian, sinusoidal, …) to that segment; copy or export parameters as CSV
- **FFT viewer** — frequency analysis window with automatic peak annotation
- **PETH / Z-score** — peri-event time histogram for TDT data, plus a GuPPy-style Event PETH (stacked heatmap + trial-averaged trace) with a per-trial include/exclude checklist for dropping an obviously contaminated trial without changing the event or window
- **Plot signal selector** — for TDT recordings, a toolbar "Plot:" dropdown (Normalized (dF/F), Isosbestic, Main Driver — built from whatever the recording actually has, no Isosbestic entry if there's no 415 reference stream) picks what the main plot shows; tick more than one in the dropdown to overlay them, the button's own label summarizes the current pick(s). Analysis tools (AUC, FFT, Curve Fit, Z-Score PETH) still work on a single signal — whichever was ticked most recently — regardless of how many are shown on the plot
- **PT2 image viewer** — colormap selector, live title editing, PNG/PDF/SVG export
- **Markers** — a fresh load starts with no markers on screen; use **Add Marker** to bulk-add auto-detected event markers by store (multi-select, add/remove in one action, High/Low phase checkboxes), or configure a custom name/colour/font size once and stamp repeated markers Snipping-Tool style (click, click, click, then stop) — the name can be left blank for a plain, unlabeled tick; a separate multi-select **Remove Markers** list handles batch cleanup; right-click a marker to rename/delete it (or delete every marker sharing that name) individually, or right-click and hold its label to drag it up/down to a different height; markers auto-save as a `.markers.json` sidecar
- **Group Analysis** (Hypothesis Testing) — open a folder with two or more TDT recordings and a wizard picks the recordings, markers, window and measures (AUC, peak, mean, latency, decay); a mixed-effects model per measure with Holm-corrected comparisons; the results open in a Report + Figures window and are saved beside the tables (PNG and PDF, each with the data behind it), and **Open Results…** reopens them later
- **Undo** — **Ctrl+Z** takes back the last marker, splice, highlight or text-box edit, including a dragged text box or marker label
- **Highlighter** — pick one of 5 standard colors, then click two points on the plot to shade the range between (non-destructive, stacks); right-click a highlight to delete it; saved as `highlights.json`
- **Text tool** — click the plot to drop a free text box (content and font size asked fresh each time); right-click and hold to drag one, a plain right-click deletes it; saved as `text_annotations.json`
- **High/low phase** — auto-detected markers show both onset (high, superscript ¹) and offset (low, superscript ⁰) by default High-only; useful for anything where on-duration matters (a pump, a light), not just the press
- **Rename stores** — right-click a marker → Rename → "Rename all" applies to every marker from that store at once (or just the one instance); the Add Marker dialog's store list supports the same inline (right-click a store, type, Enter); **Reset Name** reverts back to the raw store id
- **Measure Intervals** — a table of every marker currently on the plot, sorted by time, with time-since-previous-in-store (on-duration for high/low pairs) and time-since-previous-any-marker columns; exportable as CSV
- **Analysis window** — a single **Window** button opens a dialog for the pre/post seconds around an FFT/PETH/Curve Fit click: symmetric (one total size, split evenly) or asymmetric (independent before/after, e.g. 10s before, 20s after)
- **Rename on the plot** — double-click the graph title or an axis label to retype it, on either plot engine
- **Edit Attributes** — customise plot title, axis labels, font sizes, legend entries, and each trace's line color (pick from a hue/saturation field with a darkness slider); changes persist across zoom/pan/hover
- **Open Results…** (Open menu) — look at a finished analysis again from the files it left: pick a group analysis's `analysis_settings.json`, an analysis' `.provenance.json` record or an exported `.csv`; the analysis engine reads the numbers back and the window draws them (a group analysis in its Report + Figures window), with nothing recomputed and no recording needed.
- **Export Figure** — every figure's export (an analysis window's **Export Plot**, the main plot's **Export View**, the Group Analysis figures, the PT2 image) opens one dialog: PNG or TIFF at a resolution you pick (300 dpi default, up to 1200), or PDF/SVG as vector files whose text stays editable text (Illustrator, Inkscape); a transparent background if you want one; a live preview with the real pixel size; the titles, axis labels, colour-bar labels and legend entries as editable fields (the export changes, the figure on screen doesn't); and a CSV of the data behind each plot saved beside the figure. Export View redraws the plot as a white-background figure whichever plot engine is showing it — the visible range, markers, highlights, text, your edited title/labels/legend — with a CSV of every sample in view
- **Rename signals** — **Plot ▾ → Rename signals…** (or rename the legend entry in Edit Attributes) replaces names like "Main Driver (x465A)" everywhere that signal appears: legend, Plot menu, analysis windows, the Channel column of exports. Saved with **Save Changes** (`signal_labels.json`) and restored on the next load
- **Provenance records** — every export gets `<name>.provenance.json` beside it: the software versions, a fingerprint of the recording's files, its splices and signal names, the pipeline's own settings (filter, smoothing, z-score baseline), the analysis parameters and the files written. It never holds recording data. Turn it off in **Options → Reproducibility**; see *Reproducing a result* below
- **Error log** — each session writes a rotating log (`~/.physicsanalysis/logs/pyat.log`) that starts with the app, library, Python, OS and dependency versions and records actions, parameters and stack traces — never recording contents; file paths are replaced by tokens unless you turn them on in **Options → Error log**. A crash shows a short message with **Save report**, and the status-bar bug button's menu offers **Save problem report…** and **Open error log folder** — send that file when something goes wrong
- **Golden-ratio font scaling** — all figure text scales proportionally to figure/widget size and stays live during window resize, on both plot engines
- **Grid toggle** — show/hide background grid from the toolbar
- **TSI Fit Factor** — extracted automatically from Oxysoft files and shown in the legend
- **Options dialog** — default folder for Open dialogs, main-plot render decimation, whether the window stays responsive while the analysis engine works, and matplotlib/PyQtGraph plot engine selection
- **A separate analysis engine** — loading a recording, a splice's dF/F re-fit, the Z-Score / AUC / FFT / Curve Fit windows, Event PETH, Peak Finder, group analysis, the text field study, Save Changes and the provenance records run in a second process (`python -m PyATCLI serve`; in the packaged app, `PyAT.exe --engine serve`), so the window never freezes and a crash in a library cannot take it down. **Esc** cancels what it is doing. The packaged program also holds the library's command line for scripts: `PyAT.exe --engine run ... --json > result.json` is `python -m PyATCLI run ... --json` (a windowed program writes to a file or a pipe, not to the terminal it was started from)
- **Progress toasts** — anything slow (loading a recording or file, a Splice ΔF/F recompute, Event PETH and Peak Finder runs, the text-study pipelines) shows a toast in the bottom-right corner with a live percentage, what it is doing right now and a thin bar; quick actions never flash one
- **Text field study analysis** (**Text Field Study ▾** menu) — pick a folder of one-JSON-file-per-subject data (any schema), then pick pairs of fields to compare directly from the actual field names found in that folder — no fixed format, no grouping concept. Computes per-field word counts and low-word-count quality flags, embeds each compared field with a sentence-transformers model, an optional delta-vector magnitude between two fields, and a paired-similarity metric per pair with a permutation test (p-value, effect size) against a shuffled-pairing null plus a word-count confound check; results in a table with full-DataFrame CSV export. Field configuration is saved locally outside the repo, not in source.
- **Statistical validation** (for text field studies) — permutation-test p-value with Benjamini-Hochberg FDR correction across pairs, Cohen's d effect size, a word-count-controlled OLS regression per field, a bootstrap 95% confidence interval on the mean similarity, and leave-one-out sensitivity flags; one row per pair, CSV export

---

## Requirements

- Python 3.10+
- Dependencies listed in `requirements.txt` / `pyproject.toml`

---

## Installation

```bash
git clone https://github.com/zakgm2/PyAT.git
cd PyAT
pip install -r requirements.txt
```

That installs the analysis library from PyPI too (`PyATCLI`, 2026.10.10 or newer). To work on both repositories side by side, clone [PyATCLI](https://github.com/zakgm2/PyATCLI) next to this one and run `pip install -e ../PyATCLI`.

**Prebuilt executables** (no Python install needed) are attached to each
[GitHub Release](https://github.com/zakgm2/PyAT/releases) for
Windows and macOS. **macOS**: the app isn't signed with a paid Apple
Developer certificate, so the first launch needs one extra step — see
[MACOS_INSTALL.md](MACOS_INSTALL.md).

---

## Running

```bash
python run_qt.py
```

> **Spyder users:** do not run `run_qt.py` via Spyder's Run button or console — Spyder's own UI is built on PyQt5, and loading PyQt6 in the same process causes a `DLL load failed while importing QtWidgets` crash. Edit the file in Spyder normally, but launch it from a plain terminal.

---

## Loading Data

| Menu item | What it opens |
|-----------|----------------|
| **Open TDT Folder** | A TDT tank directory (`.Tbk`, `.tev`, … files) |
| **Open TXT (Oxysoft)** | A single Oxysoft / Artinis `.txt` export |
| **Open Excel/CSV/TSV** | Any tabular file — a dialog lets you pick X and Y columns |
| **Open PT2 (EFNMR)** | A Terranova Prospa `.pt2` 2D image file |

Text field studies live in their own **Text Field Study ▾** menu instead (not the Open menu above): **Open Study Folder** (pick a folder, then pick pairs of fields to compare right from that folder's own field names), **View Results**, **Statistical Validation**.

---

## Keyboard & Mouse

| Action | How |
|--------|-----|
| Zoom in / out | Scroll wheel |
| Pan | Right-click drag |
| Zoom to region | Left-click drag (rectangle select) |
| Reset zoom | **Rescale** button (left icon sidebar) |
| Place markers | **Add Marker** → *Place Custom Markers* → Start Placing, then left-click the plot repeatedly; click **Add Marker** again to stop |
| Add auto-detected markers | **Add Marker** → *Add / Remove Auto-Detected Markers* → select store(s) → Add Selected |
| Remove markers | **Add Marker** → *Remove Markers* → select marker(s) → Remove Selected |
| Edit / delete a single marker | Right-click near it |
| Rename / reset / delete all of one name | Right-click near it → Rename (with "all" toggle) / Reset Name / Delete all |
| Rename a store inline | Add Marker → right-click a store in the list → type → Enter |
| Measure time between events | **Measure Intervals** button |
| Set analysis window | **Analysis** button → Window row → symmetric size or independent before/after |
| Fit curve | **Analysis** button → **Curve Fit**, then click two points |
| Run FFT / Z-Score / AUC | **Analysis** button → pick one, then double-click the plot (one run per pick — tick **Persist through trials** to stay armed across trials). Going back to the **Analysis** menu cancels the current tool, so closing it with the X returns you to the plain plot. With **Persist through trials** ticked a **Done** panel appears bottom-left — press it (or **Done** on a graph window) to stop) |
| Text field study (open/view/validate) | **Text Field Study ▾** menu |

---

## Reproducing a result

Every export carries a provenance record, and PyATCLI can run the analysis again from it without the app and check the numbers against the export:

```bash
python -m PyATCLI reproduce "Event PETH_L1P_103522.provenance.json" --compare "Event PETH_L1P_103522.csv"
```

The command line (`python -m PyATCLI`) computes and writes files and never draws or opens a window: the CSVs and records it writes have the columns of the ones the analysis windows export, and the figures are the app's (**Export Figure** writes them: png, tif, pdf, svg, with the data CSV beside each).

What Save Changes saves (markers, splices, signal names, highlights, text) a script can save too, as the same files: `python -m PyATCLI saved marker "D:/rats/Rat7" --time 312.5 --label Lever`, or `pl.saved_state.add_splice(...)`; `--output-folder` on `run`/`batch`/`group` puts results under your Output folder in the layout the app uses; `group-setup` is the Hypothesis Testing wizard from the command line.

PyAT writes its CSVs with a fixed number of decimals, so for its records `reproduce` accepts the digits an export shows (`--exact` compares to the tolerance only). The same analyses can be run on any recording from Python (`pl.run_analysis("event_peth", cache, {...})`) or a shell (`python -m PyATCLI run`, `batch`, `group`); the tables have the columns of the CSVs PyAT exports. See PyATCLI's [API reference](https://github.com/zakgm2/PyATCLI/blob/main/API_REFERENCE.md#running-analyses-by-name).

---

## Version History

See [CHANGELOG.md](CHANGELOG.md) for the full changelog.

| Version | Summary |
|---------|---------|
| 4.0.0 | Major release. The slow work — loading a recording, splicing, every analysis, group analysis, Save Changes — runs in a second process, the **analysis engine**, so the window never freezes, **Esc** cancels and a crash in a library cannot take the app down (`PyAT.exe` starts itself as the engine; two `PyAT.exe` in Task Manager is normal). The analysis library is now **PyATCLI** (`pip install PyATCLI`; PhysicsLibrary / `ZaksPhysicsLibrary` before) and requires `PyATCLI>=2026.10.10`; it draws nothing, the app draws everything. New: **Open Results…** (reopen a group analysis, a record or an exported CSV from its files), a **provenance record** beside every export that `python -m PyATCLI reproduce` replays, an **Export Figure** dialog (PNG/TIFF/PDF/SVG up to 1200 dpi, editable text, the data CSV beside each figure) and a white-page **Export View**, **Rename signals**, rename the title/labels by double-click on both engines and a **legend entry** on PyQtGraph, a rotating **crash and error log** with Save report, the folders reorganised. Fixed: Ctrl+Z on text boxes and highlights, the Z-Score window cutting off its peak, Event PETH's trial axis. Removed: the VisPy plot engine. Settings and saved files are read as before |
| 3.2.0 | New **Highlighter** (5 standard colors, click-click to shade a range) and **Text** tools (click to drop a free text box, right-click-hold to drag, plain right-click to delete) on the left sidebar, both saved as sidecars like markers; markers can be placed with no name, and a marker's label can be dragged to a different height; **Ctrl+Z** undoes the last marker/splice edit; Event PETH and every Group Analysis figure now have an editable Title field; the Group Analysis measures figure can show a single measure full-size, fixed its title overlapping at small sizes, and its heatmap color scale is now symmetric around the data's own peak; the "Plot:" signal picker is now a checkable dropdown instead of a row that didn't scale to a narrow window; the Tools sidebar's collapse arrow lines up with its other icons and drops the redundant "Tools" title while expanded |
| 3.1.0 | New **Group Analysis** ("Hypothesis Testing" on a folder with 2+ TDT recordings): a wizard picks recordings/markers/window/measures (AUC, Peak Amplitude, Mean Amplitude, Latency to Peak, Decay Time), fits a linear mixed-effects model per measure with Holm-corrected post hoc comparisons, and shows a tabbed Report + Figures results dialog (trace/heatmap/measures/diagnostics figures, auto-saved as PNG+PDF in a colorblind-safe palette); requires `ZaksPhysicsLibrary>=2026.9.28`. Exports now nest as `<Output>/<type>/<recording name> (Analysis)/`, auto-disambiguated between same-named recordings, with repeat exports numbered instead of overwritten (Group Analysis reruns get a freshly numbered folder instead of a replace prompt). More background work now shows progress toasts (recording loads including generic tabular, Splice, Event PETH, Peak Finder, text-field study); fixed a freeze that could follow a background load finishing |
| 3.0.1 | Requires PhysicsLibrary 2026.9.24, which fixes the motion-correction fit on long recordings (the default OLS was wrong past ~3 minutes: float32 precision), makes dF/F a real ΔF/F and stops clipping z-scores in raw units — dF/F values and default-OLS PETH z-scores change; Peak Finder's default Z-score threshold is now 5 (was 2.5); AGPL-3.0 stated everywhere (README, package metadata, `CITATION.cff`, `LICENSE.txt` in the release zips); repo-name cleanup to `zakgm2/PyAT` |
| 3.0.0 | App renamed **PyAT (Python Analysis Tool)** (major version for the rename) with a new loading-screen logo; the Analysis dropdown is now an **Analysis** button/menu (one run per pick, "Persist through trials" + a Done panel/buttons, analysis window moved inside it); per-trace line colors in Edit Attributes via a new hue/saturation + darkness color picker; "Tools" title on the left sidebar with a sideways collapsed tab; Options and the other resizable windows now fit small screens; one notification toast at a time; fixed PyQtGraph lines/legend piling up after Overlay All and VisPy's legend collapsing / invisible in dark mode |
| 2.13.0 | Splice's Cut Out now recomputes dF/F (motion + bleaching correction) on the stitched TDT signal instead of just cutting the old trace; Open Data Folder detects multiple TDT recordings in one directory (Single Experiment Analysis vs Hypothesis Testing placeholder); fixed saved markers/splices being silently lost or corrupted on reload (TDT/Oxysoft/Generic) and Splice failing at recording borders; default motion-correction regression changed from RANSAC to OLS; Splice's mode picker now defaults to Cut Out |
| 2.12.1 | Loading screen redesign (just the logo, no card), update-available prompt now lives on the splash itself instead of a separate popup, fixed a real bug where that popup could open behind the always-on-top splash and get stuck |
| 2.12.0 | AUC analysis, Custom Statistics picker, Event PETH "Trials" overlay view, Splice now works on Oxysoft/Generic, RANSAC/Huber/OLS motion-correction choice, Output Folder option, shared export buttons everywhere, marker hit-testing scales with zoom |
| 2.11.3 | Update check no longer forces a wall — "Continue Anyway" launches the current version, "Download Update" opens the release page and exits |
| 2.11.2 | Fixed `__version__` not being bumped alongside `pyproject.toml` (caused every fresh install to still think it was out of date); fixed a `packaging/` folder name collision breaking CI's `pip install .` |
| 2.11.1 | CI-built Windows/macOS executables (GitHub Actions, PyInstaller onefile), attached automatically to a GitHub Release on every version tag push |
| 2.11.0 | VisPy (OpenGL/GPU-native) added as a third plot engine alongside matplotlib and PyQtGraph, with full interaction parity (rectangle-zoom/pan, markers, legend, hover, decimation, export) |
| 2.10.0 | Update check now blocks launch entirely for a stale PhysicsAnalysis version (download-link dialog instead of a soft notice); now also checks PhysicsLibrary |
| 2.9.0 | Loading screen with a GitHub update check, `Launch PhysicsAnalysis.lnk` desktop launcher, splice stacking with a manager dialog, per-note Add Marker grouping, RANSAC inlier-fraction toast, Tick epoc excluded from markers/analysis |
| 2.8.0 | Plot signal selector for TDT (Normalized/Isosbestic/Main Driver), Event PETH per-trial include/exclude, Rescale moved to icon sidebar, RANSAC-robust motion correction, zoom-state and PyQtGraph flicker fixes |
| 2.7.0 | Debounce presses in Add Marker (switch-bounce/double-tap duplicate press filtering) |
| 2.6.0 | Splice Recording, left icon sidebar, PETH/Peak Finder improvements |
| 2.5.0 | Event PETH (GuPPy-style stacked heatmap + trial average), Find Significant Peaks, dark mode, settings persistence |
| 2.4.0 | Text field study analysis + statistical validation (permutation test, FDR correction, Cohen's d, regression, bootstrap CI, leave-one-out) |
| 2.3.0 | High/low phase markers, store renaming, Measure Intervals, working Reload, inline-rename Qt bug fixes |
| 2.2.0 | Redesigned opt-in marker workflow, asymmetric analysis window, live-resize fonts/margins, tkinter version removed |
| 2.1.0 | PyQtGraph (GPU) plot engine option, Options dialog, background loading |
| 2.0.0 | PyQt6 GUI port added alongside the tkinter version |
| 1.3.0 | Golden-ratio proportional font sizing, resize-safe zoom |
| 1.2.0 | PT2 EFNMR image viewer, scroll/double-click zoom fixes |
| 1.1.0 | Generic file parser, Excel support, blit hover, curve fit export, marker editing |
| 1.0.0 | Full GUI with TDT and Oxysoft support |
| 0.1.0 | Initial file parser and plotting prototype |

## License

AGPL-3.0 — see [LICENSE](LICENSE) for details.
