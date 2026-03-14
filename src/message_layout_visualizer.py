#!/usr/bin/env python3

"""
Dedicated CAN/CAN FD message layout visualizer widgets.

Grid layout:
    - Columns represent bit positions 7..0 within each byte.
    - Rows represent bytes 0..N from top to bottom.
    - Signals are drawn as flat colored blocks spanning their bit cells.
    - Each signal shows its name and bit info directly on the grid.
"""

import copy
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from multiplex_support import (
    filter_signals_by_mux_id,
    format_mux_id_with_name,
    get_mux_ids,
    is_message_multiplexed,
)


class MessageLayoutVisualizerError(Exception):
    """Raised when message data cannot be visualized safely."""


# ---------------------------------------------------------------------------
#  Validated data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SignalLayoutData:
    name: str
    start_bit: int
    length: int
    byte_order: str
    bit_positions: Tuple[int, ...]


@dataclass(frozen=True)
class MessageLayoutData:
    name: str
    frame_id: int
    length: int
    is_extended_frame: bool
    is_fd: bool
    signals: List[SignalLayoutData]


# ---------------------------------------------------------------------------
#  Flat signal color palette (Material Design 200-level, muted and readable)
# ---------------------------------------------------------------------------

_SIGNAL_PALETTE: List[QtGui.QColor] = [
    QtGui.QColor("#A5D6A7"),  # green
    QtGui.QColor("#90CAF9"),  # blue
    QtGui.QColor("#FFCC80"),  # orange
    QtGui.QColor("#CE93D8"),  # purple
    QtGui.QColor("#80DEEA"),  # cyan
    QtGui.QColor("#EF9A9A"),  # red
    QtGui.QColor("#FFF59D"),  # yellow
    QtGui.QColor("#B0BEC5"),  # blue-gray
    QtGui.QColor("#BCAAA4"),  # brown
    QtGui.QColor("#F48FB1"),  # pink
    QtGui.QColor("#C5E1A5"),  # light green
    QtGui.QColor("#81D4FA"),  # light blue
    QtGui.QColor("#FFE082"),  # amber
    QtGui.QColor("#B39DDB"),  # deep purple
    QtGui.QColor("#80CBC4"),  # teal
    QtGui.QColor("#FFAB91"),  # deep orange
]


# ---------------------------------------------------------------------------
#  Visualizer widget
# ---------------------------------------------------------------------------

class MessageSignalLayoutVisualizer(QtWidgets.QWidget):
    """Flat, clean CAN message bit-layout grid."""

    renderFailed = QtCore.pyqtSignal(str)

    _BG = QtGui.QColor("#FFFFFF")
    _BORDER = QtGui.QColor("#cccccc")
    _HEADER_BG = QtGui.QColor("#f5f5f5")
    _CELL_BG = QtGui.QColor("#FFFFFF")
    _GRID_LINE = QtGui.QColor("#e0e0e0")
    _TEXT_PRIMARY = QtGui.QColor("#333333")
    _TEXT_SECONDARY = QtGui.QColor("#666666")
    _TEXT_MUTED = QtGui.QColor("#999999")

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._message_data: Optional[MessageLayoutData] = None
        self._last_render_error: Optional[str] = None
        self.setMinimumSize(760, 420)

    # -- public API ----------------------------------------------------------

    def clear_message_data(self) -> None:
        self._message_data = None
        self._last_render_error = None
        self.update()

    def set_message_data(self, message_data: Optional[Dict[str, Any]]) -> None:
        if message_data is None:
            self.clear_message_data()
            return
        self._message_data = self._build_message_layout(message_data)
        self._last_render_error = None
        self.update()

    # -- validation ----------------------------------------------------------

    def _build_message_layout(self, raw: Dict[str, Any]) -> MessageLayoutData:
        if not isinstance(raw, dict):
            raise MessageLayoutVisualizerError("Visualizer received invalid message data.")

        name = self._require_str(raw, "name", "Message name is required.")
        frame_id = self._require_int(raw, "frame_id", "Frame ID is invalid.")
        length = self._require_int(raw, "length", "Message length is invalid.")
        is_ext = self._require_bool(raw, "is_extended_frame", "Frame type is invalid.")
        is_fd = self._require_bool(raw, "is_fd", "Bus type is invalid.")

        if not 1 <= length <= 64:
            raise MessageLayoutVisualizerError("Message length must be 1-64 bytes.")

        raw_signals = raw.get("signals")
        if not isinstance(raw_signals, list):
            raise MessageLayoutVisualizerError("Signals list is missing or malformed.")

        total_bits = length * 8
        signals = [
            self._build_signal(s, i, total_bits) for i, s in enumerate(raw_signals)
        ]
        return MessageLayoutData(name, frame_id, length, is_ext, is_fd, signals)

    def _build_signal(
        self, raw: Dict[str, Any], index: int, total_bits: int
    ) -> SignalLayoutData:
        if not isinstance(raw, dict):
            raise MessageLayoutVisualizerError(f"Signal {index + 1} is malformed.")

        name = self._require_str(raw, "name", f"Signal {index + 1} is missing a name.")
        start = self._require_int(raw, "start_bit", f"Signal '{name}': invalid start bit.")
        length = self._require_int(raw, "length", f"Signal '{name}': invalid bit length.")
        order = self._require_str(raw, "byte_order", f"Signal '{name}': missing byte order.")

        if order not in ("little_endian", "big_endian"):
            raise MessageLayoutVisualizerError(f"Signal '{name}': unsupported byte order '{order}'.")
        if not 0 <= start < total_bits:
            raise MessageLayoutVisualizerError(f"Signal '{name}': start bit {start} out of range.")
        if length <= 0:
            raise MessageLayoutVisualizerError(f"Signal '{name}': length must be > 0.")

        positions = self._compute_bit_positions(name, start, length, order, total_bits)
        return SignalLayoutData(name, start, length, order, tuple(positions))

    @staticmethod
    def _require_str(d: Dict[str, Any], key: str, msg: str) -> str:
        v = d.get(key)
        if not isinstance(v, str) or not v.strip():
            raise MessageLayoutVisualizerError(msg)
        return v.strip()

    @staticmethod
    def _require_int(d: Dict[str, Any], key: str, msg: str) -> int:
        v = d.get(key)
        if isinstance(v, bool) or not isinstance(v, int):
            raise MessageLayoutVisualizerError(msg)
        return v

    @staticmethod
    def _require_bool(d: Dict[str, Any], key: str, msg: str) -> bool:
        v = d.get(key)
        if not isinstance(v, bool):
            raise MessageLayoutVisualizerError(msg)
        return v

    # -- bit position math ---------------------------------------------------

    @staticmethod
    def _next_motorola_bit(bit: int) -> int:
        return bit + 15 if bit % 8 == 0 else bit - 1

    def _compute_bit_positions(
        self, name: str, start: int, length: int, order: str, total: int
    ) -> List[int]:
        positions: List[int] = []
        current = start
        for _ in range(length):
            if not 0 <= current < total:
                raise MessageLayoutVisualizerError(
                    f"Signal '{name}' exceeds message boundaries."
                )
            positions.append(current)
            current = (
                self._next_motorola_bit(current)
                if order == "big_endian"
                else current + 1
            )
        return positions

    @staticmethod
    def _bit_to_column(bit: int) -> int:
        return 7 - (bit % 8)

    @staticmethod
    def _signal_color(index: int) -> QtGui.QColor:
        return _SIGNAL_PALETTE[index % len(_SIGNAL_PALETTE)]

    # -- segment grouping (contiguous column ranges per byte row) ------------

    @staticmethod
    def _group_segments(
        signal: SignalLayoutData,
    ) -> Dict[int, List[Tuple[int, int]]]:
        by_byte: Dict[int, List[int]] = {}
        for bit in signal.bit_positions:
            by_byte.setdefault(bit // 8, []).append(7 - (bit % 8))

        result: Dict[int, List[Tuple[int, int]]] = {}
        for byte_idx, cols in by_byte.items():
            cols_sorted = sorted(cols)
            segs: List[Tuple[int, int]] = []
            s = e = cols_sorted[0]
            for c in cols_sorted[1:]:
                if c == e + 1:
                    e = c
                else:
                    segs.append((s, e))
                    s = e = c
            segs.append((s, e))
            result[byte_idx] = segs
        return result

    # -- painting ------------------------------------------------------------

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing)
        painter.fillRect(self.rect(), self._BG)

        if self._message_data is None:
            return

        try:
            self._paint(painter, self._message_data)
            self._last_render_error = None
        except Exception as exc:
            msg = f"Render error: {exc}"
            if msg != self._last_render_error:
                self._last_render_error = msg
                self.renderFailed.emit(msg)

    def _paint(self, p: QtGui.QPainter, msg: MessageLayoutData) -> None:
        margin = 20
        area = QtCore.QRectF(margin, margin, self.width() - 2 * margin, self.height() - 2 * margin)

        header_h = self._draw_header(p, area, msg)

        grid_top = area.top() + header_h + 12
        grid_rect = QtCore.QRectF(area.left(), grid_top, area.width(), area.bottom() - grid_top)
        self._draw_grid(p, grid_rect, msg)

    # -- header --------------------------------------------------------------

    def _draw_header(
        self, p: QtGui.QPainter, area: QtCore.QRectF, msg: MessageLayoutData
    ) -> float:
        name_font = QtGui.QFont(self.font())
        name_font.setPointSize(max(11, name_font.pointSize() + 3))
        name_font.setBold(True)
        p.setFont(name_font)
        p.setPen(self._TEXT_PRIMARY)
        p.drawText(
            QtCore.QRectF(area.left(), area.top(), area.width() * 0.6, 26),
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
            msg.name,
        )

        meta_font = QtGui.QFont(self.font())
        meta_font.setPointSize(max(8, meta_font.pointSize() - 1))
        p.setFont(meta_font)
        p.setPen(self._TEXT_SECONDARY)
        bus = "CAN FD" if msg.is_fd else "CAN"
        frame = "Extended" if msg.is_extended_frame else "Standard"
        meta = f"{bus}  |  {frame}  |  {msg.length} bytes  |  ID 0x{msg.frame_id:X}  |  {len(msg.signals)} signals"
        p.drawText(
            QtCore.QRectF(area.left(), area.top() + 28, area.width(), 18),
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
            meta,
        )

        line_y = area.top() + 52
        p.setPen(QtGui.QPen(self._BORDER, 1.0))
        p.drawLine(QtCore.QPointF(area.left(), line_y), QtCore.QPointF(area.right(), line_y))
        return 56.0

    # -- grid ----------------------------------------------------------------

    def _draw_grid(
        self, p: QtGui.QPainter, rect: QtCore.QRectF, msg: MessageLayoutData
    ) -> None:
        byte_count = msg.length
        col_count = 8
        byte_label_w = 36.0
        col_header_h = 26.0
        cell_w = (rect.width() - byte_label_w) / col_count
        cell_h = (rect.height() - col_header_h) / max(1, byte_count)
        grid_left = rect.left() + byte_label_w
        grid_top = rect.top() + col_header_h

        header_font = QtGui.QFont(self.font())
        header_font.setPointSize(max(8, header_font.pointSize() - 1))
        header_font.setBold(True)

        p.setPen(QtGui.QPen(self._BORDER, 1.0))
        p.setBrush(self._HEADER_BG)
        p.drawRect(QtCore.QRectF(grid_left, rect.top(), cell_w * col_count, col_header_h))

        p.setFont(header_font)
        p.setPen(self._TEXT_SECONDARY)
        for c in range(col_count):
            cr = QtCore.QRectF(grid_left + c * cell_w, rect.top(), cell_w, col_header_h)
            p.drawText(cr, QtCore.Qt.AlignCenter, str(7 - c))

        # Y-axis: same as X-axis header — grey strip, no borders, numbers on top
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(self._HEADER_BG)
        p.drawRect(QtCore.QRectF(rect.left(), grid_top, byte_label_w, cell_h * byte_count))

        byte_font = QtGui.QFont(self.font())
        byte_font.setPointSize(max(8, byte_font.pointSize() - 1))
        p.setFont(byte_font)
        p.setPen(self._TEXT_SECONDARY)
        for r in range(byte_count):
            row_top = grid_top + r * cell_h
            label_rect = QtCore.QRectF(rect.left(), row_top, byte_label_w - 4, cell_h)
            p.drawText(label_rect, QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter, str(r))

        for r in range(byte_count):
            row_top = grid_top + r * cell_h

            for c in range(col_count):
                cr = QtCore.QRectF(grid_left + c * cell_w, row_top, cell_w, cell_h)
                p.setPen(QtGui.QPen(self._GRID_LINE, 1.0))
                p.setBrush(self._CELL_BG)
                p.drawRect(cr)

        p.setPen(QtGui.QPen(self._BORDER, 1.0))
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawRect(QtCore.QRectF(grid_left, grid_top, cell_w * col_count, cell_h * byte_count))

        # Precompute per-signal segments for later bit-number color lookup
        signal_segments: List[Tuple[int, QtGui.QColor, Dict[int, List[Tuple[int, int]]]]] = []
        for sig_idx, sig in enumerate(msg.signals):
            color = self._signal_color(sig_idx)
            segments = self._group_segments(sig)
            signal_segments.append((sig_idx, color, segments))

        for sig_idx, sig in enumerate(msg.signals):
            color = self._signal_color(sig_idx)
            segments = self._group_segments(sig)
            name_drawn = False

            sorted_bytes = sorted(segments.keys())
            for byte_idx in sorted_bytes:
                if byte_idx >= byte_count:
                    continue
                row_top = grid_top + byte_idx * cell_h

                for seg_start, seg_end in segments[byte_idx]:
                    span = seg_end - seg_start + 1
                    seg_rect = QtCore.QRectF(
                        grid_left + seg_start * cell_w + 1,
                        row_top + 1,
                        span * cell_w - 2,
                        cell_h - 2,
                    )
                    p.setPen(QtGui.QPen(color.darker(120), 1.0))
                    p.setBrush(color)
                    p.drawRect(seg_rect)

                    self._draw_signal_label(
                        p, seg_rect, sig, not name_drawn, cell_h
                    )
                    if not name_drawn:
                        name_drawn = True

        # Draw bit number in every cell so it is always visible (on empty or filled)
        self._draw_bit_numbers_in_cells(
            p, grid_left, grid_top, cell_w, cell_h, byte_count, col_count,
            signal_segments,
        )

        # Redraw grid lines on top so borders stay visible over filled signal blocks
        p.setPen(QtGui.QPen(self._GRID_LINE, 1.0))
        p.setBrush(QtCore.Qt.NoBrush)
        for c in range(col_count + 1):
            x = grid_left + c * cell_w
            p.drawLine(
                QtCore.QPointF(x, grid_top),
                QtCore.QPointF(x, grid_top + byte_count * cell_h),
            )
        for r in range(byte_count + 1):
            y = grid_top + r * cell_h
            p.drawLine(
                QtCore.QPointF(grid_left, y),
                QtCore.QPointF(grid_left + col_count * cell_w, y),
            )

    def _draw_bit_numbers_in_cells(
        self,
        p: QtGui.QPainter,
        grid_left: float,
        grid_top: float,
        cell_w: float,
        cell_h: float,
        byte_count: int,
        col_count: int,
        signal_segments: List[Tuple[int, QtGui.QColor, Dict[int, List[Tuple[int, int]]]]],
    ) -> None:
        bit_font = QtGui.QFont(self.font())
        bit_font.setPointSize(max(6, bit_font.pointSize() - 3))
        bit_font.setBold(True)
        p.setFont(bit_font)

        for r in range(byte_count):
            row_top = grid_top + r * cell_h
            for c in range(col_count):
                bit_num = r * 8 + (7 - c)
                cell_rect = QtCore.QRectF(
                    grid_left + c * cell_w + 1,
                    row_top + 1,
                    cell_w - 2,
                    cell_h - 2,
                )
                fill_color = self._CELL_BG
                for _sig_idx, sig_color, segments in signal_segments:
                    if r not in segments:
                        continue
                    for seg_start, seg_end in segments[r]:
                        if seg_start <= c <= seg_end:
                            fill_color = sig_color
                            break
                text_color = self._text_on_fill(fill_color)
                p.setPen(text_color)
                p.drawText(cell_rect, QtCore.Qt.AlignLeft | QtCore.Qt.AlignBottom, str(bit_num))

    def _draw_signal_label(
        self,
        p: QtGui.QPainter,
        rect: QtCore.QRectF,
        sig: SignalLayoutData,
        is_primary: bool,
        cell_h: float,
    ) -> None:
        pad = 4
        available_w = rect.width() - 2 * pad
        available_h = rect.height() - 2 * pad
        if available_w < 12 or available_h < 8:
            return

        name_font = QtGui.QFont(self.font())
        name_font.setPointSize(max(9, name_font.pointSize()))
        name_font.setBold(True)
        p.setFont(name_font)
        metrics = QtGui.QFontMetricsF(name_font)

        text_color = self._text_on_fill(p.brush().color())
        p.setPen(text_color)

        wrap_flags = QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop | QtCore.Qt.TextWordWrap
        content_rect = QtCore.QRectF(
            rect.left() + pad, rect.top() + pad, available_w, available_h
        )

        if is_primary and available_h >= 28 and available_w >= 40:
            name_rect = QtCore.QRectF(
                content_rect.left(), content_rect.top(),
                content_rect.width(), content_rect.height() * 0.55
            )
            name_br = metrics.boundingRect(name_rect, wrap_flags, sig.name)
            p.drawText(name_rect, wrap_flags, sig.name)

            info_font = QtGui.QFont(self.font())
            info_font.setPointSize(max(8, info_font.pointSize() - 1))
            p.setFont(info_font)
            muted = QtGui.QColor(text_color)
            muted.setAlpha(180)
            p.setPen(muted)
            order_label = "Intel" if sig.byte_order == "little_endian" else "Motorola"
            info_text = f"bit {sig.start_bit}  |  {sig.length}b  |  {order_label}"
            info_rect = QtCore.QRectF(
                content_rect.left(),
                name_rect.top() + name_br.height() + 2,
                content_rect.width(),
                content_rect.height() - name_br.height() - 2,
            )
            p.drawText(info_rect, wrap_flags, info_text)
            return

        p.drawText(content_rect, wrap_flags, sig.name)

    @staticmethod
    def _text_on_fill(color: QtGui.QColor) -> QtGui.QColor:
        lum = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
        return QtGui.QColor("#333333") if lum > 140 else QtGui.QColor("#FFFFFF")


# ---------------------------------------------------------------------------
#  Wrapper dialog (non-modal)
# ---------------------------------------------------------------------------

class MessageSignalLayoutWindow(QtWidgets.QDialog):
    """Non-modal container with explicit error reporting and mux filtering."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Message Signal Layout")
        self.setModal(False)
        self.resize(900, 600)
        self._raw_message_data: Optional[Dict[str, Any]] = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.error_label = QtWidgets.QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        self.error_label.setStyleSheet(
            "QLabel {"
            "  background-color: #FFEBEE;"
            "  color: #C62828;"
            "  border-bottom: 1px solid #EF9A9A;"
            "  padding: 8px 12px;"
            "  font-size: 12px;"
            "}"
        )
        layout.addWidget(self.error_label)

        self.mux_filter_row = QtWidgets.QWidget(self)
        mux_row_layout = QtWidgets.QHBoxLayout(self.mux_filter_row)
        mux_row_layout.setContentsMargins(12, 4, 12, 4)
        mux_row_layout.setSpacing(6)
        self.mux_filter_label = QtWidgets.QLabel("Multiplexer Signal:")
        self.mux_filter_label.setStyleSheet(
            "QLabel { color: #333; font-weight: bold; font-size: 11px; border: none; background: transparent; }"
        )
        self.mux_filter_combo = QtWidgets.QComboBox()
        self.mux_filter_combo.setToolTip("Filter signals by multiplexer ID")
        self.mux_filter_combo.setFixedHeight(24)
        self.mux_filter_combo.setMinimumWidth(160)
        self.mux_filter_combo.setStyleSheet(
            "QComboBox {"
            "  padding: 2px 8px;"
            "  border: 1px solid #ccc;"
            "  border-radius: 3px;"
            "  background: #fff;"
            "  font-size: 11px;"
            "}"
            "QComboBox::drop-down { border: none; padding-right: 4px; }"
            "QComboBox QAbstractItemView {"
            "  border: 1px solid #ccc;"
            "  selection-background-color: #e3f2fd;"
            "  selection-color: #333;"
            "}"
        )
        self.mux_filter_combo.currentIndexChanged.connect(self._on_mux_filter_changed)
        mux_row_layout.addWidget(self.mux_filter_label)
        mux_row_layout.addWidget(self.mux_filter_combo)
        mux_row_layout.addStretch()
        self.mux_filter_row.setFixedHeight(32)
        self.mux_filter_row.setStyleSheet(
            "QWidget#muxFilterRow { background: #fafafa; border-bottom: 1px solid #e0e0e0; }"
        )
        self.mux_filter_row.setObjectName("muxFilterRow")
        self.mux_filter_row.hide()
        layout.addWidget(self.mux_filter_row)

        self.visualizer = MessageSignalLayoutVisualizer(self)
        self.visualizer.renderFailed.connect(self._show_error)
        layout.addWidget(self.visualizer)

    def set_message_data(self, message_data: Optional[Dict[str, Any]]) -> None:
        self._raw_message_data = message_data
        if message_data is None:
            self._clear_error()
            self._hide_mux_filter()
            self.setWindowTitle("Message Signal Layout")
            self.visualizer.clear_message_data()
            return

        self._update_mux_filter(message_data)
        self._apply_mux_filter()

    def _update_mux_filter(self, message_data: Dict[str, Any]) -> None:
        self.mux_filter_combo.blockSignals(True)
        self.mux_filter_combo.clear()
        if is_message_multiplexed(message_data):
            self.mux_filter_combo.addItem("All Signals", None)
            for mux_id in get_mux_ids(message_data):
                label = format_mux_id_with_name(message_data, mux_id)
                self.mux_filter_combo.addItem(f"Mux ID: {label}", mux_id)
            self.mux_filter_combo.setCurrentIndex(0)
            self.mux_filter_row.show()
        else:
            self._hide_mux_filter()
        self.mux_filter_combo.blockSignals(False)

    def _hide_mux_filter(self) -> None:
        self.mux_filter_combo.clear()
        self.mux_filter_row.hide()

    def _on_mux_filter_changed(self) -> None:
        self._apply_mux_filter()

    def _apply_mux_filter(self) -> None:
        data = self._raw_message_data
        if data is None:
            return

        selected_mux_id = (
            self.mux_filter_combo.currentData()
            if self.mux_filter_combo.isVisible()
            else None
        )

        if selected_mux_id is not None:
            filtered = copy.copy(data)
            filtered["signals"] = filter_signals_by_mux_id(
                data.get("signals", []), selected_mux_id
            )
        else:
            filtered = data

        try:
            self.visualizer.set_message_data(filtered)
        except MessageLayoutVisualizerError as exc:
            self.visualizer.clear_message_data()
            self.setWindowTitle("Message Signal Layout")
            self._show_error(str(exc))
            return

        self._clear_error()
        self.setWindowTitle(f"Message Signal Layout \u2014 {data['name']}")

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def _clear_error(self) -> None:
        self.error_label.clear()
        self.error_label.hide()
