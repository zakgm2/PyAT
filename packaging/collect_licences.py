"""
collect_licences.py
-------------------
Writes THIRD_PARTY_NOTICES.txt: every open-source package the release executable contains, with its version, its licence, where it comes from and the
full text of its licence files, read from the installed packages' own metadata. Run by .github/workflows/build.yml after the app and its dependencies
are installed (the executable contains what is installed there) and copied into both release zips.

Why: the BSD, MIT and Apache licences of the bundled packages (numpy, scipy, pandas, matplotlib, statsmodels, ...) require their copyright notice and licence
text to travel with a binary, and the GPL and LGPL ones (PyQt6, Qt, tdt) their text and where to get the source. PyAT itself is AGPL-3.0 (LICENSE.txt, beside this file).

    python packaging/collect_licences.py dist/THIRD_PARTY_NOTICES.txt

tests/test_third_party_notices.py runs this on the development environment, so a bundled package whose licence cannot be found is noticed before a release.
"""

import os
import re
import sys
from importlib import metadata

from packaging.requirements import Requirement

# What PhysicsAnalysis.spec bundles (its `_metadata` list, plus what those need): the app, the library, and the numerical and GUI packages.
ROOTS = ["PyATCLI", "numpy", "scipy", "pandas", "statsmodels", "scikit-learn", "matplotlib", "tdt", "openpyxl", "tqdm", "PyQt6",
         "pyqtgraph", "packaging"]
# the spec excludes these from the executable (the text field study's language model is not bundled)
EXCLUDED = {"sentence-transformers", "torch", "transformers"}
# packages whose metadata does not say (tdt's reads "UNKNOWN") but whose shipped licence file does
OVERRIDES = {"tdt": "GNU GPL v3 (from the LICENSE file the package ships)"}
LICENCE_FILE = re.compile(r"(^|[/\\])(LICEN[CS]E|COPYING|NOTICE|AUTHORS)[^/\\]*$", re.IGNORECASE)

SOURCE_OFFERS = {
    "pyqt6": "PyQt6 is available under the GPL v3 (or a commercial licence): https://www.riverbankcomputing.com/software/pyqt/",
    "pyqt6-qt6": "Qt is available under the LGPL v3: the source of the Qt libraries in this program is at https://download.qt.io/official_releases/qt/ "
                 "and https://code.qt.io/. The LGPL lets you replace them with your own build of the same version.",
    "tdt": "tdt is TDT's Python package, under the GPL v3: https://pypi.org/project/tdt/",
}

FOOTER = """\
PyInstaller bootloader
----------------------
The executable is built with PyInstaller (https://pyinstaller.org). Its bootloader is under the GNU General Public License v2 or later with an exception
that allows the program it carries to be distributed under any licence.

Python
------
The Python runtime in the executable is under the Python Software Foundation License: https://docs.python.org/3/license.html
"""


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def requirements(dist):
    """Names of the distributions `dist` needs on this platform, without extras (an optional extra is a root of its own where the executable has it)."""
    names = []
    for text in dist.requires or []:
        requirement = Requirement(text)
        if requirement.marker is not None and not requirement.marker.evaluate({"extra": ""}):
            continue
        names.append(norm(requirement.name))
    return names


def distributions():
    """[(name, Distribution or None)] for the roots and everything they need, in the order found."""
    installed = {norm(d.metadata["Name"]): d for d in metadata.distributions()}
    queue, seen, found = [norm(r) for r in ROOTS], set(), []
    while queue:
        name = queue.pop(0)
        if name in seen or name in EXCLUDED:
            continue
        seen.add(name)
        dist = installed.get(name)
        found.append((name, dist))
        if dist is not None:
            queue.extend(requirements(dist))
    return found


def licence_of(dist):
    if norm(dist.metadata["Name"]) in OVERRIDES:
        return OVERRIDES[norm(dist.metadata["Name"])]
    md = dist.metadata
    expression = md.get("License-Expression")
    text = md.get("License")
    classifiers = [c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
    if expression:
        return expression
    if text and text.strip().upper() != "UNKNOWN" and len(text) < 120:
        return text.strip()
    return "; ".join(classifiers) or None


def homepage_of(dist):
    md = dist.metadata
    for entry in md.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        if label.strip().lower() in ("homepage", "home", "source", "repository", "source code"):
            return url.strip()
    home = md.get("Home-page")
    return home if home and home != "UNKNOWN" else None


def licence_texts(dist):
    """[(file name, text)] of the licence, copying and notice files the distribution ships."""
    texts = []
    for entry in dist.files or []:
        if LICENCE_FILE.search(str(entry)):
            try:
                texts.append((str(entry).replace("\\", "/"), dist.locate_file(entry).read_text(encoding="utf-8", errors="replace").strip()))
            except OSError:
                pass
    return texts


def collect():
    """[{"name", "version", "licence", "url", "texts", "installed"}] for everything the executable contains."""
    records = []
    for name, dist in distributions():
        if dist is None:
            records.append({"name": name, "version": None, "licence": None, "url": None, "texts": [], "installed": False})
            continue
        records.append({"name": dist.metadata["Name"], "version": dist.version, "licence": licence_of(dist), "url": homepage_of(dist),
                        "texts": licence_texts(dist), "installed": True})
    return records


def render(records):
    rule = "=" * 78
    lines = ["THIRD-PARTY NOTICES", rule, "",
             "PyAT (Python Analysis Tool) is licensed under the GNU Affero General Public License v3.0 (LICENSE.txt); the complete source of PyAT and of the analysis",
             "library inside it, PyATCLI, is at https://github.com/zakgm2/PyAT and https://github.com/zakgm2/PyATCLI.",
             "", "This program contains the open-source packages listed below. Each is used under its own licence, whose text follows its entry.", "",
             "Contents", "--------"]
    for r in records:
        if r["installed"]:
            lines.append(f"  {r['name']} {r['version']}  -  {r['licence'] or 'see its licence text below'}")
    lines.append("")
    for r in records:
        if not r["installed"]:
            continue
        lines += [rule, f"{r['name']} {r['version']}", rule, f"Licence: {r['licence'] or '(see the text below)'}"]
        if r["url"]:
            lines.append(f"Home: {r['url']}")
        offer = SOURCE_OFFERS.get(norm(r["name"]))
        if offer:
            lines.append(offer)
        lines.append("")
        if not r["texts"]:
            lines += ["(this package ships no licence file; its licence is as stated above, see its home page)", ""]
        for filename, text in r["texts"]:
            lines += [f"--- {filename} ---", text, ""]
    lines += [rule, FOOTER]
    return "\n".join(lines)


def main(out_path):
    records = collect()
    missing = [r["name"] for r in records if not r["installed"] and norm(r["name"]) in {norm(x) for x in ROOTS}]
    text = render(records)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    unlicensed = [r["name"] for r in records if r["installed"] and not r["licence"] and not r["texts"]]
    print(f"{len(records)} packages, {sum(len(r['texts']) for r in records)} licence files -> {out_path}")
    if missing:
        print(f"::warning::bundled packages not installed here, so not listed: {', '.join(missing)}")
    if unlicensed:
        print(f"::error::no licence found for: {', '.join(unlicensed)}")
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
