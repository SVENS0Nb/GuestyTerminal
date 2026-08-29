from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.release_preflight import (
    RELEASE_PERMISSION_MARKER,
    ReleaseValidationError,
    build_release_notes,
    validate_release,
)

ROOT = Path(__file__).resolve().parents[1]


def test_current_repository_release_metadata_is_consistent() -> None:
    metadata = validate_release(ROOT, expected_version="0.3.53")

    assert metadata.version == "0.3.53"
    assert "Native Graustufen und saubere Schriftkanten" in metadata.changelog_body
    assert "Wiederkehrenden Panelrand behandeln" in metadata.changelog_body
    assert "Prüfung und Installation" in metadata.changelog_body


@pytest.mark.parametrize("hardware_status", ["passed", "not_tested"])
def test_release_notes_disclose_hardware_and_distribution(
    hardware_status: str,
) -> None:
    metadata = validate_release(ROOT)

    notes = build_release_notes(metadata, hardware_status)

    assert "## Hardwareprüfung" in notes
    assert "## Distribution" in notes
    assert "proprietärer Quellcode" in notes
    if hardware_status == "passed":
        assert "erfolgreich geprüft" in notes
    else:
        assert "noch nicht vollständig" in notes


def test_release_validation_rejects_version_mismatch(tmp_path: Path) -> None:
    _copy_release_inputs(tmp_path)
    manifest_path = tmp_path / "custom_components/guesty_terminal/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["version"] = "9.9.9"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ReleaseValidationError, match="versions do not match"):
        validate_release(tmp_path)


def test_release_validation_requires_owner_decision_marker(tmp_path: Path) -> None:
    _copy_release_inputs(tmp_path)
    status_path = tmp_path / "LICENSE_STATUS.md"
    status_path.write_text(
        status_path.read_text(encoding="utf-8").replace(RELEASE_PERMISSION_MARKER, ""),
        encoding="utf-8",
    )

    with pytest.raises(ReleaseValidationError, match="release marker"):
        validate_release(tmp_path)


def test_release_notes_reject_unknown_hardware_status() -> None:
    metadata = validate_release(ROOT)

    with pytest.raises(ReleaseValidationError, match="Unknown hardware status"):
        build_release_notes(metadata, "maybe")


def _copy_release_inputs(destination: Path) -> None:
    for relative_path in (
        "custom_components/guesty_terminal/manifest.json",
        "custom_components/guesty_terminal/firmware.py",
        "esphome/guestyterminal-display-1.yaml",
        "esphome/components/guesty_epaper_gray4/LICENSE",
        "esphome/components/guesty_epaper_gray4/SEEED_GFX_LICENSE.txt",
        "CHANGELOG.md",
        "README.md",
        "CONTRIBUTING.md",
        "LICENSE_STATUS.md",
        "THIRD_PARTY_NOTICES.md",
        "requirements-firmware.txt",
    ):
        target = destination / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative_path).read_bytes())
