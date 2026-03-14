#!/usr/bin/env python3

"""
DBC Comparator UI
Rich comparison tools for DBC files with side-by-side, unified, and structured views.
"""

from __future__ import annotations

import copy
import difflib
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import cantools
import qtawesome as qta  # pyright: ignore[reportMissingImports]
from PyQt5 import QtCore, QtGui, QtWidgets

from dbc_comparator import (
    CompareSide,
    DiffChunk,
    DiffResult,
    DiffRow,
    DiffType,
    MessageComparisonItem,
    SignalComparisonItem,
    StructuredDiffResult,
    build_dbc_string,
    compare_dbc_structures,
    compare_texts,
    parse_dbc_to_dicts,
)
from multiplex_support import format_mux_indicator

logger = logging.getLogger(__name__)


_BORDER_COLOR = "#cccccc"
_HEADER_BG = "#eef1f5"
_SUMMARY_BG = "#f6f8fa"
_INSERT_BG = QtGui.QColor("#e6ffec")
_DELETE_BG = QtGui.QColor("#ffebe9")
_REPLACE_BG = QtGui.QColor("#fff8c5")
_EMPTY_BG = QtGui.QColor("#f5f5f5")
_CHANGE_CHAR_BG = QtGui.QColor("#ffd866")


def _badge_text(label: str, is_primary: bool) -> str:
    return f"{label}  [PRIMARY]" if is_primary else label


def _format_location(label: str, path: Optional[str]) -> str:
    return f"{label}\n{path}" if path else label


def _line_number_text(number: Optional[int]) -> str:
    return f"{number:>6}" if number is not None else " " * 6


def _row_background(diff_type: DiffType, side: CompareSide) -> Optional[QtGui.QColor]:
    if diff_type == DiffType.INSERT:
        return _INSERT_BG if side == CompareSide.RIGHT else _EMPTY_BG
    if diff_type == DiffType.DELETE:
        return _DELETE_BG if side == CompareSide.LEFT else _EMPTY_BG
    if diff_type == DiffType.REPLACE:
        return _REPLACE_BG
    return None


def _prefix_marker(diff_type: DiffType) -> str:
    if diff_type == DiffType.INSERT:
        return "+"
    if diff_type == DiffType.DELETE:
        return "-"
    if diff_type == DiffType.REPLACE:
        return "~"
    return " "


def _read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _write_text_file(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


@dataclass
class EditableDiffDisplayRow:
    diff_type: DiffType
    left_text: str
    right_text: str
    left_lineno: Optional[int]
    right_lineno: Optional[int]
    left_chunks: list[DiffChunk]
    right_chunks: list[DiffChunk]
    left_placeholder: bool
    right_placeholder: bool

    @property
    def is_changed(self) -> bool:
        return self.diff_type != DiffType.EQUAL


class DiffTextView(QtWidgets.QTextEdit):
    """Read-only monospace text view that supports formatted diff rendering."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        self.setFont(QtGui.QFont("Consolas", 10))
        self.setStyleSheet(
            f"QTextEdit {{ border: 1px solid {_BORDER_COLOR}; background: white; }}"
        )
        self._change_blocks: list[int] = []

    def clear_view(self) -> None:
        self.clear()
        self._change_blocks = []

    def set_change_blocks(self, blocks: list[int]) -> None:
        self._change_blocks = blocks

    def change_count(self) -> int:
        return len(self._change_blocks)

    def goto_change(self, index: int) -> None:
        if not self._change_blocks:
            return
        block = self.document().findBlockByNumber(self._change_blocks[index])
        if not block.isValid():
            return
        cursor = QtGui.QTextCursor(block)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()


class _HeaderCard(QtWidgets.QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background: {_HEADER_BG}; border: 1px solid {_BORDER_COLOR}; border-radius: 4px; }}"
            f"QLabel#title {{ font-weight: bold; }}"
            f"QLabel#path {{ color: #555; }}"
        )
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self.title_label = QtWidgets.QLabel()
        self.title_label.setObjectName("title")
        self.path_label = QtWidgets.QLabel()
        self.path_label.setObjectName("path")
        self.path_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.path_label)

    def set_content(self, label: str, path: Optional[str], is_primary: bool) -> None:
        self.title_label.setText(_badge_text(label, is_primary))
        self.path_label.setText(path or "")
        self.path_label.setVisible(bool(path))
        title_style = "color: #1f6feb;" if is_primary else "color: #222;"
        self.title_label.setStyleSheet(title_style)


class _LineNumberArea(QtWidgets.QWidget):
    def __init__(self, editor: "EditableDiffEditor"):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(self._editor.line_number_area_width(), 0)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        self._editor.paint_line_number_area(event)


class _DiffHighlighter(QtGui.QSyntaxHighlighter):
    def __init__(self, editor: "EditableDiffEditor"):
        super().__init__(editor.document())
        self._editor = editor

    def highlightBlock(self, text: str) -> None:
        row = self._editor.row_for_block(self.currentBlock().blockNumber())
        if row is None:
            return

        chunks = row.left_chunks if self._editor.side == CompareSide.LEFT else row.right_chunks
        expected_text = row.left_text if self._editor.side == CompareSide.LEFT else row.right_text
        if text != expected_text:
            return

        position = 0
        for chunk in chunks:
            if chunk.changed and chunk.text:
                fmt = QtGui.QTextCharFormat()
                fmt.setBackground(_CHANGE_CHAR_BG)
                fmt.setFontWeight(QtGui.QFont.Bold)
                self.setFormat(position, len(chunk.text), fmt)
            position += len(chunk.text)


class EditableDiffEditor(QtWidgets.QPlainTextEdit):
    """Editable aligned diff editor with line numbers and change highlighting."""

    undoRequested = QtCore.pyqtSignal()
    redoRequested = QtCore.pyqtSignal()

    def __init__(self, side: CompareSide, parent=None):
        super().__init__(parent)
        self.side = side
        self._rows: list[EditableDiffDisplayRow] = []
        self._change_blocks: list[int] = []
        self._line_number_area = _LineNumberArea(self)
        self._highlighter = _DiffHighlighter(self)

        self.setUndoRedoEnabled(False)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.setFont(QtGui.QFont("Consolas", 10))
        self.setStyleSheet(
            f"QPlainTextEdit {{ border: 1px solid {_BORDER_COLOR}; background: white; }}"
        )

        self.blockCountChanged.connect(self._update_line_number_area_width)
        self.updateRequest.connect(self._update_line_number_area)
        self._update_line_number_area_width(0)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.matches(QtGui.QKeySequence.Undo):
            self.undoRequested.emit()
            event.accept()
            return
        if event.matches(QtGui.QKeySequence.Redo):
            self.redoRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def line_number_area_width(self) -> int:
        digits = max(2, len(str(max(1, self.blockCount()))))
        return 12 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_line_number_area_width(self, _new_block_count: int) -> None:
        self.setViewportMargins(self.line_number_area_width(), 0, 0, 0)

    def _update_line_number_area(self, rect: QtCore.QRect, dy: int) -> None:
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())

        if rect.contains(self.viewport().rect()):
            self._update_line_number_area_width(0)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        contents = self.contentsRect()
        self._line_number_area.setGeometry(
            QtCore.QRect(contents.left(), contents.top(), self.line_number_area_width(), contents.height())
        )

    def paint_line_number_area(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self._line_number_area)
        painter.fillRect(event.rect(), QtGui.QColor("#f3f4f6"))

        block = self.firstVisibleBlock()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        block_number = block.blockNumber()

        while block.isValid() and top <= event.rect().bottom():
            height = int(self.blockBoundingRect(block).height())
            bottom = top + height

            if block.isVisible() and bottom >= event.rect().top():
                row = self.row_for_block(block_number)
                if row is None:
                    line_no = None
                else:
                    line_no = row.left_lineno if self.side == CompareSide.LEFT else row.right_lineno
                painter.setPen(QtGui.QColor("#6b7280" if line_no is not None else "#b6b6b6"))
                painter.drawText(
                    0,
                    top,
                    self._line_number_area.width() - 6,
                    height,
                    QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                    str(line_no) if line_no is not None else "",
                )

            block = block.next()
            block_number += 1
            top = bottom

    def row_for_block(self, block_number: int) -> Optional[EditableDiffDisplayRow]:
        if 0 <= block_number < len(self._rows):
            return self._rows[block_number]
        return None

    def set_rows(self, rows: list[EditableDiffDisplayRow]) -> None:
        self._rows = rows
        self._change_blocks = [index for index, row in enumerate(rows) if row.is_changed]
        lines = [row.left_text if self.side == CompareSide.LEFT else row.right_text for row in rows]
        self.blockSignals(True)
        self.setPlainText("\n".join(lines))
        self.blockSignals(False)
        self._apply_row_highlights()
        self._highlighter.rehighlight()
        self._update_line_number_area_width(0)
        self._line_number_area.update()

    def clear_view(self) -> None:
        self._rows = []
        self._change_blocks = []
        self.blockSignals(True)
        self.clear()
        self.blockSignals(False)
        self.setExtraSelections([])
        self._line_number_area.update()

    def _apply_row_highlights(self) -> None:
        selections: list[QtWidgets.QTextEdit.ExtraSelection] = []

        for index, row in enumerate(self._rows):
            background = _row_background(row.diff_type, self.side)
            placeholder = row.left_placeholder if self.side == CompareSide.LEFT else row.right_placeholder
            if background is None and not placeholder:
                continue

            block = self.document().findBlockByNumber(index)
            if not block.isValid():
                continue

            selection = QtWidgets.QTextEdit.ExtraSelection()
            selection.cursor = QtGui.QTextCursor(block)
            selection.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
            selection.format.setBackground(background or _EMPTY_BG)
            selections.append(selection)

        self.setExtraSelections(selections)

    def change_count(self) -> int:
        return len(self._change_blocks)

    def goto_change(self, index: int) -> None:
        if not self._change_blocks:
            return
        block_number = self._change_blocks[index]
        block = self.document().findBlockByNumber(block_number)
        if not block.isValid():
            return
        cursor = QtGui.QTextCursor(block)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _logical_line_for_block(self, block_number: int) -> int:
        """Count non-placeholder lines before *block_number*."""
        count = 0
        for i in range(min(block_number, len(self._rows))):
            ph = self._rows[i].left_placeholder if self.side == CompareSide.LEFT else self._rows[i].right_placeholder
            if not ph:
                count += 1
        return count

    def _block_for_logical_line(self, logical_line: int) -> int:
        """Return the block index that contains *logical_line*-th real line."""
        count = 0
        for i, row in enumerate(self._rows):
            ph = row.left_placeholder if self.side == CompareSide.LEFT else row.right_placeholder
            if not ph:
                if count == logical_line:
                    return i
                count += 1
        return max(0, self.document().blockCount() - 1)

    def capture_state(self) -> Dict[str, Any]:
        cursor = self.textCursor()
        bn = cursor.blockNumber()
        return {
            "block": bn,
            "column": cursor.positionInBlock(),
            "logical_line": self._logical_line_for_block(bn),
            "vscroll": self.verticalScrollBar().value(),
            "hscroll": self.horizontalScrollBar().value(),
        }

    def restore_state(self, state: Optional[Dict[str, Any]]) -> None:
        if not state:
            return

        if "logical_line" in state:
            block_number = self._block_for_logical_line(state["logical_line"])
        else:
            block_number = state.get("block", 0)
        block_number = min(block_number, max(0, self.document().blockCount() - 1))
        block = self.document().findBlockByNumber(block_number)
        if block.isValid():
            cursor = QtGui.QTextCursor(block)
            column = min(state.get("column", 0), len(block.text()))
            cursor.movePosition(QtGui.QTextCursor.Right, QtGui.QTextCursor.MoveAnchor, column)
            self.setTextCursor(cursor)

        self.verticalScrollBar().setValue(state.get("vscroll", 0))
        self.horizontalScrollBar().setValue(state.get("hscroll", 0))

    def display_lines(self) -> list[str]:
        lines: list[str] = []
        block = self.document().firstBlock()
        while block.isValid():
            lines.append(block.text())
            block = block.next()
        return lines or [""]

    def line_text(self, row_index: int) -> str:
        block = self.document().findBlockByNumber(row_index)
        return block.text() if block.isValid() else ""

    def replace_display_line(self, row_index: int, text: str) -> None:
        block = self.document().findBlockByNumber(row_index)
        if not block.isValid():
            return

        cursor = QtGui.QTextCursor(block)
        cursor.setPosition(block.position())
        cursor.movePosition(QtGui.QTextCursor.EndOfBlock, QtGui.QTextCursor.KeepAnchor)
        cursor.insertText(text)


class _SideCopyGutter(QtWidgets.QWidget):
    """Narrow gutter placed at the left of each editor panel with a single arrow
    indicating 'copy from the other side into this panel'."""

    copyRequested = QtCore.pyqtSignal(int)

    def __init__(self, editor: EditableDiffEditor, icon: QtGui.QIcon, comparison_widget: "SideBySideDiffWidget"):
        super().__init__(comparison_widget)
        self._editor = editor
        self._icon = icon
        self._comparison_widget = comparison_widget
        self._hover_row: Optional[int] = None
        self.setMouseTracking(True)
        self.setFixedWidth(24)

    def _iter_visible_rows(self):
        block = self._editor.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self._editor.blockBoundingGeometry(block).translated(self._editor.contentOffset()).top())

        while block.isValid() and top <= self.height():
            height = int(self._editor.blockBoundingRect(block).height())
            bottom = top + height
            row = self._comparison_widget.row_for_index(block_number)
            if block.isVisible() and bottom >= 0 and row is not None:
                yield block_number, row, top, bottom
            block = block.next()
            block_number += 1
            top = bottom

    def _icon_rect(self, top: int, bottom: int) -> QtCore.QRect:
        size = max(14, min(18, bottom - top - 4))
        y = top + max(2, (bottom - top - size) // 2)
        x = (self.width() - size) // 2
        return QtCore.QRect(x, y, size, size)

    def _hit_test(self, pos: QtCore.QPoint) -> Optional[int]:
        for row_index, row, top, bottom in self._iter_visible_rows():
            if not row.is_changed:
                continue
            if self._icon_rect(top, bottom).contains(pos):
                return row_index
        return None

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        self._hover_row = self._hit_test(event.pos())
        self.setCursor(QtCore.Qt.PointingHandCursor if self._hover_row is not None else QtCore.Qt.ArrowCursor)
        self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:
        self._hover_row = None
        self.setCursor(QtCore.Qt.ArrowCursor)
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        hit = self._hit_test(event.pos())
        if hit is not None:
            self.copyRequested.emit(hit)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.fillRect(event.rect(), QtGui.QColor("#f8fafc"))
        painter.setPen(QtGui.QColor(_BORDER_COLOR))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())

        for row_index, row, top, bottom in self._iter_visible_rows():
            if not row.is_changed:
                continue
            rect = self._icon_rect(top, bottom)
            if self._hover_row == row_index:
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(QtGui.QColor("#dbeafe"))
                painter.drawRoundedRect(rect.adjusted(-2, -1, 2, 1), 4, 4)
            self._icon.paint(painter, rect)


class SideBySideDiffWidget(QtWidgets.QWidget):
    """Editable side-by-side comparison with per-panel copy arrows and live re-diff."""

    contentChanged = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[EditableDiffDisplayRow] = []
        self._syncing_vertical = False
        self._syncing_horizontal = False
        self._loading = False

        self._edit_timer = QtCore.QTimer(self)
        self._edit_timer.setSingleShot(True)
        self._edit_timer.timeout.connect(self.contentChanged.emit)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.summary_label = QtWidgets.QLabel("No comparison loaded")
        self.summary_label.setStyleSheet(
            f"QLabel {{ padding: 6px 10px; background: {_SUMMARY_BG}; border: 1px solid {_BORDER_COLOR}; border-radius: 4px; font-weight: bold; }}"
        )
        layout.addWidget(self.summary_label)

        self._header_container = QtWidgets.QWidget()
        header_layout = QtWidgets.QHBoxLayout(self._header_container)
        header_layout.setContentsMargins(0, 0, 0, 0)
        self.left_header = _HeaderCard()
        self.right_header = _HeaderCard()
        header_layout.addWidget(self.left_header, 1)
        header_layout.addWidget(self.right_header, 1)
        self._header_container.hide()
        layout.addWidget(self._header_container)

        editor_layout = QtWidgets.QHBoxLayout()
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)

        self.left_editor = EditableDiffEditor(CompareSide.LEFT)
        self.right_editor = EditableDiffEditor(CompareSide.RIGHT)

        self.left_gutter = _SideCopyGutter(
            self.left_editor,
            qta.icon("fa5s.arrow-right", color="#0f766e"),
            self,
        )
        self.right_gutter = _SideCopyGutter(
            self.right_editor,
            qta.icon("fa5s.arrow-left", color="#0f766e"),
            self,
        )

        editor_layout.addWidget(self.left_gutter)
        editor_layout.addWidget(self.left_editor, 1)
        editor_layout.addWidget(self.right_gutter)
        editor_layout.addWidget(self.right_editor, 1)
        layout.addLayout(editor_layout, 1)

        self.left_editor.verticalScrollBar().valueChanged.connect(
            lambda value: self._sync_scroll(value, self.right_editor.verticalScrollBar(), "vertical")
        )
        self.right_editor.verticalScrollBar().valueChanged.connect(
            lambda value: self._sync_scroll(value, self.left_editor.verticalScrollBar(), "vertical")
        )
        self.left_editor.horizontalScrollBar().valueChanged.connect(
            lambda value: self._sync_scroll(value, self.right_editor.horizontalScrollBar(), "horizontal")
        )
        self.right_editor.horizontalScrollBar().valueChanged.connect(
            lambda value: self._sync_scroll(value, self.left_editor.horizontalScrollBar(), "horizontal")
        )
        self.left_editor.updateRequest.connect(lambda *_a: self.left_gutter.update())
        self.right_editor.updateRequest.connect(lambda *_a: self.right_gutter.update())

        self.left_editor.textChanged.connect(self._schedule_content_sync)
        self.right_editor.textChanged.connect(self._schedule_content_sync)
        self.left_gutter.copyRequested.connect(self._copy_left_to_right)
        self.right_gutter.copyRequested.connect(self._copy_right_to_left)

        self._set_loaded(False)

    def _sync_scroll(self, value: int, target_bar: QtWidgets.QScrollBar, axis: str) -> None:
        flag_name = "_syncing_vertical" if axis == "vertical" else "_syncing_horizontal"
        if getattr(self, flag_name):
            return
        setattr(self, flag_name, True)
        target_bar.setValue(value)
        setattr(self, flag_name, False)
        self.left_gutter.update()
        self.right_gutter.update()

    def _schedule_content_sync(self) -> None:
        if self._loading:
            return
        self._edit_timer.start(400)

    def has_pending_changes(self) -> bool:
        return self._edit_timer.isActive()

    def row_for_index(self, row_index: int) -> Optional[EditableDiffDisplayRow]:
        if 0 <= row_index < len(self._rows):
            return self._rows[row_index]
        return None

    @staticmethod
    def _editable_rows(rows: list[DiffRow]) -> list[EditableDiffDisplayRow]:
        return [
            EditableDiffDisplayRow(
                diff_type=row.diff_type,
                left_text=row.left_text,
                right_text=row.right_text,
                left_lineno=row.left_lineno,
                right_lineno=row.right_lineno,
                left_chunks=row.left_chunks,
                right_chunks=row.right_chunks,
                left_placeholder=row.left_lineno is None,
                right_placeholder=row.right_lineno is None,
            )
            for row in rows
        ]

    def _set_loaded(self, loaded: bool) -> None:
        self._header_container.setVisible(loaded)
        self.left_editor.setEnabled(loaded)
        self.right_editor.setEnabled(loaded)
        self.left_gutter.setVisible(loaded)
        self.right_gutter.setVisible(loaded)

    def load_result(self, result: DiffResult, *, restore_state: Optional[Dict[str, Any]] = None) -> None:
        self._edit_timer.stop()
        self._rows = self._editable_rows(result.rows)

        self.left_header.set_content(result.left_label, result.left_path, result.primary_side == CompareSide.LEFT)
        self.right_header.set_content(result.right_label, result.right_path, result.primary_side == CompareSide.RIGHT)
        self.summary_label.setText(self._summary_text(result))

        self._loading = True
        self.left_editor.set_rows(self._rows)
        self.right_editor.set_rows(self._rows)
        self._loading = False
        self.left_gutter.update()
        self.right_gutter.update()
        self._set_loaded(True)

        if restore_state:
            self.restore_view_state(restore_state)

    def _summary_text(self, result: DiffResult) -> str:
        stats = result.stats
        return (
            f"Side by Side  |  +{stats.added_lines} added  |  -{stats.deleted_lines} deleted  |  "
            f"~{stats.modified_lines} modified  |  Use arrows to copy lines"
        )

    def _side_source(self, side: CompareSide) -> tuple[EditableDiffEditor, list[str], list[bool]]:
        editor = self.left_editor if side == CompareSide.LEFT else self.right_editor
        lines = editor.display_lines()
        original_lines = [row.left_text if side == CompareSide.LEFT else row.right_text for row in self._rows]
        original_flags = [row.left_placeholder if side == CompareSide.LEFT else row.right_placeholder for row in self._rows]
        flags = [False] * len(lines)
        matcher = difflib.SequenceMatcher(None, original_lines, lines)

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag in {"equal", "replace"}:
                mapped = min(i2 - i1, j2 - j1)
                for offset in range(mapped):
                    flags[j1 + offset] = original_flags[i1 + offset]

        return editor, lines, flags

    def _logical_text(self, side: CompareSide) -> str:
        _editor, lines, flags = self._side_source(side)
        logical_lines = [line for line, placeholder in zip(lines, flags) if not placeholder or line != ""]
        return "\n".join(logical_lines)

    def logical_texts(self) -> tuple[str, str]:
        return self._logical_text(CompareSide.LEFT), self._logical_text(CompareSide.RIGHT)

    def capture_view_state(self) -> Dict[str, Any]:
        focus_side = None
        if self.left_editor.hasFocus():
            focus_side = CompareSide.LEFT
        elif self.right_editor.hasFocus():
            focus_side = CompareSide.RIGHT
        return {
            "focus_side": focus_side,
            "left": self.left_editor.capture_state(),
            "right": self.right_editor.capture_state(),
        }

    def restore_view_state(self, state: Optional[Dict[str, Any]]) -> None:
        if not state:
            return
        self.left_editor.restore_state(state.get("left"))
        self.right_editor.restore_state(state.get("right"))
        focus_side = state.get("focus_side")
        if focus_side == CompareSide.LEFT:
            self.left_editor.setFocus()
        elif focus_side == CompareSide.RIGHT:
            self.right_editor.setFocus()

    def _copy_right_to_left(self, row_index: int) -> None:
        if not (0 <= row_index < len(self._rows)):
            return
        self._loading = True
        copied_text = self.right_editor.line_text(row_index)
        self.left_editor.replace_display_line(row_index, copied_text)
        self._loading = False
        self.contentChanged.emit()

    def _copy_left_to_right(self, row_index: int) -> None:
        if not (0 <= row_index < len(self._rows)):
            return
        self._loading = True
        copied_text = self.left_editor.line_text(row_index)
        self.right_editor.replace_display_line(row_index, copied_text)
        self._loading = False
        self.contentChanged.emit()

    def clear(self) -> None:
        self._rows = []
        self._edit_timer.stop()
        self.left_editor.clear_view()
        self.right_editor.clear_view()
        self.left_header.set_content("Primary", None, True)
        self.right_header.set_content("Secondary", None, False)
        self.summary_label.setText("No comparison loaded")
        self.left_gutter.update()
        self.right_gutter.update()
        self._set_loaded(False)

    def change_count(self) -> int:
        return sum(1 for row in self._rows if row.is_changed)

    def goto_change(self, index: int) -> None:
        if self.change_count() == 0:
            return
        self.left_editor.goto_change(index)
        self.right_editor.goto_change(index)


class UnifiedDiffWidget(QtWidgets.QWidget):
    """Unified comparison view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.summary_label = QtWidgets.QLabel("No comparison loaded")
        self.summary_label.setStyleSheet(
            f"QLabel {{ padding: 6px 10px; background: {_SUMMARY_BG}; border: 1px solid {_BORDER_COLOR}; border-radius: 4px; font-weight: bold; }}"
        )
        layout.addWidget(self.summary_label)

        self.header_label = QtWidgets.QLabel("Unified comparison")
        self.header_label.setStyleSheet(
            f"QLabel {{ padding: 6px 10px; background: {_HEADER_BG}; border: 1px solid {_BORDER_COLOR}; border-radius: 4px; font-weight: bold; }}"
        )
        layout.addWidget(self.header_label)

        self.view = DiffTextView()
        layout.addWidget(self.view, 1)

    def load_result(self, result: DiffResult, *, only_changes: bool) -> None:
        stats = result.stats
        primary_label = result.left_label if result.primary_side == CompareSide.LEFT else result.right_label
        self.summary_label.setText(
            f"Unified  |  +{stats.added_lines} added  |  -{stats.deleted_lines} deleted  |  "
            f"~{stats.modified_lines} modified  |  Primary: {primary_label}"
        )
        self.header_label.setText(
            f"{_format_location(result.left_label, result.left_path)}  ->  {_format_location(result.right_label, result.right_path)}"
        )
        self._render_unified(result.rows, only_changes=only_changes)

    def _render_unified(self, rows: list[DiffRow], *, only_changes: bool) -> None:
        self.view.clear_view()
        document = self.view.document()
        cursor = QtGui.QTextCursor(document)
        change_blocks: list[int] = []
        first_row = True

        prefix_format = QtGui.QTextCharFormat()
        prefix_format.setForeground(QtGui.QColor("#6b7280"))
        text_format = QtGui.QTextCharFormat()
        changed_format = QtGui.QTextCharFormat()
        changed_format.setBackground(_CHANGE_CHAR_BG)
        changed_format.setFontWeight(QtGui.QFont.Bold)

        def insert_block(prefix: str, line_no: Optional[int], chunks: list[DiffChunk], bg: Optional[QtGui.QColor], mark_change: bool) -> None:
            nonlocal first_row
            if first_row:
                first_row = False
            else:
                cursor.insertBlock()

            block_format = QtGui.QTextBlockFormat()
            if bg is not None:
                block_format.setBackground(bg)
            cursor.setBlockFormat(block_format)

            if mark_change:
                change_blocks.append(cursor.block().blockNumber())

            cursor.insertText(f"{_line_number_text(line_no)} {prefix} ", prefix_format)
            if chunks:
                for chunk in chunks:
                    cursor.insertText(chunk.text, changed_format if chunk.changed else text_format)
            else:
                cursor.insertText(" ", text_format)

        for row in rows:
            if only_changes and not row.is_changed:
                continue

            if row.diff_type == DiffType.EQUAL:
                insert_block(" ", row.right_lineno, row.right_chunks, None, False)
            elif row.diff_type == DiffType.DELETE:
                insert_block("-", row.left_lineno, row.left_chunks, _DELETE_BG, True)
            elif row.diff_type == DiffType.INSERT:
                insert_block("+", row.right_lineno, row.right_chunks, _INSERT_BG, True)
            elif row.diff_type == DiffType.REPLACE:
                insert_block("-", row.left_lineno, row.left_chunks, _DELETE_BG, True)
                insert_block("+", row.right_lineno, row.right_chunks, _INSERT_BG, False)

        self.view.set_change_blocks(change_blocks)

    def clear(self) -> None:
        self.view.clear_view()
        self.summary_label.setText("No comparison loaded")
        self.header_label.setText("Unified comparison")

    def change_count(self) -> int:
        return self.view.change_count()

    def goto_change(self, index: int) -> None:
        self.view.goto_change(index)


_GRAY_BTN = "QPushButton { background-color: #6b7280; } QPushButton:hover { background-color: #4b5563; }"
_BLUE_BTN = "QPushButton { background-color: #1f6feb; } QPushButton:hover { background-color: #1a5fd0; }"
_ORANGE_BTN = "QPushButton { background-color: #ff9800; } QPushButton:hover { background-color: #f57c00; }"

# Structured-view colors
_STRUCT_ADDED_BG = QtGui.QColor("#d4edda")
_STRUCT_REMOVED_BG = QtGui.QColor("#f8d7da")
_STRUCT_MODIFIED_BG = QtGui.QColor("#fff3cd")
_STRUCT_PLACEHOLDER_BG = QtGui.QColor("#e9ecef")
_STRUCT_PLACEHOLDER_FG = QtGui.QColor("#999999")

_ITEM_ROLE_TYPE = QtCore.Qt.UserRole + 1     # 'message' | 'signal' | 'property' | 'placeholder'
_ITEM_ROLE_DATA = QtCore.Qt.UserRole + 2     # the full dict for message/signal
_ITEM_ROLE_MSG_IDX = QtCore.Qt.UserRole + 3  # index into the messages list
_ITEM_ROLE_SIG_IDX = QtCore.Qt.UserRole + 4  # index into the signals list
_ITEM_ROLE_STATUS = QtCore.Qt.UserRole + 5   # diff status string


class _StructuredTree(QtWidgets.QTreeWidget):
    """Single-side tree for the structured comparison view."""

    def __init__(self, side_label: str, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.side_label = side_label
        self.setHeaderLabels(["Name", "Value", "Details"])
        self.setColumnCount(3)
        self.setRootIsDecorated(True)
        self.setAlternatingRowColors(False)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setExpandsOnDoubleClick(False)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        header = self.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)

    def _apply_status_colors(self, item: QtWidgets.QTreeWidgetItem, status: str) -> None:
        bg = None
        if status == "added":
            bg = _STRUCT_ADDED_BG
        elif status == "removed":
            bg = _STRUCT_REMOVED_BG
        elif status == "modified":
            bg = _STRUCT_MODIFIED_BG

        if bg:
            for col in range(self.columnCount()):
                item.setBackground(col, bg)

    def _make_placeholder(self, text: str = "") -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem([text or "(not present)", "", ""])
        item.setData(0, _ITEM_ROLE_TYPE, "placeholder")
        item.setData(0, _ITEM_ROLE_STATUS, "placeholder")
        item.setFlags(item.flags() & ~QtCore.Qt.ItemIsSelectable)
        for col in range(self.columnCount()):
            item.setBackground(col, _STRUCT_PLACEHOLDER_BG)
            item.setForeground(col, _STRUCT_PLACEHOLDER_FG)
        return item


class StructuredDiffWidget(QtWidgets.QWidget):
    """Side-by-side tree view showing parsed DBC structure with diff colours."""

    contentChanged = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._primary_dicts: Dict[str, Any] = {"messages": []}
        self._secondary_dicts: Dict[str, Any] = {"messages": []}
        self._comparison: Optional[StructuredDiffResult] = None
        self._loading = False
        self._setup_ui()

    # ------------------------------------------------------------------ UI
    def _setup_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setContentsMargins(4, 4, 4, 4)
        self._primary_header = QtWidgets.QLabel("Primary")
        self._secondary_header = QtWidgets.QLabel("Secondary")
        self._primary_header.setStyleSheet(
            f"font-weight: bold; padding: 4px 8px; background: {_HEADER_BG}; border-radius: 3px;"
        )
        self._secondary_header.setStyleSheet(
            f"font-weight: bold; padding: 4px 8px; background: {_HEADER_BG}; border-radius: 3px;"
        )
        header_layout.addWidget(self._primary_header, 1)
        header_layout.addWidget(self._secondary_header, 1)
        self._header_widget = QtWidgets.QWidget()
        self._header_widget.setLayout(header_layout)
        root.addWidget(self._header_widget)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.primary_tree = _StructuredTree("Primary")
        self.secondary_tree = _StructuredTree("Secondary")
        splitter.addWidget(self.primary_tree)
        splitter.addWidget(self.secondary_tree)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        self._summary_label = QtWidgets.QLabel()
        self._summary_label.setStyleSheet(
            f"padding: 4px 8px; background: {_SUMMARY_BG}; border-top: 1px solid {_BORDER_COLOR};"
        )
        root.addWidget(self._summary_label)

        self.primary_tree.verticalScrollBar().valueChanged.connect(
            self.secondary_tree.verticalScrollBar().setValue
        )
        self.secondary_tree.verticalScrollBar().valueChanged.connect(
            self.primary_tree.verticalScrollBar().setValue
        )
        self.primary_tree.itemExpanded.connect(
            lambda item: self._sync_expand(item, self.primary_tree, self.secondary_tree)
        )
        self.primary_tree.itemCollapsed.connect(
            lambda item: self._sync_collapse(item, self.primary_tree, self.secondary_tree)
        )
        self.secondary_tree.itemExpanded.connect(
            lambda item: self._sync_expand(item, self.secondary_tree, self.primary_tree)
        )
        self.secondary_tree.itemCollapsed.connect(
            lambda item: self._sync_collapse(item, self.secondary_tree, self.primary_tree)
        )

        self.primary_tree.customContextMenuRequested.connect(
            lambda pos: self._show_context_menu(self.primary_tree, pos, "primary")
        )
        self.secondary_tree.customContextMenuRequested.connect(
            lambda pos: self._show_context_menu(self.secondary_tree, pos, "secondary")
        )
        self.primary_tree.itemDoubleClicked.connect(
            lambda item, col: self._on_double_click(item, "primary")
        )
        self.secondary_tree.itemDoubleClicked.connect(
            lambda item, col: self._on_double_click(item, "secondary")
        )

        self._set_loaded(False)

    def _set_loaded(self, loaded: bool) -> None:
        self._header_widget.setVisible(loaded)
        self.primary_tree.setVisible(loaded)
        self.secondary_tree.setVisible(loaded)
        self._summary_label.setVisible(loaded)

    # --------------------------------------------------------- expand sync
    @staticmethod
    def _sync_expand(
        item: QtWidgets.QTreeWidgetItem,
        source_tree: _StructuredTree,
        target_tree: _StructuredTree,
    ) -> None:
        path = StructuredDiffWidget._item_path(item, source_tree)
        partner = StructuredDiffWidget._item_at_path(target_tree, path)
        if partner and not partner.isExpanded():
            target_tree.blockSignals(True)
            partner.setExpanded(True)
            target_tree.blockSignals(False)

    @staticmethod
    def _sync_collapse(
        item: QtWidgets.QTreeWidgetItem,
        source_tree: _StructuredTree,
        target_tree: _StructuredTree,
    ) -> None:
        path = StructuredDiffWidget._item_path(item, source_tree)
        partner = StructuredDiffWidget._item_at_path(target_tree, path)
        if partner and partner.isExpanded():
            target_tree.blockSignals(True)
            partner.setExpanded(False)
            target_tree.blockSignals(False)

    @staticmethod
    def _item_path(
        item: QtWidgets.QTreeWidgetItem,
        tree: QtWidgets.QTreeWidget,
    ) -> List[int]:
        path: List[int] = []
        current = item
        while current:
            parent = current.parent()
            if parent:
                path.insert(0, parent.indexOfChild(current))
            else:
                path.insert(0, tree.indexOfTopLevelItem(current))
            current = parent
        return path

    @staticmethod
    def _item_at_path(
        tree: QtWidgets.QTreeWidget,
        path: List[int],
    ) -> Optional[QtWidgets.QTreeWidgetItem]:
        if not path:
            return None
        current = tree.topLevelItem(path[0]) if path[0] < tree.topLevelItemCount() else None
        for idx in path[1:]:
            if current is None:
                return None
            current = current.child(idx) if idx < current.childCount() else None
        return current

    # -------------------------------------------------------- load / clear
    def load(
        self,
        primary_text: str,
        secondary_text: str,
        primary_label: str = "Primary",
        secondary_label: str = "Secondary",
    ) -> None:
        self._loading = True
        try:
            self._primary_dicts = parse_dbc_to_dicts(primary_text)
        except Exception:
            logger.warning("Failed to parse primary DBC for structured view", exc_info=True)
            self._primary_dicts = {"messages": []}
        try:
            self._secondary_dicts = parse_dbc_to_dicts(secondary_text)
        except Exception:
            logger.warning("Failed to parse secondary DBC for structured view", exc_info=True)
            self._secondary_dicts = {"messages": []}

        self._comparison = compare_dbc_structures(self._primary_dicts, self._secondary_dicts)
        self._primary_header.setText(primary_label)
        self._secondary_header.setText(secondary_label)
        self._populate_trees()
        self._set_loaded(True)
        self._loading = False

    def clear(self) -> None:
        self.primary_tree.clear()
        self.secondary_tree.clear()
        self._primary_dicts = {"messages": []}
        self._secondary_dicts = {"messages": []}
        self._comparison = None
        self._summary_label.setText("")
        self._set_loaded(False)

    def change_count(self) -> int:
        if not self._comparison:
            return 0
        return sum(
            1 for mc in self._comparison.message_comparisons
            if mc.diff_status.status != "unchanged"
        )

    def goto_change(self, index: int) -> None:
        if not self._comparison:
            return
        changed = [
            i for i, mc in enumerate(self._comparison.message_comparisons)
            if mc.diff_status.status != "unchanged"
        ]
        if not changed or index >= len(changed):
            return
        top_index = changed[index]
        primary_item = self.primary_tree.topLevelItem(top_index)
        secondary_item = self.secondary_tree.topLevelItem(top_index)
        if primary_item:
            self.primary_tree.scrollToItem(primary_item)
            self.primary_tree.setCurrentItem(primary_item)
        if secondary_item:
            self.secondary_tree.scrollToItem(secondary_item)

    def has_pending_changes(self) -> bool:
        return False

    def primary_data(self) -> Dict[str, Any]:
        return copy.deepcopy(self._primary_dicts)

    def secondary_data(self) -> Dict[str, Any]:
        return copy.deepcopy(self._secondary_dicts)

    # ------------------------------------------------- tree population
    def _populate_trees(self) -> None:
        self.primary_tree.clear()
        self.secondary_tree.clear()
        if not self._comparison:
            return

        for mc in self._comparison.message_comparisons:
            p_item = self._build_message_item(mc, "primary")
            s_item = self._build_message_item(mc, "secondary")
            self.primary_tree.addTopLevelItem(p_item)
            self.secondary_tree.addTopLevelItem(s_item)

        r = self._comparison
        parts = []
        if r.primary_only_count:
            parts.append(f"{r.primary_only_count} primary-only")
        if r.secondary_only_count:
            parts.append(f"{r.secondary_only_count} secondary-only")
        if r.modified_count:
            parts.append(f"{r.modified_count} modified")
        if r.unchanged_count:
            parts.append(f"{r.unchanged_count} unchanged")
        total = len(r.message_comparisons)
        self._summary_label.setText(
            f"Structured comparison: {total} messages — " + ", ".join(parts)
            if parts else f"Structured comparison: {total} messages — identical"
        )

    def _build_message_item(
        self,
        mc: MessageComparisonItem,
        side: str,
    ) -> QtWidgets.QTreeWidgetItem:
        msg = mc.primary_message if side == "primary" else mc.secondary_message
        status = mc.diff_status.status
        is_present = msg is not None

        if not is_present:
            placeholder = self.primary_tree._make_placeholder(
                f"{mc.name} (0x{mc.frame_id:X})"
            )
            self._add_placeholder_children(placeholder, mc, side)
            return placeholder

        label = f"{msg['name']} (0x{msg['frame_id']:X})"
        frame_type = "CAN FD" if msg.get("is_fd") else "CAN"
        item = QtWidgets.QTreeWidgetItem([label, f"{msg['length']} bytes", frame_type])
        item.setData(0, _ITEM_ROLE_TYPE, "message")
        item.setData(0, _ITEM_ROLE_DATA, msg)
        item.setData(0, _ITEM_ROLE_STATUS, status)
        item.setIcon(0, qta.icon("fa5s.envelope", color="#444"))

        effective_status = status
        if side == "primary" and status == "added":
            effective_status = "placeholder"
        elif side == "secondary" and status == "removed":
            effective_status = "placeholder"

        tree = self.primary_tree if side == "primary" else self.secondary_tree
        if effective_status != "placeholder":
            tree._apply_status_colors(item, effective_status)

        props_group = QtWidgets.QTreeWidgetItem(["Properties", "", ""])
        props_group.setData(0, _ITEM_ROLE_TYPE, "group")
        props_group.setIcon(0, qta.icon("fa5s.cog", color="#888"))
        self._add_message_properties(props_group, msg, mc, side)
        item.addChild(props_group)

        signals_group = QtWidgets.QTreeWidgetItem([
            f"Signals ({len(msg.get('signals', []))})", "", ""
        ])
        signals_group.setData(0, _ITEM_ROLE_TYPE, "group")
        signals_group.setIcon(0, qta.icon("fa5s.broadcast-tower", color="#888"))
        self._add_signal_items(signals_group, mc, side)
        item.addChild(signals_group)

        if status != "unchanged":
            item.setExpanded(True)
            signals_group.setExpanded(True)

        return item

    def _add_placeholder_children(
        self,
        placeholder: QtWidgets.QTreeWidgetItem,
        mc: MessageComparisonItem,
        side: str,
    ) -> None:
        """Add empty child placeholders to keep tree alignment with the other side."""
        other_msg = mc.secondary_message if side == "primary" else mc.primary_message
        if not other_msg:
            return
        props_ph = self.primary_tree._make_placeholder("Properties")
        placeholder.addChild(props_ph)
        sig_count = len(other_msg.get("signals", []))
        sigs_ph = self.primary_tree._make_placeholder(f"Signals ({sig_count})")
        placeholder.addChild(sigs_ph)
        for sc in mc.signal_comparisons:
            sigs_ph.addChild(self.primary_tree._make_placeholder(sc.name))

    def _add_message_properties(
        self,
        parent: QtWidgets.QTreeWidgetItem,
        msg: Dict[str, Any],
        mc: MessageComparisonItem,
        side: str,
    ) -> None:
        changed_props = mc.diff_status.changed_properties
        props = [
            ("Name", msg.get("name", "")),
            ("Frame ID", f"0x{msg.get('frame_id', 0):X}"),
            ("Length", f"{msg.get('length', 0)} bytes"),
            ("Senders", ", ".join(msg.get("senders", [])) or "(none)"),
            ("Cycle Time", str(msg.get("cycle_time") or "(none)")),
            ("Send Type", str(msg.get("send_type") or "(none)")),
            ("Bus Type", "CAN FD" if msg.get("is_fd") else "CAN"),
            ("Comment", msg.get("comments") or "(none)"),
        ]
        for prop_name, prop_value in props:
            child = QtWidgets.QTreeWidgetItem([prop_name, str(prop_value), ""])
            child.setData(0, _ITEM_ROLE_TYPE, "property")
            key_map = {
                "Name": "name", "Length": "length", "Senders": "senders",
                "Cycle Time": "cycle_time", "Send Type": "send_type",
                "Bus Type": "is_fd", "Comment": "comments",
            }
            if key_map.get(prop_name) in changed_props:
                for col in range(3):
                    child.setBackground(col, _STRUCT_MODIFIED_BG)
            parent.addChild(child)

    def _add_signal_items(
        self,
        parent: QtWidgets.QTreeWidgetItem,
        mc: MessageComparisonItem,
        side: str,
    ) -> None:
        msg = mc.primary_message if side == "primary" else mc.secondary_message
        signals = msg.get("signals", []) if msg else []
        sig_name_to_idx = {s["name"]: i for i, s in enumerate(signals)}
        tree = self.primary_tree if side == "primary" else self.secondary_tree

        for sc in mc.signal_comparisons:
            sig = sc.primary_signal if side == "primary" else sc.secondary_signal
            sig_status = sc.diff_status.status

            if sig is None:
                ph = tree._make_placeholder(sc.name)
                parent.addChild(ph)
                continue

            mux_tag = format_mux_indicator(sig)
            name_display = f"{mux_tag} {sig['name']}" if mux_tag else sig["name"]
            bits_info = f"{sig.get('start_bit', 0)}:{sig.get('length', 0)}"
            scale_info = f"Scale: {sig.get('scale', 1.0)} {sig.get('unit', '')}"

            sig_item = QtWidgets.QTreeWidgetItem([name_display, bits_info, scale_info])
            sig_item.setData(0, _ITEM_ROLE_TYPE, "signal")
            sig_item.setData(0, _ITEM_ROLE_DATA, sig)
            sig_item.setData(0, _ITEM_ROLE_STATUS, sig_status)
            if sig["name"] in sig_name_to_idx:
                sig_item.setData(0, _ITEM_ROLE_SIG_IDX, sig_name_to_idx[sig["name"]])
            sig_item.setIcon(0, qta.icon("fa5s.signal", color="#444") if not mux_tag
                             else qta.icon("fa5s.random", color="#6f42c1"))

            effective_status = sig_status
            if side == "primary" and sig_status == "added":
                effective_status = "unchanged"
            elif side == "secondary" and sig_status == "removed":
                effective_status = "unchanged"
            tree._apply_status_colors(sig_item, effective_status)

            self._add_signal_properties(sig_item, sig, sc, side)

            if sig_status != "unchanged":
                sig_item.setExpanded(True)

            parent.addChild(sig_item)

    def _add_signal_properties(
        self,
        parent: QtWidgets.QTreeWidgetItem,
        sig: Dict[str, Any],
        sc: SignalComparisonItem,
        side: str,
    ) -> None:
        changed_props = sc.diff_status.changed_properties
        props = [
            ("Start Bit", str(sig.get("start_bit", 0)), "start_bit"),
            ("Length", str(sig.get("length", 0)), "length"),
            ("Byte Order", sig.get("byte_order", "little_endian"), "byte_order"),
            ("Signed", "Yes" if sig.get("is_signed") else "No", "is_signed"),
            ("Scale", str(sig.get("scale", 1.0)), "scale"),
            ("Offset", str(sig.get("offset", 0.0)), "offset"),
            ("Min", str(sig.get("minimum") if sig.get("minimum") is not None else "(none)"), "minimum"),
            ("Max", str(sig.get("maximum") if sig.get("maximum") is not None else "(none)"), "maximum"),
            ("Unit", sig.get("unit") or "(none)", "unit"),
            ("Receivers", ", ".join(sig.get("receivers", [])) or "(none)", "receivers"),
            ("Comment", sig.get("comments") or "(none)", "comments"),
        ]
        for prop_name, prop_value, key in props:
            child = QtWidgets.QTreeWidgetItem([prop_name, prop_value, ""])
            child.setData(0, _ITEM_ROLE_TYPE, "property")
            if key in changed_props:
                for col in range(3):
                    child.setBackground(col, _STRUCT_MODIFIED_BG)
            parent.addChild(child)

    # ----------------------------------------------- context menu / editing
    def _show_context_menu(
        self, tree: _StructuredTree, pos: QtCore.QPoint, side: str
    ) -> None:
        item = tree.itemAt(pos)
        menu = QtWidgets.QMenu(self)
        other_side = "secondary" if side == "primary" else "primary"
        other_label = "Secondary" if side == "primary" else "Primary"

        if item is None:
            add_msg_action = menu.addAction(
                qta.icon("fa5s.plus", color="#28a745"), "Add Message"
            )
            add_msg_action.triggered.connect(lambda: self._add_message(side))
        else:
            item_type = item.data(0, _ITEM_ROLE_TYPE)
            item_status = item.data(0, _ITEM_ROLE_STATUS)

            if item_type == "message" and item_status != "placeholder":
                edit_action = menu.addAction(
                    qta.icon("fa5s.edit", color="#007bff"), "Edit Message"
                )
                edit_action.triggered.connect(lambda: self._edit_message(item, side))
                menu.addSeparator()
                add_sig_action = menu.addAction(
                    qta.icon("fa5s.plus", color="#28a745"), "Add Signal"
                )
                add_sig_action.triggered.connect(lambda: self._add_signal(item, side))
                menu.addSeparator()
                copy_action = menu.addAction(
                    qta.icon("fa5s.copy", color="#6f42c1"),
                    f"Copy Message to {other_label}",
                )
                copy_action.triggered.connect(
                    lambda: self._copy_message(item, side, other_side)
                )
                menu.addSeparator()
                del_action = menu.addAction(
                    qta.icon("fa5s.trash", color="#dc3545"), "Delete Message"
                )
                del_action.triggered.connect(lambda: self._delete_message(item, side))

            elif item_type == "signal" and item_status != "placeholder":
                edit_action = menu.addAction(
                    qta.icon("fa5s.edit", color="#007bff"), "Edit Signal"
                )
                edit_action.triggered.connect(lambda: self._edit_signal(item, side))
                menu.addSeparator()
                copy_action = menu.addAction(
                    qta.icon("fa5s.copy", color="#6f42c1"),
                    f"Copy Signal to {other_label}",
                )
                copy_action.triggered.connect(
                    lambda: self._copy_signal(item, side, other_side)
                )
                menu.addSeparator()
                del_action = menu.addAction(
                    qta.icon("fa5s.trash", color="#dc3545"), "Delete Signal"
                )
                del_action.triggered.connect(lambda: self._delete_signal(item, side))

            elif item_type == "placeholder":
                pass
            else:
                return

        if menu.actions():
            menu.exec_(tree.viewport().mapToGlobal(pos))

    def _on_double_click(self, item: QtWidgets.QTreeWidgetItem, side: str) -> None:
        item_type = item.data(0, _ITEM_ROLE_TYPE)
        if item_type == "message":
            self._edit_message(item, side)
        elif item_type == "signal":
            self._edit_signal(item, side)

    # ------------------------------------------- editing helpers
    def _get_dicts(self, side: str) -> Dict[str, Any]:
        return self._primary_dicts if side == "primary" else self._secondary_dicts

    def _find_message_index(self, item: QtWidgets.QTreeWidgetItem, side: str) -> int:
        msg_data = item.data(0, _ITEM_ROLE_DATA)
        if not msg_data:
            return -1
        dicts = self._get_dicts(side)
        for i, m in enumerate(dicts.get("messages", [])):
            if m.get("frame_id") == msg_data.get("frame_id"):
                return i
        return -1

    def _find_message_item_for_signal(
        self, sig_item: QtWidgets.QTreeWidgetItem
    ) -> Optional[QtWidgets.QTreeWidgetItem]:
        parent = sig_item.parent()
        if parent and parent.data(0, _ITEM_ROLE_TYPE) == "group":
            return parent.parent()
        return parent

    def _find_signal_index(
        self, sig_item: QtWidgets.QTreeWidgetItem, msg_dict: Dict[str, Any]
    ) -> int:
        sig_data = sig_item.data(0, _ITEM_ROLE_DATA)
        if not sig_data:
            return -1
        for i, s in enumerate(msg_dict.get("signals", [])):
            if s.get("name") == sig_data.get("name"):
                return i
        return -1

    def _notify_change(self) -> None:
        self._comparison = compare_dbc_structures(self._primary_dicts, self._secondary_dicts)
        self._populate_trees()
        self.contentChanged.emit()

    # ------------------------------------------- message operations
    def _add_message(self, side: str) -> None:
        from dbc_editor_ui import MessageEditDialog
        dlg = MessageEditDialog(self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            new_msg = dlg.get_data()
            new_msg.setdefault("signals", [])
            dicts = self._get_dicts(side)
            dicts.setdefault("messages", []).append(new_msg)
            self._notify_change()

    def _edit_message(self, item: QtWidgets.QTreeWidgetItem, side: str) -> None:
        from dbc_editor_ui import MessageEditDialog
        msg_data = item.data(0, _ITEM_ROLE_DATA)
        if not msg_data:
            return
        idx = self._find_message_index(item, side)
        if idx < 0:
            return
        dlg = MessageEditDialog(self, message_data=msg_data)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            updated = dlg.get_data()
            updated["signals"] = msg_data.get("signals", [])
            dicts = self._get_dicts(side)
            dicts["messages"][idx] = updated
            self._notify_change()

    def _delete_message(self, item: QtWidgets.QTreeWidgetItem, side: str) -> None:
        msg_data = item.data(0, _ITEM_ROLE_DATA)
        if not msg_data:
            return
        name = msg_data.get("name", "?")
        reply = QtWidgets.QMessageBox.question(
            self, "Delete Message",
            f'Delete message "{name}" from {side}?',
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        idx = self._find_message_index(item, side)
        if idx >= 0:
            dicts = self._get_dicts(side)
            dicts["messages"].pop(idx)
            self._notify_change()

    def _copy_message(
        self, item: QtWidgets.QTreeWidgetItem, from_side: str, to_side: str
    ) -> None:
        msg_data = item.data(0, _ITEM_ROLE_DATA)
        if not msg_data:
            return
        dicts = self._get_dicts(to_side)
        messages = dicts.setdefault("messages", [])
        for existing in messages:
            if existing.get("frame_id") == msg_data.get("frame_id"):
                reply = QtWidgets.QMessageBox.question(
                    self, "Overwrite?",
                    f'Message 0x{msg_data["frame_id"]:X} already exists in {to_side}. Overwrite?',
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                )
                if reply != QtWidgets.QMessageBox.Yes:
                    return
                idx = messages.index(existing)
                messages[idx] = copy.deepcopy(msg_data)
                self._notify_change()
                return
        messages.append(copy.deepcopy(msg_data))
        self._notify_change()

    # ------------------------------------------- signal operations
    def _add_signal(self, msg_item: QtWidgets.QTreeWidgetItem, side: str) -> None:
        from dbc_editor_ui import SignalEditDialog
        msg_data = msg_item.data(0, _ITEM_ROLE_DATA)
        if not msg_data:
            return
        existing_sigs = msg_data.get("signals", [])
        dlg = SignalEditDialog(
            self,
            existing_receivers=[],
            message_senders=msg_data.get("senders", []),
            message_signals=existing_sigs,
        )
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            new_sig = dlg.get_data()
            idx = self._find_message_index(msg_item, side)
            if idx >= 0:
                dicts = self._get_dicts(side)
                dicts["messages"][idx].setdefault("signals", []).append(new_sig)
                self._notify_change()

    def _edit_signal(self, sig_item: QtWidgets.QTreeWidgetItem, side: str) -> None:
        from dbc_editor_ui import SignalEditDialog
        sig_data = sig_item.data(0, _ITEM_ROLE_DATA)
        if not sig_data:
            return
        msg_item = self._find_message_item_for_signal(sig_item)
        if not msg_item:
            return
        msg_data = msg_item.data(0, _ITEM_ROLE_DATA)
        if not msg_data:
            return
        msg_idx = self._find_message_index(msg_item, side)
        sig_idx = self._find_signal_index(sig_item, msg_data)
        if msg_idx < 0 or sig_idx < 0:
            return
        dlg = SignalEditDialog(
            self,
            signal_data=sig_data,
            existing_receivers=[],
            message_senders=msg_data.get("senders", []),
            message_signals=msg_data.get("signals", []),
        )
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            updated = dlg.get_data()
            dicts = self._get_dicts(side)
            dicts["messages"][msg_idx]["signals"][sig_idx] = updated
            self._notify_change()

    def _delete_signal(self, sig_item: QtWidgets.QTreeWidgetItem, side: str) -> None:
        sig_data = sig_item.data(0, _ITEM_ROLE_DATA)
        if not sig_data:
            return
        name = sig_data.get("name", "?")
        reply = QtWidgets.QMessageBox.question(
            self, "Delete Signal",
            f'Delete signal "{name}" from {side}?',
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        msg_item = self._find_message_item_for_signal(sig_item)
        if not msg_item:
            return
        msg_data = msg_item.data(0, _ITEM_ROLE_DATA)
        if not msg_data:
            return
        msg_idx = self._find_message_index(msg_item, side)
        sig_idx = self._find_signal_index(sig_item, msg_data)
        if msg_idx >= 0 and sig_idx >= 0:
            dicts = self._get_dicts(side)
            dicts["messages"][msg_idx]["signals"].pop(sig_idx)
            self._notify_change()

    def _copy_signal(
        self, sig_item: QtWidgets.QTreeWidgetItem, from_side: str, to_side: str
    ) -> None:
        sig_data = sig_item.data(0, _ITEM_ROLE_DATA)
        if not sig_data:
            return
        msg_item = self._find_message_item_for_signal(sig_item)
        if not msg_item:
            return
        msg_data = msg_item.data(0, _ITEM_ROLE_DATA)
        if not msg_data:
            return
        frame_id = msg_data.get("frame_id")

        target_dicts = self._get_dicts(to_side)
        target_msg = None
        target_msg_idx = -1
        for i, m in enumerate(target_dicts.get("messages", [])):
            if m.get("frame_id") == frame_id:
                target_msg = m
                target_msg_idx = i
                break

        if target_msg is None:
            QtWidgets.QMessageBox.warning(
                self, "No Target Message",
                f"Message 0x{frame_id:X} does not exist in {to_side}. "
                "Copy the message first.",
            )
            return

        new_sig = copy.deepcopy(sig_data)
        for i, existing in enumerate(target_msg.get("signals", [])):
            if existing.get("name") == new_sig.get("name"):
                target_msg["signals"][i] = new_sig
                self._notify_change()
                return
        target_msg.setdefault("signals", []).append(new_sig)
        self._notify_change()


class DBCCompareWidget(QtWidgets.QWidget):
    """Full-featured comparison tool for standalone use and editor save review."""

    saveConfirmed = QtCore.pyqtSignal(str, str)
    reviewCancelled = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._review_file_path: Optional[str] = None
        self._current_result: Optional[DiffResult] = None
        self._current_change_index = 0
        self._review_mode = False
        self._left_text = ""
        self._right_text = ""
        self._left_label = "Primary"
        self._right_label = "Secondary"
        self._left_path: Optional[str] = None
        self._right_path: Optional[str] = None
        self._history: list[tuple[str, str]] = []
        self._history_index = -1
        self._restoring_history = False
        self._left_saved_text = ""
        self._right_saved_text = ""
        self._left_dirty = False
        self._right_dirty = False
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 6)
        root.setSpacing(6)

        self.setStyleSheet(
            f"""
            QGroupBox {{
                font-weight: bold;
                border: 2px solid {_BORDER_COLOR};
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }}
            QPushButton {{
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 6px 12px;
                border-radius: 4px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background-color: #45a049; }}
            QPushButton:pressed {{ background-color: #3d8b40; }}
            QPushButton:disabled {{ background-color: #cccccc; color: #666666; }}
            QLineEdit, QComboBox {{
                padding: 5px;
                border: 1px solid {_BORDER_COLOR};
                border-radius: 3px;
            }}
            QCheckBox {{
                padding: 2px 4px;
            }}
            """
        )

        toolbar_group = QtWidgets.QGroupBox("DBC Comparison Tools")
        toolbar_main = QtWidgets.QVBoxLayout()
        toolbar_main.setContentsMargins(8, 10, 8, 8)
        toolbar_main.setSpacing(6)

        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(6)

        self.file_a_edit = QtWidgets.QLineEdit()
        self.file_a_edit.setPlaceholderText("Primary file (left)")
        self.file_b_edit = QtWidgets.QLineEdit()
        self.file_b_edit.setPlaceholderText("Secondary file (right)")

        self.browse_a_button = QtWidgets.QPushButton()
        self.save_primary_button = QtWidgets.QPushButton()
        self.save_primary_button.setStyleSheet(_ORANGE_BTN)
        self.save_primary_button.setEnabled(False)
        self.browse_b_button = QtWidgets.QPushButton()
        self.save_secondary_button = QtWidgets.QPushButton()
        self.save_secondary_button.setStyleSheet(_ORANGE_BTN)
        self.save_secondary_button.setEnabled(False)
        self.swap_button = QtWidgets.QPushButton()
        self.swap_button.setStyleSheet(_BLUE_BTN)
        self.compare_button = QtWidgets.QPushButton()

        row1.addWidget(QtWidgets.QLabel("Primary:"))
        row1.addWidget(self.file_a_edit, 3)
        row1.addWidget(self.browse_a_button)
        row1.addWidget(self.save_primary_button)
        row1.addWidget(QtWidgets.QLabel("Secondary:"))
        row1.addWidget(self.file_b_edit, 3)
        row1.addWidget(self.browse_b_button)
        row1.addWidget(self.save_secondary_button)
        toolbar_main.addLayout(row1)

        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(6)

        self.view_mode_combo = QtWidgets.QComboBox()
        self.view_mode_combo.addItems(["Side by Side", "Unified", "Structured"])
        self.only_changes_check = QtWidgets.QCheckBox("Only Changes")
        self.ignore_whitespace_check = QtWidgets.QCheckBox("Ignore Whitespace")

        self.prev_button = QtWidgets.QPushButton()
        self.next_button = QtWidgets.QPushButton()
        self.prev_button.setStyleSheet(_GRAY_BTN)
        self.next_button.setStyleSheet(_GRAY_BTN)

        self.undo_button = QtWidgets.QPushButton()
        self.redo_button = QtWidgets.QPushButton()
        self.undo_button.setStyleSheet(_GRAY_BTN)
        self.redo_button.setStyleSheet(_GRAY_BTN)

        self.refresh_button = QtWidgets.QPushButton()
        self.refresh_button.setStyleSheet(_BLUE_BTN)

        row2.addWidget(self.swap_button)
        row2.addWidget(self.compare_button)
        row2.addWidget(self.refresh_button)
        row2.addWidget(self._separator())
        row2.addWidget(QtWidgets.QLabel("View:"))
        row2.addWidget(self.view_mode_combo)
        row2.addWidget(self.only_changes_check)
        row2.addWidget(self.ignore_whitespace_check)
        row2.addWidget(self._separator())
        row2.addWidget(self.prev_button)
        row2.addWidget(self.next_button)
        row2.addWidget(self._separator())
        row2.addWidget(self.undo_button)
        row2.addWidget(self.redo_button)
        row2.addStretch()
        toolbar_main.addLayout(row2)

        toolbar_group.setLayout(toolbar_main)
        root.addWidget(toolbar_group)

        # --- Review header ---
        self.review_header = QtWidgets.QLabel()
        self.review_header.setStyleSheet(
            "QLabel { padding: 8px 12px; background: #fff3cd; border: 1px solid #ffc107; border-radius: 4px; font-weight: bold; color: #856404; }"
        )
        self.review_header.hide()
        root.addWidget(self.review_header)

        # --- Diff views ---
        self.view_stack = QtWidgets.QStackedWidget()
        self.side_by_side_view = SideBySideDiffWidget()
        self.unified_view = UnifiedDiffWidget()
        self.structured_view = StructuredDiffWidget()
        self.view_stack.addWidget(self.side_by_side_view)
        self.view_stack.addWidget(self.unified_view)
        self.view_stack.addWidget(self.structured_view)
        root.addWidget(self.view_stack, 1)

        # --- Review action bar ---
        self.review_actions = QtWidgets.QWidget()
        review_layout = QtWidgets.QHBoxLayout(self.review_actions)
        review_layout.setContentsMargins(0, 0, 0, 0)
        review_layout.addStretch()
        self.back_button = QtWidgets.QPushButton("Back to Editor")
        self.back_button.setStyleSheet(_GRAY_BTN)
        self.confirm_save_button = QtWidgets.QPushButton("Confirm Save")
        self.confirm_save_button.setStyleSheet(_ORANGE_BTN)
        review_layout.addWidget(self.back_button)
        review_layout.addWidget(self.confirm_save_button)
        self.review_actions.hide()
        root.addWidget(self.review_actions)

        # --- Status bar ---
        status_layout = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("Ready")
        self.navigation_label = QtWidgets.QLabel("No changes")
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.navigation_label)
        root.addLayout(status_layout)

        self.browse_a_button.clicked.connect(lambda: self._browse_file(self.file_a_edit))
        self.browse_b_button.clicked.connect(lambda: self._browse_file(self.file_b_edit))
        self.swap_button.clicked.connect(self._swap_files)
        self.compare_button.clicked.connect(self._compare_selected_files)
        self.refresh_button.clicked.connect(self._refresh_from_disk)
        self.view_mode_combo.currentIndexChanged.connect(self._on_view_mode_changed)
        self.only_changes_check.toggled.connect(self._render_current_result)
        self.ignore_whitespace_check.toggled.connect(self._on_ignore_whitespace_toggled)
        self.prev_button.clicked.connect(self._goto_previous_change)
        self.next_button.clicked.connect(self._goto_next_change)
        self.undo_button.clicked.connect(self._undo_comparison)
        self.redo_button.clicked.connect(self._redo_comparison)
        self.save_primary_button.clicked.connect(self._save_primary)
        self.save_secondary_button.clicked.connect(self._save_secondary)
        self.back_button.clicked.connect(self._on_cancel_review)
        self.confirm_save_button.clicked.connect(self._on_confirm_save)
        self.side_by_side_view.contentChanged.connect(self._on_side_by_side_content_changed)
        self.side_by_side_view.left_editor.undoRequested.connect(self._undo_comparison)
        self.side_by_side_view.right_editor.undoRequested.connect(self._undo_comparison)
        self.side_by_side_view.left_editor.redoRequested.connect(self._redo_comparison)
        self.side_by_side_view.right_editor.redoRequested.connect(self._redo_comparison)
        self.structured_view.contentChanged.connect(self._on_structured_content_changed)

        self._undo_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence.Undo, self)
        self._undo_shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
        self._undo_shortcut.activated.connect(self._undo_comparison)
        self._redo_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence.Redo, self)
        self._redo_shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
        self._redo_shortcut.activated.connect(self._redo_comparison)

        self._apply_icons()
        self._update_mode_controls()

    @staticmethod
    def _separator() -> QtWidgets.QFrame:
        sep = QtWidgets.QFrame()
        sep.setFrameShape(QtWidgets.QFrame.VLine)
        sep.setFrameShadow(QtWidgets.QFrame.Sunken)
        sep.setFixedWidth(2)
        return sep

    def _apply_icons(self) -> None:
        icon_size = QtCore.QSize(18, 18)
        icon_only_buttons = (
            (self.browse_a_button, "fa5s.folder-open", "Browse primary file"),
            (self.browse_b_button, "fa5s.folder-open", "Browse secondary file"),
            (self.swap_button, "fa5s.exchange-alt", "Swap primary and secondary"),
            (self.compare_button, "fa6s.code-compare", "Compare files"),
            (self.refresh_button, "fa5s.sync-alt", "Refresh from disk"),
            (self.prev_button, "fa5s.chevron-left", "Previous change"),
            (self.next_button, "fa5s.chevron-right", "Next change"),
            (self.undo_button, "fa5s.undo", "Undo (Ctrl+Z)"),
            (self.redo_button, "fa5s.redo", "Redo (Ctrl+Y)"),
            (self.save_primary_button, "fa5s.save", "Save primary file"),
            (self.save_secondary_button, "fa5s.save", "Save secondary file"),
        )
        btn_size = QtCore.QSize(32, 32)
        for button, icon_name, tooltip in icon_only_buttons:
            button.setIcon(qta.icon(icon_name, color="white"))
            button.setIconSize(icon_size)
            button.setToolTip(tooltip)
            button.setFixedSize(btn_size)

        for button, icon_name, tooltip in (
            (self.back_button, "fa5s.arrow-left", "Back to editor"),
            (self.confirm_save_button, "fa5s.check", "Confirm save"),
        ):
            button.setIcon(qta.icon(icon_name, color="white"))
            button.setIconSize(icon_size)
            button.setToolTip(tooltip)

    def _update_mode_controls(self) -> None:
        mode_idx = self.view_mode_combo.currentIndex()
        is_unified = mode_idx == 1
        self.only_changes_check.setEnabled(is_unified)
        self.only_changes_check.setToolTip(
            "" if is_unified else "Only Changes is available in Unified view."
        )
        if mode_idx == 0:
            self.status_label.setText("Side by Side view is editable. Use the inline arrows to copy individual lines.")
        elif mode_idx == 2:
            self.status_label.setText("Structured view: double-click or right-click to edit messages and signals.")
        self._update_history_controls()

    @staticmethod
    def _validate_dbc_text(dbc_text: str) -> None:
        try:
            cantools.database.load_string(dbc_text, database_format="dbc", strict=True)
        except cantools.database.errors.Error as exc:
            if "are overlapping in message" in str(exc):
                cantools.database.load_string(dbc_text, database_format="dbc", strict=False)
            else:
                raise

    def _read_selected_file(self, path: str, role: str) -> Optional[str]:
        if not path:
            QtWidgets.QMessageBox.warning(self, "Missing File", f"Select a {role.lower()} file before comparing.")
            return None
        if not os.path.isfile(path):
            QtWidgets.QMessageBox.warning(self, "File Not Found", f"{role} file not found:\n{path}")
            return None
        try:
            return _read_text_file(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Read Error", f"Could not read {role.lower()} file:\n{exc}")
            return None

    def _browse_file(self, target_edit: QtWidgets.QLineEdit) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select DBC File",
            target_edit.text().strip(),
            "DBC Files (*.dbc);;All Files (*)",
        )
        if path:
            target_edit.setText(path)

    def _swap_files(self) -> None:
        self._sync_live_texts()
        a_text, b_text = self.file_a_edit.text(), self.file_b_edit.text()
        a_label, b_label = self._left_label, self._right_label
        a_path, b_path = self._left_path, self._right_path
        self.file_a_edit.setText(b_text)
        self.file_b_edit.setText(a_text)
        self._left_label, self._right_label = b_label, a_label
        self._left_path, self._right_path = b_path, a_path
        self._left_text, self._right_text = self._right_text, self._left_text
        if self._left_text or self._right_text:
            self._refresh_from_current_texts(reset_change_index=True)
            self._append_history_snapshot()

    def _active_view(self):
        idx = self.view_mode_combo.currentIndex()
        if idx == 0:
            return self.side_by_side_view
        if idx == 2:
            return self.structured_view
        return self.unified_view

    def _sync_live_texts(self) -> None:
        if self._current_result is None:
            return
        self._left_text, self._right_text = self.side_by_side_view.logical_texts()

    def _reset_history(self) -> None:
        if self._current_result is None:
            self._history = []
            self._history_index = -1
        else:
            self._history = [(self._left_text, self._right_text)]
            self._history_index = 0
        self._update_history_controls()

    def _append_history_snapshot(self) -> None:
        snapshot = (self._left_text, self._right_text)
        if self._history_index >= 0 and self._history[self._history_index] == snapshot:
            self._update_history_controls()
            return

        if self._history_index + 1 < len(self._history):
            self._history = self._history[: self._history_index + 1]
        self._history.append(snapshot)
        self._history_index = len(self._history) - 1
        self._update_history_controls()

    def _update_history_controls(self) -> None:
        is_editable = self.view_mode_combo.currentIndex() in (0, 2)
        self.undo_button.setEnabled(is_editable and self._history_index > 0)
        self.redo_button.setEnabled(is_editable and 0 <= self._history_index < len(self._history) - 1)

    def _mark_saved(self, side: str) -> None:
        """Snapshot the current text as the 'saved' baseline for the given side."""
        if side == "primary":
            self._left_saved_text = self._left_text
        else:
            self._right_saved_text = self._right_text
        self._update_dirty_state()

    def _mark_both_saved(self) -> None:
        self._left_saved_text = self._left_text
        self._right_saved_text = self._right_text
        self._update_dirty_state()

    def _update_dirty_state(self) -> None:
        has_result = self._current_result is not None
        self._left_dirty = has_result and self._left_text != self._left_saved_text
        self._right_dirty = has_result and self._right_text != self._right_saved_text

        left_display = self._left_label
        right_display = self._right_label
        if self._left_dirty:
            left_display = "* " + left_display
        if self._right_dirty:
            right_display = "* " + right_display

        if not self._review_mode:
            primary_prefix = "Primary: "
            secondary_prefix = "Secondary: "
            self.file_a_edit.setToolTip(
                f"{primary_prefix}{left_display}" if self._left_dirty else ""
            )
            self.file_b_edit.setToolTip(
                f"{secondary_prefix}{right_display}" if self._right_dirty else ""
            )

        self.save_primary_button.setEnabled(has_result and self._left_dirty)
        self.save_secondary_button.setEnabled(has_result and self._right_dirty)

        if hasattr(self, "side_by_side_view"):
            sbs = self.side_by_side_view
            if hasattr(sbs, "left_header"):
                sbs.left_header.title_label.setText(
                    _badge_text(left_display, True)
                )
            if hasattr(sbs, "right_header"):
                sbs.right_header.title_label.setText(
                    _badge_text(right_display, False)
                )
        if hasattr(self, "structured_view"):
            sv = self.structured_view
            if hasattr(sv, "_primary_header"):
                sv._primary_header.setText(left_display)
            if hasattr(sv, "_secondary_header"):
                sv._secondary_header.setText(right_display)

    def _apply_history_snapshot(self, index: int) -> None:
        if not (0 <= index < len(self._history)):
            return

        preserve_state = None
        if self._current_result is not None:
            preserve_state = self.side_by_side_view.capture_view_state()

        self._history_index = index
        self._restoring_history = True
        self._left_text, self._right_text = self._history[index]
        self._refresh_from_current_texts(reset_change_index=False, preserve_side_by_side_state=preserve_state)
        self._restoring_history = False
        self._update_history_controls()
        self._update_dirty_state()

    def _undo_comparison(self) -> None:
        if self.view_mode_combo.currentIndex() not in (0, 2) or self._history_index <= 0:
            return
        self._apply_history_snapshot(self._history_index - 1)

    def _redo_comparison(self) -> None:
        if self.view_mode_combo.currentIndex() not in (0, 2) or self._history_index >= len(self._history) - 1:
            return
        self._apply_history_snapshot(self._history_index + 1)

    def _save_text(self, role: str, text: str, current_path: Optional[str], target_edit: QtWidgets.QLineEdit) -> Optional[str]:
        try:
            self._validate_dbc_text(text)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Invalid DBC", f"{role} content is not a valid DBC file:\n{exc}")
            return None

        save_path = current_path
        if not save_path:
            default_path = target_edit.text().strip()
            save_path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self,
                f"Save {role} File",
                default_path if default_path.lower().endswith(".dbc") else "",
                "DBC Files (*.dbc);;All Files (*)",
            )
            if not save_path:
                return None

        if not save_path.lower().endswith(".dbc"):
            save_path += ".dbc"

        try:
            _write_text_file(save_path, text)
            target_edit.setText(save_path)
            self.status_label.setText(f"{role} saved to {save_path}")
            QtWidgets.QMessageBox.information(
                self, "File Saved",
                f"{role} file saved successfully:\n{save_path}",
            )
            return save_path
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Save Error", f"Could not save {role.lower()} file:\n{exc}")
            return None

    def _save_primary(self) -> None:
        if self._current_result is None:
            QtWidgets.QMessageBox.warning(self, "No Comparison", "Load a comparison before saving.")
            return
        self._sync_live_texts()
        saved_path = self._save_text("Primary", self._left_text, self._left_path, self.file_a_edit)
        if saved_path:
            self._left_path = saved_path
            self._left_label = os.path.basename(saved_path)
            self._mark_saved("primary")
            self._refresh_from_current_texts(reset_change_index=False)

    def _save_secondary(self) -> None:
        if self._current_result is None:
            QtWidgets.QMessageBox.warning(self, "No Comparison", "Load a comparison before saving.")
            return
        self._sync_live_texts()
        saved_path = self._save_text("Secondary", self._right_text, self._right_path, self.file_b_edit)
        if saved_path:
            self._right_path = saved_path
            self._right_label = os.path.basename(saved_path)
            self._mark_saved("secondary")
            self._refresh_from_current_texts(reset_change_index=False)

    def _set_review_mode(self, enabled: bool) -> None:
        self._review_mode = enabled
        self.review_header.setVisible(enabled)
        self.review_actions.setVisible(enabled)

        controls_enabled = not enabled
        self.file_a_edit.setEnabled(controls_enabled)
        self.file_b_edit.setEnabled(controls_enabled)
        self.browse_a_button.setEnabled(controls_enabled)
        self.browse_b_button.setEnabled(controls_enabled)
        self.swap_button.setEnabled(controls_enabled)
        self.compare_button.setEnabled(controls_enabled)

    def _compare_selected_files(self) -> None:
        left_path = self.file_a_edit.text().strip()
        right_path = self.file_b_edit.text().strip()
        left_text = self._read_selected_file(left_path, "Primary")
        if left_text is None:
            return
        right_text = self._read_selected_file(right_path, "Secondary")
        if right_text is None:
            return

        self._left_path = left_path
        self._right_path = right_path
        self._left_label = os.path.basename(left_path)
        self._right_label = os.path.basename(right_path)
        self._left_text = left_text
        self._right_text = right_text
        self._set_review_mode(False)
        self.review_header.hide()
        self.review_actions.hide()
        self._refresh_from_current_texts(reset_change_index=True)
        self._reset_history()
        self._mark_both_saved()

    def _refresh_from_disk(self) -> None:
        """Reload both files from disk and re-compare, discarding unsaved edits."""
        left_path = self.file_a_edit.text().strip()
        right_path = self.file_b_edit.text().strip()
        if not left_path and not right_path:
            QtWidgets.QMessageBox.warning(
                self, "No Files", "No files are loaded to refresh."
            )
            return

        if self._left_dirty or self._right_dirty:
            reply = QtWidgets.QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Refreshing will discard them.\nContinue?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return

        reloaded = False
        if left_path and os.path.isfile(left_path):
            try:
                self._left_text = _read_text_file(left_path)
                self._left_path = left_path
                self._left_label = os.path.basename(left_path)
                reloaded = True
            except Exception as exc:
                QtWidgets.QMessageBox.warning(
                    self, "Read Error", f"Could not reload primary file:\n{exc}"
                )

        if right_path and os.path.isfile(right_path):
            try:
                self._right_text = _read_text_file(right_path)
                self._right_path = right_path
                self._right_label = os.path.basename(right_path)
                reloaded = True
            except Exception as exc:
                QtWidgets.QMessageBox.warning(
                    self, "Read Error", f"Could not reload secondary file:\n{exc}"
                )

        if reloaded:
            self._refresh_from_current_texts(reset_change_index=True)
            self._reset_history()
            self._mark_both_saved()
            self.status_label.setText("Files refreshed from disk")

    def _build_current_result(self) -> Optional[DiffResult]:
        if not self._left_text and not self._right_text and not self._left_path and not self._right_path:
            return None

        return compare_texts(
            self._left_text,
            self._right_text,
            left_label=self._left_label,
            right_label=self._right_label,
            left_path=self._left_path,
            right_path=self._right_path,
            primary_side=CompareSide.LEFT,
            ignore_whitespace=self.ignore_whitespace_check.isChecked(),
        )

    def _refresh_from_current_texts(self, _checked: Optional[bool] = None, *, reset_change_index: bool = False, preserve_side_by_side_state: Optional[Dict[str, Any]] = None) -> None:
        if not self._left_text and not self._right_text and not self._left_path and not self._right_path:
            self._current_result = None
            self._render_current_result()
            return
        try:
            self._current_result = self._build_current_result()
            if reset_change_index:
                self._current_change_index = 0
            self._render_current_result(preserve_side_by_side_state=preserve_side_by_side_state)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Comparison Error", str(exc))
            self.status_label.setText("Comparison failed")

    def _render_current_result(self, _checked: Optional[bool] = None, *, preserve_side_by_side_state: Optional[Dict[str, Any]] = None) -> None:
        if not self._current_result:
            self.side_by_side_view.clear()
            self.unified_view.clear()
            self.structured_view.clear()
            self.navigation_label.setText("No changes")
            self._update_history_controls()
            return

        self._update_mode_controls()
        mode_idx = self.view_mode_combo.currentIndex()
        self.view_stack.setCurrentIndex(mode_idx)
        active_view = self._active_view()

        if active_view is self.side_by_side_view:
            self.side_by_side_view.load_result(self._current_result, restore_state=preserve_side_by_side_state)
        elif active_view is self.structured_view:
            self.structured_view.load(
                self._left_text,
                self._right_text,
                primary_label=self._left_label,
                secondary_label=self._right_label,
            )
        else:
            self.unified_view.load_result(self._current_result, only_changes=self.only_changes_check.isChecked())

        change_count = active_view.change_count()
        if change_count == 0:
            self.navigation_label.setText("No changes")
        else:
            self._current_change_index = min(self._current_change_index, change_count - 1)
            self.navigation_label.setText(f"Change {self._current_change_index + 1} of {change_count}")
            if not preserve_side_by_side_state:
                active_view.goto_change(self._current_change_index)

        if self._review_mode:
            self.status_label.setText("Review or edit the comparison, then confirm save or go back to the editor")
        else:
            self.status_label.setText("Comparison ready")
        self._update_history_controls()

    def _on_side_by_side_content_changed(self) -> None:
        if self._current_result is None:
            return
        side_by_side_state = self.side_by_side_view.capture_view_state()
        self._sync_live_texts()
        if not self._restoring_history:
            self._append_history_snapshot()
        self._refresh_from_current_texts(reset_change_index=False, preserve_side_by_side_state=side_by_side_state)
        self._update_dirty_state()

    def _on_ignore_whitespace_toggled(self) -> None:
        self._sync_live_texts()
        self._refresh_from_current_texts(reset_change_index=False)

    def _on_structured_content_changed(self) -> None:
        """Structured view edited data -- rebuild DBC text from dicts."""
        if self._current_result is None:
            return
        try:
            self._left_text = build_dbc_string(self.structured_view.primary_data())
        except Exception:
            logger.warning("Failed to rebuild primary DBC from structured edit", exc_info=True)
        try:
            self._right_text = build_dbc_string(self.structured_view.secondary_data())
        except Exception:
            logger.warning("Failed to rebuild secondary DBC from structured edit", exc_info=True)
        if not self._restoring_history:
            self._append_history_snapshot()
        self._current_result = self._build_current_result()
        self._update_history_controls()
        self._update_dirty_state()

    def _on_view_mode_changed(self) -> None:
        self._update_mode_controls()
        prev_view = self.view_stack.currentWidget()
        if prev_view is self.side_by_side_view and self.side_by_side_view.has_pending_changes():
            self._on_side_by_side_content_changed()
        elif prev_view is self.structured_view and self.structured_view._comparison is not None:
            try:
                self._left_text = build_dbc_string(self.structured_view.primary_data())
            except Exception:
                pass
            try:
                self._right_text = build_dbc_string(self.structured_view.secondary_data())
            except Exception:
                pass
        else:
            self._sync_live_texts()
        self._refresh_from_current_texts(reset_change_index=False)

    def _goto_next_change(self) -> None:
        active_view = self._active_view()
        change_count = active_view.change_count()
        if change_count == 0:
            return
        self._current_change_index = (self._current_change_index + 1) % change_count
        active_view.goto_change(self._current_change_index)
        self.navigation_label.setText(f"Change {self._current_change_index + 1} of {change_count}")

    def _goto_previous_change(self) -> None:
        active_view = self._active_view()
        change_count = active_view.change_count()
        if change_count == 0:
            return
        self._current_change_index = (self._current_change_index - 1) % change_count
        active_view.goto_change(self._current_change_index)
        self.navigation_label.setText(f"Change {self._current_change_index + 1} of {change_count}")

    def load_editor_diff(
        self,
        original_data: Dict[str, Any],
        modified_data: Dict[str, Any],
        file_path: str,
    ) -> None:
        self._review_file_path = file_path
        self._left_text = build_dbc_string(original_data)
        self._right_text = build_dbc_string(modified_data)
        self._left_label = "Original (saved)"
        self._right_label = "Modified (unsaved)"
        self._left_path = file_path
        self._right_path = None
        self.file_a_edit.setText(file_path)
        self.file_b_edit.setText("Unsaved editor changes")
        self.review_header.setText(f"Reviewing pending save for: {file_path}")
        self._set_review_mode(True)
        self._refresh_from_current_texts(reset_change_index=True)
        self._reset_history()
        self._mark_both_saved()

    def _exit_review_mode(self) -> None:
        self._review_file_path = None
        self._set_review_mode(False)
        self._current_result = None
        self._current_change_index = 0
        self._left_text = ""
        self._right_text = ""
        self._left_saved_text = ""
        self._right_saved_text = ""
        self._left_dirty = False
        self._right_dirty = False
        self._left_label = "Primary"
        self._right_label = "Secondary"
        self._left_path = None
        self._right_path = None
        self.file_a_edit.clear()
        self.file_b_edit.clear()
        self.side_by_side_view.clear()
        self.unified_view.clear()
        self.structured_view.clear()
        self._history = []
        self._history_index = -1
        self.navigation_label.setText("No changes")
        self.status_label.setText("Ready")
        self._update_history_controls()
        self._update_dirty_state()

    def _on_confirm_save(self) -> None:
        self._sync_live_texts()
        if self._review_file_path:
            try:
                self._validate_dbc_text(self._right_text)
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "Invalid DBC", f"The edited comparison text is not valid DBC:\n{exc}")
                return
            self.saveConfirmed.emit(self._review_file_path, self._right_text)
        self._exit_review_mode()

    def _on_cancel_review(self) -> None:
        self.reviewCancelled.emit()
        self._exit_review_mode()
