"""Tests for Guesty polling and payload coordination."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

import custom_components.guesty_terminal.coordinator as coordinator_module
from custom_components.guesty_terminal.api import (
    GuestyAuthenticationError,
    GuestyError,
    GuestyRateLimitError,
)
from custom_components.guesty_terminal.const import CONF_MAPPINGS, CONF_WEATHER_ENTITY
from custom_components.guesty_terminal.coordinator import GuestyTerminalCoordinator
from custom_components.guesty_terminal.models import (
    DisplayPayload,
    Listing,
    Reservation,
    extract_reservation_notes,
)


class FakeClient:
    """Configurable asynchronous Guesty client."""

    def __init__(self) -> None:
        self.listings = []
        self.full_listings = {}
        self.reservations = []
        self.account_current_reservations = []
        self.reservations_by_query = {}
        self.upcoming_reservations = {}
        self.verified_reservations = {}
        self.populated = {}
        self.definitions = {}
        self.listing_calls = []
        self.reservation_calls = []
        self.reservation_as_of = []
        self.account_current_calls = 0
        self.account_current_as_of = []
        self.upcoming_reservation_calls = []
        self.upcoming_as_of = []
        self.verification_calls = []
        self.verification_failure: Exception | None = None
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
        value = self.full_listings.get(listing_id, {})
        if isinstance(value, Exception):
            raise value
        return value

    async def async_get_reservations(self, listing_ids, *, as_of=None):
        self.reservation_calls.append(listing_ids)
        self.reservation_as_of.append(as_of)
        query = tuple(listing_ids)
        if query in self.reservations_by_query:
            value = self.reservations_by_query[query]
            if isinstance(value, Exception):
                raise value
            return value
        return self.reservations

    async def async_get_current_reservations(self, *, as_of=None):
        self.account_current_calls += 1
        self.account_current_as_of.append(as_of)
        value = self.account_current_reservations
        if isinstance(value, Exception):
            raise value
        return value

    async def async_get_upcoming_reservations(self, listing_id, *, limit, as_of=None):
        self.upcoming_reservation_calls.append((listing_id, limit))
        self.upcoming_as_of.append(as_of)
        value = self.upcoming_reservations.get(listing_id, [])
        if isinstance(value, Exception):
            raise value
        return value

    async def async_get_reservations_by_ids(self, reservation_ids):
        requested = list(reservation_ids)
        self.verification_calls.append(requested)
        if self.verification_failure is not None:
            raise self.verification_failure
        return [
            self.verified_reservations[reservation_id]
            for reservation_id in requested
            if reservation_id in self.verified_reservations
        ]

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
    coordinator._listing_detail_cache = {}
    coordinator._reservation_snapshot_cache = {}
    coordinator._account_id = None
    coordinator._blocked_endpoints = set()
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


def test_projection_merge_fills_complementary_fields_without_reviving_clears() -> None:
    current = {
        "reservationId": "reservation-1",
        "status": "confirmed",
        "guest": {"firstName": "Anna"},
        "notes": {"cleaning": ""},
        "channelMetadata": {"source": "direct"},
        "customFields": [{"fieldId": "keycode", "value": ""}],
        "stay": [{"listingId": "listing-1"}],
    }
    upcoming = {
        "reservationId": "reservation-1",
        "guest": {"lastName": "Beispiel"},
        "notes": {
            "cleaning": "stale cleaner note",
            "other": "General note",
            "specialRequests": "Late arrival",
        },
        "channelMetadata": {"specialRequests": "Late arrival"},
        "customFields": [
            {"fieldId": "keycode", "value": "stale-code"},
            {"fieldId": "arrival", "value": "after 18:00"},
        ],
        "stay": [
            {
                "listingId": "listing-1",
                "checkInDateLocalized": "2026-09-10",
                "checkOutDateLocalized": "2026-09-13",
            }
        ],
    }

    merged, include_keycode = coordinator_module._merge_reservation_observations(
        [
            ("listing-1", current, True),
            ("listing-1", upcoming, False),
        ]
    )

    assert include_keycode is True
    assert merged["guest"] == {"firstName": "Anna", "lastName": "Beispiel"}
    assert merged["notes"] == {
        "cleaning": "",
        "other": "General note",
        "specialRequests": "Late arrival",
    }
    assert merged["channelMetadata"] == {
        "source": "direct",
        "specialRequests": "Late arrival",
    }
    assert merged["keycode"] == ""
    assert merged["customFields"] == [{"fieldId": "arrival", "value": "after 18:00"}]
    assert merged["stay"][0]["checkOutDateLocalized"] == "2026-09-13"

    current["notes"] = {}
    explicitly_cleared, _include_keycode = (
        coordinator_module._merge_reservation_observations(
            [
                ("listing-1", current, True),
                ("listing-1", upcoming, False),
            ]
        )
    )
    assert explicitly_cleared["notes"] == {}


def test_projection_merge_blocks_sensitive_cross_shape_aliases() -> None:
    current = {
        "reservationId": "reservation-1",
        "status": "confirmed",
        "guest": {},
        "notes": {},
        "channelMetadata": {},
        "customFields": [],
    }
    stale = {
        "reservationId": "reservation-1",
        "guestId": "stale-guest",
        "generalNotes": "stale general note",
        "notesForCleaner": "stale cleaner note",
        "specialRequests": "stale request",
        "channelMetadata": {"specialRequests": "stale channel request"},
        "keycode": "stale-code",
    }

    merged, _include_keycode = coordinator_module._merge_reservation_observations(
        [("listing-1", current, True), ("listing-1", stale, False)]
    )
    coordinator = _coordinator()

    assert merged["guest"] == {}
    assert "guestId" not in merged
    assert extract_reservation_notes(merged) == ("", "", "")
    assert merged["keycode"] == ""
    assert asyncio.run(coordinator._async_guest(merged)) == {}
    assert asyncio.run(coordinator._async_keycode(merged)) == ""
    assert coordinator.client.guest_calls == []
    assert coordinator.client.custom_calls == []


def test_later_current_clears_block_every_upcoming_alias() -> None:
    account_current = {
        "reservationId": "reservation-1",
        "status": "confirmed",
        "checkIn": "2026-09-10T13:00:00Z",
        "checkOut": "2026-09-13T08:00:00Z",
        "stay": [{"listingId": "listing-1"}],
        "guest": {"firstName": "Mia"},
    }
    scoped_current_clear = {
        "reservationId": "reservation-1",
        "customFields": [{"fieldId": "keycode", "value": ""}],
        "channelMetadata": {},
    }
    upcoming_stale = {
        "reservationId": "reservation-1",
        "keycode": "stale-code",
        "specialRequests": "stale root request",
        "notes": {"specialRequests": "stale nested request"},
    }

    merged, _include_keycode = coordinator_module._merge_reservation_observations(
        [
            ("", account_current, True),
            ("listing-1", scoped_current_clear, True),
            ("listing-1", upcoming_stale, False),
        ]
    )

    assert merged["keycode"] == ""
    assert merged["customFields"] == []
    assert merged["channelMetadata"] == {}
    assert extract_reservation_notes(merged)[2] == ""


@pytest.mark.parametrize(
    "channel_metadata",
    [{}, {"specialRequests": ""}],
)
def test_explicit_channel_metadata_blocks_special_request_aliases(
    channel_metadata,
) -> None:
    merged, _include_keycode = coordinator_module._merge_reservation_observations(
        [
            (
                "listing-1",
                {
                    "reservationId": "reservation-1",
                    "status": "confirmed",
                    "channelMetadata": channel_metadata,
                },
                True,
            ),
            (
                "listing-1",
                {
                    "reservationId": "reservation-1",
                    "notes": {"specialRequests": "stale nested request"},
                    "specialRequests": "stale root request",
                },
                False,
            ),
        ]
    )

    assert extract_reservation_notes(merged)[2] == ""


def test_identified_empty_keycode_field_blocks_root_and_remote_fallbacks() -> None:
    current = {
        "reservationId": "reservation-1",
        "status": "confirmed",
        "customFields": [
            {"fieldId": "keycode", "value": ""},
            {"fieldId": "arrival", "value": "after 18:00"},
        ],
    }
    stale = {
        "reservationId": "reservation-1",
        "keycode": "stale-code",
        "notes": {
            "keyCode": "stale-notes-code",
            "nested": {"fieldName": "keycode", "value": "stale-named-code"},
        },
    }
    merged, _include_keycode = coordinator_module._merge_reservation_observations(
        [("listing-1", current, True), ("listing-1", stale, False)]
    )
    coordinator = _coordinator()
    coordinator.client.populated["reservation-1"] = {"keycode": "remote-stale-code"}

    assert merged["keycode"] == ""
    assert "keyCode" not in merged["notes"]
    assert merged["notes"]["nested"] == {}
    assert asyncio.run(coordinator._async_keycode(merged)) == ""
    assert coordinator.client.custom_calls == []


@pytest.mark.parametrize(
    "projection",
    [
        {"fields": []},
        {"customField": []},
        {"customFields": {"keycode": ""}},
        {"customField": {"fieldName": "keycode", "value": ""}},
        {"fields": [{"name": "keycode", "value": ""}]},
    ],
)
def test_every_empty_keycode_projection_blocks_stale_and_remote_fallbacks(
    projection,
) -> None:
    current = {
        "reservationId": "reservation-1",
        "status": "confirmed",
        **projection,
    }
    stale = {
        "reservationId": "reservation-1",
        "keycode": "stale-code",
        "notes": {"keyCode": "stale-notes-code"},
    }
    merged, _include_keycode = coordinator_module._merge_reservation_observations(
        [("listing-1", current, True), ("listing-1", stale, False)]
    )
    coordinator = _coordinator()
    coordinator.client.populated["reservation-1"] = {"keycode": "remote-stale"}

    assert asyncio.run(coordinator._async_keycode(merged)) == ""
    assert coordinator.client.custom_calls == []


def test_guest_id_projection_blocks_stale_embedded_guest() -> None:
    current = {
        "reservationId": "reservation-1",
        "status": "confirmed",
        "guestId": "guest-current",
    }
    stale = {
        "reservationId": "reservation-1",
        "guest": {"firstName": "Alt"},
        "bookerId": "guest-stale",
    }
    merged, _include_keycode = coordinator_module._merge_reservation_observations(
        [("listing-1", current, True), ("listing-1", stale, False)]
    )
    coordinator = _coordinator()
    coordinator.client.guests["guest-current"] = {"firstName": "Neu"}

    assert "guest" not in merged
    assert "bookerId" not in merged
    assert asyncio.run(coordinator._async_guest(merged)) == {"firstName": "Neu"}
    assert coordinator.client.guest_calls == ["guest-current"]


@pytest.mark.parametrize("guest_field", ["guestId", "bookerId"])
def test_empty_guest_id_alias_blocks_every_stale_guest_fallback(guest_field) -> None:
    current = {
        "reservationId": "reservation-1",
        "status": "confirmed",
        guest_field: "",
    }
    stale = {
        "reservationId": "reservation-1",
        "guest": {"firstName": "Alt"},
        "guestId": "guest-stale",
        "bookerId": "booker-stale",
    }
    merged, _include_keycode = coordinator_module._merge_reservation_observations(
        [("listing-1", current, True), ("listing-1", stale, False)]
    )
    coordinator = _coordinator()

    assert asyncio.run(coordinator._async_guest(merged)) == {}
    assert coordinator.client.guest_calls == []


def test_later_current_sensitive_clears_override_richer_current_projection() -> None:
    rich_account_current = {
        "reservationId": "reservation-1",
        "status": "confirmed",
        "checkIn": "2026-09-10T13:00:00Z",
        "checkOut": "2026-09-13T08:00:00Z",
        "stay": [{"listingId": "listing-1"}],
        "guest": {"firstName": "Alt"},
        "keycode": "old-code",
        "notes": {
            "other": "old general",
            "cleaning": "old cleaner",
            "specialRequests": "old request",
        },
    }
    scoped_current_clear = {
        "reservationId": "reservation-1",
        "guestId": "",
        "customField": {"name": "keycode", "value": ""},
        "generalNotes": "",
        "cleaningNotes": "",
        "channelMetadata": {"specialRequests": ""},
    }
    stale_upcoming = {
        "reservationId": "reservation-1",
        "guest": {"firstName": "Noch älter"},
        "keyCode": "stale-code",
        "otherNotes": "stale general",
        "notesForCleaner": "stale cleaner",
        "specialRequests": "stale request",
    }

    merged, _include_keycode = coordinator_module._merge_reservation_observations(
        [
            ("", rich_account_current, True),
            ("listing-1", scoped_current_clear, True),
            ("listing-1", stale_upcoming, False),
        ]
    )
    coordinator = _coordinator()
    coordinator.client.guests["guest-stale"] = {"firstName": "Falsch"}
    coordinator.client.populated["reservation-1"] = {"keycode": "remote-stale"}

    assert extract_reservation_notes(merged) == ("", "", "")
    assert asyncio.run(coordinator._async_guest(merged)) == {}
    assert asyncio.run(coordinator._async_keycode(merged)) == ""
    assert coordinator.client.guest_calls == []
    assert coordinator.client.custom_calls == []


def test_sensitive_clear_wins_inside_one_current_projection() -> None:
    current = {
        "reservationId": "reservation-1",
        "status": "confirmed",
        "keycode": "old-code",
        "notes": {
            "keyCode": "notes-old-code",
            "doorCode": "",
            "other": "old general note",
            "general": "",
        },
    }

    merged, _include_keycode = coordinator_module._merge_reservation_observations(
        [("listing-1", current, True)]
    )
    coordinator = _coordinator()
    coordinator.client.populated["reservation-1"] = {"keycode": "remote-stale"}

    assert extract_reservation_notes(merged)[0] == ""
    assert asyncio.run(coordinator._async_keycode(merged)) == ""
    assert coordinator.client.custom_calls == []


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

    coordinator.entry.options = {CONF_MAPPINGS: {endpoint: _mapping()}}
    coordinator.block_endpoints({endpoint})
    assert coordinator.mapping_options() == []


def test_explicit_sync_invalidates_guest_api_caches() -> None:
    coordinator = _coordinator()
    coordinator._keycode_cache[("reservation", "version")] = "opaque-code"
    coordinator._guest_cache["guest"] = (0.0, {"firstName": "Mia"})
    coordinator._custom_field_definitions["account"] = []
    coordinator._listing_detail_cache["listing"] = (0.0, Listing("listing", "Loft"))
    cached_snapshot = (SimpleNamespace(reservation_id="next"),)
    coordinator._reservation_snapshot_cache["listing"] = cached_snapshot

    coordinator.invalidate_guest_data_caches()

    assert coordinator._keycode_cache == {}
    assert coordinator._guest_cache == {}
    assert coordinator._custom_field_definitions == {}
    assert coordinator._listing_detail_cache == {}
    assert coordinator._reservation_snapshot_cache["listing"] is cached_snapshot


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


def test_live_weather_repairs_empty_cache_and_survives_temporary_outage() -> None:
    endpoint = "sensor.display"
    mapping = _mapping()
    mapping[CONF_WEATHER_ENTITY] = "weather.home"
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: mapping}},
        states={
            "weather.home": SimpleNamespace(
                state="sunny",
                attributes={"temperature": 21.6, "temperature_unit": "°C"},
            )
        },
    )
    cached = DisplayPayload(
        mode="welcome",
        property_name="LOFT",
        welcome_title="Hallo Anna",
        welcome_text="Willkommen",
        door_code="4827",
        wifi_name="WiFi",
        wifi_password="secret",
        checkout_label="morgen",
        valid_until_epoch=4102444800,
    )

    repaired = coordinator.payload_with_current_weather(endpoint, cached)

    assert repaired.weather_condition == "sunny"
    assert repaired.weather_temperature == "22 °C"
    assert repaired.content_id != cached.content_id
    assert repaired.base_content_id == cached.base_content_id

    coordinator.hass.states.states["weather.home"] = SimpleNamespace(
        state="unavailable", attributes={}
    )
    assert coordinator.payload_with_current_weather(endpoint, repaired) is repaired

    idle = DisplayPayload.idle(Listing("listing-1", "Loft"))
    assert coordinator.payload_with_current_weather(endpoint, idle) is idle

    empty = replace(
        repaired,
        mode="empty",
        weather_condition="",
        weather_temperature="",
    )
    assert coordinator.payload_with_current_weather(endpoint, empty) is empty

    checkout = replace(repaired, mode="checkout")
    coordinator.hass.states.states["weather.home"] = SimpleNamespace(
        state="rainy",
        attributes={"temperature": 17, "temperature_unit": "°C"},
    )
    checkout_weather = coordinator.payload_with_current_weather(endpoint, checkout)
    assert checkout_weather.weather_condition == "rainy"


def test_keycode_resolution_uses_direct_values_and_cache() -> None:
    client = FakeClient()
    coordinator = _coordinator(client=client)
    assert asyncio.run(coordinator._async_keycode({"keycode": "1234"})) == "1234"
    assert asyncio.run(coordinator._async_keycode({"doorCode": "2468"})) == "2468"
    assert (
        asyncio.run(coordinator._async_keycode({"notes": {"doorCode": "9753"}}))
        == "9753"
    )
    assert asyncio.run(coordinator._async_keycode({})) == ""

    client.populated["res-direct"] = {"keyCode": "5678"}
    raw = {"_id": "res-direct", "lastUpdatedAt": "v1"}
    assert asyncio.run(coordinator._async_keycode(raw)) == "5678"
    assert asyncio.run(coordinator._async_keycode(raw)) == "5678"
    assert client.custom_calls == ["res-direct"]


def test_keycode_without_change_marker_is_never_retained_indefinitely() -> None:
    client = FakeClient()
    client.populated["res-live"] = {"keyCode": "5678"}
    coordinator = _coordinator(client=client)
    raw = {"_id": "res-live"}

    assert asyncio.run(coordinator._async_keycode(raw)) == "5678"
    client.populated["res-live"] = {"customFields": []}
    assert asyncio.run(coordinator._async_keycode(raw)) == ""
    assert client.custom_calls == ["res-live", "res-live"]


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


@pytest.mark.parametrize(("current_value", "expected"), [("", ""), ("2468", "2468")])
def test_current_opaque_keycode_projection_wins_over_cache_and_remote_endpoint(
    current_value,
    expected,
) -> None:
    client = FakeClient()
    client.populated["res-current"] = {"keycode": "remote-stale"}
    client.definitions["account-1"] = [{"_id": "opaque-field", "name": "keycode"}]
    coordinator = _coordinator(client=client)
    coordinator._keycode_cache[("res-current", "v1")] = "cached-stale"
    raw = {
        "_id": "res-current",
        "accountId": "account-1",
        "lastUpdatedAt": "v1",
        "customFields": [
            {"fieldId": "opaque-field", "value": current_value},
            {"fieldId": "arrival-field", "value": "after 18:00"},
        ],
    }

    assert asyncio.run(coordinator._async_keycode(raw)) == expected
    assert client.custom_calls == []
    assert client.definition_calls == ["account-1"]
    if expected:
        assert coordinator._keycode_cache[("res-current", "v1")] == expected
    else:
        assert ("res-current", "v1") not in coordinator._keycode_cache


def test_opaque_current_clear_overrides_direct_sibling_projection() -> None:
    direct_current = {
        "_id": "res-current",
        "status": "confirmed",
        "accountId": "account-1",
        "lastUpdatedAt": "v1",
        "keycode": "old-code",
        "checkInDateLocalized": "2026-08-14",
        "checkOutDateLocalized": "2026-08-17",
        "stay": [{"listingId": "listing-1"}],
    }
    opaque_clear = {
        "_id": "res-current",
        "customFields": [{"fieldId": "opaque-field", "value": ""}],
    }
    merged, _include_keycode = coordinator_module._merge_reservation_observations(
        [
            ("listing-1", direct_current, True),
            ("listing-1", opaque_clear, True),
        ]
    )
    client = FakeClient()
    client.definitions["account-1"] = [{"_id": "opaque-field", "name": "keycode"}]
    client.populated["res-current"] = {"keycode": "remote-stale"}
    coordinator = _coordinator(client=client)
    coordinator._keycode_cache[("res-current", "v1")] = "cached-stale"

    reservation = asyncio.run(
        coordinator._async_normalize_reservation(
            merged,
            Listing("listing-1", "Loft"),
            include_keycode=True,
            resolved_listing_id="listing-1",
            current=datetime(2026, 8, 15, 12, 0, tzinfo=UTC),
        )
    )

    assert reservation is not None
    assert reservation.keycode == ""
    assert client.definition_calls == ["account-1"]
    assert client.custom_calls == []
    assert ("res-current", "v1") not in coordinator._keycode_cache


def test_definition_identified_code_projection_accepts_code_value_alias() -> None:
    client = FakeClient()
    client.definitions["account-1"] = [{"_id": "opaque-field", "name": "keycode"}]
    coordinator = _coordinator(client=client)
    raw = {
        "_id": "res-current",
        "accountId": "account-1",
        "customFields": [{"fieldId": "opaque-field", "code": "2468"}],
    }

    assert asyncio.run(coordinator._async_keycode(raw)) == "2468"
    assert client.custom_calls == []


def test_expired_definitions_cannot_make_an_opaque_clear_use_cached_code() -> None:
    current = {
        "_id": "res-current",
        "status": "confirmed",
        "accountId": "account-1",
        "lastUpdatedAt": "v1",
        "customFields": [{"fieldId": "new-field", "value": ""}],
    }
    merged, _include_keycode = coordinator_module._merge_reservation_observations(
        [("listing-1", current, True)]
    )
    client = FakeClient()
    client.definitions["account-1"] = GuestyError("temporary")
    coordinator = _coordinator(client=client)
    coordinator._custom_field_definitions["account-1"] = (
        0.0,
        [{"_id": "old-field", "name": "keycode"}],
    )
    coordinator._keycode_cache[("res-current", "v1")] = "cached-stale"

    assert asyncio.run(coordinator._async_keycode(merged)) == ""
    assert client.definition_calls == ["account-1"]
    assert client.custom_calls == []
    assert ("res-current", "v1") not in coordinator._keycode_cache


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


def test_guest_cache_is_rechecked_on_the_next_five_minute_poll(monkeypatch) -> None:
    client = FakeClient()
    client.guests["guest-1"] = {"firstName": "Mia"}
    coordinator = _coordinator(client=client)
    now = [100.0]
    monkeypatch.setattr(
        "custom_components.guesty_terminal.coordinator.time.monotonic",
        lambda: now[0],
    )
    raw = {"guestId": "guest-1"}

    assert asyncio.run(coordinator._async_guest(raw))["firstName"] == "Mia"
    client.guests["guest-1"] = {"firstName": "Anna"}
    now[0] += 299
    assert asyncio.run(coordinator._async_guest(raw))["firstName"] == "Mia"
    now[0] += 2
    assert asyncio.run(coordinator._async_guest(raw))["firstName"] == "Anna"
    assert client.guest_calls == ["guest-1", "guest-1"]


def test_expired_guest_cache_survives_a_temporary_lookup_failure(monkeypatch) -> None:
    client = FakeClient()
    client.guests["guest-1"] = {"firstName": "Mia"}
    coordinator = _coordinator(client=client)
    now = [100.0]
    monkeypatch.setattr(
        "custom_components.guesty_terminal.coordinator.time.monotonic",
        lambda: now[0],
    )
    raw = {"guestId": "guest-1"}

    assert asyncio.run(coordinator._async_guest(raw))["firstName"] == "Mia"
    now[0] += 301
    client.guests["guest-1"] = GuestyError("temporary")

    assert asyncio.run(coordinator._async_guest(raw))["firstName"] == "Mia"


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
        "terms": {"checkoutInstructions": "Fenster schließen."},
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
    assert data.listings["listing-1"].checkout_instructions == "Fenster schließen."
    assert len(data.reservations) == 1
    assert data.payloads[endpoint].door_code == "4827"
    assert data.payloads[endpoint].welcome_title == "Hallo Anna"
    assert data.payloads[endpoint].weather_condition == "sunny"
    assert data.payloads[endpoint].weather_temperature == "22 °C"
    assert client.guest_calls == ["guest-1"]

    asyncio.run(coordinator._async_update_data())
    assert client.listing_calls == ["listing-1", "listing-1"]


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


def test_broken_listing_details_do_not_block_unrelated_displays() -> None:
    client = FakeClient()
    client.listings = [
        {
            "_id": "good",
            "title": "Good",
            "wifiName": "WiFi",
            "wifiPassword": "password",
            "checkoutInstructions": "Leave keys inside.",
        }
    ]
    client.full_listings["removed"] = GuestyError("not found")
    coordinator = _coordinator(
        {
            CONF_MAPPINGS: {
                "sensor.good": _mapping("good"),
                "sensor.removed": _mapping("removed"),
            }
        },
        client,
    )

    data = asyncio.run(coordinator._async_update_data())

    assert "sensor.good" in data.payloads
    assert "sensor.removed" not in data.payloads


def test_failed_listing_detail_does_not_revive_cached_wifi_credentials() -> None:
    endpoint = "sensor.display_guesty_terminal_endpoint"
    client = FakeClient()
    client.listings = [{"_id": "listing-1", "title": "Loft"}]
    client.full_listings["listing-1"] = GuestyError("temporarily unavailable")
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: _mapping("listing-1")}},
        client,
    )
    coordinator._listing_detail_cache["listing-1"] = (
        0.0,
        Listing(
            "listing-1",
            "Loft",
            wifi_name="Old WiFi",
            wifi_password="old-password",
        ),
    )

    data = asyncio.run(coordinator._async_update_data())

    assert data.listings["listing-1"].wifi_name == ""
    assert data.listings["listing-1"].wifi_password == ""
    assert data.payloads[endpoint].wifi_name == ""
    assert data.payloads[endpoint].wifi_password == ""


def test_rate_limit_from_optional_enrichment_sets_coordinator_retry_after() -> None:
    client = FakeClient()
    client.listings = [{"_id": "listing-1", "title": "Loft"}]
    client.full_listings["listing-1"] = GuestyRateLimitError(73)
    coordinator = _coordinator({CONF_MAPPINGS: {"sensor.display": _mapping()}}, client)

    with pytest.raises(UpdateFailed) as error:
        asyncio.run(coordinator._async_update_data())
    assert error.value.retry_after == 73


def test_parallel_guesty_failure_cancels_sibling_requests() -> None:
    async def exercise() -> None:
        sibling_cancelled = asyncio.Event()

        async def fail():
            await asyncio.sleep(0)
            raise GuestyRateLimitError(60)

        async def block():
            try:
                await asyncio.Event().wait()
            finally:
                sibling_cancelled.set()

        with pytest.raises(GuestyRateLimitError):
            await coordinator_module._async_gather_cancel_on_error(fail(), block())
        assert sibling_cancelled.is_set()

    asyncio.run(exercise())


def test_update_reconciles_upcoming_booking_snapshot_for_empty_room_page() -> None:
    endpoint = "sensor.display_guesty_terminal_endpoint"
    client = FakeClient()
    client.listings = [
        {
            "_id": "listing-1",
            "title": "Loft",
            "timezone": "Europe/Berlin",
            "wifiName": "Guest WiFi",
            "wifiPassword": "secret",
            "checkoutInstructions": "Fenster schließen.",
        }
    ]
    client.upcoming_reservations["listing-1"] = [
        {
            "reservationId": "next-reservation",
            "stay": [{"listingId": "listing-1"}],
            "status": "confirmed",
            "guestId": "guest-next",
            "checkIn": "2099-09-10T14:00:00Z",
            "checkOut": "2099-09-13T08:00:00Z",
            "notes": {
                "other": "Anreise mit Hund",
                "cleaning": "Hundenapf bereitstellen",
                "specialRequests": "Allergiker-Kissen",
            },
        }
    ]
    client.guests["guest-next"] = {"firstName": "Mia", "lastName": "Muster"}
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: _mapping()}},
        client,
    )

    data = asyncio.run(coordinator._async_update_data())

    payload = data.payloads[endpoint]
    assert payload.mode == "empty"
    assert payload.next_booking_guest == "Mia"
    assert "2099" in payload.next_booking_period
    assert payload.general_notes == "Anreise mit Hund"
    assert payload.cleaner_notes == "Hundenapf bereitstellen"
    assert payload.special_requests == "Allergiker-Kissen"
    assert client.upcoming_reservation_calls == [("listing-1", 5)]
    assert client.guest_calls == ["guest-next"]
    assert client.custom_calls == []

    repeated = asyncio.run(coordinator._async_update_data())
    assert repeated.payloads[endpoint].next_booking_guest == "Mia"
    assert client.upcoming_reservation_calls == [
        ("listing-1", 5),
        ("listing-1", 5),
    ]
    assert client.guest_calls == ["guest-next"]


def test_multi_unit_assignment_preserves_all_three_display_transitions(
    monkeypatch,
) -> None:
    """A later concrete unit assignment must not orphan the mapped unit type."""

    class MutableDateTime(datetime):
        current = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is None else cls.current.astimezone(tz)

    monkeypatch.setattr(coordinator_module, "datetime", MutableDateTime)

    endpoint = "sensor.display_guesty_terminal_endpoint"
    client = FakeClient()
    listing = {
        "_id": "multi-unit-parent",
        "title": "Apartmenthaus",
        "timezone": "Europe/Berlin",
        "defaultCheckInTime": "15:00",
        "defaultCheckOutTime": "10:00",
        "wifiName": "Guest WiFi",
        "wifiPassword": "secret",
        "checkoutInstructions": "Schlüssel in die Box legen.",
    }
    client.listings = [listing]
    client.full_listings["multi-unit-parent"] = listing

    def booking(*, assigned: bool) -> dict:
        stay = {
            # Reservations-v3 search exposes the matched unit or unit type as
            # stay.listingId, plus the multi-unit parent after assignment.
            "listingId": ("assigned-apartment" if assigned else "multi-unit-parent"),
            "checkInDateLocalized": "2026-09-10",
            "checkOutDateLocalized": "2026-09-13",
            "plannedArrivalTime": "15:00",
            "plannedDepartureTime": "10:00",
        }
        if assigned:
            stay["parentListingId"] = "multi-unit-parent"
        return {
            "reservationId": "reservation-1",
            "status": "confirmed",
            "guest": {"firstName": "Anna"},
            "stay": [stay],
            "keycode": "4827",
            "notes": {"cleaning": "Kinderbett vorbereiten"},
        }

    mapping = _mapping("multi-unit-parent")
    mapping["lead_hours"] = 1
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: mapping}},
        client,
    )

    unassigned = booking(assigned=False)
    client.reservations_by_query[("multi-unit-parent",)] = []
    client.upcoming_reservations["multi-unit-parent"] = [unassigned]
    before_check_in = asyncio.run(coordinator._async_update_data())

    assert before_check_in.payloads[endpoint].mode == "empty"
    assert before_check_in.payloads[endpoint].next_booking_guest == "Anna"
    assert before_check_in.payloads[endpoint].cleaner_notes == (
        "Kinderbett vorbereiten"
    )
    assert client.reservation_as_of == [MutableDateTime.current]
    assert client.upcoming_as_of == [MutableDateTime.current]

    # Once the stay is under way, Guesty's search projects the assigned unit in
    # stay.listingId and the mapped unit type in stay.parentListingId. The
    # future-snapshot query also stops returning the stay after its arrival day.
    assigned = booking(assigned=True)
    client.reservations_by_query[("multi-unit-parent",)] = [assigned]
    client.upcoming_reservations["multi-unit-parent"] = []
    MutableDateTime.current = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)
    # A Home Assistant restart during the stay must route the real search shape
    # without depending on the earlier in-memory snapshot.
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: mapping}},
        client,
    )
    after_check_in = asyncio.run(coordinator._async_update_data())

    assert after_check_in.payloads[endpoint].mode == "welcome"
    assert after_check_in.payloads[endpoint].door_code == "4827"
    assert after_check_in.payloads[endpoint].wifi_name == "Guest WiFi"
    assert after_check_in.reservations[0].listing_id == "multi-unit-parent"
    assert client.reservation_as_of[-1] == MutableDateTime.current
    assert client.upcoming_as_of[-1] == MutableDateTime.current

    MutableDateTime.current = datetime(2026, 9, 13, 3, 1, tzinfo=UTC)
    checkout_day = asyncio.run(coordinator._async_update_data())

    assert checkout_day.payloads[endpoint].mode == "checkout"
    assert checkout_day.payloads[endpoint].checkout_instructions == (
        "Schlüssel in die Box legen."
    )
    assert checkout_day.payloads[endpoint].door_code == ""
    assert checkout_day.payloads[endpoint].wifi_name == ""


def test_account_snapshot_discovers_active_later_stay_segment_after_restart(
    monkeypatch,
) -> None:
    class FixedDateTime(datetime):
        current = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is None else cls.current.astimezone(tz)

    monkeypatch.setattr(coordinator_module, "datetime", FixedDateTime)
    endpoint = "sensor.unit_b_guesty_terminal_endpoint"
    client = FakeClient()
    listing = {
        "_id": "unit-b",
        "title": "Apartment B",
        "timezone": "Europe/Berlin",
        "wifiName": "Guest WiFi",
        "wifiPassword": "secret",
    }
    client.listings = [listing]
    client.full_listings["unit-b"] = listing
    # The scoped filter for unit-b is empty because Guesty only matches the
    # first stay segment. The unfiltered current snapshot still represents B.
    client.reservations_by_query[("unit-b",)] = []
    client.account_current_reservations = [
        {
            "reservationId": "relocation-1",
            "status": "confirmed",
            "guest": {"firstName": "Mia"},
            "keycode": "4827",
            "stay": [
                {
                    "listingId": "unit-a",
                    "checkIn": "2026-09-10T13:00:00Z",
                    "checkOut": "2026-09-10T22:30:00Z",
                },
                {
                    "listingId": "unit-b",
                    "checkIn": "2026-09-10T22:30:00Z",
                    "checkOut": "2026-09-13T08:00:00Z",
                },
            ],
        }
    ]
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: _mapping("unit-b")}},
        client,
    )

    data = asyncio.run(coordinator._async_update_data())

    assert client.account_current_calls == 1
    assert client.account_current_as_of == [FixedDateTime.current]
    assert data.payloads[endpoint].mode == "welcome"
    assert data.payloads[endpoint].door_code == "4827"
    assert data.reservations[0].listing_id == "unit-b"
    assert data.reservations[0].check_in == datetime(2026, 9, 10, 22, 30, tzinfo=UTC)


def test_account_current_discovery_failure_fails_the_whole_refresh() -> None:
    endpoint = "sensor.display_guesty_terminal_endpoint"
    client = FakeClient()
    listing = {"_id": "listing-1", "title": "Loft"}
    client.listings = [listing]
    client.full_listings["listing-1"] = listing
    client.account_current_reservations = GuestyError("account discovery failed")
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: _mapping("listing-1")}},
        client,
    )

    with pytest.raises(UpdateFailed, match="account discovery failed"):
        asyncio.run(coordinator._async_update_data())

    assert client.account_current_calls == 1


def test_missing_cached_active_stay_is_verified_before_removal(monkeypatch) -> None:
    class FixedDateTime(datetime):
        current = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is None else cls.current.astimezone(tz)

    monkeypatch.setattr(coordinator_module, "datetime", FixedDateTime)

    endpoint = "sensor.display_guesty_terminal_endpoint"
    client = FakeClient()
    listing = {
        "_id": "multi-unit-parent",
        "title": "Apartmenthaus",
        "timezone": "Europe/Berlin",
        "wifiName": "Guest WiFi",
        "wifiPassword": "secret",
    }
    search_row = {
        "reservationId": "reservation-active",
        "status": "confirmed",
        "guest": {"firstName": "Anna"},
        "keycode": "4827",
        "stay": [
            {
                "listingId": "assigned-apartment",
                "parentListingId": "multi-unit-parent",
                "checkInDateLocalized": "2026-09-10",
                "checkOutDateLocalized": "2026-09-13",
                "plannedArrivalTime": "15:00",
                "plannedDepartureTime": "10:00",
            }
        ],
    }
    client.listings = [listing]
    client.full_listings["multi-unit-parent"] = listing
    client.reservations_by_query[("multi-unit-parent",)] = [search_row]
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: _mapping("multi-unit-parent")}},
        client,
    )

    first = asyncio.run(coordinator._async_update_data())
    assert first.payloads[endpoint].mode == "welcome"

    client.reservations_by_query[("multi-unit-parent",)] = []
    client.verified_reservations["reservation-active"] = search_row
    verified = asyncio.run(coordinator._async_update_data())

    assert client.verification_calls == [["reservation-active"]]
    assert verified.payloads[endpoint].mode == "welcome"
    assert verified.payloads[endpoint].door_code == "4827"
    assert verified.reservations[0].listing_id == "multi-unit-parent"
    assert all(value == FixedDateTime.current for value in client.reservation_as_of)
    assert all(value == FixedDateTime.current for value in client.upcoming_as_of)

    client.verified_reservations.clear()
    removed = asyncio.run(coordinator._async_update_data())

    assert client.verification_calls == [
        ["reservation-active"],
        ["reservation-active"],
    ]
    assert removed.reservations == ()
    assert removed.payloads[endpoint].mode == "idle"


def test_transient_active_stay_verification_failure_retains_snapshot(
    monkeypatch,
) -> None:
    class FixedDateTime(datetime):
        current = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is None else cls.current.astimezone(tz)

    monkeypatch.setattr(coordinator_module, "datetime", FixedDateTime)

    endpoint = "sensor.display_guesty_terminal_endpoint"
    client = FakeClient()
    client.listings = [{"_id": "listing-1", "title": "Loft"}]
    client.reservations_by_query[("listing-1",)] = [
        {
            "reservationId": "reservation-active",
            "status": "confirmed",
            "stay": [{"listingId": "listing-1"}],
        }
    ]
    client.verification_failure = GuestyError("temporarily unavailable")
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: _mapping("listing-1")}},
        client,
    )
    cached_snapshot = (
        Reservation(
            "reservation-active",
            "listing-1",
            "confirmed",
            "Mia",
            FixedDateTime.current - timedelta(days=1),
            FixedDateTime.current + timedelta(days=1),
            keycode="4827",
        ),
    )
    coordinator._reservation_snapshot_cache["listing-1"] = cached_snapshot

    with pytest.raises(UpdateFailed, match="Could not refresh any mapped"):
        asyncio.run(coordinator._async_update_data())

    assert client.verification_calls == [["reservation-active"]]
    assert coordinator._reservation_snapshot_cache["listing-1"] is cached_snapshot


def test_unroutable_by_id_projection_never_reuses_cached_listing_context(
    monkeypatch,
) -> None:
    class FixedDateTime(datetime):
        current = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is None else cls.current.astimezone(tz)

    monkeypatch.setattr(coordinator_module, "datetime", FixedDateTime)
    endpoint = "sensor.display_guesty_terminal_endpoint"
    client = FakeClient()
    client.listings = [{"_id": "listing-1", "title": "Loft"}]
    client.verified_reservations["reservation-active"] = {
        "reservationId": "reservation-active",
        "status": "confirmed",
        "stay": [
            {
                "listingId": "unmapped-unit",
                "checkIn": "2026-09-10T13:00:00Z",
                "checkOut": "2026-09-13T08:00:00Z",
            }
        ],
    }
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: _mapping("listing-1")}},
        client,
    )
    cached_snapshot = (
        Reservation(
            "reservation-active",
            "listing-1",
            "confirmed",
            "Mia",
            FixedDateTime.current - timedelta(days=1),
            FixedDateTime.current + timedelta(days=1),
            keycode="4827",
        ),
    )
    coordinator._reservation_snapshot_cache["listing-1"] = cached_snapshot

    with pytest.raises(UpdateFailed, match="Could not refresh any mapped"):
        asyncio.run(coordinator._async_update_data())

    assert client.verification_calls == [["reservation-active"]]
    assert coordinator._reservation_snapshot_cache["listing-1"] is cached_snapshot


def test_missing_future_reservation_is_removed_without_by_id_verification(
    monkeypatch,
) -> None:
    class FixedDateTime(datetime):
        current = datetime(2026, 9, 10, 10, 0, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.current if tz is None else cls.current.astimezone(tz)

    monkeypatch.setattr(coordinator_module, "datetime", FixedDateTime)

    endpoint = "sensor.display_guesty_terminal_endpoint"
    client = FakeClient()
    client.listings = [{"_id": "listing-1", "title": "Loft"}]
    client.upcoming_reservations["listing-1"] = [
        {
            "reservationId": "reservation-future",
            "status": "confirmed",
            "guest": {"firstName": "Mia"},
            "stay": [{"listingId": "listing-1"}],
            "checkIn": "2026-09-12T14:00:00Z",
            "checkOut": "2026-09-13T08:00:00Z",
        }
    ]
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: _mapping("listing-1")}},
        client,
    )

    first = asyncio.run(coordinator._async_update_data())
    assert first.payloads[endpoint].mode == "empty"

    client.upcoming_reservations["listing-1"] = []
    removed = asyncio.run(coordinator._async_update_data())

    assert client.verification_calls == []
    assert removed.reservations == ()
    assert removed.payloads[endpoint].mode == "idle"


def test_snapshot_keeps_five_upcoming_bookings_and_changes_only_on_reconcile() -> None:
    endpoint = "sensor.display_guesty_terminal_endpoint"
    client = FakeClient()
    client.listings = [
        {
            "_id": "listing-1",
            "title": "Loft",
            "wifiName": "Guest WiFi",
            "wifiPassword": "secret",
            "checkoutInstructions": "Fenster schließen.",
        }
    ]

    def booking(number: int, *, notes: str = "") -> dict:
        return {
            "reservationId": f"booking-{number}",
            "listingId": "listing-1",
            "status": "confirmed",
            "guest": {"firstName": f"Guest{number}"},
            "checkIn": f"2099-09-{number + 10:02d}T14:00:00Z",
            "checkOut": f"2099-09-{number + 11:02d}T10:00:00Z",
            "notes": {"specialRequests": notes} if notes else {},
        }

    client.upcoming_reservations["listing-1"] = [
        booking(number) for number in range(1, 7)
    ]
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: _mapping()}},
        client,
    )

    first = asyncio.run(coordinator._async_update_data())
    first_snapshot = coordinator._reservation_snapshot_cache["listing-1"]

    assert [item.reservation_id for item in first.reservations] == [
        "booking-1",
        "booking-2",
        "booking-3",
        "booking-4",
        "booking-5",
    ]

    asyncio.run(coordinator._async_update_data())
    assert coordinator._reservation_snapshot_cache["listing-1"] is first_snapshot

    client.upcoming_reservations["listing-1"] = [
        booking(1),
        booking(3, notes="Late arrival"),
        booking(4),
        booking(5),
        booking(6),
    ]
    changed = asyncio.run(coordinator._async_update_data())
    changed_snapshot = coordinator._reservation_snapshot_cache["listing-1"]

    assert changed_snapshot is not first_snapshot
    assert [item.reservation_id for item in changed.reservations] == [
        "booking-1",
        "booking-3",
        "booking-4",
        "booking-5",
        "booking-6",
    ]
    assert changed_snapshot[1].special_requests == "Late arrival"
    assert client.upcoming_reservation_calls == [
        ("listing-1", 5),
        ("listing-1", 5),
        ("listing-1", 5),
    ]


def test_multiple_displays_receive_only_their_mapped_listing_payload() -> None:
    first_endpoint = "sensor.first_guesty_terminal_endpoint"
    second_endpoint = "sensor.second_guesty_terminal_endpoint"
    third_endpoint = "sensor.third_guesty_terminal_endpoint"
    client = FakeClient()
    client.listings = [
        {
            "_id": "listing-a",
            "title": "Loft A",
            "wifiName": "WiFi A",
            "wifiPassword": "password-a",
            "checkoutInstructions": "Leave A tidy.",
        },
        {
            "_id": "listing-b",
            "title": "Loft B",
            "wifiName": "WiFi B",
            "wifiPassword": "password-b",
            "checkoutInstructions": "Leave B tidy.",
        },
    ]
    client.reservations = [
        {
            "reservationId": "reservation-a",
            "listingId": "listing-a",
            "status": "confirmed",
            "guest": {"firstName": "Anna"},
            "keycode": "1111",
            "checkIn": "2026-08-14T12:00:00Z",
            "checkOut": "2099-08-18T10:00:00Z",
        },
        {
            "reservationId": "reservation-b",
            "listingId": "listing-b",
            "status": "confirmed",
            "guest": {"firstName": "Ben"},
            "keycode": "2222",
            "checkIn": "2026-08-14T12:00:00Z",
            "checkOut": "2099-08-18T10:00:00Z",
        },
    ]
    first_mapping = _mapping("listing-a")
    second_mapping = _mapping("listing-a")
    second_mapping["welcome_title"] = "Hi {first_name}"
    second_mapping["show_wifi"] = False
    third_mapping = _mapping("listing-b")
    coordinator = _coordinator(
        {
            CONF_MAPPINGS: {
                first_endpoint: first_mapping,
                second_endpoint: second_mapping,
                third_endpoint: third_mapping,
            }
        },
        client,
    )

    data = asyncio.run(coordinator._async_update_data())

    assert set(data.payloads) == {
        first_endpoint,
        second_endpoint,
        third_endpoint,
    }
    assert data.payloads[first_endpoint].reservation_id == "reservation-a"
    assert data.payloads[first_endpoint].door_code == "1111"
    assert data.payloads[first_endpoint].wifi_name == "WiFi A"
    assert data.payloads[second_endpoint].reservation_id == "reservation-a"
    assert data.payloads[second_endpoint].welcome_title == "Hi Anna"
    assert data.payloads[second_endpoint].wifi_name == ""
    assert data.payloads[third_endpoint].reservation_id == "reservation-b"
    assert data.payloads[third_endpoint].door_code == "2222"
    assert data.payloads[third_endpoint].wifi_name == "WiFi B"
    assert client.reservation_calls == [["listing-a"], ["listing-b"]]
    assert client.upcoming_reservation_calls == [
        ("listing-a", 5),
        ("listing-b", 5),
    ]


def test_context_only_reservation_is_never_copied_to_multiple_listings(
    caplog,
) -> None:
    first_endpoint = "sensor.first_guesty_terminal_endpoint"
    second_endpoint = "sensor.second_guesty_terminal_endpoint"
    client = FakeClient()
    client.listings = [
        {"_id": "listing-a", "title": "Loft A"},
        {"_id": "listing-b", "title": "Loft B"},
    ]
    # Simulate a sparse search projection returned for both mapped filters.
    # Without an explicit identity, choosing either listing would risk leaking
    # one guest's data to another property's display.
    client.reservations = [
        {
            "reservationId": "ambiguous-reservation",
            "status": "confirmed",
            "guest": {"firstName": "Anna"},
            "keycode": "1111",
            "checkIn": "2026-08-14T12:00:00Z",
            "checkOut": "2099-08-18T10:00:00Z",
        }
    ]
    coordinator = _coordinator(
        {
            CONF_MAPPINGS: {
                first_endpoint: _mapping("listing-a"),
                second_endpoint: _mapping("listing-b"),
            }
        },
        client,
    )

    data = asyncio.run(coordinator._async_update_data())

    assert data.reservations == ()
    assert data.payloads[first_endpoint].mode == "idle"
    assert data.payloads[second_endpoint].mode == "idle"
    assert "Skipped 1 Guesty reservation(s)" in caplog.text


def test_completed_booking_remains_cached_until_twelve_hours_after_checkout() -> None:
    coordinator = _coordinator()
    checkout = datetime(2026, 8, 20, 10, tzinfo=UTC)
    completed = Reservation(
        "completed",
        "listing-1",
        "confirmed",
        "Mia",
        checkout - timedelta(days=2),
        checkout,
    )
    future_cancelled = Reservation(
        "future-cancelled",
        "listing-1",
        "confirmed",
        "Lina",
        checkout + timedelta(days=2),
        checkout + timedelta(days=4),
    )
    coordinator._reservation_snapshot_cache["listing-1"] = (
        completed,
        future_cancelled,
    )

    coordinator._reconcile_reservation_snapshots(
        {},
        {"listing-1"},
        checkout + timedelta(hours=11, minutes=59),
    )

    assert coordinator._reservation_snapshot_cache["listing-1"] == (completed,)

    coordinator._prune_expired_reservation_snapshots(checkout + timedelta(hours=12))

    assert coordinator._reservation_snapshot_cache["listing-1"] == ()


def test_fresh_multi_stay_owner_removes_completed_copy_from_previous_listing() -> None:
    coordinator = _coordinator()
    transition = datetime(2026, 9, 11, 0, 30, tzinfo=UTC)
    previous_segment = Reservation(
        "relocation-1",
        "listing-a",
        "confirmed",
        "Mia",
        transition - timedelta(days=1),
        transition,
        keycode="4827",
    )
    active_segment = Reservation(
        "relocation-1",
        "listing-b",
        "confirmed",
        "Mia",
        transition,
        transition + timedelta(days=2),
        keycode="4827",
    )
    coordinator._reservation_snapshot_cache["listing-a"] = (previous_segment,)

    coordinator._reconcile_reservation_snapshots(
        {"listing-a": (), "listing-b": (active_segment,)},
        {"listing-a", "listing-b"},
        transition + timedelta(minutes=1),
    )

    assert coordinator._reservation_snapshot_cache["listing-a"] == ()
    assert coordinator._reservation_snapshot_cache["listing-b"] == (active_segment,)


@pytest.mark.parametrize("failed_query", ["current", "upcoming"])
def test_reservation_query_failure_isolated_per_listing(failed_query: str) -> None:
    first_endpoint = "sensor.first_guesty_terminal_endpoint"
    second_endpoint = "sensor.second_guesty_terminal_endpoint"
    client = FakeClient()
    client.listings = [
        {
            "_id": listing_id,
            "title": title,
            "wifiName": f"WiFi {listing_id}",
            "wifiPassword": "password",
        }
        for listing_id, title in (("listing-a", "Loft A"), ("listing-b", "Loft B"))
    ]
    if failed_query == "current":
        client.reservations_by_query[("listing-a",)] = GuestyError(
            "temporarily unavailable"
        )
    else:
        client.upcoming_reservations["listing-a"] = GuestyError(
            "temporarily unavailable"
        )
    client.upcoming_reservations["listing-b"] = [
        {
            "reservationId": "fresh-b",
            "status": "confirmed",
            "guest": {"firstName": "Lina"},
            "stay": [{"listingId": "listing-b"}],
            "checkIn": "2099-09-10T14:00:00Z",
            "checkOut": "2099-09-13T08:00:00Z",
        }
    ]
    coordinator = _coordinator(
        {
            CONF_MAPPINGS: {
                first_endpoint: _mapping("listing-a"),
                second_endpoint: _mapping("listing-b"),
            }
        },
        client,
    )

    cached_reservation = Reservation(
        "cached",
        "listing-a",
        "confirmed",
        "Mia",
        datetime.now(UTC) + timedelta(days=2),
        datetime.now(UTC) + timedelta(days=3),
    )
    cached_snapshot = (cached_reservation,)
    coordinator._reservation_snapshot_cache["listing-a"] = cached_snapshot

    data = asyncio.run(coordinator._async_update_data())

    assert coordinator._reservation_snapshot_cache["listing-a"] is cached_snapshot
    assert [item.reservation_id for item in data.reservations] == ["cached", "fresh-b"]
    assert first_endpoint not in data.payloads
    assert data.payloads[second_endpoint].next_booking_guest == "Lina"


def test_single_listing_query_failure_keeps_the_refresh_unsuccessful() -> None:
    endpoint = "sensor.display_guesty_terminal_endpoint"
    client = FakeClient()
    client.listings = [{"_id": "listing-1", "title": "Loft"}]
    client.reservations_by_query[("listing-1",)] = GuestyError(
        "temporarily unavailable"
    )
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: _mapping("listing-1")}},
        client,
    )
    cached_snapshot = (
        Reservation(
            "cached",
            "listing-1",
            "confirmed",
            "Mia",
            datetime.now(UTC) - timedelta(days=1),
            datetime.now(UTC) + timedelta(days=1),
        ),
    )
    coordinator._reservation_snapshot_cache["listing-1"] = cached_snapshot

    with pytest.raises(UpdateFailed, match="Could not refresh any mapped"):
        asyncio.run(coordinator._async_update_data())

    assert coordinator._reservation_snapshot_cache["listing-1"] is cached_snapshot


def test_incomplete_confirmed_projection_is_not_an_authoritative_empty_snapshot() -> (
    None
):
    endpoint = "sensor.display_guesty_terminal_endpoint"
    client = FakeClient()
    client.listings = [{"_id": "listing-1", "title": "Loft"}]
    client.reservations_by_query[("listing-1",)] = [
        {
            "reservationId": "incomplete",
            "status": "confirmed",
            "stay": [{"listingId": "listing-1"}],
        }
    ]
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: _mapping("listing-1")}},
        client,
    )

    with pytest.raises(UpdateFailed, match="Could not refresh any mapped"):
        asyncio.run(coordinator._async_update_data())

    assert coordinator._reservation_snapshot_cache == {}


def test_listing_requests_use_bounded_parallelism() -> None:
    class ConcurrentClient(FakeClient):
        def __init__(self) -> None:
            super().__init__()
            self.active_requests = 0
            self.maximum_active_requests = 0

        async def _track(self):
            self.active_requests += 1
            self.maximum_active_requests = max(
                self.maximum_active_requests, self.active_requests
            )
            await asyncio.sleep(0.01)
            self.active_requests -= 1

        async def async_get_listing(self, listing_id):
            self.listing_calls.append(listing_id)
            await self._track()
            return self.full_listings[listing_id]

        async def async_get_upcoming_reservations(
            self, listing_id, *, limit, as_of=None
        ):
            self.upcoming_reservation_calls.append((listing_id, limit))
            self.upcoming_as_of.append(as_of)
            await self._track()
            return []

    client = ConcurrentClient()
    listing_ids = [f"listing-{index}" for index in range(6)]
    client.listings = [
        {"_id": listing_id, "title": f"Loft {index}"}
        for index, listing_id in enumerate(listing_ids)
    ]
    client.full_listings = {
        listing_id: {"_id": listing_id, "title": f"Loft {index}"}
        for index, listing_id in enumerate(listing_ids)
    }
    options = {
        CONF_MAPPINGS: {
            f"sensor.display_{index}_guesty_terminal_endpoint": _mapping(listing_id)
            for index, listing_id in enumerate(listing_ids)
        }
    }

    data = asyncio.run(_coordinator(options, client)._async_update_data())

    assert len(data.listings) == 6
    assert client.maximum_active_requests == 4


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
