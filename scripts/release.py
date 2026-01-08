#!/usr/bin/env python3

"""
Release script for DBC Utility
Automates the release process including building and versioning.
"""

import os
import sys
import subprocess
import shutil
import re
from datetime import datetime
from pathlib import Path

def get_version():
    """Get current version from pyproject.toml"""
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pyproject_path = Path(project_root) / "pyproject.toml"
        
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

def build_release():
    """Build the release executable"""
    print("=== Building Release Executable ===")
    
    # Change to project root
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(project_root)
    
    # Run build script
    try:
        subprocess.run([sys.executable, "scripts/build_exe.py"], check=True)
        print("✓ Build completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Build failed: {e}")
        return False

def create_release_package(version):
    """Create release package with versioned executable"""
    print(f"=== Creating Release Package v{version} ===")
    
    # Create release directory
    release_dir = f"release-v{version}"
    if os.path.exists(release_dir):
        shutil.rmtree(release_dir)
    os.makedirs(release_dir)
    
    # Copy executable with version
    exe_source = "dist/DBCUtility.exe"
    exe_dest = f"{release_dir}/DBCUtility-v{version}.exe"
    
    if os.path.exists(exe_source):
        shutil.copy2(exe_source, exe_dest)
        print(f"✓ Copied executable: DBCUtility-v{version}.exe")
    else:
        print(f"✗ Executable not found: {exe_source}")
        return False
    
    # Copy README and LICENSE
    files_to_copy = ['README.md', 'LICENSE', 'CHANGELOG.md']
    for file in files_to_copy:
        if os.path.exists(file):
            shutil.copy2(file, release_dir)
            print(f"✓ Copied {file}")
    
    # Create release notes
    create_release_notes(release_dir, version)
    
    # Create zip package
    create_zip_package(release_dir, version)
    
    print(f"✓ Release package created: {release_dir}/")
    return True

def create_release_notes(release_dir, version):
    """Create release notes file"""
    release_notes = f"""DBC Utility v{version} Release Notes

Release Date: {datetime.now().strftime('%Y-%m-%d')}

## What's New in v{version}

This is the initial release of DBC Utility, a comprehensive CAN database editor.

### Features
- DBC file viewer with tree structure
- Full DBC file editor with CRUD operations
- Advanced search functionality

- Modern PyQt5-based GUI
- Icon support for all buttons
- File management (load, save, save-as)
- Automatic backup file cleanup

### System Requirements
- Windows 10/11 (64-bit)
- No additional dependencies required (standalone executable)

### Installation
1. Download DBCUtility-v{version}.exe
2. Run the executable directly
3. No installation required

### Usage
- Use "Load DBC File" to open your DBC files
- Browse messages and signals in the View tab
- Edit messages and signals in the Edit tab
- Use the search functionality to find specific items


### License
This software is licensed under GNU General Public License v3 (GPL v3).
See LICENSE file for details.

### Support
For issues and feature requests, please visit the project repository.
"""
    
    with open(f"{release_dir}/RELEASE_NOTES.txt", 'w', encoding='utf-8') as f:
        f.write(release_notes)
    
    print("✓ Created RELEASE_NOTES.txt")

def create_zip_package(release_dir, version):
    """Create a zip package for the release"""
    print(f"=== Creating Zip Package ===")
    
    # Zip file name
    zip_filename = f"DBCUtility-v{version}.zip"
    
    # Create zip file
    try:
        import zipfile
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add all files from release directory
            for root, dirs, files in os.walk(release_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    # Add file to zip with relative path
                    arcname = os.path.relpath(file_path, release_dir)
                    zipf.write(file_path, arcname)
                    print(f"✓ Added to zip: {arcname}")
        
        # Get file size
        file_size = os.path.getsize(zip_filename)
        size_mb = file_size / (1024 * 1024)
        
        print(f"✓ Zip package created: {zip_filename}")
        print(f"✓ File size: {size_mb:.1f} MB")
        
    except Exception as e:
        print(f"✗ Failed to create zip: {e}")

def main():
    """Main release process"""
    print("=== DBC Utility Release Process ===")
    
    # Get current version
    version = get_version()
    print(f"Current version: {version}")
    
    # Build executable
    if not build_release():
        sys.exit(1)
    
    # Create release package
    if not create_release_package(version):
        sys.exit(1)
    
    print(f"\n=== Release v{version} Complete ===")
    print(f"Release package: release-v{version}/")
    print("Next steps:")
    print("1. Test the release executable")
    print("2. Create a GitHub release")
    print("3. Upload the release package")
    print("4. Update version in pyproject.toml for next release")

if __name__ == "__main__":
    main() 