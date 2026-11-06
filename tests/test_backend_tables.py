"""The tables an engine answer hands over as files, read by the app (backend/tables.py): the numbers come back exactly as the engine wrote them."""

import os
import tempfile
import unittest
import warnings

import numpy as np
import pandas as pd

from physicsanalysis_qt.backend.tables import read_tables


class TestReadTables(unittest.TestCase):
    def test_numbers_read_back_exactly_and_without_a_pandas_warning(self):
        """Exact on every pandas (the default converter before 3.1 is not, so the argument is passed there) and silent on 3.1 and later
        (which deprecated the argument, so it is not passed there)."""
        rng = np.random.default_rng(1)
        values = np.concatenate([rng.normal(size=20000), rng.normal(size=20000) * 10.0 ** rng.integers(-12, 12, size=20000)])
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "numbers.csv")
            pd.DataFrame({"a": values}).to_csv(path, index=False)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                tables = read_tables({"numbers": {"path": path}})
        np.testing.assert_array_equal(tables["numbers"]["a"].to_numpy(), values)
        self.assertEqual([str(w.message) for w in caught if "float_precision" in str(w.message)], [])


if __name__ == "__main__":
    unittest.main()
