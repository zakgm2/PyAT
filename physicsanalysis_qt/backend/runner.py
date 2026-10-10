"""
backend/runner.py
-----------------
Running PyATCLI as a separate program, which is how the app reaches its analysis code: the window never imports the numerical
libraries' work into its own process, so a slow load or fit cannot freeze it and a crash in one cannot take it down.

    library_command(*args)   the argv that runs `python -m PyATCLI *args` — in the frozen app, `PyAT.exe --engine *args`
    child_environment()      the environment the child runs in (UTF-8 streams, unbuffered)
    popen_options()          keyword arguments for subprocess.Popen: pipes, no console window on Windows
    CliRun(args)             one command, run once: `CliRun(["run", "zscore", folder, "--out", out]).start().result()` gives the --json result;
                             events (progress, warnings) arrive as it runs; cancel() stops it

A one-shot run pays the library's start-up (about a second) every time and forgets the recording when it ends, so the window uses it for
what is rare and self-contained; everything it does repeatedly goes through the long-lived engine (engine_client.py), which speaks the same
operations. Both report failures as BackendError.
"""

import json
import os
import subprocess
import sys
import threading
from concurrent.futures import Future

from .errors import BackendError

def _python():
    """The interpreter to run the library with: not pythonw (it has no standard streams to speak over)."""
    exe = sys.executable
    if os.name == "nt" and os.path.basename(exe).lower() == "pythonw.exe":
        console = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.exists(console):
            return console
    return exe


def launcher():
    """The start of the argv that runs the library's command line: `python -m PyATCLI`, or — in the frozen app, which has no Python
    to run it with — the app itself, whose entry point (run_qt.py) turns `PyAT.exe --engine <command line>` into the library's."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--engine"]
    return [_python(), "-m", "PyATCLI"]


def library_command(*args):
    return [*launcher(), *[str(a) for a in args]]


def child_environment(extra=None):
    env = dict(os.environ)
    env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    env.update(extra or {})
    return env


def popen_options(stdin=True):
    options = dict(stdin=subprocess.PIPE if stdin else subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=child_environment())
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW         # no console window flashing up beside the app
    return options


def _stderr_failure(text, returncode):
    """The BackendError a failed run's standard error holds: the --json error record if there is one, else its last lines."""
    lines = [line for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            doc = json.loads(line)
        except ValueError:
            continue
        if isinstance(doc, dict) and doc.get("ok") is False and isinstance(doc.get("error"), dict):
            return BackendError.from_info(doc["error"])
    tail = [line for line in lines if not line.startswith("{")][-6:]
    if returncode == 130:
        return BackendError("cancelled", code="cancelled")
    return BackendError("\n".join(tail) or f"the analysis engine stopped (exit status {returncode})", code="engine_stopped" if returncode else "bad_reply")


class CliRun:
    """One `python -m PyATCLI` command, run in a child process.

        run = CliRun(["run", "zscore", folder, "--out", out], on_event=print).start()
        result = run.result()          # the "result" of its --json document; BackendError if it failed

    `--json --events --no-input` are added: the result is one document, progress and warnings come as event dicts to `on_event(event)` (on
    a helper thread), and nothing waits for a person to answer. `future` completes with the result (or the BackendError).
    """

    def __init__(self, args, on_event=None, stdin_text=None, cwd=None):
        self.args = [str(a) for a in args]
        self.on_event = on_event
        self.stdin_text = stdin_text
        self.cwd = cwd
        self.future = Future()
        self.warnings = []
        self._proc = None
        self._cancelled = False
        self._lock = threading.Lock()

    def start(self):
        try:
            argv = library_command("--json", "--events", "--no-input", *self.args)
            self._proc = subprocess.Popen(argv, cwd=self.cwd, **popen_options(stdin=self.stdin_text is not None))
        except (BackendError, OSError) as e:
            self.future.set_exception(e if isinstance(e, BackendError) else BackendError(f"could not start the analysis engine: {e}", code="engine_unavailable"))
            return self
        threading.Thread(target=self._pump, name="cli-run", daemon=True).start()
        return self

    def result(self, timeout=None):
        return self.future.result(timeout)

    def cancel(self):
        """Stops the run: the process is ended, and the run's result is a BackendError with code "cancelled"."""
        with self._lock:
            self._cancelled = True
            proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()

    def _pump(self):
        try:
            self._pump_run()
        finally:
            for pipe in (self._proc.stdin, self._proc.stdout, self._proc.stderr):
                try:
                    if pipe is not None:
                        pipe.close()
                except OSError:
                    pass

    def _pump_run(self):
        proc = self._proc
        stderr_lines = []

        def read_events():
            for raw in proc.stderr:
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith("{"):
                    try:
                        event = json.loads(line)
                    except ValueError:
                        event = None
                    if isinstance(event, dict) and "event" in event:
                        if event["event"] == "warning":
                            self.warnings.append(event.get("text", ""))
                        if self.on_event is not None:
                            try:
                                self.on_event(event)
                            except Exception:                                              # noqa: BLE001 — a listener's bug is not the run's
                                pass
                        continue
                stderr_lines.append(line)

        reader = threading.Thread(target=read_events, name="cli-run-stderr", daemon=True)
        reader.start()
        try:
            if self.stdin_text is not None:
                try:
                    proc.stdin.write(self.stdin_text.encode("utf-8"))
                    proc.stdin.close()
                except OSError:
                    pass
            out = proc.stdout.read().decode("utf-8", errors="replace")
            code = proc.wait()
            reader.join(2)
        except Exception as e:                                                             # noqa: BLE001
            self.future.set_exception(BackendError(f"lost the analysis engine: {e}", code="engine_stopped"))
            return
        if self._cancelled:
            self.future.set_exception(BackendError("cancelled", code="cancelled"))
        elif code != 0:
            self.future.set_exception(_stderr_failure("\n".join(stderr_lines), code))
        else:
            try:
                doc = json.loads(out)
                result = doc["result"]
            except (ValueError, KeyError, TypeError):
                self.future.set_exception(BackendError("the analysis engine's answer could not be read", code="bad_reply",
                                                       hint=out[:200] or None))
                return
            self.future.set_result(result)


def run_cli(args, on_event=None, stdin_text=None, timeout=None, cwd=None):
    """Runs a command and waits for its result (do not call this on the window's thread for anything slow)."""
    return CliRun(args, on_event=on_event, stdin_text=stdin_text, cwd=cwd).start().result(timeout)
