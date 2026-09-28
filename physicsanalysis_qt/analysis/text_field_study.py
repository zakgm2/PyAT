"""
analysis/text_field_study.py
-------------------------------
Results viewer for the generic text-field-study pipeline (see
loaders/text_field_study.py and PhysicsLibrary.run_field_study_pipeline):
a table of the analysis columns (word counts, delta magnitude,
paired-similarity + null stats) plus CSV export of the full DataFrame —
same dialog + QTableWidget + export shape as analysis/intervals.py, the
most recent precedent in this codebase.
"""

import datetime

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView,
)

from ..context import export_file
from ..toasts import show_error
from ..window_fit import fit_to_screen


class FieldStudyResultsDialog(QDialog):
    """Table of the pipeline's per-subject analysis columns, plus
    full-DataFrame CSV export."""

    def __init__(self, ctx, df, config):
        super().__init__(ctx.win)
        self.ctx = ctx
        self.df = df
        self.setWindowTitle("Text Field Study Results")
        fit_to_screen(self, 900, 500)
        layout = QVBoxLayout(self)

        intro = QLabel(
            f"{len(df)} subject(s). One row per subject — sim_<pair> is that subject's "
            "similarity score for that comparison (0 = unrelated, 1 = same idea). Those "
            "numbers alone don't tell you if the pattern across all subjects is real — "
            "for that, click Run Statistical Validation below.\n"
            "Showing analysis columns only — export includes every field, including raw text."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # The raw text fields (long free-text) would make the grid
        # unwieldy — exclude exactly those (known from the config used
        # to run this pipeline), keep everything else the pipeline
        # computed (word counts, delta magnitude, similarities, null
        # stats) plus whatever non-text metadata fields came through.
        text_fields = set(config.get("text_fields", []))
        columns = [c for c in df.columns if c not in text_fields]

        table = QTableWidget(len(df), len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for r in range(len(df)):
            for c, col in enumerate(columns):
                value = df.iloc[r][col]
                text = f"{value:.4f}" if isinstance(value, float) else str(value)
                table.setItem(r, c, QTableWidgetItem(text))
        # Stretch mode forces every column to the same width regardless of
        # its content — with this many columns (word counts, quality
        # flags, delta, similarity, p-value, effect size, confound check
        # per pair) that squeezes long header names into columns far too
        # narrow to hold them, reading as overlapping/garbled text. Size
        # each column to what it actually needs instead, and let the
        # table scroll horizontally for the rest — same as the legend for
        # every other wide table in this app.
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(table)

        btn_row = QHBoxLayout()
        btn_csv = QPushButton("Export CSV")
        btn_csv.clicked.connect(self._export_csv)
        btn_row.addWidget(btn_csv)
        if config.get("paired_fields"):
            btn_validate = QPushButton("Run Statistical Validation")
            btn_validate.clicked.connect(self._run_validation)
            btn_row.addWidget(btn_validate)
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _run_validation(self):
        from .field_study_validation import launch_field_study_validation
        launch_field_study_validation(self.ctx)

    def _export_csv(self):
        ts = datetime.datetime.now().strftime("%H%M%S")
        export_file(self.ctx, self, "Export Text Field Study Results",
                     f"TextFieldStudyResults_{ts}.csv", "CSV (*.csv);;Text (*.txt)",
                     lambda path: self.df.to_csv(path, index=False),
                     recording_type="Text Field Study", recording_source=self.ctx.study_data_path)


def launch_field_study_results(ctx):
    if ctx.study_data is None:
        show_error(ctx, "No text field study loaded — use Text Field Study ▾ → 1. Open Study Folder first.")
        return
    dlg = FieldStudyResultsDialog(ctx, ctx.study_data, ctx.study_data_config or {})
    dlg.exec()
