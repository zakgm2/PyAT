"""
PyAT (Python Analysis Tool) — entry point
-----------------------------------------
Entry point for the PyQt6 desktop app.

All the actual implementation lives in the physicsanalysis_qt/ package,
split by concern (app, loading, plot, edit, analysis, export, fieldstudy, UI
assembly) — see physicsanalysis_qt/__init__.py for the module map.

Do not run this from inside Spyder's console/Run button — Spyder's own
UI is built on PyQt5, and loading PyQt6 in the same process causes a
"DLL load failed while importing QtWidgets" crash. Launch it from a
plain terminal instead.
"""

import sys

# The frozen app is its own analysis engine: backend/runner.py starts `PyAT.exe --engine serve ...` (any
# PyATCLI command line works after --engine). Decided before anything else is imported: the engine
# needs neither Qt nor the error log, and it must answer on its standard output and nothing else.
if len(sys.argv) > 1 and sys.argv[1] == "--engine":
    import traceback
    try:
        from PyATCLI.cli import main as _library_main
        _status = _library_main(sys.argv[2:])
    except Exception:                                        # a bug: say so on stderr and end — a windowed program shows an unhandled
        if sys.stderr is not None:                           # exception in a dialog nobody can see, and waits for it forever
            traceback.print_exc()
        _status = 1
    sys.exit(_status)

from physicsanalysis_qt import __version__ as _app_version
from physicsanalysis_qt.app import errorlog

# The error log starts before anything heavy is imported, so a crash while importing it (a missing DLL, a
# broken install) is still caught and reported instead of the app closing without a word.
errorlog.start(app_version=_app_version)

from PyQt6.QtCore import QEventLoop, QTimer
from PyQt6.QtWidgets import QApplication

from physicsanalysis_qt.context import AppState
from physicsanalysis_qt.plot.plotting import apply_theme_to_canvas
from physicsanalysis_qt.splash import SplashScreen, app_icon
from physicsanalysis_qt.app.theme import apply_theme
from physicsanalysis_qt.ui.main_window import build_main_window
from physicsanalysis_qt.app.update_check import UpdateCheckWorker


def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())

    # Shown before any of the setup below so there's something on screen
    # immediately instead of a blank moment while the matplotlib/PyQtGraph
    # widgets and every dialog get built.
    splash = SplashScreen()
    splash.show()
    splash.pump()  # let the window manager actually paint it before the blocking setup below

    ctx = AppState(app)
    # The analysis engine is a second process that imports the numerical libraries (a second or two): started
    # now, it is ready by the time a file has been picked. It is stopped with the app.
    try:
        ctx.engine.start()
    except Exception as e:                                  # noqa: BLE001 — the first request that needs it will say why
        errorlog.action("engine_start_failed", error=str(e))
    app.aboutToQuit.connect(ctx.engine.shutdown)
    errorlog.configure(ctx.settings)
    errorlog.attach_app(app)
    apply_theme(app, ctx.settings.get("theme", "light"))

    update_worker = UpdateCheckWorker()
    update_result = {}
    update_worker.checked.connect(update_result.update)
    wait_loop = QEventLoop()
    update_worker.checked.connect(wait_loop.quit)
    QTimer.singleShot(5000, wait_loop.quit)  # don't hold up startup if GitHub is slow/unreachable/no internet
    update_worker.start()
    wait_loop.exec()

    # An available PyAT update swaps the splash itself into
    # the message + Download Update / Continue Anyway prompt (see
    # splash.py's prompt_update) rather than opening a second dialog —
    # this window is WindowStaysOnTopHint, so a separate QMessageBox
    # would've opened *behind* it, unreachable. No internet, GitHub
    # down, or already up to date all land here as a no-op: update_result
    # only ever has "outdated" set to True after a real successful
    # comparison against a fetched remote version, never as a fallback
    # for a failed check — see UpdateCheckWorker's own docstring.
    if update_result.get("outdated"):
        if not splash.prompt_update(update_result["message"]):
            return  # Download Update or the corner X was clicked; prompt_update already closed the splash
    ctx._update_check_worker = update_worker  # keeps it alive if it's still running past the timeout

    build_main_window(ctx)
    apply_theme_to_canvas(ctx)
    errorlog.set_main_window(ctx.win)

    splash.finish(ctx.win)
    ctx.win.show()
    # If the last run did not close normally, offer a report about it once the window is up.
    QTimer.singleShot(600, lambda: errorlog.offer_previous_report(ctx.win))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
