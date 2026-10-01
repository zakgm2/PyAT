"""
sidecar.py
----------
Marker persistence: a `.markers.json` file saved next to the loaded
data file/folder.
"""

import json
import os

from .toasts import show_error, show_window_toast


def _legacy_sidecar_path(ctx):
    """Pre-JSON-saves-folder location: a sibling file next to the raw
    data folder/file, e.g. <FolderPath>.markers.json. Kept read-only for
    loading sidecars saved before markers moved into a JSON saves/
    subfolder, so old studies don't lose their saved markers."""
    if ctx.cache is None or not ctx.cache.get('source_path'):
        return None
    return ctx.cache['source_path'] + ".markers.json"


def sidecar_path(ctx):
    if ctx.cache is None or not ctx.cache.get('source_path'):
        return None
    source = ctx.cache['source_path']
    if os.path.isdir(source):
        json_dir = os.path.join(source, "JSON saves")
        return os.path.join(json_dir, "markers.json")
    json_dir = os.path.join(os.path.dirname(source), "JSON saves")
    return os.path.join(json_dir, os.path.basename(source) + ".markers.json")


def save_markers(ctx):
    if ctx.cache is None:
        return
    path = sidecar_path(ctx)
    if not path:
        show_error(ctx, "No source file/folder path to save markers next to.")
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(ctx.cache['markers'], f, indent=2)
        show_window_toast(ctx, f"Markers saved -> JSON saves/{os.path.basename(path)}")
    except Exception as e:
        show_error(ctx, f"Could not save markers: {e}")


def clear_json_saves(ctx):
    """Deletes every file inside the JSON saves/ folder (not the folder
    itself) — used by Undo All Changes so a previously-saved sidecar
    doesn't get silently reloaded right back after the undo."""
    path = sidecar_path(ctx)
    if not path:
        return
    json_dir = os.path.dirname(path)
    if not os.path.isdir(json_dir):
        return
    for name in os.listdir(json_dir):
        entry = os.path.join(json_dir, name)
        if os.path.isfile(entry):
            try:
                os.remove(entry)
            except OSError as e:
                show_error(ctx, f"Could not clear {name}: {e}")


def load_markers_from_sidecar(ctx):
    """Overwrite cache['markers'] from the sidecar if one exists; otherwise
    leave whatever markers the loader already populated (e.g. TDT epoc
    events or Oxysoft dataset events) untouched."""
    path = sidecar_path(ctx)
    if not path or not os.path.exists(path):
        path = _legacy_sidecar_path(ctx)  # fall back to pre-JSON-saves-folder location
    if path and os.path.exists(path):
        try:
            with open(path, 'r') as f:
                ctx.cache['markers'] = json.load(f)
            show_window_toast(ctx, f"Markers restored ({len(ctx.cache['markers'])})")
        except Exception as e:
            show_error(ctx, f"Could not load markers: {e}")


def _annotation_sidecar_path(ctx, cache_key, filename):
    """Same JSON saves/ folder as markers.json, for any other cache list that gets saved the
    same way (highlights.json, text_annotations.json) — no legacy pre-JSON-saves-folder fallback
    for these, since they're new; nothing used the old location for them."""
    if ctx.cache is None or not ctx.cache.get('source_path'):
        return None
    source = ctx.cache['source_path']
    if os.path.isdir(source):
        return os.path.join(source, "JSON saves", filename)
    return os.path.join(os.path.dirname(source), "JSON saves", os.path.basename(source) + f".{filename}")


def save_annotation_list(ctx, cache_key, filename, noun):
    """Saves ctx.cache[cache_key] (a plain list of JSON-able dicts) to its own sidecar file next
    to markers.json — used for highlights and text annotations, which follow the identical
    save/restore convention as markers but are their own files, not mixed into markers.json."""
    if ctx.cache is None:
        return
    path = _annotation_sidecar_path(ctx, cache_key, filename)
    if not path:
        show_error(ctx, f"No source file/folder path to save {noun} next to.")
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(ctx.cache.get(cache_key, []), f, indent=2)
    except Exception as e:
        show_error(ctx, f"Could not save {noun}: {e}")


def load_annotation_list_from_sidecar(ctx, cache_key, filename):
    """Overwrites ctx.cache[cache_key] from its sidecar if one exists; leaves it untouched (not
    even set to []) otherwise, same as load_markers_from_sidecar — callers that need the key to
    always exist use ctx.cache.get(cache_key, []) rather than relying on this to initialize it."""
    path = _annotation_sidecar_path(ctx, cache_key, filename)
    if path and os.path.exists(path):
        try:
            with open(path, 'r') as f:
                ctx.cache[cache_key] = json.load(f)
        except Exception as e:
            show_error(ctx, f"Could not load {filename}: {e}")


def save_highlights(ctx):
    save_annotation_list(ctx, 'highlights', 'highlights.json', 'highlights')


def load_highlights_from_sidecar(ctx):
    load_annotation_list_from_sidecar(ctx, 'highlights', 'highlights.json')


def save_text_annotations(ctx):
    save_annotation_list(ctx, 'text_annotations', 'text_annotations.json', 'text annotations')


def load_text_annotations_from_sidecar(ctx):
    load_annotation_list_from_sidecar(ctx, 'text_annotations', 'text_annotations.json')
