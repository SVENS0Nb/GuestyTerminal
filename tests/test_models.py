"""Tests for Guesty normalization and display selection."""

from datetime import UTC, datetime

from custom_components.guesty_terminal.models import (
    DisplayPayload,
    Listing,
    MappingOptions,
    Reservation,
    build_display_payload,
    extract_keycode_direct,
    extract_keycode_from_custom_fields,
    reservation_listing_id,
)


def _listing() -> Listing:
    return Listing(
        listing_id="listing-1",
        title="Apartment am Park",
        timezone="Europe/Berlin",
        default_check_in="15:00",
        default_check_out="11:00",
        wifi_name="Guest-WLAN",
        wifi_password="Beispiel-2026",
    )


def _reservation(keycode: str = "4827") -> Reservation:
    raw = {
        "_id": "reservation-1",
        "listingId": "listing-1",
        "status": "confirmed",
        "guest": {"firstName": "Anna"},
        "checkInDateLocalized": "2026-08-14",
        "checkOutDateLocalized": "2026-08-17",
        "keycode": keycode,
    }
    reservation = Reservation.from_api(raw, _listing())
    assert reservation is not None
    return reservation


def test_extracts_direct_keycode_variants() -> None:
    assert extract_keycode_direct({"keycode": "4827"}) == "4827"
    assert extract_keycode_direct({"keyCode": 9123}) == "9123"
    assert extract_keycode_direct({"keycode": {"value": "3159"}}) == "3159"
    assert extract_keycode_direct({"notes": {"keyCode": "8642"}}) == "8642"
    assert (
        extract_keycode_direct(
            {"customFields": [{"name": "Key code", "value": "7788"}]}
        )
        == "7788"
    )


def test_resolves_keycode_by_custom_field_definition() -> None:
    populated = {"customFields": [{"fieldId": "field-123", "value": "5643"}]}
    definitions = [{"_id": "field-123", "name": "keycode"}]
    assert extract_keycode_from_custom_fields(populated, definitions) == "5643"


def test_normalizes_v3_reservation_without_payment_dependency() -> None:
    raw = {
        "reservationId": "reservation-v3",
        "status": "confirmed",
        "guest": {"firstName": "Mia"},
        "checkIn": "2026-08-14T13:00:00Z",
        "checkOut": "2026-08-17T09:00:00Z",
        "stay": [{"listingId": "listing-1"}],
        "notes": {"keyCode": "7391"},
        # Payment and OTA payout state deliberately have no influence.
        "money": {"balanceDue": 999, "totalPaid": 0},
    }
    reservation = Reservation.from_api(raw, _listing())
    assert reservation is not None
    assert reservation.reservation_id == "reservation-v3"
    assert reservation.listing_id == "listing-1"
    assert reservation.keycode == "7391"
    assert reservation.status == "confirmed"
    assert reservation_listing_id(raw) == "listing-1"


def test_builds_welcome_payload_inside_lead_window() -> None:
    options = MappingOptions(
        endpoint_entity="sensor.guestyterminal_display_1_guesty_terminal_endpoint",
        listing_id="listing-1",
    )
    payload = build_display_payload(
        _listing(),
        [_reservation()],
        options,
        now=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
    )
    assert payload.mode == "welcome"
    assert payload.welcome_title == "Willkommen, Anna!"
    assert payload.door_code == "4827"
    assert payload.wifi_name == "Guest-WLAN"
    assert payload.wifi_password == "Beispiel-2026"
    assert payload.checkout_label == "Check-out: 17.08. · 11:00 Uhr"


def test_uses_idle_payload_before_lead_window() -> None:
    options = MappingOptions(
        endpoint_entity="sensor.guestyterminal_display_1_guesty_terminal_endpoint",
        listing_id="listing-1",
        lead_hours=2,
    )
    payload = build_display_payload(
        _listing(),
        [_reservation()],
        options,
        now=datetime(2026, 8, 14, 8, 0, tzinfo=UTC),
    )
    assert payload.mode == "idle"
    assert payload.door_code == ""
    assert payload.wifi_password == ""


def test_payload_lease_is_renewed_only_until_checkout_grace() -> None:
    options = MappingOptions(
        endpoint_entity="sensor.guestyterminal_display_1_guesty_terminal_endpoint",
        listing_id="listing-1",
    )
    payload = build_display_payload(
        _listing(),
        [_reservation()],
        options,
        now=datetime(2026, 8, 17, 8, 50, tzinfo=UTC),
    )
    assert not payload.is_expired(datetime(2026, 8, 17, 9, 4, tzinfo=UTC))
    assert payload.is_expired(datetime(2026, 8, 17, 9, 5, tzinfo=UTC))

    renewed = build_display_payload(
        _listing(),
        [_reservation()],
        options,
        now=datetime(2026, 8, 17, 9, 20, tzinfo=UTC),
    )
    assert not renewed.is_expired(datetime(2026, 8, 17, 9, 29, tzinfo=UTC))
    assert renewed.is_expired(datetime(2026, 8, 17, 9, 30, tzinfo=UTC))


def test_idle_payload_never_contains_credentials() -> None:
    payload = DisplayPayload.idle(_listing())
    assert payload.mode == "idle"
    assert payload.door_code == ""
    assert payload.wifi_name == ""
    assert payload.wifi_password == ""


def test_next_arrival_wins_over_previous_checkout_grace_period() -> None:
    listing = _listing()
    previous = Reservation(
        reservation_id="previous",
        listing_id=listing.listing_id,
        status="confirmed",
        first_name="Anna",
        check_in=datetime(2026, 8, 12, 13, 0, tzinfo=UTC),
        check_out=datetime(2026, 8, 14, 9, 0, tzinfo=UTC),
        keycode="1111",
    )
    next_guest = Reservation(
        reservation_id="next",
        listing_id=listing.listing_id,
        status="confirmed",
        first_name="Ben",
        check_in=datetime(2026, 8, 14, 13, 0, tzinfo=UTC),
        check_out=datetime(2026, 8, 17, 9, 0, tzinfo=UTC),
        keycode="2222",
    )
    options = MappingOptions(
        endpoint_entity="sensor.guestyterminal_display_1_guesty_terminal_endpoint",
        listing_id=listing.listing_id,
        lead_hours=4,
        clear_after_minutes=120,
    )

    payload = build_display_payload(
        listing,
        [previous, next_guest],
        options,
        now=datetime(2026, 8, 14, 9, 30, tzinfo=UTC),
    )

    assert payload.welcome_title == "Willkommen, Ben!"
    assert payload.door_code == "2222"
