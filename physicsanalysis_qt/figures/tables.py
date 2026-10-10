"""
figures/tables.py
-----------------
Looking at result tables by their columns: which table is which, and the channels in one.
"""

import numpy as np
import pandas as pd


def has(table, *columns):
    return set(columns) <= set(table.columns)


def find(tables, *columns):
    """The first table that has all of `columns`, or None."""
    return next((t for t in tables.values() if has(t, *columns)), None)


def ordered(values):
    """The distinct values in the order they first appear."""
    return list(dict.fromkeys(values))


def channels(table):
    """[(channel name, its rows)] — a table with no Channel column is one unnamed channel."""
    if "Channel" in table.columns:
        return [(str(name), g) for name, g in table.groupby("Channel", sort=False)]
    return [("", table)]


def numeric(table, exclude=()):
    return [c for c in table.columns if c not in exclude and pd.api.types.is_numeric_dtype(table[c])]


def float_array(values):
    return np.asarray(values, dtype=float)
