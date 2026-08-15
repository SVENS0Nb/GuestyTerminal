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
from custom_components.guesty_terminal.const import CONF_MAPPINGS
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


def _coordinator(options=None, client=None) -> GuestyTerminalCoordinator:
    coordinator = object.__new__(GuestyTerminalCoordinator)
    coordinator.entry = SimpleNamespace(options=options or {})
    coordinator.client = client or FakeClient()
    coordinator._keycode_cache = {}
    coordinator._custom_field_definitions = {}
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
    assert coordinator._custom_field_definitions["account-2"] == []


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
            "_id": "res-1",
            "listing": {"_id": "listing-1"},
            "status": "confirmed",
            "guest": {"firstName": "Anna"},
            "checkIn": "2026-08-14T12:00:00Z",
            "checkOut": "2099-08-18T10:00:00Z",
            "keycode": "4827",
        },
        {
            "_id": "unknown-listing",
            "listingId": "missing",
            "status": "confirmed",
        },
    ]
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: _mapping()}},
        client,
    )

    data = asyncio.run(coordinator._async_update_data())

    assert client.listing_calls == ["listing-1"]
    assert client.reservation_calls == [["listing-1"]]
    assert data.listings["listing-1"].wifi_name == "Guest WiFi"
    assert len(data.reservations) == 1
    assert data.payloads[endpoint].door_code == "4827"


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
