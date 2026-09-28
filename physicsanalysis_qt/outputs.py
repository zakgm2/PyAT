"""
outputs.py
----------
Where an export lands once the user has set an Output folder (Options): a folder per data type,
and inside it a folder per recording, so a recording's CSVs/figures/reports accumulate together
across reloads and sessions instead of a growing flat pile of similar-looking filenames. See
context.py's export_file() — the one function every export in the app funnels through, and the
only caller of recording_dir() below.

    <Output>/
      TDT/<recording name>/...
      Oxysoft/<recording name>/...
      Generic/<recording name>/...
      PT2/<recording name>/...
      Text Field Study/<study folder name>/...
      Group Analysis/<group name>/...          (its own resolver, analysis/group/output.py,
                                                 which reuses safe_folder_name/output_base below)

A recording's folder name is its own basename (a file's, without the extension) plus " (Analysis)"
— not ctx.cache['store'], which grows a "[cut ...]" tag every time it is spliced
(analysis/splice.py); keying off that would split one recording's exports across a new folder each
time it changes. The " (Analysis)" suffix is deliberate: without it, an export folder can end up
named identically to the real recording folder/file sitting right next to it, and it's too easy to
mistake one for the other (and e.g. delete or overwrite real data thinking it's disposable output).

Nothing written through export_file() ever silently overwrites an earlier export, either: see
unique_path() below, which every write goes through when its destination is auto-resolved (no save
dialog) — a repeat export gets " (2)", " (3)", ... instead of replacing the last one.

If a name collision would put two DIFFERENT recordings in the same folder — two different subjects
both called "Day1" in different parent folders, say, which genuinely happens (see loaders/tdt.py's
own _find_tdt_subfolders docstring) — the second one gets " (2)" instead: a small marker file inside
each folder (SOURCE_MARKER_FILENAME) records which absolute source path it belongs to, checked
before an existing folder is reused. Nothing here moves or migrates exports made before this existed;
new exports simply start landing in the nested folders.
"""

import json
import os
from datetime import datetime

SOURCE_MARKER_FILENAME = ".pyat_source.json"

_INVALID_CHARS = '<>:"/\\|?*'
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_MAX_LENGTH = 100


def safe_folder_name(name):
    """`name` as a folder name Windows will accept: characters it disallows become "_", surrounding
    spaces and trailing dots are dropped, and a reserved device name (CON, NUL, ...) gets a "_" in
    front. Returns "" if nothing usable is left."""
    cleaned = "".join("_" if (c in _INVALID_CHARS or ord(c) < 32) else c for c in str(name)).strip()
    cleaned = cleaned[:_MAX_LENGTH].rstrip(". ")
    if not cleaned:
        return ""
    if cleaned.split(".")[0].upper() in _RESERVED:
        cleaned = "_" + cleaned
    return cleaned


def output_base(ctx):
    """The Output folder from Options, or None if it is unset (or no longer exists)."""
    base = ctx.settings.get("output_folder")
    return base if base and os.path.isdir(base) else None


def _recording_name(source_path):
    """The folder/file's own basename — a file's without its extension, so "MyFile.xlsx" and a
    same-named "MyFile.csv" opened another day still share one folder — plus " (Analysis)", so the
    export folder never reads as the recording itself (see the module docstring)."""
    stripped = source_path.rstrip("/\\")
    base = os.path.basename(stripped)
    if os.path.isfile(source_path):
        base = os.path.splitext(base)[0]
    return f"{base} (Analysis)"


def unique_path(path):
    """`path`, or the same name with " (2)", " (3)", ... inserted before the extension if something
    is already there — so a repeat export never silently replaces an earlier one. Only meant for the
    auto-resolved (no save dialog) path in export_file(); a save dialog already asks before
    replacing an existing file on its own."""
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    n = 2
    while True:
        candidate = f"{root} ({n}){ext}"
        if not os.path.exists(candidate):
            return candidate
        n += 1


def _normalize(source_path):
    """So the same recording resolves to the same folder however it is re-opened (different
    relative path, different case on a case-insensitive filesystem, a trailing slash, ...)."""
    return os.path.normcase(os.path.normpath(os.path.abspath(source_path)))


def _read_marker_source(marker_path):
    try:
        with open(marker_path, "r", encoding="utf-8") as f:
            return json.load(f).get("source_path")
    except (OSError, ValueError):
        return None


def _write_marker(marker_path, data_type, source_path):
    try:
        with open(marker_path, "w", encoding="utf-8") as f:
            json.dump({"type": data_type, "source_path": source_path,
                      "created": datetime.now().isoformat(timespec="seconds")}, f, indent=2)
    except OSError:
        pass                                    # exports still work without it; just no collision protection this time


def recording_dir(base, data_type, source_path):
    """<base>/<data_type>/<name>[ (n)]/ for one recording, auto-disambiguated: creates the folder
    (and its parents) the first time, and reuses the same one on every later call for the same
    source_path — including across separate app runs, via SOURCE_MARKER_FILENAME. A different
    recording that happens to share a name gets "name (2)", "name (3)", ... instead of mixing in.

    Parameters
    ----------
    base : str
        The Output folder itself (already known to exist — see output_base()).
    data_type : str
        "TDT", "Oxysoft", "Generic", "PT2" or "Text Field Study" today; used as the top-level
        subfolder name (through safe_folder_name, so a caller can pass it unsanitised).
    source_path : str
        The recording's own path, exactly as ctx.cache['source_path'] (or the loader's own path
        attribute, for PT2/the text field study tools) holds it.
    """
    name = safe_folder_name(_recording_name(source_path)) or "Untitled (Analysis)"
    type_dir = os.path.join(base, safe_folder_name(data_type) or "Other")
    norm_source = _normalize(source_path)

    candidate, n = name, 1
    while True:
        folder = os.path.join(type_dir, candidate)
        marker = os.path.join(folder, SOURCE_MARKER_FILENAME)
        if not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)
            _write_marker(marker, data_type, source_path)
            return folder
        existing = _read_marker_source(marker)
        if existing is None or _normalize(existing) == norm_source:
            if existing is None:                # a folder that predates this marker (or one made by hand) — claim it
                _write_marker(marker, data_type, source_path)
            return folder
        n += 1
        candidate = f"{name} ({n})"
