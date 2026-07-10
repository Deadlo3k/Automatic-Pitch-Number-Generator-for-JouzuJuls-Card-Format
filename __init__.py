"""
Fill Pitch Numbers — Anki add-on
=================================
Automatically fills the "Pitch Number" field on Japanese vocabulary cards
by looking up each card's reading in the bundled Kanjium pitch accent
dataset.

Menu entry: Tools > Japanese Pitch > Fill Pitch Numbers...

Configuration lives in config.json next to this file.
Compatible with Anki 2.1.45+ through 25.x (Qt5 and Qt6).
"""

from __future__ import annotations  # allows X | Y, list[X] etc. on Python 3.8+

import os
import json
from dataclasses import dataclass

from aqt import mw
from aqt.utils import showInfo, qconnect, tooltip
from aqt.qt import (
    QAction,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    Qt,
    pyqtSignal,  # moved from inside _PreviewDialog class body
)

from .pitch_lookup import (
    PitchLookup,
    count_moras,
    katakana_to_hiragana,
    _extract_expression,
    _extract_reading,
    _extract_inline_pitch,
)
from .compat import (
    get_note,
    QDIALOG_ACCEPTED,
    QLISTWIDGET_SINGLE,
    QHEADER_RESIZE_CONTENTS,
    QTABLE_NO_EDIT,
    QTABLE_SELECT_ROWS,
    QT_MATCH_EXACTLY,
    QT_WINDOW_MODAL,
)

# ---------------------------------------------------------------------------
# Paths / config
# ---------------------------------------------------------------------------

ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ADDON_DIR, "config.json")

_lookup_cache: PitchLookup | None = None


def _load_config() -> dict:
    defaults = {
        "reading_field": "Reading",
        "pitch_field": "Pitch Number",
        "expression_fields": ["Expression", "Word", "Vocabulary", "単語", "Front"],
        "overwrite_existing": False,
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            defaults.update(loaded)
        except Exception:
            pass
    return defaults


def _get_lookup() -> PitchLookup:
    """Return a cached PitchLookup instance (loads dataset once per session)."""
    global _lookup_cache
    if _lookup_cache is None:
        _lookup_cache = PitchLookup(ADDON_DIR)
    return _lookup_cache


# ---------------------------------------------------------------------------
# Pitch pattern label helper
# ---------------------------------------------------------------------------

def _pitch_pattern(pitch: int, reading: str) -> str:
    """Return the human-readable pattern name for a pitch number + reading."""
    moras = count_moras(katakana_to_hiragana(reading))
    if pitch == 0:
        return "Heiban"
    if pitch == 1:
        return "Atamadaka"
    if pitch == moras:
        return "Odaka"
    return "Nakadaka"


# ---------------------------------------------------------------------------
# Data class for a pending change (used by both preview and real run)
# ---------------------------------------------------------------------------

@dataclass
class _Change:
    note_id: int
    expression: str
    reading: str
    pitch_num: int

    @property
    def pattern(self) -> str:
        return _pitch_pattern(self.pitch_num, self.reading)


# ---------------------------------------------------------------------------
# Deck-picker dialog
# ---------------------------------------------------------------------------

class _FillPitchDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fill Pitch Numbers")
        self.setMinimumWidth(400)
        self.setMinimumHeight(340)

        config = _load_config()
        layout = QVBoxLayout()

        layout.addWidget(QLabel("<b>Select a deck:</b>"))

        self._deck_list = QListWidget()
        self._deck_list.setSelectionMode(QLISTWIDGET_SINGLE)

        # Populate with every deck in the collection, sorted alphabetically
        try:
            all_decks = sorted(
                mw.col.decks.all_names_and_ids(), key=lambda d: d.name
            )
            deck_names = [d.name for d in all_decks]
        except Exception:
            deck_names = sorted(mw.col.decks.allNames())  # type: ignore[attr-defined]

        for name in deck_names:
            self._deck_list.addItem(QListWidgetItem(name))

        # Pre-select the currently active deck
        try:
            current_deck_name = mw.col.decks.name(mw.col.decks.get_current_id())
            matches = self._deck_list.findItems(current_deck_name, QT_MATCH_EXACTLY)
            if matches:
                self._deck_list.setCurrentItem(matches[0])
            else:
                self._deck_list.setCurrentRow(0)
        except Exception:
            self._deck_list.setCurrentRow(0)

        layout.addWidget(self._deck_list)
        layout.addSpacing(8)

        self._cb_overwrite = QCheckBox("Overwrite existing values")
        self._cb_overwrite.setChecked(config.get("overwrite_existing", False))
        layout.addWidget(self._cb_overwrite)

        layout.addSpacing(10)

        # Button row: [Preview]  [Run]  [Cancel]
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._btn_preview = QPushButton("Preview…")
        self._btn_preview.setToolTip(
            "See what would be changed without writing anything"
        )
        self._btn_preview.clicked.connect(self._on_preview)
        btn_layout.addWidget(self._btn_preview)

        self._btn_run = QPushButton("Run")
        self._btn_run.setDefault(True)
        self._btn_run.clicked.connect(self.accept)
        btn_layout.addWidget(self._btn_run)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def selected_deck_name(self) -> str | None:
        item = self._deck_list.currentItem()
        return item.text() if item else None

    def overwrite(self) -> bool:
        return self._cb_overwrite.isChecked()

    def _on_preview(self) -> None:
        deck_name = self.selected_deck_name()
        if not deck_name:
            showInfo("Please select a deck first.")
            return

        lookup, ok = _ensure_lookup_ready()
        if not ok:
            return

        changes, stats = _compute_changes(deck_name, self.overwrite(), lookup)
        preview_dlg = _PreviewDialog(deck_name, changes, stats, parent=self)

        # "Run for real" from the preview window: apply, then close both dialogs
        def _run_from_preview() -> None:
            preview_dlg.accept()
            self.accept()
            filled = _apply_changes(deck_name, changes)
            showInfo(
                f"<b>Done!</b><br><br>"
                f"Deck: <i>{deck_name}</i><br>"
                f"Filled: <b>{filled}</b> notes."
            )

        preview_dlg.run_requested.connect(_run_from_preview)
        preview_dlg.exec()


# ---------------------------------------------------------------------------
# Preview results dialog
# ---------------------------------------------------------------------------

class _PreviewDialog(QDialog):
    """Shows a dry-run table and offers a "Run for real" button."""

    # pyqtSignal is now imported at module level (not inside the class body)
    run_requested = pyqtSignal()

    def __init__(self, deck_name: str, changes: list[_Change], stats: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Preview — "{deck_name}"')
        self.setMinimumWidth(580)
        self.setMinimumHeight(420)

        layout = QVBoxLayout()

        total        = stats["total"]
        filled       = len(changes)
        not_found    = stats["not_found"]
        existing     = stats["existing"]
        missing_field = stats["missing_field"]

        summary_parts = [
            f"<b>Would fill {filled} of {total} notes.</b>",
            f"Not in database: {not_found}",
            f"Already have a value: {existing}",
        ]
        if missing_field:
            summary_parts.append(f"Field not on note type: {missing_field}")
        layout.addWidget(QLabel("  ".join(summary_parts)))
        layout.addSpacing(6)

        if changes:
            table = QTableWidget(len(changes), 4)
            table.setHorizontalHeaderLabels(["Expression", "Reading", "Pitch", "Pattern"])
            table.horizontalHeader().setSectionResizeMode(QHEADER_RESIZE_CONTENTS)
            table.horizontalHeader().setStretchLastSection(True)
            table.setEditTriggers(QTABLE_NO_EDIT)
            table.setSelectionBehavior(QTABLE_SELECT_ROWS)
            table.verticalHeader().setVisible(False)

            for row, ch in enumerate(changes):
                table.setItem(row, 0, QTableWidgetItem(ch.expression))
                table.setItem(row, 1, QTableWidgetItem(ch.reading))
                table.setItem(row, 2, QTableWidgetItem(str(ch.pitch_num)))
                table.setItem(row, 3, QTableWidgetItem(ch.pattern))

            layout.addWidget(table)
        else:
            layout.addWidget(QLabel("<i>No cards would be changed.</i>"))

        layout.addSpacing(8)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        if changes:
            btn_run = QPushButton("Run for real")
            btn_run.setDefault(True)
            btn_run.setToolTip("Apply these changes now")
            btn_run.clicked.connect(self.run_requested)
            btn_layout.addWidget(btn_run)

        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.reject)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)
        self.setLayout(layout)


# ---------------------------------------------------------------------------
# Core: compute changes (dry run) and apply changes (real run)
# ---------------------------------------------------------------------------

def _ensure_lookup_ready() -> tuple[PitchLookup | None, bool]:
    tooltip("Loading pitch accent database…", period=3000)
    lookup = _get_lookup()
    if not lookup.is_ready():
        err = lookup.last_error()
        detail = f"\n\nError: {err}" if err else ""
        showInfo(
            "The pitch accent database could not be loaded or downloaded."
            + detail
            + "\n\nPlease check your internet connection and try again."
        )
        return None, False
    return lookup, True


def _compute_changes(
    deck_name: str,
    overwrite: bool,
    lookup: PitchLookup,
) -> tuple[list[_Change], dict]:
    """
    Iterate every note in deck_name and compute what would be written.
    Does NOT modify any notes.  Returns (changes, stats).
    """
    config = _load_config()
    reading_field: str = config["reading_field"]
    pitch_field: str   = config["pitch_field"]
    expr_fields: list[str] = config["expression_fields"]

    note_ids = list(mw.col.find_notes(f'deck:"{deck_name}"'))
    col = mw.col

    changes: list[_Change] = []
    not_found     = 0
    existing      = 0
    missing_field = 0

    progress = QProgressDialog(
        f'Scanning "{deck_name}"…', "Cancel", 0, len(note_ids), mw
    )
    progress.setWindowModality(QT_WINDOW_MODAL)
    progress.setMinimumDuration(500)
    progress.setValue(0)

    for i, note_id in enumerate(note_ids):
        if progress.wasCanceled():
            break
        progress.setValue(i)

        note = get_note(col, note_id)
        note_keys = note.keys()

        if reading_field not in note_keys or pitch_field not in note_keys:
            missing_field += 1
            continue

        existing_val = note[pitch_field].strip()
        if existing_val and not overwrite:
            existing += 1
            continue

        raw_reading = note[reading_field]
        inline_pitch = _extract_inline_pitch(raw_reading)
        reading = _extract_reading(raw_reading)
        if not reading:
            not_found += 1
            continue

        expression = _get_expression(note, expr_fields)
        db_pitch = lookup.lookup(expression, reading)

        if db_pitch is not None:
            if inline_pitch is not None and inline_pitch != db_pitch:
                pitch_num = inline_pitch
            else:
                pitch_num = db_pitch
        elif inline_pitch is not None:
            pitch_num = inline_pitch
        else:
            pitch_num = None

        if pitch_num is None:
            not_found += 1
            continue

        changes.append(_Change(
            note_id=note_id,
            expression=expression,
            reading=reading,
            pitch_num=pitch_num,
        ))

    progress.setValue(len(note_ids))

    stats = {
        "total":         len(note_ids),
        "not_found":     not_found,
        "existing":      existing,
        "missing_field": missing_field,
    }
    return changes, stats


def _apply_changes(deck_name: str, changes: list[_Change]) -> int:
    """
    Write pre-computed changes to the collection in one transaction.
    Returns the number of notes written.  Does NOT show any dialog.
    """
    if not changes:
        return 0

    config = _load_config()
    pitch_field: str = config["pitch_field"]
    col = mw.col

    notes = []
    for ch in changes:
        value = str(ch.pitch_num)
        # Guard: only write plain non-negative integer strings.
        if not value.isdigit():
            continue
        note = get_note(col, ch.note_id)
        note[pitch_field] = value
        notes.append(note)

    _batch_update(col, notes)
    col.save()
    return len(notes)


def _get_expression(note, expr_fields: list[str]) -> str:
    note_keys = note.keys()
    for field in expr_fields:
        if field in note_keys and note[field].strip():
            return _extract_expression(note[field])
    return ""


def _batch_update(col, notes: list) -> None:
    if not notes:
        return
    try:
        col.update_notes(notes)       # Anki 2.1.45+
    except AttributeError:
        for note in notes:
            note.flush()              # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Main action (Run directly from dialog — skips preview)
# ---------------------------------------------------------------------------

def fill_pitch_numbers() -> None:
    dlg = _FillPitchDialog(mw)
    if dlg.exec() != QDIALOG_ACCEPTED:
        return

    deck_name = dlg.selected_deck_name()
    if not deck_name:
        showInfo("No deck selected.")
        return

    lookup, ok = _ensure_lookup_ready()
    if not ok:
        return

    changes, stats = _compute_changes(deck_name, dlg.overwrite(), lookup)

    if not changes and stats["total"] == 0:
        showInfo(f'No notes found in deck "{deck_name}".')
        return

    filled = _apply_changes(deck_name, changes)

    lines = [
        "<b>Done!</b><br><br>",
        f"Deck: <i>{deck_name}</i><br>",
        f"Filled: <b>{filled}</b><br>",
        f"Not in database: {stats['not_found']}<br>",
        f"Already had a value: {stats['existing']}<br>",
    ]
    if stats["missing_field"]:
        lines.append(f"Field not on note type: {stats['missing_field']}<br>")
    showInfo("".join(lines))


# ---------------------------------------------------------------------------
# Menu registration
# ---------------------------------------------------------------------------

def _setup_menu() -> None:
    tools_menu = mw.form.menuTools

    japanese_menu: QMenu | None = None
    for act in tools_menu.actions():
        if act.text() == "Japanese Pitch" and act.menu():
            japanese_menu = act.menu()
            break

    if japanese_menu is None:
        japanese_menu = QMenu("Japanese Pitch", mw)
        tools_menu.addMenu(japanese_menu)

    action = QAction("Fill Pitch Numbers…", mw)
    qconnect(action.triggered, fill_pitch_numbers)
    japanese_menu.addAction(action)


_setup_menu()
