"""The checks the release workflow makes before anything is built (.github/scripts/check_release.py): the tag, pyproject.toml, __version__, CITATION.cff and
CHANGELOG.md agree. The last test runs them on the repository as it is."""

import contextlib
import importlib.util
import io
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, ".github", "scripts", "check_release.py")

spec = importlib.util.spec_from_file_location("check_release", SCRIPT)
check_release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_release)

PYPROJECT = '[project]\nname = "PyAT"\nversion = "4.1.1"\n'
INIT = '"""doc"""\n__version__ = "4.1.1"\n\n__release_date__ = "2026-11-05"\n'
CFF = 'cff-version: 1.2.0\nversion: "4.1.1"\ndate-released: "2026-11-05"\ndoi: "10.5281/zenodo.1"\n'
CHANGELOG = """# Changelog

---

## v4.1.1
**A fix.**

- one

---

## v4.1.10
not this one

---

## v4.1.0
older
"""


def run(tag="v4.1.1", pyproject=PYPROJECT, init=INIT, cff=CFF, changelog=CHANGELOG):
    return check_release.check(tag, pyproject, init, cff, changelog)


class TestTheChecks(unittest.TestCase):
    def test_everything_agreeing_passes(self):
        self.assertEqual(run(), [])

    def test_a_tag_that_is_not_a_version(self):
        for tag in ("4.1.1", "v4.1", "release-1", "v4.1.1-rc1"):
            self.assertEqual(len(run(tag)), 1, tag)

    def test_each_place_that_disagrees_is_named(self):
        problems = run(pyproject=PYPROJECT.replace("4.1.1", "4.1.0"))
        self.assertEqual(len(problems), 1)
        self.assertIn("pyproject.toml says 4.1.0", problems[0])
        problems = run(init=INIT.replace('__version__ = "4.1.1"', '__version__ = "4.1.0"'))
        self.assertEqual(len(problems), 1)
        self.assertIn("__version__ says 4.1.0", problems[0])
        problems = run(cff=CFF.replace('version: "4.1.1"', 'version: "4.1.0"'))
        self.assertEqual(len(problems), 1)
        self.assertIn("CITATION.cff says 4.1.0", problems[0])

    def test_the_release_date_must_agree_between_the_app_and_the_citation_file(self):
        problems = run(cff=CFF.replace("2026-11-05", "2026-11-02"))
        self.assertEqual(len(problems), 1)
        self.assertIn("differ", problems[0])

    def test_the_changelog_needs_the_versions_section(self):
        problems = run("v4.1.2", PYPROJECT.replace("4.1.1", "4.1.2"), INIT.replace("4.1.1", "4.1.2"), CFF.replace("4.1.1", "4.1.2"))
        self.assertEqual(len(problems), 1)
        self.assertIn("no '## v4.1.2' section", problems[0])

    def test_a_longer_version_is_not_mistaken_for_it(self):
        self.assertEqual(check_release.changelog_section(CHANGELOG, "4.1.10"), "not this one")
        self.assertIsNone(check_release.changelog_section(CHANGELOG, "4.1.2"))
        self.assertEqual(check_release.changelog_section(CHANGELOG, "4.1.1"), "**A fix.**\n\n- one")

    def test_every_problem_is_reported_together(self):
        self.assertEqual(len(run("v9.9.9")), 4)      # pyproject, __version__, CITATION.cff and the changelog; the two dates still agree

    def test_the_script_returns_nonzero_and_prints_github_errors_on_a_problem(self):
        with tempfile.TemporaryDirectory() as folder:
            os.makedirs(os.path.join(folder, "physicsanalysis_qt"))
            for name, text in (("pyproject.toml", PYPROJECT), ("physicsanalysis_qt/__init__.py", INIT), ("CITATION.cff", CFF), ("CHANGELOG.md", CHANGELOG)):
                with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
                    f.write(text)
            here = os.getcwd()
            os.chdir(folder)
            printed = io.StringIO()      # `::error::` lines would show as annotations on a green test run
            try:
                with contextlib.redirect_stdout(printed):
                    self.assertEqual(check_release.main("v4.1.1"), 0)
                    self.assertEqual(check_release.main("v4.1.9"), 1)
            finally:
                os.chdir(here)
            self.assertEqual(printed.getvalue().count("::error::"), 4)


class TestThisRepository(unittest.TestCase):
    def test_the_version_in_the_repository_could_be_released_as_it_stands(self):
        """A release that would fail the workflow's checks (CITATION.cff, __version__ or the changelog left behind) fails here first."""
        def read(name):
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                return f.read()

        version = check_release.pyproject_version(read("pyproject.toml"))
        problems = check_release.check(f"v{version}", read("pyproject.toml"), read("physicsanalysis_qt/__init__.py"), read("CITATION.cff"), read("CHANGELOG.md"))
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
