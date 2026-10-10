"""A backend (backend/ports.py) that is not PyATCLI: small, deterministic, in memory. A window that works with it is one that asks only the
interface. Use it with `backend.use(FakeBackend())` and put the previous one back afterwards."""

import os
from dataclasses import dataclass, field

import numpy as np


@dataclass
class FakeGroupSettings:
    group_name: str = ""
    subjects: list = field(default_factory=list)
    markers: list = field(default_factory=list)
    store_labels: dict = field(default_factory=dict)
    pre: float = 5.0
    post: float = 5.0
    baseline: tuple = (-5.0, -1.0)
    response: tuple = (0.0, 5.0)
    signal: str = "dff"
    smooth_seconds: float = 0.0
    metrics: list = field(default_factory=lambda: ["auc", "peak"])
    peak_direction: str = "positive"
    decay_fraction: float = 0.5
    correction: str = "holm"
    alpha: float = 0.05
    regression_method: str = "ols"

    def problems(self):
        return ["Name the group."] if not self.group_name else []

    def window_problems(self):
        return ["The window must be longer than the baseline."] if self.pre <= 0 else []

    def to_dict(self):
        return dict(self.__dict__)


class _Saved:
    highlight_colors = {"Fake": "#123456"}
    highlight_alpha = 0.5
    default_text_font_size = 11

    def default_marker(self):
        return {"label": "fake", "color": "#000000"}


class _Recording:
    splice_cut_out = "fake_cut"
    splice_keep_inside = "fake_keep"

    def normalized_signal(self, cache):
        return "normalized", "Fake signal", cache.get("y")

    def current_signal_labels(self, cache):
        return dict(cache.get("labels", {}))

    def apply_signal_labels(self, cache, labels):
        cache.setdefault("labels", {}).update(labels)

    def marker_sidecar_path(self, source_path):
        return source_path + ".fake-markers"

    def name_problem(self, final_labels):
        names = list(final_labels.values())
        for name in names:
            if names.count(name) > 1:
                return f"Two signals can't both be called {name!r}."
        return None

    def plan_signal_renames(self, cache, renames):
        return dict(renames)


class _Markers:
    def store_display_name(self, store_id, store_labels):
        return store_labels.get(store_id, store_id)

    def marker_display_label(self, marker, store_labels):
        return "fake:" + str(marker.get("label", ""))

    def debounce_events(self, times, min_interval):
        kept = []
        for t in times:
            if not kept or t - kept[-1] >= min_interval:
                kept.append(t)
        return kept

    def group_by_name(self, cache, store_labels=None):
        return {}


class _Models:
    def curve_fit_model_names(self):
        return ["Fake line", "Fake curve"]


class _Group:
    settings_filename = "fake_settings.json"
    metrics = ("auc", "peak")
    metric_labels = {"auc": "Fake AUC", "peak": "Fake peak"}
    signals = ("dff", "zscore")
    peak_directions = ("positive", "negative")
    corrections = ("holm",)
    correction_labels = {"holm": "Fake Holm"}

    def new_settings(self, **fields):
        return FakeGroupSettings(**fields)

    def default_subject_names(self, folders, base_path):
        return [f"S{i + 1}" for i, _ in enumerate(folders)]

    def marker_index(self, scans):
        return {}

    def design_summary(self, scans, markers, pre, post):
        return {"subjects": [], "markers": list(markers)}

    def report_text(self, results):
        return "fake report"

    def results_from_tables(self, tables, parameters=None, notes=None, software=None):
        if "mean_traces" not in tables and "subject_means" not in tables:
            return None
        return {"tables": tables, "parameters": parameters}

    def measure_units(self, measure, signal):
        return "units"


class _FakeTrace:
    def __init__(self, label, x, y):
        self.label, self.x, self.y, self.csv_name, self.y_full = label, x, y, label, y
        self.key, self.role, self.signal, self.color = label, "signal", "normalized", None


class _FakePlan:
    def __init__(self, cache, **options):
        x = np.asarray(cache["x"])
        self.traces = [_FakeTrace("Fake", x, x)]
        self.xlim, self.ylim, self.x_name, self.x, self.markers, self.signals = (float(x[0]), float(x[-1])), None, "time_s", x, [], None
        self.show_grid, self.title, self.x_label, self.y_label, self.in_view = True, "Fake", "Time (s)", "Signal", []
        self.attributes = dict(options.get("attributes") or {})

    def parameters(self):
        return {"x_range": list(self.xlim), "y_range": None, "signals": None, "show_grid": True, "attributes": self.attributes, "traces": ["Fake"]}

    def data_table(self):
        return None

    def markers_table(self):
        return None

    def write_data(self, base_path):
        return []


class _View:
    def view_traces(self, cache, *, signals=None, active=None):
        return _FakePlan(cache).traces, "Fake", "Time (s)", "Signal"

    def plan_view(self, cache, **options):
        return _FakePlan(cache, **options)

    def padded_xlim(self, x):
        lo, hi = float(np.min(x)), float(np.max(x))
        pad = 0.02 * (hi - lo)
        return lo - pad, hi + pad


class _Stats:
    def auc_from_trace(self, x, y):
        total = float(np.trapezoid(y, x))
        return {"total_auc": total, "positive_auc": max(total, 0.0), "negative_auc": min(total, 0.0)}

    def auc_matrix(self, time_axis, trial_matrix):
        return [self.auc_from_trace(time_axis, row) for row in trial_matrix]

    def group_stats(self, trial_matrix):
        m = np.asarray(trial_matrix, dtype=float)
        n = m.shape[0]
        return m.mean(axis=0), (m.std(axis=0, ddof=1) / np.sqrt(n) if n > 1 else np.zeros(m.shape[1]))

    def peri_event_from_trace(self, rel_x, y, post, bin_width=1.0):
        return []

    def peri_event_matrix(self, time_axis, trial_matrix, post, bin_width=1.0):
        return []

    def find_fft_peaks(self, freqs, power, n_peaks=3):
        return []

    def bin_for_heatmap(self, z_seg, num_bins=300):
        return np.asarray(z_seg, dtype=float)


class _Outputs:
    source_marker_filename = ".fake_source.json"

    def safe_folder_name(self, name):
        return "".join("_" if c in '\\/:*?"<>|' else c for c in name).strip() or "unnamed"

    def group_dir(self, output_folder, group_name):
        return os.path.join(output_folder, "Group Analysis", self.safe_folder_name(group_name))

    def recording_dir(self, output_folder, recording_type, recording_source):
        return os.path.join(output_folder, recording_type, os.path.basename(str(recording_source)) + " (Analysis)")

    def unique_path(self, path):
        base, ext = os.path.splitext(path)
        candidate, n = path, 1
        while os.path.exists(candidate):
            n += 1
            candidate = f"{base} ({n}){ext}"
        return candidate


class FakeBackend:
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
        return {"python": "fake", "implementation": "fake", "bits": 64, "platform": "fake", "frozen": False, "library": "fake",
                "packages": {}, "app": dict(app)}
