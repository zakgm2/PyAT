"""
fieldstudy/config.py
--------------------
Local configuration for the generic text-field-study feature (see
fieldstudy/open_study.py, PyATCLI.run_field_study_pipeline).

Which fields exist, how they're grouped, and which pair up is entirely
study-specific — so none of that lives in this repo's source. It's
stored in a small JSON file in the user's home directory instead,
completely outside any git repo. Built via FieldAssignmentDialog (shown
right after picking a study folder, using that folder's own field
names) rather than requiring the fields to already be known/typed
anywhere first; saved here so the next folder you open pre-fills from it.
"""

import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".physicsanalysis" / "text_field_study_config.json"


def load_config():
    """Returns the saved config dict, or None if none has been saved yet."""
    if not CONFIG_PATH.exists():
        return None
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save_config(config):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
