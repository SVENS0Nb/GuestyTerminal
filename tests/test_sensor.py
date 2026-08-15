"""Tests for privacy-safe Home Assistant diagnostic sensors."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.guesty_terminal.models import (
    DisplayPayload,
    Listing,
    MappingOptions,
)
from custom_components.guesty_terminal.sensor import (
    GuestyTerminalStatusSensor,
    async_setup_entry,
)

ENDPOINT = "sensor.display_guesty_terminal_endpoint"


class FakeCoordinator:
    def __init__(self, data, mappings) -> None:
        self.data = data
        self._mappings = mappings

    def mapping_options(self):
        return self._mappings


def test_status_sensor_reports_only_non_sensitive_diagnostics() -> None:
    listing = Listing(
        "listing-1",
        "Loft",
        wifi_name="Guest WiFi",
        wifi_password="top-secret",
    )
    payload = DisplayPayload(
        "welcome",
        "LOFT",
        "Hallo Anna",
        "Willkommen",
        "4827",
        "Guest WiFi",
        "top-secret",
        "Check-out morgen",
        123456,
    )
    mapping = MappingOptions(ENDPOINT, "listing-1")
    coordinator = FakeCoordinator(
        SimpleNamespace(payloads={ENDPOINT: payload}, listings={"listing-1": listing}),
        [mapping],
    )
    sensor = GuestyTerminalStatusSensor(coordinator, ENDPOINT)

    assert sensor.native_value == "welcome"
    attributes = sensor.extra_state_attributes
    assert attributes["listing_name"] == "Loft"
    assert attributes["contains_door_code"] is True
    assert attributes["contains_wifi"] is True
    assert attributes["valid_until_epoch"] == 123456
    assert "top-secret" not in repr(attributes)
    assert sensor.unique_id.startswith("guesty_terminal_")


def test_status_sensor_handles_unconfigured_or_missing_listing() -> None:
    coordinator = FakeCoordinator(
        SimpleNamespace(payloads={}, listings={}),
        [],
    )
    sensor = GuestyTerminalStatusSensor(coordinator, ENDPOINT)
    assert sensor.native_value == "unconfigured"
    assert sensor.extra_state_attributes == {"endpoint_entity": ENDPOINT}

    listing_mapping = MappingOptions(ENDPOINT, "missing")
    coordinator._mappings = [listing_mapping]
    coordinator.data.payloads[ENDPOINT] = DisplayPayload.idle(Listing("id", "Loft"))
    assert sensor.extra_state_attributes["listing_name"] is None


def test_platform_setup_adds_one_sensor_per_mapping() -> None:
    mappings = [
        MappingOptions(ENDPOINT, "listing-1"),
        MappingOptions("sensor.second_guesty_terminal_endpoint", "listing-2"),
    ]
    coordinator = FakeCoordinator(SimpleNamespace(payloads={}, listings={}), mappings)
    entry = SimpleNamespace(runtime_data=SimpleNamespace(coordinator=coordinator))
    added = []

    def add_entities(entities):
        added.extend(entities)

    asyncio.run(async_setup_entry(None, entry, add_entities))
    assert len(added) == 2
