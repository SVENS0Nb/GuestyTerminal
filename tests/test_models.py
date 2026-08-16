"""Tests for Guesty normalization and display selection."""

from dataclasses import replace
from datetime import UTC, datetime

from custom_components.guesty_terminal.models import (
    DisplayPayload,
    Listing,
    MappingOptions,
    Reservation,
    build_display_payload,
    extract_checkout_instructions,
    extract_keycode_direct,
    extract_keycode_from_custom_fields,
    extract_reservation_notes,
    reservation_listing_id,
    sanitize_door_code,
    select_next_reservation,
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
        checkout_instructions=(
            "Bitte Fenster schließen und den Schlüssel in die Box legen."
        ),
    )


def _reservation(keycode: str = "4827") -> Reservation:
    raw = {
        "_id": "reservation-1",
        "listingId": "listing-1",
        "status": "confirmed",
        "guest": {"firstName": "Anna", "lastName": "Beispiel"},
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
    assert sanitize_door_code("782070#\ufe0f\u20e3\u200b\n") == "782070#"
    assert extract_keycode_direct({"keycode": "782070#\ufe0f\u20e3"}) == "782070#"


def test_extracts_checkout_instructions_from_flexible_listing_shapes() -> None:
    assert extract_checkout_instructions(
        {"checkoutInstructions": "Fenster schließen."}
    ) == ("Fenster schließen.")
    assert (
        extract_checkout_instructions(
            {"terms": {"checkOutInstructions": "Schlüssel ablegen.<br>Danke!"}}
        )
        == "Schlüssel ablegen.\nDanke!"
    )
    assert (
        extract_checkout_instructions(
            {
                "departureInstructions": [
                    {"text": "Handtücher sammeln"},
                    {"details": "Tür schließen"},
                ]
            }
        )
        == "Handtücher sammeln\nTür schließen"
    )
    assert (
        extract_checkout_instructions(
            {"cleaning": {"instructions": "Not checkout copy"}}
        )
        == ""
    )


def test_extracts_only_supported_reservation_note_types() -> None:
    assert extract_reservation_notes(
        {
            "notes": {
                "other": "Allgemein<br>zweite Zeile",
                "cleaning": "Bitte Hochstuhl bereitstellen.",
                "guest": "Nicht auf der internen Seite anzeigen",
                "specialRequests": "Babybett gewünscht",
            }
        }
    ) == (
        "Allgemein\nzweite Zeile",
        "Bitte Hochstuhl bereitstellen.",
        "Babybett gewünscht",
    )
    assert extract_reservation_notes(
        {
            "generalNotes": "Allgemein",
            "notesForCleaner": "Reinigung",
            "specialRequests": "Späte Anreise",
        }
    ) == ("Allgemein", "Reinigung", "Späte Anreise")


def test_explicitly_cleared_notes_do_not_fall_back_to_stale_copies() -> None:
    assert extract_reservation_notes(
        {
            "notes": {
                "other": "",
                "cleaning": None,
                "specialRequests": "",
            },
            "generalNotes": "Veraltete allgemeine Notiz",
            "notesForCleaner": "Veraltete Reinigungsnotiz",
            "specialRequests": "Veralteter Sonderwunsch",
            "channelMetadata": {"specialRequests": "Veralteter Channel-Sonderwunsch"},
        }
    ) == ("", "", "")


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


def test_normalizes_v3_stay_dates_and_internal_notes() -> None:
    raw = {
        "reservationId": "reservation-v3-stay",
        "status": "confirmed",
        "guest": {"firstName": "Mia"},
        "stay": [
            {
                "listingId": "listing-1",
                "checkInDateLocalized": "2026-09-10",
                "checkOutDateLocalized": "2026-09-13",
                "plannedArrivalTime": "16:30",
                "plannedDepartureTime": "09:30",
            }
        ],
        "notes": {
            "other": "Allgemeine Notiz",
            "cleaning": "Kinderbett vorbereiten",
            "specialRequests": "Allergiker-Kissen",
        },
    }

    reservation = Reservation.from_api(raw, _listing())

    assert reservation is not None
    assert reservation.check_in == datetime(2026, 9, 10, 14, 30, tzinfo=UTC)
    assert reservation.check_out == datetime(2026, 9, 13, 7, 30, tzinfo=UTC)
    assert reservation.general_notes == "Allgemeine Notiz"
    assert reservation.cleaner_notes == "Kinderbett vorbereiten"
    assert reservation.special_requests == "Allergiker-Kissen"


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
    assert payload.door_code_label == "TÜRCODE"
    assert payload.wifi_name_label == "Name:"
    assert payload.checkout_label == "Check-out: 17.08. - 11:00 Uhr"
    assert (
        payload.booking_summary == "Anna Beispiel · 14.08.2026 15:00 – 17.08.2026 11:00"
    )


def test_uses_per_display_us_date_and_12_hour_time_format() -> None:
    options = MappingOptions(
        endpoint_entity="sensor.us_display_guesty_terminal_endpoint",
        listing_id="listing-1",
        welcome_title="Anreise: {check_in}",
        welcome_text="Abreise: {check_out}",
        date_time_format="us",
    )

    payload = build_display_payload(
        _listing(),
        [_reservation()],
        options,
        now=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
    )

    assert payload.welcome_title == "Anreise: 08/14/2026 · 3:00 PM"
    assert payload.welcome_text == "Abreise: 08/17/2026 · 11:00 AM"
    assert payload.checkout_label == "Check-out: 08/17 - 11:00 AM"
    assert (
        payload.booking_summary
        == "Anna Beispiel · 08/14/2026 3:00 PM – 08/17/2026 11:00 AM"
    )


def test_checkout_day_switches_to_its_own_localized_page_at_configured_time() -> None:
    options = MappingOptions(
        endpoint_entity="sensor.display_guesty_terminal_endpoint",
        listing_id="listing-1",
        weather_entity="weather.home",
    )

    before = build_display_payload(
        _listing(),
        [_reservation()],
        options,
        now=datetime(2026, 8, 17, 2, 59, tzinfo=UTC),
    )
    assert before.mode == "welcome"

    checkout = build_display_payload(
        _listing(),
        [_reservation()],
        options,
        now=datetime(2026, 8, 17, 3, 0, tzinfo=UTC),
        weather_condition="sunny",
        weather_temperature="20 °C",
    )
    assert checkout.mode == "checkout"
    assert checkout.welcome_title == "Heute ist Check-out, Anna"
    assert checkout.welcome_text == (
        "Danke, dass du unser Gast warst.\n"
        "Wir wünschen dir eine gute und entspannte Heimreise!"
    )
    assert checkout.checkout_instructions_title == "CHECK-OUT BIS 11:00 Uhr"
    assert checkout.checkout_instructions == (
        "Bitte Fenster schließen und den Schlüssel in die Box legen."
    )
    assert checkout.checkout_label == "17.08.2026 - 11:00 Uhr"
    assert checkout.door_code == ""
    assert checkout.wifi_name == ""
    assert checkout.weather_condition == "sunny"


def test_checkout_page_inherits_us_format_and_uses_configurable_fallback() -> None:
    listing = Listing(
        "listing-1",
        "Apartment am Park",
        timezone="Europe/Berlin",
        default_check_in="15:00",
        default_check_out="11:00",
    )
    options = MappingOptions(
        endpoint_entity="sensor.display_guesty_terminal_endpoint",
        listing_id="listing-1",
        display_language="en",
        date_time_format="us",
        checkout_start_time="06:30:00",
        checkout_page_title="Goodbye, {first_name}",
        checkout_page_message="Check-out is {check_out}.",
        checkout_instructions_label="LEAVE BY {check_out_time}",
        checkout_instructions_fallback="Close all windows.",
    )

    before = build_display_payload(
        listing,
        [_reservation()],
        options,
        now=datetime(2026, 8, 17, 4, 29, tzinfo=UTC),
    )
    assert before.mode == "welcome"

    checkout = build_display_payload(
        listing,
        [_reservation()],
        options,
        now=datetime(2026, 8, 17, 4, 30, tzinfo=UTC),
    )
    assert checkout.mode == "checkout"
    assert checkout.welcome_title == "Goodbye, Anna"
    assert checkout.welcome_text == "Check-out is 08/17/2026 · 11:00 AM."
    assert checkout.checkout_instructions_title == "LEAVE BY 11:00 AM"
    assert checkout.checkout_instructions == "Close all windows."
    assert checkout.checkout_label == "08/17/2026 - 11:00 AM"


def test_localizes_and_customizes_every_static_display_label() -> None:
    options = MappingOptions.from_dict(
        "sensor.fr_display_guesty_terminal_endpoint",
        {
            "listing_id": "listing-1",
            "display_language": "fr",
            "door_code_label": "ACCÈS",
            "wifi_label": "RÉSEAU",
            "wifi_name_label": "Nom :",
            "wifi_key_label": "Clé :",
            "checkout_label": "Départ :",
        },
    )
    payload = build_display_payload(
        _listing(),
        [_reservation()],
        options,
        now=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
    )

    assert payload.welcome_title == "Bienvenue, Anna !"
    assert payload.door_code_label == "ACCÈS"
    assert payload.wifi_label == "RÉSEAU"
    assert payload.wifi_name_label == "Nom :"
    assert payload.wifi_key_label == "Clé :"
    assert payload.checkout_label == "Départ : 17/08 - 11:00"
    service_data = payload.as_service_data(include_labels=True)
    assert service_data["door_code_label"] == "ACCÈS"
    assert service_data["wifi_key_label"] == "Clé :"
    assert service_data["idle_title"] == "PROCHAINE RÉSERVATION"
    assert service_data["idle_text"] == "Aucune réservation à venir"
    assert service_data["no_active_booking_label"] == ("Aucune réservation active")

    idle = DisplayPayload.idle(_listing(), options)
    assert idle.welcome_title == "PROCHAINE RÉSERVATION"
    assert idle.welcome_text == "Aucune réservation à venir"
    assert idle.idle_title == "PROCHAINE RÉSERVATION"
    assert idle.no_active_booking_label == "Aucune réservation active"
    assert idle.booking_summary == "Aucune réservation à venir"


def test_older_mapping_defaults_to_eu_date_and_time_format() -> None:
    mapping = MappingOptions.from_dict("sensor.display", {"listing_id": "listing-1"})
    assert mapping.date_time_format == "eu"
    assert mapping.weather_entity == ""

    invalid = MappingOptions.from_dict(
        "sensor.display", {"listing_id": "listing-1", "date_time_format": "other"}
    )
    assert invalid.date_time_format == "eu"


def test_corrupt_mapping_values_are_bounded_and_legacy_idle_copy_is_removed() -> None:
    mapping = MappingOptions.from_dict(
        "sensor.display",
        {
            "listing_id": "listing-1",
            "lead_hours": "invalid",
            "clear_after_minutes": 999,
            "show_door_code": "false",
            "show_wifi": "true",
            "idle_title": "Obsolete welcome page",
            "idle_text": "Obsolete welcome copy",
        },
    )

    assert mapping.lead_hours == 1
    assert mapping.clear_after_minutes == 120
    assert mapping.show_door_code is False
    assert mapping.show_wifi is True
    assert "idle_title" not in mapping.as_dict()
    assert "idle_text" not in mapping.as_dict()


def test_builds_weather_fields_into_visible_content() -> None:
    options = MappingOptions(
        endpoint_entity="sensor.display_guesty_terminal_endpoint",
        listing_id="listing-1",
        weather_entity="weather.home",
    )
    payload = build_display_payload(
        _listing(),
        [_reservation()],
        options,
        now=datetime(2026, 8, 14, 12, 0, tzinfo=UTC),
        weather_condition="PartlyCloudy",
        weather_temperature="18 °C",
    )

    assert payload.weather_condition == "partlycloudy"
    assert payload.weather_temperature == "18 °C"
    assert payload.as_service_data(include_weather=True)["weather_condition"] == (
        "partlycloudy"
    )
    assert (
        payload.as_service_data(include_content_id=True, include_weather=True)[
            "content_id"
        ]
        == payload.content_id
    )
    assert (
        payload.as_service_data(include_content_id=True)["content_id"]
        != payload.content_id
    )
    assert "weather_condition" not in payload.as_service_data()


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
    assert payload.mode == "empty"
    assert payload.next_booking_title == "NÄCHSTE BUCHUNG"
    assert payload.next_booking_guest == "Anna"
    assert payload.next_booking_period == (
        "14.08.2026, 15:00 Uhr – 17.08.2026, 11:00 Uhr"
    )
    assert payload.door_code == ""
    assert payload.wifi_password == ""


def test_empty_room_page_uses_one_full_width_note_slot_and_us_format() -> None:
    reservation = Reservation(
        reservation_id="next",
        listing_id="listing-1",
        status="confirmed",
        first_name="Noah",
        check_in=datetime(2026, 9, 10, 14, 0, tzinfo=UTC),
        check_out=datetime(2026, 9, 13, 8, 0, tzinfo=UTC),
        special_requests="Bitte ein allergikerfreundliches Kissen vorbereiten.",
    )
    options = MappingOptions.from_dict(
        "sensor.display_guesty_terminal_endpoint",
        {
            "listing_id": "listing-1",
            "display_language": "en",
            "date_time_format": "us",
        },
    )

    payload = build_display_payload(
        _listing(),
        [reservation],
        options,
        now=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        weather_condition="cloudy",
        weather_temperature="18 °C",
    )

    assert payload.mode == "empty"
    assert payload.next_booking_title == "NEXT BOOKING"
    assert payload.next_booking_guest == "Noah"
    assert payload.next_booking_period == ("09/10/2026, 4:00 PM – 09/13/2026, 10:00 AM")
    assert payload.general_notes == ""
    assert payload.cleaner_notes == ""
    assert payload.special_requests == (
        "Bitte ein allergikerfreundliches Kissen vorbereiten."
    )
    assert payload.special_requests_label == "SPECIAL REQUESTS"
    assert payload.weather_condition == ""
    assert payload.weather_temperature == ""
    assert payload.valid_until_epoch > 0


def test_empty_room_page_omits_all_empty_notes_and_selects_earliest_booking() -> None:
    later = Reservation(
        reservation_id="later",
        listing_id="listing-1",
        status="confirmed",
        first_name="Lina",
        check_in=datetime(2026, 10, 10, 14, 0, tzinfo=UTC),
        check_out=datetime(2026, 10, 12, 8, 0, tzinfo=UTC),
    )
    earlier = Reservation(
        reservation_id="earlier",
        listing_id="listing-1",
        status="confirmed",
        first_name="Ben",
        check_in=datetime(2026, 10, 3, 14, 0, tzinfo=UTC),
        check_out=datetime(2026, 10, 5, 8, 0, tzinfo=UTC),
    )
    cancelled = Reservation(
        reservation_id="cancelled",
        listing_id="listing-1",
        status="cancelled",
        first_name="Tom",
        check_in=datetime(2026, 9, 20, 14, 0, tzinfo=UTC),
        check_out=datetime(2026, 9, 22, 8, 0, tzinfo=UTC),
    )
    now = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)

    assert (
        select_next_reservation([later, cancelled, earlier], _listing(), now=now)
        is earlier
    )
    payload = build_display_payload(
        _listing(),
        [later, cancelled, earlier],
        MappingOptions("sensor.display", "listing-1"),
        now=now,
    )
    assert payload.mode == "empty"
    assert payload.next_booking_guest == "Ben"
    assert payload.general_notes == ""
    assert payload.cleaner_notes == ""
    assert payload.special_requests == ""
    assert (
        payload.content_id
        == replace(payload, general_notes_label="Invisible changed heading").content_id
    )


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
    assert payload.booking_summary == "Keine bevorstehende Buchung"


def test_previous_checkout_wins_over_next_arrival_during_grace_period() -> None:
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

    assert payload.mode == "checkout"
    assert payload.welcome_title == "Heute ist Check-out, Anna"
    assert payload.checkout_instructions == (
        "Bitte Fenster schließen und den Schlüssel in die Box legen."
    )
    assert payload.door_code == ""
    assert payload.reservation_id == "previous"
