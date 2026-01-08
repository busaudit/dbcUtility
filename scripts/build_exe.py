#!/usr/bin/env python3
"""
Build script for creating DBCUtility executable using PyInstaller
"""

import os
import sys
import subprocess
import shutil

def check_pyinstaller():
    """Check if PyInstaller is installed"""
    try:
        import PyInstaller
        print("✓ PyInstaller is installed")
        return True
    except ImportError:
        print("✗ PyInstaller is not installed")
        print("Installing PyInstaller...")
        try:
            # Try UV first, fall back to pip
            try:
                subprocess.check_call(["uv", "pip", "install", "pyinstaller"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("✓ PyInstaller installed successfully using UV")
                return True
            except (subprocess.CalledProcessError, FileNotFoundError):
                # Fall back to pip
                subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
                print("✓ PyInstaller installed successfully using pip")
                return True
        except subprocess.CalledProcessError:
            print("✗ Failed to install PyInstaller")
            return False

def clean_build_dirs():
    """Clean previous build directories and exe files"""
    # Change to parent directory (project root)
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(project_root)
    
    # Clean build directories
    dirs_to_clean = ['build', 'dist']
    for dir_name in dirs_to_clean:
        if os.path.exists(dir_name):
            print(f"Cleaning {dir_name} directory...")
            shutil.rmtree(dir_name)
            print(f"✓ Cleaned {dir_name}")
    
    # Clean existing exe files in project root
    exe_files = [f for f in os.listdir('.') if f.endswith('.exe')]
    for exe_file in exe_files:
        try:
            print(f"Deleting existing exe file: {exe_file}")
            os.remove(exe_file)
            print(f"✓ Deleted {exe_file}")
        except Exception as e:
            print(f"Warning: Could not delete {exe_file}: {e}")

def build_executable():
    """Build the executable using PyInstaller"""
    print("Building executable...")
    
    # Change to parent directory (project root)
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # Use the spec file if it exists, otherwise use direct command
    if os.path.exists('DBCUtility.spec'):
        cmd = [sys.executable, "-m", "PyInstaller", "DBCUtility.spec"]
    else:
        # Determine the separator for --add-data based on OS
        import platform
        if platform.system() == "Windows":
            data_sep = ";"
        else:
            data_sep = ":"
        
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--onefile",
            "--windowed",
            "--name=DBCUtility",
            "--icon=icons/app_icon.ico",
            f"--add-data=icons{data_sep}icons",
            f"--add-data=pyproject.toml{data_sep}.",
            "--paths=src",  # Add src directory to Python path
            "--hidden-import=PyQt5.QtCore",
            "--hidden-import=PyQt5.QtGui",
            "--hidden-import=PyQt5.QtWidgets",
            "--hidden-import=cantools",
            "--hidden-import=search_module",
            "--hidden-import=dbc_editor_ui",
            "--hidden-import=dbc_editor",
            "main.py"
        ]
    
    try:
        subprocess.check_call(cmd)
        print("✓ Executable built successfully!")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to build executable: {e}")
        return False

def main():
    print("=== DBCUtility Executable Builder ===")
    
    # Check if PyInstaller is available
    if not check_pyinstaller():
        sys.exit(1)
    
    # Clean previous builds
    clean_build_dirs()
    
    # Build the executable
    if build_executable():
        print("\n=== Build Complete ===")
        print("Executable location: dist/DBCUtility.exe")
        print("You can now run the executable from the dist folder.")
    else:
        print("\n=== Build Failed ===")
        sys.exit(1)

if __name__ == "__main__":
    main() 