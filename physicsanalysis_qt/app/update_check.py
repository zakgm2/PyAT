"""
app/update_check.py
-------------------
Checks GitHub for a newer version of PhysicsAnalysis and PyATCLI
than what's currently running — the same check, the same behavior,
whether this is a dev/editable install or a packaged build. There's no
installer to silently run (this project ships a plain onefile exe, no
Inno Setup/MSI/etc.), so there's no safe way to auto-apply an update
without user interaction — the app can only tell you one exists.

Both an available PhysicsAnalysis update and an available PyATCLI
update are purely a splash status line (UpdateCheckWorker.checked's
"status") — never a blocking dialog. A modal "Update Available" popup
used to gate launch here; it's gone now, both because a launch-blocking
popup is worse than just telling you and moving on, and because a
QMessageBox whose only buttons are ActionRole/AcceptRole has no button
Qt can treat as the window's close/Escape action, so its titlebar X
silently did nothing — a genuinely stuck-feeling dead end, not just an
annoying one.

Neither project reliably uses GitHub Releases (PyATCLI currently
has none at all), so "latest version" prefers the tag of the repo's
latest published Release when one exists, and falls back to the version
string committed in pyproject.toml on the default branch when it
doesn't — covering a project whether or not its owner bothers publishing
formal releases.

The GitHub calls run on a background QThread so the splash's pulse
animation and event loop stay responsive while they're in flight.
"""

import json
import re
import urllib.error
import urllib.request

from PyQt6.QtCore import QThread, pyqtSignal
from packaging.version import Version

_TIMEOUT_S = 4

_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def _parse_version(pyproject_text):
    match = _VERSION_RE.search(pyproject_text)
    return match.group(1) if match else None


def local_version(name):
    """Reads the version out of a package's own pyproject.toml, found
    relative to its installed location — works the same whether that
    package is this app itself or an editable-installed dependency like
    PyATCLI, and always reflects the actual source on disk rather
    than possibly-stale install metadata. Also used directly by
    ui/main_window.py to show this app's own version in the title bar.

    Tried first, ahead of any hardcoded __version__ string a package might
    also define (physicsanalysis_qt does — see its __init__.py),
    specifically to avoid trusting a constant that could silently drift
    from pyproject.toml's own value during development. Only falls back
    to __version__ when pyproject.toml can't be read at all, which is
    exactly the case for a frozen/packaged build — there's no source
    tree on disk there, so there's nothing for that constant to drift
    from."""
    import importlib
    import os

    module = importlib.import_module(name)
    pkg_dir = os.path.dirname(os.path.abspath(module.__file__))
    pyproject_path = os.path.join(os.path.dirname(pkg_dir), "pyproject.toml")
    version = None
    try:
        with open(pyproject_path, "r", encoding="utf-8") as f:
            version = _parse_version(f.read())
    except OSError:
        pass
    # Falls through here both when the file couldn't be opened at all
    # (frozen build — no source tree on disk) and when it opened but
    # didn't contain a recognizable version line (a frozen build's
    # module.__file__ can resolve to some other real-but-irrelevant path
    # that happens not to raise OSError) — either way, nothing usable
    # was read, so fall back the same way.
    if version is None:
        version = getattr(module, "__version__", None)
    if version is None:
        raise ValueError(f"could not determine {name}'s version")
    return version


def _remote_version(repo):
    """(version, url) for the latest published Release if one exists —
    url points straight at that release page — else the version
    committed in pyproject.toml on the default branch, with url falling
    back to the repo's own page."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"User-Agent": "PhysicsAnalysis-update-check"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            data = json.loads(resp.read())
            return data["tag_name"].lstrip("v"), data["html_url"]
    except urllib.error.HTTPError as e:
        if e.code != 404:  # 404 = no releases published, the expected fallback case
            raise

    req = urllib.request.Request(
        f"https://raw.githubusercontent.com/{repo}/main/pyproject.toml",
        headers={"User-Agent": "PhysicsAnalysis-update-check"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        return _parse_version(resp.read().decode()), f"https://github.com/{repo}"


# (display name, importable package name, GitHub "owner/repo")
# The app's repo was renamed to PyAT in v3.0.0. Copies installed before that
# still ask for the old name, which GitHub redirects to this one.
_PROJECTS = [
    ("PhysicsAnalysis", "physicsanalysis_qt", "zakgm2/PyAT"),
    ("PyATCLI", "PyATCLI", "zakgm2/PyATCLI"),
]


class UpdateCheckWorker(QThread):
    """Emits exactly one dict once the PhysicsAnalysis check settles
    (PyATCLI is checked too, but only PhysicsAnalysis being
    outdated is worth surfacing — see the module docstring):
        {"outdated": True, "message": str}
            — caller should call splash.prompt_update(message) instead
              of launching straight through. Where "Download Update"
              actually goes is splash.DOWNLOAD_PAGE_URL, a fixed
              landing page — not tied to whatever release URL this
              check happened to find, so it's not threaded through here.
        {"outdated": False}
            — nothing to offer, launch normally. This is also exactly
              what happens with no internet connection at all: every
              _remote_version() call fails, results stays empty,
              "outdated" can only ever be True from a *successful*
              comparison against a real remote version — there's no
              path from "network request failed" to a false positive
              here, by construction, not by a separate offline check."""
    checked = pyqtSignal(dict)

    def run(self):
        results = {}
        for display_name, package_name, repo in _PROJECTS:
            try:
                local = Version(local_version(package_name))
                remote_str, url = _remote_version(repo)
                remote = Version(remote_str)
            except Exception:
                # Covers everything from "no internet" (URLError/socket
                # errors from urlopen) to a missing/malformed
                # pyproject.toml to a GitHub outage — none of those are
                # the user's fault or actionable from a splash screen,
                # so this project is just silently skipped rather than
                # shown as an error on every single offline launch.
                continue
            results[display_name] = {
                "outdated": remote > local, "local": local, "remote": remote, "url": url,
            }

        analysis = results.get("PhysicsAnalysis")
        if analysis and analysis["outdated"]:
            self.checked.emit({
                "outdated": True,
                "message": (f"A newer version of PyAT is available "
                            f"(v{analysis['remote']} — you have v{analysis['local']})."),
            })
        else:
            self.checked.emit({"outdated": False})
