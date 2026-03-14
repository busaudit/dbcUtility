#!/usr/bin/env python3

"""
Linux Release Script for DBC Utility.

Builds the Linux distribution and assembles a versioned release package that
includes the real project documentation (README, LICENSE, CHANGELOG, release
notes) plus tar.gz and optional AppImage artifacts.
"""

import hashlib
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path


def get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def get_version() -> str:
    """Read the canonical version from pyproject.toml."""
    pyproject = get_project_root() / "pyproject.toml"
    if not pyproject.exists():
        print(f"Error: pyproject.toml not found at {pyproject}")
        sys.exit(1)

    content = pyproject.read_text(encoding="utf-8")
    match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
    if not match:
        print("Error: could not parse version from pyproject.toml")
        sys.exit(1)
    return match.group(1)


def get_release_notes_path(version: str) -> Path:
    """Return path to docs/RELEASE_NOTES_v{version}.md (may not exist)."""
    return get_project_root() / "docs" / f"RELEASE_NOTES_v{version}.md"


def extract_changelog_section(version: str) -> str:
    """Extract the section for *version* from CHANGELOG.md.

    Falls back to the full changelog content if the section heading is not
    found.
    """
    changelog = get_project_root() / "CHANGELOG.md"
    if not changelog.exists():
        return ""

    text = changelog.read_text(encoding="utf-8")

    header_pattern = re.compile(
        rf"^##\s*\[{re.escape(version)}\]", re.MULTILINE
    )
    match = header_pattern.search(text)
    if not match:
        return text

    start = match.start()
    next_header = re.search(r"^## \[", text[match.end() :], re.MULTILINE)
    end = match.end() + next_header.start() if next_header else len(text)
    return text[start:end].strip()


# ── Build ─────────────────────────────────────────────────────────────────

def build_linux_release() -> bool:
    print("=== Building Linux Release ===")
    os.chdir(get_project_root())
    try:
        subprocess.run([sys.executable, "scripts/build_linux.py"], check=True)
        print("✓ Linux build completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Linux build failed: {e}")
        return False


# ── Package ───────────────────────────────────────────────────────────────

def create_linux_release_package(version: str) -> bool:
    print(f"\n=== Creating Linux Release Package v{version} ===")
    root = get_project_root()
    linux_builds_dir = root / "linuxBuilds"

    dist_folders = list(linux_builds_dir.glob("DBCUtility-Linux-*"))
    if not dist_folders:
        print("✗ No Linux distribution found. Run build_linux.py first.")
        return False

    dist_folder = dist_folders[0]
    arch = dist_folder.name.split("-")[-1]

    release_dir = root / f"release-linux-v{version}"
    if release_dir.exists():
        shutil.rmtree(release_dir)
    release_dir.mkdir()

    versioned_dist_name = f"DBCUtility-Linux-{arch}-v{version}"
    versioned_dist_dir = release_dir / versioned_dist_name

    shutil.copytree(dist_folder, versioned_dist_dir)
    print(f"✓ Copied distribution: {versioned_dist_name}")

    copy_documentation(release_dir, version, arch)
    create_tar_package(release_dir, versioned_dist_name)
    create_appimage_package(versioned_dist_dir, version, arch)

    print(f"\n✓ Linux release package created: {release_dir}/")
    return True


def copy_documentation(release_dir: Path, version: str, arch: str) -> None:
    """Copy all relevant documentation into the release directory."""
    root = get_project_root()

    doc_files = {
        "README.md": root / "README.md",
        "LICENSE": root / "LICENSE",
        "CHANGELOG.md": root / "CHANGELOG.md",
    }

    for dest_name, src_path in doc_files.items():
        if src_path.exists():
            shutil.copy2(src_path, release_dir / dest_name)
            print(f"✓ Copied {dest_name}")
        else:
            print(f"  Skipped {dest_name} (not found)")

    notes_src = get_release_notes_path(version)
    notes_dest = release_dir / f"RELEASE_NOTES_v{version}.md"
    if notes_src.exists():
        shutil.copy2(notes_src, notes_dest)
        print(f"✓ Copied {notes_dest.name} from docs/")
    else:
        section = extract_changelog_section(version)
        if section:
            notes_dest.write_text(section, encoding="utf-8")
            print(f"✓ Generated {notes_dest.name} from CHANGELOG.md")
        else:
            print(f"  Skipped release notes (no docs/RELEASE_NOTES_v{version}.md and no changelog section)")

    github_notes = release_dir / f"GITHUB_RELEASE_BODY_v{version}.md"
    github_notes.write_text(
        _build_github_release_body(version, arch), encoding="utf-8"
    )
    print(f"✓ Generated {github_notes.name} (paste into GitHub release)")


def _build_github_release_body(version: str, arch: str) -> str:
    """Build a ready-to-paste GitHub release body from real docs."""
    section = extract_changelog_section(version)
    if not section:
        section = f"See CHANGELOG.md for full details on v{version}."

    return f"""# DBC Utility v{version}

## Downloads

### Windows
- **DBCUtility-Windows-v{version}.zip** — Standalone executable (no install required)

### Linux
- **DBCUtility-Linux-{arch}-v{version}.tar.gz** — Portable distribution
- **DBCUtility-Linux-{arch}-v{version}.AppImage** — AppImage (if available)

## Quick Start

### Windows
1. Download and extract `DBCUtility-Windows-v{version}.zip`
2. Run `DBCUtility-v{version}.exe`

### Linux
1. Extract: `tar -xzf DBCUtility-Linux-{arch}-v{version}.tar.gz`
2. Install: `cd DBCUtility-Linux-{arch}-v{version} && ./install.sh`
3. Or run directly: `./launch-dbc-utility.sh`

## Changes

{section}

## System Requirements

| Platform | Requirement |
|----------|-------------|
| Windows  | Windows 10 or later, ~100 MB disk space |
| Linux    | Kernel 3.0+, glibc 2.17+, X11/Wayland, ~100 MB disk space |

For detailed release notes see `RELEASE_NOTES_v{version}.md` in the download.
"""


# ── Tar / AppImage ────────────────────────────────────────────────────────

def create_tar_package(release_dir: Path, dist_name: str) -> None:
    print("\nCreating tar.gz package...")
    tar_path = release_dir / f"{dist_name}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(release_dir / dist_name, arcname=dist_name)
    print(f"✓ Created {tar_path.name}")


def create_appimage_package(dist_dir: Path, version: str, arch: str) -> None:
    print("\nAttempting to create AppImage...")
    try:
        subprocess.run(
            ["appimagetool", "--version"], capture_output=True, check=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("⚠  appimagetool not found — skipping AppImage creation.")
        print("   Install: https://github.com/AppImage/AppImageKit/releases")
        return

    try:
        appdir = dist_dir.parent / "DBCUtility.AppDir"
        if appdir.exists():
            shutil.rmtree(appdir)

        shutil.copytree(dist_dir, appdir / "usr" / "bin" / "DBCUtility")

        apprun = appdir / "AppRun"
        apprun.write_text(
            '#!/bin/bash\ncd "$(dirname "$0")"\n'
            'exec ./usr/bin/DBCUtility/DBCUtility "$@"\n'
        )
        os.chmod(apprun, 0o755)

        desktop = appdir / "usr" / "share" / "applications" / "DBCUtility.desktop"
        desktop.parent.mkdir(parents=True, exist_ok=True)
        desktop.write_text(
            "[Desktop Entry]\nVersion=1.0\nType=Application\n"
            "Name=DBC Utility\nComment=CAN Database Editor\n"
            "Exec=DBCUtility\nIcon=DBCUtility\nTerminal=false\n"
            "Categories=Development;Engineering;\n"
        )

        icon_dest = (
            appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
        )
        icon_dest.mkdir(parents=True, exist_ok=True)
        for candidate in (
            dist_dir / "icons" / "app_icon.png",
            dist_dir / "app_icon.png",
            get_project_root() / "icons" / "app_icon.png",
        ):
            if candidate.exists():
                shutil.copy2(candidate, icon_dest / "DBCUtility.png")
                break

        appimage_name = f"DBCUtility-Linux-{arch}-v{version}.AppImage"
        subprocess.run(
            ["appimagetool", str(appdir), str(dist_dir.parent / appimage_name)],
            check=True,
        )
        print(f"✓ Created AppImage: {appimage_name}")
    except Exception as e:
        print(f"✗ AppImage creation failed: {e}")
        print("  Continuing with tar.gz distribution only...")


# ── Checksums ─────────────────────────────────────────────────────────────

def create_checksums(release_dir: Path) -> None:
    print("\nCreating checksums...")
    checksums_file = release_dir / "checksums.sha256"
    lines = [
        f"# DBC Utility Release Checksums",
        f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    for fp in sorted(release_dir.rglob("*")):
        if fp.is_file() and fp.name != "checksums.sha256":
            sha = hashlib.sha256(fp.read_bytes()).hexdigest()
            lines.append(f"{sha}  {fp.relative_to(release_dir)}")

    checksums_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"✓ Created {checksums_file.name}")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print("=== DBC Utility Linux Release Builder ===\n")

    version = get_version()
    print(f"Version : {version}")

    notes_path = get_release_notes_path(version)
    print(f"Notes   : {notes_path}{' ✓' if notes_path.exists() else ' (will extract from CHANGELOG)'}")
    print()

    if not build_linux_release():
        sys.exit(1)

    if not create_linux_release_package(version):
        sys.exit(1)

    release_dir = get_project_root() / f"release-linux-v{version}"
    create_checksums(release_dir)

    print(f"\n=== Linux Release v{version} Complete ===")
    print(f"\nContents of {release_dir.name}/:")
    for item in sorted(release_dir.iterdir()):
        if item.is_file():
            size_kb = item.stat().st_size / 1024
            print(f"  {item.name:50s} {size_kb:>8.1f} KB")
        else:
            print(f"  {item.name}/")

    print("\nNext steps:")
    print("  1. Test the release on target Linux systems")
    print(f"  2. Create a GitHub release and paste GITHUB_RELEASE_BODY_v{version}.md")
    print("  3. Upload the tar.gz (and AppImage if created)")


if __name__ == "__main__":
    main()
