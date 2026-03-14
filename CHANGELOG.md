# Changelog

All notable changes to DBC Utility will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.3] - 2026-03-14

### Added

#### DBC Comparison Tool (New)
- Side-by-side diff view with editable panels, line numbers, and character-level change highlighting
- Unified diff view with +/- markers and "only changes" filter
- Structured (semantic) comparison view showing messages, signals, and properties in synchronized side-by-side trees
- Color-coded diff status: added (green), removed (red), modified (yellow), unchanged
- Per-line directional copy arrows (push model) for copying individual lines between panels
- Right-click context menus in structured view for Add, Edit, Copy, Delete of messages and signals
- Swap primary/secondary files
- Ignore whitespace option for text comparison
- Previous/Next change navigation
- Undo/Redo with keyboard shortcuts (Ctrl+Z / Ctrl+Y) and toolbar buttons
- Save Primary / Save Secondary buttons with dirty-state tracking
- Asterisk (`*`) indicator next to filenames when unsaved changes exist
- Save confirmation dialog on successful file save
- Refresh button to reload files from disk (with unsaved-changes prompt)
- Debounced live re-diff on edit with cursor position preservation
- Editor integration: save-review flow from Edit tab to Compare tab

#### Multiplexer Support
- Full multiplexed signal handling across the entire application
- Signal classification: `multiplexer`, `multiplexed`, `regular`
- Multiplexer filter dropdowns in both View and Edit tabs
- Multiplexer fields in Signal Edit dialog (Is Multiplexer, Multiplexer IDs, Multiplexer Signal)
- Mux indicator badges in signal lists (`[M]`, `[m0x5]`, etc.)
- Mux validation with warnings for common configuration issues
- Graceful handling of overlapping multiplexed signals (`strict=False` fallback in cantools)

#### Message Signal Layout Visualizer
- Bit-level grid visualization of CAN/CAN FD message layouts (up to 64 bytes)
- Color-coded signal blocks with Material Design palette (16 colors)
- Support for both Little-endian (Intel) and Big-endian (Motorola) byte orders
- Signal name, bit position, and length annotations per cell
- Message header with name, bus type, frame type, length, frame ID, signal count
- Multiplexer filter for multiplexed messages
- Accessible from both View and Edit tabs

#### Home Screen
- Landing screen with app logo, title, and navigation buttons (View DBC, Edit DBC, CAN Bus Viewer)
- Recent files manager with QSettings persistence (up to 50 files)
- Double-click or select-and-open workflow for recent files
- About dialog with app info, version, creator, website, and GitHub links

#### Editor Enhancements
- Duplicate Message and Duplicate Signal buttons with auto-unique naming
- Move Message Up/Down and Move Signal Up/Down buttons for reordering
- Value Table (Choices) editor in Signal Edit dialog with add/remove rows
- Sectioned checkable dropdown for senders and receivers
- Bus Type selector (CAN / CAN FD) in Message Edit dialog
- Save-review flow: editor changes go through a diff review before saving

#### Icons
- Migrated all icons to QtAwesome (scalable vector font icons) throughout the application
- Removed all legacy `.ico` icon files (except app_icon.ico/png for window and logo)
- Consistent white icons on green buttons in the editor
- Semantic icons for tabs, buttons, tree items, and context menus

### Changed
- Renamed comparison labels from "File A" / "File B" to "Primary" / "Secondary"
- Project structure expanded with new modules: `dbc_comparator.py`, `dbc_comparator_ui.py`, `multiplex_support.py`, `message_layout_visualizer.py`, `home_screen.py`, `about_dialog.py`, `resource_utils.py`
- Compare DBC tab added to main tabbed interface with `fa6s.code-compare` icon
- Dependencies: added `QtAwesome>=1.4.1`
- Version reading from `pyproject.toml` at runtime (no hardcoded version strings)

### Fixed
- Multiplexed signal saving no longer fails with "overlapping signals" error
- Cursor position preserved during live diff updates (logical line tracking)
- Trailing blank lines preserved correctly in text comparison
- Comment extraction handles various cantools formats (string, dict, callable)

---

## [1.0.2] - 2025-11-10

### Changed
- Changed to UV package manager
- Added button to create a new DBC file
- Added buttons to reorder messages and signals
- Binded the Edit message and Edit signals to double click
- Added Buttons to duplicate Message and duplicate signals

### Fixed
- Version label at the bottom is using the real version (from pyproject.toml)

---

## [1.0.1] - 2025-01-29

### Changed
- Updated paths for Linux installation to use `_internal/icons/` directory
- Updated Refresh button UI for better user experience
- Removed unused main.spec to avoid confusion and maintain cleaner project structure

### Fixed
- Linux installation script now correctly copies icons from PyInstaller's `_internal` folder
- Desktop entry icon paths now reference system icon directory for proper display
- Removed unnecessary PIL/Pillow dependency as it was not being used by the application

---

## [1.0.0] - 2025-01-27

### Added
- Initial release of DBC Utility
- DBC file viewer with hierarchical tree structure
- DBC file editor with full CRUD operations for messages and signals
- Advanced search functionality with real-time filtering across messages, signals, and frame IDs
- PyQt5-based modern GUI with tabbed interface
- Icon support for all buttons and tabs
- File management: load, save, and save-as functionality
- Backup file creation during save operations with automatic cleanup
- Comprehensive contribution guidelines, Code of Conduct, and Security Policy
- GPL v3 license compliance for PyQt5 compatibility
- Project structure with `src/` and `scripts/` separation
- Windows and Linux build scripts (PyInstaller, AppImage)
- Release scripts for creating versioned distribution packages

### Fixed
- None type handling for signal attributes (minimum, maximum, scale, offset, start_bit, length)
- Icon loading issues in PyInstaller executables
- Application icon consistency between executable and taskbar

---

## Contributing to the Changelog

When contributing to DBC Utility, please update this changelog by:

1. Adding your changes under the appropriate section
2. Using the correct format and categories
3. Including issue numbers when applicable
4. Following the existing style and structure

### Categories
- **Added**: New features
- **Changed**: Changes in existing functionality
- **Deprecated**: Soon-to-be removed features
- **Removed**: Removed features
- **Fixed**: Bug fixes
- **Security**: Security-related changes
