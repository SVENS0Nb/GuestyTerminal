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
from custom_components.guesty_terminal.runtime import DisplayDeliveryDiagnostic


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
    runtime = SimpleNamespace(
        coordinator=coordinator,
        delivery_diagnostic=lambda _endpoint: DisplayDeliveryDiagnostic(
            status="success",
            attempted_at="2026-08-25T18:00:00+00:00",
            confirmed_at="2026-08-25T18:00:20+00:00",
            failures=1,
        ),
    )
    entry = SimpleNamespace(
        options={"client_secret": "guesty-secret", "logo_data": "opaque-logo"},
        runtime_data=runtime,
    )
    hass = SimpleNamespace(
        states=SimpleNamespace(
            get=lambda _entity: SimpleNamespace(
                state="display_guesty_terminal_update_display_v10"
            )
        )
    )

    diagnostics = asyncio.run(async_get_config_entry_diagnostics(hass, entry))
    serialized = repr(diagnostics)

    assert diagnostics["entry"]["logo_configured"] is True
    assert diagnostics["coordinator"]["last_exception_type"] == "RuntimeError"
    assert diagnostics["displays"][0]["contains_door_code"] is True
    assert diagnostics["displays"][0]["contains_wifi"] is True
    assert diagnostics["displays"][0]["action_version"] == 10
    assert diagnostics["displays"][0]["delivery_status"] == "success"
    assert diagnostics["displays"][0]["delivery_failures"] == 1
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
