"""Tests for privacy-safe downloadable diagnostics."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.guesty_terminal.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.guesty_terminal.models import (
    DisplayPayload,
    Listing,
    MappingOptions,
)


def test_diagnostics_allow_list_excludes_guest_and_credentials() -> None:
    endpoint = "sensor.display_guesty_terminal_endpoint"
    mapping = MappingOptions.from_dict(
        endpoint,
        {
            "listing_id": "listing-1",
            "weather_entity": "weather.home",
        },
    )
    listing = Listing(
        "listing-1",
        "Loft",
        wifi_name="Guest WiFi",
        wifi_password="wifi-secret",
    )
    payload = DisplayPayload(
        "welcome",
        "LOFT",
        "Hallo Ada",
        "Privater Willkommenstext",
        "4827",
        "Guest WiFi",
        "wifi-secret",
        "morgen",
        123456,
        booking_summary="Ada · private booking",
    )
    coordinator = SimpleNamespace(
        data=SimpleNamespace(
            payloads={endpoint: payload}, listings={"listing-1": listing}
        ),
        mapping_options=lambda: [mapping],
        last_update_success=False,
        last_exception=RuntimeError("must-not-appear"),
    )
    entry = SimpleNamespace(
        options={"client_secret": "guesty-secret", "logo_data": "opaque-logo"},
        runtime_data=SimpleNamespace(coordinator=coordinator),
    )
    hass = SimpleNamespace(
        states=SimpleNamespace(
            get=lambda _entity: SimpleNamespace(
                state="display_guesty_terminal_update_display_v9"
            )
        )
    )

    diagnostics = asyncio.run(async_get_config_entry_diagnostics(hass, entry))
    serialized = repr(diagnostics)

    assert diagnostics["entry"]["logo_configured"] is True
    assert diagnostics["coordinator"]["last_exception_type"] == "RuntimeError"
    assert diagnostics["displays"][0]["contains_door_code"] is True
    assert diagnostics["displays"][0]["contains_wifi"] is True
    for secret in (
        "guesty-secret",
        "wifi-secret",
        "Guest WiFi",
        "4827",
        "Ada",
        "private booking",
        "must-not-appear",
    ):
        assert secret not in serialized
