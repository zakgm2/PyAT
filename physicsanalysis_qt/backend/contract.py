"""
backend/contract.py
-------------------
What this app needs of the analysis engine, and the check it makes when the engine says hello.

The engine (`python -m PyATCLI serve`) is a program of its own, and the library that provides it can be newer or older than the app that
asks it things. When it starts it says which protocol it speaks and which operations it has (its `ready` message); the engine's side of this is
PyATCLI's ENGINE_CONTRACT.json (what a caller can count on) and ops.PROTOCOL_VERSION (raised when something a caller could rely on goes).

    SUPPORTED_PROTOCOLS   the protocol numbers this app speaks
    OPERATIONS_USED       every operation the app asks for (tests/test_engine_contract.py keeps this list equal to what the code asks)
    TABLES_READ           the tables the analysis windows read, and the columns they read from each: all of them must be among the columns the
                          analysis says are always there (the test checks that against the library that is installed)
    OUTPUTS_READ          the same for what is written besides an analysis's tables, which Open Results reads back (a group analysis's folder)
    RESULTS_READ          the keys of each operation's answer the app reads, which the operation must promise
    CACHE_KEYS_READ       the keys of a loaded recording the app reads, which the library must promise for that kind of recording (the app's own
                          additions to it, the highlights and text boxes, are APP_CACHE_KEYS)
    check_ready(ready)    None if the engine fits this app; otherwise (message, hint) for the person

An engine that does not fit is not used: every request fails with the message (code "incompatible_engine"), rather than something odd happening
when a window asks for a table that is no longer there.
"""

SUPPORTED_PROTOCOLS = (1,)

OPERATIONS_USED = (
    "compute.event_peth",
    "compute.peaks",
    "fieldstudy.fields",
    "fieldstudy.run",
    "fieldstudy.validate",
    "file.tables",
    "files.inspect",
    "group.run",
    "group.scan",
    "provenance.write",
    "pt2.load",
    "recording.close",
    "recording.open",
    "recording.splice",
    "recording.view",
    "results.open",
    "run",
    "saved.clear",
    "saved.write",
)

TABLES_READ = {
    "zscore_window": {
        "window": ["Channel", "time_from_center_s", "z_score"],
        "peaks": ["Channel", "Peak Z-score", "Peak time from center (s)"],
    },
    "auc_window": {
        "auc": ["Channel", "Total AUC", "Positive AUC", "Negative AUC"],
        "window": ["Channel", "time_from_center_s", "value"],
    },
    "fft_window": {
        "peaks": ["Channel", "Frequency (Hz)", "BPM", "Power"],
        "spectrum": ["Channel", "frequency_hz", "power"],
    },
    "curve_fit": {
        "fit": ["Channel", "Parameter", "Value", "R2"],
        "curve": ["Channel", "time_s", "value", "fit"],
        "context": ["Channel", "time_s", "value"],
    },
    "event_intervals": {
        "intervals": ["time_s", "store", "label", "phase", "dt_since_prev_same_store_s", "dt_since_prev_any_s"],
    },
}


OUTPUTS_READ = {
    "group_analysis": {                                  # without these two a group's results have nothing to draw; the other tables are shown when there
        "mean_traces": ["marker", "subject", "n_trials", "time", "value"],
        "subject_means": ["subject", "marker", "measure", "n", "mean"],
    },
}


RESULTS_READ = {
    "recording.open": ["id", "path", "cache", "directory", "original_cache", "splices", "signal_labels", "restored", "warnings", "regression_method"],
    "recording.view": ["cache", "directory", "splices"],
    "recording.splice": ["cache", "directory", "splices"],
    "files.inspect": ["valid", "recordings"],
    "file.tables": ["tables"],
    "pt2.load": ["image"],
    "results.open": ["directory", "files", "kind", "notes", "parameters", "software", "tables"],
    "saved.write": ["files"],
    "compute.event_peth": ["result"],
    "run": ["tables", "summary", "notes"],
    "group.run": ["table_data", "spec", "note_records", "software", "files"],
    "group.scan": ["scans"],
    "fieldstudy.fields": ["fields"],
    "fieldstudy.run": ["tables"],
    "fieldstudy.validate": ["tables"],
}

CACHE_KEYS_READ = {
    "always": ["x", "fs", "source", "source_path", "store", "markers"],
    "TDT": ["signals", "corr", "raw", "detected_markers", "motion_correction_inlier_fraction"],
}
APP_CACHE_KEYS = ("highlights", "text_annotations")           # put on a recording by the app's own editing tools (and its saved state)


def check_ready(ready):
    """None if the engine that sent this `ready` message fits this app; otherwise (message, hint)."""
    protocol = ready.get("protocol")
    library = ready.get("library") or "unknown version"
    if protocol not in SUPPORTED_PROTOCOLS:
        speaks = ", ".join(str(p) for p in SUPPORTED_PROTOCOLS)
        return (f"This PyAT speaks the analysis engine's protocol {speaks}, but the PyATCLI it started ({library}) speaks "
                f"protocol {protocol}.",
                "Use the PyATCLI that goes with this PyAT (pip install --upgrade PyATCLI), or the PyAT that goes with this library.")
    missing = sorted(set(OPERATIONS_USED) - set(ready.get("operations") or []))
    if missing:
        return (f"The PyATCLI this PyAT started ({library}) cannot do what PyAT asks of it: it has no operation "
                f"{', '.join(missing)}.",
                "Use the PyATCLI that goes with this PyAT (pip install --upgrade PyATCLI), or the PyAT that goes with this library.")
    return None
