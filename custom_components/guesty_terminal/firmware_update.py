"""Queue managed GuestyTerminal firmware updates in ESPHome Device Builder."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DATA_FIRMWARE_UPDATE_LOCK, DOMAIN
from .firmware import (
    FIRMWARE_VERSION,
    FirmwareConfigError,
    ManagedFirmwareConfig,
    update_managed_firmware_configs,
)

_COMMAND = "firmware/install_bulk"
_RESPONSE_TIMEOUT_SECONDS = 15


@dataclass(frozen=True, slots=True)
class BulkFirmwareUpdateResult:
    """Summary returned as soon as Device Builder accepts all jobs."""

    managed_configurations: int
    updated_configurations: int
    queued_jobs: int
    firmware_version: str = FIRMWARE_VERSION


def _translated_error(key: str) -> HomeAssistantError:
    """Build a localized Home Assistant service error."""
    return HomeAssistantError(translation_domain=DOMAIN, translation_key=key)


def _get_esphome_dashboard(hass: HomeAssistant):
    """Resolve Home Assistant's optional ESPHome dashboard connection lazily."""
    try:
        from homeassistant.components.esphome.dashboard import (  # noqa: PLC0415
            async_get_dashboard,
        )
    except ImportError:
        return None
    return async_get_dashboard(hass)


async def async_queue_device_builder_updates(
    session: aiohttp.ClientSession,
    dashboard_url: str,
    configurations: list[str],
) -> int:
    """Submit one non-blocking OTA job per configuration over the builder API."""
    message_id = f"guestyterminal-{uuid4().hex}"
    websocket_url = f"{dashboard_url.rstrip('/')}/ws"
    try:
        async with asyncio.timeout(_RESPONSE_TIMEOUT_SECONDS):
            async with session.ws_connect(websocket_url) as websocket:
                server_info = await websocket.receive_json()
                if not isinstance(server_info, dict):
                    raise _translated_error("firmware_builder_invalid_response")
                if server_info.get("requires_auth"):
                    raise _translated_error("firmware_builder_auth_required")

                await websocket.send_json(
                    {
                        "command": _COMMAND,
                        "message_id": message_id,
                        "args": {"configurations": configurations, "port": "OTA"},
                    }
                )
                while True:
                    response = await websocket.receive_json()
                    if not isinstance(response, dict):
                        raise _translated_error("firmware_builder_invalid_response")
                    if response.get("message_id") != message_id:
                        continue
                    if response.get("error_code") == "unknown_command":
                        raise _translated_error("firmware_builder_too_old")
                    if response.get("error_code"):
                        raise _translated_error("firmware_queue_failed")
                    jobs = response.get("result")
                    if not isinstance(jobs, list) or len(jobs) != len(configurations):
                        raise _translated_error("firmware_builder_invalid_response")
                    return len(jobs)
    except HomeAssistantError:
        raise
    except (TimeoutError, aiohttp.ClientError, TypeError, ValueError) as err:
        raise _translated_error("firmware_builder_unavailable") from err


async def async_update_all_managed_firmware(
    hass: HomeAssistant,
) -> BulkFirmwareUpdateResult:
    """Upgrade managed YAML files and queue every display for OTA installation."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    lock = domain_data.setdefault(DATA_FIRMWARE_UPDATE_LOCK, asyncio.Lock())
    if lock.locked():
        raise _translated_error("firmware_update_in_progress")
    async with lock:
        directory = Path(hass.config.path("esphome"))
        try:
            managed: list[ManagedFirmwareConfig] = await hass.async_add_executor_job(
                update_managed_firmware_configs, directory
            )
        except (FirmwareConfigError, OSError) as err:
            raise _translated_error("firmware_config_update_failed") from err
        if not managed:
            raise _translated_error("firmware_no_managed_configs")

        dashboard = _get_esphome_dashboard(hass)
        if dashboard is None:
            raise _translated_error("firmware_builder_unavailable")
        queued_jobs = await async_queue_device_builder_updates(
            async_get_clientsession(hass),
            dashboard.url,
            [item.path.name for item in managed],
        )
        return BulkFirmwareUpdateResult(
            managed_configurations=len(managed),
            updated_configurations=sum(item.changed for item in managed),
            queued_jobs=queued_jobs,
        )
