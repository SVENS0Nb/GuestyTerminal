"""Generate ESPHome configurations for GuestyTerminal displays."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

FIRMWARE_VERSION = "0.3.57"
FIRMWARE_HEADER = "# Managed by the GuestyTerminal firmware assistant."
POWER_MODES = ("auto", "battery", "mains")
FLASH_LAYOUT_LEGACY = "legacy_4mb"
FLASH_LAYOUT_EXPANDED = "expanded_32mb"
FLASH_LAYOUTS = (FLASH_LAYOUT_LEGACY, FLASH_LAYOUT_EXPANDED)
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


class FirmwareFlashLayoutMigrationRequired(FirmwareConfigError):
    """A managed device needs an explicitly confirmed USB layout migration."""


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
    flash_layout: str = FLASH_LAYOUT_LEGACY

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
        if self.flash_layout not in FLASH_LAYOUTS:
            raise FirmwareConfigError("Unsupported flash layout")
        return FirmwareOptions(
            device_name=device_name,
            friendly_name=friendly_name,
            power_mode=self.power_mode,
            wake_interval_minutes=int(self.wake_interval_minutes),
            awake_seconds=int(self.awake_seconds),
            flash_layout=self.flash_layout,
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
    credentials = FirmwareCredentials(*values)
    try:
        api_key = base64.b64decode(credentials.api_key, validate=True)
    except (binascii.Error, ValueError):
        return None
    if (
        len(api_key) != 32
        or not 16 <= len(credentials.ota_password) <= 128
        or not 8 <= len(credentials.fallback_password) <= 64
    ):
        return None
    return credentials


def _existing_flash_layout(content: str) -> str:
    """Return the managed file's flash layout without guessing an expansion."""
    match = re.search(r"(?m)^\s*flash_size:\s*(4MB|32MB)\s*$", content)
    if match is None or match.group(1) == "4MB":
        # GuestyTerminal releases through 0.3.39 omitted flash_size. ESPHome
        # compiled those files with its 4 MB default, so absence is legacy.
        return FLASH_LAYOUT_LEGACY
    return FLASH_LAYOUT_EXPANDED


def _atomic_write_private(destination: Path, content: str) -> None:
    """Atomically replace one managed file without a publicly readable window."""
    temporary = destination.with_name(
        f".{destination.name}.{secrets.token_hex(8)}.guestyterminal.tmp"
    )
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = None
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        destination.chmod(0o600)
        try:
            directory_descriptor = os.open(
                destination.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError:
            # Some network and overlay filesystems do not support directory
            # fsync. The file itself is already flushed, private and replaced.
            pass
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def render_firmware_config(
    options: FirmwareOptions,
    credentials: FirmwareCredentials | None = None,
) -> str:
    """Render a self-contained, device-specific ESPHome entry file."""
    options = options.validated()
    credentials = credentials or _new_credentials()
    friendly_name = json.dumps(options.friendly_name, ensure_ascii=False)
    flash_size = "32MB" if options.flash_layout == FLASH_LAYOUT_EXPANDED else "4MB"
    framework_advanced = (
        "\n    advanced:\n      enable_idf_experimental_features: true"
        if options.flash_layout == FLASH_LAYOUT_EXPANDED
        else ""
    )
    return f"""{FIRMWARE_HEADER}
# Open this device in ESPHome Device Builder and choose Install.
# WiFi credentials are read from /config/esphome/secrets.yaml.
# Flash layout: {options.flash_layout}
# Changing an existing device to expanded_32mb requires one complete USB install.

substitutions:
  device_name: {options.device_name}
  friendly_name: {friendly_name}
  power_mode: {options.power_mode}
  battery_sleep_duration: {options.wake_interval_minutes}min
  awake_duration_seconds: "{options.awake_seconds}"
  gray_lut_mode: auto
  gray_waveform_profile: lighter
  gray_gamma: "1.35"
  environment_temperature_offset: "0.0"
  environment_humidity_offset: "0.0"
  flash_layout: {options.flash_layout}

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
  flash_size: {flash_size}
  framework:
    type: arduino{framework_advanced}

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
    directory: Path,
    options: FirmwareOptions,
    overwrite: bool = False,
    confirm_usb_flash_migration: bool = False,
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
        if (
            _existing_flash_layout(existing) != options.flash_layout
            and not confirm_usb_flash_migration
        ):
            raise FirmwareFlashLayoutMigrationRequired(str(destination))

    content = render_firmware_config(options, credentials)
    _atomic_write_private(destination, content)
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
        updated, content_changed = _updated_managed_config(content)
        if _existing_credentials(content) is None:
            raise FirmwareConfigError(
                "Managed ESPHome configuration has invalid credentials"
            )
        permissions_changed = (path.stat().st_mode & 0o777) != 0o600
        changed = content_changed or permissions_changed
        prepared.append((path, updated, changed))

    results: list[ManagedFirmwareConfig] = []
    for path, content, changed in prepared:
        if changed:
            _atomic_write_private(path, content)
        results.append(ManagedFirmwareConfig(path=path, changed=changed))
    return results
