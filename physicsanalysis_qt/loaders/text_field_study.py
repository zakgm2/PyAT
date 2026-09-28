"""
loaders/text_field_study.py
------------------------------
Generic text-field-study folder loading (see PhysicsLibrary's
run_field_study_pipeline). Unlike the signal-plot sources
(TDT/Oxysoft/Generic), the result is a pandas DataFrame, not an
x/y/markers cache — it's kept on its own ctx.study_data instead of
overloading ctx.cache, whose shape every plotting/marker/analysis
module downstream assumes. See analysis/text_field_study.py for the
results viewer this hands off to, and field_study_config.py for where
the (study-specific, never-committed) field configuration lives.

Field comparisons are set up inline right after picking a folder —
CompareFieldsDialog shows the actual field names found in that folder's
own files (via PhysicsLibrary.peek_fields) and lets you pick pairs of
fields to compare directly (e.g. "does field X track field Y for the
same subject") — no grouping concept, just pick two fields at a time.
"""

from PyQt6.QtWidgets import (
    QFileDialog, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTableWidget, QTableWidgetItem, QComboBox, QCheckBox, QLineEdit,
    QPushButton, QLabel, QGroupBox, QSpinBox,
)

import PhysicsLibrary as pl

from ..background import run_in_background
from ..field_study_config import load_config, save_config
from ..toasts import show_error, show_window_toast
from ..window_fit import scroll_body, fit_dialog_to_content


class CompareFieldsDialog(QDialog):
    """Shown right after picking a study folder: lists the actual field
    names found in that folder's own files (via PhysicsLibrary's
    peek_fields), and lets you build a list of field comparisons —
    pick any two fields + a name for that comparison, add as many as you
    want. Each comparison becomes one similarity score per subject
    (e.g. "does their answer to X track their answer to Y").

    Pre-fills from a previously saved config, if this folder's fields
    match one field-for-field."""

    def __init__(self, ctx, folder_path, fields):
        super().__init__(ctx.win)
        self.ctx = ctx
        self.folder_path = folder_path
        self.fields = fields
        self.setWindowTitle("Compare Fields")
        outer, layout, body = scroll_body(self)  # see window_fit.py

        existing = load_config()

        intro = QLabel(
            "For each pair you add below: does what a person wrote in Field 1 mean "
            "roughly the same thing as what they wrote in Field 2? Every subject gets "
            "a similarity score (0 = unrelated, 1 = same idea). Add as many pairs as "
            "you want compared.\n\n"
            f"Fields found in this folder: {', '.join(fields)}."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # ---- comparisons (pairs) --------------------------------------
        compare_box = QGroupBox("Compare")
        compare_layout = QVBoxLayout(compare_box)
        self.pair_table = QTableWidget(0, 3)
        self.pair_table.setHorizontalHeaderLabels(["Field 1", "Field 2", "Comparison name"])
        self.pair_table.horizontalHeader().setStretchLastSection(True)
        compare_layout.addWidget(self.pair_table)

        add_row = QHBoxLayout()
        self.new_pair_a = QComboBox()
        self.new_pair_a.addItems(fields)
        add_row.addWidget(self.new_pair_a)
        self.new_pair_b = QComboBox()
        self.new_pair_b.addItems(fields)
        if len(fields) > 1:
            self.new_pair_b.setCurrentIndex(1)
        add_row.addWidget(self.new_pair_b)
        self.new_pair_name = QLineEdit()
        self.new_pair_name.setPlaceholderText("comparison name")
        add_row.addWidget(self.new_pair_name)
        btn_add_pair = QPushButton("Add")
        btn_add_pair.clicked.connect(self._add_pair_row)
        add_row.addWidget(btn_add_pair)
        compare_layout.addLayout(add_row)

        btn_remove_pair = QPushButton("Remove Selected")
        btn_remove_pair.clicked.connect(self._remove_selected_pairs)
        compare_layout.addWidget(btn_remove_pair)
        layout.addWidget(compare_box)
        self._prefill_pairs(existing)

        # ---- optional delta vector (e.g. "how much did they change
        # between two related fields") --------------------------------
        delta_box = QGroupBox("Change Between Two Fields (optional)")
        delta_layout = QGridLayout(delta_box)
        self.chk_delta = QCheckBox("Also measure how much the response changes from one field to another")
        prior_delta = (existing or {}).get("delta_pair")
        self.chk_delta.setChecked(bool(prior_delta))
        delta_layout.addWidget(self.chk_delta, 0, 0, 1, 4)
        delta_layout.addWidget(QLabel("From:"), 1, 0)
        self.delta_from = QComboBox()
        self.delta_from.addItems(fields)
        if prior_delta and prior_delta[0] in fields:
            self.delta_from.setCurrentText(prior_delta[0])
        delta_layout.addWidget(self.delta_from, 1, 1)
        delta_layout.addWidget(QLabel("To:"), 1, 2)
        self.delta_to = QComboBox()
        self.delta_to.addItems(fields)
        if prior_delta and prior_delta[1] in fields:
            self.delta_to.setCurrentText(prior_delta[1])
        elif len(fields) > 1:
            self.delta_to.setCurrentIndex(1)
        delta_layout.addWidget(self.delta_to, 1, 3)
        layout.addWidget(delta_box)

        # ---- data quality -----------------------------------------------
        min_words_row = QHBoxLayout()
        min_words_row.addWidget(QLabel("Flag a field as low-quality if it's under:"))
        self.min_words = QSpinBox()
        self.min_words.setRange(0, 100)
        self.min_words.setValue((existing or {}).get("min_words", 5))
        min_words_row.addWidget(self.min_words)
        min_words_row.addWidget(QLabel("words"))
        min_words_row.addStretch(1)
        layout.addLayout(min_words_row)

        btn_row = QHBoxLayout()
        btn_run = QPushButton("Run")
        btn_run.setDefault(True)
        btn_run.clicked.connect(self.accept)
        btn_row.addWidget(btn_run)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        outer.addLayout(btn_row)

        fit_dialog_to_content(self, body, min_width=640)

    def _add_pair_row(self):
        field_a = self.new_pair_a.currentText()
        field_b = self.new_pair_b.currentText()
        if not field_a or not field_b:
            return
        if field_a == field_b:
            show_error(self.ctx, "Pick two different fields to compare.")
            return
        name = self.new_pair_name.text().strip() or f"{field_a}_{field_b}"
        row = self.pair_table.rowCount()
        self.pair_table.insertRow(row)
        self.pair_table.setItem(row, 0, QTableWidgetItem(field_a))
        self.pair_table.setItem(row, 1, QTableWidgetItem(field_b))
        self.pair_table.setItem(row, 2, QTableWidgetItem(name))
        self.new_pair_name.clear()

    def _remove_selected_pairs(self):
        rows = sorted({idx.row() for idx in self.pair_table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.pair_table.removeRow(r)

    def _prefill_pairs(self, existing):
        if not existing:
            return
        available = set(self.fields)
        for field_a, field_b, name in existing.get("paired_fields") or []:
            if field_a in available and field_b in available:
                row = self.pair_table.rowCount()
                self.pair_table.insertRow(row)
                self.pair_table.setItem(row, 0, QTableWidgetItem(field_a))
                self.pair_table.setItem(row, 1, QTableWidgetItem(field_b))
                self.pair_table.setItem(row, 2, QTableWidgetItem(name))

    def get_config(self):
        paired_fields = []
        for r in range(self.pair_table.rowCount()):
            paired_fields.append([
                self.pair_table.item(r, 0).text(),
                self.pair_table.item(r, 1).text(),
                self.pair_table.item(r, 2).text(),
            ])

        delta_pair = None
        if self.chk_delta.isChecked() and self.delta_from.currentText() and self.delta_to.currentText():
            delta_pair = [self.delta_from.currentText(), self.delta_to.currentText()]

        # word-count every field actually being compared — no reason to
        # word-count/quality-flag a field nobody's looking at.
        used_fields = set()
        for field_a, field_b, _ in paired_fields:
            used_fields.update([field_a, field_b])
        if delta_pair:
            used_fields.update(delta_pair)

        return {
            "text_fields": sorted(used_fields),
            "paired_fields": paired_fields,
            "delta_pair": delta_pair,
            "file_glob": "P-*.json",
            "min_words": self.min_words.value(),
        }


def open_field_study_folder(ctx):
    start_dir = ctx.last_dir or ctx.settings["default_folder"]
    path = QFileDialog.getExistingDirectory(ctx.win, "Open Text Field Study Folder", start_dir)
    if not path:
        return
    ctx.last_dir = path

    try:
        fields = pl.peek_fields(path)
    except Exception as e:
        show_error(ctx, str(e))
        return

    dlg = CompareFieldsDialog(ctx, path, fields)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return
    config = dlg.get_config()
    if not config["paired_fields"] and not config["delta_pair"]:
        show_error(ctx, "Add at least one field comparison, or a change-between-two-fields measurement.")
        return
    save_config(config)
    _load_field_study_folder(ctx, path, config)


def _load_field_study_folder(ctx, folder_path, config):
    from ..analysis.text_field_study import launch_field_study_results

    def _work(progress):
        return pl.run_field_study_pipeline(
            folder_path,
            text_fields=config["text_fields"],
            delta_pair=config.get("delta_pair"),
            paired_fields=config.get("paired_fields"),
            file_glob=config.get("file_glob", "P-*.json"),
            min_words=config.get("min_words", 5),
            progress=progress,
        )

    def _on_success(df):
        ctx.study_data = df
        ctx.study_data_path = folder_path
        ctx.study_data_config = config
        show_window_toast(ctx, f"Loaded {len(df)} subject(s)")
        launch_field_study_results(ctx)

    def _on_error(msg):
        show_error(ctx, msg)

    # Embedding every compared field plus a permutation null distribution is
    # real work, unlike a quick file parse — this can take a while, especially
    # the first run (downloads the sentence-transformers model), so the progress
    # toast walks through the steps ("Loading language model", ...).
    run_in_background(ctx, _work, _on_success, _on_error, label="Running text field study")
