# Changelog — PyAT (Python Analysis Tool)

---

## v3.2.0
**New: Group Analysis measures figure — single-measure view, editable titles, auto-scaled heatmap**
- The measures figure's Customize panel can now show a single measure full-size instead of always the whole grid (handiest for box-and-whisker, which was cramped in a small grid cell).
- Fixed the measures figure's title overlapping the panel titles below it whenever its window/canvas was smaller than whatever size happened to be current when the figure was built — it used a one-shot layout pass that never revisited the title's spacing afterward. It now uses matplotlib's `constrained` layout, which keeps re-solving as the figure resizes, and the canvas's minimum size is sized off the figure's own dimensions so the window can be shrunk freely without ever reaching a size small enough to break it.
- Fixed the results dialog sometimes needing to be far taller than the screen to open at all. A `QStackedWidget`'s minimum size is the largest across every figure it holds, shown or not (Qt's own documented behavior) — the tall model-diagnostics grid was forcing that much room to be reserved even while a small trace or single-measure view was what was actually on screen. The minimum now tracks only the currently displayed figure and updates on every switch.
- Every figure (traces, each heatmap, measures, diagnostics) now has its own editable **Title** field next to the Figure picker, same "typed text wins" convention as Event PETH's — untouched titles keep tracking their auto-generated text, and a customized one survives switching figures, Customize panel changes, and Export Plot.
- The per-marker heatmap's color scale is now symmetric around zero, sized off that heatmap's own peak amplitude plus 2 units of headroom (e.g. a 2.5 peak scales to -4..4, a 7 peak to -9..9) instead of a 98th-percentile heuristic, so the true peak is always visible without sitting right at the colorbar's edge.

**New: Ctrl+Z undoes the last marker or splice edit**
- One step at a time: placing/renaming/deleting a marker (or a bulk add/remove), renaming/resetting a store name, and applying/removing a splice (or Restore Full Recording) each push one undo step, restored wholesale on Ctrl+Z — not a general app-wide undo (Edit Attributes, Options, the plot engine, etc. are unaffected). Works the same across all three plot engines. A toast says what was undone; "Nothing to undo" once the stack is empty.

**New: Event PETH's figure title is editable**
- A **Title** field defaults to "Event PETH — {event}" and tracks the event picker until you type your own; from then on your text is left alone, even across switching events or Recalculate, the same "typed text wins" convention Edit Attributes already uses for the main plot's title.

**New: Highlighter tool**
- A new icon in the left sidebar: pick one of 5 standard highlighter colors (Yellow, Green, Pink, Orange, Blue), then click two points on the plot to shade the range between — non-destructive, stacks (several can overlap), works on both the matplotlib and PyQtGraph engines. Right-click a highlight to delete it. Saved/restored like markers and splices (a `highlights.json` sidecar), and covered by Save Changes, Undo All Changes, and Ctrl+Z.

**New: Text tool**
- Another new icon: click the plot to drop a free text box there — content and font size are asked fresh each time, since two boxes usually say different things. One-shot, not a stays-on toggle: one click of the icon places one box, then it disarms itself (matches Splice/Highlighter rather than Add Marker's repeat-placement style). No background box around the text. Right-click and hold on one to drag it anywhere; a plain right-click (no hold) deletes it instead. Works on both plot engines, saved/restored the same way as highlights (`text_annotations.json`).
- Fixed a dragged text box (or marker label) snapping back to its old position the moment the mouse moved again after the drag, only "teleporting" to where it was actually dropped on some later, unrelated redraw. The hover tracker keeps its own cached snapshot of the canvas to restore between frames (see `_refresh_hover_bg`); finishing a drag drew the new position once, but left that cache holding the old one, so the very next mouse-move pasted the stale image straight back over it. Panning already avoids this by recapturing the cache after its own drag — the text/label drag now does the same.
- Fixed placing a text box corrupting the rectangle-zoom-select tool afterward (click-drag-to-zoom would behave erratically). The text dialog blocks while still inside the same mouse-press handler RectangleSelector is also listening to, which desyncs its internal drag state — the same already-known issue window-settings dialogs have, fixed the same already-established way (deactivate it before the dialog opens, reactivate on the next Qt tick rather than immediately).

**New: markers can be placed with no name**
- The marker name field in Add Marker (and the right-click Rename dialog) no longer silently falls back to the word "Marker" when left blank — leaving it empty now places a genuinely unnamed marker: just the dashed tick, no label to draw, position, or drag.

**New: a marker's label can be dragged to a different height**
- Right-click and hold on a marker's label text (not the line itself) to slide it up or down along the marker, on both plot engines — handy for separating overlapping labels on markers that are close together in time. Persisted with the marker, undoable with Ctrl+Z.

**Changed: the "Plot:" dropdown is now checkboxes**
- Pick any combination of the signals a TDT recording offers (Normalized, Isosbestic, Main Driver) to overlay on the main plot, instead of one at a time plus a separate "Overlay All" entry — ticking every box is now just what that used to be. Works the same on both the matplotlib and PyQtGraph engines; PyQtGraph's fast in-place line swap still applies whenever exactly one box ends up checked. AUC, FFT, Curve Fit, and Z-Score PETH keep working on a single signal — whichever box was checked most recently — unaffected by how many are shown on the plot.
- The checkboxes themselves moved into a dropdown (one fixed-width button, its label summarizing what's picked) instead of a row inline in the toolbar — a row grows with however many signals a recording has and doesn't scale down to a narrow window; a dropdown stays the same size regardless. The dropdown stays open across ticking several boxes in a row, rather than closing after each one.

**Changed: the Tools sidebar's collapse arrow and title**
- The "Tools" title next to the collapse arrow is gone while the sidebar is expanded — the column of icons doesn't need it. The arrow itself is now the first icon in that same column (same size, same alignment as Rescale/Add Marker/etc. below it) instead of sitting in its own separate header row. Collapsed, it still shrinks to the slim tab with "Tools" written sideways, click it to expand.

---

## v3.1.0
**New: Group Analysis ("Hypothesis Testing") — compare markers across recordings**
- Opening a folder that contains two or more TDT recordings now offers **Hypothesis Testing** alongside Single Experiment Analysis. A five-page wizard picks recordings, markers (each ticked marker is a level of one factor), the analysis window, and the measures to compute (AUC, Peak Amplitude, Mean Amplitude, Latency to Peak, Decay Time), then names the group and runs.
- Each recording is a subject (named after its own folder), loaded and processed one at a time to bound memory; trials are every occurrence of a marker, taken the same way the single-recording Event PETH takes them. Two or more markers fit a linear mixed-effects model per measure (subject + subject×marker random intercepts) with Holm-corrected post hoc pairwise comparisons; one marker tests AUC/Mean Amplitude against zero (Peak/Latency/Decay are reported as estimates with 95% CIs, since they have no null value). Requires the new `ZaksPhysicsLibrary>=2026.9.28` (not `2026.9.27`, which crashed on two-or-more-marker analyses under `statsmodels>=0.15`).
- Results open in a tabbed dialog: a **Report** tab (plain-text summary, Copy button) and a **Figures** tab — trial-averaged traces, a per-marker heatmap of every trial, a measures-comparison plot with significance brackets, and a model-diagnostics figure, switchable from a dropdown. Every figure is saved automatically as both PNG (300 DPI) and PDF (vector), using the Okabe-Ito colorblind-safe palette for markers and a diverging colormap for heatmaps, matching common journal figure guidelines; the Figures tab's own **Export Plot** button additionally offers SVG.
- Output lands in `<Output folder>/Group Analysis/<group name>/` — see the output-folder changes below for what happens on a repeat run with the same name.

**New: organized, collision-safe output folders**
- With an Output folder set (Options), every export now nests as `<Output>/<data type>/<recording name> (Analysis)/` — e.g. `TDT/PFC-GCaMP-Sucrose-251222-210404 (Analysis)/AUC_142s_143059.csv` — instead of dropping every file flat into one folder. The " (Analysis)" suffix means an export folder can never be mistaken for the real recording folder/file sitting next to it. Two different recordings that happen to share a folder name are disambiguated automatically (`... (Analysis) (2)`, `(3)`, ...); reopening the same recording reuses its existing folder so exports accumulate there across sessions. With no Output folder set, behaviour is unchanged (a save dialog, seeded from the last-opened folder).
- Exporting the same file twice never silently overwrites the first: a repeat auto-resolved export gets " (2)", " (3)", ... inserted before the extension. Group Analysis gets the equivalent at the folder level — re-running the same group name gets a freshly numbered `Group Analysis/<name> (2)/` folder instead of overwriting the previous run's tables/figures/report, so the old "Group already saved — Replace them?" prompt is gone (there is never anything left to replace).

**New: progress toasts for more background work**
- Loading a recording (TDT, Oxysoft, and now generic tabular data too), Splice's cut-out/replay/restore, Event PETH, Peak Finder, and the text-field-study/validation pipelines all show a live percentage in the same bottom-right toast used elsewhere, instead of freezing the window with no feedback.
- Fixed a freeze after a background load finished: cleanup dropped the worker thread's last reference on the GUI thread while the worker still needed the GIL to finish shutting down. The thread is now waited on first, which releases the GIL.

**Fixed: Splice's "Keep only this range" didn't recompute dF/F**
- For TDT recordings, "Cut out this range" already re-ran motion/bleaching correction on the result; "Keep only this range" silently kept the *original* fit instead, computed from data that may no longer even be in the kept window. Both modes now re-fit dF/F on whatever raw signal survives the splice.

**Fixed: Z-Score PETH and Event PETH heatmaps used a fixed ±5 color range**
- The single-recording Z-Score PETH heatmap/trace and Event PETH's stacked-trial heatmap always colored/scaled to a hardcoded -5..5, regardless of the data (matplotlib's default tick spacing on that range lands on -4,-2,0,2,4, which read as "-4 to 4"). Both now scale to that trial's/recording's own 98th-percentile |z|, matching how the Group Analysis heatmap already worked — a quiet recording is no longer washed out and a large responder is no longer clipped.

**Changed: Options' motion-correction method applies immediately**
- Changing Regression (Options → Motion Correction) and clicking OK now reprocesses the currently loaded TDT recording right away — no separate click on the toolbar's Reload button needed. The note under the dropdown no longer says otherwise.

**Changed: loading a recording no longer pops up a "Success" dialog to dismiss**
- Opening or reloading a TDT/Oxysoft/generic-tabular recording, and opening a text field study, showed a modal "Success" popup that had to be clicked through — every time, including the new automatic reload above. It's now the same bottom-right toast used everywhere else in the app. For TDT specifically, the toast no longer names the folder at all (the plot's own title already shows it) — it shows the regression method's inlier percentage instead, the one thing not already visible anywhere, and shows nothing at all for a single-channel recording (no motion correction to report).

---

## v3.0.1
**Fixed: analysis numbers — now requires `ZaksPhysicsLibrary>=2026.9.24`**
- Motion correction is now fitted in float64. TDT streams are float32, and on a long recording the isosbestic regression silently returned a line at roughly half the true slope (`np.polyfit` in single precision drops the slope term past ~200,000 samples, ~3 minutes at 1 kHz). That hit the **default OLS setting**; RANSAC and Huber barely changed. On a 17-minute test recording the default's peak PETH z-scores were 2-3x too large, and after the fix OLS, RANSAC and Huber agree (mean PETH traces r ≥ 0.995).
- ΔF/F is now a real ΔF/F. The two-channel path used to divide the motion-corrected residual by the bleaching trend of that same near-zero residual, so the "Normalized (dF/F)" trace had the right shape but a meaningless scale and offset (a simulated 10% transient read as +1,650% with Huber and +399,000% with OLS). It is now divided by the 465 channel's bleaching baseline. Splice's "Cut out this range" goes through the same fix.
- Z-Score PETH, Event PETH and the Peak Finder no longer clip the signal to ±5 in raw units before z-scoring (which made z-scores depend on the signal's units, gave all-zero z-scores for large-valued signals, truncated large responses and put latencies too early). A brief artifact in the baseline is now handled by winsorising the baseline at 5 robust SDs instead, so the result no longer depends on units.
- What changes for you: dF/F values, and anything computed in dF/F units (AUC of dF/F, exported dF/F, amplitudes), differ from earlier versions; z-scored PETH shapes change little except with the default OLS on recordings longer than ~3 minutes. Figures made with those should be regenerated.

**Changed: the Peak Finder's default Z-score threshold is 5 (was 2.5)**
- The response search takes the largest z in each event's window, so 2.5 reported a "response" for about 58% of random pseudo-events on a real recording (10% at 5; the box's tooltip says so). The box still goes from 0.5 to 20 for anyone who wants it lower.

**Changed: the license is stated as AGPL-3.0 everywhere**
- The README (which said MIT), the package metadata (`license = "AGPL-3.0-only"`, which needs `setuptools>=77` to build), `CITATION.cff` and `packaging/README.txt` all match the `LICENSE` file now. Both release zips (Windows and macOS) include the license text as `LICENSE.txt`.

**New: `CITATION.cff`**
- GitHub's "Cite this repository" box works, and Zenodo can read it; it matches the app's ❝ APA Citation.

**Changed: repository name cleanup**
- The README clone and releases links, the `packaging/` docs, the status-bar bug-report link (`REPO_URL`) and the update check (`update_check.py`) use the current repository name, `zakgm2/PyAT`, instead of the old ones.

---

## v3.0.0
**Changed: the app is now PyAT (Python Analysis Tool)** — a new major version because the name changed; nothing about how existing recordings, sidecar files or saved settings work was broken by it.
- Renamed everywhere a user sees it: the window title, the citation and update-available text, the README / `packaging/` / `MACOS_INSTALL.md` docs, and the built artifacts — CI now produces `PyAT.exe` (Windows) and `PyAT.app` (macOS) and names the release assets to match (`PhysicsAnalysis.spec` builds with `name='PyAT'`; the spec file's own name is unchanged). The desktop launcher shortcut is now `Python Analysis Tool.lnk`.
- Deliberately *not* renamed, so nothing that already exists breaks: the `physicsanalysis_qt` package, the GitHub repo/URLs, the `~/.physicsanalysis` settings folder (saved settings carry straight over), the `PhysicsAnalysis.spec` filename, the `PhysicsAnalysisGUI` distribution name, and the macOS bundle id.
- Now requires `ZaksPhysicsLibrary>=2026.9.22`.
- Loading screen: new logo (`assets/AppIcon.png` — the magpie in a shield, with the PyAT wordmark), used on the splash only. Its silhouette now gets a 1px white outline instead of a black backing: the artwork is dark, so the old black backing made it vanish on a dark desktop. The window/taskbar/exe icon stays the original red shield (`icon.png` / `icon.ico`, unchanged).

**New: the Analysis dropdown is now an Analysis button**
- The toolbar's "Analysis ▾" dropdown (Z-Score / FFT / AUC / Curve Fit) and the separate top-bar "Window: Ns" button are replaced by one **Analysis** button that opens a menu, like Custom Statistics does (`physicsanalysis_qt/analysis/analysis_picker.py`). Pick Z-Score PETH, FFT, AUC or Curve Fit and a toast says what to do on the graph (double-click the point — Curve Fit: click two points). A picked tool is armed for **one run**, then disarms itself, like Splice. The analysis window setting (seconds either side of the click) now lives inside this menu instead of the top bar.
- **Persist through trials** (checkbox at the top of the menu): the tool stays armed after each run, so you can go from trial to trial by double-clicking each in turn. While it's ticked and a tool is armed, a **Done** panel sits in the window's bottom-left corner — press it to stop. Each analysis graph window (FFT, Z-Score PETH, AUC, Curve Fit) also has a **Done** button at the bottom: it closes the window and turns the tool off, while closing it with the X leaves a persistent tool armed for the next trial. With the checkbox unticked there is no panel — the tool just runs once.
- Going back to the Analysis menu cancels whatever was armed, so closing it with the X returns you to the plain plot. The selected tool is shown on the button ("Analysis: FFT", in the same armed yellow Add Marker uses).
- Internal: `ctx.analysis_mode` (None, or the armed tool's name) replaces `ctx.plot_type_combo`, which no longer exists; `analysis/window_settings.py` no longer owns a toolbar button.

**New: per-trace line colors in Edit Attributes**
- A new **Line Colors** group: one row per plotted trace with a color swatch and a Reset button. Clicking a swatch opens a continuous color picker (`physicsanalysis_qt/color_picker.py`) — a hue/saturation rectangle with a circle pointer, a vertical darkness slider on its left (the whole rectangle darkens live as it moves), a hex field, and an old-vs-new preview.
- Applies on all three plot engines (matplotlib, PyQtGraph, VisPy — including VisPy's legend swatch) and survives switching the Plot dropdown, including into and out of Overlay All. Oxysoft's per-channel lines follow their group's single legend entry. Picks are keyed by the trace's original name (renaming a legend entry never loses one) and, like the other attributes, last for the session. Every engine resolves trace colors through one helper, `context.trace_color()`.

**New: "Tools" title on the left sidebar**
- The sidebar now has a bold "Tools" title beside its collapse arrow. Collapsed, it shrinks to a slim tab with "Tools" written sideways down the middle (clickable, like the arrow), following the light/dark theme.

**New: windows and dialogs fit small screens**
- The Options dialog used a hard-coded size that didn't fit small displays. Options, Edit Attributes, Add Marker and Compare Fields now scroll and size themselves to their content, never exceeding the screen; the analysis, loader, splice and study windows (FFT, Z-Score, AUC, Curve Fit, Event PETH, Peak Finder, Intervals, Custom Statistics, the Generic/PT2 loaders, and so on) open at a size capped to a fraction of the available screen, and so does the main window (up to 95% of it). The handful of tiny fixed-size dialogs are left as they were (`physicsanalysis_qt/window_fit.py`).

**Changed: one notification toast at a time**
- Toasts (bottom-right) used to pile up on top of each other, each only dismissing itself on its own timer. A new toast now replaces the one on screen immediately, and an older toast's timer can no longer cut a newer one short. The Done panel above is separate (bottom-left) and never replaced by a toast.

**Fixed: PyQtGraph lines and legend piling up when switching the Plot signal**
- Switching from **Overlay All** to a single signal left the other overlay lines (and their legend rows) drawn on top: the in-place fast path used for single-to-single switches only retargeted the first line. It now applies only when exactly one trace is drawn; anything else does a full rebuild.
- Even plain switches grew the legend by one row each time: the legend bookkeeping (`ctx._legend_entries`) was being wiped by matplotlib's canvas resize handler, which still fires for the hidden matplotlib canvas while another engine is active. The old row was then never found to remove. The row is now removed via the line item itself, and that handler does nothing unless matplotlib is the active engine — which also fixes Edit Attributes' legend-rename list coming up empty after any window resize on PyQtGraph or VisPy.

**Fixed: VisPy legend**
- Legend rows from a previous plot stayed painted underneath the new ones ("stacking" after each Plot switch); after the first redraw the legend collapsed to an empty sliver (its rows were sized before Qt had shown them); its text was invisible in dark theme (white-on-white — the canvas is always white); and every row and label got its own border. Fixed: old rows are detached immediately, rows are shown before sizing, text color is fixed, and the border is scoped to the legend itself.

**Fixed**
- Edit Attributes' "Labels & Font Sizes" group title rendered as "Labels _Font Sizes" (Qt treats a single `&` as a shortcut marker).

---

## v2.13.0
**New: Splice's "Cut out this range" recomputes dF/F on TDT recordings**
- Removing an artifact and stitching the rest together used to just cut the already-computed dF/F trace along with everything else — the motion/bleaching correction underneath it was still the one originally fit *with* the artifact still in the recording. Cut Out now re-runs motion correction and bleaching correction (`PhysicsLibrary.compute_dff`, factored out of `process_tdt_folder` for this) on the stitched raw signal, so the fit for the rest of the recording can actually improve once the artifact is gone from what it's fit against — not just show a shorter view of the old one. Uses whatever regression method is currently selected in Options. Keep Inside intentionally still doesn't recompute — a short trimmed window doesn't have enough data for a stable refit.

**New: Open Data Folder detects multiple TDT recordings in one directory**
- Picking a folder that isn't itself a TDT block now searches every subfolder underneath it, at any depth, for ones that are (e.g. a cohort folder containing per-subcohort folders that each contain the actual per-animal/per-session recordings, not just a flat one level down) — anything that's never a TDT block anywhere in the tree is silently ignored, same as a single folder's own validation already does. Stops descending once a folder is confirmed to be a TDT block itself.
- 0 found → error. 1 found → opens it directly, same as picking it by hand. 2+ found → reports the count and asks **Single Experiment Analysis** (pick one from a list to open) or **Hypothesis Testing** — the latter is wired in as a placeholder only for now ("not built yet"), since there's no real cross-recording analysis or data to validate one against yet; it exists so the choice is already there once that gets built. The picker labels each entry with its path relative to the searched folder rather than just its own name, since two recordings nested under different subcohorts could otherwise share a name (e.g. two different subcohorts each with their own "Animal1_Day1").
- Guards against a directory cycle (a folder that links back to one of its own ancestors) by tracking each folder's real, symlink/junction-resolved identity rather than relying on `os.walk`'s own `followlinks=False` default — confirmed by direct testing with a real Windows NTFS junction that that default doesn't catch a junction cycle at all (`os.path.islink()` returns False for a junction), which would otherwise walk the same real folder over and over, reporting it as more and more distinct-looking "finds" each time, stopped only by accidentally hitting the OS's path-length limit rather than by any real protection.

**Fixed: saved markers/splices could be silently lost or corrupted on reload**
- TDT: a marker added *after* applying a splice, then saved via Save Changes, was silently dropped on the next load. `markers.json` already holds the final, post-splice marker state, but the old load order ran it through splice replay's own cut/shift logic a second time — re-interpreting a post-splice marker's timestamp as if it were on the original, unspliced timeline, and dropping it if that landed inside a cut range. Fixed by replaying splice.json *before* loading markers.json, so markers.json is a plain final overwrite instead of going through the splice logic twice (`loaders/tdt.py`).
- Oxysoft: splices were never restored on reload at all — `loaders/oxysoft.py` saved `splice.json` (Save Changes reported success) but never read it back. Now wired up with the same splice-before-markers order as TDT, plus a reset of stale splice state from a previously-loaded recording (matching TDT's own guard against that).
- Generic: neither markers nor splices were restored on reload — `loaders/generic.py` never called either sidecar loader. Both are now wired up the same way as TDT/Oxysoft.
- Splice's "Cut out this range" couldn't cut from the very start or to the very end of a recording — it required usable signal on both sides of the cut, so removing e.g. a bad first few seconds wasn't possible (PhysicsLibrary's `splice_cut_out`, now only requires 2+ samples to remain overall).
- Clicking outside the recording's actual time range during Splice's two-click point selection (any of the three plot engines) now clamps to the nearest boundary sample instead of handing an out-of-range time to the splice — none of the engines restrict clicks to where data actually is, only to the visible axes area.

**Changed**
- Default motion-correction regression is now OLS instead of RANSAC (Options → Motion Correction) — RANSAC's hard exclusion can distort the correction at a real, large transient it misjudges as an artifact, where OLS's weakness (the fit line drags toward severe artifacts) is at least predictable. RANSAC/Huber are still available and worth trying per-recording.
- The Options dialog's regression note now points out the three methods can give noticeably different results on the same recording and suggests comparing them before settling on one.
- Splice's mode picker now lists and defaults to **Cut out this range** instead of **Keep only this range** — removing an artifact is the more common reason to splice than trimming to a window.
- Internal cleanup pass, no behavior change: FFT peak annotation (labels/arrows/line drawn on the plot) moved from PhysicsLibrary into this app's own `analysis/fft.py` — drawing onto a matplotlib Axes is presentation, not computation, and didn't belong in a library with no other GUI code in it. `plotting.py`/`pg_engine.py`/`vispy_engine.py` each had their own inline `.mean(axis=0)` for Oxysoft's multi-channel display trace instead of calling PhysicsLibrary's already-exported `mean_channels` — now they do, one fewer duplicated one-liner across three files.

---

## v2.12.1
**New: Loading screen redesign — just the logo, and the update prompt lives on it too**
- `physicsanalysis_qt/splash.py`: the loading screen is now just the app logo itself (masked to its own silhouette via `QPixmap.mask()`, not a rectangular card) with a thin black border tracing its outline, instead of the previous dark rounded card.
- The "a newer version is available" prompt no longer opens as a separate popup — it swaps this same splash window's content in place to a message + **Continue Anyway** / **Download Update** buttons (dark-gray card), plus a small **✕** in the corner for "just close the app, I don't want to update or keep going either."
- Fixed a real bug in the process: the old popup was a plain `QMessageBox`, and this splash window is always-on-top — so the popup could open *behind* the splash, invisible and unreachable, which is what made an available update feel like the app had hung on "Checking for updates...". One window now, no second popup to get stuck behind anything.

**Fixed**
- The loading screen briefly flashed on real Windows launches — first traced to `WA_TranslucentBackground` (true per-pixel window transparency), which is known to be unreliable on Windows' compositor for this kind of window; replaced with the older, always-reliable opaque-region window mask instead. A second, smaller flash remained after that (the mask not being picked up until the window's native handle actually existed) — fixed by forcing native window creation before masking, plus fading the window in via `windowOpacity` only once everything's confirmed settled, so nothing ever paints half-formed.

---

## v2.12.0
**New: Area Under Curve (AUC) analysis**
- New "AUC" option in the double-click Analysis dropdown, alongside FFT/Z-Score/Curve Fit (`physicsanalysis_qt/analysis/auc.py`). Oxysoft gets Mean O2Hb/HHb/optional tHb channels, TDT/Generic get whichever signal the Plot dropdown currently shows — same per-source branching as the other click-triggered tools.

**New: Custom Statistics picker window**
- Replaces the old "Advanced Analysis ▾" toolbar menu (`physicsanalysis_qt/analysis/custom_statistics.py`). Lists dataset-specific tools (Event PETH, Find Significant Peaks) that each declare which source type they need, so a dataset with no applicable tool says so explicitly instead of the menu just not showing anything.

**New: Event PETH "Trials" view**
- A 5th mutually-exclusive toggle alongside Z-Score/AUC/Peak/Bins: overlays every checked trial's individual z-score trace directly (no mean, no SEM band), each trial colored from a 15-color cycling palette so trial-to-trial shape/timing is visible without collapsing into one average. Has its own matching CSV export (one row per trial per timepoint).

**New: Splice Recording now works on Oxysoft and Generic sources, not just TDT**
- `analysis/splice.py`'s `_splice_once` now branches per `cache['source']` and routes every source's arrays — Oxysoft's 2D per-detector channels, Generic's 1D columns — through PhysicsLibrary's now axis-agnostic `extra_channels` slicing. The click-to-anchor capture driving this was already source-agnostic; this module was the only actual blocker.

**New: Motion-correction regression method is now a real choice**
- Options → Motion Correction (TDT): pick RANSAC (default, excludes severe artifacts entirely), Huber (downweights outliers instead of excluding them), or OLS (plain least-squares, no robustness) for the 415-vs-465 isosbestic regression — previously hardcoded to RANSAC. Takes effect on the next TDT folder load/reload.

**New: Status bar — APA citation, feedback, and coffee buttons**
- `❝ APA Citation` copies a ready-made APA 7 software citation for this app to the clipboard, for anyone citing it in a paper. `🐞` opens this repo's GitHub issues page for bug reports/feedback. `☕` opens [buymeacoffee.com/zakgm2](https://buymeacoffee.com/zakgm2). All three live in the status bar's bottom-right corner, in that left-to-right order.

**New: Output Folder option**
- Options → Folders → Output folder: pin every CSV/PNG/PDF/SVG export to a specific folder — skips the save dialog entirely and just saves there with a confirmation toast. Leave blank to keep the previous behavior (follows wherever you last opened a file from).

**Changed**
- Every stats-bearing analysis dialog (AUC, FFT, Z-Score, Event PETH, Peak Finder's alignment/scan results) now shares one Copy + Export CSV button pair (`analysis/dispatch.py`'s new `add_stats_export_buttons`) instead of five near-identical hand-rolled copies — Peak Finder's results dialogs gained CSV export for the first time as a result.
- Every export path across the app (figures and CSVs — Curve Fit, FFT, AUC, PETH, Event PETH, Intervals, PT2, Text Field Study, Statistical Validation) now goes through one shared `export_file()` (`context.py`) — respects the new Output Folder setting uniformly and always ends with a "Saved …" toast.
- FFT and Z-Score windows migrated to the same per-source channel-list pattern AUC/Curve Fit already used — Oxysoft's optional tHb channel, previously only available in AUC/Curve Fit, now shows up in FFT and Z-Score too.
- Peak Finder's alignment/scan tools now always analyze the normalized signal (`get_normalized_signal`) regardless of what the main plot's Plot dropdown currently shows — matching Event PETH's existing behavior, since these are dataset-specific "Custom Statistics" tools rather than generic click-analyze ones.
- Trace opacity is now consistent across all three plot engines — PyQtGraph and VisPy previously drew every trace fully opaque while matplotlib varied by trace type (0.8 for TDT/overlay traces, 0.5 for Oxysoft per-channel traces, opaque for means/Generic); both engines now match matplotlib's values exactly.
- New "Overlay All" entry in the TDT Plot-signal dropdown shows every per-wavelength signal at once on the main plot, on all 3 engines.
- Marker hit-testing (right-click menu, click detection) now scales with zoom — a constant ~5px on-screen radius converted to data-space seconds from the current view, instead of a fixed 2-second tolerance that made right-click-to-pan near a marker nearly impossible once zoomed in.
- Measure Intervals moved from the top toolbar into the left icon sidebar (📏 ruler icon), alongside Rescale/Add Marker/Splice/Save/Undo.
- `PhysicsLibrary`'s shared helpers (`compute_group_stats`, `estimate_sample_rate`, `compute_marker_intervals`) now back Event PETH's group mean/SEM, the Generic loader's sample-rate estimate, and Measure Intervals' computation, replacing formulas that were previously duplicated at each call site.

**Fixed**
- FFT exports were silently overwriting the same file every time (no timestamp in the filename) — now match every other export's `HHMMSS`-suffixed naming.
- Curve Fit's Generic-source branch was silently broken: its cache-key fallback always evaluated to `None` for any Generic/Excel/CSV/TSV file (those caches have no `corr`/`raw` keys, only `y_columns`), so Curve Fit never actually worked on Generic sources. Found and fixed while aligning its per-source branching with AUC/FFT/PETH's.
- VisPy's click-vs-drag threshold hardcoded `5` at one call site instead of referencing the shared `_MIN_DRAG_PX` constant already used everywhere else in the same file.

---

## v2.11.3
**Changed: Update check no longer forces you to go update**
- The "a newer version is available" dialog now offers a real choice instead of a wall: **Continue Anyway** launches the current version normally; **Download Update** opens the release page and exits instead (so the old version isn't still running while a new one gets installed over it). Previously the app refused to launch at all once an update was detected, with only a "Close" button that also just quit — see `physicsanalysis_qt/update_check.py`'s `show_update_available_dialog` (renamed from `show_update_required_dialog`).

---

## v2.11.2
**Fixed**
- `physicsanalysis_qt/__init__.py`'s `__version__` (what a packaged build actually reads at runtime — there's no `pyproject.toml` on disk in a frozen exe) hadn't been bumped alongside `pyproject.toml`'s version during the v2.11.1 release, so every freshly-built app still reported itself as the *previous* version and permanently thought a newer release was available no matter how many times you reinstalled "latest" — the update-check comparison was accurate, the baked-in version string it was comparing against just wasn't. Also added explicit `[tool.setuptools.packages.find]` config to `pyproject.toml`: the new `packaging/` directory (README/thank-you files for the distributed zips) collided with setuptools' automatic flat-layout package discovery — it happens to share a name with an actual dependency of this project — causing `pip install .` to fail outright in CI with "Multiple top-level packages discovered."

---

## v2.11.1
**New: CI-built Windows/macOS executables**
- `.github/workflows/build.yml`: on a version tag push (or manually via the Actions tab), builds a native PyInstaller executable on `windows-latest` and `macos-latest` separately (PyInstaller can't cross-compile) and attaches both to a GitHub Release for that tag.
- `PhysicsAnalysis.spec` switched to onefile mode — a single `.exe`/`.app` instead of a folder of files, so the Windows build uploads directly with no zip step (macOS still zips its `.app`, since that's an inherently multi-file bundle regardless of onefile/onedir).
- macOS's `.icns` app icon is generated automatically during the CI build from `icon.png` via `sips`/`iconutil` (no Mac needed locally to produce it).
- App icon (`icon.png`/`icon.ico`) updated to the actual logo at full resolution (512×512), replacing a placeholder-quality 192×192 version.

---

## v2.11.0
**New: VisPy (OpenGL/GPU-native) plot engine — third option alongside matplotlib and PyQtGraph**
- `Options -> Plot Engine -> VisPy (OpenGL, experimental)` adds a genuinely GPU-native rendering engine for the main plot (`physicsanalysis_qt/vispy_engine.py` + `vispy_interaction.py`, ~950 combined lines). Unlike PyQtGraph — whose 2D line rendering is actually CPU/Qt-painter-based, fast via clever decimation rather than true GPU shading — VisPy renders through OpenGL directly.
- Full feature parity with the other two engines: axes with real tick labels, gridlines, a hand-built legend (VisPy has no legend widget) shown as a Qt overlay so it doesn't shrink the plot area the way a side panel would, event markers as hand-built vertical lines (VisPy has no infinite-line visual) that stay extended to the current view during live pan/zoom, hover snap-to-nearest-point with the status bar readout, marker placement, right-click marker rename/delete menu, Curve Fit and Splice click-to-anchor, and double-click-to-analyze.
- Left-drag = rectangle zoom (a translucent yellow overlay while dragging), right-drag = pan, wheel = zoom at cursor — matching the app's existing convention on the other two engines via a custom `RectZoomPanCamera` (VisPy's own stock camera binds left-drag to pan and right-drag to zoom instead).
- Manual min/max-envelope decimation (VisPy has no PyQtGraph-style built-in downsampling) keeps pan/zoom cost independent of recording size — verified against a 1,055,744-sample real recording: displayed points stay capped at the configured budget while hover/click still resolve against the full-resolution data underneath. Re-decimates automatically as you pan/zoom.
- Title/axis-label/tick font sizes and axis-column pixel widths scale with window size the same way PyQtGraph's engine does, so all three engines look proportionally consistent at any window size.
- Export View support via `canvas.render()`, compositing the Qt-overlay legend back in so the exported PNG matches what's actually on screen.
- Marked "experimental" in the Options dialog — genuinely GPU-native rendering is a real potential win for very large recordings, but this is the newest of the three engines and hasn't seen the same real-world mileage as matplotlib or PyQtGraph yet.

---

## v2.10.0
**Changed: Update check now blocks launch for a stale app, checks PhysicsLibrary too**
- An available PhysicsAnalysis update now refuses to launch the app at all — instead of building the main window, it shows a dialog with the new version number and a link to download it (an "Open Download Page" button, plus the raw URL as text). A PhysicsLibrary update stays a quiet, non-blocking splash status line, since that's developed locally alongside this app and drifting ahead of what's pushed to GitHub is an expected mid-work state, not something to block launch over.
- "Latest version" for either project now prefers the tag of its latest published GitHub Release when one exists, falling back to the version committed in `pyproject.toml` on the default branch when it doesn't (neither project reliably uses Releases). Checked via `physicsanalysis_qt/update_check.py`'s `UpdateCheckWorker`, still on a background thread with a 5s cap so a slow/absent network never holds up launch.

---

## v2.9.0
**New: Loading screen**
- A small frameless, rounded splash screen (`physicsanalysis_qt/splash.py`) now shows immediately on launch — the app's logo (`physicsanalysis_qt/assets/icon.png`) with a gentle pulse and a status line, closing once the main window is ready. Stays up at least ~3s even if setup finishes faster (this app's startup usually does), so it's actually visible instead of flashing past before it registers. Also now used as the app/taskbar window icon, and as the icon for the new `Launch PhysicsAnalysis.lnk` desktop shortcut (`physicsanalysis_qt/assets/icon.ico`).
- Checks GitHub for a newer PhysicsAnalysis release while the splash is up (`physicsanalysis_qt/update_check.py`) — a quiet "Update available: vX.Y.Z" status if one exists, silent otherwise (no releases published yet, offline, GitHub unreachable — none of those are worth interrupting startup over). Runs on a background thread with a 5s cap so a slow/absent network never holds up launch. Checks this repo only, not PhysicsLibrary — that's developed locally alongside this app and would never match whatever's published.

**New: Splices stack, with a manager to review/remove them**
- Splice Recording no longer restarts from the pristine original every time — each new splice now applies on top of whatever's currently shown, so removing several separate artifacts from the same recording no longer means the second attempt undoes the first. Left-click the sidebar's scissors icon to add another splice at any time; right-click it for a **Manage Splices** list showing every splice currently applied (in order), each individually removable, plus a one-click **Restore Full Recording**. Removing one from the middle replays the rest from the original in order — the same tradeoff any sequential edit/undo stack has: removing an earlier step can shift what a later step's saved range lines up with. `JSON saves/splice.json` now stores the whole list (old single-splice files still load fine).

**New: `Launch PhysicsAnalysis.lnk`**
- A proper double-click launcher (repo root) that runs the app via `pyw.exe` directly — no console window ever appears, and it doesn't depend on however (or whether) `.pyw` happens to be file-associated in Explorer. Copy/pin it wherever's convenient; its target and working directory are absolute, so it works from any location.

**Changed**
- Motion correction now uses PhysicsLibrary 1.10.0's corrected noise-estimate formula for RANSAC's residual threshold (fixed in 1.9.1 — see that changelog for why) and skips the 'Tick' epoc store entirely when building marker/event lists — it's TDT's own 1-second heartbeat signal, not a real event, and previously cluttered every marker and Event PETH picker.
- A toast now reports what fraction of samples RANSAC kept as inliers right after a TDT folder loads (only shown when a 415 reference stream exists, since that's when motion correction actually runs) — visibility into how much of the recording was judged to be motion artifact and excluded from the fit, via PhysicsLibrary 1.10.0's new `motion_correction_inlier_fraction`.

**Fixed**
- PyQtGraph engine: Splice mode's click-to-anchor-two-points never actually did anything — the click dispatch (`pg_interaction.py`) only ever handled Curve Fit clicks; Splice's handling existed only in the matplotlib engine's `interaction.py`. Splicing now works identically on both engines.
- Event PETH's heatmap Y-axis ("Trial") could show fractional tick labels (e.g. 2.5) for small trial counts — trial rows are a count, not a continuous quantity. Forced to integer-only ticks.
- Rescale (and every "show everything" moment — a fresh load or a Plot signal switch) fit the matplotlib view exactly to the data's bounds with zero margin, leaving the trace flush against the plot edges. PyQtGraph's `autoRange()` already adds a small default margin; matplotlib's `set_xlim()` doesn't, so it needed an explicit ~2% padding to match.
- Loading screen could still flash past almost instantly despite the 3s floor: its wait loop polled `processEvents()`+`sleep()`, which isn't reliable for keeping a window actually composited on screen, and nothing forced a first paint before the (event-loop-free) main-window construction took over the thread. Swapped the wait for a real nested `QEventLoop` and added an explicit paint pump right after `show()`.
- Loading screen could render as a bare outline with no logo/text visible at all — `WA_TranslucentBackground` combined with the `SplashScreen` window flag is flaky on Windows (DWM sometimes never composites it). Switched the rounded corners to a plain window mask instead, which doesn't depend on real alpha compositing.
- Add Marker's "Add/Remove Auto-Detected Markers" list showed exactly one "Note" entry no matter how many distinct manually-entered notes (Clap, Sucrose, ...) the recording actually had, since every note shares the same underlying TDT store name — grouping now uses each note's own text for Note-style markers (matching how renaming/bulk-delete already treated them elsewhere), so every distinct note gets its own checkbox. Right-click renaming stays store-only, since a note's displayed text isn't a store name to begin with.
- Clicking the sidebar's scissors icon a second time in a row (without switching to another analysis mode first) silently did nothing instead of reopening the splice mode picker — it worked by setting the Analysis dropdown's text to "Splice", which only fires a change event the *first* time (re-setting a combo to the value it's already showing isn't a change). Splice-mode tracking no longer goes through that dropdown at all: "Splice" is removed from it entirely (it was never meant to be picked from there once the scissors icon existed) and a dedicated `ctx.splice_click_mode` flag drives both engines' click capture, so the scissors icon reopens the mode picker on every click.

---

## v2.8.0
**New: Plot options for TDT (Normalized / Isosbestic / Main Driver)**
- A new "Plot:" dropdown appears in the toolbar whenever a TDT recording is loaded, letting you choose what the main plot (and every TDT analysis tool — FFT, Z-Score PETH, Event PETH, Peak Finder, Curve Fit) actually shows: **Normalized (dF/F)** (the motion-corrected, bleach-corrected trace — what was always plotted before), **Isosbestic** (the raw 415-type reference channel, only shown if the recording has one), or **Main Driver** (the raw 465-type probe channel). Switching it re-renders immediately in both the matplotlib and PyQtGraph engines.
- Not hardcoded to exactly those three or to "465"/"415" — the options are built from whatever PhysicsLibrary 1.9.0's `process_tdt_folder()` actually found in the recording, so a block missing an isosbestic reference stream just shows Normalized + Main Driver, and the dropdown is hidden entirely for Oxysoft/Generic loads (which already show every channel at once). Replaces the old `show_corrected` raw/corrected toggle, which had no wired-up UI control and was effectively dead code.
- Splice Recording now trims/cuts these raw channels along with everything else, so picking Isosbestic or Main Driver still lines up correctly after a splice instead of showing stale, wrong-length data (PhysicsLibrary 1.9.0's `extra_channels` support).

**New: Per-trial include/exclude in Event PETH**
- Event PETH's results window now has a "Trials" checklist on the right — every trial starts checked, uncheck any to drop it from the heatmap and the mean/SEM trace (recomputed live from just the checked trials), with "All"/"None" buttons for quickly toggling the whole set. No automatic std/threshold-based rejection — this is a manual look-and-decide tool for dropping a trial that's obviously contaminated (movement, a marker that fired on a false trigger) without changing the event or window. The checklist rebuilds fresh (all checked) every time the event or window changes, since a checkbox tied to a row index wouldn't mean anything for a different trial count.

**New: Rescale moved to the icon sidebar**
- "Reset Zoom" is renamed "Rescale" and moved out of the top toolbar into the left icon sidebar, alongside Add Marker/Splice/Save/Undo.

**Changed**
- Motion correction now uses PhysicsLibrary 1.9.0's RANSAC robust regression instead of ordinary least squares — see that changelog for why. Affects dF/F values for any TDT recording with an isosbestic stream.

**Fixed**
- The view's "is this a new dataset or the same one redrawn" check used `id(cache)` — a freed cache dict's memory address can be reused by the very next same-shaped dict CPython allocates, which could make a brand new recording get silently treated as unchanged and snap to whatever zoom was active on the previous one. Replaced with an explicit generation counter bumped only on a genuine new load/splice/restore.
- Switching the Plot signal dropdown now always fits to the newly selected signal's full range instead of trying to carry over whatever pan/zoom was active — different signals can have wildly different scale, and there's no reason a zoom on one still makes sense on another.
- PyQtGraph engine: switching the Plot dropdown (and the resize-settle tick after a fresh TDT load reveals it) visibly flashed for one frame — both went through a full clear()+rebuild that briefly leaves an intermediate scene state on screen before the corrected view/data lands. Switching the signal now swaps the existing line's data/color/legend/title in place instead of rebuilding, and the resize-settle tick now only does its font/margin pass (`pg_refresh_fonts`) instead of a full replot — neither has anything left to flash, since there's no intermediate "cleared" state anymore. Same fix pattern this file already used for grid toggles (`pg_set_grid_visibility`).

---

## v2.7.0
**New: Debounce presses in Add Marker**
- Add Marker's auto-detected-store panel gained a "Debounce presses within ___ s of each other" checkbox (default 0.15s), next to the existing High/Low phase checkboxes — for rigs where a lever occasionally registers more than one contact for a single physical press (switch bounce/double-tap), regardless of the FR schedule (FR1, FR3, ...) in use. When checked, onset/offset markers are grouped per store+phase and filtered with PhysicsLibrary 1.8.0's new `debounce_events()` before being added to the plot; the success toast reports how many duplicates were dropped. Grouped per store+phase so a fast event in one store never suppresses an unrelated one in another, and Note-style markers (free-text annotations, no onset/offset phase) are never touched by it.

---

## v2.6.0
**New: Splice Recording**
- New left-side icon sidebar (📍 Add Marker, ✂ Splice, 💾 Save Changes, ↺ Undo All Changes), collapsible via a small arrow handle — tools that change how the data looks/is analyzed without ever touching the original raw data, moved out of the top toolbar rather than duplicated.
- **Splice Recording**: pick a mode (Keep only this range / Cut out this range — removes an artifact from the middle and stitches the remainder together, shifting everything after the cut so the timeline stays contiguous) then click two points directly on the plot to mark the range, same click-to-anchor pattern as Curve Fit. No typed start/end numbers. Works on a copy — the original recording is never mutated, restorable at any time via the same icon (becomes "Restore Full Recording").
- The active splice can now be saved (`JSON saves/splice.json`, alongside the markers sidecar) via Save Changes, and is automatically reapplied the next time the folder is opened — previously it was memory-only and lost on restart/reload.
- "Undo All Changes": discards marker/splice changes (including previously-saved ones) with a confirmation dialog, clears the `JSON saves/` folder's contents (not the folder itself), and re-reads the file fresh.
- Architecture: the actual splice computation (trim, cut-and-stitch, timeline-shifting, marker filtering) lives in PhysicsLibrary 1.7.0's new `splice_keep_inside`/`splice_cut_out` — this module is GUI orchestration only (dialogs, click capture, sidecar I/O), matching how Event PETH/Peak Finder already split GUI vs. computation.

**Event PETH / Peak Finder improvements**
- Fixed the results heatmap's colorbar stacking a new one on every row-order change or event switch instead of replacing the old one (needed to remove it before, not after, clearing the axes — order mattered because it restores the axes' pre-colorbar geometry on removal).
- Event PETH no longer requires closing and reopening to look at a different event — an Event dropdown right in the results dialog switches and recomputes in place. Also gained its own local pre/post window fields (defaulting to the global Window setting) with a Recalculate button, same pattern Curve Fit already used, instead of only ever using the global window.
- Peak Finder reworked: default scope now scans every event type at once and shows a summary (occurrences/hit-rate/avg z-score per type, sorted so likely-real events float to the top) with nothing added to the plot until you choose to — instead of requiring you to already know which single event to check. Both Event PETH's and Peak Finder's event lists now pull from every event TDT actually detected in the recording, not just what's already been added to the plot as a marker.

**Fixed**
- Grid toggle (Edit Attributes → Show Grid) didn't actually toggle — `ax.grid(False, color=..., linestyle=...)` is a matplotlib gotcha where passing style kwargs alongside `False` makes it force the grid back **on** regardless. Only pass those kwargs when actually turning it on.
- `RectangleSelector` (drag-to-zoom) visibly flashed while resizing the selection — the hover-tracker dot was doing its own independent canvas blit on every mouse-move tick during the drag, racing `RectangleSelector`'s own blit for the same region. Suppressed the hover tracker for the duration of a rect-select drag.
- The 📍 Add Marker icon lost its pin glyph and became clipped/garbled text ("Placing 'Marker'…" in a 44×44 square) while placing, and never got its icon back afterward — `toggle_marker_mode()` was overwriting the button's text directly, a leftover from when it was a full-width text button. Now reflects state via tooltip + background color only, never touches the icon's text.
- Oxysoft loader: a file whose Legend block doesn't match the expected `O2Hb`/`HHb` column format failed with a cryptic `not enough values to unpack` instead of saying what's actually wrong (PhysicsLibrary 1.7.0).

---

## v2.5.0
**New: Event PETH (GuPPy-style, stacked heatmap + trial average)**
- **Advanced Analysis ▾ → Event PETH**: pick an event/marker name and Z-score every occurrence of it against its own pre-event baseline, stacked as one row per trial in a heatmap (colorbar included) with the trial-averaged trace ± SEM plotted below — lets you actually see whether a response is consistent across trials, not just look at one clicked moment. Row order is sortable (trial order vs. peak amplitude) without recomputing. Distinct from the existing single-click PETH, which stays as-is.
- Event names are pulled from every event TDT actually detected in the recording (not just what's already been added to the plot), so this works on a freshly loaded file with zero markers placed yet.

**New: Find Significant Peaks**
- **Advanced Analysis ▾ → Find Significant Peaks…**: auto-detects statistically significant transients straight from the signal instead of trusting that event markers line up with real neural activity. Four scopes: scan every event type at once (a summary table — occurrences, hit rate, average z-score per event type, sorted so likely-real events float to the top, nothing added to the plot until you choose to), all occurrences of one chosen event type, one specific event instance, or a blind whole-recording scan unrelated to any marker. Event-scoped modes report per-occurrence found/latency/z-score. Found peaks are added as `AutoPeak`/`AutoTrough` markers, which work immediately with Event PETH.
- New PhysicsLibrary 1.6.0 functions backing both features: `compute_event_zscore_peth`, `find_significant_peaks`, `find_peak_near_events`.

**Fixed**
- Toasts were a separate top-level window pinned to a screen position instead of a child of the main window — didn't move/stack with it. Now a real child widget.
- Double-click-triggered analysis (FFT/PETH/Curve Fit hint) occasionally needed an extra click — matplotlib's own double-click detection could desync from `RectangleSelector`'s press handler seeing the same clicks. Replaced with a manual time+position double-click detector.
- Options dialog settings (including the default folder) only lived in memory and reset every restart — now persisted to `~/.physicsanalysis/settings.json`.
- Marker sidecar JSON was saved as a sibling file next to the raw data folder instead of inside it — now saved to a `JSON saves/` subfolder within the loaded folder (old sidecar locations still load as a fallback).
- A TDT epoc store with a level/buffered logic signal already "high" the instant recording started got a spurious onset marker at exactly t=0 (TDT's synthetic starting-state entry, not a real event) — now filtered out, mirroring the existing `offset == inf` guard for the opposite edge case.

**New: double-click to rename plot text; light/dark mode; Grid moved into Edit Attributes**
- Double-click the title, X/Y axis label, or a legend entry directly on the plot to retype just that one — updates the same values the Edit Attributes dialog shows.
- New Options → Appearance → Theme (Light/Dark): a Qt palette swap for every dialog plus matching matplotlib figure/axes/legend/grid colors, persisted like other settings. Applies to the empty canvas at startup too, not just after a file loads.
- The Grid toggle moved out of the toolbar into Edit Attributes ("Show Grid," next to Bold) — no longer a standalone toolbar checkbox.
- Toolbar reorganized: Advanced Analysis ▾, the Analysis mode combo, and the Window button now sit together in one section.

---

## v2.4.1
**Fixed: Curve Fit results invisible under Windows dark mode**
- The results box only set `background-color: white`, not the text color — on a system with Windows dark mode enabled, Qt6's automatic dark palette rendered the label text white as well, so fitted parameters were computed and displayed on the plot correctly but unreadable (white on white) above it. Text color is now explicitly pinned to black.

---

## v2.4.0
**New: text field study analysis**
- New **Text Field Study ▾** toolbar menu (its own dropdown, not mixed into the marker controls or the main Open menu — a study is a completely separate workflow from the main signal plot): **Open Study Folder**, **View Results**, **Statistical Validation**.
- **Open Study Folder**: pick a folder of one-JSON-file-per-subject data (any study, not a fixed schema — see PhysicsLibrary 1.5.0's `run_field_study_pipeline`). Every file matching the folder's naming pattern is loaded into one DataFrame, one row per subject.
- Field comparisons are set up inline, right after picking the folder: a dialog shows the actual field names found in that folder's own files (via `peek_fields`), and you just pick pairs of fields to compare directly (e.g. "does this answer track that one") — add as many comparisons as you want, plus an optional "how much did the response change between these two fields" measurement and a configurable low-word-count quality-flag threshold. No grouping concept to learn — pick two fields, name the comparison, done. Saved locally and pre-fills next time you open a folder.
- **View Results** (reopens without rerunning): a table of the analysis columns — word counts, data-quality flags, delta magnitude, paired similarity, a permutation-test p-value/effect size per pair, and a word-count-confound check — plus full-DataFrame CSV export.
- The actual field configuration for a given study (which fields, which pairs) is study-specific and lives in a local config file outside this repo (`~/.physicsanalysis/`), not in source — nothing about what any particular study measures ships with the app.
- New `ctx.study_data`/`ctx.study_data_path`/`ctx.study_data_config` — kept separate from `ctx.cache`, whose x/y/markers shape every plotting/marker/analysis module elsewhere assumes; a DataFrame doesn't fit that.
- New dependency: pandas.

**New: statistical validation for text field studies**
- **Statistical Validation** (in the same menu, and directly in the results dialog once a study has at least one comparison): re-runs the pipeline through PhysicsLibrary's `run_validation_pipeline` and shows one row per field pair — permutation-test p-value with Benjamini-Hochberg FDR correction across every pair, Cohen's d effect size, a word-count-controlled OLS regression coefficient/p-value per field, a bootstrap 95% confidence interval on the mean similarity, and leave-one-out sensitivity flags, plus a plain-language "Verdict" column (a quick-glance read, not a substitute for the actual numbers). Full CSV export.
- Fixed the results table forcing every column to equal width regardless of content (`Stretch` resize mode) — with this many columns, long header names were getting squeezed into columns far too narrow to hold them, reading as overlapping/garbled text. Columns now size to their own content, with horizontal scrolling for the rest.
- Fixed PhysicsLibrary's word-count confound check crashing outright (`pearsonr` needs at least 2 subjects) instead of returning `NaN` for a statistic that's genuinely undefined with too little data — same fix applied to Cohen's d, the word-count regression, and leave-one-out for the same reason.
- Clarified the whole workflow: the menu is numbered ("1. Open Study Folder…", "2. Statistical Validation") with tooltips explaining what each step does and that results already open automatically after step 1; both dialogs now explain in plain language what the similarity score and the statistics actually mean, not just their column names.

**Fixed: every Export/Save dialog opening to System32**
- None of the app's Export/Save dialogs (View, plot images, CSVs across curve fit, FFT, event intervals, and both new text field study dialogs) passed a starting directory to `QFileDialog.getSaveFileName`, so it fell back to the process's working directory — which on Windows can resolve to `System32` depending on how the app was launched. Every one of them now opens to the last folder you browsed to (or Desktop by default), matching how the Open dialogs already behaved.

---

## v2.3.0
**New: high/low phase for auto-detected markers**
- Every TDT epoc is a state that goes high (onset — a press, a light/pump turning on) and later low (offset — the release, turning off). `get_event_markers()` (PhysicsLibrary 1.4.0) now surfaces both instead of only onset.
- The Add Marker dialog's auto-detected section has **High**/**Low** checkboxes (High on by default) controlling which edges get bulk-added — most stores (lever presses, etc.) only need the press; a pump or light also benefits from the release/off edge for computing on-duration.
- Every phase-tagged marker on the plot now shows a superscript **¹** (high) or **⁰** (low) next to its label.

**New: rename auto-detected store names**
- Right-click a marker → **Rename** now offers "Rename all '\<store\>' markers" (checked by default) — applies to every marker from that store, past and future, instead of just the one instance. The store's raw id (e.g. `PP1_`) stays the internal grouping key everywhere; only the display changes.
- The Add Marker dialog's store list supports the same thing inline: right-click a store to turn it into an editable text box, Enter to save — no separate dialog needed. Left-click still multi-selects normally.
- **Reset Name** — in the Edit Marker dialog (only shown once a store has a custom name) and as a **Reset Selected Names** button in the Add Marker dialog's store list — reverts back to the raw store id.
- New **"Delete all '\<name\>' markers"** action in the right-click menu, next to the existing single Delete — removes every marker sharing that name (both phases together for a renamed/auto-detected store, since they're "the same name" once renamed, just a different superscript).
- Note markers (free-text annotations like 'Clap') and manually-placed markers are never affected by store renames — their label was never derived from a store name to begin with.

**New: Measure Intervals**
- New **Measure Intervals** toolbar button: a table of every marker currently on the plot (any source — TDT, Oxysoft, or manually placed), sorted by time, with two interval columns — time since the previous event in the same store (which is exactly the on-duration for a store with alternating high/low phases) and time since the previous marker of any kind (useful when several event types are interleaved). Exportable as CSV.

**New: single Reload actually reloads**
- **Reload** previously just re-opened the same file picker as Open. It now re-reads the currently loaded folder/file from disk in place: TDT/Oxysoft skip the dialog entirely, Generic (Excel/CSV/TSV) re-parses the same file and reopens the table/column picker (skipping only the file-choice step). Falls back to Open if nothing's loaded yet.

**Fixes**
- Fixed several real Qt bugs found while building the inline store-rename box: the built-in item-editing delegate (`editItem()`) painted the old text underneath/offset from the new editor rather than replacing it — replaced with a manually-managed `QLineEdit` overlay; committing on Enter was falling through to the dialog's default button ("Start Placing"), dropping the user straight into marker-placement mode, because the editor was torn down synchronously while still inside its own Return-keypress dispatch; clicking a dialog button (e.g. "Add Selected") while a rename was still uncommitted needed two clicks to register, because auto-committing on focus-loss destroyed the editor mid-dispatch of its own focus-out event, corrupting that same click's delivery to the button. Renaming now only auto-commits from inside the editor on Enter/Escape; any other dialog action explicitly flushes a pending rename first (silently, folded into that action's own single redraw) before proceeding — so renaming and then immediately clicking Add/Remove/Start Placing now takes exactly one click.

---

## v2.2.0
**New: redesigned marker workflow**
- Fresh loads (TDT and Oxysoft) no longer auto-populate the plot with every detected event marker — a busy TDT recording can easily have a dozen+ epoc stores (I/O strobes, Tick, Epoch Event Storage, …) that used to overlap into an unreadable mess. Auto-detected markers are now kept separately (`detected_markers`) and only added when you ask for them.
- **Add Marker** now opens a dialog instead of immediately entering placement mode:
  - **Add / Remove Auto-Detected Markers** — multi-select one or more stores (ctrl/shift-click) and Add Selected or Remove Selected in one action.
  - **Place Custom Markers** — configure a name/colour/font size once, then **Start Placing**: click the plot repeatedly to stamp markers with that config (Snipping-Tool style) until you toggle Add Marker off again — no more re-opening a dialog for every single marker.
  - **Remove Markers** — a multi-select list of every marker currently on the plot (auto-detected or custom), with Select All + Remove Selected for fast batch cleanup.
- Removed the "Undo Last" toolbar button — redundant now that removal is multi-select and immediate.

**New: asymmetric analysis window**
- The always-visible "Window (s)" field is now a single **Window** toolbar button showing the current setting, opening a small dialog: **Symmetric** (default, one "window size" field = the total span, split evenly before/after the event) or untick it for independent Before/After fields — e.g. 10s before an event, 20s after.
- `PhysicsLibrary`'s `get_zscore_slice()`/`compute_fft_slice()` gained matching `pre`/`post` parameters (see PhysicsLibrary CHANGELOG).
- Fixed PETH silently ignoring the window setting entirely — it hardcoded a 30s window and hardcoded plot axis ranges regardless of what was configured; it now honours the same Window setting FFT already did.

**Fixes: resize smoothness (PyQtGraph engine)**
- Fixed the PyQtGraph plot flashing to fill the whole widget for one frame on every resize and on any redraw (e.g. Edit Attributes) — its margin-measurement pass briefly zeroed out margins to probe axis geometry; repaints are now frozen for that probe so the intermediate state is never shown.
- Resize is now smooth and live instead of snapping once after the drag settles: a cheap per-tick margin/font update (reusing the last-measured axis size, no flash-prone probe) runs on every resize event, with the more expensive accurate re-measurement + full replot debounced to once after the drag ends.
- Matplotlib engine's title/axis-label/legend fonts now also rescale live during resize — previously only the plot area itself resized live; text stayed a fixed size until the next full redraw.
- Fixed a genuine pyqtgraph bug where `LegendItem.setLabelTextSize()` never actually re-rendered the legend text (it only updated internal state) — legend font size now visibly updates by forcing each label's `setText()`.

**Fixes: other**
- Fixed **Reload** just re-opening the same file picker as **Open** — it now re-reads the currently loaded folder/file from disk in place instead. TDT/Oxysoft skip the dialog entirely; Generic (Excel/CSV/TSV) re-parses the same file and reopens the table/column picker (sub-tables or columns may have changed since last load), skipping only the file-choice step. Falls back to Open when nothing's loaded yet.

**Cleanup**
- Removed the legacy tkinter GUI (`PhysicsAnalysisGUI.py`) — the PyQt6 version (`run_qt.py`) is now the only supported app. Full tkinter history remains in git log for reference.
- Split `pg_engine.py`'s mouse-interaction code (hover snap, click dispatch, right-click marker menu) into a new `pg_interaction.py`, mirroring the matplotlib engine's existing `plotting.py`/`interaction.py` split.
- Added the missing `pyqtgraph` dependency to `requirements.txt`/`pyproject.toml` — it was already required by the GPU engine (added in v2.1.0) but never listed.

---

## v2.1.0
**New: PyQtGraph (GPU) plot engine**
- The PyQt6 main plot can now render with either matplotlib (CPU) or PyQtGraph (GPU-accelerated), switchable anytime in the new **Options** dialog. Covers pan/zoom, hover snap + coordinate readout, event markers, and rectangle-select zoom. FFT/PETH/Curve Fit/PT2 windows always stay matplotlib-rendered — they open fresh, small figures each time and aren't the performance bottleneck.
- Edit Attributes (title/label text, font sizes, bold toggle, legend show/hide + rename) now applies identically to both engines via the shared `plot_attrs` state.
- Font sizes and plot margins scale to the actual on-screen widget size (shared formula/reference for both engines), so the two engines render at matching proportions and stay correct across window resizes instead of each interpreting a literal point size through a different renderer.
- New "Bold" checkbox in Edit Attributes for title/axis label weight.

**New: Options dialog**
- Default folder for all Open dialogs (now defaults to Desktop instead of the process's working directory, which could land on `System32`).
- Main-plot render decimation: traces are min/max-decimated to the visible x-range on every pan/zoom, independent of dataset size, with a configurable max-points-per-trace setting. Fixes large TDT/Oxysoft recordings making panning unusably slow.
- Background-thread loading for TDT/Oxysoft files (on by default) — keeps the UI responsive during large loads instead of freezing until they finish. Guarded against starting a second load while one is already in flight.

**Bug fixes**
- Fixed a genuine pyqtgraph bug: `setClipToView(True)` crashes `PlotDataItem._getDisplayDataset()` on every redraw (reproduces on a bare `PlotWidget`, all recent pyqtgraph versions, not caused by anything project-specific) — removed it; `setDownsampling` alone still bounds render cost.
- Fixed `PlotItem.setTitle()` hardcoding its title row to a fixed 30px height regardless of font size, which made larger titles overlap the plot area — row height and plot margins now account for the actual title size.
- Fixed the PyQtGraph plot area rendering at a different size than matplotlib's for the same widget size — matplotlib's subplot margins already include room for tick/axis labels, but PyQtGraph's margins are in addition to what its own axes auto-reserve; margins are now measured in two passes so the two engines' actual data areas match.
- Fixed zoom/pan resetting on every redraw (grid toggle, marker add/edit, attribute changes) in both engines — the view now only resets on an actual new dataset or an engine switch, not a same-data redraw.
- Fixed grid toggle visibly flashing/snapping in the PyQtGraph engine — it no longer routes through a full clear+rebuild; it's now a direct `showGrid()`/`ax.grid()` call with nothing else touched.
- Fixed a silent hard crash (process exits with no traceback) when a background load finished: cleanup was dropping the last Python reference to a `QThread` before it had actually finished, which Qt treats as a fatal error rather than a catchable exception.

---

## v2.0.0
**New:**
- `run_qt.py` — full PyQt6 port of the GUI, added alongside the existing tkinter version (`PhysicsAnalysisGUI.py`). Full feature parity: file loading (TDT/Oxysoft/Generic/PT2), blit-based hover/zoom/pan, rect-select zoom, resize-safe zoom, Add/Edit Marker, Edit Attributes, Curve Fit, PETH, FFT, PT2 viewer.
- Golden-ratio font sizing carried over unchanged from v1.3.0 (pure matplotlib logic, framework-agnostic).

**Bug fixes (found during Qt port testing):**
- Fixed a phantom rectangle-selector: double-click → analysis dialog (FFT/PETH) → close, then moving the mouse would draw a selection rectangle following the cursor. `RectangleSelector` never received the button-release event for that click because it was consumed inside the modal dialog's nested event loop. Fixed by deactivating the selector before the dialog opens and deferring reactivation to the next Qt event-loop tick.
- Fixed `launch_fft` crashing with `KeyError: 'corr'` on Generic-source (CSV/Excel) data — it assumed TDT-only cache keys. Falls back to the first Y-column for Generic data. (Pre-existing bug, also present in the tkinter version.)
- Fixed TDT folders and Oxysoft files no longer auto-placing their native event markers on load — the loader was hardcoding `markers: []` instead of using the epoc/event data already returned by `process_tdt_folder()` / `load_dataset_file()`, and the sidecar loader was unconditionally wiping markers to `[]` when no `.markers.json` sidecar existed.

**Known issue:**
- Do not run `run_qt.py` from inside Spyder's console/Run button — Spyder's own UI is built on PyQt5, and loading PyQt6 in the same process causes a `DLL load failed while importing QtWidgets` crash. Edit the file in Spyder as normal, but launch it from a plain terminal (`python run_qt.py`).

Both GUI versions are kept side by side for now; the tkinter version remains the fallback until the Qt version has more real-world use.

---

## v1.3.0
**Improvements:**
- Golden-ratio font sizing: all secondary figure windows (PETH, FFT, PT2 viewer, curve fit) now scale title, axis label, and legend fonts proportionally to the figure diagonal, with each tier related by φ ≈ 1.618.
- Font sizes apply from first load — no longer require opening Edit Attributes first.
- Figures with multiple subplots (PETH, Oxysoft FFT) automatically halve font sizes to avoid crowding.

**Bug fixes:**
- Window resize no longer breaks zoom/scroll: canvas `resize_event` now invalidates the blit background and reschedules a fresh capture.

---

## v1.2.0
**New features:**
- Terranova EFNMR `.pt2` image viewer: opens 2D NMR/MRI images in a dedicated window with colormap selector, editable title, and PNG/PDF/SVG export. Supports all square power-of-two image sizes (16×16 through 256×256) with automatic dimension detection.

**Bug fixes:**
- Scroll zoom no longer snaps back and forth: stale blit background is invalidated immediately on scroll so `on_motion` cannot restore a stale frame before the refresh fires.
- Double-click no longer triggers rect-select zoom: `on_select` now checks `eclick.dblclick` and uses a 10-pixel distance threshold (replaces the 0.1 data-unit threshold that failed on long recordings).
- Marker colour is now editable via right-click → Edit Marker.
- Added black as a marker colour option (matches TDT default).

---

## v1.1.0
**New features:**
- Generic file parser: supports Excel (`.xlsx`), CSV, TSV, and plain text with automatic sub-table detection for side-by-side data layouts.
- Open button consolidated into a single dropdown menu (Open TDT / Open TXT Oxysoft / Open Excel).
- Excel/generic data loads directly into the main GUI plot with full snap and hover support.
- TSI Fit Factor extracted from Oxysoft `.txt` files and displayed as `[FF: x.x%]` in the legend.
- Curve fit parameters can be copied to clipboard or exported as a CSV file.
- Grid toggle checkbox added to the toolbar.
- Marker enhancements: font size and colour editable when adding and via right-click. Colour options: green, red, blue, orange, purple, black.

**Bug fixes and performance:**
- Blit-based hover animation: tracker dots drawn via `restore_region` / `draw_artist` / `blit` instead of `canvas.draw_idle()`, making hover ~20–50× faster.
- Scroll zoom debounced (150 ms) and scale reduced to 1.1× per tick for smoother zooming.
- Tracker dots no longer disappear during scroll zoom; dots no longer cause autoscale zoom.
- Rect-select drag no longer accidentally triggers a curve fit click on release.
- Oxysoft hover snap now correctly targets mean lines (O₂Hb, HHb, tHb) by linewidth filter.
- Edit Attributes changes now persist correctly across all view interactions (zoom, pan, hover).

---

## v1.0.0
- Full GUI with TDT and Oxysoft NIRS support.
- Interactive plot with scroll zoom, right-click pan, and rectangle select zoom.
- Curve fitting, slope analysis, FFT viewer, and PETH/Z-score windows.
- Event markers with colour picker, sidecar save/load.

---

## v0.1.0
- Initial prototype: file parser and basic plotting.
