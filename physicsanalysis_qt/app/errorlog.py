"""
app/errorlog.py
---------------
The app's error log, so a bug can be reproduced from a file a user sends instead of from "it just closed".

  - A rotating log file in the app's data folder (~/.physicsanalysis/logs/pyat.log, 5 files of 1 MB).
    Every session starts with a header — PyAT and PyATCLI versions, Python, OS, Qt, the numerical
    packages, the settings that change behaviour — and the header is written again whenever the file
    rolls over, so the newest file always says what it was produced by.
  - A global exception hook (main thread, worker threads, unraisable errors) that logs the traceback and
    shows a short modal message with a "Save report" button, instead of the app closing silently. A
    crash in native code (Qt, OpenGL) can't be caught from Python, so faulthandler writes its traceback
    to a file and the next start offers a report about it.
  - It never logs data. What goes in the log is actions (what was opened, run, exported), their
    parameters, errors and stack traces. Arrays, tables and lists are described by shape and length
    (see describe()), never by content.
  - File and folder names can hold animal IDs or participant names, so by default none appear: every
    path, and every bare name of a recording or folder the app has opened, becomes a stable token like
    <path-3fa9c1> (stable so repeated mentions of one recording still read as one; salted per
    install so the token can't be reversed by trying likely names). Options -> "Include file and folder
    names in the error log" turns that off. The user's home folder is always shown as ~.

Importing this module imports only the standard library, so run_qt.py can start it before anything heavy
and catch a crash at import time. Qt is imported only where the dialog or the Qt message handler needs it.
"""

import atexit
import faulthandler
import hashlib
import json
import logging
import logging.handlers
import os
import platform
import re
import secrets
import sys
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path

LOGGER_NAME = "pyat"
LOG_FILENAME = "pyat.log"
NATIVE_FILENAME = "native_crash.log"
LAST_REPORT_FILENAME = "last_error_report.txt"
SETTINGS_KEY_PATHS = "log_file_paths"       # the Options checkbox: include file and folder names in the log
MAX_BYTES = 1_000_000
BACKUP_COUNT = 4
KEEP_NATIVE_ARCHIVES = 3
# the settings that change what the app does, listed in the header (never a path: output_folder is just "set"/"not set")
HEADER_SETTINGS = ("plot_engine", "theme", "regression_method", "background_loading", "decimate_max_points")

# at most this many error dialogs per window of time, and the same error not twice within a while
DIALOG_WINDOW_S = 60.0
DIALOG_MAX_IN_WINDOW = 3
SAME_ERROR_QUIET_S = 30.0

log = logging.getLogger(LOGGER_NAME)

_WIN_PATH = re.compile(r"""(?:[A-Za-z]:|\\\\[^\\/\s]+\\[^\\/\s]+)[\\/][^\s"'<>|?*]*""")
_POSIX_PATH = re.compile(r"""(?<![\w.])/(?:Users|home|Volumes|mnt|media|tmp|var|private|opt)/[^\s"'<>|?*]*""")
_FRAME = re.compile(r'File "([^"]+)", line (\d+)(, in .*)?')
_PATHY_SUFFIXES = ("_path", "_folder", "_dir", "_file", "_directory")
_PATHY_NAMES = ("path", "folder", "dir", "file", "directory")


class _State:
    def __init__(self):
        self.started = False
        self.started_at = None
        self.ended = False
        self.dialog_open = False
        self.log_dir = None
        self.include_paths = False
        self.session_id = None
        self.app_version = None
        self.settings = {}
        self.handler = None
        self.salt = None
        self.tokens = {}                 # name variant -> token, for names that must not appear bare
        self.header_text = ""
        self.previous = {"crashed": False, "native": "", "sessions": []}
        self.native_file = None
        self.lock_path = None
        self.dialog_fn = None            # tests: replaces the Qt dialog
        self.dispatcher = None
        self.main_window = None
        self.last_error = None
        self.dialog_times = []
        self.recent = {}                 # error signature -> last time seen
        self.hooks = None
        self.replaced_stderr = False
        self.qt_handler = False
        self.qt_last = ("", 0.0, 0)
        self.lock = threading.RLock()
        self.local = threading.local()


_S = _State()


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

def _home():
    try:
        return str(Path.home())
    except Exception:                                    # noqa: BLE001
        return ""


def _norm(p):
    return os.path.normcase(os.path.normpath(str(p)))


def _get_salt():
    if _S.salt is None:
        salt_file = _S.log_dir / ".salt" if _S.log_dir else None
        try:
            _S.salt = salt_file.read_text().strip() if salt_file and salt_file.exists() else ""
            if not _S.salt:
                _S.salt = secrets.token_hex(16)
                if salt_file:
                    salt_file.write_text(_S.salt)
        except Exception:                                # noqa: BLE001 - an unwritable folder: a per-process salt will do
            _S.salt = _S.salt or secrets.token_hex(16)
    return _S.salt


def _token_for(name):
    digest = hashlib.sha256((_get_salt() + "|" + _norm(name).lower()).encode("utf-8")).hexdigest()[:6]
    return f"<path-{digest}>"


def _shorten_home(text):
    home = _home()
    if home and len(home) > 3:
        for variant in {home, home.replace("\\", "/")}:
            text = text.replace(variant, "~")
    return text


def path_token(path):
    """How a path appears in the log: itself (home shortened to ~) if the user chose to include names,
    otherwise a stable token."""
    if _S.include_paths:
        return _shorten_home(str(path))
    return _token_for(path)


def register_recording(path):
    """Tells the redactor a recording or folder is in use, so its name is replaced wherever it appears —
    inside a path, or bare in an error message ("Could not read Subject-0042")."""
    if _S.include_paths or not path:
        return
    path = str(path).rstrip("/\\")
    token = _token_for(path)
    base = os.path.basename(path)
    variants = {path, path.replace("\\", "/"), path.replace("/", "\\"), base, os.path.splitext(base)[0]}
    with _S.lock:
        for v in variants:
            if v and len(v) >= 4:                        # a 1-3 character name would replace half the log
                _S.tokens[v] = token


def _replace_registered(text):
    for name in sorted(_S.tokens, key=len, reverse=True):
        if name in text:
            text = text.replace(name, _S.tokens[name])
    return text


def scrub(text):
    """`text` with names removed according to the setting: with names included only the home folder
    becomes ~; otherwise every path and every registered recording name becomes a token."""
    if not isinstance(text, str) or not text:
        return text
    if _S.include_paths:
        return _shorten_home(text)
    # Whole paths first: shortening the home folder to ~ beforehand would leave "~\Desktop\Subject-01"
    # behind, which no path pattern matches, and every folder name below the home folder would leak.
    text = _replace_registered(text)
    text = _WIN_PATH.sub(lambda m: _token_for(m.group(0)), text)
    text = _POSIX_PATH.sub(lambda m: _token_for(m.group(0)), text)
    return _shorten_home(text)


def _display_source_path(p):
    """A source-code path as it should appear in a traceback: from its package on, never the user's folders."""
    q = p.replace("\\", "/")
    for marker in ("/site-packages/", "/dist-packages/"):
        i = q.find(marker)
        if i >= 0:
            return q[i + 1:]
    for marker in ("/physicsanalysis_qt/", "/PyATCLI/"):
        i = q.rfind(marker)                              # the LAST one: a checkout's folder shares the package's name
        if i >= 0:
            return q[i + 1:]
    m = re.search(r"/_MEI\d+/(.*)", q)
    if m:
        return m.group(1)
    for prefix in {sys.base_prefix, sys.prefix}:
        pre = prefix.replace("\\", "/").rstrip("/") + "/"
        if prefix and q.startswith(pre):
            return "<python>/" + q[len(pre):]
    return q.rsplit("/", 1)[-1]


def scrub_traceback(text):
    """A formatted traceback with source paths cut down to their package and everything else scrubbed."""
    def frame(m):
        return f'File "{_display_source_path(m.group(1))}", line {m.group(2)}{m.group(3) or ""}'
    return scrub(_FRAME.sub(frame, text))


def format_exception(exc_type, exc, tb):
    """The scrubbed text of an exception, traceback first."""
    try:
        return scrub_traceback("".join(traceback.format_exception(exc_type, exc, tb)).rstrip("\n"))
    except Exception:                                    # noqa: BLE001 - formatting must never be what fails
        return f"{getattr(exc_type, '__name__', 'Error')}: (could not format)"


# ---------------------------------------------------------------------------
# Describing values without leaking them
# ---------------------------------------------------------------------------

def _is_pathy_key(key):
    """Whether a parameter's name says its value is a file or folder (`source_path`, `folder`, `out_dir`) —
    by name or suffix, so `peak_direction` and `source` are not mistaken for one."""
    k = key.lower()
    return k in _PATHY_NAMES or k.endswith(_PATHY_SUFFIXES)


def describe(value, key=""):
    """A value as it may appear in the log: scalars as they are, short numeric tuples (a window, a
    range), paths as tokens — and anything that could be data (an array, a table, a list, a dict, a long
    string) as its kind and size only. Never the contents."""
    if value is None or isinstance(value, (bool, int)):
        return repr(value)
    if isinstance(value, float):
        return format(value, ".6g")
    try:
        import numpy as np
        if isinstance(value, np.generic):
            return describe(value.item(), key)
        if isinstance(value, np.ndarray):
            return f"<ndarray shape={tuple(value.shape)} dtype={value.dtype}>"
    except ImportError:
        pass
    mod = type(value).__module__
    if mod.startswith("pandas"):
        shape = getattr(value, "shape", None)
        return f"<{type(value).__name__} {'x'.join(str(n) for n in shape) if shape else ''}>".replace(" >", ">")
    if isinstance(value, str):
        if _is_pathy_key(key) or os.path.isabs(value):
            return path_token(value)
        text = scrub(value)
        return repr(text if len(text) <= 60 else text[:57] + "...")
    if isinstance(value, (list, tuple)) and len(value) <= 4 and all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in value):
        return "(" + ", ".join(describe(v) for v in value) + ")"
    if isinstance(value, (list, tuple, set, frozenset)):
        return f"<{type(value).__name__} n={len(value)}>"
    if isinstance(value, dict):
        return f"<dict n={len(value)}>"
    return f"<{type(value).__name__}>"


def recording_loaded(cache):
    """Logs that a recording was opened — its kind and size, never its contents — and registers its name
    so the redactor hides it wherever it appears."""
    try:
        register_recording(cache.get("source_path"))
        x = cache.get("x")
        n = len(x) if x is not None else None
        action("recording_loaded", kind=cache.get("source"), n_samples=n, fs=cache.get("fs"),
               duration_s=round(float(x[-1] - x[0]), 3) if n else None)
    except Exception:                                    # noqa: BLE001 - logging a load must never fail it
        pass


def action(name, **params):
    """Logs something the user did or the app ran: `action("export", kind="png", dpi=300)` ->
    `ACTION export kind='png' dpi=300`. Parameters go through describe(), so no data and no names."""
    parts = " ".join(f"{k}={describe(v, k)}" for k, v in params.items())
    log.info("ACTION %s%s", name, (" " + parts) if parts else "")


# ---------------------------------------------------------------------------
# The log file
# ---------------------------------------------------------------------------

def default_log_dir():
    return Path.home() / ".physicsanalysis" / "logs"


def log_path():
    """The current log file, or None before start()."""
    return _S.log_dir / LOG_FILENAME if _S.log_dir else None


class _RedactFilter(logging.Filter):
    """Runs every record — ours and every library's — through scrub() before it is written."""

    def filter(self, record):
        try:
            record.msg = scrub(record.getMessage())
        except Exception:                                # noqa: BLE001
            record.msg = scrub(str(record.msg))
        record.args = None
        if record.exc_info:
            record.exc_text = format_exception(*record.exc_info)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = scrub_traceback(record.exc_text)
        return True


class _SessionHandler(logging.handlers.RotatingFileHandler):
    """Rotating file that writes the session header again after each rollover."""

    def doRollover(self):
        super().doRollover()
        try:
            self.stream.write(build_header(continued=True) + "\n")
            self.flush()
        except Exception:                                # noqa: BLE001
            pass

    def handleError(self, record):                       # a failed write must never take the app down
        pass


def _versions():
    try:
        from ..backend import api
        return api.software_versions({"name": "PyAT", "version": _S.app_version or "?"})
    except Exception:                                    # noqa: BLE001 - the header must not depend on the library importing
        return {"python": platform.python_version(), "implementation": platform.python_implementation(),
                "bits": 64 if sys.maxsize > 2 ** 32 else 32, "platform": platform.platform(),
                "frozen": bool(getattr(sys, "frozen", False)), "library": "unavailable", "packages": {},
                "app": {"name": "PyAT", "version": _S.app_version or "?"}}


def build_header(continued=False):
    """The text that opens a session: what is running and the settings that change behaviour."""
    v = _versions()
    qt = ""
    try:
        from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR
        qt = f"PyQt6 {PYQT_VERSION_STR}, Qt {QT_VERSION_STR}"
    except Exception:                                    # noqa: BLE001
        qt = "not loaded yet"
    pk = v.get("packages", {})
    s = _S.settings or {}
    settings = ", ".join(f"{k}={s[k]}" for k in HEADER_SETTINGS if k in s)
    out_set = "set" if s.get("output_folder") else "not set"
    started = datetime.fromtimestamp(_S.started_at).strftime("%Y-%m-%d %H:%M:%S") if _S.started_at else ""
    bar = "=" * 72
    prev = _S.previous
    if prev.get("crashed"):
        prev_text = "did not close normally" + (" (a native crash was recorded)" if prev.get("native") else "")
    else:
        prev_text = "closed normally (or this is the first run)"
    lines = [
        bar,
        f"PyAT session {_S.session_id} started {started}" + ("  [continued after log rotation]" if continued else ""),
        f"  PyAT            {v.get('app', {}).get('version', '?')} ({'frozen build' if v.get('frozen') else 'running from source'})",
        f"  PyATCLI  {v.get('library', '?')}",
        f"  Python          {v.get('python', '?')} ({v.get('implementation', '?')}, {v.get('bits', '?')}-bit)",
        f"  OS              {v.get('platform', '?')}",
        f"  Qt              {qt}",
        "  Packages        " + (", ".join(f"{k} {pk[k]}" for k in pk) or "none found"),
        f"  Settings        {settings}; output folder {out_set}",
        "  File names      " + ("included in this log (Options)" if _S.include_paths else "hidden: paths appear as <path-xxxxxx> tokens"),
        f"  Previous run    {prev_text}",
        bar,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sessions: did the last one end properly?
# ---------------------------------------------------------------------------

def _pid_alive(pid):
    if pid <= 0:
        return False
    if sys.platform.startswith("win"):
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            handle = k32.OpenProcess(0x1000, False, pid)             # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            try:
                code = ctypes.c_ulong()
                return bool(k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259    # STILL_ACTIVE
            finally:
                k32.CloseHandle(handle)
        except Exception:                                # noqa: BLE001
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _check_previous_sessions(log_dir):
    """Stale session locks (from a process that is gone) and a non-empty native-crash file mean the last
    run did not end properly. Returns {"crashed", "native", "sessions"} and clears what it found."""
    found = {"crashed": False, "native": "", "sessions": []}
    for lock in sorted(log_dir.glob("session-*.lock")):
        try:
            info = json.loads(lock.read_text(encoding="utf-8"))
        except Exception:                                # noqa: BLE001
            info = {}
        pid = int(info.get("pid", 0) or 0)
        if pid and pid != os.getpid() and _pid_alive(pid):
            continue                                     # another PyAT is running right now: not a crash
        if pid != os.getpid():
            found["crashed"] = True
            found["sessions"].append(info)
        try:
            lock.unlink()
        except OSError:
            pass
    native = log_dir / NATIVE_FILENAME
    try:
        if native.exists() and native.stat().st_size > 0:
            found["crashed"] = True
            found["native"] = format_exception_text_native(native.read_text(encoding="utf-8", errors="replace"))
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            native.rename(log_dir / f"native_crash.{stamp}.log")
            for old in sorted(log_dir.glob("native_crash.*.log"))[:-KEEP_NATIVE_ARCHIVES]:
                old.unlink()
    except OSError:
        pass
    return found


def format_exception_text_native(text):
    """faulthandler's output ("Windows fatal exception: access violation", stack of File lines) scrubbed."""
    return scrub_traceback(text.strip())


def _write_lock():
    path = _S.log_dir / f"session-{os.getpid()}.lock"
    try:
        path.write_text(json.dumps({"pid": os.getpid(), "session": _S.session_id,
                                    "started": datetime.fromtimestamp(_S.started_at).isoformat(timespec="seconds"),
                                    "version": _S.app_version}), encoding="utf-8")
        _S.lock_path = path
    except OSError:
        _S.lock_path = None


def mark_clean_exit():
    """The app is closing normally: remove this session's lock so the next start knows. Safe to call twice."""
    if _S.lock_path is not None:
        try:
            _S.lock_path.unlink()
        except OSError:
            pass
        _S.lock_path = None
    if _S.started and not _S.ended:
        _S.ended = True
        log.info("Session ended normally")


# ---------------------------------------------------------------------------
# Start / stop
# ---------------------------------------------------------------------------

def configure(settings):
    """Applies the settings the log depends on (the include-names choice); called at start and whenever
    Options changes them."""
    settings = settings or {}
    _S.settings = dict(settings)
    new = bool(settings.get(SETTINGS_KEY_PATHS, False))
    if new != _S.include_paths:
        _S.include_paths = new
        if _S.started:
            log.info("File and folder names in the log: %s", "included" if new else "hidden")


def _read_saved_settings():
    """The few settings the log needs, read straight from the settings file (so the log can start before
    the app's own settings load, and before anything heavy is imported)."""
    try:
        with open(Path.home() / ".physicsanalysis" / "settings.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                    # noqa: BLE001
        return {}


class _StreamToLog:
    """Stands in for a missing sys.stderr (a windowed build has none) so stray prints reach the log."""

    def __init__(self):
        self._buf = ""

    def write(self, text):
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                log.warning("stderr: %s", line)
        return len(text)

    def flush(self):
        pass

    def isatty(self):
        return False


def start(app_version=None, settings=None, log_dir=None, install_hooks=True):
    """Starts the error log: the rotating file and its header, the redaction setting, the exception
    hooks and faulthandler. Idempotent. Returns the log file's path.

    Meant to be the first thing the app runs, so nothing here may fail the app: every step that touches
    the disk or the process is guarded."""
    if _S.started:
        return log_path()
    _S.app_version = app_version
    _S.started_at = time.time()
    _S.session_id = secrets.token_hex(4)
    _S.log_dir = Path(log_dir) if log_dir else default_log_dir()
    saved = settings if settings is not None else _read_saved_settings()
    _S.settings = dict(saved)
    _S.include_paths = bool(saved.get(SETTINGS_KEY_PATHS, False))
    try:
        _S.log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    _S.previous = _check_previous_sessions(_S.log_dir) if _S.log_dir.is_dir() else _S.previous

    handler = _SessionHandler(str(_S.log_dir / LOG_FILENAME), maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
                              encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s [%(threadName)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    handler.addFilter(_RedactFilter())
    _S.handler = handler
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.WARNING)
    log.setLevel(logging.INFO)
    logging.captureWarnings(True)

    _S.header_text = build_header()
    try:
        handler.stream.write(_S.header_text + "\n")
        handler.flush()
    except Exception:                                    # noqa: BLE001
        pass
    _write_lock()
    atexit.register(mark_clean_exit)
    _S.started = True

    if install_hooks:
        _install_hooks()
    return log_path()


def _install_hooks():
    if sys.stderr is None:
        sys.stderr = _StreamToLog()
        _S.replaced_stderr = True
    try:
        _S.native_file = open(_S.log_dir / NATIVE_FILENAME, "a", encoding="utf-8")
        faulthandler.enable(file=_S.native_file, all_threads=True)
    except Exception:                                    # noqa: BLE001
        _S.native_file = None
    _S.hooks = (sys.excepthook, threading.excepthook, sys.unraisablehook)
    sys.excepthook = _excepthook
    threading.excepthook = _threading_excepthook
    sys.unraisablehook = _unraisablehook


def shutdown():
    """Stops the log and removes the hooks (for tests; the app just exits)."""
    if not _S.started:
        return
    mark_clean_exit()
    if _S.qt_handler:
        try:
            from PyQt6.QtCore import qInstallMessageHandler
            qInstallMessageHandler(None)
        except Exception:                                # noqa: BLE001
            pass
    if _S.replaced_stderr:
        sys.stderr = None
    if _S.hooks:
        sys.excepthook, threading.excepthook, sys.unraisablehook = _S.hooks
        try:
            faulthandler.disable()
        except Exception:                                # noqa: BLE001
            pass
    if _S.native_file is not None:
        try:
            _S.native_file.close()
        except OSError:
            pass
    root = logging.getLogger()
    if _S.handler is not None:
        root.removeHandler(_S.handler)
        _S.handler.close()
    atexit.unregister(mark_clean_exit)
    logging.captureWarnings(False)
    fresh = _State()
    _S.__dict__.clear()
    _S.__dict__.update(fresh.__dict__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ErrorInfo:
    """One caught error, ready to show or to put in a report. Everything in it is already scrubbed."""

    def __init__(self, exc_type, message, trace, source, signature):
        self.type = exc_type
        self.message = message
        self.traceback = trace
        self.source = source
        self.signature = signature
        self.time = datetime.now()


def _signature(exc_type, tb):
    last = traceback.extract_tb(tb)[-1] if tb is not None else None
    where = f"{last.filename}:{last.lineno}" if last else ""
    return f"{getattr(exc_type, '__name__', exc_type)}@{where}"


def _should_show(info, now=None):
    """Whether this error earns a dialog: not while one is already open, not the same error again within a
    while (an exception in a mouse-move handler fires hundreds of times a second), and not more than a few
    in a minute. Updates its own bookkeeping."""
    now = time.monotonic() if now is None else now
    with _S.lock:
        if _S.dialog_open:
            return False
        last = _S.recent.get(info.signature)
        _S.recent[info.signature] = now
        if last is not None and now - last < SAME_ERROR_QUIET_S:
            return False
        _S.dialog_times = [t for t in _S.dialog_times if now - t < DIALOG_WINDOW_S]
        if len(_S.dialog_times) >= DIALOG_MAX_IN_WINDOW:
            return False
        _S.dialog_times.append(now)
        return True


def handle_exception(exc_type, exc, tb, source="main thread", show=True):
    """Logs an exception, remembers it for "Save report", and (if it deserves one) shows the dialog.
    Never raises: a failure here would hide the failure it was reporting."""
    if getattr(_S.local, "busy", False):
        return None
    _S.local.busy = True
    try:
        text = format_exception(exc_type, exc, tb)
        name = getattr(exc_type, "__name__", "Error")
        message = scrub(str(exc))
        message = message if len(message) <= 300 else message[:297] + "..."
        info = ErrorInfo(name, message, text, source, _signature(exc_type, tb))
        _S.last_error = info
        log.critical("Unhandled exception in %s\n%s", source, text)
        try:
            _write_last_report(info)
        except Exception:                                # noqa: BLE001
            pass
        if show and _should_show(info):
            _dispatch(lambda: _show_error(info))
        elif show:
            log.info("(error dialog not shown: the same error, or too many, in a short time)")
        return info
    except Exception:                                    # noqa: BLE001
        try:
            if sys.__stderr__ is not None:
                traceback.print_exc(file=sys.__stderr__)
        except Exception:                                # noqa: BLE001
            pass
        return None
    finally:
        _S.local.busy = False


def _excepthook(exc_type, exc, tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    handle_exception(exc_type, exc, tb, source="main thread")


def _threading_excepthook(args):
    if args.exc_type is SystemExit:
        return
    handle_exception(args.exc_type, args.exc_value, args.exc_traceback,
                     source=f"thread {getattr(args.thread, 'name', '?')}")


def _unraisablehook(unraisable):
    if unraisable.exc_type is not None:
        handle_exception(unraisable.exc_type, unraisable.exc_value, unraisable.exc_traceback,
                         source=f"unraisable ({scrub(str(unraisable.err_msg or ''))})", show=False)


def report_caught(exc_type, exc, tb, source):
    """For code that catches an exception itself (a background worker turns it into a message for the
    user) but must not lose the traceback: logs it with its stack, without a dialog of its own."""
    if _S.started:
        try:
            log.error("Error in %s: %s\n%s", source, scrub(str(exc)), format_exception(exc_type, exc, tb))
            _S.last_error = ErrorInfo(getattr(exc_type, "__name__", "Error"), scrub(str(exc)),
                                      format_exception(exc_type, exc, tb), source, _signature(exc_type, tb))
        except Exception:                                # noqa: BLE001
            pass


def error(message, exc_info=False):
    """Logs an error the app already tells the user about (show_error), with the traceback if one is in
    flight."""
    if _S.started:
        log.error("%s", message, exc_info=sys.exc_info() if exc_info and sys.exc_info()[0] else None)


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def _recent_log_lines(max_lines=400):
    """The current session's lines from the log file (and the one before it if the session rolled over)."""
    if not _S.log_dir:
        return []
    lines = []
    for name in (LOG_FILENAME + ".1", LOG_FILENAME):
        path = _S.log_dir / name
        if path.exists():
            try:
                lines.extend(path.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                pass
    marker = f"PyAT session {_S.session_id} started"
    start_idx = next((i for i in range(len(lines) - 1, -1, -1) if marker in lines[i] and "continued" not in lines[i]), 0)
    start_idx = max(0, start_idx - 1)                    # the bar above the header
    mine = lines[start_idx:]
    return mine[-max_lines:] if len(mine) > max_lines else mine


def build_report(error=None, max_log_lines=400):
    """A plain-text problem report, ready to send: what ran, the error (if there is one), what happened
    before it, and how the last run ended. Holds no recording data; names are redacted unless the user
    chose to include them."""
    names = "included, as chosen in Options" if _S.include_paths else "hidden (shown as <path-xxxxxx> tokens)"
    out = [
        "PyAT problem report",
        f"Created {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "This file holds the steps taken in PyAT, its settings and the error details. It does not hold your",
        f"recording data. File and folder names are {names}.",
        "",
        _S.header_text or build_header(),
        "",
    ]
    err = error or _S.last_error
    if err is not None:
        out += ["--- The error " + "-" * 58, f"{err.type}: {err.message}", f"(in {err.source}, at {err.time.strftime('%H:%M:%S')})",
                "", err.traceback, ""]
    else:
        out += ["--- No error is attached: this report was saved on request. " + "-" * 12, ""]
    prev = _S.previous
    if prev.get("crashed"):
        out += ["--- The previous run did not close normally " + "-" * 29]
        if prev.get("native"):
            out += ["Native crash (from faulthandler):", prev["native"]]
        else:
            out += ["No native crash was recorded; PyAT was closed from outside or the computer stopped."]
        out.append("")
    out += ["--- Recent log (this session, oldest first) " + "-" * 29]
    out += _recent_log_lines(max_log_lines)
    text = "\n".join(out) + "\n"
    return text if _S.include_paths else scrub(text)


def _write_last_report(info):
    if _S.log_dir:
        (_S.log_dir / LAST_REPORT_FILENAME).write_text(build_report(info, max_log_lines=200), encoding="utf-8")


def save_report(path, error=None):
    """Writes build_report() to `path`; returns the path."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(build_report(error))
    log.info("ACTION save_report")
    return path


def open_log_folder():
    """Shows the log folder in the system file browser."""
    if not _S.log_dir:
        return
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(_S.log_dir))                # noqa: S606 - the app's own log folder
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", str(_S.log_dir)])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(_S.log_dir)])
    except Exception:                                    # noqa: BLE001
        log.warning("Could not open the log folder")


# ---------------------------------------------------------------------------
# The dialog (Qt) and getting it onto the GUI thread
# ---------------------------------------------------------------------------

def attach_app(app, window=None):
    """Called once the QApplication exists: lets the dialog be raised from any thread, routes Qt's own
    warnings into the log, and marks a clean exit when the app quits."""
    from PyQt6.QtCore import QObject, Qt, pyqtSignal, qInstallMessageHandler

    class _Dispatcher(QObject):
        call = pyqtSignal(object)

        def __init__(self):
            super().__init__()
            self.call.connect(lambda fn: fn(), Qt.ConnectionType.QueuedConnection)

    _S.dispatcher = _Dispatcher()
    _S.dispatcher.moveToThread(app.thread())
    _S.main_window = window
    qInstallMessageHandler(_qt_message)
    _S.qt_handler = True
    app.aboutToQuit.connect(mark_clean_exit)


def set_main_window(window):
    _S.main_window = window


def _dispatch(fn):
    """Runs fn on the GUI thread: through the dispatcher when there is one, straight away in tests, and
    through the operating system's own message box if Qt isn't up yet."""
    if _S.dialog_fn is not None:
        fn()
        return
    if _S.dispatcher is not None:
        _S.dispatcher.call.emit(fn)
        return
    _native_message("PyAT ran into a problem",
                    f"{(_S.last_error.type + ': ' + _S.last_error.message) if _S.last_error else ''}\n\n"
                    f"A report was saved to:\n{(_S.log_dir / LAST_REPORT_FILENAME) if _S.log_dir else 'the log folder'}\n\n"
                    "Please send that file to the developer.")


def _native_message(title, text):
    """A last-resort message box for a failure before Qt is available (Windows only; elsewhere the report
    file is all there is)."""
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
        except Exception:                                # noqa: BLE001
            pass


def _qt_message(msg_type, context, message):
    from PyQt6.QtCore import QtMsgType
    if msg_type in (QtMsgType.QtDebugMsg, QtMsgType.QtInfoMsg):
        return
    now = time.monotonic()
    last, when, repeats = _S.qt_last
    if message == last and now - when < 5.0:
        _S.qt_last = (last, when, repeats + 1)
        return
    if repeats:
        log.warning("Qt: (previous message repeated %d more times)", repeats)
    _S.qt_last = (message, now, 0)
    level = {QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
             QtMsgType.QtFatalMsg: logging.CRITICAL}.get(msg_type, logging.WARNING)
    log.log(level, "Qt: %s", message)


def _show_error(info):
    """The short modal message: what happened in a line, that the recordings are untouched, and a button to
    save a report."""
    if _S.dialog_fn is not None:
        _S.dialog_fn(info)
        return
    _S.dialog_open = True
    try:
        from PyQt6.QtWidgets import QMessageBox
        box = QMessageBox(_S.main_window)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("PyAT ran into a problem")
        box.setText("Something went wrong, so that action did not finish.")
        box.setInformativeText(
            f"{info.type}: {info.message}\n\n"
            "Your original recording files are untouched. If this keeps happening, save a report and send it "
            "to the developer. It holds the steps you took and this error, not your data.")
        save = box.addButton("Save report…", QMessageBox.ButtonRole.AcceptRole)
        keep = box.addButton("Continue", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(keep)
        box.setEscapeButton(keep)
        box.exec()
        if box.clickedButton() is save:
            save_report_dialog(_S.main_window, error=info)
    finally:
        _S.dialog_open = False


def save_report_dialog(parent=None, error=None):
    """Asks where to save the report, writes it, and says where it went."""
    from PyQt6.QtCore import QStandardPaths
    from PyQt6.QtWidgets import QFileDialog, QMessageBox

    docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation) or str(Path.home())
    name = f"PyAT problem report {datetime.now().strftime('%Y-%m-%d %H%M')}.txt"
    path, _ = QFileDialog.getSaveFileName(parent, "Save problem report", os.path.join(docs, name), "Text (*.txt)")
    if not path:
        return None
    try:
        save_report(path, error)
    except OSError as e:
        QMessageBox.warning(parent, "Could not save the report", str(e))
        return None
    done = QMessageBox(parent)
    done.setIcon(QMessageBox.Icon.Information)
    done.setWindowTitle("Report saved")
    done.setText("The report is saved. Please send this file to the developer:")
    done.setInformativeText(path)
    show = done.addButton("Show in folder", QMessageBox.ButtonRole.ActionRole)
    done.addButton("Close", QMessageBox.ButtonRole.RejectRole)
    done.exec()
    if done.clickedButton() is show:
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))
    return path


def offer_previous_report(parent=None):
    """After a start that follows a run that did not close normally: ask once whether to save a report
    about it. Returns True if the offer was shown."""
    if not _S.previous.get("crashed"):
        return False
    from PyQt6.QtWidgets import QMessageBox
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("PyAT did not close normally")
    box.setText("PyAT did not close normally last time.")
    box.setInformativeText("If something went wrong, a report helps the developer find out what. It holds what "
                           "PyAT logged before it stopped, not your data.")
    save = box.addButton("Save report…", QMessageBox.ButtonRole.AcceptRole)
    later = box.addButton("Not now", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(later)
    box.exec()
    _S.previous = {**_S.previous, "offered": True}
    if box.clickedButton() is save:
        save_report_dialog(parent)
    return True
