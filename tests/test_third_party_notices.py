"""The third-party notices the release zips carry (packaging/collect_licences.py): every open-source package the executable contains, with its licence and
the text of its licence files, so a bundled package whose licence cannot be found is noticed before a release."""

import importlib.util
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("collect_licences", os.path.join(ROOT, "packaging", "collect_licences.py"))
collect_licences = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect_licences)

# the packages the executable contains that this test environment must also have (CI installs them all)
BUNDLED = ["numpy", "scipy", "pandas", "statsmodels", "scikit-learn", "matplotlib", "tdt", "openpyxl", "tqdm", "PyQt6", "pyqtgraph", "packaging"]


class TestTheNotices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = collect_licences.collect()
        cls.by_name = {collect_licences.norm(r["name"]): r for r in cls.records}
        cls.text = collect_licences.render(cls.records)

    def test_every_bundled_package_is_listed_with_a_licence_text(self):
        for name in BUNDLED:
            record = self.by_name.get(collect_licences.norm(name))
            self.assertIsNotNone(record, name)
            self.assertTrue(record["installed"], name)
            self.assertTrue(record["texts"], f"{name} ships no licence file the notices could carry")

    def test_what_they_need_is_listed_too(self):
        for name in ("pillow", "kiwisolver", "contourpy", "patsy", "joblib", "pyqt6-qt6", "pyqt6-sip"):
            self.assertIn(name, self.by_name, f"{name} is bundled with the packages above but is not in the notices")

    def test_nothing_the_spec_excludes_is_listed(self):
        for name in ("sentence-transformers", "torch", "transformers"):
            self.assertNotIn(name, self.by_name)

    def test_the_copyleft_ones_carry_their_text_and_where_to_get_the_source(self):
        self.assertIn("GNU GENERAL PUBLIC LICENSE", self.text)
        self.assertIn("https://download.qt.io/official_releases/qt/", self.text)              # the LGPL source offer for Qt
        self.assertIn("GNU GPL v3", self.by_name["tdt"]["licence"])

    def test_the_header_says_where_the_apps_own_source_is(self):
        self.assertIn("https://github.com/zakgm2/PyAT", self.text)
        self.assertIn("https://github.com/zakgm2/PyATCLI", self.text)

    def test_the_script_writes_the_file(self):
        with tempfile.TemporaryDirectory() as folder:
            out = os.path.join(folder, "sub", "THIRD_PARTY_NOTICES.txt")
            self.assertEqual(collect_licences.main(out), 0)
            with open(out, encoding="utf-8") as f:
                self.assertGreater(len(f.read()), 10_000)


if __name__ == "__main__":
    unittest.main()
