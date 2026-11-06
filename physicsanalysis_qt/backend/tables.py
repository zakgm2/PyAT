"""
backend/tables.py
-----------------
The tables an engine answer hands over as files (a request made with tables="files": group.run, results.open) read as DataFrames.
"""

import re

import pandas as pd


def _pandas_before(major, minor):
    parts = pd.__version__.split(".")
    return (int(parts[0]), int(re.match(r"\d+", parts[1]).group())) < (major, minor)


# What read_csv needs to give float64 numbers back exactly as they were written. Before pandas 3.1 its default converter does not always return the
# same float64 (about a quarter of random values came back different in a test), so `float_precision="round_trip"` is passed there. pandas 3.1 made
# its one converter exact and deprecated the argument (a Pandas4Warning whenever it is given), so on 3.1 and later it is left out.
EXACT_FLOATS = {"float_precision": "round_trip"} if _pandas_before(3, 1) else {}


def read_tables(wire):
    """{name: DataFrame} for the tables of an answer: {name: {"path": a CSV, ...}}. The numbers are read back exactly as the engine wrote them."""
    return {name: pd.read_csv(table["path"], **EXACT_FLOATS) for name, table in wire.items()}
