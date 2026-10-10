"""
backend/engine_client.py
------------------------
The window's side of the analysis engine (`python -m PyATCLI serve`, see PyATCLI/engine/server.py): a long-lived child process
that holds the open recordings and runs the operations, spoken to in JSON lines over its standard input and output.

    client = EngineClient()                       # nothing starts yet
    client.start()                                # starts the process (returns at once: the process is still importing the libraries)
    request = client.request("recording.open", {"path": folder}, on_progress=lambda fraction, message: ...)
    request.future.result()                       # or request.future.add_done_callback(...); request.cancel() stops it
    client.shutdown()

Everything is asynchronous: `request` returns at once with a Request whose `future` completes with the result (or a BackendError), and
progress, warnings and notes are handed to the callbacks as they arrive. The callbacks run on the client's reader thread, never on the
caller's: a Qt window forwards them as signals (background.run_engine does). One request runs at a time in the engine, in the order they
were sent; a cancel is cooperative (the engine stops at its next progress report).

If the engine dies the pending requests fail with a BackendError (code "engine_stopped") and the next request starts a new one — which has
no recordings open, so `generation` goes up and a caller holding a recording id can tell that it is gone.

`EngineClient(thread_transport)` runs the same server on a thread of this process, over the same pipes and the same JSON — for tests and
for debugging with a debugger attached (PYAT_ENGINE=inprocess); nothing but the process boundary differs.
"""

import atexit
import io
import json
import os
import subprocess
import sys
import threading
import weakref
from collections import deque
from concurrent.futures import Future

from .errors import BackendError
from .contract import check_ready
from .runner import library_command, popen_options

READY_TIMEOUT_S = 90.0         # a cold start imports numpy, pandas, scipy, sklearn ... (a second or two; a virus scanner can make it many)


def _jsonable(value):
    """json.dumps's `default`: what a request may hold besides JSON — numpy numbers and arrays, paths."""
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, (set, frozenset, tuple)):
        return list(value)
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    raise TypeError(f"{type(value).__name__} cannot be sent to the analysis engine")


# ---------------------------------------------------------------------------
# Transports: where the server is
# ---------------------------------------------------------------------------

class _Pipes:
    """What both transports share: the three pipes (stdin to write requests, stdout to read answers, stderr to read what it complains about)
    and how they are let go of."""

    def close_input(self):
        try:
            self.stdin.close()
        except OSError:
            pass

    def close(self):
        """Lets go of the pipes once the server has ended."""
        for pipe in (self.stdin, self.stdout, self.stderr):
            try:
                pipe.close()
            except OSError:
                pass


class ProcessTransport(_Pipes):
    """The server as a child process."""

    def __init__(self, argv=None, data_dir=None, app_name="PyAT", app_version=None, verbose=False):
        if argv is None:
            argv = library_command("serve", "--app-name", app_name, *(["--app-version", app_version] if app_version else []),
                                   *(["--data-dir", data_dir] if data_dir else []), *(["--verbose"] if verbose else []))
        try:
            self.proc = subprocess.Popen(argv, **popen_options())
        except OSError as e:
            raise BackendError(f"could not start the analysis engine: {e}", code="engine_unavailable") from e
        self.stdin, self.stdout, self.stderr = self.proc.stdin, self.proc.stdout, self.proc.stderr

    def poll(self):
        return self.proc.poll()

    def wait(self, timeout):
        try:
            return self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            return None

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()


class ThreadTransport(_Pipes):
    """The server on a thread of this process, over OS pipes: the same bytes in the same order, minus the second process."""

    def __init__(self, data_dir=None, app_name="PyAT", app_version=None):
        from PyATCLI.engine.server import serve

        to_server_r, to_server_w = os.pipe()
        from_server_r, from_server_w = os.pipe()
        self.stdin = os.fdopen(to_server_w, "wb")
        self.stdout = os.fdopen(from_server_r, "rb")
        self.stderr = io.BytesIO()
        self._server_in = os.fdopen(to_server_r, "rb")
        self._server_out = os.fdopen(from_server_w, "w", encoding="utf-8", newline="\n")
        self._errors = io.StringIO()
        self._code = None
        app = {"name": app_name, **({"version": app_version} if app_version else {})}

        def run():
            try:
                serve(self._server_in, self._server_out, self._errors, data_dir=data_dir, app=app)
                self._code = 0
            except BaseException:                                                          # noqa: BLE001 — whatever it was, the client sees EOF
                self._code = 1
            finally:
                for f in (self._server_out, self._server_in):
                    try:
                        f.close()
                    except OSError:
                        pass

        self.thread = threading.Thread(target=run, name="engine-thread", daemon=True)
        self.thread.start()

    def poll(self):
        return self._code if not self.thread.is_alive() else None

    def wait(self, timeout):
        self.thread.join(timeout)
        return self.poll()

    def kill(self):                                                                         # a thread cannot be killed: let go of its input
        self.close_input()


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class Request:
    """One request in flight: its `future` completes with the operation's result or a BackendError."""

    def __init__(self, link, request_id, method, on_progress=None, on_event=None):
        self.id = request_id
        self.method = method
        self.future = Future()
        self._link = link
        self._on_progress = on_progress
        self._on_event = on_event

    def result(self, timeout=None):
        return self.future.result(timeout)

    def done(self):
        return self.future.done()

    def cancel(self):
        """Asks the engine to stop this request (at its next progress report). The future then fails with code "cancelled"."""
        if not self.future.done():
            try:
                self._link.send({"cancel": self.id})
            except (OSError, ValueError):                    # the engine is gone: the request fails on its own
                pass


class _Link:
    """One launch of the engine: its transport, the requests waiting on it, what it said it is, what it said on stderr."""

    def __init__(self, transport, generation):
        self.transport = transport
        self.generation = generation
        self.pending = {}
        self.ready = None
        self.ready_event = threading.Event()
        self.stderr = deque(maxlen=60)
        self.closing = False
        self.dead = False
        self.write_lock = threading.Lock()
        self.stderr_thread = None

    def send(self, message):
        line = json.dumps(message, default=_jsonable, ensure_ascii=True) + "\n"
        with self.write_lock:
            self.transport.stdin.write(line.encode("utf-8"))
            self.transport.stdin.flush()


class EngineClient:
    def __init__(self, transport_factory=None, app_name="PyAT", app_version=None, data_dir=None, verbose=False):
        self._factory = transport_factory or (lambda: ProcessTransport(data_dir=data_dir, app_name=app_name, app_version=app_version, verbose=verbose))
        self._lock = threading.RLock()
        self._link = None
        self._generation = 0
        self._next_id = 0
        self._atexit = False
        self._unfit = None            # (message, hint) once an engine said it does not fit this app (backend/contract.py)

    # -- lifecycle ---------------------------------------------------------------------------------------------------------------------

    @property
    def generation(self):
        """How many times the engine has been started: a recording opened under another generation is gone."""
        return self._generation

    @property
    def running(self):
        link = self._link
        return link is not None and not link.dead and link.transport.poll() is None

    def start(self):
        """Starts the engine if it is not running. Returns at once; `wait_ready` waits until it can answer."""
        with self._lock:
            self._current()
        return self

    def wait_ready(self, timeout=READY_TIMEOUT_S):
        """The engine's ready message ({"protocol", "library", "pid", "data_dir", "operations"}), waiting for it to finish starting."""
        link = self._current()
        if not link.ready_event.wait(timeout):
            raise BackendError("the analysis engine did not start in time", code="engine_unavailable", hint=self._tail(link) or None)
        self._refuse_unfit()
        if link.ready is None:
            raise BackendError(*self._stopped(link))
        return link.ready

    def _refuse_unfit(self):
        if self._unfit is not None:
            raise BackendError(self._unfit[0], code="incompatible_engine", hint=self._unfit[1])

    @property
    def operations(self):
        link = self._link
        return list(link.ready["operations"]) if link is not None and link.ready else []

    def shutdown(self, timeout=5.0):
        """Asks the engine to finish and exit, and waits for it; ends it if it will not."""
        with self._lock:
            link, self._link = self._link, None
        if link is None or link.dead:
            return
        link.closing = True
        try:
            link.send({"method": "shutdown"})
        except (OSError, ValueError):
            pass
        link.transport.close_input()
        if link.transport.wait(timeout) is None:
            link.transport.kill()
            link.transport.wait(2.0)

    def restart(self):
        self.shutdown()
        return self.start()

    def _current(self):
        with self._lock:
            self._refuse_unfit()                              # an engine that does not fit is not started again: every request says why
            link = self._link
            if link is None or link.dead or link.transport.poll() is not None:
                self._generation += 1
                link = _Link(self._factory(), self._generation)
                self._link = link
                link.stderr_thread = threading.Thread(target=self._read_stderr, args=(link,), name="engine-stderr", daemon=True)
                link.stderr_thread.start()
                threading.Thread(target=self._read, args=(link,), name="engine-reader", daemon=True).start()
                if not self._atexit:
                    self._atexit = True
                    atexit.register(_shutdown_quietly, weakref.ref(self))
            return link

    # -- requests ----------------------------------------------------------------------------------------------------------------------

    def request(self, method, params=None, on_progress=None, on_event=None):
        """Sends one request and returns its Request at once. `on_progress(fraction, message)` and `on_event(name, fields)` are called
        (on the reader thread) as the engine reports."""
        with self._lock:
            link = self._current()
            self._next_id += 1
            req = Request(link, self._next_id, method, on_progress, on_event)
            link.pending[req.id] = req
        try:
            link.send({"id": req.id, "method": method, "params": params or {}})
        except TypeError as e:
            link.pending.pop(req.id, None)
            req.future.set_exception(BackendError(str(e), code="bad_parameter"))
        except (OSError, ValueError):
            link.pending.pop(req.id, None)
            req.future.set_exception(BackendError(*self._stopped(link)))
        else:
            if link.dead and link.pending.pop(req.id, None) is not None:     # the engine ended while this was being sent: nobody will answer
                req.future.set_exception(BackendError(*self._stopped(link)))
        return req

    def call(self, method, params=None, timeout=None, on_progress=None, on_event=None):
        """A request, waited for: the result, or a BackendError."""
        return self.request(method, params, on_progress=on_progress, on_event=on_event).result(timeout)

    # -- the engine's replies ----------------------------------------------------------------------------------------------------------

    def _read(self, link):
        try:
            for raw in link.transport.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except ValueError:
                    link.stderr.append(f"(not protocol) {line[:200]}")
                    continue
                if isinstance(message, dict):
                    self._dispatch(link, message)
        except (OSError, ValueError):
            pass
        finally:
            self._finished(link)

    def _read_stderr(self, link):
        try:
            for raw in link.transport.stderr:
                link.stderr.append(raw.decode("utf-8", errors="replace").rstrip())
        except (OSError, ValueError):
            pass

    def _dispatch(self, link, message):
        event = message.get("event")
        if event == "ready":
            link.ready = message
            unfit = check_ready(message)
            if unfit is not None:
                self._unfit = unfit                           # (first: a request made from now on is refused in _current)
                link.closing = True
                refusal = BackendError(unfit[0], code="incompatible_engine", hint=unfit[1])
                while link.pending:
                    try:
                        _, req = link.pending.popitem()
                    except KeyError:
                        break
                    if not req.future.done():
                        req.future.set_exception(refusal)
                link.ready_event.set()
                link.transport.close_input()                  # it has nothing to do for this app: it ends
                return
            link.ready_event.set()
            return
        if event == "bye":
            return
        request_id = message.get("id")
        if event == "result":
            req = link.pending.pop(request_id, None)
            if req is not None:
                req.future.set_result(message.get("result"))
        elif event == "error":
            req = link.pending.pop(request_id, None)
            if req is not None:
                req.future.set_exception(BackendError.from_info(message.get("error")))
            else:
                link.stderr.append(f"(engine) {(message.get('error') or {}).get('message')}")
        else:
            req = link.pending.get(request_id)
            if req is None:
                return
            fields = {k: v for k, v in message.items() if k not in ("id", "event")}
            try:
                if event == "progress" and req._on_progress is not None:
                    req._on_progress(float(fields.get("fraction", 0.0)), str(fields.get("message", "")))
                if req._on_event is not None:
                    req._on_event(event, fields)
            except Exception:                                                              # noqa: BLE001 — a listener's bug must not end the reader
                link.stderr.append("(listener failed) " + repr(sys.exc_info()[1]))

    def _finished(self, link):
        """The engine's output ended: it exited (or was ended). Everything still waiting fails."""
        link.dead = True                                    # first: a request made from now on sees it (see request())
        link.transport.wait(2.0)
        thread = link.stderr_thread
        if thread is not None:
            thread.join(1.0)
        link.ready_event.set()
        link.transport.close()
        message, code, hint = self._stopped(link)
        while link.pending:
            try:
                _, req = link.pending.popitem()
            except KeyError:
                break
            if not req.future.done():
                req.future.set_exception(BackendError(message, code=code, hint=hint))

    def _tail(self, link):
        return "\n".join(line for line in list(link.stderr)[-8:] if line)

    def _stopped(self, link):
        """(message, code, hint) for requests that found the engine gone."""
        if link.closing:
            return "the analysis engine was shut down", "engine_stopped", None
        tail = self._tail(link)
        if link.ready is None:
            return ("the analysis engine could not start" + (f":\n{tail}" if tail else ""), "engine_unavailable",
                    "check that PyATCLI is installed for the Python that runs PyAT")
        return ("the analysis engine stopped unexpectedly" + (f":\n{tail}" if tail else ""), "engine_stopped",
                "it restarts on its own, but the recordings it held are gone: open them again")


def _shutdown_quietly(ref):
    client = ref()
    if client is not None:
        try:
            client.shutdown(timeout=3.0)
        except Exception:                                                                  # noqa: BLE001 — at exit there is nobody to tell
            pass


def thread_engine(data_dir=None, app_name="PyAT", app_version=None):
    """An EngineClient whose server runs on a thread of this process (tests, debugging)."""
    return EngineClient(lambda: ThreadTransport(data_dir=data_dir, app_name=app_name, app_version=app_version))


def make_engine(kind=None, **options):
    """The engine the app uses: a child process, or — PYAT_ENGINE=inprocess — a thread of this one."""
    kind = (kind or os.environ.get("PYAT_ENGINE") or "process").strip().lower()
    try:
        from .. import __version__ as version
    except ImportError:
        version = None
    options.setdefault("app_version", version)
    if kind in ("inprocess", "thread"):
        return thread_engine(**{k: v for k, v in options.items() if k in ("data_dir", "app_name", "app_version")})
    return EngineClient(**options)
