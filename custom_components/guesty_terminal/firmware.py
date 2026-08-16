"""Generate ESPHome configurations for GuestyTerminal displays."""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

FIRMWARE_VERSION = "0.3.23"
FIRMWARE_HEADER = "# Managed by the GuestyTerminal firmware assistant."
POWER_MODES = ("auto", "battery", "mains")
_DEVICE_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,22}[a-z0-9])?$")
_FIRMWARE_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
_GUESTY_REPOSITORY_REF_PATTERN = re.compile(
    r"(?m)(^\s*url:\s*https://github\.com/SVENS0Nb/GuestyTerminal\s*$"
    r"\n^\s*ref:\s*v)(\d+\.\d+\.\d+)(\s*$)"
)
_PROJECT_VERSION_PATTERN = re.compile(r'(?m)(^\s*version:\s*")(\d+\.\d+\.\d+)("\s*$)')


class FirmwareConfigError(ValueError):
    """Base firmware configuration error."""


class FirmwareFileExistsError(FirmwareConfigError):
    """A user-managed ESPHome configuration already uses the requested name."""


@dataclass(frozen=True, slots=True)
class FirmwareCredentials:
    """Per-device credentials embedded in a private ESPHome file."""

    api_key: str
    ota_password: str
    fallback_password: str


@dataclass(frozen=True, slots=True)
class FirmwareOptions:
    """User-selected E1001 power and identity settings."""

    device_name: str
    friendly_name: str
    power_mode: str = "auto"
    wake_interval_minutes: int = 30
    awake_seconds: int = 90

    def validated(self) -> FirmwareOptions:
        """Return normalized settings or raise for unsafe values."""
        device_name = self.device_name.strip().lower()
        friendly_name = self.friendly_name.strip()
        if not _DEVICE_NAME_PATTERN.fullmatch(device_name):
            raise FirmwareConfigError(
                "Device name must contain 1-24 lowercase letters, digits, or hyphens"
            )
        if not friendly_name or len(friendly_name) > 48:
            raise FirmwareConfigError("Friendly name must contain 1-48 characters")
        if self.power_mode not in POWER_MODES:
            raise FirmwareConfigError("Unsupported power mode")
        if not 5 <= int(self.wake_interval_minutes) <= 180:
            raise FirmwareConfigError("Wake interval must be between 5 and 180 minutes")
        if not 30 <= int(self.awake_seconds) <= 300:
            raise FirmwareConfigError("Awake time must be between 30 and 300 seconds")
        return FirmwareOptions(
            device_name=device_name,
            friendly_name=friendly_name,
            power_mode=self.power_mode,
            wake_interval_minutes=int(self.wake_interval_minutes),
            awake_seconds=int(self.awake_seconds),
        )


@dataclass(frozen=True, slots=True)
class ManagedFirmwareConfig:
    """One GuestyTerminal-managed ESPHome configuration prepared for OTA."""

    path: Path
    changed: bool


def _new_api_key() -> str:
    """Return a valid 32-byte ESPHome Noise encryption key."""
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def _new_credentials() -> FirmwareCredentials:
    """Return fresh credentials for a newly created display."""
    return FirmwareCredentials(
        api_key=_new_api_key(),
        ota_password=secrets.token_hex(24),
        fallback_password=secrets.token_urlsafe(12)[:16],
    )


def _existing_credentials(content: str) -> FirmwareCredentials | None:
    """Recover credentials so regenerating a file does not break OTA access."""
    patterns = (
        r'\napi:\n  encryption:\n    key: "([^"\n]+)"',
        r'\nota:\n  - platform: esphome\n    password: "([^"\n]+)"',
        r'\n  ap:\n    ssid: "\$\{device_name\}-setup"\n    password: "([^"\n]+)"',
    )
    values: list[str] = []
    for pattern in patterns:
        match = re.search(pattern, content)
        if match is None:
            return None
        values.append(match.group(1))
    return FirmwareCredentials(*values)


def render_firmware_config(
    options: FirmwareOptions,
    credentials: FirmwareCredentials | None = None,
) -> str:
    """Render a self-contained, device-specific ESPHome entry file."""
    options = options.validated()
    credentials = credentials or _new_credentials()
    friendly_name = json.dumps(options.friendly_name, ensure_ascii=False)
    return f"""{FIRMWARE_HEADER}
# Open this device in ESPHome Device Builder and choose Install.
# WiFi credentials are read from /config/esphome/secrets.yaml.

substitutions:
  device_name: {options.device_name}
  friendly_name: {friendly_name}
  power_mode: {options.power_mode}
  battery_sleep_duration: {options.wake_interval_minutes}min
  awake_duration_seconds: "{options.awake_seconds}"
  gray_lut_mode: auto

external_components:
  - source:
      type: git
      url: https://github.com/SVENS0Nb/GuestyTerminal
      ref: v{FIRMWARE_VERSION}
    components:
      - guesty_epaper_gray4
    refresh: 1d

packages:
  guesty_terminal:
    url: https://github.com/SVENS0Nb/GuestyTerminal
    ref: v{FIRMWARE_VERSION}
    files:
      - esphome/packages/reterminal-e1001-guesty-terminal.yaml
    refresh: 1d

esphome:
  name: ${{device_name}}
  friendly_name: ${{friendly_name}}
  project:
    name: guestyterminal.reterminal-e1001
    version: "{FIRMWARE_VERSION}"

esp32:
  board: esp32-s3-devkitc-1
  framework:
    type: arduino

logger:
  hardware_uart: UART0

api:
  encryption:
    key: "{credentials.api_key}"

ota:
  - platform: esphome
    password: "{credentials.ota_password}"

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password
  power_save_mode: LIGHT
  ap:
    ssid: "${{device_name}}-setup"
    password: "{credentials.fallback_password}"

captive_portal:
"""


def write_firmware_config(
    directory: Path, options: FirmwareOptions, overwrite: bool = False
) -> Path:
    """Atomically create or replace a GuestyTerminal-managed ESPHome file."""
    options = options.validated()
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{options.device_name}.yaml"
    credentials = None
    if destination.exists():
        existing = destination.read_text(encoding="utf-8")
        if not overwrite or not existing.startswith(FIRMWARE_HEADER):
            raise FirmwareFileExistsError(str(destination))
        credentials = _existing_credentials(existing)
        if credentials is None:
            raise FirmwareFileExistsError(str(destination))

    content = render_firmware_config(options, credentials)
    temporary = destination.with_name(
        f".{destination.name}.{secrets.token_hex(8)}.guestyterminal.tmp"
    )
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _version_tuple(version: str) -> tuple[int, int, int]:
    """Return a comparable release tuple for a validated firmware version."""
    if not _FIRMWARE_VERSION_PATTERN.fullmatch(version):
        raise FirmwareConfigError(f"Invalid firmware version: {version}")
    return tuple(int(part) for part in version.split("."))  # type: ignore[return-value]


def _updated_managed_config(content: str) -> tuple[str, bool]:
    """Update repository refs in one managed file without touching credentials."""
    repository_versions = _GUESTY_REPOSITORY_REF_PATTERN.findall(content)
    project_versions = _PROJECT_VERSION_PATTERN.findall(content)
    if len(repository_versions) != 2 or len(project_versions) != 1:
        raise FirmwareConfigError("Managed ESPHome configuration is malformed")

    detected_versions = {
        *(match[1] for match in repository_versions),
        project_versions[0][1],
    }
    if len(detected_versions) != 1:
        raise FirmwareConfigError("Managed ESPHome firmware versions do not match")

    installed_config_version = detected_versions.pop()
    if _version_tuple(installed_config_version) >= _version_tuple(FIRMWARE_VERSION):
        return content, False

    updated = _GUESTY_REPOSITORY_REF_PATTERN.sub(
        rf"\g<1>{FIRMWARE_VERSION}\g<3>", content
    )
    updated = _PROJECT_VERSION_PATTERN.sub(rf"\g<1>{FIRMWARE_VERSION}\g<3>", updated)
    return updated, updated != content


def update_managed_firmware_configs(directory: Path) -> list[ManagedFirmwareConfig]:
    """Upgrade every managed ESPHome YAML while preserving private credentials."""
    if not directory.exists():
        return []

    prepared: list[tuple[Path, str, bool]] = []
    for path in sorted(directory.glob("*.yaml")):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        if not content.startswith(FIRMWARE_HEADER):
            continue
        updated, changed = _updated_managed_config(content)
        prepared.append((path, updated, changed))

    results: list[ManagedFirmwareConfig] = []
    for path, content, changed in prepared:
        if changed:
            temporary = path.with_name(
                f".{path.name}.{secrets.token_hex(8)}.guestyterminal.tmp"
            )
            try:
                temporary.write_text(content, encoding="utf-8")
                temporary.chmod(path.stat().st_mode & 0o777)
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        results.append(ManagedFirmwareConfig(path=path, changed=changed))
    return results
