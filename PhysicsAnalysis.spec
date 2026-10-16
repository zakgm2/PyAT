# PhysicsAnalysis.spec
# ---------------------
# (This file keeps its old name — what actually ships is named by the
# name= arguments below: PyAT.exe / PyAT.app.)
#
# PyInstaller build spec for the PyQt6 desktop app, onefile mode — a
# single executable instead of a folder of DLLs/data files, so CI can
# upload/attach it directly with no zip step. Trade-off: onefile
# self-extracts to a temp dir on every launch, adding startup latency on
# top of matplotlib/pyqtgraph's own import cost.
#
# sentence-transformers/torch/transformers are excluded on purpose: they're
# only reachable via one lazy import inside PyATCLI's Text Field
# Study embedding feature, but PyInstaller's static scanner finds
# function-local imports too and would otherwise bundle the whole
# torch/transformers tree (hundreds of MB-1GB+) for a feature most builds
# of this app will never touch. That one function now catches the
# resulting ImportError and tells the user to `pip install
# sentence-transformers` if they want it — see PyATCLI's
# fieldstudy/study.py.
#
# One executable is both the window and the analysis engine: the window starts
# `PyAT.exe --engine serve ...` as a second process (run_qt.pyw sends --engine to
# PyATCLI's command line before it imports Qt), so nothing slow runs on the
# window's thread and the download is not doubled by a second program.
#
# Run with: pyinstaller PhysicsAnalysis.spec
#
# pathex: only needed on a machine where PyATCLI is editable-
# installed via a PEP 660 import-hook finder (not a plain sys.path
# entry) — PyInstaller's static analysis can't follow that redirect, so
# it needs the sibling repo's actual source directory to find/bundle it
# at all. CI installs PyATCLI as a normal (non-editable) package
# from PyPI, where PyInstaller finds it via site-packages with no help
# needed, so this only adds the local dev checkout's path when it's
# actually present on the machine running this build.
#
# icon: .ico is Windows-only; PyInstaller wants .icns on macOS (a bare
# .ico there is silently ignored). Picked per-platform below; add
# physicsanalysis_qt/assets/icon.icns to get a real icon on macOS builds.

import os
import sys

from PyInstaller.utils.hooks import copy_metadata

block_cipher = None

# Version stamps (a provenance record, the error log header, `PyAT.exe --engine info`) are read from
# installed-package metadata, which a frozen app only has if it is bundled: without these, every export
# made by the shipped app says its library and packages are "unknown".
_metadata = []
for _dist in ('PyATCLI', 'numpy', 'scipy', 'pandas', 'statsmodels', 'scikit-learn', 'matplotlib',
              'tdt', 'openpyxl', 'tqdm', 'PyQt6', 'pyqtgraph'):
    try:
        _metadata += copy_metadata(_dist)
    except Exception:                                    # not installed in this build environment: just absent
        pass

# the sibling checkout: its folder is PyATCLI, or PhysicsLibrary on a machine where it has not been renamed yet
_local_pyatcli = next((p for p in (r'C:\Users\zakgm\Desktop\Github\PyATCLI', r'C:\Users\zakgm\Desktop\Github\PhysicsLibrary')
                       if os.path.isdir(os.path.join(p, 'PyATCLI'))), None)
_pathex = [_local_pyatcli] if _local_pyatcli else []

if sys.platform == 'darwin':
    _icon_path = 'physicsanalysis_qt/assets/icon.icns'
    _icon = _icon_path if os.path.isfile(_icon_path) else None
else:
    _icon = 'physicsanalysis_qt/assets/icon.ico'

a = Analysis(
    ['run_qt.pyw'],
    pathex=_pathex,
    binaries=[],
    datas=[
        ('physicsanalysis_qt/assets', 'physicsanalysis_qt/assets'),
    ] + _metadata,
    # savefig() imports its backend by name at run time (importlib), which PyInstaller's static scan cannot see, and the
    # app itself only imports backend_qtagg: without these two, Export Figure, the group analysis's PDFs and Export
    # View fail in the shipped exe with "No module named 'matplotlib.backends.backend_pdf'" (PNG and TIFF go through
    # backend_agg, which backend_qtagg already pulls in). tests/test_packaging.py keeps this list in step with the
    # formats figures/render.py writes.
    hiddenimports=['matplotlib.backends.backend_pdf', 'matplotlib.backends.backend_svg'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['sentence_transformers', 'torch', 'transformers'],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PyAT',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=_icon,
)

if sys.platform == 'darwin':
    app = BUNDLE(
        exe,
        name='PyAT.app',
        icon=_icon,
        bundle_identifier='com.zakgm2.physicsanalysis',
    )
