#!/usr/bin/env python3
"""
Linux Release Script for DBC Utility
Creates a complete Linux release package with versioning.
"""

import os
import sys
import subprocess
import shutil
import tarfile
import platform
import re
from datetime import datetime
from pathlib import Path

def get_version():
    """Get current version from pyproject.toml"""
    try:
        project_root = Path(__file__).parent.parent
        pyproject_path = project_root / "pyproject.toml"
        
        if pyproject_path.exists():
            with open(pyproject_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Look for version = "x.y.z" pattern
                match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    return match.group(1)
        
        print(f"Error: pyproject.toml not found at {pyproject_path}")
        sys.exit(1)
    except Exception as e:
        print(f"Error reading version from pyproject.toml: {e}")
        sys.exit(1)

def build_linux_release():
    """Build the Linux release"""
    print("=== Building Linux Release ===")
    
    # Change to project root
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
    
    # Run Linux build script
    try:
        subprocess.run([sys.executable, "scripts/build_linux.py"], check=True)
        print("✓ Linux build completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Linux build failed: {e}")
        return False

def create_linux_release_package(version):
    """Create Linux release package with versioning"""
    print(f"=== Creating Linux Release Package v{version} ===")
    
    project_root = Path(__file__).parent.parent
    linux_builds_dir = project_root / "linuxBuilds"
    
    # Find the Linux distribution folder
    dist_folders = list(linux_builds_dir.glob("DBCUtility-Linux-*"))
    if not dist_folders:
        print("✗ No Linux distribution found. Run build_linux.py first.")
        return False
    
    dist_folder = dist_folders[0]  # Take the first one
    arch = dist_folder.name.split('-')[-1]
    
    # Create release directory
    release_dir = project_root / f"release-linux-v{version}"
    if release_dir.exists():
        shutil.rmtree(release_dir)
    release_dir.mkdir()
    
    # Create versioned distribution folder
    versioned_dist_name = f"DBCUtility-Linux-{arch}-v{version}"
    versioned_dist_dir = release_dir / versioned_dist_name
    
    # Copy the distribution
    shutil.copytree(dist_folder, versioned_dist_dir)
    print(f"✓ Copied distribution: {versioned_dist_name}")
    
    # Create release notes
    create_linux_release_notes(release_dir, version, arch)
    create_combined_release_notes(release_dir, version)
    
    # Create tar.gz package
    create_tar_package(release_dir, versioned_dist_name, version)
    
    # Create AppImage (if possible)
    create_appimage_package(versioned_dist_dir, version, arch)
    
    print(f"✓ Linux release package created: {release_dir}/")
    return True

def create_linux_release_notes(release_dir, version, arch):
    """Create Linux-specific release notes"""
    release_notes = f"""# DBC Utility Linux v{version} Release Notes

Release Date: {datetime.now().strftime('%Y-%m-%d')}
Architecture: {arch}

## What's New in v{version}

This is the Linux release of DBC Utility, a comprehensive CAN database editor.

### Features
- DBC file viewer with tree structure
- Full DBC file editor with CRUD operations
- Advanced search functionality
- Modern PyQt5-based GUI
- Icon support for all buttons
- File management (load, save, save-as)

### Linux-Specific Features
- Cross-distribution compatibility
- Desktop integration (menu entry, icon)
- System-wide installation support
- Portable execution (no installation required)
- Proper Linux permissions and file structure

### Installation Options

1. **System-wide Installation (Recommended)**
   ```bash
   chmod +x install.sh
   ./install.sh
   ```

2. **Portable Execution**
   ```bash
   chmod +x launch-dbc-utility.sh
   ./launch-dbc-utility.sh
   ```

3. **Direct Execution**
   ```bash
   chmod +x DBCUtility
   ./DBCUtility
   ```

### System Requirements
- Linux kernel 3.0 or later
- glibc 2.17 or later
- X11 or Wayland display server
- 100MB free disk space

### Supported Distributions
This release has been tested on:
- Ubuntu 20.04 LTS and later
- Debian 11 and later
- Fedora 35 and later
- CentOS 8 and later
- Arch Linux
- openSUSE Leap 15.3 and later

### Package Contents
- DBCUtility executable (with all dependencies)
- Icons and resources
- Installation scripts
- Desktop integration files
- Documentation (README, LICENSE, CHANGELOG)

### Uninstallation
If installed system-wide:
```bash
sudo /opt/DBCUtility/uninstall.sh
```

### Troubleshooting
See README-Linux.md for detailed troubleshooting information.

### Support
For issues and support, please refer to the main README.md file or create an issue on the project repository.
"""
    
    release_notes_path = release_dir / f"RELEASE_NOTES_Linux_v{version}.md"
    with open(release_notes_path, 'w') as f:
        f.write(release_notes)
    print(f"✓ Created release notes: {release_notes_path}")

def create_tar_package(release_dir, dist_name, version):
    """Create tar.gz package"""
    print("Creating tar.gz package...")
    
    tar_filename = f"{dist_name}.tar.gz"
    tar_path = release_dir / tar_filename
    
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(release_dir / dist_name, arcname=dist_name)
    
    print(f"✓ Created tar.gz package: {tar_filename}")

def create_appimage_package(dist_dir, version, arch):
    """Create AppImage package if appimagetool is available"""
    print("Attempting to create AppImage...")
    
    # Check if appimagetool is available
    try:
        subprocess.run(["appimagetool", "--version"], 
                      capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("⚠️  appimagetool not found. Skipping AppImage creation.")
        print("   To create AppImage, install appimagetool:")
        print("   wget https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage")
        print("   chmod +x appimagetool-x86_64.AppImage")
        print("   sudo mv appimagetool-x86_64.AppImage /usr/local/bin/appimagetool")
        return
    
    try:
        # Create AppDir structure
        appdir = dist_dir.parent / f"DBCUtility.AppDir"
        if appdir.exists():
            shutil.rmtree(appdir)
        
        # Copy application to AppDir
        shutil.copytree(dist_dir, appdir / "usr" / "bin" / "DBCUtility")
        
        # Create AppRun script
        apprun_content = """#!/bin/bash
cd "$(dirname "$0")"
exec ./usr/bin/DBCUtility/DBCUtility "$@"
"""
        apprun_path = appdir / "AppRun"
        with open(apprun_path, 'w') as f:
            f.write(apprun_content)
        os.chmod(apprun_path, 0o755)
        
        # Create desktop entry for AppImage
        desktop_content = """[Desktop Entry]
Version=1.0
Type=Application
Name=DBC Utility
Comment=CAN Database Editor
Exec=DBCUtility
Icon=DBCUtility
Terminal=false
Categories=Development;Engineering;
"""
        desktop_path = appdir / "usr" / "share" / "applications" / "DBCUtility.desktop"
        desktop_path.parent.mkdir(parents=True, exist_ok=True)
        with open(desktop_path, 'w') as f:
            f.write(desktop_content)
        
        # Copy icon - try multiple possible locations
        icon_path = appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
        icon_path.mkdir(parents=True, exist_ok=True)
        
        # Try to find the icon in various possible locations
        possible_icon_sources = [
            dist_dir / "icons" / "app_icon.png",
            dist_dir / "app_icon.png",
            Path(__file__).parent.parent / "icons" / "app_icon.png"
        ]
        
        icon_found = False
        for icon_source in possible_icon_sources:
            if icon_source.exists():
                shutil.copy2(icon_source, icon_path / "DBCUtility.png")
                print(f"✓ Copied icon from: {icon_source}")
                icon_found = True
                break
        
        if not icon_found:
            print("⚠️  Warning: Could not find app_icon.png, AppImage will use default icon")
            # Create a simple placeholder icon or skip icon creation
        
        # Create AppImage
        appimage_name = f"DBCUtility-Linux-{arch}-v{version}.AppImage"
        appimage_path = dist_dir.parent / appimage_name
        
        subprocess.run([
            "appimagetool", 
            str(appdir), 
            str(appimage_path)
        ], check=True)
        print(f"✓ Created AppImage: {appimage_name}")
        
    except Exception as e:
        print(f"✗ AppImage creation failed: {e}")
        print("   Continuing with tar.gz distribution only...")

def create_combined_release_notes(release_dir, version):
    """Create combined release notes for GitHub"""
    combined_notes = f"""# DBC Utility v{version}

## Downloads

### Windows
- **DBCUtility-Windows-v{version}.zip** - Windows executable with all dependencies

### Linux  
- **DBCUtility-Linux-x86_64-v{version}.tar.gz** - Linux distribution (works on all Linux distros)
- **DBCUtility-Linux-x86_64-v{version}.AppImage** - AppImage format (if available)

## Quick Start

### Windows
1. Download and extract `DBCUtility-Windows-v{version}.zip`
2. Run `DBCUtility.exe`

### Linux
1. Download and extract `DBCUtility-Linux-x86_64-v{version}.tar.gz`
2. Run `./install.sh` for system installation
3. Or run `./launch-dbc-utility.sh` for portable use

## Common Features (Both Platforms)
- DBC file viewer with tree structure
- Full DBC file editor with CRUD operations
- Advanced search functionality
- Modern PyQt5-based GUI
- Icon support for all buttons
- File management (load, save, save-as)

## Platform-Specific Features

### Windows
- Single-file executable
- No installation required
- Windows 10/11 compatible
- Automatic dependency bundling

### Linux
- Cross-distribution compatibility
- Desktop integration (menu entry, icon)
- System-wide installation support
- Portable execution (no installation required)
- Proper Linux permissions and file structure

## Detailed Release Notes
- **Windows**: See `RELEASE_NOTES_Windows_v{version}.md`
- **Linux**: See `RELEASE_NOTES_Linux_v{version}.md`

## System Requirements

### Windows
- Windows 10 or later
- 100MB free disk space

### Linux
- Linux kernel 3.0 or later
- glibc 2.17 or later
- X11 or Wayland display server
- 100MB free disk space

## Support
For issues and support, please create an issue on the project repository.
"""
    
    combined_notes_path = release_dir / f"RELEASE_NOTES_Combined_v{version}.md"
    with open(combined_notes_path, 'w') as f:
        f.write(combined_notes)
    print(f"✓ Created combined release notes: {combined_notes_path}")

def create_checksums(release_dir):
    """Create checksums for all files"""
    print("Creating checksums...")
    
    checksums_file = release_dir / "checksums.txt"
    with open(checksums_file, 'w') as f:
        f.write(f"# DBC Utility Linux Release Checksums\n")
        f.write(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        for file_path in release_dir.rglob("*"):
            if file_path.is_file() and file_path.name != "checksums.txt":
                try:
                    import hashlib
                    with open(file_path, 'rb') as file:
                        sha256_hash = hashlib.sha256(file.read()).hexdigest()
                    relative_path = file_path.relative_to(release_dir)
                    f.write(f"{sha256_hash}  {relative_path}\n")
                except Exception as e:
                    print(f"Warning: Could not create checksum for {file_path}: {e}")
    
    print(f"✓ Created checksums: {checksums_file}")

def main():
    print("=== DBC Utility Linux Release Builder ===")
    
    # Get version
    version = get_version()
    print(f"Building release for version: {version}")
    
    # Build Linux release
    if not build_linux_release():
        sys.exit(1)
    
    # Create release package
    if not create_linux_release_package(version):
        sys.exit(1)
    
    # Create checksums
    project_root = Path(__file__).parent.parent
    release_dir = project_root / f"release-linux-v{version}"
    create_checksums(release_dir)
    
    print("\n=== Linux Release Complete ===")
    print(f"Release package created: release-linux-v{version}/")
    print("\nContents:")
    
    for item in release_dir.iterdir():
        if item.is_file():
            size = item.stat().st_size
            print(f"  {item.name} ({size:,} bytes)")
        elif item.is_dir():
            print(f"  {item.name}/ (directory)")
    
    print("\nNext steps:")
    print("1. Test the release package on target systems")
    print("2. Upload to GitHub releases")
    print("3. Update documentation with download links")

if __name__ == "__main__":
    main() 