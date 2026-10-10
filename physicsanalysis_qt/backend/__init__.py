"""
backend
-------
The app's way to the analysis code, now that none of it runs on the window's thread: PyATCLI's operations (ops/) run in a separate
process — the engine, `python -m PyATCLI serve` — and the window sends it requests and hears its answers.

    errors.py          BackendError: a failed request, with the engine's error code and hint
    runner.py          how the library is launched (python -m PyATCLI; in the frozen app, `PyAT.exe --engine ...`), and CliRun,
                       one command run once with its --json result
    engine_client.py   EngineClient: the long-lived engine, requests and futures, progress, cancel, restart; thread_engine for tests
    recordings.py      what comes back from recording.open / recording.view: the cache the window draws, its arrays mapped from the engine's files

app/background.py's run_engine is the Qt side: it turns a request's progress and answer into the signals and toasts the window uses.

The rest of the app does not import the analysis library at all. What it needs from it is written down in ports.py, from the app's side, and a window
reaches it through `api`:

    from ..backend import api
    colours = api.saved.highlight_colors

    ports.py     what the app asks for (Protocols; nothing in it names the library)
    library.py   the real answer to it, PyATCLI's: the one place that knows where things are in the library
    contract.py  what the app needs of the engine (the protocols it speaks, the operations and tables it uses) and the check on the engine's `ready`;
                 an engine that does not fit is refused, and every request says why (code "incompatible_engine")
    make_backend()   builds it; `api` is the one in use (made on first use); use(other) swaps it, which is how a test brings a fake

tests/test_backend_boundary.py fails if a window imports the library anyway.
"""

from .engine_client import EngineClient, make_engine, thread_engine
from .errors import BackendError
from .runner import CliRun, run_cli

__all__ = ["BackendError", "CliRun", "EngineClient", "api", "current", "make_backend", "make_engine", "run_cli", "thread_engine", "use"]


def make_backend(name="pyatcli"):
    """A backend (ports.Backend). The analysis library is only loaded here, when one is asked for."""
    if name == "pyatcli":
        from .library import PyATCLIBackend
        return PyATCLIBackend()
    raise ValueError(f"no backend called {name!r}; there is 'pyatcli'")


_current = None


def current():
    """The backend in use: made on first use, until use() puts another in its place."""
    global _current
    if _current is None:
        _current = make_backend()
    return _current


def use(backend):
    """Puts `backend` in use (None: forget it, and make the real one again next time). Returns the one it replaced, so a test can put it back."""
    global _current
    previous, _current = _current, backend
    return previous


class _Api:
    """`backend.api.saved` is `backend.current().saved` — looked up each time, so use() takes effect everywhere, even where the name was imported."""

    def __getattr__(self, name):
        return getattr(current(), name)


api = _Api()
