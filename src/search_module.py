from PyQt5 import QtWidgets, QtCore, QtGui
import logging

logger = logging.getLogger(__name__)

class UnifiedSearchWidget(QtWidgets.QWidget):
    """
    Unified search widget for both view and edit pages.
    Emits searchChanged(str, str) when the search query or filter changes.
    """
    searchChanged = QtCore.pyqtSignal(str, str)  # search_query, filter_type

    def __init__(self, parent=None, mode="view"):
        """
        Args:
            parent: Parent widget
            mode: 'view' for tree view, 'edit' for list view
        """
        super().__init__(parent)
        self.mode = mode
        self._setup_ui()

    def _setup_ui(self):
        """Setup the search widget UI based on mode."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Search bar
        search_layout = QtWidgets.QHBoxLayout()
        self.search_label = QtWidgets.QLabel("Search:")
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Search...")
        self.search_edit.textChanged.connect(self._on_search_changed)

        search_layout.addWidget(self.search_label)
        search_layout.addWidget(self.search_edit)

        # Filter options
        if self.mode == "view":
            self._setup_view_filters(layout, search_layout)
        else:
            self._setup_edit_filters(layout, search_layout)

    def _setup_view_filters(self, layout, search_layout):
        self.filter_label = QtWidgets.QLabel("Filter by:")
        self.filter_all_rb = QtWidgets.QRadioButton("All")
        self.filter_message_rb = QtWidgets.QRadioButton("Messages")
        self.filter_signal_rb = QtWidgets.QRadioButton("Signals")
        self.filter_frame_id_rb = QtWidgets.QRadioButton("Frame IDs")
        self.filter_all_rb.setChecked(True)

        self.filter_group = QtWidgets.QButtonGroup(self)
        self.filter_group.addButton(self.filter_all_rb)
        self.filter_group.addButton(self.filter_message_rb)
        self.filter_group.addButton(self.filter_signal_rb)
        self.filter_group.addButton(self.filter_frame_id_rb)
        self.filter_group.buttonClicked.connect(self._on_filter_changed)

        filter_layout = QtWidgets.QHBoxLayout()
        filter_layout.addWidget(self.filter_label)
        filter_layout.addWidget(self.filter_all_rb)
        filter_layout.addWidget(self.filter_message_rb)
        filter_layout.addWidget(self.filter_signal_rb)
        filter_layout.addWidget(self.filter_frame_id_rb)
        filter_layout.addStretch()

        layout.addLayout(search_layout)
        layout.addLayout(filter_layout)

    def _setup_edit_filters(self, layout, search_layout):
        self.frame_filter_combo = QtWidgets.QComboBox()
        self.frame_filter_combo.addItems(['All', 'Standard Frame', 'Extended Frame'])
        self.frame_filter_combo.currentTextChanged.connect(self._on_filter_changed)
        search_layout.addWidget(self.frame_filter_combo)
        layout.addLayout(search_layout)

    def _on_search_changed(self):
        try:
            self._emit_search_changed()
        except Exception as e:
            logger.error(f"Error in search text change: {e}")

    def _on_filter_changed(self):
        try:
            self._emit_search_changed()
        except Exception as e:
            logger.error(f"Error in filter change: {e}")

    def _emit_search_changed(self):
        search_query = self.search_edit.text()
        filter_type = self.get_filter_type()
        self.searchChanged.emit(search_query, filter_type)

    def get_search_query(self):
        """Get the current search query."""
        return self.search_edit.text()

    def get_filter_type(self):
        """Get the current filter type."""
        if self.mode == "view":
            if self.filter_message_rb.isChecked():
                return "message"
            elif self.filter_signal_rb.isChecked():
                return "signal"
            elif self.filter_frame_id_rb.isChecked():
                return "frame_id"
            else:
                return "all"
        else:
            return self.frame_filter_combo.currentText()

    def clear_search(self):
        """Clear the search field."""
        self.search_edit.clear()

    def set_search_query(self, query):
        """Set the search query."""
        self.search_edit.setText(query)

    def set_filter_type(self, filter_type):
        """Set the filter type."""
        if self.mode == "view":
            if filter_type == "message":
                self.filter_message_rb.setChecked(True)
            elif filter_type == "signal":
                self.filter_signal_rb.setChecked(True)
            elif filter_type == "frame_id":
                self.filter_frame_id_rb.setChecked(True)
            else:
                self.filter_all_rb.setChecked(True)
        else:
            index = self.frame_filter_combo.findText(filter_type)
            if index >= 0:
                self.frame_filter_combo.setCurrentIndex(index)