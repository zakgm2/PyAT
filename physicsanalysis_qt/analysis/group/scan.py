"""
analysis/group/scan.py
------------------------
Finds out what each recording of a group contains — its event markers and how
long it is — without processing the signal, so the setup dialog can list the
markers the recordings share before anything slow happens.

A recording's markers are built the way the single-recording analyses build
them: the events TDT detected (with the recording's saved splices applied, as
PyAT does when it restores splice.json) plus any markers saved next to it
(JSON saves/markers.json), grouped by name with the same function Event PETH
uses. Nothing here touches a widget, so it runs on a worker thread.
"""

import json
import os
from types import SimpleNamespace

import PhysicsLibrary as pl

from ...sidecar import _legacy_sidecar_path, sidecar_path
from ..event_peth import _group_markers_by_name
from ..splice import splice_sidecar_path


def default_subject_names(folders, base_path):
    """One subject name per recording: the recording's own folder name (Synapse's
    Subject-YYMMDD-HHMMSS). Two recordings that share a folder name (in different
    subfolders) get their path from the searched folder on, so names start out unique."""
    names = [os.path.basename(f.rstrip("/\\")) for f in folders]
    out = []
    for f, n in zip(folders, names):
        out.append(n if names.count(n) == 1 else os.path.relpath(f, base_path).replace("\\", "/"))
    return out


def read_saved_splices(folder):
    """The recording's saved splices, in the order they were applied ([] if none). Accepts the
    current list format and the old single-splice dict, like the loader does."""
    path = splice_sidecar_path(SimpleNamespace(cache={"source_path": folder}))
    if not path or not os.path.exists(path):
        return []
    with open(path, "r") as f:
        saved = json.load(f)
    return [saved] if isinstance(saved, dict) else list(saved)


def read_saved_markers(folder):
    """The markers saved for the recording (JSON saves/markers.json, else the older sibling
    <folder>.markers.json); [] if there are none. Same lookup as the loader's restore."""
    shim = SimpleNamespace(cache={"source_path": folder})
    path = sidecar_path(shim)
    if not path or not os.path.exists(path):
        path = _legacy_sidecar_path(shim)
    if not path or not os.path.exists(path):
        return []
    with open(path, "r") as f:
        saved = json.load(f)
    if not isinstance(saved, list):
        raise ValueError("markers.json does not hold a list of markers")
    return saved


def scan_recording(folder, base_path, store_labels=None, progress=None):
    """
    What one recording contains, ready for the setup dialog.

    Returns a dict with
        folder, name (its folder name), label (path from the searched folder),
        groups      {marker name: sorted event times} — every event the single-recording
                    analyses would offer, under the same names
        t_range     (first, last sample time) after any saved splices, or None
        n_events, n_splices (applied), n_splices_saved, n_saved_markers,
        block_name, start_time, warnings (things skipped, in words), error (None, or why the
        recording could not be read at all — then `groups` is empty).
    """
    result = {
        "folder": folder,
        "name": os.path.basename(folder.rstrip("/\\")),
        "label": os.path.relpath(folder, base_path).replace("\\", "/"),
        "groups": {}, "t_range": None, "n_events": 0,
        "n_splices": 0, "n_splices_saved": 0, "n_saved_markers": 0,
        "block_name": None, "start_time": None, "warnings": [], "error": None,
    }
    try:
        valid, message = pl.validate_tdt_folder(folder)
        if not valid:
            raise ValueError(message)
        splices = []
        try:
            splices = read_saved_splices(folder)
        except Exception as e:
            result["warnings"].append(f"Saved splices could not be read ({e}); the recording is used as recorded.")
        result["n_splices_saved"] = len(splices)

        scan = pl.scan_tdt_markers(folder, splices=splices or None, progress=progress)

        saved = []
        try:
            saved = read_saved_markers(folder)
        except Exception as e:
            result["warnings"].append(f"Saved markers could not be read ({e}); only the recorded events are used.")

        shim = SimpleNamespace(cache={"detected_markers": scan["markers"], "markers": saved},
                               store_labels=dict(store_labels or {}))
        groups = _group_markers_by_name(shim)
        result.update(groups=groups, t_range=scan["t_range"], n_events=sum(len(t) for t in groups.values()),
                      n_splices=scan["n_splices"], n_saved_markers=len(saved),
                      block_name=scan["block_name"], start_time=scan["start_time"])
    except Exception as e:
        result["error"] = str(e) or type(e).__name__
    return result


def scan_recordings(folders, base_path, store_labels=None, progress=None):
    """scan_recording for each folder, in order, one step of `progress` per recording. A recording
    that cannot be read comes back with its `error` set instead of stopping the rest."""
    plan = pl.Plan(progress, [(f"rec{i}", 1) for i in range(len(folders))])
    out = []
    for i, folder in enumerate(folders):
        name = os.path.basename(folder.rstrip("/\\"))
        plan.begin(f"rec{i}", f"Scanning {name} ({i + 1} of {len(folders)})")
        out.append(scan_recording(folder, base_path, store_labels))
    plan.done()
    return out
