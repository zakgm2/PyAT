"""
export/outputs.py
-----------------
Where an export lands once the user has set an Output folder (Options): a folder per data type, and inside it a folder per
recording, so a recording's CSVs/figures/reports accumulate together across reloads and sessions instead of a growing flat
pile of similar-looking filenames. See context.py's export_file() — the one function every export in the app funnels
through, and the only caller of recording_dir() below.

The layout and every rule in it (the " (Analysis)" suffix, the marker file that tells two recordings of one name apart,
" (2)" instead of overwriting) are PyATCLI's (outputs.py) — the command line writes into the same folders with
`--output-folder`, so a recording analysed from a script and in the app ends up in one place. What is the app's is the
setting that names the folder:

    <Output>/
      TDT/<recording name> (Analysis)/...
      Oxysoft/...  Generic/...  PT2/...  Text Field Study/...
      Group Analysis/<group name>/...          (analysis/group/output.py)
"""

import os

from ..backend import api

SOURCE_MARKER_FILENAME = api.outputs.source_marker_filename


def group_dir(output_folder, group_name):
    return api.outputs.group_dir(output_folder, group_name)


def recording_dir(output_folder, recording_type, recording_source):
    return api.outputs.recording_dir(output_folder, recording_type, recording_source)


def safe_folder_name(name):
    return api.outputs.safe_folder_name(name)


def unique_path(path):
    return api.outputs.unique_path(path)

__all__ = ["SOURCE_MARKER_FILENAME", "group_dir", "output_base", "recording_dir", "safe_folder_name", "unique_path"]


def output_base(ctx):
    """The Output folder from Options, or None if it is unset (or no longer exists)."""
    base = ctx.settings.get("output_folder")
    return base if base and os.path.isdir(base) else None
