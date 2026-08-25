"""Privacy-safe diagnostics for GuestyTerminal config entries."""

from __future__ import annotations

from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

from .const import (
    CONF_LOGO_DATA,
    CONF_POLL_MINUTES,
    DEFAULT_POLL_MINUTES,
    DISPLAY_ACTION_SUFFIX,
    DISPLAY_ACTION_V2_SUFFIX,
    DISPLAY_ACTION_V3_SUFFIX,
    DISPLAY_ACTION_V4_SUFFIX,
    DISPLAY_ACTION_V5_SUFFIX,
    DISPLAY_ACTION_V6_SUFFIX,
    DISPLAY_ACTION_V7_SUFFIX,
    DISPLAY_ACTION_V8_SUFFIX,
    DISPLAY_ACTION_V9_SUFFIX,
    DISPLAY_ACTION_V10_SUFFIX,
)
from .runtime import GuestyTerminalConfigEntry

_ACTION_VERSIONS = (
    (DISPLAY_ACTION_V10_SUFFIX, 10),
    (DISPLAY_ACTION_V9_SUFFIX, 9),
    (DISPLAY_ACTION_V8_SUFFIX, 8),
    (DISPLAY_ACTION_V7_SUFFIX, 7),
    (DISPLAY_ACTION_V6_SUFFIX, 6),
    (DISPLAY_ACTION_V5_SUFFIX, 5),
    (DISPLAY_ACTION_V4_SUFFIX, 4),
    (DISPLAY_ACTION_V3_SUFFIX, 3),
    (DISPLAY_ACTION_V2_SUFFIX, 2),
    (DISPLAY_ACTION_SUFFIX, 1),
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: GuestyTerminalConfigEntry,
) -> dict[str, Any]:
    """Return an allow-listed diagnostic snapshot without guest data or secrets."""
    runtime = entry.runtime_data
    coordinator = runtime.coordinator
    data = coordinator.data
    displays: list[dict[str, Any]] = []
    for mapping in coordinator.mapping_options():
        payload = (
            data.payloads.get(mapping.endpoint_entity) if data is not None else None
        )
        listing = data.listings.get(mapping.listing_id) if data is not None else None
        endpoint_state = hass.states.get(mapping.endpoint_entity)
        action = str(getattr(endpoint_state, "state", ""))
        endpoint_available = bool(action) and action not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        )
        action_version = next(
            (
                version
                for suffix, version in _ACTION_VERSIONS
                if action.endswith(suffix)
            ),
            None,
        )
        delivery = runtime.delivery_diagnostic(mapping.endpoint_entity)
        displays.append(
            {
                "endpoint_entity": mapping.endpoint_entity,
                "endpoint_id": mapping.endpoint_id,
                "endpoint_available": endpoint_available,
                "action_version": action_version,
                "delivery_status": delivery.status,
                "delivery_attempted_at": delivery.attempted_at,
                "delivery_confirmed_at": delivery.confirmed_at,
                "delivery_failures": delivery.failures,
                "listing_id": mapping.listing_id,
                "listing_name": listing.display_name if listing is not None else None,
                "display_language": mapping.display_language,
                "date_time_format": mapping.date_time_format,
                "weather_entity": mapping.weather_entity or None,
                "mode": payload.mode if payload is not None else "unconfigured",
                "contains_door_code": bool(payload and payload.door_code),
                "contains_wifi": bool(payload and payload.wifi_name),
                "contains_weather": bool(
                    payload
                    and (payload.weather_condition or payload.weather_temperature)
                ),
                "valid_until_epoch": (
                    payload.valid_until_epoch
                    if payload is not None and payload.valid_until_epoch
                    else None
                ),
            }
        )

    last_exception = getattr(coordinator, "last_exception", None)
    return {
        "entry": {
            "poll_minutes": entry.options.get(CONF_POLL_MINUTES, DEFAULT_POLL_MINUTES),
            "logo_configured": bool(entry.options.get(CONF_LOGO_DATA)),
            "mapping_count": len(displays),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "last_exception_type": (
                type(last_exception).__name__ if last_exception is not None else None
            ),
        },
        "displays": displays,
    }
