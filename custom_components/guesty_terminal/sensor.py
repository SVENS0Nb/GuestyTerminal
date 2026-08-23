"""Privacy-safe diagnostic sensors for GuestyTerminal."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import GuestyTerminalCoordinator
from .models import MappingOptions, endpoint_stable_id
from .runtime import GuestyTerminalConfigEntry, GuestyTerminalRuntime


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: GuestyTerminalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one status sensor per mapping."""
    runtime: GuestyTerminalRuntime = entry.runtime_data
    async_add_entities(
        GuestyTerminalStatusSensor(runtime.coordinator, mapping)
        for mapping in runtime.coordinator.mapping_options()
    )


class GuestyTerminalStatusSensor(
    CoordinatorEntity[GuestyTerminalCoordinator], SensorEntity
):
    """Show display mode without exposing guest or credential data."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_icon = "mdi:tablet-dashboard"

    def __init__(
        self,
        coordinator: GuestyTerminalCoordinator,
        mapping: MappingOptions | str,
    ) -> None:
        super().__init__(coordinator)
        if isinstance(mapping, MappingOptions):
            self._endpoint_entity = mapping.endpoint_entity
            digest = mapping.endpoint_id or endpoint_stable_id(mapping.endpoint_entity)
        else:
            self._endpoint_entity = mapping
            digest = endpoint_stable_id(mapping)
        self._attr_unique_id = f"guesty_terminal_{digest}_status"
        self._attr_name = f"GuestyTerminal {self._endpoint_entity} Status"

    @property
    def native_value(self) -> str:
        """Return idle or welcome without sensitive content."""
        payload = self.coordinator.data.payloads.get(self._endpoint_entity)
        return payload.mode if payload is not None else "unconfigured"

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Return only non-sensitive diagnostics."""
        payload = self.coordinator.data.payloads.get(self._endpoint_entity)
        mapping = next(
            (
                item
                for item in self.coordinator.mapping_options()
                if item.endpoint_entity == self._endpoint_entity
            ),
            None,
        )
        if payload is None or mapping is None:
            return {"endpoint_entity": self._endpoint_entity}
        listing = self.coordinator.data.listings.get(mapping.listing_id)
        return {
            "endpoint_entity": self._endpoint_entity,
            "listing_id": mapping.listing_id,
            "listing_name": listing.display_name if listing else None,
            "contains_door_code": bool(payload.door_code),
            "contains_wifi": bool(payload.wifi_name),
            "weather_entity": mapping.weather_entity or None,
            "contains_weather": bool(
                payload.weather_condition or payload.weather_temperature
            ),
            "valid_until_epoch": payload.valid_until_epoch or None,
        }
