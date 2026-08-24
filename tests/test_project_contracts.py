"""Repository-wide compatibility and localization contracts."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "guesty_terminal"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _shape(value: object) -> object:
    if isinstance(value, dict):
        return {key: _shape(child) for key, child in value.items()}
    return None


def test_strings_are_canonical_english_translation() -> None:
    """Keep Home Assistant's canonical strings and English catalog identical."""
    assert _load_json(INTEGRATION / "strings.json") == _load_json(
        INTEGRATION / "translations" / "en.json"
    )


def test_all_translation_catalogs_have_the_same_shape() -> None:
    """Every supported UI language must contain every translation key."""
    expected = _shape(_load_json(INTEGRATION / "strings.json"))
    for language in ("de", "en", "es", "fr"):
        assert (
            _shape(_load_json(INTEGRATION / "translations" / f"{language}.json"))
            == expected
        )


def test_ci_exercises_minimum_home_assistant_and_real_firmware_build() -> None:
    """Prevent compatibility and firmware compilation checks from disappearing."""
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )
    assert 'homeassistant-version: "2025.12.0"' in workflow
    assert 'homeassistant-version: "2026.2.3"' in workflow
    assert "constraints-homeassistant-2025.12.txt" in workflow
    assert "mypy custom_components/guesty_terminal" in workflow
    minimum_constraints = (ROOT / "constraints-homeassistant-2025.12.txt").read_text(
        encoding="utf-8"
    )
    assert "litellm==1.94.3" in minimum_constraints
    assert "pycares<5" in minimum_constraints
    assert "esphome config esphome/guestyterminal-display-1.yaml" in workflow
    assert "esphome compile esphome/guestyterminal-display-1.yaml" in workflow
    assert "-name firmware.ota.bin" in workflow
    assert 'test "$firmware_size" -le "$maximum_budget"' in workflow
    assert "GENERATE_A_32_BYTE_BASE64_KEY" in (
        ROOT / "esphome" / "secrets.example.yaml"
    ).read_text(encoding="utf-8")
    assert "sed -i 's/GENERATE_A_32_BYTE_BASE64_KEY/" in workflow


def test_maintenance_guidance_covers_current_critical_contracts() -> None:
    """Keep current routing, power, testing and distribution rules discoverable."""
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for phrase in (
        "one timezone-aware UTC timestamp",
        "`unitId`, then a direct/legacy `listingId`",
        "`unitTypeId`, then",
        "`parentListingId`",
        "`REG0A.BUS_GD`",
        "16 averaged ADC samples",
        "`Wake-up reason`, and `Awake duration`",
        "mypy custom_components/guesty_terminal",
        "version-specific tests, `CHANGELOG.md`",
        "Before any public release or redistribution",
        "unresolved right or redistribution",
    ):
        assert phrase in agents

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for document in (
        "AGENTS.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        "SECURITY.md",
        "LICENSE_STATUS.md",
        "THIRD_PARTY_NOTICES.md",
    ):
        assert f"[`{document}`](" in readme

    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "Home Assistant 2025.12.0" in contributing
    assert "2026.2.3" in contributing
    assert "mypy custom_components/guesty_terminal" in contributing
    assert "python3 -m compileall -q custom_components/guesty_terminal" in contributing
    assert "LICENSE_STATUS.md" in contributing
    assert "THIRD_PARTY_NOTICES.md" in contributing


def test_epaper_driver_has_only_documented_redistributable_sources() -> None:
    """Keep the former ambiguous driver dependency out of current sources."""
    component = ROOT / "esphome" / "components" / "guesty_epaper_gray4"
    for path in (
        component / "guesty_epaper_gray4.cpp",
        component / "guesty_epaper_gray4.h",
        ROOT / "README.md",
        ROOT / "THIRD_PARTY_NOTICES.md",
        ROOT / "LICENSE_STATUS.md",
    ):
        assert "GxEPD2_4G" not in path.read_text(encoding="utf-8")

    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "b3dbc5e6232d8e5945706bf8c0b7b7466dee144a" in notices
    assert "a2de1abca0597c202193f22d01e9fa35d1ff613b" in notices
    assert (component / "LICENSE").is_file()
    assert (component / "SEEED_GFX_LICENSE.txt").is_file()
