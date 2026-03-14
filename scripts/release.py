#!/usr/bin/env python3

"""
Windows Release Script for DBC Utility.

Builds the executable and assembles a versioned release package that includes
the real project documentation (README, LICENSE, CHANGELOG, release notes).
"""

import os
import sys
import subprocess
import shutil
import re
import zipfile
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

def build_release() -> bool:
    print("=== Building Release Executable ===")
    os.chdir(get_project_root())
    try:
        subprocess.run([sys.executable, "scripts/build_exe.py"], check=True)
        print("✓ Build completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Build failed: {e}")
        return False


# ── Package ───────────────────────────────────────────────────────────────

def create_release_package(version: str) -> bool:
    print(f"\n=== Creating Release Package v{version} ===")
    root = get_project_root()
    release_dir = root / f"release-v{version}"

    if release_dir.exists():
        shutil.rmtree(release_dir)
    release_dir.mkdir()

    exe_source = root / "dist" / "DBCUtility.exe"
    exe_dest = release_dir / f"DBCUtility-v{version}.exe"
    if exe_source.exists():
        shutil.copy2(exe_source, exe_dest)
        print(f"✓ Copied executable: {exe_dest.name}")
    else:
        print(f"✗ Executable not found: {exe_source}")
        return False

    copy_documentation(release_dir, version)
    create_zip_package(release_dir, version)

    print(f"\n✓ Release package created: {release_dir}/")
    return True


def copy_documentation(release_dir: Path, version: str) -> None:
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


def create_zip_package(release_dir: Path, version: str) -> None:
    print("\n=== Creating Zip Package ===")
    zip_path = release_dir.parent / f"DBCUtility-Windows-v{version}.zip"

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(release_dir.rglob("*")):
                if file_path.is_file():
                    arcname = file_path.relative_to(release_dir)
                    zf.write(file_path, arcname)
                    print(f"  + {arcname}")

        size_mb = zip_path.stat().st_size / (1024 * 1024)
        print(f"✓ Zip created: {zip_path.name} ({size_mb:.1f} MB)")
    except Exception as e:
        print(f"✗ Failed to create zip: {e}")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print("=== DBC Utility Windows Release Process ===\n")

    version = get_version()
    print(f"Version : {version}")

    notes_path = get_release_notes_path(version)
    print(f"Notes   : {notes_path}{' ✓' if notes_path.exists() else ' (will extract from CHANGELOG)'}")
    print()

    if not build_release():
        sys.exit(1)

    if not create_release_package(version):
        sys.exit(1)

    print(f"\n=== Release v{version} Complete ===")
    print(f"  Package dir : release-v{version}/")
    print(f"  Zip archive : DBCUtility-Windows-v{version}.zip")
    print()
    print("Next steps:")
    print("  1. Test the release executable")
    print("  2. Create a GitHub release")
    print("  3. Upload the zip archive")


if __name__ == "__main__":
    main()
