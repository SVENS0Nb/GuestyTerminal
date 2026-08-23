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
        weather_condition="sunny",
        weather_temperature="18 °C",
    )
    mapping = MappingOptions(ENDPOINT, "listing-1", weather_entity="weather.home")
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
    assert attributes["weather_entity"] == "weather.home"
    assert attributes["contains_weather"] is True
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


def test_status_sensor_recognizes_an_open_wifi_network() -> None:
    payload = DisplayPayload(
        "welcome",
        "LOFT",
        "Hallo",
        "Willkommen",
        "",
        "Open Guest WiFi",
        "",
        "Check-out morgen",
        123456,
    )
    mapping = MappingOptions(ENDPOINT, "listing-1")
    coordinator = FakeCoordinator(
        SimpleNamespace(payloads={ENDPOINT: payload}, listings={}), [mapping]
    )

    assert (
        GuestyTerminalStatusSensor(coordinator, ENDPOINT).extra_state_attributes[
            "contains_wifi"
        ]
        is True
    )


def test_status_sensor_unique_id_survives_endpoint_rename() -> None:
    original = MappingOptions.from_dict(ENDPOINT, {"listing_id": "listing-1"})
    renamed = MappingOptions.from_dict(
        "sensor.renamed_guesty_terminal_endpoint", original.as_dict()
    )
    coordinator = FakeCoordinator(SimpleNamespace(payloads={}, listings={}), [])

    assert (
        GuestyTerminalStatusSensor(coordinator, original).unique_id
        == GuestyTerminalStatusSensor(coordinator, renamed).unique_id
    )


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
