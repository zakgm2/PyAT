"""
app/background.py
-----------------
Slow work, off the window's thread: a request to the analysis engine (backend/), a separate process that
holds the open recordings and runs PyATCLI's operations. Nothing of that work runs in this process,
so the window cannot freeze while it does, and a crash in a library cannot take the window with it.

    run_engine(ctx, "recording.open", {"path": folder}, on_success, on_error, label="Loading TDT folder")

on_success(result) / on_error(message) run on the GUI thread, after run_engine has returned (or, with
ctx.settings["background_loading"] off, before it returns: the window waits for the engine). Qt widgets
are only ever touched from those callbacks.

Progress: give run_engine a `label` and the request gets a progress toast (toasts.ProgressToast) with the
engine's live percentage and what it is doing. A caller that must tell failures apart gives on_failure(error)
instead of on_error: it gets the BackendError, whose .code says what kind of failure it was.

cancel_running(ctx) asks the engine to stop the request the window is waiting for (at its next progress
report; Esc does it from the main window); the request then fails with code "cancelled": on_error is not
called for that (a "Cancelled" toast says so), on_failure is.
"""

import concurrent.futures
import queue
import time

from PyQt6.QtCore import QObject, Qt, pyqtSignal

from . import errorlog
from .toasts import ProgressToast, show_window_toast


class _EngineBridge(QObject):
    """Carries an engine request's progress and answer from the engine client's reader thread to the GUI thread: a signal emitted from
    another thread is queued to the thread the receiving slot lives in."""
    progress = pyqtSignal(float, str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(object)                        # the BackendError


def run_engine(ctx, method, params, on_success, on_error=None, label=None, on_failure=None, exclusive=True):
    """
    Send the analysis engine the request `method` with `params` and deliver its answer via
    on_success(result) / on_error(message), both on the GUI thread, after this call has returned.
    A caller that must tell failures apart (a splice that leaves too little is not an engine that
    died) gives on_failure(error) instead of on_error: it gets the BackendError, whose .code says
    what kind of failure it was.

    If `label` is given, a progress toast with that title follows the engine's progress reports.
    Returns the backend Request (its .cancel() stops the work at its next progress report; the
    request then fails with code "cancelled"), or None if nothing was started.

    If ctx.settings["background_loading"] is off, waits right here for the answer (the toast, if
    any, repaints meanwhile) and then calls on_success/on_error.

    One engine request at a time from the window: a second call while one is running shows a toast
    and starts nothing. A request that is not what the person is waiting for — Save Changes, the
    provenance record beside an export — passes exclusive=False: it neither waits for nor blocks the
    one that is (the engine does them in the order they were sent), and Esc does not cancel it.
    """
    from ..backend import BackendError

    running = ctx._bg_request
    if exclusive and running is not None and not running.done():
        show_window_toast(ctx, "Something is already running — wait for it to finish first.")
        return None
    name = label or method
    errorlog.action("task_started", label=name)
    t0 = time.monotonic()

    def _failed(e):
        """The BackendError for whatever went wrong, logged."""
        if not isinstance(e, BackendError):
            e = BackendError(str(e), code="internal_error", type_name=type(e).__name__)
        if e.cancelled:
            errorlog.action("task_cancelled", label=name)
        else:
            errorlog.report_caught(type(e), e, e.__traceback__, f"engine request {method!r}")
        return e

    def _deliver_failure(error):
        if error.cancelled:                                             # the person asked for it: a toast, not an error box
            show_window_toast(ctx, "Cancelled")
            if on_failure is not None:
                on_failure(error)                                       # (a caller waiting on it has to know it is over)
        elif on_failure is not None:
            on_failure(error)
        elif on_error is not None:
            on_error(str(error))

    def _finished():
        errorlog.action("task_finished", label=name, seconds=round(time.monotonic() - t0, 2))

    if not ctx.settings.get("background_loading"):
        toast = _new_toast(ctx, label, pump=True)
        updates = queue.SimpleQueue()
        try:
            request = ctx.engine.request(method, params, on_progress=lambda f, m: updates.put((f, m)))
            if exclusive:
                ctx._bg_request = request
            while True:
                finished = bool(concurrent.futures.wait([request.future], timeout=0.02).done)
                while not updates.empty():                              # the toast is only ever touched from this thread
                    fraction, message = updates.get_nowait()
                    if toast is not None:
                        toast.update(fraction, message)
                if finished:
                    break
            result = request.future.result()
        except Exception as e:                                          # noqa: BLE001 — BackendError, or the request could not be sent
            error = _failed(e)
            if exclusive:
                ctx._bg_request = None
            if toast is not None:
                toast.finish()
            _deliver_failure(error)
            return None
        if exclusive:
            ctx._bg_request = None
        if toast is not None:
            toast.update(1.0, "Done")                                   # (the bar is seen full, whatever the engine last reported)
            toast.finish()
        _finished()
        on_success(result)
        return request

    bridge = _EngineBridge()
    queued = Qt.ConnectionType.QueuedConnection        # always after this call returns, even if the answer is already in

    def _hold(b):                                                       # keeps the bridge alive until it has delivered
        if exclusive:
            ctx._bg_bridge = b
        else:
            ctx._bg_extra.add(b)

    # The toast is wired up BEFORE on_success/on_error: it is gone before a success handler opens a dialog.
    toast = _new_toast(ctx, label, pump=False)
    if toast is not None:
        bridge.progress.connect(toast.update, queued)
        bridge.finished.connect(lambda _result: toast.update(1.0, "Done"), queued)     # (an analysis that reports nothing still ends at 100%)
        bridge.finished.connect(toast.finish, queued)
        bridge.failed.connect(toast.finish, queued)

    def _release():
        if not exclusive:
            ctx._bg_extra.discard(bridge)
        elif ctx._bg_bridge is bridge:                                  # (a request started since this one finished is not ours to forget)
            ctx._bg_request = None
            ctx._bg_bridge = None
        bridge.deleteLater()

    def _ok(result):
        _release()
        _finished()
        on_success(result)

    def _err(error):
        _release()
        _deliver_failure(error)

    bridge.finished.connect(_ok, queued)
    bridge.failed.connect(_err, queued)

    try:
        request = ctx.engine.request(method, params, on_progress=lambda f, m: bridge.progress.emit(f, m))
    except Exception as e:                                              # noqa: BLE001 — the engine could not be started
        error = _failed(e)
        _hold(bridge)
        bridge.failed.emit(error)
        return None

    def _done(future):                                                  # on the engine client's reader thread
        error = future.exception()
        if error is None:
            bridge.finished.emit(future.result())
        else:
            bridge.failed.emit(_failed(error))

    if exclusive:
        ctx._bg_request = request
    _hold(bridge)
    request.future.add_done_callback(_done)
    return request


def cancel_running(ctx):
    """Asks the engine to stop the request the window is waiting for, if there is one. Returns True if there was one."""
    request = ctx._bg_request
    if request is None or request.done():
        return False
    request.cancel()
    return True


def _new_toast(ctx, label, pump):
    """A started ProgressToast for `label`, registered on ctx; None if there is no label."""
    if label is None:
        return None
    toast = ProgressToast(ctx, label, pump=pump)
    ctx._progress_toast = toast
    toast.start()
    return toast
