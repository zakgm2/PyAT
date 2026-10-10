"""
backend/ports.py
----------------
What the app needs from "the analysis code", written from the app's side: these are the only things the windows know about it. Nothing here names
PyATCLI. An implementation (backend/library.py is the real one; a test can bring a fake) supplies them, and a window reaches them through
`backend.api` — it never imports the analysis library itself. A test (tests/test_backend_boundary.py) keeps it that way.

Each port is what one part of the app asks for:

    saved       how what the app edits is saved with a recording: the highlighter's colours, the text tool's default size, a new marker
    recording   a loaded recording as the windows hold it: its signals and their names (and the rules for naming them), where its markers are saved,
                the splice modes
    markers     how event markers are named and tidied
    models      the curve-fit models on offer
    group       Group Analysis: the settings the wizard fills in, the choices it offers, the checks it shows, results rebuilt from their tables
    view        what the main plot shows (its lines, range and markers, as data), which both plot engines and Export View share
    stats       the arithmetic the Event PETH window redoes when trials are ticked or unticked, and what the figures it draws are made of
    outputs     where an export lands under the Output folder

Every port is a Protocol: an object with these members satisfies it, whatever it is made of. Drawing is not behind a port: the figures are the app's
own (physicsanalysis_qt/figures), made from the numbers these ports hand over.
"""

from typing import Any, Mapping, Protocol, Sequence


class GroupSettings(Protocol):
    """Everything the person decides for one group analysis, as the wizard fills it in. The rules for what is valid are the implementation's:
    problems() and window_problems() say what is wrong, in words a person can read."""

    group_name: str
    subjects: list            # [{"subject": name, "folder": path}, ...]
    markers: list
    store_labels: dict
    pre: float
    post: float
    baseline: tuple
    response: tuple
    signal: str
    smooth_seconds: float
    metrics: list
    peak_direction: str
    decay_fraction: float
    correction: str
    alpha: float
    regression_method: str

    def problems(self) -> Sequence[str]: ...
    def window_problems(self) -> Sequence[str]: ...
    def to_dict(self) -> dict: ...


class GroupPort(Protocol):
    settings_filename: str                         # the file a run's settings are saved in, beside its results
    metrics: Sequence[str]                         # the measures a trial gets, in the order they are offered
    metric_labels: Mapping[str, str]
    signals: Sequence[str]                         # what is measured ("dff", "zscore")
    peak_directions: Sequence[str]
    corrections: Sequence[str]                     # multiple-comparison corrections
    correction_labels: Mapping[str, str]

    def new_settings(self, **fields: Any) -> GroupSettings:
        """Settings with every default, except what is given. new_settings() is also how a window reads a default."""

    def default_subject_names(self, folders: Sequence[str], base_path: str) -> list[str]: ...
    def marker_index(self, scans: Sequence[dict]) -> dict: ...
    def design_summary(self, scans: Sequence[dict], markers: Sequence[str], pre: float, post: float) -> dict: ...
    def report_text(self, results: Any) -> str: ...

    def results_from_tables(self, tables: Mapping, parameters: Any = None, notes: Any = None, software: Any = None) -> Any:
        """A finished group analysis's results rebuilt from its tables (and the settings, notes and software no table holds); None if the
        tables are not a group analysis's."""

    def measure_units(self, measure: str, signal: str) -> str:
        """The units a measure is in, as text."""


class SavedPort(Protocol):
    highlight_colors: Mapping[str, str]            # the highlighter's choices: name -> colour
    highlight_alpha: float
    default_text_font_size: int

    def default_marker(self) -> dict:
        """What a marker placed now looks like until the person changes it (a fresh dict each time)."""


class RecordingPort(Protocol):
    splice_cut_out: str                            # the two ways to splice
    splice_keep_inside: str

    def normalized_signal(self, cache: dict) -> tuple:
        """(key, label, trace) of the recording's normalized (dF/F) signal."""

    def current_signal_labels(self, cache: dict) -> dict:
        """{signal key: the name it is shown under}."""

    def apply_signal_labels(self, cache: dict, labels: Mapping[str, str]) -> None:
        """Renames the recording's signals, in place."""

    def marker_sidecar_path(self, source_path: str) -> str:
        """Where the recording's markers are saved."""

    def name_problem(self, final_labels: Mapping[str, str]) -> Any:
        """Why these signal names ({signal key: name}) cannot all be used (None if they can)."""

    def plan_signal_renames(self, cache: dict, renames: Mapping[str, str]) -> dict:
        """{signal key: new name} for what would change; ValueError, with nothing changed, if two would share a name."""


class MarkersPort(Protocol):
    def store_display_name(self, store_id: str, store_labels: Mapping[str, str]) -> str: ...
    def marker_display_label(self, marker: Mapping, store_labels: Mapping[str, str]) -> str: ...
    def group_by_name(self, cache: dict, store_labels: Mapping[str, str] = None) -> dict:
        """{marker name as listed: its times}."""

    def debounce_events(self, times: Sequence[float], min_interval: float) -> list[float]:
        """The times that remain once events closer together than `min_interval` are merged into the first of them."""


class ModelsPort(Protocol):
    def curve_fit_model_names(self) -> list[str]: ...


class PlannedTrace(Protocol):
    """One line of the main plot as the analysis code plans it: what it holds, not how it looks."""

    label: str
    x: Any
    y: Any
    csv_name: str
    y_full: Any
    key: Any
    role: str                                      # what the line is ("signal", "corrected", "o2hb_mean", "column", ...): the app styles it by that
    signal: Any                                    # a TDT signal's key in the recording's signals
    color: Any                                     # the colour the recording itself gives the signal, if it gives one


class ViewPlan(Protocol):
    """What the main plot shows of a recording: its lines, the range, the markers in it — the numbers of an Export View."""

    traces: Sequence[PlannedTrace]
    xlim: tuple
    ylim: Any
    x_name: str
    x: Any
    markers: list
    signals: Any
    show_grid: bool
    title: str
    x_label: str
    y_label: str
    in_view: list
    attributes: dict

    def parameters(self) -> dict: ...
    def data_table(self) -> Any: ...
    def markers_table(self) -> Any: ...
    def write_data(self, base_path: str) -> list[str]: ...


class ViewPort(Protocol):
    def view_traces(self, cache: dict, *, signals: Any = None, active: Any = None) -> tuple:
        """(planned lines, title, x label, y label) the main plot shows for a recording, before any edit of its title, labels or legend."""

    def plan_view(self, cache: dict, **options: Any) -> ViewPlan:
        """The plan of a view. The keywords: signals, active, xlim, ylim, show_grid, store_labels, attributes."""

    def padded_xlim(self, x: Any) -> tuple: ...


class StatsPort(Protocol):
    def auc_from_trace(self, x: Any, y: Any) -> Any: ...
    def auc_matrix(self, time_axis: Any, trial_matrix: Any) -> Any: ...
    def group_stats(self, trial_matrix: Any) -> tuple: ...
    def peri_event_from_trace(self, rel_x: Any, y: Any, post: float, bin_width: float = 1.0) -> Any: ...
    def peri_event_matrix(self, time_axis: Any, trial_matrix: Any, post: float, bin_width: float = 1.0) -> Any: ...
    def find_fft_peaks(self, freqs: Any, power: Any, n_peaks: int = 3) -> list:
        """The top peaks of a power spectrum, as [{"freq_hz", "power", "bpm"}] by power."""

    def bin_for_heatmap(self, z_seg: Any, num_bins: int = 300) -> Any:
        """A signal binned into equal segments for a heatmap."""


class OutputsPort(Protocol):
    source_marker_filename: str

    def group_dir(self, output_folder: str, group_name: str) -> str: ...
    def recording_dir(self, output_folder: str, recording_type: str, recording_source: str) -> str: ...
    def safe_folder_name(self, name: str) -> str: ...
    def unique_path(self, path: str) -> str: ...


class Backend(Protocol):
    saved: SavedPort
    recording: RecordingPort
    markers: MarkersPort
    models: ModelsPort
    group: GroupPort
    view: ViewPort
    stats: StatsPort
    outputs: OutputsPort

    def software_versions(self, app: Mapping[str, str]) -> dict:
        """The versions the error log starts with: the app (given), the analysis code, Python, the OS, the numerical libraries."""
