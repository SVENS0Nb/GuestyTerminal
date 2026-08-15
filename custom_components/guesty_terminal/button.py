"""Home Assistant buttons for GuestyTerminal fleet operations."""

from __future__ import annotations

import asyncio

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DOMAIN
from .firmware import FIRMWARE_VERSION
from .firmware_update import (
    BulkFirmwareUpdateResult,
    async_update_all_managed_firmware,
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the central firmware-update button for one Guesty account."""
    async_add_entities([GuestyTerminalFirmwareUpdateButton(entry.entry_id)])


class GuestyTerminalFirmwareUpdateButton(ButtonEntity):
    """Queue the latest managed firmware for every GuestyTerminal display."""

    _attr_translation_key = "update_all_firmware"
    _attr_has_entity_name = True
    _attr_icon = "mdi:update"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry_id: str) -> None:
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_update_all_firmware"
        self._lock = asyncio.Lock()
        self._last_result: BulkFirmwareUpdateResult | None = None

    @property
    def extra_state_attributes(self) -> dict[str, int | str]:
        """Expose only non-sensitive queue diagnostics."""
        result = self._last_result
        if result is None:
            return {"target_firmware_version": FIRMWARE_VERSION}
        return {
            "target_firmware_version": result.firmware_version,
            "managed_displays": result.managed_configurations,
            "updated_configurations": result.updated_configurations,
            "queued_jobs": result.queued_jobs,
        }

    async def async_press(self) -> None:
        """Prepare and queue all managed E1001 firmware installations."""
        if self._lock.locked():
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="firmware_update_in_progress",
            )
        async with self._lock:
            self._last_result = await async_update_all_managed_firmware(self.hass)
            self.async_write_ha_state()
