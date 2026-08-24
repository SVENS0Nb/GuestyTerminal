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
)


class FakeClient:
    """Configurable asynchronous Guesty client."""

    def __init__(self) -> None:
        self.listings = []
        self.full_listings = {}
        self.reservations = []
        self.upcoming_reservations = {}
        self.populated = {}
        self.definitions = {}
        self.listing_calls = []
        self.reservation_calls = []
        self.upcoming_reservation_calls = []
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

    async def async_get_reservations(self, listing_ids):
        self.reservation_calls.append(listing_ids)
        return self.reservations

    async def async_get_upcoming_reservations(self, listing_id, *, limit):
        self.upcoming_reservation_calls.append((listing_id, limit))
        value = self.upcoming_reservations.get(listing_id, [])
        if isinstance(value, Exception):
            raise value
        return value

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


def test_rate_limit_from_optional_enrichment_sets_coordinator_retry_after() -> None:
    client = FakeClient()
    client.listings = [{"_id": "listing-1", "title": "Loft"}]
    client.full_listings["listing-1"] = GuestyRateLimitError(73)
    coordinator = _coordinator({CONF_MAPPINGS: {"sensor.display": _mapping()}}, client)

    with pytest.raises(UpdateFailed) as error:
        asyncio.run(coordinator._async_update_data())
    assert error.value.retry_after == 73


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

    def booking(*, assigned: bool, include_parent: bool = True) -> dict:
        stay = {
            "checkInDateLocalized": "2026-09-10",
            "checkOutDateLocalized": "2026-09-13",
            "plannedArrivalTime": "15:00",
            "plannedDepartureTime": "10:00",
        }
        if include_parent:
            stay["unitTypeId"] = "multi-unit-parent"
        if assigned:
            stay["unitId"] = "assigned-apartment"
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
    client.reservations = [unassigned]
    client.upcoming_reservations["multi-unit-parent"] = [unassigned]
    before_check_in = asyncio.run(coordinator._async_update_data())

    assert before_check_in.payloads[endpoint].mode == "empty"
    assert before_check_in.payloads[endpoint].next_booking_guest == "Anna"
    assert before_check_in.payloads[endpoint].cleaner_notes == (
        "Kinderbett vorbereiten"
    )

    # Once the stay is under way, Guesty's current-reservation search may only
    # project the assigned concrete unit. The configured unit type is still the
    # filter that matched this row, but no longer appears in the response. The
    # future-snapshot query also stops returning the stay after its arrival day.
    assigned = booking(assigned=True, include_parent=False)
    client.reservations = [assigned]
    client.upcoming_reservations["multi-unit-parent"] = []
    MutableDateTime.current = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)
    # The query context must be sufficient on its own; a Home Assistant restart
    # during the stay must not depend on the earlier in-memory snapshot.
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: mapping}},
        client,
    )
    after_check_in = asyncio.run(coordinator._async_update_data())

    assert after_check_in.payloads[endpoint].mode == "welcome"
    assert after_check_in.payloads[endpoint].door_code == "4827"
    assert after_check_in.payloads[endpoint].wifi_name == "Guest WiFi"
    assert after_check_in.reservations[0].listing_id == "multi-unit-parent"

    MutableDateTime.current = datetime(2026, 9, 13, 3, 1, tzinfo=UTC)
    checkout_day = asyncio.run(coordinator._async_update_data())

    assert checkout_day.payloads[endpoint].mode == "checkout"
    assert checkout_day.payloads[endpoint].checkout_instructions == (
        "Schlüssel in die Box legen."
    )
    assert checkout_day.payloads[endpoint].door_code == ""
    assert checkout_day.payloads[endpoint].wifi_name == ""


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


def test_upcoming_snapshot_failure_does_not_replace_cached_data() -> None:
    endpoint = "sensor.display_guesty_terminal_endpoint"
    client = FakeClient()
    client.listings = [
        {
            "_id": "listing-1",
            "title": "Loft",
            "wifiName": "WiFi",
            "wifiPassword": "password",
            "checkoutInstructions": "Fenster schließen.",
        }
    ]
    client.upcoming_reservations["listing-1"] = GuestyError("temporarily unavailable")
    coordinator = _coordinator(
        {CONF_MAPPINGS: {endpoint: _mapping()}},
        client,
    )

    cached_reservation = Reservation(
        "cached",
        "listing-1",
        "confirmed",
        "Mia",
        datetime.now(UTC) + timedelta(days=1),
        datetime.now(UTC) + timedelta(days=2),
    )
    cached_snapshot = (cached_reservation,)
    coordinator._reservation_snapshot_cache["listing-1"] = cached_snapshot

    with pytest.raises(UpdateFailed, match="temporarily unavailable"):
        asyncio.run(coordinator._async_update_data())

    assert coordinator._reservation_snapshot_cache["listing-1"] is cached_snapshot


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

        async def async_get_upcoming_reservations(self, listing_id, *, limit):
            self.upcoming_reservation_calls.append((listing_id, limit))
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
