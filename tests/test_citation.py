"""The citation the status bar's button copies (app/citation.py): each format built from the same facts, the
facts agreeing with CITATION.cff (which GitHub and Zenodo read), and the button's menu putting the right text
on the clipboard."""

import os
import re
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMenu, QToolButton

import physicsanalysis_qt
from physicsanalysis_qt.app import citation
from physicsanalysis_qt.app.update_check import local_version
from physicsanalysis_qt.ui import main_window

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WITHOUT_DOI = citation.Software("Grand Maison", "Zakary", "PyAT: Python Analysis Tool", "4.1.0", "2026",
                                "https://github.com/zakgm2/PyAT")
WITH_DOI = citation.Software("Grand Maison", "Zakary", "PyAT: Python Analysis Tool", "4.1.0", "2026",
                             "https://github.com/zakgm2/PyAT", "10.5281/zenodo.1234567")


def cff(key):
    """A top-level `key: value` line of CITATION.cff (None when it is absent); the file is simple enough that
    no YAML reader is needed, which the app's test environment does not have."""
    with open(os.path.join(ROOT, "CITATION.cff"), encoding="utf-8") as f:
        match = re.search(rf'^{re.escape(key)}:\s*"?([^"\r\n]*)"?\s*$', f.read(), re.MULTILINE)
    return match.group(1) if match else None


def cff_author(key):
    with open(os.path.join(ROOT, "CITATION.cff"), encoding="utf-8") as f:
        return re.search(rf'^\s+-?\s*{re.escape(key)}:\s*"([^"\r\n]*)"', f.read(), re.MULTILINE).group(1)


class TestEachFormat(unittest.TestCase):
    def test_every_format_names_the_work_the_version_the_year_and_where_to_find_it(self):
        for software, link, publisher in ((WITHOUT_DOI, "https://github.com/zakgm2/PyAT", "GitHub"),
                                          (WITH_DOI, "https://doi.org/10.5281/zenodo.1234567", "Zenodo")):
            for label, build, _styled in citation.FORMATS:
                text = citation.plain(build(software))
                for needed in ("Grand Maison", "PyAT: Python Analysis Tool", "4.1.0", "2026", link, publisher):
                    self.assertIn(needed, text, f"{label}: {needed!r} missing from {text!r}")

    def test_a_citation_with_a_doi_does_not_also_send_readers_to_the_repository(self):
        for label, build, _styled in citation.FORMATS:
            self.assertNotIn("github.com", build(WITH_DOI), label)

    def test_without_a_version_nothing_says_version(self):
        bare = citation.Software("Grand Maison", "Zakary", "PyAT: Python Analysis Tool", None, "2026", "https://github.com/zakgm2/PyAT")
        for label, build, _styled in citation.FORMATS:
            self.assertNotIn("ersion", build(bare), label)

    def test_apa(self):
        self.assertEqual(citation.apa(WITHOUT_DOI),
                         "Grand Maison, Z. (2026). *PyAT: Python Analysis Tool* (Version 4.1.0) [Computer software]. "
                         "GitHub. https://github.com/zakgm2/PyAT")
        self.assertEqual(citation.apa(WITH_DOI),
                         "Grand Maison, Z. (2026). *PyAT: Python Analysis Tool* (Version 4.1.0) [Computer software]. "
                         "Zenodo. https://doi.org/10.5281/zenodo.1234567")

    def test_the_other_text_styles(self):
        self.assertEqual(citation.mla(WITH_DOI),
                         "Grand Maison, Zakary. *PyAT: Python Analysis Tool*. Version 4.1.0, Zenodo, 2026, "
                         "https://doi.org/10.5281/zenodo.1234567.")
        self.assertEqual(citation.chicago(WITH_DOI),
                         "Grand Maison, Zakary. 2026. *PyAT: Python Analysis Tool*. Version 4.1.0. Zenodo. "
                         "https://doi.org/10.5281/zenodo.1234567.")
        self.assertEqual(citation.harvard(WITH_DOI),
                         "Grand Maison, Z. (2026) *PyAT: Python Analysis Tool*. Version 4.1.0 [Computer program]. "
                         "Zenodo. Available at: https://doi.org/10.5281/zenodo.1234567")
        self.assertEqual(citation.vancouver(WITH_DOI),
                         "Grand Maison Z. PyAT: Python Analysis Tool [computer program]. Version 4.1.0. "
                         "Zenodo; 2026. Available from: https://doi.org/10.5281/zenodo.1234567")
        self.assertEqual(citation.ieee(WITH_DOI),
                         "Z. Grand Maison, “PyAT: Python Analysis Tool,” version 4.1.0, Zenodo, 2026. "
                         "[Online]. Available: https://doi.org/10.5281/zenodo.1234567")

    def test_the_italics_marker_wraps_only_the_title_and_goes_away_in_plain_text(self):
        italic = set()
        for label, build, _styled in citation.FORMATS:
            text = build(WITH_DOI)
            if "*" in text:
                italic.add(label)
                self.assertEqual(re.findall(r"\*(.+?)\*", text), ["PyAT: Python Analysis Tool"], label)
            self.assertNotIn("*", citation.plain(text), label)
        self.assertEqual(italic, {"APA 7", "MLA 9", "Chicago (author-date)", "Harvard"})   # Vancouver and IEEE set the title in roman
        self.assertIn("<i>PyAT: Python Analysis Tool</i>", citation.html(citation.apa(WITH_DOI)))

    def test_html_escapes_what_it_must(self):
        self.assertEqual(citation.html("a & b <c> *d*"), "a &amp; b &lt;c&gt; <i>d</i>")


class TestBibtexAndRis(unittest.TestCase):
    def test_bibtex_is_a_software_entry_with_the_family_name_first(self):
        text = citation.bibtex(WITH_DOI)
        self.assertTrue(text.startswith("@software{grandmaison2026pyat,\n"))
        self.assertTrue(text.endswith("}"))
        self.assertEqual(text.count("{"), text.count("}"))
        for field in ("author    = {Grand Maison, Zakary},", "title     = {{PyAT: Python Analysis Tool}},",
                      "version   = {4.1.0},", "year      = {2026},", "publisher = {Zenodo},",
                      "doi       = {10.5281/zenodo.1234567},", "url       = {https://doi.org/10.5281/zenodo.1234567},"):
            self.assertIn(f"  {field}\n", text)
        self.assertNotIn("*", text)

    def test_bibtex_without_a_doi_points_at_the_repository(self):
        text = citation.bibtex(WITHOUT_DOI)
        self.assertNotIn("doi", text)
        self.assertIn("publisher = {GitHub},", text)
        self.assertIn("url       = {https://github.com/zakgm2/PyAT},", text)

    def test_ris_is_a_computer_program_record_that_ends_properly(self):
        lines = citation.ris(WITH_DOI).split("\n")
        self.assertEqual(lines[0], "TY  - COMP")
        self.assertEqual(lines[-1], "ER  - ")
        self.assertEqual(lines[1:-1], ["AU  - Grand Maison, Zakary", "TI  - PyAT: Python Analysis Tool", "PY  - 2026",
                                       "ET  - 4.1.0", "PB  - Zenodo", "DO  - 10.5281/zenodo.1234567",
                                       "UR  - https://doi.org/10.5281/zenodo.1234567"])
        for line in lines:
            self.assertRegex(line, r"^[A-Z][A-Z0-9]  - ")

    def test_ris_without_a_doi_has_no_doi_line(self):
        self.assertNotIn("DO  -", citation.ris(WITHOUT_DOI))


class TestTheFactsAgreeWithCitationCff(unittest.TestCase):
    """GitHub's "Cite this repository" box and Zenodo read CITATION.cff; the app prints the same facts from
    constants (a packaged build has no CITATION.cff to read), so a release that bumps one and not the other fails here."""

    def test_version(self):
        self.assertEqual(cff("version"), physicsanalysis_qt.__version__)
        self.assertEqual(citation.current().version, physicsanalysis_qt.__version__)
        self.assertEqual(local_version("physicsanalysis_qt"), physicsanalysis_qt.__version__)

    def test_release_date(self):
        self.assertEqual(cff("date-released"), physicsanalysis_qt.__release_date__)
        self.assertEqual(citation.current().year, physicsanalysis_qt.__release_date__[:4])

    def test_author_title_and_repository(self):
        self.assertEqual(cff_author("family-names"), citation.FAMILY)
        self.assertEqual(cff_author("given-names"), citation.GIVEN)
        self.assertEqual(cff("title"), citation.TITLE)
        self.assertEqual(cff("repository-code"), citation.REPO_URL)

    def test_doi(self):
        self.assertEqual(cff("doi") or "", citation.CONCEPT_DOI)
        if citation.CONCEPT_DOI:
            self.assertRegex(citation.CONCEPT_DOI, r"^10\.\d{4,9}/\S+$")

    def test_the_citation_the_button_copies_points_at_the_doi(self):
        self.assertTrue(citation.CONCEPT_DOI, "a release cites the Zenodo concept DOI: set CONCEPT_DOI and `doi:` in CITATION.cff")
        software = citation.current()
        self.assertEqual(software.doi, citation.CONCEPT_DOI)
        for label, build, _styled in citation.FORMATS:
            self.assertIn(f"https://doi.org/{citation.CONCEPT_DOI}", build(software), label)


class TestTheButton(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.toasts = []
        patcher = mock.patch.object(main_window, "show_window_toast", lambda ctx, msg, *a, **k: self.toasts.append(msg))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.button = main_window._build_citation_button(SimpleNamespace(app=self.app))
        self.addCleanup(self.button.deleteLater)

    def actions(self):
        return {a.text(): a for a in self.button.menu().actions() if not a.isSeparator()}

    def test_the_menu_lists_every_format_in_order_with_a_line_before_the_data_formats(self):
        actions = self.button.menu().actions()
        self.assertEqual([a.text() for a in actions if not a.isSeparator()], [label for label, _, _ in citation.FORMATS])
        self.assertEqual([i for i, a in enumerate(actions) if a.isSeparator()],
                         [[styled for _, _, styled in citation.FORMATS].index(False)])

    def test_choosing_a_style_copies_it_as_plain_text_and_with_the_title_in_italics(self):
        self.actions()["APA 7"].trigger()
        mime = self.app.clipboard().mimeData()
        expected = citation.apa(citation.current())
        self.assertEqual(mime.text(), citation.plain(expected))
        self.assertIn("<i>PyAT: Python Analysis Tool</i>", mime.html())
        self.assertEqual(self.toasts, ["APA 7 citation copied to clipboard"])

    def test_choosing_bibtex_copies_the_entry_with_no_rich_text(self):
        self.actions()["BibTeX"].trigger()
        mime = self.app.clipboard().mimeData()
        self.assertEqual(mime.text(), citation.bibtex(citation.current()))
        self.assertFalse(mime.hasHtml())

    def test_both_menu_buttons_leave_room_for_the_drop_down_arrow(self):
        """The arrow touched the end of the label (a pixel or two) until the buttons were given right padding."""
        feedback = main_window._build_feedback_button(SimpleNamespace(app=self.app, win=None))
        self.addCleanup(feedback.deleteLater)
        for built in (self.button, feedback):
            bare = QToolButton()
            bare.setText(built.text())
            bare.setMenu(QMenu(bare))
            bare.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            self.addCleanup(bare.deleteLater)
            self.assertGreater(built.sizeHint().width(), bare.sizeHint().width(), built.text())

    def test_every_menu_entry_copies_something(self):
        for label, action in self.actions().items():
            self.app.clipboard().clear()
            action.trigger()
            self.assertIn("Grand Maison", self.app.clipboard().text(), label)
            self.assertIn(physicsanalysis_qt.__version__, self.app.clipboard().text(), label)


if __name__ == "__main__":
    unittest.main()
