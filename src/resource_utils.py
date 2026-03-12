#!/usr/bin/env python3
"""
Shared resource helpers.

Why this exists:
- In development, resources live in the repo (e.g. ./icons).
- In a PyInstaller build, resources are extracted into a temp directory pointed to by sys._MEIPASS.

Centralizing this avoids duplicating the same logic across multiple modules.
"""

from __future__ import annotations

import os
import re
import sys


def get_resource_path(relative_path: str) -> str:
    """
    Return an absolute path for a resource file.

    - PyInstaller: resolves relative to sys._MEIPASS
    - Dev: resolves relative to the project root (one level above this file's directory)
    """
    base_path = getattr(sys, "_MEIPASS", None)
    if base_path:
        return os.path.join(base_path, relative_path)

    # Dev mode: project root = ../ (since this file lives in ./src)
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(project_root, relative_path)


# ---------------------------------------------------------------------------
# File dialog helpers
#
# On Linux and macOS, Qt's QFileDialog works correctly and is used directly.
#
# On Windows, Qt 5.15.2's QFileDialog crashes on Windows 11 due to a
# regression in the Windows shell's IFileDialog COM integration.  The crash
# occurs for both native and non-native dialog modes.
#
# The fix for Windows is to open the dialog in a separate powershell.exe
# process using System.Windows.Forms.OpenFileDialog / SaveFileDialog.
# Because the dialog runs outside the Qt process, the two event loops never
# share a thread and the crash disappears.  This approach also works in
# PyInstaller-frozen executables, where spawning `sys.executable -c …`
# would fail (sys.executable is the bundled .exe, not python.exe).
# ---------------------------------------------------------------------------

def _qt_filter_to_winforms(qt_filter: str) -> str:
    """Convert a Qt-style filter string to a WinForms FileDialog Filter string.

    Qt      : "DBC Files (*.dbc);;All Files (*)"
    WinForms: "DBC Files (*.dbc)|*.dbc|All Files (*.*)|*.*"
    """
    parts = []
    for part in qt_filter.split(";;"):
        part = part.strip()
        m = re.match(r"^(.+?)\s*\((.+?)\)$", part)
        if m:
            label = m.group(1).strip()
            exts  = m.group(2).strip()
            if exts == "*":
                exts = "*.*"
            parts.append(f"{label} ({exts})|{exts}")
    return "|".join(parts) if parts else "*.*|*.*"


def _ps_str(s: str) -> str:
    """Escape a string for use inside a PowerShell single-quoted literal."""
    return s.replace("'", "''")


def _run_powershell_dialog(ps_command: str) -> str:
    """Run a PowerShell one-liner and return the path printed to stdout."""
    import subprocess
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_command],
            capture_output=True, text=True, timeout=300,
        )
        path = proc.stdout.strip()
        return os.path.normpath(path) if path else ""
    except Exception:
        return ""


def open_file_dialog(title: str, qt_filter: str = "All Files (*)") -> str:
    """Show an open-file dialog; return the chosen path, or '' if cancelled."""
    if sys.platform != "win32":
        from PyQt5 import QtWidgets
        path, _ = QtWidgets.QFileDialog.getOpenFileName(None, title, "", qt_filter)
        return path

    ps_filter = _qt_filter_to_winforms(qt_filter)
    cmd = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d = New-Object System.Windows.Forms.OpenFileDialog; "
        f"$d.Title = '{_ps_str(title)}'; "
        f"$d.Filter = '{_ps_str(ps_filter)}'; "
        "if ($d.ShowDialog() -eq 'OK') { $d.FileName }"
    )
    return _run_powershell_dialog(cmd)


def save_file_dialog(title: str, qt_filter: str = "All Files (*)") -> str:
    """Show a save-file dialog; return the chosen path, or '' if cancelled."""
    if sys.platform != "win32":
        from PyQt5 import QtWidgets
        path, _ = QtWidgets.QFileDialog.getSaveFileName(None, title, "", qt_filter)
        return path

    ps_filter = _qt_filter_to_winforms(qt_filter)
    m = re.search(r"\*(\.\w+)", ps_filter)
    default_ext = m.group(1) if m else ".dbc"
    cmd = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$d = New-Object System.Windows.Forms.SaveFileDialog; "
        f"$d.Title = '{_ps_str(title)}'; "
        f"$d.Filter = '{_ps_str(ps_filter)}'; "
        f"$d.DefaultExt = '{default_ext}'; "
        "$d.AddExtension = $true; "
        "if ($d.ShowDialog() -eq 'OK') { $d.FileName }"
    )
    return _run_powershell_dialog(cmd)


