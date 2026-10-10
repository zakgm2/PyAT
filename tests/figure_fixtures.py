"""Recordings and a group analysis to draw from, made up: what the figure tests of the app need of the analysis library's own test fixtures."""

import types

import numpy as np

import PyATCLI as pl
from PyATCLI.analysis.group import GroupSpec

EVENTS = [40.0, 90.0, 140.0, 200.0, 250.0]


def phase_marker(t, phase, store="L1P"):
    return {"time": float(t), "label": store, "color": "black", "store": store, "phase": phase}


def make_cache(n=30_000, fs=100.0, seed=0):
    """A TDT-shaped recording: a decaying response after each L1P onset, a note at 120 s, two signals."""
    rng = np.random.default_rng(seed)
    x = np.arange(n) / fs
    y = 0.01 * rng.standard_normal(n)
    for e in EVENTS:
        d = x - e
        y = y + np.where(d >= 0, 1.5 * np.exp(-np.clip(d, 0, None) / 2.0), 0.0)
    return {
        "source": "TDT", "source_path": "C:/x/Rec", "store": "Rec", "x": x, "fs": fs, "raw": y, "corr": y,
        "detected_markers": [phase_marker(e, "high") for e in EVENTS] + [phase_marker(e + 0.5, "low") for e in EVENTS],
        "markers": [{"time": 120.0, "label": "MyNote", "color": "green", "fontsize": 8}],
        "signals": {"normalized": {"label": "Normalized (dF/F)", "y": y},
                    "main_driver": {"label": "Main Driver (x465A)", "y": 2 * y + 10}},
    }


def oxysoft_cache(thb=False):
    t = np.arange(600) / 10.0
    rng = np.random.default_rng(1)
    dataset = types.SimpleNamespace(
        metadata={"n_channels": 2, "fit_factor_mean": 91.25}, num_channels=4, signals=rng.normal(size=(4, 600)),
        folder_name="NIRS-1", num_samples=len(t), sample_rate=10.0, events=[{"sample": 100, "label": "A"}])
    cache = pl.make_oxysoft_cache("nirs.txt", dataset)
    if thb:
        cache["thb"] = rng.normal(size=(2, 600))
    return cache


def generic_cache():
    t = np.arange(50.0)
    b = np.cos(t / 5)
    b[10:14] = np.nan
    table = types.SimpleNamespace(headers=["Time (s)", "Left", "Right"], data=np.column_stack([t, np.sin(t / 5), b]), name="Sheet1")
    return pl.make_generic_cache("table.csv", table)


def simulated_loader(n_sub=6, seed=0, fail_on=None, warn_on=None):
    """load(folder, regression_method, store_labels, progress) for stand-in recordings: 'big' events respond
    twice as strongly as 'small' ones. Records what it was asked."""
    rng = np.random.default_rng(seed)
    data, calls = {}, []
    amp = {"big": 2.0, "small": 1.0}
    for s in range(n_sub):
        gain = rng.lognormal(0, 0.3)
        events = {m: [round(float(e), 2) for e in np.sort(rng.uniform(30, 270, 12))] for m in amp}
        x = np.arange(30_000) / 100.0
        y = 0.02 + 0.005 * rng.standard_normal(len(x))
        for m, times in events.items():
            for e in times:
                d = x - e
                y = y + np.where(d >= 0, gain * amp[m] * np.exp(-np.clip(d, 0, None) / 1.5), 0.0)
        data[f"f{s}"] = {"x": x, "y": y, "fs": 100.0, "groups": events, "n_splices": 0, "warnings": []}

    def load(folder, regression_method, store_labels, progress):
        calls.append((folder, regression_method, store_labels))
        if folder == fail_on:
            raise OSError("boom")
        out = dict(data[folder])
        if folder == warn_on:
            out["warnings"] = ["markers.json was unreadable"]
        if progress:
            progress(1.0, "loaded")
        return out

    return load, calls


def simulated_spec(n_sub=6, **kw):
    return GroupSpec(group_name="G", subjects=[{"subject": f"S{i}", "folder": f"f{i}"} for i in range(n_sub)],
                     markers=["big", "small"], metrics=["auc", "peak"], smooth_seconds=0.5, **kw)
