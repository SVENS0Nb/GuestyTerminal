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
