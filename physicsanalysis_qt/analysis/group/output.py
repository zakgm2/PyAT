"""
analysis/group/output.py
--------------------------
Where a group analysis saves its files: a "Group Analysis" folder alongside the per-data-type ones
(outputs.py, which is PyATCLI's) inside the output location (Options -> Output folder), with a folder named after the
group inside that. If no output location is set, the person is asked for one, the same way
single-recording exports fall back to a save dialog. (The settings file written into that folder is
PyATCLI.write_group_settings.)

A group name that was already run gets " (2)", " (3)", ... instead of overwriting the earlier run —
resolve_group_dir() only ever hands back a folder that has no analysis_settings.json in it yet, so
there is nothing for the wizard to ask about replacing.
"""

from PyQt6.QtWidgets import QFileDialog

from ...context import get_export_dir
from ...export.outputs import group_dir, output_base, safe_folder_name


def resolve_group_dir(ctx, parent, group_name):
    """<output location>/Group Analysis/<group name>[ (n)], or None if the person backs out of
    choosing a location. With no output location set they are asked for one now (starting where
    exports start).

    A group name already used for a finished run gets " (2)", " (3)", ... instead: this always
    returns a folder with no analysis_settings.json in it yet, so a run can never overwrite an
    earlier one just because the group was named (or renamed back to) the same thing."""
    if not safe_folder_name(group_name):
        return None
    base = output_base(ctx)
    if base is None:
        base = QFileDialog.getExistingDirectory(parent, "Where should the group results be saved?",
                                                get_export_dir(ctx))
        if not base:
            return None
    return group_dir(base, group_name)                       # PyATCLI.outputs: "Group Analysis/<name>", " (2)" if used
