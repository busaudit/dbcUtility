#!/usr/bin/env python3

"""
DBC Editor UI Component
Provides the user interface for editing DBC files.
"""

import os
import sys
from PyQt5 import QtWidgets, QtCore, QtGui
from typing import Dict, List, Optional, Any
import json

from dbc_editor import DBCEditor, DBCEditorError
from search_module import UnifiedSearchWidget

from resource_utils import get_resource_path

class MessageEditDialog(QtWidgets.QDialog):
    """Enhanced dialog for editing message properties."""
    
    def __init__(self, parent=None, message_data=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Message")
        self.setModal(True)
        self.resize(500, 600)
        
        self.message_data = message_data or {}
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
        basic_layout = QtWidgets.QFormLayout()
        
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("Enter message name")
        self.name_edit.setToolTip("Name of the CAN message")
        
        self.frame_id_edit = QtWidgets.QSpinBox()
        self.frame_id_edit.setRange(0, 0x1FFFFFFF)
        self.frame_id_edit.setPrefix("0x")
        self.frame_id_edit.setDisplayIntegerBase(16)
        self.frame_id_edit.setToolTip("CAN frame ID (0x000 to 0x1FFFFFFF)")
        
        self.length_edit = QtWidgets.QSpinBox()
        self.length_edit.setRange(0, 8)
        self.length_edit.setToolTip("Message length in bytes (0-8)")
        
        basic_layout.addRow("Name:", self.name_edit)
        basic_layout.addRow("Frame ID:", self.frame_id_edit)
        basic_layout.addRow("Length (bytes):", self.length_edit)
        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)
        
        # Network Properties Group
        network_group = QtWidgets.QGroupBox("Network Properties")
        network_layout = QtWidgets.QFormLayout()
        
        self.senders_edit = QtWidgets.QLineEdit()
        self.senders_edit.setPlaceholderText("Comma-separated list of sending nodes")
        self.senders_edit.setToolTip("Nodes that send this message")
        
        # Frame type selection
        self.frame_type_combo = QtWidgets.QComboBox()
        self.frame_type_combo.addItems(['Standard Frame (11-bit)', 'Extended Frame (29-bit)'])
        self.frame_type_combo.setToolTip("CAN frame type")
        
        network_layout.addRow("Senders:", self.senders_edit)
        network_layout.addRow("Frame Type:", self.frame_type_combo)
        network_group.setLayout(network_layout)
        scroll_layout.addWidget(network_group)
        
        # Advanced Properties Group
        advanced_group = QtWidgets.QGroupBox("Advanced Properties")
        advanced_layout = QtWidgets.QFormLayout()
        
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
        
        advanced_layout.addRow("Cycle Time:", self.cycle_time_edit)
        advanced_layout.addRow("Message Type:", self.message_type_combo)
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
        self.frame_id_edit.setValue(0)
        self.length_edit.setValue(8)
        self.senders_edit.clear()
        self.frame_type_combo.setCurrentIndex(0)  # Standard Frame
        self.cycle_time_edit.setValue(0)
        self.message_type_combo.setCurrentIndex(0)  # Normal
        self.comments_edit.clear()

    def load_data(self):
        """Load existing message data into the form."""
        if self.message_data:
            self.name_edit.setText(self.message_data.get('name', ''))
            self.frame_id_edit.setValue(self.message_data.get('frame_id', 0))
            self.length_edit.setValue(self.message_data.get('length', 8))
            self.senders_edit.setText(', '.join(self.message_data.get('senders', [])))
            self.comments_edit.setPlainText(self.message_data.get('comments', ''))
            
            # Set frame type based on frame_id
            frame_id = self.message_data.get('frame_id', 0)
            if frame_id > 0x7FF:
                self.frame_type_combo.setCurrentIndex(1)  # Extended Frame
            else:
                self.frame_type_combo.setCurrentIndex(0)  # Standard Frame
    
    def get_data(self) -> Dict[str, Any]:
        """Get the form data as a dictionary."""
        name = self.name_edit.text().strip()
        if not name:
            raise ValueError("Message name is required")
        
        # Determine frame_id based on frame type selection
        frame_id = self.frame_id_edit.value()
        if self.frame_type_combo.currentIndex() == 1:  # Extended Frame
            if frame_id <= 0x7FF:
                frame_id = 0x800  # Minimum extended frame ID
        
        return {
            'name': name,
            'frame_id': frame_id,
            'length': self.length_edit.value(),
            'senders': [s.strip() for s in self.senders_edit.text().split(',') if s.strip()],
            'comments': self.comments_edit.toPlainText().strip(),
            'cycle_time': self.cycle_time_edit.value() if self.cycle_time_edit.value() > 0 else None,
            'message_type': self.message_type_combo.currentText(),
            'signals': self.message_data.get('signals', [])
        }

class SignalEditDialog(QtWidgets.QDialog):
    """Enhanced dialog for editing signal properties."""
    
    def __init__(self, parent=None, signal_data=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Signal")
        self.setModal(True)
        self.resize(600, 700)
        
        self.signal_data = signal_data or {}
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
        basic_layout = QtWidgets.QFormLayout()
        
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("Enter signal name")
        
        self.start_bit_edit = QtWidgets.QSpinBox()
        self.start_bit_edit.setRange(0, 63)
        self.start_bit_edit.setToolTip("Starting bit position (0-63)")
        
        self.length_edit = QtWidgets.QSpinBox()
        self.length_edit.setRange(1, 64)
        self.length_edit.setToolTip("Number of bits (1-64)")
        
        basic_layout.addRow("Name:", self.name_edit)
        basic_layout.addRow("Start Bit:", self.start_bit_edit)
        basic_layout.addRow("Length (bits):", self.length_edit)
        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)
        
        # Data Properties Group
        data_group = QtWidgets.QGroupBox("Data Properties")
        data_layout = QtWidgets.QFormLayout()
        
        self.byte_order_combo = QtWidgets.QComboBox()
        self.byte_order_combo.addItems(['little_endian', 'big_endian'])
        self.byte_order_combo.setToolTip("Byte order for multi-byte signals")
        
        self.is_signed_check = QtWidgets.QCheckBox("Signed")
        self.is_signed_check.setToolTip("Check if signal is signed")
        
        self.unit_edit = QtWidgets.QLineEdit()
        self.unit_edit.setPlaceholderText("e.g., rpm, km/h, deg")
        self.unit_edit.setToolTip("Physical unit of the signal")
        
        data_layout.addRow("Byte Order:", self.byte_order_combo)
        data_layout.addRow("", self.is_signed_check)
        data_layout.addRow("Unit:", self.unit_edit)
        data_group.setLayout(data_layout)
        scroll_layout.addWidget(data_group)
        
        # Scaling Properties Group
        scaling_group = QtWidgets.QGroupBox("Scaling Properties")
        scaling_layout = QtWidgets.QFormLayout()
        
        self.scale_edit = QtWidgets.QDoubleSpinBox()
        self.scale_edit.setRange(-1000000, 1000000)
        self.scale_edit.setDecimals(6)
        self.scale_edit.setValue(1.0)
        self.scale_edit.setToolTip("Scale factor: physical_value = raw_value * scale + offset")
        
        self.offset_edit = QtWidgets.QDoubleSpinBox()
        self.offset_edit.setRange(-1000000, 1000000)
        self.offset_edit.setDecimals(6)
        self.offset_edit.setToolTip("Offset value")
        
        scaling_layout.addRow("Scale:", self.scale_edit)
        scaling_layout.addRow("Offset:", self.offset_edit)
        scaling_group.setLayout(scaling_layout)
        scroll_layout.addWidget(scaling_group)
        
        # Range Properties Group
        range_group = QtWidgets.QGroupBox("Range Properties")
        range_layout = QtWidgets.QFormLayout()
        
        self.minimum_edit = QtWidgets.QDoubleSpinBox()
        self.minimum_edit.setRange(-1000000, 1000000)
        self.minimum_edit.setDecimals(6)
        self.minimum_edit.setToolTip("Minimum physical value")
        
        self.maximum_edit = QtWidgets.QDoubleSpinBox()
        self.maximum_edit.setRange(-1000000, 1000000)
        self.maximum_edit.setDecimals(6)
        self.maximum_edit.setToolTip("Maximum physical value")
        
        range_layout.addRow("Minimum:", self.minimum_edit)
        range_layout.addRow("Maximum:", self.maximum_edit)
        range_group.setLayout(range_layout)
        scroll_layout.addWidget(range_group)
        
        # Network Properties Group
        network_group = QtWidgets.QGroupBox("Network Properties")
        network_layout = QtWidgets.QFormLayout()
        
        self.receivers_edit = QtWidgets.QLineEdit()
        self.receivers_edit.setPlaceholderText("Comma-separated list of receiving nodes")
        self.receivers_edit.setToolTip("Nodes that receive this signal")
        
        network_layout.addRow("Receivers:", self.receivers_edit)
        network_group.setLayout(network_layout)
        scroll_layout.addWidget(network_group)
        
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
            self.receivers_edit.setText(', '.join(self.signal_data.get('receivers', [])))
            self.comments_edit.setPlainText(self.signal_data.get('comments', ''))
    
    def reset_to_defaults(self):
        """Reset all fields to default values."""
        self.name_edit.clear()
        self.start_bit_edit.setValue(0)
        self.length_edit.setValue(1)
        self.byte_order_combo.setCurrentIndex(0)  # little_endian
        self.is_signed_check.setChecked(False)
        self.scale_edit.setValue(1.0)
        self.offset_edit.setValue(0.0)
        self.minimum_edit.setValue(0.0)
        self.maximum_edit.setValue(0.0)
        self.unit_edit.clear()
        self.receivers_edit.clear()
        self.comments_edit.clear()

    def get_data(self) -> Dict[str, Any]:
        """Get the form data as a dictionary."""
        name = self.name_edit.text().strip()
        if not name:
            raise ValueError("Signal name is required")
        
        # Handle minimum and maximum values
        minimum_val = self.minimum_edit.value()
        maximum_val = self.maximum_edit.value()
        
        # Note: The spinboxes will always return numeric values (0.0 if not set)
        # If you need to distinguish between "not set" and "explicitly set to 0",
        # you would need to add additional UI elements (like checkboxes) to track this
        
        return {
            'name': name,
            'start_bit': self.start_bit_edit.value(),
            'length': self.length_edit.value(),
            'byte_order': self.byte_order_combo.currentText(),
            'is_signed': self.is_signed_check.isChecked(),
            'scale': self.scale_edit.value(),
            'offset': self.offset_edit.value(),
            'minimum': minimum_val,
            'maximum': maximum_val,
            'unit': self.unit_edit.text().strip(),
            'receivers': [r.strip() for r in self.receivers_edit.text().split(',') if r.strip()],
            'comments': self.comments_edit.toPlainText().strip()
        }

class DBCEditorWidget(QtWidgets.QWidget):
    """Main DBC editor widget with error handling and improved readability."""
    dbcFileLoaded = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dbc_editor = DBCEditor()
        self.current_file_path = None
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
            QLineEdit, QSpinBox, QComboBox {
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
        file_layout = QtWidgets.QHBoxLayout()
        
        self.file_label = QtWidgets.QLabel("No file loaded")
        self.new_button = QtWidgets.QPushButton("New DBC File")
        self.load_button = QtWidgets.QPushButton("Load DBC File")
        self.save_button = QtWidgets.QPushButton("Save Changes")
        self.save_as_button = QtWidgets.QPushButton("Save As...")
        
        # Set button icons
        self._set_button_icon(self.new_button, "icons/add.ico")
        self._set_button_icon(self.load_button, "icons/load.ico")
        self._set_button_icon(self.save_button, "icons/save.ico")
        self._set_button_icon(self.save_as_button, "icons/save_as.ico")
        
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
        
        file_group.setLayout(file_layout)
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
        
        # Set button icons
        self._set_button_icon(self.add_message_button, "icons/add.ico")
        self._set_button_icon(self.edit_message_button, "icons/edit.ico")
        self._set_button_icon(self.delete_message_button, "icons/delete.ico")
        
        self.add_message_button.clicked.connect(self.add_message)
        self.edit_message_button.clicked.connect(self.edit_message)
        self.delete_message_button.clicked.connect(self.delete_message)
        self.duplicate_message_button.clicked.connect(self.duplicate_message)
        
        message_buttons_layout.addWidget(self.add_message_button)
        message_buttons_layout.addWidget(self.edit_message_button)
        message_buttons_layout.addWidget(self.delete_message_button)
        message_buttons_layout.addWidget(self.duplicate_message_button)
        message_buttons_layout.addStretch()
        
        messages_layout.addLayout(message_buttons_layout)
        
        # Message list with move controls
        message_list_row = QtWidgets.QHBoxLayout()
        message_move_col = QtWidgets.QVBoxLayout()
        self.move_message_up_button = QtWidgets.QPushButton("↑")
        self.move_message_down_button = QtWidgets.QPushButton("↓")
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
        
        # Signal buttons
        signal_buttons_layout = QtWidgets.QHBoxLayout()
        self.add_signal_button = QtWidgets.QPushButton("Add Signal")
        self.edit_signal_button = QtWidgets.QPushButton("Edit Signal")
        self.delete_signal_button = QtWidgets.QPushButton("Delete Signal")
        self.duplicate_signal_button = QtWidgets.QPushButton("Duplicate")
        
        # Set button icons
        self._set_button_icon(self.add_signal_button, "icons/add.ico")
        self._set_button_icon(self.edit_signal_button, "icons/edit.ico")
        self._set_button_icon(self.delete_signal_button, "icons/delete.ico")
        
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
        self.move_signal_up_button = QtWidgets.QPushButton("↑")
        self.move_signal_down_button = QtWidgets.QPushButton("↓")
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

    def _set_button_icon(self, button, icon_path):
        """Set icon for a button if the icon file exists."""
        try:
            full_icon_path = get_resource_path(icon_path)
            if os.path.exists(full_icon_path):
                icon = QtGui.QIcon(full_icon_path)
                button.setIcon(icon)
                # Set icon size
                button.setIconSize(QtCore.QSize(16, 16))
        except Exception as e:
            print(f"Could not load icon {icon_path}: {e}")

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
        print(f"Button states - has_file: {has_file}, has_data: {has_data}, has_changes: {has_changes}")
        print(f"Current file: {self.current_file_path}")
        print(f"Original data exists: {self.dbc_editor._original_data is not None}")
        print(f"Modified data exists: {self.dbc_editor._modified_data is not None}")
        
        # Enable save button if we have data (file loaded or new file created)
        # This allows users to save the file as-is or make changes
        self.save_button.setEnabled(has_data)
        self.save_as_button.setEnabled(has_data)
        self.add_message_button.setEnabled(has_data)
        self.edit_message_button.setEnabled(has_data and has_selected_message)
        self.delete_message_button.setEnabled(has_data and has_selected_message)
        self.duplicate_message_button.setEnabled(has_data and has_selected_message)
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
            
            # Check search text
            matches_search = (search_text in msg_data['name'].lower() or 
                            search_text in f"0x{msg_data['frame_id']:X}".lower())
            
            # Check filter type
            matches_filter = True
            if filter_type == 'Standard Frame':
                matches_filter = msg_data['frame_id'] <= 0x7FF
            elif filter_type == 'Extended Frame':
                matches_filter = msg_data['frame_id'] > 0x7FF
            
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
            frame_type = "Extended" if msg['frame_id'] > 0x7FF else "Standard"
            display_text = f"{msg['name']} (ID: 0x{msg['frame_id']:X}, {frame_type})"
            item = QtWidgets.QListWidgetItem(display_text)
            item.setData(QtCore.Qt.UserRole, msg)
            self.message_list.addItem(item)
    
    def on_message_selected(self, item):
        """Handle message selection."""
        message_data = item.data(QtCore.Qt.UserRole)
        self.populate_signal_list(message_data)
        self.update_button_states()
    
    def on_signal_selected(self, item):
        """Handle signal selection."""
        self.update_button_states()
    
    def populate_signal_list(self, message_data):
        """Populate the signal list for the selected message."""
        self.signal_list.clear()
        
        signals = message_data.get('signals', [])
        if not signals:
            item = QtWidgets.QListWidgetItem("No signals in this message")
            item.setFlags(item.flags() & ~QtCore.Qt.ItemIsSelectable)
            self.signal_list.addItem(item)
            return
        
        for sig in signals:
            # Create a more informative display string
            signed_text = "S" if sig.get('is_signed', False) else "U"
            unit_text = f", {sig['unit']}" if sig.get('unit') else ""
            display_text = f"{sig['name']} ({sig['start_bit']}:{sig['length']}, {signed_text}, Scale: {sig['scale']}{unit_text})"
            item = QtWidgets.QListWidgetItem(display_text)
            item.setData(QtCore.Qt.UserRole, sig)
            self.signal_list.addItem(item)
    
    def add_message(self):
        """Add a new message with error handling."""
        dialog = MessageEditDialog(self)
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
        dialog = MessageEditDialog(self, message_data)
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
        dialog = SignalEditDialog(self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            try:
                signal_data = dialog.get_data()
                self.dbc_editor.add_signal(current_row, signal_data)
                self.populate_message_list()
                self.message_list.setCurrentRow(current_row)
                current_message = self.message_list.item(current_row).data(QtCore.Qt.UserRole)
                self.populate_signal_list(current_message)
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
        dialog = SignalEditDialog(self, signal_data)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            try:
                new_data = dialog.get_data()
                self.dbc_editor.update_signal(message_row, signal_row, new_data)
                self.populate_message_list()
                self.message_list.setCurrentRow(message_row)
                current_message = self.message_list.item(message_row).data(QtCore.Qt.UserRole)
                self.populate_signal_list(current_message)
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
                self.populate_signal_list(current_message)
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
            self.populate_signal_list(current_message)
            # Select the newly created signal
            self.signal_list.setCurrentRow(new_sig_idx)
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
        """Save changes to the current file with error handling."""
        if not self.current_file_path:
            # If no file path, prompt for save as
            self.save_as()
            return
        try:
            self.status_label.setText("Saving changes...")
            QtWidgets.QApplication.processEvents()
            self.dbc_editor.save_dbc_file(self.current_file_path)
            self.file_label.setText(f"File: {self.current_file_path}")
            self.status_label.setText("Changes saved successfully")
            self.update_button_states()
            QtWidgets.QMessageBox.information(self, "Success", f"Changes saved successfully to:\n{self.current_file_path}")
        except DBCEditorError as e:
            self._show_error(f"Failed to save changes: {str(e)}")
        except Exception as e:
            self._show_error(f"Unexpected error: {str(e)}")

    def save_as(self):
        """Save changes to a new file with error handling."""
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