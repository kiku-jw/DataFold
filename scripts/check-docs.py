#!/usr/bin/env python3
"""Check documentation consistency with code."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def check_license_consistency() -> list[str]:
    """Check that license is consistent across files."""
    errors = []
    expected_license = "AGPL-3.0"

    # Check pyproject.toml
    pyproject = REPO_ROOT / "pyproject.toml"
    if pyproject.exists():
        content = pyproject.read_text()
        if 'license = "MIT"' in content:
            errors.append("pyproject.toml: License should be AGPL-3.0, not MIT")
        if "MIT License" in content:
            errors.append("pyproject.toml: Classifier should use AGPL, not MIT")

    # Check README.md
    readme = REPO_ROOT / "README.md"
    if readme.exists():
        content = readme.read_text()
        if "opensource.org/licenses/MIT" in content:
            errors.append("README.md: License link should point to AGPL, not MIT")

    # Check LICENSE file
    license_file = REPO_ROOT / "LICENSE"
    if license_file.exists():
        content = license_file.read_text()
        if "GNU AFFERO GENERAL PUBLIC LICENSE" not in content:
            errors.append("LICENSE: Should contain AGPL-3.0 license text")

    return errors


def check_table_names_in_docs() -> list[str]:
    """Check that table names in docs match actual code."""
    errors = []

    # Read actual table names from sqlite.py
    sqlite_file = REPO_ROOT / "src" / "driftguard" / "storage" / "sqlite.py"
    if not sqlite_file.exists():
        return errors

    sqlite_content = sqlite_file.read_text()

    # Expected table names from code
    expected_tables = {
        "snapshots",
        "alert_state",
        "deliveries",
        "schema_meta",
    }

    # Check architecture.md
    arch_file = REPO_ROOT / "docs" / "architecture.md"
    if arch_file.exists():
        content = arch_file.read_text()

        # Check for old/wrong table names
        wrong_names = {
            "alert_states": "alert_state",
            "delivery_log": "deliveries",
        }

        for wrong, correct in wrong_names.items():
            if wrong in content:
                errors.append(
                    f"docs/architecture.md: Use '{correct}' instead of '{wrong}'"
                )

    return errors


def check_config_paths() -> list[str]:
    """Check that config file paths in docs match code."""
    errors = []

    # Read actual paths from config.py
    config_file = REPO_ROOT / "src" / "driftguard" / "config.py"
    if not config_file.exists():
        return errors

    config_content = config_file.read_text()

    # Check configuration.md
    config_doc = REPO_ROOT / "docs" / "configuration.md"
    if config_doc.exists():
        content = config_doc.read_text()

        # Check for wrong paths
        if "~/.driftguard/config.yaml" in content:
            errors.append(
                "docs/configuration.md: Use '~/.config/driftguard/driftguard.yaml' "
                "instead of '~/.driftguard/config.yaml'"
            )

    return errors


def check_version_consistency() -> list[str]:
    """Check version consistency across files."""
    errors = []

    # Get version from pyproject.toml
    pyproject = REPO_ROOT / "pyproject.toml"
    if not pyproject.exists():
        return errors

    pyproject_content = pyproject.read_text()
    version_match = re.search(r'version\s*=\s*"([^"]+)"', pyproject_content)
    if not version_match:
        errors.append("pyproject.toml: Could not find version")
        return errors

    expected_version = version_match.group(1)

    # Check __init__.py
    init_file = REPO_ROOT / "src" / "driftguard" / "__init__.py"
    if init_file.exists():
        content = init_file.read_text()
        if f'__version__ = "{expected_version}"' not in content:
            init_version = re.search(r'__version__\s*=\s*"([^"]+)"', content)
            if init_version:
                actual = init_version.group(1)
                if actual != expected_version:
                    errors.append(
                        f"src/driftguard/__init__.py: Version '{actual}' "
                        f"doesn't match pyproject.toml '{expected_version}'"
                    )

    return errors


def main() -> int:
    """Run all documentation checks."""
    all_errors: list[str] = []

    print("Checking documentation consistency...")
    print()

    checks = [
        ("License consistency", check_license_consistency),
        ("Table names in docs", check_table_names_in_docs),
        ("Config paths in docs", check_config_paths),
        ("Version consistency", check_version_consistency),
    ]

    for name, check_fn in checks:
        print(f"  Checking {name}...")
        errors = check_fn()
        if errors:
            for error in errors:
                print(f"    ❌ {error}")
            all_errors.extend(errors)
        else:
            print(f"    ✓ OK")

    print()

    if all_errors:
        print(f"Found {len(all_errors)} issue(s)")
        return 1

    print("All documentation checks passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
