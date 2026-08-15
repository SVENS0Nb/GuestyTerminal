"""Generate ESPHome configurations for GuestyTerminal displays."""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

FIRMWARE_VERSION = "0.3.0"
FIRMWARE_HEADER = "# Managed by the GuestyTerminal firmware assistant."
POWER_MODES = ("auto", "battery", "mains")
_DEVICE_NAME_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,22}[a-z0-9])?$")


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
    temporary = destination.with_suffix(".yaml.guestyterminal.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
