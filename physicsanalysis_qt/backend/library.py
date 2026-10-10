"""
backend/library.py
------------------
The real implementation of backend/ports.py: it answers each of the app's questions with PyATCLI. This is the module that knows what the
analysis code is called and where things are in it — when the library renames or moves something, this is the file to change, and a window
never notices. (backend/engine_client.py and recordings.py also touch the library, for the engine's own pipes and arrays; they are the other
half of the same boundary.)

Where the library's own type is the right thing to hand back (the group settings, which carry the rules for what is valid), it is handed back
as the port's type: the app uses it through that interface and never by its library name.
"""

import PyATCLI as pl
from PyATCLI import outputs as _outputs
from PyATCLI import viewplan as _viewplan
from PyATCLI.analysis import group as _group
from PyATCLI.analysis.group import rebuild as _rebuild
from PyATCLI.analysis.group import report as _report


class _Saved:
    highlight_colors = pl.saved_state.HIGHLIGHT_COLORS
    highlight_alpha = pl.saved_state.HIGHLIGHT_ALPHA
    default_text_font_size = pl.saved_state.DEFAULT_TEXT_FONT_SIZE

    def default_marker(self):
        return dict(pl.saved_state.DEFAULT_MARKER)


class _Recording:
    splice_cut_out = pl.MODE_CUT_OUT
    splice_keep_inside = pl.MODE_KEEP_INSIDE

    def normalized_signal(self, cache):
        return pl.normalized_signal(cache)

    def current_signal_labels(self, cache):
        return pl.current_signal_labels(cache)

    def apply_signal_labels(self, cache, labels):
        pl.apply_signal_labels(cache, labels)

    def marker_sidecar_path(self, source_path):
        return pl.marker_sidecar_path(source_path)

    def name_problem(self, final_labels):
        return pl.recording.name_problem(final_labels)

    def plan_signal_renames(self, cache, renames):
        return pl.recording.plan_signal_renames(cache, renames)


class _Markers:
    def store_display_name(self, store_id, store_labels):
        return pl.store_display_name(store_id, store_labels)

    def marker_display_label(self, marker, store_labels):
        return pl.marker_display_label(marker, store_labels)

    def debounce_events(self, times, min_interval):
        return pl.debounce_events(times, min_interval)

    def group_by_name(self, cache, store_labels=None):
        return pl.group_markers_by_name(cache, store_labels)


class _Models:
    def curve_fit_model_names(self):
        return list(pl.CURVE_FIT_MODELS)


class _Group:
    settings_filename = pl.GROUP_SETTINGS_FILENAME
    metrics = _group.METRICS
    metric_labels = _group.METRIC_LABELS
    signals = _group.SIGNALS
    peak_directions = _group.PEAK_DIRECTIONS
    corrections = _group.CORRECTIONS
    correction_labels = _group.CORRECTION_LABELS

    def new_settings(self, **fields):
        return _group.GroupSpec(**fields)

    def default_subject_names(self, folders, base_path):
        return pl.default_subject_names(folders, base_path)

    def marker_index(self, scans):
        return pl.marker_index(scans)

    def design_summary(self, scans, markers, pre, post):
        return pl.design_summary(scans, markers, pre, post)

    def report_text(self, results):
        return pl.group_report_text(results)

    def results_from_tables(self, tables, parameters=None, notes=None, software=None):
        return _rebuild.results_from_tables(tables, parameters, notes=notes, software=software)

    def measure_units(self, measure, signal):
        return _report.measure_units(measure, signal)


class _View:
    def view_traces(self, cache, *, signals=None, active=None):
        return _viewplan.view_traces(cache, signals=signals, active=active)

    def plan_view(self, cache, **options):
        return _viewplan.plan_view(cache, **options)

    def padded_xlim(self, x):
        return _viewplan.padded_xlim(x)


class _Stats:
    def auc_from_trace(self, x, y):
        return pl.compute_auc_from_trace(x, y)

    def auc_matrix(self, time_axis, trial_matrix):
        return pl.compute_auc_matrix(time_axis, trial_matrix)

    def group_stats(self, trial_matrix):
        return pl.compute_group_stats(trial_matrix)

    def peri_event_from_trace(self, rel_x, y, post, bin_width=1.0):
        return pl.compute_peri_event_from_trace(rel_x, y, post, bin_width)

    def peri_event_matrix(self, time_axis, trial_matrix, post, bin_width=1.0):
        return pl.compute_peri_event_matrix(time_axis, trial_matrix, post, bin_width)

    def find_fft_peaks(self, freqs, power, n_peaks=3):
        return pl.find_fft_peaks(freqs, power, n_peaks=n_peaks)

    def bin_for_heatmap(self, z_seg, num_bins=300):
        return pl.bin_for_heatmap(z_seg, num_bins)


class _Outputs:
    source_marker_filename = _outputs.SOURCE_MARKER_FILENAME

    def group_dir(self, output_folder, group_name):
        return _outputs.group_dir(output_folder, group_name)

    def recording_dir(self, output_folder, recording_type, recording_source):
        return _outputs.recording_dir(output_folder, recording_type, recording_source)

    def safe_folder_name(self, name):
        return _outputs.safe_folder_name(name)

    def unique_path(self, path):
        return _outputs.unique_path(path)


class PyATCLIBackend:
    """backend/ports.Backend, answered by PyATCLI."""

    def __init__(self):
        self.saved = _Saved()
        self.recording = _Recording()
        self.markers = _Markers()
        self.models = _Models()
        self.group = _Group()
        self.view = _View()
        self.stats = _Stats()
        self.outputs = _Outputs()

    def software_versions(self, app):
        return pl.software_versions(dict(app))
