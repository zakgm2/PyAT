"""
background.py
--------------
Off-main-thread execution for slow, pure-compute work (parsing a large
TDT tank or Oxysoft export), on by default via
ctx.settings["background_loading"] (see Options dialog for when to turn
it off).

Qt widgets must only be touched from the main thread, so `fn` must be pure
compute (no ctx.win/ctx.ax/etc access) — the result is handed back to
on_success/on_error, which run on the main thread via Qt's queued signal
delivery, safe to touch widgets from there.

Progress: give run_in_background a `label` and the action gets a progress
toast (toasts.ProgressToast) with a live percentage, and `fn` is called as
fn(progress) instead of fn(). `progress` is what PhysicsLibrary's slow
functions take as their own `progress=` argument (see PhysicsLibrary.progress),
so it is usually just handed straight through:

    def _work(progress):
        return pl.process_tdt_folder(path, progress=progress)

    run_in_background(ctx, _work, on_success, on_error, label="Loading TDT folder")

run_with_progress is the same thing for work that has to run right here on the
GUI thread (Splice re-fits ΔF/F before the plot can redraw).
"""

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from .toasts import ProgressToast, show_window_toast


class _Worker(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)
    progress = pyqtSignal(float, str)

    def __init__(self, fn, wants_progress=False):
        super().__init__()
        self.fn = fn
        self.wants_progress = wants_progress

    def report(self, fraction, message=""):
        """The `progress` callable handed to fn: runs on the worker thread, and turns each
        call into a queued signal so the toast is only ever touched on the GUI thread."""
        self.progress.emit(float(fraction), str(message))

    def run(self):
        try:
            result = self.fn(self.report) if self.wants_progress else self.fn()
        except Exception as e:
            self.failed.emit(str(e))
        else:
            self.finished.emit(result)


def run_in_background(ctx, fn, on_success, on_error=None, label=None):
    """
    Run fn() and deliver its result via on_success(result) / on_error(msg).

    If `label` is given, a progress toast with that title is shown while it
    runs and fn is called as fn(progress) — see the module docstring.

    If ctx.settings["background_loading"] is off, runs synchronously
    (identical to calling fn() directly; the progress toast, if any, repaints
    between the reports fn makes).

    Refuses to start a second background load while one is already
    running — ctx._bg_thread/_bg_worker hold only one load's references at
    a time, so a second call while busy would silently orphan the first
    thread (it keeps running with nothing left tracking it) rather than
    queuing or erroring cleanly.
    """
    if not ctx.settings.get("background_loading"):
        toast = _new_toast(ctx, label, pump=True)
        try:
            result = fn(toast.update) if toast is not None else fn()
        except Exception as e:
            if toast is not None:
                toast.finish()
            if on_error:
                on_error(str(e))
        else:
            if toast is not None:
                toast.finish()
            on_success(result)
        return

    if ctx._bg_thread is not None and ctx._bg_thread.isRunning():
        show_window_toast(ctx, "A file is already loading — wait for it to finish first.")
        return

    thread = QThread()
    worker = _Worker(fn, wants_progress=label is not None)
    worker.moveToThread(thread)

    # The progress toast is wired up BEFORE on_success/on_error: Qt runs a signal's slots in
    # the order they were connected, so the toast is gone before a success handler opens a
    # dialog (or replaces it with its own toast) rather than sitting behind it.
    toast = _new_toast(ctx, label, pump=False)
    if toast is not None:
        worker.progress.connect(toast.update)
        worker.finished.connect(toast.finish)
        worker.failed.connect(toast.finish)

    # thread.finished only fires once the QThread has actually stopped
    # running (i.e. after thread.quit() below has taken effect) — dropping
    # ctx's references to it any earlier (e.g. in the worker.finished
    # handler) frees the last Python reference to a QThread that Qt still
    # considers alive, which is a hard "QThread: Destroyed while thread is
    # still running" abort with no Python traceback, not a catchable
    # exception. Keep ctx._bg_thread/_bg_worker alive until here.
    def _cleanup():
        # thread.finished is emitted by the worker thread at the START of its own shutdown, which
        # then still deletes `worker` (worker.deleteLater below), and that needs the GIL. Dropping
        # the last reference to the QThread from here (GUI thread, GIL held) makes Qt wait for that
        # shutdown to end while nothing can hand it the GIL: the window freezes right after a load
        # (a stress test of back-to-back trivial jobs did it within 50 runs, every time). wait()
        # gives up the GIL while it waits, so the shutdown can finish first.
        thread.wait()
        ctx._bg_thread = None
        ctx._bg_worker = None

    thread.started.connect(worker.run)
    worker.finished.connect(on_success)
    if on_error:
        worker.failed.connect(on_error)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.finished.connect(_cleanup)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)

    # Keep references alive on ctx so they aren't garbage-collected mid-run.
    ctx._bg_thread = thread
    ctx._bg_worker = worker
    thread.start()


def run_with_progress(ctx, label, fn):
    """Run fn(progress) right here on the GUI thread, with a progress toast, and return its result.

    For work that has to happen in place (Splice re-fits ΔF/F before the plot can redraw). The
    toast repaints between the reports fn makes, but the window can't be clicked meanwhile.
    """
    toast = _new_toast(ctx, label, pump=True)
    try:
        return fn(toast.update)
    finally:
        toast.finish()


def _new_toast(ctx, label, pump):
    """A started ProgressToast for `label`, registered on ctx; None if there is no label."""
    if label is None:
        return None
    toast = ProgressToast(ctx, label, pump=pump)
    ctx._progress_toast = toast
    toast.start()
    return toast
