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

cancel_running(ctx) asks the engine to stop the request the window is waiting for (the progress toast's Cancel button, and Esc from the main
window, do it). The engine notices at its next progress report, so a task that is in one long call can go on for a long time: if it has not stopped
STOP_AFTER_S seconds later, or the button (now "Stop now") or Esc is pressed again, the engine process is ended (EngineClient.abort), which stops the
work at once and gives all its memory back. The request then fails with code "cancelled": on_error is not called for that (a "Cancelled" toast says
so), on_failure is. An ended engine took the recordings it held with it, so the recording on screen is opened again in the new one
(loading/common.reconnect_recording) and analyses go on working; the window keeps what it has, so nothing unsaved is lost.
"""

import concurrent.futures
import queue
import time

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal

from . import errorlog
from .toasts import ProgressToast, show_window_toast


STOP_AFTER_S = 4.0         # a cancel the engine has not acted on by then ends the engine


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
    toast = _new_toast(ctx, label, pump=False, cancellable=exclusive)
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
        reconnect = error.engine_ended and error.cancelled and not getattr(ctx, "_reconnecting", False)
        _deliver_failure(error)
        if reconnect:                                                   # the engine was ended to stop this: it took the recording with it
            from ..loading.common import reconnect_recording
            reconnect_recording(ctx)

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
    """Stops the request the window is waiting for, if there is one; returns True if there was one. The first call asks the engine to stop it (at
    its next progress report) and the toast says "Stopping…"; if it is still running STOP_AFTER_S seconds later, or this is called again, the
    engine is ended (abort_running)."""
    request = ctx._bg_request
    if request is None or request.done():
        return False
    if getattr(request, "stopping", False):
        return abort_running(ctx)
    request.stopping = True
    request.cancel()
    toast = getattr(ctx, "_progress_toast", None)
    if toast is not None and hasattr(toast, "stopping"):
        toast.stopping()
    QTimer.singleShot(int(STOP_AFTER_S * 1000), lambda: _stop_if_still_running(ctx, request))
    return True


def abort_running(ctx):
    """Ends the analysis engine to stop the request the window is waiting for (EngineClient.abort). Returns True if there was one to stop."""
    request = ctx._bg_request
    if request is None or request.done():
        return False
    errorlog.action("task_aborted", label=getattr(request, "method", None))
    return ctx.engine.abort(request)


def _stop_if_still_running(ctx, request):
    if ctx._bg_request is request and not request.done():
        abort_running(ctx)


def _new_toast(ctx, label, pump, cancellable=False):
    """A started ProgressToast for `label`, registered on ctx; None if there is no label. `cancellable` gives it the Cancel button (not while the
    work runs on the window's own thread: nothing could be clicked)."""
    if label is None:
        return None
    toast = ProgressToast(ctx, label, pump=pump, on_cancel=(lambda: cancel_running(ctx)) if cancellable and not pump else None)
    ctx._progress_toast = toast
    toast.start()
    return toast
