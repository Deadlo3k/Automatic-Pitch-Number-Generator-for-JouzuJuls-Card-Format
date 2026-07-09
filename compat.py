"""
compat.py — version compatibility shims for Fill Pitch Numbers.

Handles differences between:
  - Anki 2.1.45–2.1.49  (PyQt5, Qt5 flat enums, col.getNote())
  - Anki 2.1.50–22.x    (PyQt6, Qt6 scoped enums, col.get_note())
  - Anki 23.x–25.x+     (PyQt6, Qt6 scoped enums, col.get_note())

Import the constants from here instead of using enum paths directly in
__init__.py, so the add-on never raises AttributeError on any supported build.
"""

from __future__ import annotations

from aqt.qt import Qt, QDialog, QListWidget, QHeaderView, QTableWidget

# ---------------------------------------------------------------------------
# Detect Qt version once at import time
# ---------------------------------------------------------------------------

try:
    # Qt6 scoped enums exist in Anki 2.1.50+ / 23.x+
    Qt.WindowModality.WindowModal  # noqa: B018
    _QT6 = True
except AttributeError:
    # Qt5 flat enums — Anki 2.1.45–2.1.49
    _QT6 = False

# ---------------------------------------------------------------------------
# Version-safe enum constants
# ---------------------------------------------------------------------------

if _QT6:
    QT_WINDOW_MODAL:         object = Qt.WindowModality.WindowModal
    QT_MATCH_EXACTLY:        object = Qt.MatchFlag.MatchExactly
    QDIALOG_ACCEPTED:        object = QDialog.DialogCode.Accepted
    QLISTWIDGET_SINGLE:      object = QListWidget.SelectionMode.SingleSelection
    QHEADER_RESIZE_CONTENTS: object = QHeaderView.ResizeMode.ResizeToContents
    QTABLE_NO_EDIT:          object = QTableWidget.EditTrigger.NoEditTriggers
    QTABLE_SELECT_ROWS:      object = QTableWidget.SelectionBehavior.SelectRows
else:
    QT_WINDOW_MODAL         = Qt.WindowModal           # type: ignore[attr-defined]
    QT_MATCH_EXACTLY        = Qt.MatchExactly          # type: ignore[attr-defined]
    QDIALOG_ACCEPTED        = QDialog.Accepted         # type: ignore[attr-defined]
    QLISTWIDGET_SINGLE      = QListWidget.SingleSelection    # type: ignore[attr-defined]
    QHEADER_RESIZE_CONTENTS = QHeaderView.ResizeToContents   # type: ignore[attr-defined]
    QTABLE_NO_EDIT          = QTableWidget.NoEditTriggers    # type: ignore[attr-defined]
    QTABLE_SELECT_ROWS      = QTableWidget.SelectRows        # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# col.get_note() / col.getNote() compatibility
# ---------------------------------------------------------------------------

def get_note(col, note_id: int):
    """
    Fetch a note by ID.  Works on all supported Anki versions:
      - Anki 2.1.45+: col.get_note()  (snake_case)
      - Anki <2.1.45:  col.getNote()   (camelCase)
    """
    try:
        return col.get_note(note_id)        # Anki 2.1.45+
    except AttributeError:
        return col.getNote(note_id)         # type: ignore[attr-defined]
