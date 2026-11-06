"""
app/citation.py
-----------------
The citation the status bar's ❝ Citation button copies, in the formats a paper or a reference manager asks
for (APA, MLA, Chicago, Harvard, Vancouver, IEEE, BibTeX, RIS). Every format is built from the one set of facts
in `Software` (who wrote it, what it is called, which version, which year, where it lives), so the formats
cannot disagree with one another. The facts that cannot be read from the installed app live as constants here
and in the package's `__init__.py`; tests/test_citation.py checks them against CITATION.cff, which GitHub's
"Cite this repository" box and Zenodo read.

Text styles are written with *asterisks* around the part that is italic (the title). `plain()` removes them and
`html()` turns them into <i>, so the clipboard holds both and a word processor keeps the italics on paste.
BibTeX and RIS carry no markup.
"""

import re
from dataclasses import dataclass
from html import escape

from .. import __release_date__
from .update_check import local_version

FAMILY, GIVEN = "Grand Maison", "Zakary"
TITLE = "PyAT: Python Analysis Tool"
REPO_URL = "https://github.com/zakgm2/PyAT"

# The Zenodo *concept* DOI ("Cite all versions"): one number for every version of the app, so it is right in an
# install of any age (a version's own DOI is made when Zenodo archives it, so a release cannot contain it).
# Keep it equal to `doi:` in CITATION.cff; a test fails if they differ. Empty: the citation points at the GitHub
# repository instead, as 4.1.0's did (it was released before Zenodo had made the number).
CONCEPT_DOI = "10.5281/zenodo.23994251"


@dataclass(frozen=True)
class Software:
    family: str
    given: str
    title: str
    version: str | None
    year: str
    url: str
    doi: str = ""

    @property
    def initial(self):
        return self.given[:1] + "."

    @property
    def publisher(self):
        return "Zenodo" if self.doi else "GitHub"

    @property
    def link(self):
        """Where a reader goes: the DOI when there is one, otherwise the repository."""
        return f"https://doi.org/{self.doi}" if self.doi else self.url


def current():
    """This app, as installed: its version from the package, the year of that release, the concept DOI."""
    try:
        version = local_version("physicsanalysis_qt")
    except Exception:
        version = None
    return Software(FAMILY, GIVEN, TITLE, version, __release_date__[:4], REPO_URL, CONCEPT_DOI)


def apa(s):
    version = f" (Version {s.version})" if s.version else ""
    return f"{s.family}, {s.initial} ({s.year}). *{s.title}*{version} [Computer software]. {s.publisher}. {s.link}"


def mla(s):
    version = f" Version {s.version}," if s.version else ""
    return f"{s.family}, {s.given}. *{s.title}*.{version} {s.publisher}, {s.year}, {s.link}."


def chicago(s):
    version = f" Version {s.version}." if s.version else ""
    return f"{s.family}, {s.given}. {s.year}. *{s.title}*.{version} {s.publisher}. {s.link}."


def harvard(s):
    version = f" Version {s.version}" if s.version else ""
    return f"{s.family}, {s.initial} ({s.year}) *{s.title}*.{version} [Computer program]. {s.publisher}. Available at: {s.link}"


def vancouver(s):
    version = f" Version {s.version}." if s.version else ""
    return (f"{s.family} {s.initial} {s.title} [computer program].{version} "
            f"{s.publisher}; {s.year}. Available from: {s.link}")


def ieee(s):
    version = f" version {s.version}," if s.version else ""
    return f"{s.initial} {s.family}, “{s.title},”{version} {s.publisher}, {s.year}. [Online]. Available: {s.link}"


def bibtex_key(s):
    return f"{re.sub('[^a-z]', '', s.family.lower())}{s.year}pyat"


def bibtex(s):
    fields = [("author", f"{s.family}, {s.given}"), ("title", "{" + s.title + "}")]
    if s.version:
        fields.append(("version", s.version))
    fields += [("year", s.year), ("publisher", s.publisher)]
    if s.doi:
        fields.append(("doi", s.doi))
    fields.append(("url", s.link))
    body = "".join(f"  {name:<9} = {{{value}}},\n" for name, value in fields)
    return f"@software{{{bibtex_key(s)},\n{body}}}"


def ris(s):
    lines = [("TY", "COMP"), ("AU", f"{s.family}, {s.given}"), ("TI", s.title), ("PY", s.year)]
    if s.version:
        lines.append(("ET", s.version))
    lines.append(("PB", s.publisher))
    if s.doi:
        lines.append(("DO", s.doi))
    lines += [("UR", s.link), ("ER", "")]
    return "\n".join(f"{tag}  - {value}" for tag, value in lines)


# (label in the menu, builder, whether it is a text style with an italic title); the menu draws a line before
# the first entry that is not a text style
FORMATS = [
    ("APA 7", apa, True),
    ("MLA 9", mla, True),
    ("Chicago (author-date)", chicago, True),
    ("Harvard", harvard, True),
    ("Vancouver", vancouver, True),
    ("IEEE", ieee, True),
    ("BibTeX", bibtex, False),
    ("RIS (EndNote, Zotero, Mendeley)", ris, False),
]


def plain(text):
    return text.replace("*", "")


def html(text):
    return re.sub(r"\*(.+?)\*", r"<i>\1</i>", escape(text))
