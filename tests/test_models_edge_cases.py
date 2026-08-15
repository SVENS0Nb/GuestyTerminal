"""Edge-case tests for Guesty normalization and selection rules."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from custom_components.guesty_terminal.models import (
    DisplayPayload,
    Listing,
    MappingOptions,
    Reservation,
    build_custom_field_name_map,
    build_display_payload,
    extract_keycode_direct,
    extract_keycode_from_custom_fields,
    first_present,
    normalize_field_name,
    render_template,
    select_reservation,
)


def test_scalar_and_keycode_helpers_handle_flexible_api_shapes() -> None:
    assert normalize_field_name(" Key-Code ") == "keycode"
    assert normalize_field_name({"not": "scalar"}) == ""
    assert first_present({"a": [], "b": 0, "c": " ok "}, "a", "b", "c") == "0"
    assert (
        extract_keycode_direct({"fields": [{"slug": "key_code", "value": 123}]})
        == "123"
    )
    assert extract_keycode_direct([None, {"keycode": {"code": "9876"}}]) == "9876"
    assert extract_keycode_direct({"keycode": []}) == ""
    assert extract_keycode_direct("keycode") == ""


def test_custom_field_definition_helpers_ignore_malformed_entries() -> None:
    definitions = {
        "results": [
            None,
            {"name": "missing id"},
            {"id": "empty-name"},
            {"fieldId": "field-1", "placeholder": "Key Code"},
        ]
    }
    assert build_custom_field_name_map(definitions) == {"field-1": "keycode"}
    assert build_custom_field_name_map({"results": "invalid"}) == {}
    assert build_custom_field_name_map(None) == {}
    assert extract_keycode_from_custom_fields([], definitions) == ""
    assert extract_keycode_from_custom_fields({"fields": "invalid"}, definitions) == ""
    assert (
        extract_keycode_from_custom_fields(
            {"fields": [None, {"fieldId": "other", "value": "1234"}]},
            definitions,
        )
        == ""
    )


def test_listing_and_mapping_defaults_round_trip() -> None:
    listing = Listing.from_api(
        {
            "id": "listing-1",
            "nickname": "Innenstadt",
            "timezone": "",
            "defaultCheckInTime": "",
        }
    )
    assert listing.display_name == "Innenstadt"
    assert listing.title == "Innenstadt"
    assert listing.timezone == "UTC"
    assert Listing("id", "").display_name == "Unterkunft"

    mapping = MappingOptions.from_dict("sensor.display", {"listing_id": "listing-1"})
    assert MappingOptions.from_dict("sensor.display", mapping.as_dict()) == mapping


def test_reservation_parses_dates_times_names_and_invalid_values() -> None:
    listing = Listing(
        "listing-1",
        "Loft",
        timezone="Invalid/Timezone",
        default_check_in="bad",
        default_check_out="11:30:00",
    )
    reservation = Reservation.from_api(
        {
            "id": "res-1",
            "listing": {"id": "nested-listing"},
            "status": "CONFIRMED",
            "guest": {"fullName": "Ada Lovelace"},
            "checkInDateLocalized": "2026-08-14",
            "checkOutDateLocalized": "2026-08-17",
            "plannedArrival": "invalid",
            "plannedDeparture": "invalid",
            "keyCode": "4321",
            "accountId": "account-1",
        },
        listing,
    )
    assert reservation is not None
    assert reservation.first_name == "Ada"
    assert reservation.guest_name == "Ada Lovelace"
    assert reservation.listing_id == "nested-listing"
    assert reservation.check_in.hour == 15
    assert reservation.check_out.hour == 11
    assert reservation.status == "confirmed"
    assert reservation.keycode == "4321"

    timestamp_reservation = Reservation.from_api(
        {
            "_id": "res-2",
            "status": "reserved",
            "guest": "invalid",
            "plannedArrival": "2026-08-14T15:45:00",
            "plannedDeparture": "2026-08-17T10:00:00",
        },
        Listing("listing-1", "Loft", timezone="Europe/Berlin"),
        keycode="override",
    )
    assert timestamp_reservation is not None
    assert timestamp_reservation.first_name == "Gast"
    assert timestamp_reservation.check_in.utcoffset() is not None
    assert timestamp_reservation.keycode == "override"

    assert Reservation.from_api({"checkIn": "invalid"}, listing) is None


def test_local_dates_use_listing_defaults_instead_of_misaligned_utc_times() -> None:
    listing = Listing(
        "listing-1",
        "Loft",
        timezone="Europe/Berlin",
        default_check_in="14:00",
        default_check_out="11:00",
    )
    reservation = Reservation.from_api(
        {
            "id": "res-channel",
            "listingId": "listing-1",
            "status": "confirmed",
            "checkInDateLocalized": "2026-08-14",
            "checkOutDateLocalized": "2026-08-16",
            # Some channel/V3 payloads expose floating local timestamps as UTC.
            # Guest-facing times must come from the localized date semantics.
            "checkIn": "2026-08-14T12:00:00Z",
            "checkOut": "2026-08-16T12:00:00Z",
        },
        listing,
    )
    assert reservation is not None
    assert reservation.check_in.hour == 14
    assert reservation.check_out.hour == 11

    planned = Reservation.from_api(
        {
            "id": "res-late",
            "listingId": "listing-1",
            "status": "confirmed",
            "checkInDateLocalized": "2026-08-14",
            "checkOutDateLocalized": "2026-08-16",
            "plannedArrival": "15:30",
            "plannedDeparture": "12:15",
        },
        listing,
    )
    assert planned is not None
    assert planned.check_in.hour == 15
    assert planned.check_in.minute == 30
    assert planned.check_out.hour == 12
    assert planned.check_out.minute == 15


def test_templates_shortening_visibility_and_service_data() -> None:
    listing = Listing(
        "listing-1",
        "A" * 50,
        wifi_name="N" * 60,
        wifi_password="P" * 80,
    )
    reservation = Reservation(
        "res-1",
        "listing-1",
        "confirmed",
        "Anna",
        datetime(2026, 8, 14, 12, tzinfo=UTC),
        datetime(2026, 8, 17, 10, tzinfo=UTC),
        keycode="1" * 20,
    )
    options = MappingOptions(
        "sensor.display",
        "listing-1",
        welcome_title="Hallo {first_name} {unknown}" + "X" * 50,
        welcome_text="Text " + "Y" * 180,
    )
    payload = build_display_payload(
        listing,
        [reservation],
        options,
        now=datetime(2026, 8, 14, 12, tzinfo=UTC),
    )
    assert payload.property_name.endswith("…")
    assert len(payload.welcome_title) == 36
    assert len(payload.welcome_text.splitlines()) == 3
    assert all(len(line) <= 34 for line in payload.welcome_text.splitlines())
    assert payload.welcome_text.endswith("…")
    assert len(payload.door_code) == 16
    assert len(payload.wifi_name) == 48
    assert len(payload.wifi_password) == 64
    assert payload.as_service_data()["valid_until_epoch"] == payload.valid_until_epoch
    assert "booking_summary" not in payload.as_service_data()
    assert (
        payload.as_service_data(include_booking_summary=True)["booking_summary"]
        == payload.booking_summary
    )
    content_id = payload.content_id
    assert len(content_id) == 24
    assert payload.as_service_data(include_content_id=True)["content_id"] == content_id
    renewed = replace(payload, valid_until_epoch=payload.valid_until_epoch + 60)
    assert renewed.content_id == content_id
    assert replace(payload, door_code="different").content_id != content_id
    assert not DisplayPayload.idle(listing).is_expired()
    assert render_template("broken {", {}) == "broken {"

    hidden = build_display_payload(
        listing,
        [reservation],
        MappingOptions(
            "sensor.display",
            "listing-1",
            show_door_code=False,
            show_wifi=False,
        ),
        now=datetime(2026, 8, 14, 12, tzinfo=UTC),
    )
    assert hidden.door_code == ""
    assert hidden.wifi_name == ""


def test_reservation_selection_filters_and_prioritizes_candidates() -> None:
    listing = Listing("listing-1", "Loft")
    now = datetime(2026, 8, 14, 12, tzinfo=UTC)

    def reservation(identifier, listing_id, status, check_in, check_out):
        return Reservation(
            identifier,
            listing_id,
            status,
            "Guest",
            check_in,
            check_out,
        )

    ignored_listing = reservation(
        "other",
        "other-listing",
        "confirmed",
        datetime(2026, 8, 14, 10, tzinfo=UTC),
        datetime(2026, 8, 15, 10, tzinfo=UTC),
    )
    ignored_status = reservation(
        "cancelled",
        "listing-1",
        "cancelled",
        datetime(2026, 8, 14, 10, tzinfo=UTC),
        datetime(2026, 8, 15, 10, tzinfo=UTC),
    )
    outside = reservation(
        "future",
        "listing-1",
        "confirmed",
        datetime(2026, 8, 20, 10, tzinfo=UTC),
        datetime(2026, 8, 21, 10, tzinfo=UTC),
    )
    assert (
        select_reservation(
            [ignored_listing, ignored_status, outside],
            listing,
            now=now,
            lead_hours=-1,
            clear_after_minutes=-1,
        )
        is None
    )

    current = reservation(
        "current",
        "listing-1",
        "reserved",
        datetime(2026, 8, 14, 8, tzinfo=UTC),
        datetime(2026, 8, 15, 8, tzinfo=UTC),
    )
    upcoming = reservation(
        "upcoming",
        "listing-1",
        "confirmed",
        datetime(2026, 8, 14, 13, tzinfo=UTC),
        datetime(2026, 8, 16, 8, tzinfo=UTC),
    )
    selected = select_reservation([upcoming, current], listing, now=now, lead_hours=4)
    assert selected is upcoming
