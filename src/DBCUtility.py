#!/usr/bin/env python3

"""
DBC Utility - CAN Database Editor
Copyright (C) 2025 Abhijith Purohit

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

Author: Abhijith Purohit
Date: 15, July - 2025

Description:
    PyQt5 GUI to View and Edit DBC files.

Version: Read from pyproject.toml (see get_version() function)

Features:
    1. User can view and edit the DBC file.
    2. Helps Search signals for ease of access
    3. Able to edit both Messages and Signals.
    4. TODO: Add ability to view CAN dumps ?

"""

import sys
import os
import re
from pathlib import Path

from resource_utils import get_resource_path

def _clean_comment_text(comment_text: object) -> str:
    """
    Clean comment text by removing:
    - 'None:' prefix (if present)
    - Curly braces '{...}' only when they wrap the entire string
    - Single quotes '...' only when they wrap the entire string
    """
    if not comment_text:
        return ""

    cleaned = str(comment_text).strip()

    if cleaned.startswith("None:"):
        cleaned = cleaned[5:].strip()

    if cleaned.startswith("{") and cleaned.endswith("}"):
        cleaned = cleaned[1:-1].strip()

    # Sometimes 'None:' appears inside the braces wrapper, so run it again after stripping.
    if cleaned.startswith("None:"):
        cleaned = cleaned[5:].strip()

    if cleaned.startswith("'") and cleaned.endswith("'"):
        cleaned = cleaned[1:-1].strip()

    return cleaned

def show_import_error(pkg):
    try:
        from PyQt5.QtWidgets import QMessageBox, QApplication
        app = QApplication(sys.argv)
        QMessageBox.critical(None, "Missing Dependency",
            f"Required package '{pkg}' is not installed.\n"
            "Please install it using:\n"
            f"    pip install {pkg}\n"
            "and then restart the application.")
    except Exception:
        print(f"Required package '{pkg}' is not installed. Please install it using: pip install {pkg}")
    sys.exit(1)

try:
    from PyQt5 import QtWidgets, QtCore, QtGui
except ImportError:
    show_import_error('PyQt5')

try:
    import cantools
except ImportError:
    show_import_error('cantools')

from search_module import UnifiedSearchWidget
from dbc_editor_ui import DBCEditorWidget
from home_screen import HomeScreenWidget, RecentFilesManager

def get_version():
    """Get version from pyproject.toml"""
    possible_paths = []
    
    try:
        # Try multiple possible locations for pyproject.toml
        if hasattr(sys, '_MEIPASS'):
            # PyInstaller: look in _MEIPASS first (where bundled files are)
            possible_paths.append(Path(sys._MEIPASS) / "pyproject.toml")
            # Also check next to executable
            possible_paths.append(Path(sys.executable).parent / "pyproject.toml")
        else:
            # Development: look relative to this file
            possible_paths.append(Path(__file__).parent.parent / "pyproject.toml")
            # Also try current working directory
            possible_paths.append(Path.cwd() / "pyproject.toml")
        
        for pyproject_path in possible_paths:
            if pyproject_path.exists():
                with open(pyproject_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Look for version = "x.y.z" pattern
                    match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
                    if match:
                        return f"v{match.group(1)}"
    except Exception as e:
        print(f"Could not read version from pyproject.toml: {e}")
    
    # Fallback to default version
    return "v1.0.0"

# Package installation removed for executable compatibility
# All required packages should be installed during development
# and included in the PyInstaller spec file

class EmptyWidget(QtWidgets.QWidget):
    """A placeholder widget for empty menu pages."""
    def __init__(self, text="This page is under construction.", parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        label = QtWidgets.QLabel(text)
        label.setAlignment(QtCore.Qt.AlignCenter)
        label.setFont(QtGui.QFont("Arial", 16, QtGui.QFont.Bold))
        layout.addWidget(label)
        self.setLayout(layout)

class DBCProcessor:
    """
    Handles the logic for loading DBC files and extracting data.
    Separated from the UI for better modularity.
    """
    def __init__(self):
        self.db = None
        self._extracted_data = []
        # Metadata about the currently loaded DBC (kept separate from message list)
        self.dbc_info = None

    def load_dbc_file(self, dbc_path):
        """Loads a DBC file and populates _extracted_data."""
        if not dbc_path:
            raise ValueError("No DBC file path provided.")
        try:
            self.db = cantools.database.load_file(dbc_path)
        except Exception as e:
            raise RuntimeError(f"Failed to load DBC file: {e}")
        self._extracted_data = []

        self.dbc_info = {
            "dbc_file_path": dbc_path,
            "dbc_node_count": len(self.db.nodes),
            "dbc_message_count": len(self.db.messages),
            "dbc_signal_count": sum(len(msg.signals) for msg in self.db.messages),
            "dbc_file_size": os.path.getsize(dbc_path),
            "dbc_version": self.db.version,
            "dbc_buses": self.db.buses,
        }
        
        for msg in self.db.messages:
            # Signal groups come from 'SIG_GROUP_ ...;' lines in the DBC.
            # In cantools (>=40.x), they are exposed as 'Message.signal_groups'
            signal_groups = []
            for group in (getattr(msg, "signal_groups", None) or []):
                group_name = getattr(group, "name", None)
                group_signal_names = getattr(group, "signal_names", None) or []

                if group_name and group_signal_names:
                    signal_groups.append((group_name, list(group_signal_names)))

            # Build a reverse index for quick membership lookups while preserving group order.
            # signal_name -> [group_name1, group_name2, ...]
            signal_to_groups = {}
            for group_name, group_signals in signal_groups:
                for sig_name in group_signals:
                    signal_to_groups.setdefault(sig_name, []).append(group_name)
            
            message_info = {
                "message_name": msg.name,
                "senders": [str(s) for s in msg.senders],
                "frame_id": msg.frame_id,
                "length": msg.length,  # Message length in bytes
                "signal_groups": signal_groups,  # List of (group_name, [signal_names]) tuples
                "signals": []
            }
            for sig in msg.signals:
                raw_comments = str(sig.comments).strip('\0').replace('\n', ' ') if sig.comments else ""
                cleaned_comments = _clean_comment_text(raw_comments)
                # Extract value table/enum if available
                values_dict = {}
                if hasattr(sig, 'choices') and sig.choices:
                    values_dict = {int(k): str(v) for k, v in sig.choices.items()}
                
                # Find which signal groups this signal belongs to (if any)
                signal_groups_membership = signal_to_groups.get(sig.name, [])
                
                signal_info = {
                    "signal_name": sig.name,
                    "byte_order": getattr(sig, 'byte_order', 'little_endian'),
                    "is_signed": sig.is_signed,
                    "scale": getattr(sig, 'scale', 1.0),
                    "offset": getattr(sig, 'offset', 0.0),
                    "minimum": sig.minimum,
                    "maximum": sig.maximum,
                    "start bit|length": f"{sig.start}|{sig.length}",
                    "unit": getattr(sig, 'unit', '') or '',
                    "initial_value": getattr(sig, 'initial', None),
                    "values": values_dict if values_dict else None,  # Enum/choice table
                    "receivers": [str(r) for r in sig.receivers],
                    "signal_groups": signal_groups_membership,  # List[str] of group names this signal belongs to
                    "comments": cleaned_comments,
                    "item_text": f"{msg.name}.{sig.name}"
                }
                message_info["signals"].append(signal_info)
            self._extracted_data.append(message_info)
        return list(self._extracted_data)

    def get_extracted_data(self):
        return list(self._extracted_data)



class ConverterWindow(QtWidgets.QWidget):
    """
    Main DBC viewer interface with error handling and improved readability.
    """
    dbcFileLoaded = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dbc_processor = DBCProcessor()
        self._full_data = []
        self._setup_ui()

    def _setup_ui(self):
        main_h_layout = QtWidgets.QHBoxLayout()
        left_v_layout = QtWidgets.QVBoxLayout()
        dbc_layout = QtWidgets.QHBoxLayout()
        self.dbc_label = QtWidgets.QLabel("DBC File:")
        # Show only the file name (not editable).
        self.dbc_file_name_label = QtWidgets.QLabel("No file selected")
        self.dbc_file_name_label.setToolTip("No file selected")
        self.dbc_file_name_label.setMinimumWidth(240)
        self.dbc_file_name_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.dbc_browse_btn = QtWidgets.QPushButton("Browse...")
        self.load_signals_btn = QtWidgets.QPushButton("Load DBC")
        
        # Set button icons
        self._set_button_icon(self.dbc_browse_btn, "icons/browse.ico")
        self._set_button_icon(self.load_signals_btn, "icons/load.ico")
        
        dbc_layout.addWidget(self.dbc_label)
        dbc_layout.addWidget(self.dbc_file_name_label)
        dbc_layout.addWidget(self.dbc_browse_btn)
        dbc_layout.addWidget(self.load_signals_btn)
        left_v_layout.addLayout(dbc_layout)
        
        # File info panel (one line)
        self.info_group = QtWidgets.QGroupBox("File Information")
        info_layout = QtWidgets.QHBoxLayout()
        info_layout.setContentsMargins(8, 8, 8, 8)
        info_layout.setSpacing(12)
        
        self.info_node_count = QtWidgets.QLabel("Nodes: —")
        self.info_message_count = QtWidgets.QLabel("Messages: —")
        self.info_signal_count = QtWidgets.QLabel("Signals: —")
        self.info_file_size = QtWidgets.QLabel("Size: —")
        self.info_version = QtWidgets.QLabel("Version: —")
        self.info_buses = QtWidgets.QLabel("Buses: —")
        
        info_layout.addWidget(self.info_node_count)
        info_layout.addWidget(QtWidgets.QLabel("|"))  # Separator
        info_layout.addWidget(self.info_message_count)
        info_layout.addWidget(QtWidgets.QLabel("|"))
        info_layout.addWidget(self.info_signal_count)
        info_layout.addWidget(QtWidgets.QLabel("|"))
        info_layout.addWidget(self.info_file_size)
        info_layout.addWidget(QtWidgets.QLabel("|"))
        info_layout.addWidget(self.info_version)
        info_layout.addWidget(QtWidgets.QLabel("|"))
        info_layout.addWidget(self.info_buses)
        info_layout.addStretch()
        
        self.info_group.setLayout(info_layout)
        left_v_layout.addWidget(self.info_group)
        
        # Status label for errors/loading messages
        self.message_label = QtWidgets.QLabel("Ready")
        self.message_label.setAlignment(QtCore.Qt.AlignLeft)
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet("font-weight: bold; color: #34495E;")
        left_v_layout.addWidget(self.message_label)
        left_v_layout.addSpacing(10)
        self.search_widget = UnifiedSearchWidget(self, mode="view")
        self.search_widget.search_edit.setPlaceholderText("Search messages, signals, or frame IDs...")
        self.search_widget.searchChanged.connect(self._apply_filter_to_tree)
        left_v_layout.addWidget(self.search_widget)
        self.tree_widget = QtWidgets.QTreeWidget()
        self.tree_widget.setHeaderLabels(["Key", "Value", "Type"])
        self.tree_widget.header().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        self.tree_widget.setAlternatingRowColors(True)
        left_v_layout.addWidget(self.tree_widget)
        main_h_layout.addLayout(left_v_layout, 2)
        right_v_layout = QtWidgets.QVBoxLayout()
        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.refresh_btn.setStyleSheet("background-color: #3498db; color: white; border-radius: 5px; padding: 5px 10px;")
        self.refresh_btn.setFixedWidth(80)
        self.exitBtn = QtWidgets.QPushButton("Exit")
        self.exitBtn.setStyleSheet("background-color: #e74c3c; color: white; border-radius: 5px; padding: 5px 10px;")
        self.exitBtn.setFixedWidth(80)
        
        # Set button icons
        self._set_button_icon(self.refresh_btn, "icons/load_white.ico")
        self._set_button_icon(self.exitBtn, "icons/exit.ico")
        
        top_buttons_layout = QtWidgets.QHBoxLayout()
        top_buttons_layout.addStretch()
        top_buttons_layout.addWidget(self.refresh_btn)
        top_buttons_layout.addWidget(self.exitBtn)
        right_v_layout.addLayout(top_buttons_layout)
        self.details_widget = QtWidgets.QFrame()
        self.details_widget.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.details_widget.setFrameShadow(QtWidgets.QFrame.Sunken)
        self.details_widget_layout = QtWidgets.QVBoxLayout(self.details_widget)
        self.details_title_label = QtWidgets.QLabel("Item Details")
        self.details_title_label.setFont(QtGui.QFont("Arial", 12, QtGui.QFont.Bold))
        self.details_title_label.setAlignment(QtCore.Qt.AlignCenter)
        self.details_widget_layout.addWidget(self.details_title_label)
        self.details_text_edit = QtWidgets.QTextEdit()
        self.details_text_edit.setReadOnly(True)
        self.details_text_edit.setFont(QtGui.QFont("Monospace", 10))
        self.details_widget_layout.addWidget(self.details_text_edit)
        right_v_layout.addWidget(self.details_widget)
        main_h_layout.addLayout(right_v_layout, 1)
        self.setLayout(main_h_layout)
        self.dbc_browse_btn.clicked.connect(self.select_dbc_file)
        self.load_signals_btn.clicked.connect(self.load_and_display_signals)
        self.refresh_btn.clicked.connect(self.load_and_display_signals)
        self.exitBtn.clicked.connect(self.parent().close)
        self.tree_widget.itemClicked.connect(self.display_item_details)

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

    def select_dbc_file(self):
        try:
            file_name, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Select DBC File", "", "DBC Files (*.dbc);;All Files (*)"
            )
            if file_name:
                self._prepare_new_dbc(file_name)
        except Exception as e:
            self._show_error(f"Error selecting DBC file: {e}")

    def load_dbc_path(self, file_path: str) -> bool:
        """
        Load a DBC file directly (no file dialog). Intended for the Home screen.
        Returns True on success, False on failure.
        """
        try:
            if not file_path:
                self._show_error("No DBC file path provided.")
                return False
            if not os.path.exists(file_path):
                self._show_error(f"DBC file not found:\n{file_path}")
                return False
            if not file_path.lower().endswith(".dbc"):
                self._show_error("Selected file must have .dbc extension.")
                return False

            self._prepare_new_dbc(file_path)
            self.load_and_display_signals()
            return True
        except Exception as e:
            self._show_error(f"Error loading DBC file: {e}")
            return False

    def _prepare_new_dbc(self, file_path: str) -> None:
        """Prepare UI state for a new DBC selection."""
        self.dbc_path = file_path
        file_name = os.path.basename(file_path) if file_path else "No file selected"
        self.dbc_file_name_label.setText(file_name)
        self.dbc_file_name_label.setToolTip(file_path or "")
        self.message_label.setText("DBC file selected.")
        self.tree_widget.clear()
        self.details_text_edit.clear()
        self.details_title_label.setText("Item Details")
        self.search_widget.clear_search()
        self.dbc_processor._extracted_data = []
        self._full_data = []
        # Clear file info panel
        self.info_node_count.setText("Nodes: —")
        self.info_message_count.setText("Messages: —")
        self.info_signal_count.setText("Signals: —")
        self.info_file_size.setText("Size: —")
        self.info_version.setText("Version: —")
        self.info_buses.setText("Buses: —")

    def load_and_display_signals(self):
        if not hasattr(self, 'dbc_path') or not self.dbc_path:
            self._show_error("Please select a DBC file first.")
            return
        try:
            self.message_label.setText("Loading DBC file and extracting data...")
            self._full_data = self.dbc_processor.load_dbc_file(self.dbc_path)
            self._apply_filter_to_tree()
            self._update_file_info()
            self.message_label.setText("DBC file loaded successfully")
            self.details_text_edit.clear()
            self.details_title_label.setText("Item Details")
            self.dbcFileLoaded.emit(self.dbc_path)
        except Exception as e:
            self._show_error(f"Error loading DBC file: {e}")
    
    def _format_file_size(self, size_bytes):
        """Format file size in human-readable format."""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.2f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"
    
    def _update_file_info(self):
        """Update the file information panel with current DBC data."""
        if not self.dbc_processor.dbc_info:
            return
        
        info = self.dbc_processor.dbc_info
        self.info_node_count.setText(f"Nodes: {info.get('dbc_node_count', 0)}")
        self.info_message_count.setText(f"Messages: {info.get('dbc_message_count', 0)}")
        self.info_signal_count.setText(f"Signals: {info.get('dbc_signal_count', 0)}")
        self.info_file_size.setText(f"Size: {self._format_file_size(info.get('dbc_file_size', 0))}")
        self.info_version.setText(f"Version: {info.get('dbc_version', '—')}")
        
        buses = info.get('dbc_buses', [])
        if buses:
            buses_str = ', '.join(str(b) for b in buses) if isinstance(buses, list) else str(buses)
            self.info_buses.setText(f"Buses: {buses_str}")
        else:
            self.info_buses.setText("Buses: —")

    def _apply_filter_to_tree(self, search_query="", filter_type="all"):
        try:
            if not self._full_data:
                self._populate_tree_widget([])
                return
            search_query_lower = search_query.lower().strip()
            filtered_results = []
            if not search_query_lower and filter_type == "all":
                filtered_results = list(self._full_data)
            else:
                for msg_data in self._full_data:
                    message_matches = False
                    signals_matching = []
                    if filter_type == "all" or filter_type == "message":
                        if search_query_lower in msg_data["message_name"].lower():
                            message_matches = True
                    if filter_type == "all" or filter_type == "frame_id":
                        if search_query_lower in str(hex(msg_data["frame_id"])).lower() or \
                           search_query_lower in str(msg_data["frame_id"]).lower():
                            message_matches = True
                    for sig_data in msg_data["signals"]:
                        signal_level_match = False
                        if filter_type == "all" or filter_type == "signal":
                            if (search_query_lower in sig_data["signal_name"].lower() or
                                search_query_lower in sig_data["comments"].lower() or
                                search_query_lower in ",".join(sig_data["receivers"]).lower() or
                                search_query_lower in str(sig_data.get("minimum", "")).lower() or
                                search_query_lower in str(sig_data.get("maximum", "")).lower()):
                                signal_level_match = True
                        if filter_type == "frame_id" and (search_query_lower in str(hex(msg_data["frame_id"])).lower() or \
                                                          search_query_lower in str(msg_data["frame_id"]).lower()):
                            if not search_query_lower or signal_level_match:
                                signals_matching.append(sig_data)
                        elif signal_level_match:
                            signals_matching.append(sig_data)
                    if message_matches:
                        filtered_results.append(msg_data)
                    elif signals_matching:
                        temp_msg_data = msg_data.copy()
                        temp_msg_data["signals"] = signals_matching
                        filtered_results.append(temp_msg_data)
            self._populate_tree_widget(filtered_results)
        except Exception as e:
            self._show_error(f"Error filtering data: {e}")

    @staticmethod
    def _tree_add_group(parent, title: str, type_name: str = "Group") -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem(parent)
        item.setText(0, title)
        item.setText(2, type_name)
        return item

    @staticmethod
    def _tree_add_row(parent, key: str, value, type_name: str) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem(parent)
        item.setText(0, key)
        item.setText(1, str(value))
        item.setText(2, type_name)
        return item

    def _add_signal_to_tree(self, parent_item, sig_data):
        """
        Helper method to add a signal item with all its properties to the tree.
        
        Args:
            parent_item: QTreeWidgetItem to add the signal under
            sig_data: Dictionary containing signal information
        """
        sig_item = QtWidgets.QTreeWidgetItem(parent_item)
        sig_item.setText(0, sig_data["signal_name"])
        sig_item.setText(2, "Signal")
        sig_item.setData(0, QtCore.Qt.UserRole, sig_data)

        # Summary line (quick glance)
        summary_parts = []
        scale = sig_data.get("scale", 1.0)
        offset = sig_data.get("offset", 0.0)
        if scale != 1.0 or offset != 0.0:
            summary_parts.append(f"Scale: {scale}, Offset: {offset}")

        unit = sig_data.get("unit") or ""
        if unit:
            summary_parts.append(f"Unit: {unit}")

        summary_parts.append("Signed" if sig_data.get("is_signed") else "Unsigned")

        summary_item = QtWidgets.QTreeWidgetItem(sig_item)
        summary_item.setText(0, "Summary")
        summary_item.setText(1, " | ".join(summary_parts))
        summary_item.setText(2, "Summary")
        summary_item.setForeground(0, QtGui.QBrush(QtGui.QColor("#2980B9")))

        # Basic Properties
        basic_group = self._tree_add_group(sig_item, "Basic Properties")
        start_bit_length = sig_data.get("start bit|length")
        if start_bit_length:
            self._tree_add_row(basic_group, "Start Bit|Length", start_bit_length, "str")
        byte_order = sig_data.get("byte_order", "little_endian")
        byte_order_display = f"{byte_order} (Intel)" if byte_order == "little_endian" else f"{byte_order} (Motorola)"
        self._tree_add_row(basic_group, "Byte Order", byte_order_display, "str")
        self._tree_add_row(basic_group, "Signed", "Yes" if sig_data.get("is_signed") else "No", "bool")

        # Scaling Properties
        scaling_group = self._tree_add_group(sig_item, "Scaling Properties")
        self._tree_add_row(scaling_group, "Scale", scale, "float")
        self._tree_add_row(scaling_group, "Offset", offset, "float")
        if unit:
            self._tree_add_row(scaling_group, "Unit", unit, "str")

        # Range Properties (only if present)
        minimum = sig_data.get("minimum")
        maximum = sig_data.get("maximum")
        if minimum is not None or maximum is not None:
            range_group = self._tree_add_group(sig_item, "Range Properties")
            if minimum is not None:
                self._tree_add_row(range_group, "Minimum", minimum, "float")
            if maximum is not None:
                self._tree_add_row(range_group, "Maximum", maximum, "float")

        # Initial Value
        initial_value = sig_data.get("initial_value")
        if initial_value is not None:
            self._tree_add_row(sig_item, "Initial Value", initial_value, type(initial_value).__name__)

        # Value Table (Enums)
        values = sig_data.get("values")
        if values:
            values_group = self._tree_add_group(sig_item, "Value Table (Enums)")
            for enum_val, enum_name in sorted(values.items()):
                hex_val = hex(enum_val)
                self._tree_add_row(values_group, hex_val, enum_name, "Enum")

        # Receivers
        receivers = sig_data.get("receivers") or []
        if receivers:
            self._tree_add_row(sig_item, "Receivers", ", ".join(receivers), "List")

        # Signal Groups
        memberships = sig_data.get("signal_groups") or []
        if memberships:
            self._tree_add_row(sig_item, "Signal Groups", ", ".join(memberships), "List")

        # Comments
        comments = sig_data.get("comments") or ""
        if comments:
            displayed_comment = _clean_comment_text(comments)
            if len(displayed_comment) > 50:
                displayed_comment = displayed_comment[:50] + "..."
            if displayed_comment:  # Only show if there's content after cleaning
                self._tree_add_row(sig_item, "Comments", displayed_comment, "str")

    def _populate_tree_widget(self, data):
        """
        Populate the tree widget with message and signal data.
        If signal groups exist, signals are organized under their respective groups.
        Ungrouped signals are displayed separately.
        """
        self.tree_widget.clear()
        if not data:
            QtWidgets.QTreeWidgetItem(self.tree_widget).setText(0, "No matching data found.")
            return

        for msg_data in data:
            msg_item = QtWidgets.QTreeWidgetItem(self.tree_widget)
            msg_item.setText(0, msg_data["message_name"])

            frame_id = msg_data["frame_id"]
            frame_type = "Extended" if frame_id > 0x7FF else "Standard"
            msg_item.setText(1, f"Frame ID: {hex(frame_id)} ({frame_type})")
            msg_item.setText(2, "Message")
            msg_item.setData(0, QtCore.Qt.UserRole, msg_data)

            # Message properties
            msg_props_item = self._tree_add_group(msg_item, "Message Properties", "Group")
            self._tree_add_row(msg_props_item, "Length", f"{msg_data.get('length', 'N/A')} bytes", "int")
            self._tree_add_row(msg_props_item, "Frame ID", f"{hex(frame_id)} (decimal: {frame_id})", "int")
            self._tree_add_row(msg_props_item, "Frame Type", frame_type, "str")

            # Senders
            senders = msg_data.get("senders") or []
            senders_item = self._tree_add_row(msg_item, "Senders", ", ".join(senders) if senders else "None", "List")
            senders_item.setData(0, QtCore.Qt.UserRole, {"Type": "Senders List", "Senders": senders})

            # Signals grouped by name for fast lookup
            signals = msg_data.get("signals") or []
            signals_by_name = {sig["signal_name"]: sig for sig in signals}
            signals_added_to_groups = set()

            # Signal Groups -> Signals
            signal_groups = msg_data.get("signal_groups") or []
            if signal_groups:
                signal_groups_item = self._tree_add_group(msg_item, "Signal Groups", "Collection")
                for group_name, group_signal_names in signal_groups:
                    group_item = self._tree_add_group(signal_groups_item, group_name, "Group")
                    group_item.setData(
                        0,
                        QtCore.Qt.UserRole,
                        {"Type": "Signal Group", "Name": group_name, "Signals": group_signal_names},
                    )

                    for sig_name in group_signal_names:
                        sig_data = signals_by_name.get(sig_name)
                        if sig_data:
                            signals_added_to_groups.add(sig_name)
                            self._add_signal_to_tree(group_item, sig_data)

            # Ungrouped signals (or all signals if no groups)
            ungrouped = [sig for sig in signals if sig["signal_name"] not in signals_added_to_groups]
            if ungrouped:
                title = "Ungrouped Signals" if signal_groups else "Signals"
                root = self._tree_add_group(msg_item, title, "Collection")
                for sig_data in ungrouped:
                    self._add_signal_to_tree(root, sig_data)

        self.tree_widget.expandAll()

    def display_item_details(self, item, column):
        try:
            item_data = item.data(0, QtCore.Qt.UserRole)
            details_html = []
            # Set the title label appropriately
            if item_data:
                if "message_name" in item_data:
                    self.details_title_label.setText(f"Message: {item_data['message_name']}")
                    details_html.append("<div style='background-color:#f7fafc; border-radius:8px; padding:18px 18px 10px 18px; margin-bottom:10px; border:1px solid #e0e0e0;'>")
                    details_html.append(f"<div style='margin-bottom:8px;'><b>Frame ID:</b> <span style='color:#E67E22;'>{hex(item_data['frame_id'])}</span></div>")
                    details_html.append(f"<div style='margin-bottom:8px;'><b>Senders:</b> <span style='color:#2980B9;'>{', '.join(item_data['senders'])}</span></div>")
                    if item_data.get('comments'):
                        details_html.append(f"<div style='margin-bottom:8px;'><b>Comments:</b> <span style='color:#888;'>{item_data['comments']}</span></div>")
                    details_html.append("</div>")
                    if item_data["signals"]:
                        details_html.append("<div style='margin-top:18px;'><span style='font-size:14pt; color:#2C3E50; font-weight:bold;'>Signals</span></div>")
                        for sig in item_data["signals"]:
                            details_html.append("<div style='background-color:#f0f4f8; border-radius:6px; padding:10px 12px; margin:10px 0 10px 0; border-left: 4px solid #3498DB;'>")
                            details_html.append(f"<div style='font-size:12pt; color:#16A085; font-weight:bold;'>{sig['signal_name']}</div>")
                            if sig.get('comments'):
                                details_html.append(f"<div style='margin-bottom:4px; color:#888;'><b>Comments:</b> {sig['comments']}</div>")
                            details_html.append(f"<div><b>Receivers:</b> {', '.join(sig['receivers'])}</div>")
                            details_html.append(f"<div><b>Is Signed:</b> {sig['is_signed']}</div>")
                            details_html.append(f"<div><b>Minimum:</b> {sig['minimum']}</div>")
                            details_html.append(f"<div><b>Maximum:</b> {sig['maximum']}</div>")
                            details_html.append(f"<div><b>Maximum:</b> {sig['maximum']}</div>")
                            details_html.append(f"<div><b>Start Bit|Length:</b> {sig['start bit|length']}</div>")
                            details_html.append("</div>")
                    else:
                        details_html.append("<div style='font-style:italic; color:#7F8C8D; margin-top:10px;'>No signals for this message.</div>")
                elif "signal_name" in item_data:
                    self.details_title_label.setText(f"Signal: {item_data['signal_name']}")
                    details_html.append("<div style='background-color:#f7fafc; border-radius:8px; padding:18px 18px 10px 18px; margin-bottom:10px; border:1px solid #e0e0e0;'>")
                    for key, value in item_data.items():
                        # Format byte_order with Intel/Motorola labels
                        if key == "byte_order":
                            byte_order_display = f"{value} (Intel)" if value == "little_endian" else f"{value} (Motorola)"
                            details_html.append(f"<div style='margin-bottom:8px;'><b>{key.replace('_', ' ').title()}:</b> {byte_order_display}</div>")
                        elif key == "values" and isinstance(value, dict):
                            # Format value table with hex values in a pretty list
                            details_html.append(f"<div style='margin-bottom:12px;'><b>{key.replace('_', ' ').title()}:</b></div>")
                            details_html.append("<div style='background-color:#f0f4f8; border-radius:6px; padding:10px; margin-left:10px;'>")
                            for enum_val, enum_name in sorted(value.items()):
                                hex_val = hex(enum_val)
                                details_html.append(f"<div style='margin-bottom:6px; padding:4px 8px; background-color:#ffffff; border-radius:4px; border-left:3px solid #3498DB;'><span style='color:#E67E22; font-weight:bold;'>{hex_val}</span> → <span style='color:#2C3E50;'>{enum_name}</span></div>")
                            details_html.append("</div>")
                        elif isinstance(value, list):
                            details_html.append(f"<div style='margin-bottom:8px;'><b>{key.replace('_', ' ').title()}:</b> {', '.join(map(str, value))}</div>")
                        else:
                            details_html.append(f"<div style='margin-bottom:8px;'><b>{key.replace('_', ' ').title()}:</b> {value}</div>")
                    details_html.append("</div>")
                elif "Type" in item_data and item_data["Type"] == "Senders List":
                    self.details_title_label.setText("Senders List")
                    details_html.append("<div style='background-color:#f7fafc; border-radius:8px; padding:18px; border:1px solid #e0e0e0;'>")
                    details_html.append(f"<div><b>Senders:</b> {', '.join(item_data['Senders'])}</div>")
                    details_html.append("</div>")
                else:
                    self.details_title_label.setText("Item Details")
                    details_html.append("<div style='text-align:center; color:#7F8C8D;'><i>Select an item from the tree to view its details.</i></div>")
            else:
                self.details_title_label.setText("Item Details")
                details_html.append("<div style='text-align:center; color:#7F8C8D;'><i>Select an item from the tree to view its details.</i></div>")
            self.details_text_edit.setHtml("".join(details_html))
        except Exception as e:
            self._show_error(f"Error displaying item details: {e}")



    def _show_error(self, message):
        QtWidgets.QMessageBox.critical(self, "Error", message)
        self.message_label.setText(f"<font color='red'>{message}</font>")

class MainWindow(QtWidgets.QMainWindow):
    APP_NAME = "CAN DBC Utility"
    APP_VERSION = get_version()
    APP_DESCRIPTION = "Open Source tool to view and edit CAN DBC files."
    APP_WEBSITE = "https://DBCUtility.com"
    APP_GITHUB = "https://github.com/abhi-1203/dbcUtility"
    APP_CREATOR = "Abhijith"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.APP_NAME)
        self.resize(1200, 750)
        self.setStyleSheet("QMainWindow { border: 1px solid lightgray; }")

        # Set application icon
        self._set_app_icon()

        # Central navigation: Home screen
        self._recent_files = RecentFilesManager()
        self._stack = QtWidgets.QStackedWidget()
        self.setCentralWidget(self._stack)

        self.view_dbc_page = ConverterWindow(self)
        self.edit_dbc_page = DBCEditorWidget(self)
        self.view_can_bus_page = EmptyWidget("Coming Soon: CAN Bus Viewer.")

        self.tab_widget = QtWidgets.QTabWidget()
        # Add tabs with icons
        self.tab_widget.addTab(self.view_dbc_page, self._get_tab_icon("icons/view.ico"), "View DBC")
        self.tab_widget.addTab(self.edit_dbc_page, self._get_tab_icon("icons/edit.ico"), "Edit DBC")
        self.tab_widget.addTab(self.view_can_bus_page, self._get_tab_icon("icons/can_bus.ico"), "CAN Bus Viewer")

        # Home button shown next to the tabs (returns to the Home screen)
        self.home_button = QtWidgets.QToolButton()
        self.home_button.setAutoRaise(True)
        self.home_button.setToolTip("Home")
        self.home_button.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        try:
            home_icon = self._get_tab_icon("icons/home.ico")
            if home_icon.isNull():
                home_icon = self.style().standardIcon(QtWidgets.QStyle.SP_DirHomeIcon)
            self.home_button.setIcon(home_icon)
        except Exception:
            pass
        self.home_button.clicked.connect(self._show_home)
        self.tab_widget.setCornerWidget(self.home_button, QtCore.Qt.TopLeftCorner)

        self.home_page = HomeScreenWidget(
            self.APP_NAME,
            self.APP_VERSION,
            self.APP_DESCRIPTION,
            self.APP_CREATOR,
            self.APP_WEBSITE,
            self.APP_GITHUB,
            self._recent_files,
            self,
        )

        self._stack.addWidget(self.home_page)
        self._stack.addWidget(self.tab_widget)
        self._stack.setCurrentWidget(self.home_page)

        # Wire Home -> pages
        self.home_page.openViewRequested.connect(self._open_view_dbc)
        self.home_page.openEditRequested.connect(self._open_edit_dbc)
        self.home_page.openCanBusRequested.connect(self._open_can_bus)

        # Update recents whenever a page successfully loads a DBC
        self.view_dbc_page.dbcFileLoaded.connect(self._on_dbc_file_loaded)
        if hasattr(self.edit_dbc_page, "dbcFileLoaded"):
            self.edit_dbc_page.dbcFileLoaded.connect(self._on_dbc_file_loaded)

        self._create_status_bar()

    def _show_home(self) -> None:
        """Return to the Home screen."""
        try:
            self._stack.setCurrentWidget(self.home_page)
            self.home_page.refresh_recent_files()
        except Exception as e:
            print(f"Error showing home: {e}")

    def _on_dbc_file_loaded(self, file_path: str) -> None:
        try:
            if file_path:
                self._recent_files.add_file(file_path)
                if hasattr(self, "home_page"):
                    self.home_page.refresh_recent_files()
        except Exception as e:
            print(f"Error updating recent files: {e}")

    def _open_view_dbc(self, file_path):
        self._stack.setCurrentWidget(self.tab_widget)
        self.tab_widget.setCurrentIndex(0)
        if file_path:
            ok = self.view_dbc_page.load_dbc_path(str(file_path))
            if not ok:
                # If load fails, return to home so the user can pick another file
                self._stack.setCurrentWidget(self.home_page)

    def _open_edit_dbc(self, file_path):
        self._stack.setCurrentWidget(self.tab_widget)
        self.tab_widget.setCurrentIndex(1)
        if file_path and hasattr(self.edit_dbc_page, "load_dbc_path"):
            ok = self.edit_dbc_page.load_dbc_path(str(file_path))
            if not ok:
                self._stack.setCurrentWidget(self.home_page)

    def _open_can_bus(self):
        self._stack.setCurrentWidget(self.tab_widget)
        self.tab_widget.setCurrentIndex(2)

    def _set_app_icon(self):
        """Set the application icon if the icon file exists."""
        try:
            icon_path = get_resource_path("icons/app_icon.ico")
            if os.path.exists(icon_path):
                icon = QtGui.QIcon(icon_path)
                # Set window icon (this affects the window title bar)
                self.setWindowIcon(icon)
                # Ensure application icon is set (this affects taskbar)
                app = QtWidgets.QApplication.instance()
                if app and app.windowIcon().isNull():
                    app.setWindowIcon(icon)
        except Exception as e:
            print(f"Could not load application icon {icon_path}: {e}")

    def _get_tab_icon(self, icon_path):
        """Get icon for tab if the icon file exists."""
        try:
            full_icon_path = get_resource_path(icon_path)
            if os.path.exists(full_icon_path):
                return QtGui.QIcon(full_icon_path)
        except Exception as e:
            print(f"Could not load tab icon {icon_path}: {e}")
        return QtGui.QIcon()  # Return empty icon if file doesn't exist

    def _create_status_bar(self):
        status_bar = self.statusBar()
        app_name_label = QtWidgets.QLabel(f"{self.APP_NAME}")
        app_version_label = QtWidgets.QLabel(f"Version: {self.APP_VERSION}")
        status_bar.addWidget(app_name_label)
        status_bar.addPermanentWidget(app_version_label)
        status_bar.setStyleSheet("QStatusBar{padding-left:8px;background:#f0f0f0;color:black;}")

    def closeEvent(self, event):
        """Handle application close event to clean up backup files."""
        try:
            # Clean up backup files from DBC editor
            if hasattr(self.edit_dbc_page, 'dbc_editor'):
                self.edit_dbc_page.dbc_editor.cleanup_all_backups()
        except Exception as e:
            print(f"Error during cleanup: {e}")
        
        # Accept the close event
        event.accept()


