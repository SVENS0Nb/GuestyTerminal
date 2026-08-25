#!/usr/bin/env python3
"""Validate release metadata and build deterministic GitHub release notes."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
FIRMWARE_VERSION_PATTERN = re.compile(
    r'^FIRMWARE_VERSION\s*=\s*["\'](?P<version>\d+\.\d+\.\d+)["\']\s*$',
    re.MULTILINE,
)
PROJECT_VERSION_PATTERN = re.compile(
    r"(?ms)^\s{2}project:\s*$.*?^\s{4}version:\s*[\"']?"
    r"(?P<version>\d+\.\d+\.\d+)[\"']?\s*$"
)
CHANGELOG_RELEASE_PATTERN = re.compile(
    r"(?m)^## (?P<version>\d+\.\d+\.\d+)\s+[–-]\s+[^\n]+$"
)
RELEASE_PERMISSION_MARKER = "PUBLIC_PROPRIETARY_SOURCE_RELEASES_PERMITTED"


class ReleaseValidationError(RuntimeError):
    """Raised when repository release metadata is inconsistent."""


@dataclass(frozen=True)
class ReleaseMetadata:
    """Validated release metadata used by CI and the release workflow."""

    version: str
    changelog_body: str


def _read_text(root: Path, relative_path: str) -> str:
    path = root / relative_path
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as err:
        raise ReleaseValidationError(
            f"Required release file cannot be read: {relative_path}"
        ) from err
    if not text.strip():
        raise ReleaseValidationError(f"Required release file is empty: {relative_path}")
    return text


def _single_match_version(text: str, pattern: re.Pattern[str], source: str) -> str:
    matches = [match.group("version") for match in pattern.finditer(text)]
    if len(matches) != 1:
        raise ReleaseValidationError(
            f"Expected exactly one version marker in {source}, found {len(matches)}"
        )
    return matches[0]


def validate_release(
    root: Path, *, expected_version: str | None = None
) -> ReleaseMetadata:
    """Validate version, distribution, notice, and release-note invariants."""

    root = root.resolve()
    manifest_path = "custom_components/guesty_terminal/manifest.json"
    try:
        manifest = json.loads(_read_text(root, manifest_path))
    except json.JSONDecodeError as err:
        raise ReleaseValidationError(f"Invalid JSON in {manifest_path}") from err
    manifest_version = manifest.get("version")
    if not isinstance(manifest_version, str) or not SEMVER_PATTERN.fullmatch(
        manifest_version
    ):
        raise ReleaseValidationError("Manifest version must be semantic X.Y.Z")

    versions = {
        manifest_path: manifest_version,
        "custom_components/guesty_terminal/firmware.py": _single_match_version(
            _read_text(root, "custom_components/guesty_terminal/firmware.py"),
            FIRMWARE_VERSION_PATTERN,
            "custom_components/guesty_terminal/firmware.py",
        ),
        "esphome/guestyterminal-display-1.yaml": _single_match_version(
            _read_text(root, "esphome/guestyterminal-display-1.yaml"),
            PROJECT_VERSION_PATTERN,
            "esphome/guestyterminal-display-1.yaml",
        ),
    }
    mismatches = {
        source: version
        for source, version in versions.items()
        if version != manifest_version
    }
    if mismatches:
        details = ", ".join(
            f"{source}={version}" for source, version in sorted(mismatches.items())
        )
        raise ReleaseValidationError(
            f"Release versions do not match {manifest_version}: {details}"
        )
    if expected_version is not None and expected_version != manifest_version:
        raise ReleaseValidationError(
            f"Expected version {expected_version}, repository has {manifest_version}"
        )

    changelog = _read_text(root, "CHANGELOG.md")
    changelog_matches = list(CHANGELOG_RELEASE_PATTERN.finditer(changelog))
    if (
        not changelog_matches
        or changelog_matches[0].group("version") != manifest_version
    ):
        raise ReleaseValidationError(
            f"The first CHANGELOG release must be {manifest_version}"
        )
    start = changelog_matches[0].end()
    end = changelog_matches[1].start() if len(changelog_matches) > 1 else len(changelog)
    changelog_body = changelog[start:end].strip()
    if not changelog_body:
        raise ReleaseValidationError("Current CHANGELOG release has no notes")

    readme = _read_text(root, "README.md")
    if f"Version **{manifest_version}**" not in readme:
        raise ReleaseValidationError(
            f"README.md has no current Version **{manifest_version}** release section"
        )
    contributing = _read_text(root, "CONTRIBUTING.md")
    if f"Version {manifest_version}" not in contributing:
        raise ReleaseValidationError(
            f"CONTRIBUTING.md has no current Version {manifest_version} release note"
        )

    license_status = _read_text(root, "LICENSE_STATUS.md")
    if RELEASE_PERMISSION_MARKER not in license_status:
        raise ReleaseValidationError(
            "LICENSE_STATUS.md lacks the explicit proprietary-source release marker"
        )
    for notice_path in (
        "THIRD_PARTY_NOTICES.md",
        "esphome/components/guesty_epaper_gray4/LICENSE",
        "esphome/components/guesty_epaper_gray4/SEEED_GFX_LICENSE.txt",
    ):
        _read_text(root, notice_path)

    firmware_requirements = _read_text(root, "requirements-firmware.txt")
    pins = [
        line.strip()
        for line in firmware_requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(pins) != 1 or not re.fullmatch(r"esphome==\d+\.\d+\.\d+", pins[0]):
        raise ReleaseValidationError(
            "requirements-firmware.txt must contain one exact ESPHome pin"
        )

    return ReleaseMetadata(version=manifest_version, changelog_body=changelog_body)


def build_release_notes(metadata: ReleaseMetadata, hardware_status: str) -> str:
    """Build release notes with an explicit real-device validation disclosure."""

    if hardware_status == "passed":
        hardware_copy = (
            "Die für diese Version dokumentierte Hardwarematrix wurde auf einem "
            "realen Seeed Studio reTerminal E1001 erfolgreich geprüft."
        )
    elif hardware_status == "not_tested":
        hardware_copy = (
            "Diese Version wurde kompiliert, aber noch nicht vollständig auf einem "
            "realen Seeed Studio reTerminal E1001 geprüft. Diese Einschränkung ist "
            "vor der Installation auf produktiven Displays zu beachten."
        )
    else:
        raise ReleaseValidationError(f"Unknown hardware status: {hardware_status}")

    return (
        f"{metadata.changelog_body}\n\n"
        "## Hardwareprüfung\n\n"
        f"{hardware_copy}\n\n"
        "## Distribution\n\n"
        "GuestyTerminal wird als proprietärer Quellcode ohne projektweite "
        "Nutzungslizenz veröffentlicht. Die Hinweise in `LICENSE_STATUS.md` und "
        "`THIRD_PARTY_NOTICES.md` sowie die lokalen Treiberlizenzen gelten "
        "unverändert.\n"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--expected-version")
    parser.add_argument("--print-version", action="store_true")
    parser.add_argument("--hardware-status", choices=("passed", "not_tested"))
    parser.add_argument("--notes-output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    metadata = validate_release(args.root, expected_version=args.expected_version)
    if args.notes_output is not None:
        if args.hardware_status is None:
            raise ReleaseValidationError(
                "--notes-output requires an explicit --hardware-status"
            )
        notes = build_release_notes(metadata, args.hardware_status)
        args.notes_output.write_text(notes, encoding="utf-8")
    if args.print_version:
        print(metadata.version)
    else:
        print(f"Release preflight passed for {metadata.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
