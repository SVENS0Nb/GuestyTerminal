"""Tests for Guesty polling and payload coordination."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.guesty_terminal.api import (
    GuestyAuthenticationError,
    GuestyError,
)
from custom_components.guesty_terminal.const import CONF_MAPPINGS, CONF_WEATHER_ENTITY
from custom_components.guesty_terminal.coordinator import GuestyTerminalCoordinator


class FakeClient:
    """Configurable asynchronous Guesty client."""

    def __init__(self) -> None:
        self.listings = []
        self.full_listings = {}
        self.reservations = []
        self.populated = {}
        self.definitions = {}
        self.listing_calls = []
        self.reservation_calls = []
        self.custom_calls = []
        self.definition_calls = []
        self.guests = {}
        self.guest_calls = []
        self.account = {"id": "account-current"}
        self.account_calls = 0
        self.failure: Exception | None = None

    async def async_get_listings(self):
        if self.failure:
            raise self.failure
        return self.listings

    async def async_get_listing(self, listing_id):
        self.listing_calls.append(listing_id)
        return self.full_listings.get(listing_id, {})

    async def async_get_reservations(self, listing_ids):
        self.reservation_calls.append(listing_ids)
        return self.reservations

    async def async_get_reservation_custom_fields(self, reservation_id):
        self.custom_calls.append(reservation_id)
        value = self.populated.get(reservation_id, {})
        if isinstance(value, Exception):
            raise value
        return value

    async def async_get_account_custom_fields(self, account_id):
        self.definition_calls.append(account_id)
        value = self.definitions.get(account_id, [])
        if isinstance(value, Exception):
            raise value
        return value

    async def async_get_guest(self, guest_id):
        self.guest_calls.append(guest_id)
        value = self.guests.get(guest_id, {})
        if isinstance(value, Exception):
            raise value
        return value

    async def async_get_current_account(self):
        self.account_calls += 1
        if isinstance(self.account, Exception):
            raise self.account
        return self.account


class FakeStates:
    def __init__(self, states=None) -> None:
        self.states = states or {}

    def get(self, entity_id):
        return self.states.get(entity_id)


def _coordinator(
    options=None, client=None, *, states=None
) -> GuestyTerminalCoordinator:
    coordinator = object.__new__(GuestyTerminalCoordinator)
    coordinator.hass = SimpleNamespace(
        states=FakeStates(states),
        config=SimpleNamespace(units=SimpleNamespace(temperature_unit="°C")),
    )
    coordinator.entry = SimpleNamespace(options=options or {})
    coordinator.client = client or FakeClient()
    coordinator._keycode_cache = {}
    coordinator._custom_field_definitions = {}
    coordinator._guest_cache = {}
    coordinator._account_id = None
    return coordinator


def _mapping(listing_id="listing-1"):
    return {
        "listing_id": listing_id,
        "welcome_title": "Hallo {first_name}",
        "welcome_text": "Willkommen im {property_name}",
        "lead_hours": 24,
        "clear_after_minutes": 0,
        "show_door_code": True,
        "show_wifi": True,
    }


def test_mapping_options_ignores_invalid_records() -> None:
    endpoint = "sensor.display_guesty_terminal_endpoint"
    coordinator = _coordinator(
        {
            CONF_MAPPINGS: {
                endpoint: _mapping(),
                "sensor.bad": "not-a-dict",
                "": _mapping(),
                "sensor.no_listing": _mapping(""),
            }
        }
    )
    assert [item.endpoint_entity for item in coordinator.mapping_options()] == [
        endpoint
    ]

    coordinator.entry.options = {CONF_MAPPINGS: []}
    assert coordinator.mapping_options() == []


def test_weather_values_round_temperature_and_tolerate_invalid_states() -> None:
    mapping = _mapping()
    mapping[CONF_WEATHER_ENTITY] = "weather.home"
    coordinator = _coordinator(
        {CONF_MAPPINGS: {"sensor.display": mapping}},
        states={
            "weather.home": SimpleNamespace(
                state="partlycloudy",
                attributes={"temperature": 18.4, "temperature_unit": "°C"},
            )
        },
    )
    options = coordinator.mapping_options()[0]
    assert coordinator._weather_values(options) == ("partlycloudy", "18 °C")

    coordinator.hass.states.states["weather.home"] = SimpleNamespace(
        state="sunny", attributes={"temperature": "invalid"}
    )
    assert coordinator._weather_values(options) == ("sunny", "")

    coordinator.hass.states.states["weather.home"] = SimpleNamespace(
        state="unavailable", attributes={}
    )
    assert coordinator._weather_values(options) == ("", "")
    assert coordinator._weather_values(
        coordinator.mapping_options()[0].__class__("sensor.display", "listing-1")
    ) == ("", "")


def test_keycode_resolution_uses_direct_values_and_cache() -> None:
    client = FakeClient()
    coordinator = _coordinator(client=client)
    assert asyncio.run(coordinator._async_keycode({"keycode": "1234"})) == "1234"
    assert asyncio.run(coordinator._async_keycode({})) == ""

    client.populated["res-direct"] = {"keyCode": "5678"}
    raw = {"_id": "res-direct", "lastUpdatedAt": "v1"}
    assert asyncio.run(coordinator._async_keycode(raw)) == "5678"
    assert asyncio.run(coordinator._async_keycode(raw)) == "5678"
    assert client.custom_calls == ["res-direct"]


def test_keycode_resolution_uses_definitions_and_tolerates_failures() -> None:
    client = FakeClient()
    client.populated["res-1"] = {
        "customFields": [{"fieldId": "field-1", "value": "2468"}]
    }
    client.definitions["account-1"] = [{"_id": "field-1", "name": "keycode"}]
    coordinator = _coordinator(client=client)
    raw = {"_id": "res-1", "accountId": "account-1", "lastUpdatedAt": "v1"}
    assert asyncio.run(coordinator._async_keycode(raw)) == "2468"
    assert client.definition_calls == ["account-1"]

    client.populated["res-failed"] = GuestyError("unavailable")
    assert asyncio.run(coordinator._async_keycode({"_id": "res-failed"})) == ""

    client.populated["res-definition-failed"] = {
        "customFields": [{"fieldId": "unknown", "value": "0000"}]
    }
    client.definitions["account-2"] = GuestyError("unavailable")
    failed_raw = {"_id": "res-definition-failed", "accountId": "account-2"}
    assert asyncio.run(coordinator._async_keycode(failed_raw)) == ""
    assert "account-2" not in coordinator._custom_field_definitions
    client.definitions["account-2"] = [{"_id": "unknown", "name": "keycode"}]
    assert asyncio.run(coordinator._async_keycode(failed_raw)) == "0000"


def test_v3_keycode_resolves_current_account_and_retries_guest_failures() -> None:
    client = FakeClient()
    client.populated["res-v3"] = {
        "customFields": [{"fieldId": "field-v3", "value": "1357"}]
    }
    client.definitions["account-current"] = [{"_id": "field-v3", "name": "keycode"}]
    client.guests["guest-1"] = GuestyError("temporary")
    coordinator = _coordinator(client=client)

    raw = {
        "reservationId": "res-v3",
        "guestId": "guest-1",
        "customFields": [{"fieldId": "field-v3", "value": "1357"}],
    }
    assert asyncio.run(coordinator._async_keycode(raw)) == "1357"
    assert client.account_calls == 1
    assert coordinator._account_id == "account-current"

    assert asyncio.run(coordinator._async_guest(raw)) == {}
    client.guests["guest-1"] = {"firstName": "Mia"}
    assert asyncio.run(coordinator._async_guest(raw))["firstName"] == "Mia"
    assert asyncio.run(coordinator._async_guest(raw))["firstName"] == "Mia"
    assert client.guest_calls == ["guest-1", "guest-1"]


def test_update_builds_payload_and_fetches_missing_listing_details() -> None:
    endpoint = "sensor.display_guesty_terminal_endpoint"
    client = FakeClient()
    client.listings = [
        {
            "_id": "listing-1",
            "title": "Loft",
            "timezone": "Europe/Berlin",
        },
        {"title": "ignored"},
    ]
    client.full_listings["listing-1"] = {
        "_id": "listing-1",
        "title": "Loft",
        "timezone": "Europe/Berlin",
        "wifiName": "Guest WiFi",
        "wifiPassword": "secret",
    }
    client.reservations = [
        {
            "reservationId": "res-1",
            "stay": [{"listingId": "listing-1"}],
            "status": "confirmed",
            "guestId": "guest-1",
            "checkIn": "2026-08-14T12:00:00Z",
            "checkOut": "2099-08-18T10:00:00Z",
            "notes": {"keyCode": "4827"},
        },
        {
            "_id": "unknown-listing",
            "listingId": "missing",
            "status": "confirmed",
        },
    ]
    client.guests["guest-1"] = {"firstName": "Anna"}
    mapping = _mapping()
    mapping[CONF_WEATHER_ENTITY] = "weather.home"
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: mapping}},
        client,
        states={
            "weather.home": SimpleNamespace(
                state="sunny",
                attributes={"temperature": 21.6, "temperature_unit": "°C"},
            )
        },
    )

    data = asyncio.run(coordinator._async_update_data())

    assert client.listing_calls == ["listing-1"]
    assert client.reservation_calls == [["listing-1"]]
    assert data.listings["listing-1"].wifi_name == "Guest WiFi"
    assert len(data.reservations) == 1
    assert data.payloads[endpoint].door_code == "4827"
    assert data.payloads[endpoint].welcome_title == "Hallo Anna"
    assert data.payloads[endpoint].weather_condition == "sunny"
    assert data.payloads[endpoint].weather_temperature == "22 °C"
    assert client.guest_calls == ["guest-1"]


def test_update_skips_full_listing_when_wifi_exists_and_missing_mappings() -> None:
    client = FakeClient()
    client.listings = [
        {
            "_id": "listing-1",
            "title": "Loft",
            "wifiName": "WiFi",
            "wifiPassword": "password",
        }
    ]
    coordinator = _coordinator(
        {CONF_MAPPINGS: {"sensor.display": _mapping("missing")}}, client
    )
    data = asyncio.run(coordinator._async_update_data())
    assert client.listing_calls == ["missing"]
    assert data.payloads == {}


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (GuestyAuthenticationError("bad token"), ConfigEntryAuthFailed),
        (GuestyError("offline"), UpdateFailed),
    ],
)
def test_update_translates_client_errors(failure, expected) -> None:
    client = FakeClient()
    client.failure = failure
    coordinator = _coordinator(client=client)
    with pytest.raises(expected):
        asyncio.run(coordinator._async_update_data())
