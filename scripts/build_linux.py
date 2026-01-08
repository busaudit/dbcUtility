#!/usr/bin/env python3
"""
Linux Build Script for DBC Utility
Creates a folder-based distribution that works across Linux distributions.
"""

import os
import sys
import subprocess
import shutil
import platform
from pathlib import Path

def check_dependencies():
    """Check if required dependencies are installed"""
    # Define package names and their actual import names
    package_imports = {
        'PyQt5': 'PyQt5',
        'cantools': 'cantools'
    }
    
    missing_packages = []
    
    for package_name, import_name in package_imports.items():
        try:
            __import__(import_name)
            print(f"✓ {package_name} is installed")
        except ImportError:
            missing_packages.append(package_name)
            print(f"✗ {package_name} is missing")
    
    if missing_packages:
        print(f"\nPlease install missing packages:")
        print("Using UV (recommended):")
        print(f"  uv sync")
        print("Or using pip (legacy):")
        for package in missing_packages:
            print(f"  pip install {package}")
        return False
    
    return True

def clean_build_dirs():
    """Clean previous build directories"""
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    dirs_to_clean = ['build', 'dist', 'linuxBuilds']
    for dir_name in dirs_to_clean:
        dir_path = project_root / dir_name
        if dir_path.exists():
            print(f"Cleaning {dir_name} directory...")
            shutil.rmtree(dir_path)
            print(f"✓ Cleaned {dir_name}")

def get_system_info():
    """Get system information for the build"""
    system_info = {
        'platform': platform.system(),
        'architecture': platform.machine(),
        'python_version': platform.python_version(),
        'distribution': get_linux_distribution()
    }
    return system_info

def get_linux_distribution():
    """Get Linux distribution information"""
    try:
        with open('/etc/os-release', 'r') as f:
            lines = f.readlines()
            for line in lines:
                if line.startswith('PRETTY_NAME='):
                    return line.split('=')[1].strip().strip('"')
    except:
        pass
    
    try:
        with open('/etc/lsb-release', 'r') as f:
            lines = f.readlines()
            for line in lines:
                if line.startswith('DISTRIB_DESCRIPTION='):
                    return line.split('=')[1].strip().strip('"')
    except:
        pass
    
    return "Unknown Linux Distribution"

def build_linux_package():
    """Build the Linux package using PyInstaller"""
    print("Building Linux package...")
    
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    # Create linuxBuilds directory
    linux_builds_dir = project_root / "linuxBuilds"
    linux_builds_dir.mkdir(exist_ok=True)
    
    # PyInstaller command for Linux
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",  # Create directory instead of single file
        "--windowed",  # No console window
        "--icon=icons/app_icon.png",  # Use PNG icon for Linux
        "--add-data=icons:icons",  # Include icons
        "--paths=src",  # Add src to Python path (for imports, not data)
        "--hidden-import=PyQt5.QtCore",
        "--hidden-import=PyQt5.QtGui", 
        "--hidden-import=PyQt5.QtWidgets",
        "--hidden-import=cantools",
        "--hidden-import=search_module",
        "--hidden-import=dbc_editor_ui",
        "--hidden-import=dbc_editor",
        "--name=DBCUtility",  # Name of the executable
        "main.py"
    ]
    
    try:
        subprocess.check_call(cmd)
        print("✓ PyInstaller build completed successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ PyInstaller build failed: {e}")
        return False

def create_linux_distribution():
    """Create the final Linux distribution folder"""
    print("Creating Linux distribution...")
    
    project_root = Path(__file__).parent.parent
    dist_dir = project_root / "dist" / "DBCUtility"
    linux_builds_dir = project_root / "linuxBuilds"
    
    if not dist_dir.exists():
        print(f"✗ PyInstaller output not found: {dist_dir}")
        return False
    
    # Create versioned distribution folder
    system_info = get_system_info()
    arch = system_info['architecture']
    dist_name = f"DBCUtility-Linux-{arch}"
    final_dist_dir = linux_builds_dir / dist_name
    
    if final_dist_dir.exists():
        shutil.rmtree(final_dist_dir)
    
    # Copy PyInstaller output
    shutil.copytree(dist_dir, final_dist_dir)
    print(f"✓ Copied PyInstaller output to {final_dist_dir}")
    
    # Create launcher script
    create_launcher_script(final_dist_dir)
    
    # Create desktop entry
    create_desktop_entry(final_dist_dir)
    
    # Copy documentation
    copy_documentation(final_dist_dir, project_root)
    
    # Create installation script
    create_install_script(final_dist_dir)
    
    # Create uninstall script
    create_uninstall_script(final_dist_dir)
    
    print(f"✓ Linux distribution created: {final_dist_dir}")
    return True

def create_launcher_script(dist_dir):
    """Create a launcher script for the application"""
    launcher_content = """#!/bin/bash
# DBC Utility Launcher Script

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Set the executable path
EXECUTABLE="$SCRIPT_DIR/DBCUtility"

# Check if executable exists
if [ ! -f "$EXECUTABLE" ]; then
    echo "Error: DBCUtility executable not found at $EXECUTABLE"
    exit 1
fi

# Check if executable is executable
if [ ! -x "$EXECUTABLE" ]; then
    echo "Making executable..."
    chmod +x "$EXECUTABLE"
fi

# Run the application
cd "$SCRIPT_DIR"
exec "$EXECUTABLE" "$@"
"""
    
    launcher_path = dist_dir / "launch-dbc-utility.sh"
    with open(launcher_path, 'w') as f:
        f.write(launcher_content)
    
    # Make launcher executable
    os.chmod(launcher_path, 0o755)
    print(f"✓ Created launcher script: {launcher_path}")

def create_desktop_entry(dist_dir):
    """Create a desktop entry file"""
    desktop_content = """[Desktop Entry]
Version=1.0
Type=Application
Name=DBC Utility
GenericName=CAN Database Editor
Comment=Edit and view CAN database files (DBC format)
Exec=launch-dbc-utility.sh
Icon=app_icon.png
Terminal=false
Categories=Development;Engineering;Electronics;
Keywords=CAN;DBC;Database;Automotive;Engineering;
StartupWMClass=DBCUtility
"""
    
    desktop_path = dist_dir / "DBCUtility.desktop"
    with open(desktop_path, 'w') as f:
        f.write(desktop_content)
    print(f"✓ Created desktop entry: {desktop_path}")

def copy_documentation(dist_dir, project_root):
    """Copy documentation files"""
    docs_to_copy = ['README.md', 'LICENSE', 'CHANGELOG.md']
    
    for doc in docs_to_copy:
        src_path = project_root / doc
        if src_path.exists():
            shutil.copy2(src_path, dist_dir)
            print(f"✓ Copied {doc}")

def create_install_script(dist_dir):
    """Create installation script"""
    install_content = """#!/bin/bash
# DBC Utility Installation Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="DBCUtility"
INSTALL_DIR="/opt/$APP_NAME"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons"

echo "Installing DBC Utility..."

# Create installation directory
echo "Creating installation directory: $INSTALL_DIR"
sudo mkdir -p "$INSTALL_DIR"
echo "✓ Created installation directory: $INSTALL_DIR"

# Copy application files
echo "Copying application files..."
sudo cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/"
echo "✓ Copied application files"

# Make executable
sudo chmod +x "$INSTALL_DIR/DBCUtility"
sudo chmod +x "$INSTALL_DIR/launch-dbc-utility.sh"
echo "✓ Set executable permissions"

# Create desktop entry
mkdir -p "$DESKTOP_DIR"
cp "$INSTALL_DIR/DBCUtility.desktop" "$DESKTOP_DIR/"

# Update the desktop entry with correct paths
sed -i "s|Exec=launch-dbc-utility.sh|Exec=$INSTALL_DIR/launch-dbc-utility.sh|g" "$DESKTOP_DIR/DBCUtility.desktop"
sed -i "s|Icon=app_icon.png|Icon=dbc-utility|g" "$DESKTOP_DIR/DBCUtility.desktop"
echo "✓ Created desktop entry"

# Copy icon to system icon directory
mkdir -p "$ICON_DIR"
cp "$INSTALL_DIR/_internal/icons/app_icon.png" "$ICON_DIR/dbc-utility.png"
echo "✓ Installed application icon"

# Update desktop database
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo ""
echo "✓ DBC Utility installed successfully!"
echo "You can now find it in your applications menu."
echo ""
echo "To uninstall, run: $INSTALL_DIR/uninstall.sh"
"""
    
    install_path = dist_dir / "install.sh"
    with open(install_path, 'w') as f:
        f.write(install_content)
    
    os.chmod(install_path, 0o755)
    print(f"✓ Created installation script: {install_path}")

def create_uninstall_script(dist_dir):
    """Create uninstall script"""
    uninstall_content = """#!/bin/bash
# DBC Utility Uninstall Script

set -e

APP_NAME="DBCUtility"
INSTALL_DIR="/opt/$APP_NAME"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons"

echo "Uninstalling DBC Utility..."

# Remove desktop entry
rm -f "$DESKTOP_DIR/DBCUtility.desktop"
echo "✓ Removed desktop entry"

# Remove icon
rm -f "$ICON_DIR/dbc-utility.png"
echo "✓ Removed application icon"

# Remove installation directory
sudo rm -rf "$INSTALL_DIR"
echo "✓ Removed installation directory"

# Update desktop database
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo ""
echo "✓ DBC Utility uninstalled successfully!"
"""
    
    uninstall_path = dist_dir / "uninstall.sh"
    with open(uninstall_path, 'w') as f:
        f.write(uninstall_content)
    
    os.chmod(uninstall_path, 0o755)
    print(f"✓ Created uninstall script: {uninstall_path}")

def create_readme(dist_dir):
    """Create Linux-specific README"""
    readme_content = """# DBC Utility for Linux

## Installation

### Option 1: Install System-wide (Recommended)
```bash
chmod +x install.sh
./install.sh
```

### Option 2: Run from Current Directory
```bash
chmod +x launch-dbc-utility.sh
./launch-dbc-utility.sh
```

### Option 3: Run Directly
```bash
chmod +x DBCUtility
./DBCUtility
```

## Uninstallation

If you installed system-wide:
```bash
sudo /opt/DBCUtility/uninstall.sh
```

## System Requirements

- Linux kernel 3.0 or later
- glibc 2.17 or later
- X11 or Wayland display server
- 100MB free disk space

## Troubleshooting

### Permission Denied
If you get permission errors, make sure the executable has proper permissions:
```bash
chmod +x DBCUtility
chmod +x launch-dbc-utility.sh
```

### Missing Libraries
This distribution includes all required libraries. If you encounter issues:
1. Check if your system supports the included libraries
2. Try running from the command line to see error messages
3. Ensure you have proper display server access

### Desktop Integration
If the application doesn't appear in your applications menu:
1. Run the installation script again
2. Log out and log back in
3. Try running `update-desktop-database` manually

## Support

For issues and support, please refer to the main README.md file.
"""
    
    readme_path = dist_dir / "README-Linux.md"
    with open(readme_path, 'w') as f:
        f.write(readme_content)
    print(f"✓ Created Linux README: {readme_path}")

def main():
    print("=== DBC Utility Linux Builder ===")
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Get system info
    system_info = get_system_info()
    print(f"\nSystem Information:")
    print(f"  Platform: {system_info['platform']}")
    print(f"  Architecture: {system_info['architecture']}")
    print(f"  Python Version: {system_info['python_version']}")
    print(f"  Distribution: {system_info['distribution']}")
    
    if system_info['platform'] != 'Linux':
        print("⚠️  Warning: This script is designed for Linux systems")
        response = input("Continue anyway? (y/N): ")
        if response.lower() != 'y':
            sys.exit(1)
    
    # Clean previous builds
    clean_build_dirs()
    
    # Build the package
    if not build_linux_package():
        sys.exit(1)
    
    # Create distribution
    if not create_linux_distribution():
        sys.exit(1)
    
    # Create Linux-specific README
    project_root = Path(__file__).parent.parent
    system_info = get_system_info()
    arch = system_info['architecture']
    dist_name = f"DBCUtility-Linux-{arch}"
    final_dist_dir = project_root / "linuxBuilds" / dist_name
    create_readme(final_dist_dir)
    
    print("\n=== Build Complete ===")
    print(f"Linux distribution created: linuxBuilds/{dist_name}/")
    print("\nNext steps:")
    print("1. Test the distribution on your system")
    print("2. Package it for distribution (tar.gz, AppImage, etc.)")
    print("3. Test on target systems")

if __name__ == "__main__":
    main() 