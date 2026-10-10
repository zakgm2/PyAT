"""
figures/errors.py
-----------------
What a figure request can fail with.
"""


class NothingToPlot(ValueError):
    """There is no latest result (nothing has been run or written yet), or what was named has nothing plottable."""
