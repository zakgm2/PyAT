"""
markers.py
----------
Add/Edit Marker dialog, marker placement, nearest-marker lookup, and the
right-click rename/delete context menu.
"""

import numpy as np
from PyQt6.QtWidgets import (
    QDialog, QGridLayout, QVBoxLayout, QLabel, QLineEdit, QWidget, QHBoxLayout,
    QRadioButton, QButtonGroup, QPushButton, QMenu, QGroupBox, QCheckBox,
    QListWidget, QListWidgetItem, QAbstractItemView,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer

import PhysicsLibrary as pl

from . import undo
from .context import _MARKER_COLORS
from .marker_labels import store_display_name
from .toasts import show_error, show_success, show_window_toast
from .window_fit import scroll_body, fit_dialog_to_content


class MarkerDialog(QDialog):
    """Add-or-edit marker dialog: name, colour radio group, font size.

    When editing a marker that belongs to a store (pass store_id), an
    extra "Rename all '<store>' markers" checkbox appears — checked
    (default), the new name is remembered as that store's display name
    and applies to every marker from that store, past and future;
    unchecked, only this one marker instance is renamed."""

    def __init__(self, ctx, title, initial_label="Marker",
                 initial_color="green", initial_fontsize=8, store_id=None):
        super().__init__(ctx.win)
        self.ctx = ctx
        self.store_id = store_id
        self.reset_requested = False
        self.setWindowTitle(title)
        self.setModal(True)
        layout = QGridLayout(self)

        layout.addWidget(QLabel("Marker name:"), 0, 0)
        self.e_name = QLineEdit(initial_label)
        self.e_name.selectAll()
        layout.addWidget(self.e_name, 0, 1)

        layout.addWidget(QLabel("Colour:"), 1, 0)
        color_row = QWidget()
        color_layout = QHBoxLayout(color_row)
        color_layout.setContentsMargins(0, 0, 0, 0)
        self.color_group = QButtonGroup(self)
        for i, col in enumerate(_MARKER_COLORS):
            rb = QRadioButton(col)
            rb.setStyleSheet(f"color: {col};")
            if col == initial_color:
                rb.setChecked(True)
            self.color_group.addButton(rb, i)
            color_layout.addWidget(rb)
        layout.addWidget(color_row, 1, 1)

        layout.addWidget(QLabel("Font size:"), 2, 0)
        self.e_fontsize = QLineEdit(str(initial_fontsize))
        self.e_fontsize.setFixedWidth(50)
        layout.addWidget(self.e_fontsize, 2, 1)

        next_row = 3
        self.chk_apply_all = None
        if store_id is not None:
            self.chk_apply_all = QCheckBox(f"Rename all '{store_display_name(ctx, store_id)}' markers")
            self.chk_apply_all.setChecked(True)
            layout.addWidget(self.chk_apply_all, next_row, 0, 1, 2)
            next_row += 1

        btn_row = QHBoxLayout()
        if store_id is not None and store_id in ctx.store_labels:
            btn_reset = QPushButton("Reset Name")
            btn_reset.clicked.connect(self._reset)
            btn_row.addWidget(btn_reset)
        btn = QPushButton("OK")
        btn.setDefault(True)
        btn.clicked.connect(self.accept)
        btn_row.addWidget(btn)
        layout.addLayout(btn_row, next_row, 0, 1, 2)

        self.e_name.setFocus()

    def _reset(self):
        """Clears this store's rename, reverting every marker from it back
        to the raw store id — handled by the caller (open_edit_marker_dialog)
        once this dialog closes, same as a normal rename/apply_to_all edit."""
        self.reset_requested = True
        self.accept()

    def values(self):
        label = self.e_name.text().strip()  # "" is allowed — an unnamed marker, just a tick
        checked = self.color_group.checkedButton()
        color = checked.text() if checked else "green"
        try:
            fontsize = max(4, int(self.e_fontsize.text()))
        except ValueError:
            fontsize = 8
        return label, color, fontsize

    def apply_to_all(self):
        return self.chk_apply_all is not None and self.chk_apply_all.isChecked()


class _InlineRenameEdit(QLineEdit):
    """A QLineEdit that emits `escaped` on Escape instead of Qt's default
    (no-op) handling, so the caller can cancel the rename cleanly."""
    escaped = pyqtSignal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.escaped.emit()
            return
        super().keyPressEvent(event)


class _RenamableStoreList(QListWidget):
    """A QListWidget where left-click behaves normally (select/multi-select)
    but right-click on an item starts inline text editing — Enter or
    losing focus commits, Escape cancels.

    Deliberately NOT using Qt's built-in item-editing (setFlags(...
    ItemIsEditable) + editItem()): calling that programmatically from a
    mouse handler leaves the item's own delegate-painted text visible
    underneath/offset from the editor, a real rendering glitch rather than
    anything specific to how it was invoked here. Managing a plain
    QLineEdit via setIndexWidget() instead sidesteps it entirely — the
    widget just replaces that cell outright."""
    store_renamed = pyqtSignal(QListWidgetItem, str)  # (item, new_text) once committed

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._active = None  # (item, commit_now) while a rename edit is open

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            item = self.itemAt(event.pos())
            # UserRole + 1 == False opts an item out of renaming (used for
            # Note-text entries, which aren't a real store — renaming one
            # would set ctx.store_labels under a key nothing ever reads,
            # silently doing nothing visible).
            if item is not None and item.data(Qt.ItemDataRole.UserRole + 1) is not False:
                # Once an editor is already showing for this item, this
                # click lands on the QLineEdit child widget itself (Qt
                # dispatches to the topmost child, not the list view) —
                # let it fall through to the line edit's own handling
                # rather than starting a second overlapping editor.
                if self.indexWidget(self.indexFromItem(item)) is None:
                    self._begin_rename(item)
                    return
        super().mousePressEvent(event)

    def take_pending_rename(self):
        """If a rename edit box is currently open, close it immediately and
        return (item, new_text) — WITHOUT emitting store_renamed, so the
        caller can fold it into one larger action's own single
        redraw/toast instead of this causing a separate one first. Returns
        None if there was nothing pending (or the text was empty/unchanged).

        Callers must invoke this before any action that might close the
        dialog (Add/Remove/Start Placing) regardless of whether they use
        the return value — letting the dialog close while the edit box is
        still open crashes: Qt destroys the still-live QLineEdit
        mid-teardown, and the deferred widget-removal a normal
        Enter/Escape commit schedules (see _begin_rename) then runs
        against an already-deleted list widget on the next event loop
        tick."""
        if self._active is None:
            return None
        item, editor, state, cleanup = self._active
        if state["done"]:
            return None
        new_text = editor.text().strip()
        cleanup(deferred=False)
        if new_text and new_text != item.text():
            return item, new_text
        return None

    def _begin_rename(self, item):
        index = self.indexFromItem(item)
        editor = _InlineRenameEdit(item.text(), self.viewport())
        # A right-click landing on the editor once it exists should do
        # nothing special (see mousePressEvent above) rather than pop the
        # QLineEdit's native Cut/Copy/Paste menu.
        editor.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)

        state = {"done": False}

        def cleanup(deferred):
            if state["done"]:
                return
            state["done"] = True
            self._active = None
            if deferred:
                # Removing the index widget synchronously while we're
                # still inside its own Return-keypress handling makes Qt
                # lose track of that key event once the widget's gone
                # mid-dispatch — it then falls through to the dialog's
                # default button ("Start Placing"), dropping the user
                # straight into marker-placement mode. A one-tick delay
                # lets this event finish first.
                QTimer.singleShot(0, lambda: self.setIndexWidget(index, None))
            else:
                self.setIndexWidget(index, None)

        def commit_from_enter():
            new_text = editor.text().strip()
            already_done = state["done"]
            cleanup(deferred=True)
            if not already_done and new_text and new_text != item.text():
                self.store_renamed.emit(item, new_text)

        # Deliberately NOT wired to editingFinished/focus-loss: that fires
        # the instant another widget (e.g. the 'Add Selected' button)
        # takes focus, so destroying the editor right then — even
        # immediately, not deferred — corrupts THAT SAME click's delivery
        # to whatever's taking focus, since we'd be tearing the editor
        # down mid-dispatch of its own focus-out event. It silently ate
        # the click, requiring a second one to actually register.
        # Only Enter/Escape commit from inside the editor itself now;
        # anything else (clicking a button, another item, etc.) is
        # handled cleanly afterward by take_pending_rename(), called from
        # each button handler's own already-finished click event instead.
        editor.returnPressed.connect(commit_from_enter)
        editor.escaped.connect(lambda: cleanup(deferred=True))
        self._active = (item, editor, state, cleanup)
        self.setIndexWidget(index, editor)
        # setIndexWidget() runs its own layout pass that overrides both
        # geometry AND widget attributes set beforehand (autoFillBackground
        # included) — without redoing them after, the editor lands offset
        # from the item's rect with a see-through background, letting the
        # item's own painted text show behind it.
        editor.setGeometry(self.visualRect(index))
        editor.setAutoFillBackground(True)
        editor.setStyleSheet("background-color: white; color: black;")
        editor.selectAll()
        editor.setFocus(Qt.FocusReason.MouseFocusReason)


def _bulk_group_key(m):
    """Grouping/selection key for the Add/Remove Auto-Detected Markers
    checklist: phase-tagged markers (onset/offset epocs) group by store
    id, same as everywhere else that treats a store as a renamable,
    bulk-actionable unit. Note-style markers (phase is None) all share
    store == 'Note' regardless of their actual text — parsed straight
    from Notes.txt — so grouping those by store would still lump every
    distinct note under one checkbox; group by the note's own label
    instead so 'Clap', 'Sucrose', etc. each get their own entry. Mirrors
    _same_name_key's identical distinction for bulk delete."""
    return m['store'] if m.get('phase') is not None else m['label']


class AddMarkerDialog(QDialog):
    """Add Marker entry point: bulk-add every auto-detected marker of a
    chosen store, or configure a custom name/colour/fontsize and start
    repeated click-to-place stamping (Snipping-Tool style)."""

    def __init__(self, ctx):
        super().__init__(ctx.win)
        self.ctx = ctx
        self.start_requested = False
        self.setWindowTitle("Add Marker")
        self.setModal(True)
        # Wide (~900px) and tall enough to overflow a small screen — see
        # window_fit.py. No separate button row here: "Start Placing" is
        # the default button inside the form, so Enter still triggers it
        # even when it's scrolled out of view.
        _outer, layout, body = scroll_body(self)

        # ---- bulk-add auto-detected markers (multi-select stores) --------
        detected = (ctx.cache or {}).get('detected_markers', [])
        stores = sorted({_bulk_group_key(m) for m in detected if _bulk_group_key(m)})
        # Which group keys are real, renamable stores vs. individual note
        # texts (see _bulk_group_key) — used below to disable right-click
        # rename for the latter.
        phase_tagged_stores = {m['store'] for m in detected if m.get('phase') is not None}

        box1 = QGroupBox("Add / Remove Auto-Detected Markers")
        l1 = QVBoxLayout(box1)
        if stores:
            l1.addWidget(QLabel("Select one or more stores (ctrl/shift-click to "
                                 "multi-select) and Add Selected or Remove Selected. "
                                 "Right-click a store to rename it (not available for "
                                 "individual notes)."))
            self.store_list = _RenamableStoreList()
            self.store_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            for store_id in stores:
                item = QListWidgetItem(store_display_name(ctx, store_id))
                item.setData(Qt.ItemDataRole.UserRole, store_id)
                if store_id not in phase_tagged_stores:
                    item.setData(Qt.ItemDataRole.UserRole + 1, False)
                self.store_list.addItem(item)
            self.store_list.setFixedHeight(min(120, 22 * len(stores) + 4))
            self.store_list.store_renamed.connect(self._on_store_renamed)
            l1.addWidget(self.store_list)

            # Every epoc is a state that goes high (onset — e.g. a lever
            # press) and later low (offset — e.g. the release). For
            # something like a lever press only the press usually matters;
            # for a pump or light, how long it stayed on does too. Off by
            # default since most stores behave like the former.
            self.chk_high = QCheckBox("High (onset / press / on)")
            self.chk_high.setChecked(True)
            l1.addWidget(self.chk_high)
            self.chk_low = QCheckBox("Low (offset / release / off)")
            self.chk_low.setChecked(False)
            l1.addWidget(self.chk_low)

            # Switch bounce / double-tap duplicates land within
            # milliseconds of the real press — far closer than an animal
            # can genuinely press again, regardless of FR schedule. Off by
            # default since not every store is a lever (a pump/light epoc
            # shouldn't have "presses" collapsed).
            debounce_row = QHBoxLayout()
            self.chk_debounce = QCheckBox("Debounce presses within")
            debounce_row.addWidget(self.chk_debounce)
            self.e_min_isi = QLineEdit("0.15")
            self.e_min_isi.setFixedWidth(50)
            debounce_row.addWidget(self.e_min_isi)
            debounce_row.addWidget(QLabel("s of each other"))
            debounce_row.addStretch(1)
            l1.addLayout(debounce_row)

            store_btn_row = QHBoxLayout()
            btn_add_selected = QPushButton("Add Selected")
            btn_add_selected.clicked.connect(self._add_selected_stores)
            store_btn_row.addWidget(btn_add_selected)
            btn_remove_selected_stores = QPushButton("Remove Selected")
            btn_remove_selected_stores.clicked.connect(self._remove_selected_stores)
            store_btn_row.addWidget(btn_remove_selected_stores)
            btn_reset_selected_names = QPushButton("Reset Selected Names")
            btn_reset_selected_names.clicked.connect(self._reset_selected_names)
            store_btn_row.addWidget(btn_reset_selected_names)
            l1.addLayout(store_btn_row)
        else:
            self.store_list = None
            l1.addWidget(QLabel("No auto-detected markers for this dataset."))
        layout.addWidget(box1)

        # ---- remove markers currently on the plot (multi-select) ---------
        box3 = QGroupBox("Remove Markers")
        l3 = QVBoxLayout(box3)
        current = ctx.cache.get('markers', []) if ctx.cache else []
        if current:
            l3.addWidget(QLabel("Covers both auto-detected and custom-placed markers. "
                                 "Ctrl/shift-click to multi-select."))
            self.marker_list = QListWidget()
            self.marker_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            for i, m in enumerate(current):
                text = f"{m['label']}  @ {m['time']:.2f}s"
                if m.get('store'):
                    text += f"   [{store_display_name(ctx, m['store'])}]"
                if m.get('phase'):
                    text += f"  ({m['phase']})"
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, i)
                self.marker_list.addItem(item)
            self.marker_list.setFixedHeight(min(160, 22 * len(current) + 4))
            l3.addWidget(self.marker_list)
            btn_row = QHBoxLayout()
            btn_select_all = QPushButton("Select All")
            btn_select_all.clicked.connect(self.marker_list.selectAll)
            btn_row.addWidget(btn_select_all)
            btn_remove_selected = QPushButton("Remove Selected")
            btn_remove_selected.clicked.connect(self._remove_selected_markers)
            btn_row.addWidget(btn_remove_selected)
            l3.addLayout(btn_row)
        else:
            self.marker_list = None
            l3.addWidget(QLabel("No markers currently on the plot."))
        layout.addWidget(box3)

        # ---- configure + start custom placement --------------------------
        box2 = QGroupBox("Place Custom Markers")
        l2 = QGridLayout(box2)
        stamp = ctx.marker_stamp

        l2.addWidget(QLabel("Marker name:"), 0, 0)
        self.e_name = QLineEdit(stamp["label"])
        self.e_name.setPlaceholderText("(blank = unnamed, just a tick)")
        self.e_name.selectAll()
        l2.addWidget(self.e_name, 0, 1)

        l2.addWidget(QLabel("Colour:"), 1, 0)
        color_row = QWidget()
        color_layout = QHBoxLayout(color_row)
        color_layout.setContentsMargins(0, 0, 0, 0)
        self.color_group = QButtonGroup(self)
        for i, col in enumerate(_MARKER_COLORS):
            rb = QRadioButton(col)
            rb.setStyleSheet(f"color: {col};")
            if col == stamp["color"]:
                rb.setChecked(True)
            self.color_group.addButton(rb, i)
            color_layout.addWidget(rb)
        l2.addWidget(color_row, 1, 1)

        l2.addWidget(QLabel("Font size:"), 2, 0)
        self.e_fontsize = QLineEdit(str(stamp["fontsize"]))
        self.e_fontsize.setFixedWidth(50)
        l2.addWidget(self.e_fontsize, 2, 1)

        l2.addWidget(QLabel("Click the plot to stamp a marker with this name/colour "
                             "repeatedly; click 'Add Marker' again to stop."),
                     3, 0, 1, 2)

        btn_start = QPushButton("Start Placing")
        btn_start.setDefault(True)
        btn_start.clicked.connect(self._start)
        l2.addWidget(btn_start, 4, 0, 1, 2)
        layout.addWidget(box2)

        fit_dialog_to_content(self, body)
        self.e_name.setFocus()

    def _apply_store_rename(self, item, new_name):
        """Rename every marker of this store — same as the right-click-on-
        plot 'Rename all' path. No redraw/toast here: callers that fold
        this into a bigger action (Add/Remove/Start Placing) want exactly
        one redraw/toast for the whole action, not a separate one just for
        the rename half of it."""
        store_id = item.data(Qt.ItemDataRole.UserRole)
        self.ctx.store_labels[store_id] = new_name
        item.setText(new_name)

    def _flush_pending_rename(self):
        """Commit any open rename edit box before an action that might
        close the dialog (see _RenamableStoreList.take_pending_rename for
        why this must always be called first). Applied silently — the
        caller's own redraw/toast at the end of its action covers it, so
        renaming right before clicking Add/Remove/Start Placing doesn't
        also flash a separate 'Renamed' redraw first.

        Returns True if a rename was actually applied — callers whose main
        action bails out early (e.g. nothing selected) must still redraw
        in that case themselves, or the rename would be silently applied
        with nothing on screen ever reflecting it until some later action
        happens to redraw."""
        if self.store_list is None:
            return False
        pending = self.store_list.take_pending_rename()
        if pending is not None:
            self._apply_store_rename(*pending)
            return True
        return False

    def _on_store_renamed(self, item, new_name):
        """Connected to store_renamed for a standalone rename (Enter/focus-
        loss with nothing else happening) — this is the only path that
        redraws/toasts for the rename by itself."""
        before = undo.snapshot(self.ctx)
        self._apply_store_rename(item, new_name)
        undo.push(self.ctx, f"renamed a store to '{new_name}'", before)
        if self.ctx.cache is not None:
            from .plotting import simple_plot
            simple_plot(self.ctx)
        show_success(self.ctx, f"Renamed to '{new_name}'")

    def _reset_selected_names(self):
        """Clears any custom rename for the selected stores, reverting
        their display back to the raw store id (e.g. 'PP1_')."""
        renamed = self._flush_pending_rename()
        selected_items = self.store_list.selectedItems()
        if not selected_items:
            show_error(self.ctx, "Select at least one store first.")
            if renamed and self.ctx.cache is not None:
                from .plotting import simple_plot
                simple_plot(self.ctx)
            return
        before = undo.snapshot(self.ctx)
        reset_count = 0
        for item in selected_items:
            store_id = item.data(Qt.ItemDataRole.UserRole)
            if self.ctx.store_labels.pop(store_id, None) is not None:
                reset_count += 1
            item.setText(store_id)
        undo.push(self.ctx, f"reset {reset_count} store name(s)", before)
        if self.ctx.cache is not None:
            from .plotting import simple_plot
            simple_plot(self.ctx)
        show_success(self.ctx, f"Reset {reset_count} store name(s)")

    def _phase_allowed(self, marker):
        """Note-style markers (no 'phase' key) are instantaneous — always
        included. Everything else is a high (onset) or low (offset) edge
        of a state, filtered by the two checkboxes above."""
        phase = marker.get('phase')
        if phase is None:
            return True
        if phase == 'high':
            return self.chk_high.isChecked()
        if phase == 'low':
            return self.chk_low.isChecked()
        return True

    def _add_selected_stores(self):
        renamed = self._flush_pending_rename()

        def _redraw_if_renamed():
            if renamed and self.ctx.cache is not None:
                from .plotting import simple_plot
                simple_plot(self.ctx)

        selected_stores = {item.data(Qt.ItemDataRole.UserRole) for item in self.store_list.selectedItems()}
        if not selected_stores:
            show_error(self.ctx, "Select at least one store first.")
            _redraw_if_renamed()
            return
        if not self.chk_high.isChecked() and not self.chk_low.isChecked():
            show_error(self.ctx, "Select High and/or Low first.")
            _redraw_if_renamed()
            return
        detected = self.ctx.cache.get('detected_markers', [])
        to_add = [dict(m) for m in detected
                  if _bulk_group_key(m) in selected_stores and self._phase_allowed(m)]

        debounced_out = 0
        if self.chk_debounce.isChecked():
            try:
                min_isi = max(0.0, float(self.e_min_isi.text()))
            except ValueError:
                min_isi = 0.15
            before = len(to_add)
            to_add = self._debounce_markers(to_add, min_isi)
            debounced_out = before - len(to_add)

        before = undo.snapshot(self.ctx)
        self.ctx.cache['markers'].extend(to_add)
        undo.push(self.ctx, f"added {len(to_add)} marker(s)", before)
        from .plotting import simple_plot
        simple_plot(self.ctx)
        msg = f"Added {len(to_add)} marker(s) from {len(selected_stores)} store(s)"
        if debounced_out:
            msg += f" ({debounced_out} bounce duplicate(s) dropped)"
        show_success(self.ctx, msg)
        self.accept()

    def _debounce_markers(self, markers, min_isi):
        """Drop switch-bounce/duplicate presses within min_isi seconds of
        the previous kept event, per (store, phase) group so a fast press
        in one store never suppresses an unrelated event in another.
        Note-style markers (phase is None — free-text annotations, not a
        state's onset/offset edge) are passed through untouched."""
        groups = {}
        passthrough = []
        for m in markers:
            phase = m.get('phase')
            if phase is None:
                passthrough.append(m)
                continue
            groups.setdefault((m.get('store'), phase), []).append(m)

        result = list(passthrough)
        for group in groups.values():
            group.sort(key=lambda m: m['time'])
            kept_times = pl.debounce_events([m['time'] for m in group], min_isi)
            gi = 0
            for kt in kept_times:
                while group[gi]['time'] != kt:
                    gi += 1
                result.append(group[gi])
                gi += 1
        result.sort(key=lambda m: m['time'])
        return result

    def _remove_selected_stores(self):
        renamed = self._flush_pending_rename()
        selected_stores = {item.data(Qt.ItemDataRole.UserRole) for item in self.store_list.selectedItems()}
        if not selected_stores:
            show_error(self.ctx, "Select at least one store first.")
            if renamed and self.ctx.cache is not None:
                from .plotting import simple_plot
                simple_plot(self.ctx)
            return
        before_snap = undo.snapshot(self.ctx)
        before_n = len(self.ctx.cache['markers'])
        self.ctx.cache['markers'] = [m for m in self.ctx.cache['markers']
                                      if _bulk_group_key(m) not in selected_stores]
        removed = before_n - len(self.ctx.cache['markers'])
        undo.push(self.ctx, f"removed {removed} marker(s)", before_snap)
        from .plotting import simple_plot
        simple_plot(self.ctx)
        show_success(self.ctx, f"Removed {removed} marker(s) from "
                                f"{len(selected_stores)} store(s)")
        self.accept()

    def _remove_selected_markers(self):
        renamed = self._flush_pending_rename()
        selected_items = self.marker_list.selectedItems()
        if not selected_items:
            show_error(self.ctx, "Select at least one marker first.")
            if renamed and self.ctx.cache is not None:
                from .plotting import simple_plot
                simple_plot(self.ctx)
            return
        indices = sorted((item.data(Qt.ItemDataRole.UserRole) for item in selected_items),
                          reverse=True)
        before = undo.snapshot(self.ctx)
        for i in indices:
            self.ctx.cache['markers'].pop(i)
        undo.push(self.ctx, f"removed {len(indices)} marker(s)", before)
        from .plotting import simple_plot
        simple_plot(self.ctx)
        show_success(self.ctx, f"Removed {len(indices)} marker(s)")
        self.accept()

    def _start(self):
        # Unlike the other actions here, Start Placing never redraws on
        # its own afterward (placing markers does that per-click, later) —
        # so a rename right before clicking it needs its own redraw now,
        # or it wouldn't show up until the first marker gets placed.
        renamed = self._flush_pending_rename()
        if renamed and self.ctx.cache is not None:
            from .plotting import simple_plot
            simple_plot(self.ctx)
        label = self.e_name.text().strip()  # "" is allowed — an unnamed marker, just a tick
        checked = self.color_group.checkedButton()
        color = checked.text() if checked else "green"
        try:
            fontsize = max(4, int(self.e_fontsize.text()))
        except ValueError:
            fontsize = 8
        self.ctx.marker_stamp = {"label": label, "color": color, "fontsize": fontsize}
        self.start_requested = True
        self.accept()


def toggle_marker_mode(ctx):
    """Turn placement mode off, or (when off) open the Add Marker dialog to
    configure and start it. Reflects state via the button's style/tooltip
    only — never its text/icon, since ctx.btn_add_marker is a small
    fixed-size icon button (see ui/edit_toolbar.py) that a long label
    like "Placing 'Marker'…" would just clip/garble."""
    if ctx.marker_mode:
        ctx.marker_mode = False
        ctx.btn_add_marker.setStyleSheet("")
        ctx.btn_add_marker.setToolTip(
            "Add Marker — click the plot to place markers (non-destructive, "
            "stored separately from the raw recording)")
        show_window_toast(ctx, "Marker mode OFF")
        return

    if ctx.cache is None:
        show_error(ctx, "Load a dataset first.")
        return

    dlg = AddMarkerDialog(ctx)
    if dlg.exec() == QDialog.DialogCode.Accepted and dlg.start_requested:
        ctx.marker_mode = True
        label = ctx.marker_stamp["label"]
        ctx.btn_add_marker.setStyleSheet("background-color: #FFD54F;")
        ctx.btn_add_marker.setToolTip(
            f"Placing '{label}' markers — click the plot, click this again to stop")
        show_window_toast(ctx, f"Placing '{label}' markers — click the plot, "
                                "click Add Marker again to stop")


def place_marker(ctx, t):
    """Stamp a marker at time t using the currently configured marker_stamp.
    No dialog — placement mode stays active for repeated clicks until the
    user explicitly turns Add Marker off (Snipping-Tool style)."""
    from .plotting import simple_plot
    if ctx.cache is None:
        return
    before = undo.snapshot(ctx)
    ctx.cache['markers'].append({"time": t, **ctx.marker_stamp})
    undo.push(ctx, "placed a marker", before)
    simple_plot(ctx)


MARKER_HIT_PX = 5  # "near a marker" hit-test radius, in on-screen pixels — see
# each engine's own _marker_hit_tolerance() (interaction.py / pg_interaction.py /
# vispy_interaction.py) for how this gets converted to data-space seconds from
# the *current* view range, so it stays a constant 5px regardless of zoom
# level. Chosen to match how the old fixed 2.0s tolerance actually felt on
# real recordings (~1-3px at typical 600-1800s recording lengths, at default
# full-recording zoom) rather than the ~10px a generic UI-hit-target guess
# would suggest. tol_s's 2.0 default below only matters for a caller that
# doesn't bother computing a real one (there shouldn't be any left).


def find_nearest_marker(ctx, t, tol_s=2.0):
    if ctx.cache is None or not ctx.cache['markers']:
        return None
    dists = [abs(m['time'] - t) for m in ctx.cache['markers']]
    idx = int(np.argmin(dists))
    return idx if dists[idx] <= tol_s else None


def apply_marker_edit(ctx, marker, label, color, fontsize, apply_to_all):
    """Rename all markers of this store (via ctx.store_labels, which every
    render path/dialog looks up display names through — see
    marker_labels.py) vs. just this one marker instance. Colour/font size
    always apply to this instance only."""
    if apply_to_all and marker.get('store'):
        ctx.store_labels[marker['store']] = label
    else:
        marker['label'] = label
    marker['color'] = color
    marker['fontsize'] = fontsize


def open_edit_marker_dialog(ctx, marker):
    """Shared by both plot engines' right-click 'Rename' action.

    The "rename all" option (and the store-name prefill) only makes sense
    for markers whose label IS the store name by convention — that's
    markers with a 'phase' key (see marker_labels.marker_display_label for
    why). Anything else — Note markers (label is the actual note text,
    e.g. 'Clap', even though they share store == 'Note'), or manually
    placed markers — is renamed as a plain one-off, same as before this
    feature existed."""
    store_id = marker.get('store') if marker.get('phase') is not None else None
    current_name = store_display_name(ctx, store_id) if store_id else marker['label']
    dlg = MarkerDialog(ctx, "Edit Marker", current_name,
                        marker.get('color', 'green'), marker.get('fontsize', 8),
                        store_id=store_id)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        before = undo.snapshot(ctx)
        if dlg.reset_requested:
            ctx.store_labels.pop(store_id, None)
            undo.push(ctx, "reset a store name", before)
            return True
        label, color, fontsize = dlg.values()
        apply_marker_edit(ctx, marker, label, color, fontsize, dlg.apply_to_all())
        undo.push(ctx, "renamed a marker", before)
        return True
    return False


def _same_name_key(m):
    """What counts as 'the same name' for bulk delete: for a phase-tagged
    marker (onset/offset), that's its store — high and low share one
    display name (just a different superscript), and the store is also
    what a rename actually renamed. Anything else (Note markers, manually
    placed markers) is grouped by its own label instead, since those were
    never tied to a store name in the first place."""
    if m.get('phase') is not None:
        return ('store', m['store'])
    return ('label', m['label'])


def delete_all_same_name(ctx, marker):
    """Removes every marker matching marker's name (see _same_name_key)
    from cache['markers']. Returns how many were removed."""
    key = _same_name_key(marker)
    before = len(ctx.cache['markers'])
    ctx.cache['markers'] = [m for m in ctx.cache['markers'] if _same_name_key(m) != key]
    return before - len(ctx.cache['markers'])


def right_click_marker_menu(ctx, xdata, global_pos, tol_s=2.0):
    from .marker_labels import marker_display_label
    from .plotting import simple_plot
    if ctx.cache is None or xdata is None:
        return
    idx = find_nearest_marker(ctx, xdata, tol_s)
    if idx is None:
        return
    marker = ctx.cache['markers'][idx]
    name = marker_display_label(ctx, marker)

    menu = QMenu(ctx.win)
    act_rename = menu.addAction(f"Rename '{name}'")
    act_delete = menu.addAction(f"Delete '{name}'")
    act_delete_all = menu.addAction(f"Delete all '{name}' markers")
    chosen = menu.exec(global_pos)

    if chosen == act_rename:
        if open_edit_marker_dialog(ctx, marker):
            simple_plot(ctx)
    elif chosen == act_delete:
        before = undo.snapshot(ctx)
        ctx.cache['markers'].pop(idx)
        undo.push(ctx, "deleted a marker", before)
        simple_plot(ctx)
    elif chosen == act_delete_all:
        before = undo.snapshot(ctx)
        removed = delete_all_same_name(ctx, marker)
        undo.push(ctx, f"deleted {removed} marker(s)", before)
        simple_plot(ctx)
        show_success(ctx, f"Deleted {removed} '{name}' marker(s)")
