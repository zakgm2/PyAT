"""
analysis/group/output.py
--------------------------
Where a group analysis saves its files: a "Group Analysis" folder alongside the per-data-type ones
(outputs.py) inside the output location (Options -> Output folder), with a folder named after the
group inside that. If no output location is set, the person is asked for one, the same way
single-recording exports fall back to a save dialog.

A group name that was already run gets " (2)", " (3)", ... instead of overwriting the earlier run —
resolve_group_dir() only ever hands back a folder that has no analysis_settings.json in it yet, so
there is nothing for the wizard to ask about replacing.
"""

import json
import os
from datetime import datetime

from PyQt6.QtWidgets import QFileDialog

import PhysicsLibrary as pl

from ... import __version__
from ...context import get_export_dir
from ...outputs import output_base, safe_folder_name

SETTINGS_FILENAME = "analysis_settings.json"


def resolve_group_dir(ctx, parent, group_name):
    """<output location>/Group Analysis/<group name>[ (n)], or None if the person backs out of
    choosing a location. With no output location set they are asked for one now (starting where
    exports start).

    A group name already used for a finished run gets " (2)", " (3)", ... instead: this always
    returns a folder with no analysis_settings.json in it yet, so a run can never overwrite an
    earlier one just because the group was named (or renamed back to) the same thing."""
    folder = safe_folder_name(group_name)
    if not folder:
        return None
    base = output_base(ctx)
    if base is None:
        base = QFileDialog.getExistingDirectory(parent, "Where should the group results be saved?",
                                                get_export_dir(ctx))
        if not base:
            return None
    type_dir = os.path.join(base, "Group Analysis")
    candidate, n = folder, 2
    while os.path.exists(os.path.join(type_dir, candidate, SETTINGS_FILENAME)):
        candidate = f"{folder} ({n})"
        n += 1
    return os.path.join(type_dir, candidate)


def write_settings(group_dir, spec, scans):
    """Writes the group's analysis settings (the spec, and a summary of each recording used) to
    <group_dir>/analysis_settings.json, creating the folder; returns the file's path."""
    included = {s["folder"] for s in spec.subjects}
    recordings = []
    for sc in scans:
        if sc["folder"] not in included:
            continue
        subject = next(s["subject"] for s in spec.subjects if s["folder"] == sc["folder"])
        recordings.append({
            "subject": subject, "folder": sc["folder"], "block_name": sc["block_name"],
            "start_time": sc["start_time"], "events_per_marker": {m: len(t) for m, t in sc["groups"].items()},
            "saved_splices_applied": sc["n_splices"], "saved_markers": sc["n_saved_markers"],
        })
    doc = {
        "app": {"name": "PyAT", "version": __version__, "library_version": pl.__version__},
        "created": datetime.now().isoformat(timespec="seconds"),
        "spec": spec.to_dict(),
        "recordings": recordings,
    }
    os.makedirs(group_dir, exist_ok=True)
    path = os.path.join(group_dir, SETTINGS_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
    return path
