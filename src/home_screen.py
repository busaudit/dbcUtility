#!/usr/bin/env python3
"""
Home screen module for DBC Utility.

This module adds a non-invasive "entry" screen that routes the user to the existing
View/Edit/CAN Bus tabs, and provides a recent-files section.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from about_dialog import AboutDialog
from resource_utils import get_resource_path

class RecentFilesManager(QtCore.QObject):
    """
    Stores and retrieves recently opened DBC files.

    Uses QSettings so it works both in dev and in PyInstaller builds.
    """

    def __init__(
        self,
        organization: str = "DBCUtility",
        application: str = "DBCUtility",
        max_files: int = 50,
        parent: Optional[QtCore.QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._settings = QtCore.QSettings(organization, application)
        self._max_files = max(1, int(max_files))

    def _load_entries(self) -> List[dict]:
        """
        Load recent file entries.

        Storage format: QSettings key 'recentFiles' stores JSON:
            [{"path": "...", "last_opened": 1735150000}, ...]
        """
        raw = self._settings.value("recentFiles", None)
        if not raw:
            return []

        try:
            data = json.loads(str(raw))
        except Exception:
            return []

        if not isinstance(data, list):
            return []

        out: List[dict] = []
        for it in data:
            if not isinstance(it, dict):
                continue
            p = it.get("path")
            if not p:
                continue
            try:
                p = os.path.normpath(str(p))
            except Exception:
                continue
            ts = it.get("last_opened")
            try:
                ts_int = int(ts) if ts is not None else 0
            except Exception:
                ts_int = 0
            out.append({"path": p, "last_opened": ts_int})

        return out[: self._max_files]

    def _save_entries(self, entries: List[dict]) -> None:
        # Normalize and dedupe while preserving order
        unique: List[dict] = []
        seen = set()
        for e in entries:
            if not isinstance(e, dict):
                continue
            p = e.get("path")
            if not p:
                continue
            p = os.path.normpath(str(p))
            if p in seen:
                continue
            seen.add(p)
            ts = e.get("last_opened")
            try:
                ts = int(ts) if ts is not None else 0
            except Exception:
                ts = 0
            unique.append({"path": p, "last_opened": ts})

        unique = unique[: self._max_files]
        self._settings.setValue("recentFiles", json.dumps(unique))

    def get_recent_entries(self) -> List[dict]:
        """Return entries: [{'path': str, 'last_opened': int}, ...]."""
        return list(self._load_entries())

    def get_recent_files(self) -> List[str]:
        return [e["path"] for e in self._load_entries()]

    def set_recent_files(self, paths: List[str]) -> None:
        entries = [{"path": os.path.normpath(str(p)), "last_opened": 0} for p in paths if p]
        self._save_entries(entries)

    def add_file(self, path: str) -> None:
        if not path:
            return
        path = os.path.normpath(path)
        now = int(time.time())
        entries = self._load_entries()
        entries = [e for e in entries if e.get("path") != path]
        entries.insert(0, {"path": path, "last_opened": now})
        self._save_entries(entries)

    def remove_file(self, path: str) -> None:
        if not path:
            return
        path = os.path.normpath(path)
        entries = [e for e in self._load_entries() if e.get("path") != path]
        self._save_entries(entries)

    def prune_missing(self) -> None:
        entries = [e for e in self._load_entries() if os.path.exists(e.get("path", ""))]
        self._save_entries(entries)


class HomeScreenWidget(QtWidgets.QWidget):
    """
    Home screen showing app name + routing buttons, with a recent-files section

    Signals:
        openViewRequested(str|None): user chose View DBC, optional preselected file path
        openEditRequested(str|None): user chose Edit DBC, optional preselected file path
        openCanBusRequested(): user chose CAN Bus Viewer
    """

    openViewRequested = QtCore.pyqtSignal(object)
    openEditRequested = QtCore.pyqtSignal(object)
    openCanBusRequested = QtCore.pyqtSignal()

    def __init__(
        self,
        app_name: str,
        app_version: str,
        app_description: Optional[str],
        creator: str,
        website: Optional[str],
        github: Optional[str],
        recent_files: RecentFilesManager,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._app_name = app_name
        self._app_version = app_version
        self._app_description = app_description
        self._creator = creator
        self._website = website
        self._github = github
        self._recent_files = recent_files
        self._selected_path: Optional[str] = None
        self._setup_ui()
        # Keep the list clean (remove missing entries) silently on startup
        try:
            self._recent_files.prune_missing()
        except Exception:
            pass
        self.refresh_recent_files()

    def _setup_ui(self) -> None:
        # Intentionally minimal home screen

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.addStretch()

        card = QtWidgets.QFrame()
        card.setFrameShape(QtWidgets.QFrame.NoFrame)
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(10)

        # Logo
        logo_label = QtWidgets.QLabel()
        logo_label.setAlignment(QtCore.Qt.AlignCenter)
        logo_path = get_resource_path("icons/app_icon.png")
        if os.path.exists(logo_path):
            pix = QtGui.QPixmap(logo_path)
            if not pix.isNull():
                logo_label.setPixmap(pix.scaled(96, 96, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        card_layout.addWidget(logo_label)

        app_title = QtWidgets.QLabel(self._app_name)
        app_title.setAlignment(QtCore.Qt.AlignCenter)
        title_font = app_title.font()
        title_font.setBold(True)
        title_font.setPointSize(max(12, title_font.pointSize() + 6))
        app_title.setFont(title_font)
        card_layout.addWidget(app_title)

        subtitle = QtWidgets.QLabel("Choose what you want to do. Recents are listed below.")
        subtitle.setAlignment(QtCore.Qt.AlignCenter)
        subtitle.setWordWrap(True)
        card_layout.addWidget(subtitle)

        # Buttons row
        buttons_row = QtWidgets.QHBoxLayout()
        buttons_row.setSpacing(12)

        self.view_button = QtWidgets.QPushButton("View DBC")
        self.view_button.setToolTip("Open a DBC in the Viewer (inspect messages & signals).")

        self.edit_button = QtWidgets.QPushButton("Edit DBC")
        self.edit_button.setToolTip("Open a DBC in the Editor (modify messages & signals).")

        # CAN Bus Viewer is coming soon
        self.can_button = QtWidgets.QPushButton("CAN Bus Viewer")
        self.can_button.setToolTip("Coming soon.")

        # Icons + native buttons
        self.view_button.setIcon(QtGui.QIcon(get_resource_path("icons/view.ico")))
        self.edit_button.setIcon(QtGui.QIcon(get_resource_path("icons/edit.ico")))
        self.can_button.setIcon(QtGui.QIcon(get_resource_path("icons/can_bus.ico")))

        about_btn = QtWidgets.QPushButton("About")
        about_btn.setToolTip("About this tool")
        about_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        about_btn.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxInformation))
        about_btn.setIconSize(QtCore.QSize(18, 18))
        about_btn.setMinimumHeight(40)
        about_btn.clicked.connect(self._show_about)

        for b in (self.view_button, self.edit_button, self.can_button, about_btn):
            b.setMinimumHeight(40)
            b.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
            b.setIconSize(QtCore.QSize(18, 18))
            if b is self.can_button:
                can_container = QtWidgets.QWidget()
                can_stack = QtWidgets.QStackedLayout(can_container)
                can_stack.setContentsMargins(0, 0, 0, 0)
                can_stack.addWidget(self.can_button)

                overlay = QtWidgets.QWidget()
                overlay.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, False)
                overlay.setToolTip(self.can_button.toolTip())
                can_stack.addWidget(overlay)
                can_stack.setStackingMode(QtWidgets.QStackedLayout.StackAll)

                self.can_button.setEnabled(False)
                overlay.setCursor(QtGui.QCursor(QtCore.Qt.WhatsThisCursor))
                overlay.mousePressEvent = lambda _e: None

                buttons_row.addWidget(can_container, 1)
            else:
                buttons_row.addWidget(b, 1)

        self.view_button.clicked.connect(self._request_view)
        self.edit_button.clicked.connect(self._request_edit)
        # Note: CAN button is disabled in the Home screen

        card_layout.addLayout(buttons_row)

        # Recent files below buttons
        recent_header = QtWidgets.QLabel("Recents")
        recent_header.setStyleSheet("font-weight: 700; margin-top: 6px;")
        card_layout.addWidget(recent_header)

        self.recent_list = QtWidgets.QListWidget()
        self.recent_list.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.recent_list.setStyleSheet(
            """
            QListWidget { background: transparent; }
            QListWidget::item:hover { background: rgba(0, 0, 0, 0.05); }
            QListWidget::item:selected { background: rgba(0, 120, 215, 0.14); }
            """
        )

        self.recent_list.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.recent_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.recent_list.setFixedHeight(150)
        self.recent_list.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.recent_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.recent_list.itemSelectionChanged.connect(self._on_recent_selection_changed)
        self.recent_list.itemDoubleClicked.connect(self._on_recent_double_clicked)
        card_layout.addWidget(self.recent_list, 0)

        # created_by = QtWidgets.QLabel("Created by Abhijith")
        # created_by.setAlignment(QtCore.Qt.AlignCenter)
        # created_by.setStyleSheet("color: rgba(0, 0, 0, 0.55);")
        # footer_row = QtWidgets.QHBoxLayout()
        # footer_row.addStretch()
        # footer_row.addWidget(created_by)
        # footer_row.addStretch()

        # card_layout.addLayout(footer_row)

        card_wrap = QtWidgets.QHBoxLayout()
        card_wrap.addStretch()
        card_wrap.addWidget(card, 0)
        card_wrap.addStretch()
        root.addLayout(card_wrap)
        root.addStretch()

        card.setMinimumWidth(700)
        card.setMaximumWidth(1000)

    def refresh_recent_files(self) -> None:
        entries = self._recent_files.get_recent_entries()

        self.recent_list.clear()
        self._selected_path = None

        if not entries:
            placeholder = QtWidgets.QListWidgetItem("No recent files yet.")
            placeholder.setFlags(placeholder.flags() & ~QtCore.Qt.ItemIsSelectable)
            placeholder.setForeground(QtGui.QBrush(QtGui.QColor("#6B7280")))
            self.recent_list.addItem(placeholder)
            return

        for e in entries:
            p = e.get("path", "")
            if not p:
                continue
            ts = int(e.get("last_opened") or 0)
            if ts > 0:
                dt = datetime.fromtimestamp(ts)
                ts_text = dt.strftime("%Y-%m-%d %H:%M")
                text = f"{os.path.basename(p)} | last opened {ts_text}"
            else:
                text = f"{os.path.basename(p)} | last opened —"

            item = QtWidgets.QListWidgetItem(text)
            item.setToolTip(p)
            item.setData(QtCore.Qt.UserRole, p)
            self.recent_list.addItem(item)

    def _on_recent_selection_changed(self) -> None:
        items = self.recent_list.selectedItems()
        if not items:
            self._selected_path = None
            return
        path = items[0].data(QtCore.Qt.UserRole)
        self._selected_path = str(path) if path else None

    def _on_recent_double_clicked(self, item: QtWidgets.QListWidgetItem) -> None:
        path = item.data(QtCore.Qt.UserRole)
        if path:
            # Double click defaults to "View"
            self.openViewRequested.emit(str(path))

    def _get_or_prompt_for_dbc(self) -> Optional[str]:
        path = self._selected_path
        if path and os.path.exists(path) and path.lower().endswith(".dbc"):
            return path

        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select DBC File", "", "DBC Files (*.dbc);;All Files (*)"
        )
        if not file_path:
            return None
        if not file_path.lower().endswith(".dbc"):
            QtWidgets.QMessageBox.warning(self, "Invalid file", "Please select a .dbc file.")
            return None
        if not os.path.exists(file_path):
            QtWidgets.QMessageBox.warning(self, "File not found", "The selected file does not exist.")
            return None

        self._recent_files.add_file(file_path)
        self.refresh_recent_files()
        return file_path

    def _request_view(self) -> None:
        file_path = self._get_or_prompt_for_dbc()
        if file_path:
            self.openViewRequested.emit(file_path)

    def _request_edit(self) -> None:
        path = self._selected_path
        if path and os.path.exists(path) and path.lower().endswith(".dbc"):
            self.openEditRequested.emit(path)
        else:
            self.openEditRequested.emit(None)

    def _show_about(self) -> None:
        dlg = AboutDialog(
            app_name=self._app_name,
            app_version=self._app_version,
            description=self._app_description,
            creator=self._creator,
            website=self._website,
            github=self._github,
            parent=self,
        )
        dlg.exec_()


