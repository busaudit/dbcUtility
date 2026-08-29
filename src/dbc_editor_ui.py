#!/usr/bin/env python3

"""
DBC Editor UI Component
Provides the user interface for editing DBC files.
"""

import os
from collections import OrderedDict
from PyQt5 import QtWidgets, QtCore, QtGui
from typing import Dict, List, Optional, Any

import qtawesome as qta

from dbc_editor import DBCEditor, DBCEditorError
from message_layout_visualizer import MessageSignalLayoutWindow
from multiplex_support import (
    classify_signal,
    filter_signals_by_mux_id,
    format_mux_indicator,
    format_mux_id_with_name,
    get_mux_ids,
    is_message_multiplexed,
)
from search_module import UnifiedSearchWidget
from src.dbc_comparator import validate_dbc_data


def _format_optional_value(value: Any) -> str:
    """Format optional values for line edits."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _parse_optional_number(text: str, field_name: str) -> Optional[float]:
    """Parse optional int/float values, including hex integers."""
    value = text.strip()
    if not value:
        return None

    try:
        if value.lower().startswith(("0x", "-0x", "+0x")):
            return int(value, 0)
        if any(ch in value.lower() for ch in (".", "e")):
            return float(value)
        return int(value, 0)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid number") from exc


def _parse_optional_int(text: str, field_name: str) -> Optional[int]:
    """Parse optional integer values, including hex integers."""
    value = text.strip()
    if not value:
        return None

    try:
        return int(value, 0)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid integer") from exc


def _parse_optional_int_list(text: str, field_name: str) -> Optional[List[int]]:
    """Parse comma-separated optional integer values."""
    value = text.strip()
    if not value:
        return None

    parts = [part.strip() for part in value.split(',') if part.strip()]
    try:
        return [int(part, 0) for part in parts] or None
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a comma-separated integer list") from exc


def _normalize_choices(choices: Any) -> OrderedDict[int, str]:
    """Normalize cantools choices into an ordered integer->label mapping."""
    normalized: OrderedDict[int, str] = OrderedDict()
    if not choices:
        return normalized

    for raw_key, raw_value in choices.items():
        normalized[int(raw_key)] = str(raw_value)
    return normalized


def _unique_strings(values: List[str]) -> List[str]:
    """Return non-empty strings in insertion order without duplicates."""
    unique_values: List[str] = []
    seen = set()
    for value in values:
        if value is None:
            continue
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_values.append(normalized)
    return unique_values


class SectionedCheckableDropdown(QtWidgets.QComboBox):
    """QComboBox-styled dropdown with section headers and checkable items."""

    selectionChanged = QtCore.pyqtSignal(object)

    ITEM_TYPE_ROLE = QtCore.Qt.UserRole + 1
    ITEM_VALUE_ROLE = QtCore.Qt.UserRole + 2

    def __init__(
        self,
        placeholder: str,
        existing_items: Optional[List[str]] = None,
        *,
        allow_new: bool = False,
        new_item_label: str = "Item",
        read_only: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._placeholder = placeholder
        self._allow_new = allow_new
        self._new_item_label = new_item_label
        self._read_only = read_only
        self._existing_items: List[str] = _unique_strings(existing_items or [])
        self._new_items: List[str] = []
        self._selected_items: List[str] = []
        self._stay_open = False

        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText(self._placeholder)
        self.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.setModel(QtGui.QStandardItemModel(self))
        self.setView(QtWidgets.QListView(self))
        self.view().setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.view().viewport().installEventFilter(self)

        self._rebuild_model()
        self._update_display_text()

    def set_existing_items(self, items: List[str]) -> None:
        self._existing_items = _unique_strings(items)
        self._selected_items = [item for item in self._selected_items if item in self._existing_items or item in self._new_items]
        self._rebuild_model()
        self._update_display_text()

    def set_selected_items(self, items: List[str]) -> None:
        normalized_items = _unique_strings(items)
        for item in normalized_items:
            if item not in self._existing_items and item not in self._new_items:
                if self._allow_new:
                    self._new_items.append(item)
                else:
                    self._existing_items.append(item)
        self._selected_items = normalized_items
        self._rebuild_model()
        self._update_display_text()

    def selected_items(self) -> List[str]:
        return list(self._selected_items)

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = read_only
        self._rebuild_model()

    def hidePopup(self) -> None:
        if self._stay_open:
            self._stay_open = False
            return
        super().hidePopup()

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self.view().viewport():
            if event.type() == QtCore.QEvent.MouseButtonRelease:
                index = self.view().indexAt(event.pos())
                if index.isValid():
                    item_type = index.data(self.ITEM_TYPE_ROLE)
                    if item_type == "choice":
                        self._stay_open = True
                        if not self._read_only:
                            self._toggle_choice(index)
                        return True
                    if item_type == "create":
                        if not self._read_only:
                            self.hidePopup()
                            self._create_new_item()
                        return True
                    if item_type in {"header", "empty"}:
                        self._stay_open = True
                        return True
            elif event.type() == QtCore.QEvent.MouseButtonDblClick:
                return True
        return super().eventFilter(watched, event)

    def _update_display_text(self) -> None:
        if self._selected_items:
            text = ", ".join(self._selected_items)
        else:
            text = self._placeholder
        self.lineEdit().setText(text)
        self.setToolTip(text)

    def _append_header(self, text: str) -> None:
        item = QtGui.QStandardItem(text)
        item.setFlags(QtCore.Qt.NoItemFlags)
        item.setData("header", self.ITEM_TYPE_ROLE)
        self.model().appendRow(item)

    def _append_empty(self, text: str) -> None:
        item = QtGui.QStandardItem(text)
        item.setFlags(QtCore.Qt.NoItemFlags)
        item.setData("empty", self.ITEM_TYPE_ROLE)
        self.model().appendRow(item)

    def _append_checkable_item(self, value: str) -> None:
        item = QtGui.QStandardItem(value)
        flags = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsUserCheckable
        if not self._read_only:
            flags |= QtCore.Qt.ItemIsSelectable
        item.setFlags(flags)
        item.setData("choice", self.ITEM_TYPE_ROLE)
        item.setData(value, self.ITEM_VALUE_ROLE)
        item.setData(
            QtCore.Qt.Checked if value in self._selected_items else QtCore.Qt.Unchecked,
            QtCore.Qt.CheckStateRole,
        )
        self.model().appendRow(item)

    def _append_create_item(self) -> None:
        item = QtGui.QStandardItem(f"Create {self._new_item_label}")
        flags = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
        if self._read_only:
            flags = QtCore.Qt.NoItemFlags
        item.setFlags(flags)
        item.setData("create", self.ITEM_TYPE_ROLE)
        self.model().appendRow(item)

    def _rebuild_model(self) -> None:
        model = self.model()
        model.clear()

        self._append_header("Existing")
        if self._existing_items:
            for item in self._existing_items:
                self._append_checkable_item(item)
        else:
            self._append_empty("No existing items")

        if self._allow_new:
            self._append_header("New")
            for item in self._new_items:
                self._append_checkable_item(item)
            self._append_create_item()

    def _toggle_choice(self, index: QtCore.QModelIndex) -> None:
        item = self.model().itemFromIndex(index)
        checked = item.checkState() == QtCore.Qt.Checked
        item.setCheckState(QtCore.Qt.Unchecked if checked else QtCore.Qt.Checked)
        self._sync_selected_items_from_model()
        self._update_display_text()
        self.selectionChanged.emit(self.selected_items())

    def _sync_selected_items_from_model(self) -> None:
        selected_items: List[str] = []
        for row in range(self.model().rowCount()):
            item = self.model().item(row)
            if item.data(self.ITEM_TYPE_ROLE) != "choice":
                continue
            if item.checkState() == QtCore.Qt.Checked:
                selected_items.append(item.data(self.ITEM_VALUE_ROLE))
        self._selected_items = selected_items

    def _create_new_item(self) -> None:
        value, accepted = QtWidgets.QInputDialog.getText(
            self,
            f"Create {self._new_item_label}",
            f"{self._new_item_label}:",
        )
        if not accepted:
            return

        new_value = value.strip()
        if not new_value:
            return

        if new_value not in self._existing_items and new_value not in self._new_items:
            self._new_items.append(new_value)
        if new_value not in self._selected_items:
            self._selected_items.append(new_value)

        self._rebuild_model()
        self._update_display_text()
        self.selectionChanged.emit(self.selected_items())

class MessageEditDialog(QtWidgets.QDialog):
    """Enhanced dialog for editing message properties."""
    
    def __init__(
        self,
        parent=None,
        message_data=None,
        existing_senders=None,
        existing_receivers=None,
        existing_send_types=None,
        existing_bus_names=None,
        existing_protocols=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Edit Message")
        self.setModal(True)
        self.resize(500, 600)
        
        self.message_data = message_data or {}
        self.existing_senders = _unique_strings(existing_senders or [])
        self.existing_receivers = _unique_strings(existing_receivers or [])
        self.existing_send_types = _unique_strings(existing_send_types or [])
        self.existing_bus_names = _unique_strings(existing_bus_names or [])
        self.existing_protocols = _unique_strings(existing_protocols or [])
        self.setup_ui()
        self.load_data()
        
    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        
        # Create scroll area for better layout
        scroll_area = QtWidgets.QScrollArea()
        scroll_widget = QtWidgets.QWidget()
        scroll_layout = QtWidgets.QVBoxLayout(scroll_widget)
        
        # Basic Properties Group
        basic_group = QtWidgets.QGroupBox("Basic Properties")
        basic_layout = QtWidgets.QGridLayout()
        basic_layout.setHorizontalSpacing(8)
        basic_layout.setVerticalSpacing(8)
        
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("Enter message name")
        self.name_edit.setToolTip("Name of the CAN message")
        
        self.frame_id_edit = QtWidgets.QLineEdit()
        self.frame_id_edit.setPlaceholderText("0x123 or 291")
        self.frame_id_edit.setToolTip("CAN frame ID as decimal or hex (0x000 to 0x1FFFFFFF)")
        
        self.length_edit = QtWidgets.QSpinBox()
        self.length_edit.setRange(0, 64)
        self.length_edit.setToolTip("Message length in bytes (0-64)")

        self.bus_type_combo = QtWidgets.QComboBox()
        self.bus_type_combo.addItems(["CAN", "CAN FD"])
        self.bus_type_combo.setToolTip("Message bus type based on cantools is_fd")
        
        basic_layout.addWidget(QtWidgets.QLabel("Name:"), 0, 0)
        basic_layout.addWidget(self.name_edit, 0, 1, 1, 5)
        basic_layout.addWidget(QtWidgets.QLabel("Frame ID:"), 1, 0)
        basic_layout.addWidget(self.frame_id_edit, 1, 1)
        basic_layout.addWidget(QtWidgets.QLabel("Length (bytes):"), 1, 2)
        basic_layout.addWidget(self.length_edit, 1, 3)
        basic_layout.addWidget(QtWidgets.QLabel("Bus Type:"), 1, 4)
        basic_layout.addWidget(self.bus_type_combo, 1, 5)
        self.msg_multiplexing_label = QtWidgets.QLabel("—")
        self.msg_multiplexing_label.setToolTip("Whether this message contains multiplexed signals")
        basic_layout.addWidget(QtWidgets.QLabel("Multiplexing:"), 2, 0)
        basic_layout.addWidget(self.msg_multiplexing_label, 2, 1, 1, 3)
        basic_layout.setColumnStretch(1, 1)
        basic_layout.setColumnStretch(3, 1)
        basic_layout.setColumnStretch(5, 1)
        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)
        
        # Network Properties Group
        network_group = QtWidgets.QGroupBox("Network Properties")
        network_layout = QtWidgets.QGridLayout()
        network_layout.setHorizontalSpacing(8)
        network_layout.setVerticalSpacing(8)
        
        self.senders_dropdown = SectionedCheckableDropdown(
            "Select senders",
            self.existing_senders,
            allow_new=True,
            new_item_label="Sender",
            parent=self,
        )

        self.receivers_dropdown = SectionedCheckableDropdown(
            "Receivers",
            self.existing_receivers,
            read_only=True,
            parent=self,
        )
        
        # Frame type selection
        self.frame_type_combo = QtWidgets.QComboBox()
        self.frame_type_combo.addItems(['Standard Frame (11-bit)', 'Extended Frame (29-bit)'])
        self.frame_type_combo.setToolTip("CAN frame type")

        network_layout.addWidget(QtWidgets.QLabel("Senders:"), 0, 0)
        network_layout.addWidget(self.senders_dropdown, 0, 1)
        network_layout.addWidget(QtWidgets.QLabel("Receivers:"), 0, 2)
        network_layout.addWidget(self.receivers_dropdown, 0, 3)
        network_layout.addWidget(QtWidgets.QLabel("Frame Type:"), 1, 0)
        network_layout.addWidget(self.frame_type_combo, 1, 1)
        network_layout.setColumnStretch(1, 1)
        network_layout.setColumnStretch(3, 1)
        network_group.setLayout(network_layout)
        scroll_layout.addWidget(network_group)
        
        # Advanced Properties Group
        advanced_group = QtWidgets.QGroupBox("Advanced Properties")
        advanced_layout = QtWidgets.QGridLayout()
        advanced_layout.setHorizontalSpacing(8)
        advanced_layout.setVerticalSpacing(8)
        
        # Cycle time (optional)
        self.cycle_time_edit = QtWidgets.QSpinBox()
        self.cycle_time_edit.setRange(0, 65535)
        self.cycle_time_edit.setSuffix(" ms")
        self.cycle_time_edit.setSpecialValueText("Not specified")
        self.cycle_time_edit.setToolTip("Message transmission cycle time in milliseconds")
        
        # Message type
        self.message_type_combo = QtWidgets.QComboBox()
        self.message_type_combo.addItems(['Normal', 'Network Management', 'Diagnostic'])
        self.message_type_combo.setToolTip("Type of CAN message")

        self.send_type_combo = QtWidgets.QComboBox()
        self.send_type_combo.addItems(self.existing_send_types)
        self.send_type_combo.setToolTip("Existing cantools message send_type values from the loaded DBC")
        self.send_type_combo.setEditable(True)
        self.send_type_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.send_type_combo.lineEdit().setPlaceholderText("Optional send type")
        self.send_type_combo.setCurrentIndex(-1)

        self.bus_name_combo = QtWidgets.QComboBox()
        self.bus_name_combo.addItems(self.existing_bus_names)
        self.bus_name_combo.setToolTip("Existing cantools bus_name values from the loaded DBC")
        self.bus_name_combo.setEditable(True)
        self.bus_name_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.bus_name_combo.lineEdit().setPlaceholderText("Optional bus name")
        self.bus_name_combo.setCurrentIndex(-1)

        self.protocol_combo = QtWidgets.QComboBox()
        self.protocol_combo.addItems(self.existing_protocols)
        self.protocol_combo.setToolTip("Existing cantools protocol values from the loaded DBC")
        self.protocol_combo.setEditable(True)
        self.protocol_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.protocol_combo.lineEdit().setPlaceholderText("Optional protocol, e.g. j1939")
        self.protocol_combo.setCurrentIndex(-1)

        self.unused_bit_pattern_edit = QtWidgets.QSpinBox()
        self.unused_bit_pattern_edit.setRange(0, 255)
        self.unused_bit_pattern_edit.setToolTip("Unused bit pattern written by cantools")

        advanced_layout.addWidget(QtWidgets.QLabel("Cycle Time:"), 0, 0)
        advanced_layout.addWidget(self.cycle_time_edit, 0, 1)
        advanced_layout.addWidget(QtWidgets.QLabel("Unused Bit Pattern:"), 0, 2)
        advanced_layout.addWidget(self.unused_bit_pattern_edit, 0, 3)
        advanced_layout.addWidget(QtWidgets.QLabel("Message Type:"), 1, 0)
        advanced_layout.addWidget(self.message_type_combo, 1, 1)
        advanced_layout.addWidget(QtWidgets.QLabel("Send Type:"), 1, 2)
        advanced_layout.addWidget(self.send_type_combo, 1, 3)
        advanced_layout.addWidget(QtWidgets.QLabel("Bus Name:"), 2, 0)
        advanced_layout.addWidget(self.bus_name_combo, 2, 1)
        advanced_layout.addWidget(QtWidgets.QLabel("Protocol:"), 2, 2)
        advanced_layout.addWidget(self.protocol_combo, 2, 3)
        advanced_layout.setColumnStretch(1, 1)
        advanced_layout.setColumnStretch(3, 1)
        advanced_group.setLayout(advanced_layout)
        scroll_layout.addWidget(advanced_group)
        
        # Comments Group
        comments_group = QtWidgets.QGroupBox("Comments")
        comments_layout = QtWidgets.QVBoxLayout()
        
        self.comments_edit = QtWidgets.QTextEdit()
        self.comments_edit.setMaximumHeight(100)
        self.comments_edit.setPlaceholderText("Enter message description or comments...")
        self.comments_edit.setToolTip("Description and comments for this message")
        
        comments_layout.addWidget(self.comments_edit)
        comments_group.setLayout(comments_layout)
        scroll_layout.addWidget(comments_group)
        
        # Add stretch to push everything up
        scroll_layout.addStretch()
        
        # Setup scroll area
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        self.ok_button = QtWidgets.QPushButton("OK")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.reset_button = QtWidgets.QPushButton("Reset")
        
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.reset_button.clicked.connect(self.reset_to_defaults)
        
        button_layout.addWidget(self.reset_button)
        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
    def reset_to_defaults(self):
        """Reset all fields to default values."""
        self.name_edit.clear()
        self.frame_id_edit.setText("0x0")
        self.length_edit.setValue(8)
        self.bus_type_combo.setCurrentIndex(0)
        self.senders_dropdown.set_selected_items([])
        self.receivers_dropdown.set_selected_items([])
        self.frame_type_combo.setCurrentIndex(0)  # Standard Frame
        self.cycle_time_edit.setValue(0)
        self.message_type_combo.setCurrentIndex(0)  # Normal
        self.send_type_combo.setCurrentIndex(-1)
        self.send_type_combo.setEditText("")
        self.bus_name_combo.setCurrentIndex(-1)
        self.bus_name_combo.setEditText("")
        self.protocol_combo.setCurrentIndex(-1)
        self.protocol_combo.setEditText("")
        self.unused_bit_pattern_edit.setValue(0)
        self.comments_edit.clear()

    def load_data(self):
        """Load existing message data into the form."""
        if self.message_data:
            self.name_edit.setText(self.message_data.get('name', ''))
            self.frame_id_edit.setText(f"0x{int(self.message_data.get('frame_id', 0)):X}")
            self.length_edit.setValue(self.message_data.get('length', 8))
            self.senders_dropdown.set_selected_items(self.message_data.get('senders', []))
            message_receivers = _unique_strings(
                receiver
                for signal in self.message_data.get('signals', [])
                for receiver in signal.get('receivers', [])
            )
            self.receivers_dropdown.set_selected_items(message_receivers)
            self.comments_edit.setPlainText(self.message_data.get('comments', ''))
            self.cycle_time_edit.setValue(self.message_data.get('cycle_time') or 0)
            self.unused_bit_pattern_edit.setValue(self.message_data.get('unused_bit_pattern') or 0)
            self.bus_type_combo.setCurrentIndex(1 if self.message_data.get('is_fd', False) else 0)

            send_type = self.message_data.get('send_type')
            if send_type and self.send_type_combo.findText(send_type) < 0:
                self.send_type_combo.addItem(send_type)
            if send_type:
                self.send_type_combo.setCurrentText(send_type)
            else:
                self.send_type_combo.setCurrentIndex(-1)
                self.send_type_combo.setEditText("")

            bus_name = self.message_data.get('bus_name')
            if bus_name and self.bus_name_combo.findText(bus_name) < 0:
                self.bus_name_combo.addItem(bus_name)
            if bus_name:
                self.bus_name_combo.setCurrentText(bus_name)
            else:
                self.bus_name_combo.setCurrentIndex(-1)
                self.bus_name_combo.setEditText("")

            protocol = self.message_data.get('protocol')
            if protocol and self.protocol_combo.findText(protocol) < 0:
                self.protocol_combo.addItem(protocol)
            if protocol:
                self.protocol_combo.setCurrentText(protocol)
            else:
                self.protocol_combo.setCurrentIndex(-1)
                self.protocol_combo.setEditText("")

            message_type = self.message_data.get('message_type')
            if message_type:
                index = self.message_type_combo.findText(message_type)
                if index >= 0:
                    self.message_type_combo.setCurrentIndex(index)
            
            is_extended_frame = bool(
                self.message_data.get('is_extended_frame', self.message_data.get('frame_id', 0) > 0x7FF)
            )
            if is_extended_frame:
                self.frame_type_combo.setCurrentIndex(1)  # Extended Frame
            else:
                self.frame_type_combo.setCurrentIndex(0)  # Standard Frame

            if is_message_multiplexed(self.message_data):
                self.msg_multiplexing_label.setText("Yes — has multiplexer signal")
            else:
                self.msg_multiplexing_label.setText("No")
        else:
            self.msg_multiplexing_label.setText("No")
    
    def get_data(self) -> Dict[str, Any]:
        """Get the form data as a dictionary."""
        name = self.name_edit.text().strip()
        if not name:
            raise ValueError("Message name is required")

        frame_id_text = self.frame_id_edit.text().strip()
        if not frame_id_text:
            raise ValueError("Frame ID is required")
        try:
            frame_id = int(frame_id_text, 0)
        except ValueError as exc:
            raise ValueError("Frame ID must be a valid decimal or hex integer") from exc
        if frame_id < 0 or frame_id > 0x1FFFFFFF:
            raise ValueError("Frame ID must be between 0 and 0x1FFFFFFF")

        is_extended_frame = self.frame_type_combo.currentIndex() == 1
        
        return {
            'name': name,
            'frame_id': frame_id,
            'is_extended_frame': is_extended_frame,
            'length': self.length_edit.value(),
            'senders': self.senders_dropdown.selected_items(),
            'comments': self.comments_edit.toPlainText().strip(),
            'cycle_time': self.cycle_time_edit.value() if self.cycle_time_edit.value() > 0 else None,
            'message_type': self.message_type_combo.currentText(),
            'send_type': self.send_type_combo.currentText().strip() or None,
            'bus_name': self.bus_name_combo.currentText().strip() or None,
            'protocol': self.protocol_combo.currentText().strip() or None,
            'unused_bit_pattern': self.unused_bit_pattern_edit.value(),
            'is_fd': self.bus_type_combo.currentText() == "CAN FD",
            'signals': self.message_data.get('signals', [])
        }

class SignalEditDialog(QtWidgets.QDialog):
    """Enhanced dialog for editing signal properties."""
    
    def __init__(self, parent=None, signal_data=None, existing_receivers=None,
                 message_senders=None, message_signals=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Signal")
        self.setModal(True)
        self.resize(600, 700)
        
        self.signal_data = signal_data or {}
        self.existing_receivers = _unique_strings(existing_receivers or [])
        self.message_senders = _unique_strings(message_senders or [])
        self.message_signals = message_signals or []
        self.setup_ui()
        self.load_data()
        
    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        
        # Create scroll area for better layout
        scroll_area = QtWidgets.QScrollArea()
        scroll_widget = QtWidgets.QWidget()
        scroll_layout = QtWidgets.QVBoxLayout(scroll_widget)
        
        # Basic Properties Group
        basic_group = QtWidgets.QGroupBox("Basic Properties")
        basic_layout = QtWidgets.QGridLayout()
        
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("Enter signal name")
        
        self.start_bit_edit = QtWidgets.QSpinBox()
        self.start_bit_edit.setRange(0, 511)
        self.start_bit_edit.setToolTip("Starting bit position (0-511)")
        
        self.length_edit = QtWidgets.QSpinBox()
        self.length_edit.setRange(1, 64)
        self.length_edit.setToolTip("Number of bits (1-64)")
        
        basic_layout.addWidget(QtWidgets.QLabel("Name:"), 0, 0)
        basic_layout.addWidget(self.name_edit, 0, 1, 1, 3)
        basic_layout.addWidget(QtWidgets.QLabel("Start Bit:"), 1, 0)
        basic_layout.addWidget(self.start_bit_edit, 1, 1)
        basic_layout.addWidget(QtWidgets.QLabel("Length (bits):"), 1, 2)
        basic_layout.addWidget(self.length_edit, 1, 3)
        basic_layout.setColumnStretch(1, 1)
        basic_layout.setColumnStretch(3, 1)
        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)
        
        # Data Properties Group
        data_group = QtWidgets.QGroupBox("Data Properties")
        data_layout = QtWidgets.QGridLayout()
        data_layout.setHorizontalSpacing(8)
        data_layout.setVerticalSpacing(8)
        
        self.byte_order_combo = QtWidgets.QComboBox()
        self.byte_order_combo.addItems(['little_endian', 'big_endian'])
        self.byte_order_combo.setToolTip("Byte order for multi-byte signals")
        
        self.is_signed_check = QtWidgets.QCheckBox("Signed")
        self.is_signed_check.setToolTip("Check if signal is signed")
        
        self.unit_edit = QtWidgets.QLineEdit()
        self.unit_edit.setPlaceholderText("e.g., rpm, km/h, deg")
        self.unit_edit.setToolTip("Physical unit of the signal")

        self.raw_initial_edit = QtWidgets.QLineEdit()
        self.raw_initial_edit.setPlaceholderText("Optional raw initial value, e.g. 0 or 0xFF")
        self.raw_initial_edit.setToolTip("Native cantools raw_initial value")

        self.raw_invalid_edit = QtWidgets.QLineEdit()
        self.raw_invalid_edit.setPlaceholderText("Optional raw invalid value, e.g. 255 or 0xFF")
        self.raw_invalid_edit.setToolTip("Native cantools raw_invalid value")
        
        data_layout.addWidget(QtWidgets.QLabel("Byte Order:"), 0, 0)
        data_layout.addWidget(self.byte_order_combo, 0, 1)
        data_layout.addWidget(QtWidgets.QLabel("Unit:"), 0, 2)
        data_layout.addWidget(self.unit_edit, 0, 3)
        data_layout.addWidget(QtWidgets.QLabel("Raw Initial:"), 1, 0)
        data_layout.addWidget(self.raw_initial_edit, 1, 1)
        data_layout.addWidget(QtWidgets.QLabel("Raw Invalid:"), 1, 2)
        data_layout.addWidget(self.raw_invalid_edit, 1, 3)
        data_layout.addWidget(self.is_signed_check, 2, 0, 1, 4)
        data_layout.setColumnStretch(1, 1)
        data_layout.setColumnStretch(3, 1)
        data_group.setLayout(data_layout)
        scroll_layout.addWidget(data_group)
        
        # Scale & Range Properties Group
        scale_range_group = QtWidgets.QGroupBox("Scale && Range Properties")
        scale_range_layout = QtWidgets.QGridLayout()
        scale_range_layout.setHorizontalSpacing(8)
        scale_range_layout.setVerticalSpacing(8)
        
        self.scale_edit = QtWidgets.QDoubleSpinBox()
        self.scale_edit.setRange(-1000000, 1000000)
        self.scale_edit.setDecimals(6)
        self.scale_edit.setValue(1.0)
        self.scale_edit.setToolTip("Scale factor: physical_value = raw_value * scale + offset")
        
        self.offset_edit = QtWidgets.QDoubleSpinBox()
        self.offset_edit.setRange(-1000000, 1000000)
        self.offset_edit.setDecimals(6)
        self.offset_edit.setToolTip("Offset value")

        self.is_float_check = QtWidgets.QCheckBox("Float Conversion")
        self.is_float_check.setToolTip("Use cantools float conversion for this signal")
        
        self.minimum_edit = QtWidgets.QDoubleSpinBox()
        self.minimum_edit.setRange(-1000000, 1000000)
        self.minimum_edit.setDecimals(6)
        self.minimum_edit.setToolTip("Minimum physical value")
        
        self.maximum_edit = QtWidgets.QDoubleSpinBox()
        self.maximum_edit.setRange(-1000000, 1000000)
        self.maximum_edit.setDecimals(6)
        self.maximum_edit.setToolTip("Maximum physical value")

        scale_range_layout.addWidget(QtWidgets.QLabel("Scale:"), 0, 0)
        scale_range_layout.addWidget(self.scale_edit, 0, 1)
        scale_range_layout.addWidget(QtWidgets.QLabel("Offset:"), 0, 2)
        scale_range_layout.addWidget(self.offset_edit, 0, 3)
        scale_range_layout.addWidget(QtWidgets.QLabel("Minimum:"), 1, 0)
        scale_range_layout.addWidget(self.minimum_edit, 1, 1)
        scale_range_layout.addWidget(QtWidgets.QLabel("Maximum:"), 1, 2)
        scale_range_layout.addWidget(self.maximum_edit, 1, 3)
        scale_range_layout.addWidget(QtWidgets.QLabel("Float Conversion:"), 2, 0)
        scale_range_layout.addWidget(self.is_float_check, 2, 1)

        self.show_choices_button = QtWidgets.QPushButton("+ Add Choices")
        self.show_choices_button.setToolTip("Show the value-table editor to add signal choices")
        self.show_choices_button.setFlat(True)
        self.show_choices_button.setStyleSheet("QPushButton { color: #2980B9; text-decoration: underline; }")
        self.show_choices_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.show_choices_button.clicked.connect(self._show_choices_group)
        scale_range_layout.addWidget(self.show_choices_button, 2, 2, 1, 2, QtCore.Qt.AlignRight)

        scale_range_layout.setColumnStretch(1, 1)
        scale_range_layout.setColumnStretch(3, 1)
        scale_range_group.setLayout(scale_range_layout)
        scroll_layout.addWidget(scale_range_group)

        # Choices group (hidden when signal has no choices; revealed by button above)
        self.choices_group = QtWidgets.QGroupBox("Choices")
        choices_group_layout = QtWidgets.QHBoxLayout()
        choices_group_layout.setContentsMargins(6, 6, 6, 6)

        self.choices_table = QtWidgets.QTableWidget(0, 2)
        self.choices_table.setHorizontalHeaderLabels(["Value", "Label"])
        self.choices_table.verticalHeader().setVisible(False)
        self.choices_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.choices_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.choices_table.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
            | QtWidgets.QAbstractItemView.AnyKeyPressed
        )
        self.choices_table.setAlternatingRowColors(True)
        self.choices_table.setMinimumHeight(110)
        self.choices_table.setMaximumHeight(150)
        self.choices_table.horizontalHeader().setStretchLastSection(True)
        self.choices_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self.choices_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.choices_table.setToolTip("cantools value table. Edit Value and Label cells directly.")

        self.add_choice_button = QtWidgets.QPushButton("Add")
        self.add_choice_button.setToolTip("Add a new value-table row")
        self.add_choice_button.clicked.connect(self._add_choice_row)

        self.remove_choice_button = QtWidgets.QPushButton("Remove")
        self.remove_choice_button.setToolTip("Remove the selected value-table row")
        self.remove_choice_button.clicked.connect(self._remove_selected_choice_rows)

        choices_buttons_layout = QtWidgets.QVBoxLayout()
        choices_buttons_layout.setContentsMargins(0, 0, 0, 0)
        choices_buttons_layout.addWidget(self.add_choice_button)
        choices_buttons_layout.addWidget(self.remove_choice_button)
        choices_buttons_layout.addStretch()

        choices_group_layout.addWidget(self.choices_table, 1)
        choices_group_layout.addLayout(choices_buttons_layout)
        self.choices_group.setLayout(choices_group_layout)
        self.choices_group.hide()
        scroll_layout.addWidget(self.choices_group)
        
        # Network Properties Group
        network_group = QtWidgets.QGroupBox("Network Properties")
        network_layout = QtWidgets.QFormLayout()
        
        self.receivers_dropdown = SectionedCheckableDropdown(
            "Receivers",
            self.existing_receivers,
            allow_new=True,
            new_item_label="Receiver",
            parent=self,
        )
        self.receivers_dropdown.setToolTip("Nodes that receive this signal")

        self.senders_dropdown = SectionedCheckableDropdown(
            "Senders",
            self.message_senders,
            read_only=True,
            parent=self,
        )
        self.senders_dropdown.set_selected_items(self.message_senders)
        self.senders_dropdown.setToolTip("Message senders from the parent message")

        receivers_label = QtWidgets.QLabel("Receivers:")
        senders_label = QtWidgets.QLabel("Senders:")

        node_layout = QtWidgets.QHBoxLayout()
        node_layout.setContentsMargins(0, 0, 0, 0)
        node_layout.addWidget(receivers_label)
        node_layout.addWidget(self.receivers_dropdown, 1)
        node_layout.addWidget(senders_label)
        node_layout.addWidget(self.senders_dropdown, 1)

        network_layout.addRow("", node_layout)
        network_group.setLayout(network_layout)
        scroll_layout.addWidget(network_group)

        # Multiplexing Properties
        mux_group = QtWidgets.QGroupBox("Multiplexing Properties")
        mux_layout = QtWidgets.QFormLayout()

        self.mux_role_label = QtWidgets.QLabel("Role: —")
        self.mux_role_label.setStyleSheet("QLabel { font-weight: bold; color: #555; }")
        self.mux_role_label.setToolTip("Current multiplexing role of this signal")
        mux_layout.addRow("Role:", self.mux_role_label)

        self.is_multiplexer_check = QtWidgets.QCheckBox("This signal is the multiplexer selector")
        self.is_multiplexer_check.setToolTip(
            "Check to mark this signal as the multiplexer (M). "
            "Only one multiplexer per message is allowed."
        )
        self.is_multiplexer_check.toggled.connect(self._on_is_multiplexer_toggled)

        self.multiplexer_signal_combo = QtWidgets.QComboBox()
        self.multiplexer_signal_combo.setEditable(True)
        self.multiplexer_signal_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.multiplexer_signal_combo.lineEdit().setPlaceholderText("Select or type multiplexer signal name")
        self.multiplexer_signal_combo.setToolTip(
            "The multiplexer signal that controls when this signal is active"
        )
        self._populate_multiplexer_signal_combo()

        self.multiplexer_id_combo = QtWidgets.QComboBox()
        self.multiplexer_id_combo.setEditable(True)
        self.multiplexer_id_combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        self.multiplexer_id_combo.lineEdit().setPlaceholderText("Select or enter mux ID (e.g. 0xA)")
        self.multiplexer_id_combo.setToolTip(
            "The multiplexer ID for which this signal is active"
        )
        self._populate_multiplexer_id_combo()
        self.is_multiplexer_check.toggled.connect(self._update_mux_role_label)
        self.multiplexer_id_combo.currentIndexChanged.connect(self._update_mux_role_label)
        self.multiplexer_id_combo.currentTextChanged.connect(self._update_mux_role_label)

        mux_layout.addRow("", self.is_multiplexer_check)
        mux_layout.addRow("Multiplexer Signal:", self.multiplexer_signal_combo)
        mux_layout.addRow("Multiplexer ID:", self.multiplexer_id_combo)
        mux_group.setLayout(mux_layout)
        scroll_layout.addWidget(mux_group)

        # Advanced Signal Properties
        advanced_group = QtWidgets.QGroupBox("Advanced Signal Properties")
        advanced_layout = QtWidgets.QFormLayout()

        self.spn_edit = QtWidgets.QLineEdit()
        self.spn_edit.setPlaceholderText("Optional SPN")
        self.spn_edit.setToolTip("J1939 Suspect Parameter Number")

        advanced_layout.addRow("SPN:", self.spn_edit)
        advanced_group.setLayout(advanced_layout)
        scroll_layout.addWidget(advanced_group)
        
        # Comments Group
        comments_group = QtWidgets.QGroupBox("Comments")
        comments_layout = QtWidgets.QVBoxLayout()
        
        self.comments_edit = QtWidgets.QTextEdit()
        self.comments_edit.setMaximumHeight(100)
        self.comments_edit.setPlaceholderText("Enter signal description or comments...")
        self.comments_edit.setToolTip("Description and comments for this signal")
        
        comments_layout.addWidget(self.comments_edit)
        comments_group.setLayout(comments_layout)
        scroll_layout.addWidget(comments_group)
        
        # Add stretch to push everything up
        scroll_layout.addStretch()
        
        # Setup scroll area
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        self.ok_button = QtWidgets.QPushButton("OK")
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.reset_button = QtWidgets.QPushButton("Reset")
        
        self.ok_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self.reset_button.clicked.connect(self.reset_to_defaults)
        
        button_layout.addWidget(self.reset_button)
        button_layout.addStretch()
        button_layout.addWidget(self.ok_button)
        button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(button_layout)
        
    def load_data(self):
        """Load existing signal data into the form."""
        if self.signal_data:
            self.name_edit.setText(self.signal_data.get('name', ''))
            
            # Handle potential None values for start_bit and length
            start_bit_val = self.signal_data.get('start_bit')
            if start_bit_val is not None:
                self.start_bit_edit.setValue(int(start_bit_val))
            else:
                self.start_bit_edit.setValue(0)
                
            length_val = self.signal_data.get('length')
            if length_val is not None:
                self.length_edit.setValue(int(length_val))
            else:
                self.length_edit.setValue(1)
            
            byte_order = self.signal_data.get('byte_order', 'little_endian')
            index = self.byte_order_combo.findText(byte_order)
            if index >= 0:
                self.byte_order_combo.setCurrentIndex(index)
            
            self.is_signed_check.setChecked(self.signal_data.get('is_signed', False))
            
            # Handle potential None values for scale and offset
            scale_val = self.signal_data.get('scale')
            if scale_val is not None:
                self.scale_edit.setValue(float(scale_val))
            else:
                self.scale_edit.setValue(1.0)
                
            offset_val = self.signal_data.get('offset')
            if offset_val is not None:
                self.offset_edit.setValue(float(offset_val))
            else:
                self.offset_edit.setValue(0.0)
            self.is_float_check.setChecked(bool(self.signal_data.get('is_float', False)))
            self._load_choices_table(self.signal_data.get('choices'))
            
            # Handle None values for minimum and maximum
            minimum_val = self.signal_data.get('minimum')
            if minimum_val is not None:
                self.minimum_edit.setValue(float(minimum_val))
            else:
                self.minimum_edit.setValue(0.0)
                
            maximum_val = self.signal_data.get('maximum')
            if maximum_val is not None:
                self.maximum_edit.setValue(float(maximum_val))
            else:
                self.maximum_edit.setValue(0.0)
                
            self.unit_edit.setText(self.signal_data.get('unit', ''))
            self.raw_initial_edit.setText(_format_optional_value(self.signal_data.get('raw_initial')))
            self.raw_invalid_edit.setText(_format_optional_value(self.signal_data.get('raw_invalid')))
            self.receivers_dropdown.set_selected_items(self.signal_data.get('receivers', []))
            self.is_multiplexer_check.setChecked(bool(self.signal_data.get('is_multiplexer', False)))
            mux_sig = self.signal_data.get('multiplexer_signal') or ''
            if mux_sig and self.multiplexer_signal_combo.findText(mux_sig) < 0:
                self.multiplexer_signal_combo.addItem(mux_sig)
            self.multiplexer_signal_combo.setCurrentText(mux_sig)
            multiplexer_ids = self.signal_data.get('multiplexer_ids') or []
            if multiplexer_ids:
                mid = int(multiplexer_ids[0])
                msg_dict = {"signals": self.message_signals}
                mux_id_text = format_mux_id_with_name(msg_dict, mid)
                if self.multiplexer_id_combo.findText(mux_id_text) < 0:
                    self.multiplexer_id_combo.addItem(mux_id_text)
                self.multiplexer_id_combo.setCurrentText(mux_id_text)
            else:
                self.multiplexer_id_combo.setCurrentIndex(0)
            self.spn_edit.setText(_format_optional_value(self.signal_data.get('spn')))
            self.comments_edit.setPlainText(self.signal_data.get('comments', ''))
            self._update_mux_role_label()
    
    def reset_to_defaults(self):
        """Reset all fields to default values."""
        self.name_edit.clear()
        self.start_bit_edit.setValue(0)
        self.length_edit.setValue(1)
        self.byte_order_combo.setCurrentIndex(0)  # little_endian
        self.is_signed_check.setChecked(False)
        self.scale_edit.setValue(1.0)
        self.offset_edit.setValue(0.0)
        self.is_float_check.setChecked(False)
        self.choices_table.setRowCount(0)
        self.choices_group.hide()
        self.show_choices_button.show()
        self.minimum_edit.setValue(0.0)
        self.maximum_edit.setValue(0.0)
        self.unit_edit.clear()
        self.raw_initial_edit.clear()
        self.raw_invalid_edit.clear()
        self.receivers_dropdown.set_selected_items([])
        self.is_multiplexer_check.setChecked(False)
        self.multiplexer_signal_combo.setCurrentIndex(-1)
        self.multiplexer_signal_combo.lineEdit().clear()
        self.multiplexer_id_combo.setCurrentIndex(0)
        self.mux_role_label.setText("—")
        self.spn_edit.clear()
        self.comments_edit.clear()

    def _update_mux_role_label(self) -> None:
        """Update the read-only Role label from current form state."""
        if self.is_multiplexer_check.isChecked():
            self.mux_role_label.setText("Multiplexer (selector)")
        elif self.multiplexer_id_combo.currentText().strip():
            self.mux_role_label.setText("Multiplexed signal")
        else:
            self.mux_role_label.setText("Regular signal")

    def _populate_multiplexer_signal_combo(self) -> None:
        """Fill the multiplexer signal combo with existing multiplexer signals."""
        self.multiplexer_signal_combo.clear()
        self.multiplexer_signal_combo.addItem("")
        seen: set = set()
        for sig in self.message_signals:
            if sig.get("is_multiplexer", False):
                name = sig.get("name", "")
                if name and name not in seen:
                    self.multiplexer_signal_combo.addItem(name)
                    seen.add(name)

    def _populate_multiplexer_id_combo(self) -> None:
        """Fill the mux ID combo with existing IDs from the message, in hex with names when available."""
        self.multiplexer_id_combo.clear()
        self.multiplexer_id_combo.addItem("")
        ids: set = set()
        for sig in self.message_signals:
            for mid in sig.get("multiplexer_ids", []) or []:
                ids.add(int(mid))
        msg_dict = {"signals": self.message_signals}
        for mid in sorted(ids):
            self.multiplexer_id_combo.addItem(format_mux_id_with_name(msg_dict, mid))

    def _parse_mux_id_from_combo(self) -> Optional[List[int]]:
        """Parse the single mux ID from the combo (hex part only; name in parens is ignored)."""
        text = self.multiplexer_id_combo.currentText().strip()
        if not text:
            return None
        hex_part = text.split(" (")[0].strip()
        try:
            return [int(hex_part, 0)]
        except ValueError:
            raise ValueError(f"Invalid multiplexer ID: '{hex_part}'")

    def _on_is_multiplexer_toggled(self, checked: bool) -> None:
        """Enforce mutual exclusivity: a multiplexer cannot be multiplexed."""
        self.multiplexer_signal_combo.setEnabled(not checked)
        self.multiplexer_id_combo.setEnabled(not checked)
        if checked:
            self.multiplexer_signal_combo.setCurrentIndex(0)
            self.multiplexer_id_combo.setCurrentIndex(0)

    def get_data(self) -> Dict[str, Any]:
        """Get the form data as a dictionary."""
        name = self.name_edit.text().strip()
        if not name:
            raise ValueError("Signal name is required")
        
        raw_initial = _parse_optional_number(self.raw_initial_edit.text(), "Raw initial")
        raw_invalid = _parse_optional_number(self.raw_invalid_edit.text(), "Raw invalid")
        multiplexer_ids = self._parse_mux_id_from_combo()
        spn = _parse_optional_int(self.spn_edit.text(), "SPN")
        choices = self._extract_choices_table()

        is_mux = self.is_multiplexer_check.isChecked()
        mux_sig_ref = self.multiplexer_signal_combo.currentText().strip()
        if multiplexer_ids and not mux_sig_ref and not is_mux:
            raise ValueError(
                "Multiplexer IDs are set but no multiplexer signal is selected. "
                "Either select the multiplexer signal or clear the IDs."
            )
        if is_mux and (multiplexer_ids or mux_sig_ref):
            raise ValueError(
                "A multiplexer (selector) signal cannot itself be multiplexed. "
                "Clear the Multiplexer Signal and IDs fields, or uncheck "
                "'This signal is the multiplexer selector'."
            )

        minimum_val = self.minimum_edit.value()
        maximum_val = self.maximum_edit.value()
        
        return {
            'name': name,
            'start_bit': self.start_bit_edit.value(),
            'length': self.length_edit.value(),
            'byte_order': self.byte_order_combo.currentText(),
            'is_signed': self.is_signed_check.isChecked(),
            'raw_initial': raw_initial,
            'raw_invalid': raw_invalid,
            'scale': self.scale_edit.value(),
            'offset': self.offset_edit.value(),
            'is_float': self.is_float_check.isChecked(),
            'minimum': minimum_val,
            'maximum': maximum_val,
            'unit': self.unit_edit.text().strip(),
            'receivers': self.receivers_dropdown.selected_items(),
            'is_multiplexer': self.is_multiplexer_check.isChecked(),
            'multiplexer_signal': self.multiplexer_signal_combo.currentText().strip() or None,
            'multiplexer_ids': multiplexer_ids,
            'spn': spn,
            'comments': self.comments_edit.toPlainText().strip(),
            'choices': choices,
        }

    def _add_choice_row(self, value: str = "", label: str = "") -> None:
        """Append a value-table row and focus the first editable cell."""
        row = self.choices_table.rowCount()
        self.choices_table.insertRow(row)

        value_item = QtWidgets.QTableWidgetItem(value)
        label_item = QtWidgets.QTableWidgetItem(label)
        self.choices_table.setItem(row, 0, value_item)
        self.choices_table.setItem(row, 1, label_item)

        self.choices_table.setCurrentCell(row, 0)
        self.choices_table.editItem(value_item)

    def _remove_selected_choice_rows(self) -> None:
        """Remove all currently selected value-table rows."""
        selected_rows = sorted(
            {index.row() for index in self.choices_table.selectionModel().selectedRows()},
            reverse=True,
        )
        for row in selected_rows:
            self.choices_table.removeRow(row)

    def _show_choices_group(self) -> None:
        """Reveal the Choices group and hide the trigger button."""
        self.choices_group.show()
        self.show_choices_button.hide()

    def _load_choices_table(self, choices: Any) -> None:
        """Load cantools choices into the editable table. Shows the group only when data exists."""
        self.choices_table.setRowCount(0)
        normalized = _normalize_choices(choices)
        for value, label in normalized.items():
            row = self.choices_table.rowCount()
            self.choices_table.insertRow(row)
            self.choices_table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(value)))
            self.choices_table.setItem(row, 1, QtWidgets.QTableWidgetItem(label))
        has_choices = len(normalized) > 0
        self.choices_group.setVisible(has_choices)
        self.show_choices_button.setVisible(not has_choices)

    def _extract_choices_table(self) -> Optional[OrderedDict[int, str]]:
        """Read the editable value table back into an ordered dict."""
        choices: OrderedDict[int, str] = OrderedDict()

        for row in range(self.choices_table.rowCount()):
            value_item = self.choices_table.item(row, 0)
            label_item = self.choices_table.item(row, 1)
            value_text = value_item.text().strip() if value_item else ""
            label_text = label_item.text().strip() if label_item else ""

            if not value_text and not label_text:
                continue
            if not value_text:
                raise ValueError(f"Choices row {row + 1} is missing a value")
            if not label_text:
                raise ValueError(f"Choices row {row + 1} is missing a label")

            try:
                parsed_value = int(value_text, 0)
            except ValueError as exc:
                raise ValueError(f"Choices row {row + 1} has an invalid integer value") from exc

            if parsed_value in choices:
                raise ValueError(f"Choices row {row + 1} duplicates value {parsed_value}")

            choices[parsed_value] = label_text

        return choices or None

class DBCEditorWidget(QtWidgets.QWidget):
    """Main DBC editor widget with error handling and improved readability."""
    dbcFileLoaded = QtCore.pyqtSignal(str)
    saveReviewRequested = QtCore.pyqtSignal(object, object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dbc_editor = DBCEditor()
        self.current_file_path = None
        self.layout_visualizer_window: Optional[MessageSignalLayoutWindow] = None
        self.setup_ui()
        
    def setup_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        
        # Apply modern styling
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #cccccc;
                border-radius: 5px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                padding: 5px;
                border: 1px solid #cccccc;
                border-radius: 3px;
            }
            QListWidget {
                border: 1px solid #cccccc;
                border-radius: 3px;
                background-color: white;
            }
            QListWidget::item {
                padding: 5px;
                border-bottom: 1px solid #f0f0f0;
            }
            QListWidget::item:selected {
                background-color: #e3f2fd;
                color: black;
            }
        """)
        
        # File operations section
        file_group = QtWidgets.QGroupBox("File Operations")
        file_main_layout = QtWidgets.QVBoxLayout()
        
        file_layout = QtWidgets.QHBoxLayout()
        
        self.file_label = QtWidgets.QLabel("No file loaded")
        self.new_button = QtWidgets.QPushButton("New DBC File")
        self.load_button = QtWidgets.QPushButton("Load DBC File")
        self.save_button = QtWidgets.QPushButton("Save Changes")
        self.save_as_button = QtWidgets.QPushButton("Save As...")
        
        self.new_button.setIcon(qta.icon("fa5s.file-medical", color="white"))
        self.new_button.setIconSize(QtCore.QSize(16, 16))
        self.load_button.setIcon(qta.icon("fa5s.folder-open", color="white"))
        self.load_button.setIconSize(QtCore.QSize(16, 16))
        self.save_button.setIcon(qta.icon("fa5s.save", color="white"))
        self.save_button.setIconSize(QtCore.QSize(16, 16))
        self.save_as_button.setIcon(qta.icon("fa5s.file-export", color="white"))
        self.save_as_button.setIconSize(QtCore.QSize(16, 16))
        
        # Style the new button to match the load button (green, enabled)
        self.new_button.setStyleSheet("background-color: #4CAF50; color: white; border: none; padding: 8px 16px; border-radius: 4px; font-weight: bold;")
        
        self.new_button.clicked.connect(self.new_dbc_file)
        self.load_button.clicked.connect(self.load_dbc_file)
        self.save_button.clicked.connect(self.save_changes)
        self.save_as_button.clicked.connect(self.save_as)
        
        file_layout.addWidget(self.file_label)
        file_layout.addStretch()
        file_layout.addWidget(self.new_button)
        file_layout.addWidget(self.load_button)
        file_layout.addWidget(self.save_button)
        file_layout.addWidget(self.save_as_button)
        
        file_main_layout.addLayout(file_layout)

        # File info panel (message and signal counts)
        info_layout = QtWidgets.QHBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(12)
        self.info_message_count = QtWidgets.QLabel("Messages: —")
        self.info_signal_count = QtWidgets.QLabel("Signals: —")
        info_layout.addWidget(self.info_message_count)
        info_layout.addWidget(QtWidgets.QLabel("|"))
        info_layout.addWidget(self.info_signal_count)
        info_layout.addStretch()
        file_main_layout.addLayout(info_layout)

        file_group.setLayout(file_main_layout)
        layout.addWidget(file_group)
        
        # Messages section
        messages_group = QtWidgets.QGroupBox("Messages")
        messages_layout = QtWidgets.QVBoxLayout()
        
        # Unified search widget for messages
        self.message_search_widget = UnifiedSearchWidget(self, mode="edit")
        self.message_search_widget.search_edit.setPlaceholderText("Search messages by name or ID...")
        self.message_search_widget.searchChanged.connect(self.filter_messages)
        messages_layout.addWidget(self.message_search_widget)
        
        # Message buttons
        message_buttons_layout = QtWidgets.QHBoxLayout()
        self.add_message_button = QtWidgets.QPushButton("Add Message")
        self.edit_message_button = QtWidgets.QPushButton("Edit Message")
        self.delete_message_button = QtWidgets.QPushButton("Delete Message")
        self.duplicate_message_button = QtWidgets.QPushButton("Duplicate")
        self.duplicate_message_button.setIcon(qta.icon("fa5s.copy", color="white"))
        self.duplicate_message_button.setIconSize(QtCore.QSize(16, 16))
        self.visualize_layout_button = QtWidgets.QPushButton(" Visualize Layout")
        self.visualize_layout_button.setIcon(qta.icon("fa5s.project-diagram", color="white"))
        self.visualize_layout_button.setIconSize(QtCore.QSize(16, 16))
        
        self.add_message_button.setIcon(qta.icon("fa5s.plus", color="white"))
        self.add_message_button.setIconSize(QtCore.QSize(16, 16))
        self.edit_message_button.setIcon(qta.icon("fa5s.edit", color="white"))
        self.edit_message_button.setIconSize(QtCore.QSize(16, 16))
        self.delete_message_button.setIcon(qta.icon("fa5s.trash", color="white"))
        self.delete_message_button.setIconSize(QtCore.QSize(16, 16))
        
        self.add_message_button.clicked.connect(self.add_message)
        self.edit_message_button.clicked.connect(self.edit_message)
        self.delete_message_button.clicked.connect(self.delete_message)
        self.duplicate_message_button.clicked.connect(self.duplicate_message)
        self.visualize_layout_button.clicked.connect(self.show_layout_visualizer)
        
        message_buttons_layout.addWidget(self.add_message_button)
        message_buttons_layout.addWidget(self.edit_message_button)
        message_buttons_layout.addWidget(self.delete_message_button)
        message_buttons_layout.addWidget(self.duplicate_message_button)
        message_buttons_layout.addWidget(self.visualize_layout_button)
        message_buttons_layout.addStretch()
        
        messages_layout.addLayout(message_buttons_layout)
        
        # Message list with move controls
        message_list_row = QtWidgets.QHBoxLayout()
        message_move_col = QtWidgets.QVBoxLayout()
        self.move_message_up_button = QtWidgets.QPushButton()
        self.move_message_up_button.setIcon(qta.icon("fa5s.arrow-up", color="white"))
        self.move_message_up_button.setIconSize(QtCore.QSize(14, 14))
        self.move_message_down_button = QtWidgets.QPushButton()
        self.move_message_down_button.setIcon(qta.icon("fa5s.arrow-down", color="white"))
        self.move_message_down_button.setIconSize(QtCore.QSize(14, 14))
        self.move_message_up_button.setFixedWidth(30)
        self.move_message_down_button.setFixedWidth(30)
        message_move_col.addWidget(self.move_message_up_button)
        message_move_col.addWidget(self.move_message_down_button)
        message_move_col.addStretch()
        self.message_list = QtWidgets.QListWidget()
        self.message_list.itemClicked.connect(self.on_message_selected)
        self.message_list.itemDoubleClicked.connect(self.edit_message)
        message_list_row.addLayout(message_move_col)
        message_list_row.addWidget(self.message_list)
        messages_layout.addLayout(message_list_row)
        # Connect message move buttons
        self.move_message_up_button.clicked.connect(self.move_selected_message_up)
        self.move_message_down_button.clicked.connect(self.move_selected_message_down)
        
        messages_group.setLayout(messages_layout)
        layout.addWidget(messages_group)
        
        # Signals section
        signals_group = QtWidgets.QGroupBox("Signals")
        signals_layout = QtWidgets.QVBoxLayout()
        
        # Unified search widget for signals
        self.signal_search_widget = UnifiedSearchWidget(self, mode="edit")
        self.signal_search_widget.search_edit.setPlaceholderText("Search signals by name...")
        self.signal_search_widget.searchChanged.connect(self.filter_signals)
        signals_layout.addWidget(self.signal_search_widget)

        # Mux filter (hidden until a multiplexed message is selected)
        self.mux_filter_row = QtWidgets.QWidget()
        mux_filter_layout = QtWidgets.QHBoxLayout(self.mux_filter_row)
        mux_filter_layout.setContentsMargins(0, 2, 0, 2)
        self.mux_filter_label = QtWidgets.QLabel("Multiplexer Signal:")
        self.mux_filter_combo = QtWidgets.QComboBox()
        self.mux_filter_combo.setToolTip("Filter signals by multiplexer ID")
        self.mux_filter_combo.currentIndexChanged.connect(self._on_mux_filter_changed)
        mux_filter_layout.addWidget(self.mux_filter_label)
        mux_filter_layout.addWidget(self.mux_filter_combo, 1)
        self.mux_filter_row.hide()
        signals_layout.addWidget(self.mux_filter_row)

        # Signal buttons
        signal_buttons_layout = QtWidgets.QHBoxLayout()
        self.add_signal_button = QtWidgets.QPushButton("Add Signal")
        self.edit_signal_button = QtWidgets.QPushButton("Edit Signal")
        self.delete_signal_button = QtWidgets.QPushButton("Delete Signal")
        self.duplicate_signal_button = QtWidgets.QPushButton("Duplicate")
        self.duplicate_signal_button.setIcon(qta.icon("fa5s.copy", color="white"))
        self.duplicate_signal_button.setIconSize(QtCore.QSize(16, 16))
        
        self.add_signal_button.setIcon(qta.icon("fa5s.plus", color="white"))
        self.add_signal_button.setIconSize(QtCore.QSize(16, 16))
        self.edit_signal_button.setIcon(qta.icon("fa5s.edit", color="white"))
        self.edit_signal_button.setIconSize(QtCore.QSize(16, 16))
        self.delete_signal_button.setIcon(qta.icon("fa5s.trash", color="white"))
        self.delete_signal_button.setIconSize(QtCore.QSize(16, 16))
        
        self.add_signal_button.clicked.connect(self.add_signal)
        self.edit_signal_button.clicked.connect(self.edit_signal)
        self.delete_signal_button.clicked.connect(self.delete_signal)
        self.duplicate_signal_button.clicked.connect(self.duplicate_signal)
        
        signal_buttons_layout.addWidget(self.add_signal_button)
        signal_buttons_layout.addWidget(self.edit_signal_button)
        signal_buttons_layout.addWidget(self.delete_signal_button)
        signal_buttons_layout.addWidget(self.duplicate_signal_button)
        signal_buttons_layout.addStretch()
        
        signals_layout.addLayout(signal_buttons_layout)
        
        # Signal list with move controls
        signal_list_row = QtWidgets.QHBoxLayout()
        signal_move_col = QtWidgets.QVBoxLayout()
        self.move_signal_up_button = QtWidgets.QPushButton()
        self.move_signal_up_button.setIcon(qta.icon("fa5s.arrow-up", color="white"))
        self.move_signal_up_button.setIconSize(QtCore.QSize(14, 14))
        self.move_signal_down_button = QtWidgets.QPushButton()
        self.move_signal_down_button.setIcon(qta.icon("fa5s.arrow-down", color="white"))
        self.move_signal_down_button.setIconSize(QtCore.QSize(14, 14))
        self.move_signal_up_button.setFixedWidth(30)
        self.move_signal_down_button.setFixedWidth(30)
        signal_move_col.addWidget(self.move_signal_up_button)
        signal_move_col.addWidget(self.move_signal_down_button)
        signal_move_col.addStretch()
        self.signal_list = QtWidgets.QListWidget()
        self.signal_list.itemClicked.connect(self.on_signal_selected)
        self.signal_list.itemDoubleClicked.connect(self.edit_signal)
        signal_list_row.addLayout(signal_move_col)
        signal_list_row.addWidget(self.signal_list)
        signals_layout.addLayout(signal_list_row)
        # Connect signal move buttons
        self.move_signal_up_button.clicked.connect(self.move_selected_signal_up)
        self.move_signal_down_button.clicked.connect(self.move_selected_signal_down)
        
        signals_group.setLayout(signals_layout)
        layout.addWidget(signals_group)
        
        # Status section
        status_layout = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("Ready")
        self.changes_label = QtWidgets.QLabel("No changes")
        
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.changes_label)
        
        layout.addLayout(status_layout)
        
        # Initialize button states
        self.update_button_states()

    

    def _get_existing_message_senders(self) -> List[str]:
        if not self.dbc_editor._modified_data:
            return []
        senders: List[str] = []
        for message in self.dbc_editor._modified_data.get('messages', []):
            senders.extend(message.get('senders', []))
        return _unique_strings(senders)

    def _get_existing_signal_receivers(self) -> List[str]:
        if not self.dbc_editor._modified_data:
            return []
        receivers: List[str] = []
        for message in self.dbc_editor._modified_data.get('messages', []):
            for signal in message.get('signals', []):
                receivers.extend(signal.get('receivers', []))
        return _unique_strings(receivers)

    def _get_existing_send_types(self) -> List[str]:
        if not self.dbc_editor._modified_data:
            return []
        send_types = [
            message.get('send_type')
            for message in self.dbc_editor._modified_data.get('messages', [])
            if message.get('send_type')
        ]
        return _unique_strings(send_types)

    def _get_existing_bus_names(self) -> List[str]:
        if not self.dbc_editor._modified_data:
            return []
        bus_names = [
            message.get('bus_name')
            for message in self.dbc_editor._modified_data.get('messages', [])
            if message.get('bus_name')
        ]
        return _unique_strings(bus_names)

    def _get_existing_protocols(self) -> List[str]:
        if not self.dbc_editor._modified_data:
            return []
        protocols = [
            message.get('protocol')
            for message in self.dbc_editor._modified_data.get('messages', [])
            if message.get('protocol')
        ]
        return _unique_strings(protocols)

    def _get_selected_message_data(self) -> Optional[Dict[str, Any]]:
        current_row = self.message_list.currentRow()
        if current_row < 0:
            return None

        current_item = self.message_list.item(current_row)
        if current_item is None:
            return None

        return current_item.data(QtCore.Qt.UserRole)

    def _report_visualizer_error(self, action: str, error: Exception) -> None:
        self._show_error(f"Failed to {action} message layout visualizer: {error}")

    def show_layout_visualizer(self) -> None:
        message_data = self._get_selected_message_data()
        if message_data is None:
            self._show_error("Select a message before opening the message layout visualizer.")
            return

        try:
            if self.layout_visualizer_window is None:
                self.layout_visualizer_window = MessageSignalLayoutWindow(self)

            self.layout_visualizer_window.set_message_data(message_data)
            self.layout_visualizer_window.show()
            self.layout_visualizer_window.raise_()
            self.layout_visualizer_window.activateWindow()
        except Exception as exc:
            self._report_visualizer_error("open", exc)

    def _refresh_layout_visualizer(self) -> None:
        if self.layout_visualizer_window is None:
            return

        try:
            self.layout_visualizer_window.set_message_data(self._get_selected_message_data())
        except Exception as exc:
            self._report_visualizer_error("refresh", exc)

    def _update_file_info(self):
        """Update the file information panel with current message/signal counts."""
        if not self.dbc_editor._modified_data:
            self.info_message_count.setText("Messages: —")
            self.info_signal_count.setText("Signals: —")
            return

        messages = self.dbc_editor._modified_data.get('messages', [])
        msg_count = len(messages)
        sig_count = sum(len(msg.get('signals', [])) for msg in messages)
        self.info_message_count.setText(f"Messages: {msg_count}")
        self.info_signal_count.setText(f"Signals: {sig_count}")

    def update_button_states(self):
        """Update the enabled state of buttons based on current state."""
        has_file = self.current_file_path is not None
        # Check if we have a DBC structure initialized (either loaded or newly created)
        has_data = self.dbc_editor._modified_data is not None
        has_messages = self.message_list.count() > 0
        has_selected_message = self.message_list.currentRow() >= 0
        has_signals = self.signal_list.count() > 0
        has_selected_signal = self.signal_list.currentRow() >= 0
        selected_message_row = self.message_list.currentRow()
        selected_signal_row = self.signal_list.currentRow()
        msg_count = self.message_list.count()
        sig_count = self.signal_list.count() if has_selected_message else 0
        
        # Force refresh of change detection
        has_changes = self.dbc_editor.has_changes()
        
        # Debug: Print button state information
        # print(f"Button states - has_file: {has_file}, has_data: {has_data}, has_changes: {has_changes}")
        # print(f"Current file: {self.current_file_path}")
        # print(f"Original data exists: {self.dbc_editor._original_data is not None}")
        # print(f"Modified data exists: {self.dbc_editor._modified_data is not None}")
        
        # Enable save button if we have data (file loaded or new file created)
        # This allows users to save the file as-is or make changes
        self.save_button.setEnabled(has_data)
        self.save_as_button.setEnabled(has_data)
        self.add_message_button.setEnabled(has_data)
        self.edit_message_button.setEnabled(has_data and has_selected_message)
        self.delete_message_button.setEnabled(has_data and has_selected_message)
        self.duplicate_message_button.setEnabled(has_data and has_selected_message)
        self.visualize_layout_button.setEnabled(has_data and has_selected_message)
        self.add_signal_button.setEnabled(has_data and has_selected_message)
        self.edit_signal_button.setEnabled(has_data and has_selected_signal)
        self.delete_signal_button.setEnabled(has_data and has_selected_signal)
        self.duplicate_signal_button.setEnabled(has_data and has_selected_signal)
        # Move buttons
        self.move_message_up_button.setEnabled(has_data and has_messages and has_selected_message and selected_message_row > 0)
        self.move_message_down_button.setEnabled(has_data and has_messages and has_selected_message and selected_message_row < (msg_count - 1))
        self.move_signal_up_button.setEnabled(has_data and has_selected_message and has_signals and has_selected_signal and selected_signal_row > 0)
        self.move_signal_down_button.setEnabled(has_data and has_selected_message and has_signals and has_selected_signal and selected_signal_row < (sig_count - 1))
        
        # Update changes label and button styling
        if has_changes:
            summary = self.dbc_editor.get_changes_summary()
            changes_text = []
            
            # Message changes
            if summary.get('added_messages'):
                changes_text.append(f"Msg+: {len(summary['added_messages'])}")
            if summary.get('deleted_messages'):
                changes_text.append(f"Msg-: {len(summary['deleted_messages'])}")
            if summary.get('modified_messages'):
                changes_text.append(f"Msg~: {len(summary['modified_messages'])}")
            
            # Signal changes
            if summary.get('added_signals'):
                changes_text.append(f"Sig+: {len(summary['added_signals'])}")
            if summary.get('deleted_signals'):
                changes_text.append(f"Sig-: {len(summary['deleted_signals'])}")
            if summary.get('modified_signals'):
                changes_text.append(f"Sig~: {len(summary['modified_signals'])}")
            
            if summary.get('error'):
                changes_text.append(f"Error: {summary['error']}")
            
            self.changes_label.setText(f"Changes: {', '.join(changes_text)}")
            self.changes_label.setStyleSheet("color: orange; font-weight: bold;")
            # Style save button to indicate changes
            self.save_button.setStyleSheet("background-color: #ff9800; color: white; font-weight: bold;")
        else:
            self.changes_label.setText("No changes")
            self.changes_label.setStyleSheet("color: green;")
            # Reset save button style
            self.save_button.setStyleSheet("")

        self._update_file_info()
        self._refresh_layout_visualizer()
    
    def new_dbc_file(self):
        """Create a new empty DBC file with error handling."""
        # Check if there are unsaved changes
        if self.dbc_editor.has_changes() and self.current_file_path:
            reply = QtWidgets.QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Do you want to create a new file anyway?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No
            )
            if reply == QtWidgets.QMessageBox.No:
                return
        
        try:
            self.status_label.setText("Creating new DBC file...")
            data = self.dbc_editor.create_new_dbc()
            self.current_file_path = None
            self.file_label.setText("New DBC file (not saved)")
            self.populate_message_list()
            self.status_label.setText("New DBC file created. Add messages to get started.")
            QtWidgets.QApplication.processEvents()
            self.update_button_states()
        except DBCEditorError as e:
            self._show_error(f"Failed to create new DBC file: {str(e)}")
        except Exception as e:
            self._show_error(f"Unexpected error: {str(e)}")

    def load_dbc_file(self):
        """Load a DBC file with error handling."""
        # Check if there are unsaved changes
        if self.dbc_editor.has_changes() and self.current_file_path:
            reply = QtWidgets.QMessageBox.question(
                self, "Unsaved Changes",
                "You have unsaved changes. Do you want to load a new file anyway?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No
            )
            if reply == QtWidgets.QMessageBox.No:
                return
        
        try:
            file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Load DBC File", "", "DBC Files (*.dbc);;All Files (*)"
            )
            if file_path:
                self.load_dbc_path(file_path)
        except Exception as e:
            self._show_error(f"Unexpected error: {str(e)}")

    def load_dbc_path(self, file_path: str) -> bool:
        """
        Load a DBC file directly (no file dialog). Intended for the Home screen.
        Returns True on success, False on failure.
        """
        try:
            if not file_path:
                self._show_error("No file path provided.")
                return False
            if not os.path.exists(file_path):
                self._show_error(f"DBC file not found:\n{file_path}")
                return False
            if not file_path.lower().endswith(".dbc"):
                self._show_error("Selected file must have .dbc extension.")
                return False

            self.status_label.setText("Loading DBC file...")
            QtWidgets.QApplication.processEvents()

            self.dbc_editor.load_dbc_file(file_path)
            self.current_file_path = file_path
            self.file_label.setText(f"File: {file_path}")
            self.populate_message_list()
            self.status_label.setText("DBC file loaded successfully")
            QtWidgets.QApplication.processEvents()
            self.update_button_states()

            # Clean up any existing backup files for the newly loaded file
            self.dbc_editor._cleanup_backup_file(file_path)

            self.dbcFileLoaded.emit(file_path)
            return True
        except DBCEditorError as e:
            self._show_error(f"Failed to load DBC file: {str(e)}")
            return False
        except Exception as e:
            self._show_error(f"Unexpected error: {str(e)}")
            return False

    def filter_messages(self, search_query="", filter_type="All"):
        """Filter messages based on search text and filter selection."""
        search_text = search_query.lower()
        
        for i in range(self.message_list.count()):
            item = self.message_list.item(i)
            msg_data = item.data(QtCore.Qt.UserRole)
            is_extended_frame = bool(msg_data.get('is_extended_frame', msg_data['frame_id'] > 0x7FF))
            
            # Check search text
            matches_search = (search_text in msg_data['name'].lower() or 
                            search_text in f"0x{msg_data['frame_id']:X}".lower())
            
            # Check filter type
            matches_filter = True
            if filter_type == 'Standard Frame':
                matches_filter = not is_extended_frame
            elif filter_type == 'Extended Frame':
                matches_filter = is_extended_frame
            
            item.setHidden(not (matches_search and matches_filter))

    def filter_signals(self, search_query="", filter_type="All"):
        """Filter signals based on search text."""
        search_text = search_query.lower()
        
        for i in range(self.signal_list.count()):
            item = self.signal_list.item(i)
            if item.flags() & QtCore.Qt.ItemIsSelectable:  # Only filter selectable items
                signal_name = item.text().split(' (')[0]  # Extract signal name
                item.setHidden(search_text not in signal_name.lower())

    def populate_message_list(self):
        """Populate the message list with current data."""
        self.message_list.clear()
        self.signal_list.clear()
        
        if not self.dbc_editor._modified_data:
            return
        
        for msg in self.dbc_editor._modified_data['messages']:
            # Create more informative display text
            frame_type = "Extended" if msg.get('is_extended_frame', msg['frame_id'] > 0x7FF) else "Standard"
            display_text = f"{msg['name']} (ID: 0x{msg['frame_id']:X}, {frame_type})"
            item = QtWidgets.QListWidgetItem(display_text)
            item.setData(QtCore.Qt.UserRole, msg)
            self.message_list.addItem(item)
    
    def on_message_selected(self, item):
        """Handle message selection."""
        message_data = item.data(QtCore.Qt.UserRole)
        self._update_mux_filter(message_data)
        self.populate_signal_list(message_data)
        self.update_button_states()
    
    def on_signal_selected(self, item):
        """Handle signal selection."""
        self.update_button_states()
    
    def _update_mux_filter(self, message_data: Dict[str, Any]) -> None:
        """Show or hide the mux filter combo based on the selected message."""
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
            self.mux_filter_row.hide()
        self.mux_filter_combo.blockSignals(False)

    def _on_mux_filter_changed(self) -> None:
        """Re-populate the signal list when the mux filter selection changes."""
        message_data = self._get_selected_message_data()
        if message_data is not None:
            self.populate_signal_list(message_data)

    def populate_signal_list(self, message_data):
        """Populate the signal list for the selected message."""
        self.signal_list.clear()

        all_signals = message_data.get('signals', [])
        if not all_signals:
            item = QtWidgets.QListWidgetItem("No signals in this message")
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsSelectable)
            self.signal_list.addItem(item)
            return

        selected_mux_id = self.mux_filter_combo.currentData() if self.mux_filter_combo.isVisible() else None
        signals = filter_signals_by_mux_id(all_signals, selected_mux_id)

        for sig in signals:
            mux_tag = format_mux_indicator(sig)
            signed_text = "S" if sig.get('is_signed', False) else "U"
            unit_text = f", {sig['unit']}" if sig.get('unit') else ""
            prefix = f"{mux_tag} " if mux_tag else ""
            display_text = f"{prefix}{sig['name']} ({sig['start_bit']}:{sig['length']}, {signed_text}, Scale: {sig['scale']}{unit_text})"
            item = QtWidgets.QListWidgetItem(display_text)
            item.setData(QtCore.Qt.UserRole, sig)
            self.signal_list.addItem(item)
    
    def add_message(self):
        """Add a new message with error handling."""
        dialog = MessageEditDialog(
            self,
            existing_senders=self._get_existing_message_senders(),
            existing_receivers=self._get_existing_signal_receivers(),
            existing_send_types=self._get_existing_send_types(),
            existing_bus_names=self._get_existing_bus_names(),
            existing_protocols=self._get_existing_protocols(),
        )
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            try:
                message_data = dialog.get_data()
                self.dbc_editor.add_message(message_data)
                self.populate_message_list()
                self.status_label.setText("Message added successfully")
            except ValueError as e:
                self._show_error(f"Validation Error: {str(e)}")
                self.status_label.setText("Validation error")
            except DBCEditorError as e:
                self._show_error(f"Failed to add message: {str(e)}")
                self.status_label.setText("Failed to add message")
            except Exception as e:
                self._show_error(f"Unexpected error: {str(e)}")
                self.status_label.setText("Unexpected error")
        QtWidgets.QApplication.processEvents()
        self.update_button_states()

    def edit_message(self):
        """Edit the selected message with error handling."""
        current_row = self.message_list.currentRow()
        if current_row < 0:
            return
        message_data = self.message_list.item(current_row).data(QtCore.Qt.UserRole)
        dialog = MessageEditDialog(
            self,
            message_data,
            existing_senders=self._get_existing_message_senders(),
            existing_receivers=self._get_existing_signal_receivers(),
            existing_send_types=self._get_existing_send_types(),
            existing_bus_names=self._get_existing_bus_names(),
            existing_protocols=self._get_existing_protocols(),
        )
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            try:
                new_data = dialog.get_data()
                self.dbc_editor.update_message(current_row, new_data)
                self.populate_message_list()
                self.status_label.setText("Message updated successfully")
                self.update_button_states()
            except ValueError as e:
                self._show_error(f"Validation Error: {str(e)}")
                self.status_label.setText("Validation error")
            except DBCEditorError as e:
                self._show_error(f"Failed to update message: {str(e)}")
                self.status_label.setText("Failed to update message")
            except Exception as e:
                self._show_error(f"Unexpected error: {str(e)}")
                self.status_label.setText("Unexpected error")
        self.update_button_states()

    def delete_message(self):
        """Delete the selected message with error handling."""
        current_row = self.message_list.currentRow()
        if current_row < 0:
            return
        message_name = self.message_list.item(current_row).data(QtCore.Qt.UserRole)['name']
        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Delete", 
            f"Are you sure you want to delete message '{message_name}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if reply == QtWidgets.QMessageBox.Yes:
            try:
                self.dbc_editor.delete_message(current_row)
                self.populate_message_list()
                self.signal_list.clear()
                self.status_label.setText("Message deleted successfully")
                self.update_button_states()
            except DBCEditorError as e:
                self._show_error(f"Failed to delete message: {str(e)}")
                self.status_label.setText("Failed to delete message")
            except Exception as e:
                self._show_error(f"Unexpected error: {str(e)}")
                self.status_label.setText("Unexpected error")

    def add_signal(self):
        """Add a new signal to the selected message with error handling."""
        current_row = self.message_list.currentRow()
        if current_row < 0:
            return
        current_message = self.message_list.item(current_row).data(QtCore.Qt.UserRole)
        dialog = SignalEditDialog(
            self,
            existing_receivers=self._get_existing_signal_receivers(),
            message_senders=current_message.get('senders', []),
            message_signals=current_message.get('signals', []),
        )
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            try:
                signal_data = dialog.get_data()
                self.dbc_editor.add_signal(current_row, signal_data)
                self.populate_message_list()
                self.message_list.setCurrentRow(current_row)
                current_message = self.message_list.item(current_row).data(QtCore.Qt.UserRole)
                self._update_mux_filter(current_message)
                self.populate_signal_list(current_message)
                self._refresh_layout_visualizer()
                self.status_label.setText("Signal added successfully")
                self.update_button_states()
            except ValueError as e:
                self._show_error(f"Validation Error: {str(e)}")
                self.status_label.setText("Validation error")
            except DBCEditorError as e:
                self._show_error(f"Failed to add signal: {str(e)}")
                self.status_label.setText("Failed to add signal")
            except Exception as e:
                self._show_error(f"Unexpected error: {str(e)}")
                self.status_label.setText("Unexpected error")
        self.update_button_states()

    def edit_signal(self):
        """Edit the selected signal with error handling."""
        message_row = self.message_list.currentRow()
        signal_row = self.signal_list.currentRow()
        if message_row < 0 or signal_row < 0:
            return
        signal_data = self.signal_list.item(signal_row).data(QtCore.Qt.UserRole)
        current_message = self.message_list.item(message_row).data(QtCore.Qt.UserRole)
        dialog = SignalEditDialog(
            self,
            signal_data,
            existing_receivers=self._get_existing_signal_receivers(),
            message_senders=current_message.get('senders', []),
            message_signals=current_message.get('signals', []),
        )
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            try:
                new_data = dialog.get_data()
                self.dbc_editor.update_signal(message_row, signal_row, new_data)
                self.populate_message_list()
                self.message_list.setCurrentRow(message_row)
                current_message = self.message_list.item(message_row).data(QtCore.Qt.UserRole)
                self._update_mux_filter(current_message)
                self.populate_signal_list(current_message)
                self._refresh_layout_visualizer()
                self.status_label.setText("Signal updated successfully")
                self.update_button_states()
            except ValueError as e:
                self._show_error(f"Validation Error: {str(e)}")
                self.status_label.setText("Validation error")
            except DBCEditorError as e:
                self._show_error(f"Failed to update signal: {str(e)}")
                self.status_label.setText("Failed to update signal")
            except Exception as e:
                self._show_error(f"Unexpected error: {str(e)}")
                self.status_label.setText("Unexpected error")
        self.update_button_states()

    def delete_signal(self):
        """Delete the selected signal with error handling."""
        message_row = self.message_list.currentRow()
        signal_row = self.signal_list.currentRow()
        if message_row < 0 or signal_row < 0:
            return
        signal_name = self.signal_list.item(signal_row).data(QtCore.Qt.UserRole)['name']
        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Delete", 
            f"Are you sure you want to delete signal '{signal_name}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if reply == QtWidgets.QMessageBox.Yes:
            try:
                self.dbc_editor.delete_signal(message_row, signal_row)
                self.populate_message_list()
                self.message_list.setCurrentRow(message_row)
                current_message = self.message_list.item(message_row).data(QtCore.Qt.UserRole)
                self._update_mux_filter(current_message)
                self.populate_signal_list(current_message)
                self._refresh_layout_visualizer()
                self.status_label.setText("Signal deleted successfully")
                self.update_button_states()
            except DBCEditorError as e:
                self._show_error(f"Failed to delete signal: {str(e)}")
                self.status_label.setText("Failed to delete signal")
            except Exception as e:
                self._show_error(f"Unexpected error: {str(e)}")
                self.status_label.setText("Unexpected error")
    
    def duplicate_signal(self):
        """Duplicate the selected signal."""
        message_row = self.message_list.currentRow()
        signal_row = self.signal_list.currentRow()
        if message_row < 0 or signal_row < 0:
            return
        try:
            new_sig_idx = self.dbc_editor.duplicate_signal(message_row, signal_row)
            self.populate_message_list()
            self.message_list.setCurrentRow(message_row)
            current_message = self.message_list.item(message_row).data(QtCore.Qt.UserRole)
            self._update_mux_filter(current_message)
            self.populate_signal_list(current_message)
            self.signal_list.setCurrentRow(new_sig_idx)
            self._refresh_layout_visualizer()
            self.status_label.setText("Signal duplicated successfully")
            self.update_button_states()
        except DBCEditorError as e:
            self._show_error(f"Failed to duplicate signal: {str(e)}")
            self.status_label.setText("Failed to duplicate signal")
        except Exception as e:
            self._show_error(f"Unexpected error: {str(e)}")
            self.status_label.setText("Unexpected error")
    
    def duplicate_message(self):
        """Duplicate the selected message."""
        current_row = self.message_list.currentRow()
        if current_row < 0:
            return
        try:
            new_idx = self.dbc_editor.duplicate_message(current_row)
            self.populate_message_list()
            # Select the newly created message
            self.message_list.setCurrentRow(new_idx)
            new_msg = self.message_list.item(new_idx).data(QtCore.Qt.UserRole)
            self.populate_signal_list(new_msg)
            self.status_label.setText("Message duplicated successfully")
            self.update_button_states()
        except DBCEditorError as e:
            self._show_error(f"Failed to duplicate message: {str(e)}")
            self.status_label.setText("Failed to duplicate message")
        except Exception as e:
            self._show_error(f"Unexpected error: {str(e)}")
            self.status_label.setText("Unexpected error")
    
    def move_selected_message_up(self):
        """Move the selected message up."""
        row = self.message_list.currentRow()
        if row <= 0:
            return
        try:
            new_idx = self.dbc_editor.move_message_up(row)
            self.populate_message_list()
            self.message_list.setCurrentRow(new_idx)
            current_message = self.message_list.item(new_idx).data(QtCore.Qt.UserRole)
            self.populate_signal_list(current_message)
            self.status_label.setText("Message moved up")
            self.update_button_states()
        except DBCEditorError as e:
            self._show_error(f"Failed to move message: {str(e)}")
        except Exception as e:
            self._show_error(f"Unexpected error: {str(e)}")
    
    def move_selected_message_down(self):
        """Move the selected message down."""
        row = self.message_list.currentRow()
        if row < 0 or row >= self.message_list.count() - 1:
            return
        try:
            new_idx = self.dbc_editor.move_message_down(row)
            self.populate_message_list()
            self.message_list.setCurrentRow(new_idx)
            current_message = self.message_list.item(new_idx).data(QtCore.Qt.UserRole)
            self.populate_signal_list(current_message)
            self.status_label.setText("Message moved down")
            self.update_button_states()
        except DBCEditorError as e:
            self._show_error(f"Failed to move message: {str(e)}")
        except Exception as e:
            self._show_error(f"Unexpected error: {str(e)}")
    
    def move_selected_signal_up(self):
        """Move the selected signal up within the current message."""
        msg_row = self.message_list.currentRow()
        sig_row = self.signal_list.currentRow()
        if msg_row < 0 or sig_row <= 0:
            return
        try:
            new_sig_idx = self.dbc_editor.move_signal_up(msg_row, sig_row)
            # Refresh lists and selection
            self.populate_message_list()
            self.message_list.setCurrentRow(msg_row)
            current_message = self.message_list.item(msg_row).data(QtCore.Qt.UserRole)
            self.populate_signal_list(current_message)
            self.signal_list.setCurrentRow(new_sig_idx)
            self.status_label.setText("Signal moved up")
            self.update_button_states()
        except DBCEditorError as e:
            self._show_error(f"Failed to move signal: {str(e)}")
        except Exception as e:
            self._show_error(f"Unexpected error: {str(e)}")
    
    def move_selected_signal_down(self):
        """Move the selected signal down within the current message."""
        msg_row = self.message_list.currentRow()
        sig_row = self.signal_list.currentRow()
        if msg_row < 0 or sig_row < 0 or sig_row >= self.signal_list.count() - 1:
            return
        try:
            new_sig_idx = self.dbc_editor.move_signal_down(msg_row, sig_row)
            self.populate_message_list()
            self.message_list.setCurrentRow(msg_row)
            current_message = self.message_list.item(msg_row).data(QtCore.Qt.UserRole)
            self.populate_signal_list(current_message)
            self.signal_list.setCurrentRow(new_sig_idx)
            self.status_label.setText("Signal moved down")
            self.update_button_states()
        except DBCEditorError as e:
            self._show_error(f"Failed to move signal: {str(e)}")
        except Exception as e:
            self._show_error(f"Unexpected error: {str(e)}")

    def save_changes(self):
        """Save changes to the current file with error handling.

        If there are pending changes, emit *saveReviewRequested* so the
        MainWindow can navigate to the Compare tab for review.  When there
        are no changes the file is saved directly.
        """
        if not self.current_file_path:
            self.save_as()
            return

        try:
            validate_dbc_data(self.dbc_editor._modified_data)
        except ValueError as exc:
            self._show_error(f"{str(exc)}")
            return

        if self.dbc_editor.has_changes():
            self.saveReviewRequested.emit(
                self.dbc_editor._original_data,
                self.dbc_editor._modified_data,
                self.current_file_path,
            )
            return

        self.perform_save(self.current_file_path)

    def perform_save(self, file_path: str):
        """Execute the actual save (called after review confirmation or when no changes)."""
        try:
            self.status_label.setText("Saving changes...")
            QtWidgets.QApplication.processEvents()
            self.dbc_editor.save_dbc_file(file_path)
            self.current_file_path = file_path
            self.file_label.setText(f"File: {file_path}")
            self.status_label.setText("Changes saved successfully")
            self.update_button_states()
            QtWidgets.QMessageBox.information(self, "Success", f"Changes saved successfully to:\n{file_path}")
        except DBCEditorError as e:
            self._show_error(f"Failed to save changes: {str(e)}")
        except Exception as e:
            self._show_error(f"Unexpected error: {str(e)}")

    def perform_text_save(self, file_path: str, dbc_text: str):
        """Save raw DBC text and reload the editor from the persisted file."""
        try:
            self.status_label.setText("Saving edited comparison text...")
            QtWidgets.QApplication.processEvents()
            self.dbc_editor.save_dbc_text(dbc_text, file_path)
            self.current_file_path = file_path
            self.file_label.setText(f"File: {file_path}")
            self.populate_message_list()
            self.status_label.setText("Changes saved successfully")
            self.update_button_states()
            QtWidgets.QMessageBox.information(self, "Success", f"Changes saved successfully to:\n{file_path}")
        except DBCEditorError as e:
            self._show_error(f"Failed to save changes: {str(e)}")
        except Exception as e:
            self._show_error(f"Unexpected error: {str(e)}")

    def save_as(self):
        """Save changes to a new file with error handling."""
        try:
            validate_dbc_data(self.dbc_editor._modified_data)
        except ValueError as exc:
            self._show_error(f"{str(exc)}")
            return

        try:
            file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Save DBC File As", "", "DBC Files (*.dbc);;All Files (*)"
            )
            if file_path:
                # Ensure .dbc extension
                if not file_path.lower().endswith('.dbc'):
                    file_path += '.dbc'
                
                self.status_label.setText("Saving file...")
                QtWidgets.QApplication.processEvents()
                self.dbc_editor.save_dbc_file(file_path)
                self.current_file_path = file_path
                self.file_label.setText(f"File: {file_path}")
                self.status_label.setText("File saved successfully")
                self.update_button_states()
                QtWidgets.QMessageBox.information(self, "Success", f"File saved successfully to:\n{file_path}")
        except DBCEditorError as e:
            self._show_error(f"Failed to save file: {str(e)}")
        except Exception as e:
            self._show_error(f"Unexpected error: {str(e)}")

    def _show_error(self, message):
        QtWidgets.QMessageBox.critical(self, "Error", message)
        self.status_label.setText(f"<font color='red'>{message}</font>")
