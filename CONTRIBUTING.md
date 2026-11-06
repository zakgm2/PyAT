# Contributing to PyAT

Thank you for looking. PyAT is a small project with one maintainer, so here is what to expect and how to make a change easy to accept.

## Reporting a problem or asking a question
- Open an issue at https://github.com/zakgm2/PyAT/issues. For a problem, say which version you have (the window title shows it, or `PyAT.exe --engine info --json`), what you did, and what you expected. If an error dialog or the error log is involved, attach it; for a wrong number, say which recording type and settings.
- Please do not post data you are not allowed to share.
- Expect a first reply within about a week. This is research software maintained alongside a degree; replies can be slower in exam periods.

## Changing the code
1. Fork, branch from `main`, and keep the change to one thing.
2. Run the tests before you open a pull request:
   ```bash
   QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -t .
   ```
   (On Windows PowerShell: `$env:QT_QPA_PLATFORM="offscreen"` first.) They take a few minutes; the app's tests also run on every pull request against the library at its minimum, newest and development versions.
3. A fix should come with a test that fails without it; a new feature should come with tests of what it does.
4. Match the surrounding code: names, comment density, and how errors are reported to the user.
5. Computation belongs in the library, [PyATCLI](https://github.com/zakgm2/PyATCLI); this repository is the window, the plots and the figures. The app only reaches the library through `physicsanalysis_qt/backend/` (a test enforces it).
6. Add a line under `## Unreleased` in `CHANGELOG.md`.

## Licence
By contributing you agree that your contribution is released under the project's licence, AGPL-3.0-only (see `LICENSE`).

## Citing
See `CITATION.cff`, or the "Cite this repository" button on GitHub.
