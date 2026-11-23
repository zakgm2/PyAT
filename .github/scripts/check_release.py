"""
Before a release is built: check that the tag that was pushed, pyproject.toml, `__version__`, CITATION.cff and CHANGELOG.md all name the same version.
Run by .github/workflows/build.yml ahead of the Windows and macOS builds, so a tag put on a commit whose version numbers were not bumped (which would
publish an app that nags its users to update forever, and a Zenodo archive that cites the wrong version) is stopped before anything is built or
attached to a Release. tests/test_check_release.py runs the same checks on the repository as it is, so a release that would fail here is found by the
ordinary tests first.

    python .github/scripts/check_release.py v4.1.1
"""

import re
import sys
import textwrap


def pyproject_version(text):
    match = re.search(r'^version\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
    return match.group(1) if match else None


def assignment(text, name):
    """The string assigned to `name = "..."` at the start of a line of a Python file."""
    match = re.search(rf'^{re.escape(name)}\s*=\s*"([^"]*)"', text, re.MULTILINE)
    return match.group(1) if match else None


def citation_value(text, key):
    match = re.search(rf'^{re.escape(key)}:\s*"?([^"\s]+)"?\s*$', text, re.MULTILINE)
    return match.group(1) if match else None


def changelog_section(text, version):
    """The text of `## v<version>` up to the next `---` line (or the next `## ` heading), dedented; None when there is no such section."""
    lines = text.splitlines()
    heading = re.compile(rf"^## v{re.escape(version)}(\s|:|$)")
    start = next((i for i, line in enumerate(lines) if heading.match(line)), None)
    if start is None:
        return None
    body = []
    for line in lines[start + 1:]:
        if line.strip() == "---" or line.startswith("## "):
            break
        body.append(line)
    return textwrap.dedent("\n".join(body)).strip()


def check(tag, pyproject_text, init_text, cff_text, changelog_text):
    """What is wrong, as a list of sentences (empty when the tag can be released)."""
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        return [f"the tag {tag!r} is not of the form vX.Y.Z"]
    version = tag[1:]
    problems = []
    if pyproject_version(pyproject_text) != version:
        problems.append(f"the tag says {version} but pyproject.toml says {pyproject_version(pyproject_text)}")
    if assignment(init_text, "__version__") != version:
        problems.append(f"the tag says {version} but physicsanalysis_qt/__init__.py's __version__ says {assignment(init_text, '__version__')} "
                        "(a packaged app reads that one, and compares it with the newest Release's tag to tell its user about updates)")
    if citation_value(cff_text, "version") != version:
        problems.append(f"the tag says {version} but CITATION.cff says {citation_value(cff_text, 'version')} (Zenodo copies it into the archive)")
    if assignment(init_text, "__release_date__") != citation_value(cff_text, "date-released"):
        problems.append(f"__release_date__ ({assignment(init_text, '__release_date__')}) and CITATION.cff's date-released "
                        f"({citation_value(cff_text, 'date-released')}) differ (the app's citation takes its year from the first)")
    if not changelog_section(changelog_text, version):
        problems.append(f"CHANGELOG.md has no '## v{version}' section (or it is empty)")
    return problems


def main(tag):
    def read(path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    problems = check(tag, read("pyproject.toml"), read("physicsanalysis_qt/__init__.py"), read("CITATION.cff"), read("CHANGELOG.md"))
    if problems:
        for problem in problems:
            print(f"::error::{problem}")
        return 1
    print(f"{tag}: pyproject.toml, __version__, CITATION.cff and CHANGELOG.md agree")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
