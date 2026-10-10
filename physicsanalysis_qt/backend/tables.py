"""
backend/tables.py
-----------------
The tables an engine answer hands over as files (a request made with tables="files": group.run, results.open) read as DataFrames.
"""

import pandas as pd


def read_tables(wire):
    """{name: DataFrame} for the tables of an answer: {name: {"path": a CSV, ...}}. The numbers are read back exactly as the engine wrote them."""
    return {name: pd.read_csv(table["path"], float_precision="round_trip") for name, table in wire.items()}
