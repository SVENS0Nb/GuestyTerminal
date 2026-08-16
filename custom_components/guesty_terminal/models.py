"""Pure data models and selection logic for GuestyTerminal."""

from __future__ import annotations

import hashlib
import html
import re
import textwrap
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .const import (
    ACTIVE_RESERVATION_STATUSES,
    DATE_TIME_FORMAT_US,
    DATE_TIME_FORMATS,
    DEFAULT_CHECKOUT_INSTRUCTIONS_FALLBACK,
    DEFAULT_CHECKOUT_INSTRUCTIONS_LABEL,
    DEFAULT_CHECKOUT_LABEL,
    DEFAULT_CHECKOUT_PAGE_MESSAGE,
    DEFAULT_CHECKOUT_PAGE_TITLE,
    DEFAULT_CHECKOUT_START_TIME,
    DEFAULT_CLEANER_NOTES_LABEL,
    DEFAULT_CLEAR_AFTER_MINUTES,
    DEFAULT_DATE_TIME_FORMAT,
    DEFAULT_DISPLAY_LANGUAGE,
    DEFAULT_DOOR_CODE_LABEL,
    DEFAULT_EMPTY_NO_BOOKING_TEXT,
    DEFAULT_EMPTY_PAGE_TITLE,
    DEFAULT_GENERAL_NOTES_LABEL,
    DEFAULT_IDLE_TEXT,
    DEFAULT_IDLE_TITLE,
    DEFAULT_LEAD_HOURS,
    DEFAULT_NO_ACTIVE_BOOKING_LABEL,
    DEFAULT_SPECIAL_REQUESTS_LABEL,
    DEFAULT_WELCOME_TEXT,
    DEFAULT_WELCOME_TITLE,
    DEFAULT_WIFI_KEY_LABEL,
    DEFAULT_WIFI_LABEL,
    DEFAULT_WIFI_NAME_LABEL,
    DISPLAY_LEASE_MINUTES,
    MODE_CHECKOUT,
    MODE_EMPTY,
    MODE_IDLE,
    MODE_WELCOME,
    SENSITIVE_DISPLAY_MODES,
)
from .localization import display_text_defaults, normalize_display_language

_FIELD_NORMALIZER = re.compile(r"[^a-z0-9]+")
_HTML_BREAK = re.compile(r"(?i)<br\s*/?>")
_HTML_TAG = re.compile(r"<[^>]+>")
_CHECKOUT_INSTRUCTION_KEYS = {
    "checkoutinstruction",
    "checkoutinstructions",
    "departureinstruction",
    "departureinstructions",
}


def _string(value: Any) -> str:
    """Return a stripped string for scalar API values."""
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value).strip()


def normalize_field_name(value: Any) -> str:
    """Normalize a Guesty field name for tolerant matching."""
    return _FIELD_NORMALIZER.sub("", _string(value).lower())


def sanitize_door_code(value: Any) -> str:
    """Remove invisible formatting and combining marks from a door code."""
    normalized = unicodedata.normalize("NFKC", _string(value))
    return "".join(
        character
        for character in normalized
        if not character.isspace()
        and unicodedata.category(character)[0] not in {"C", "M"}
    )


def _instruction_value(value: Any) -> str:
    """Return readable plain text from a flexible instruction value."""
    if isinstance(value, Mapping):
        for key in ("instructions", "instruction", "text", "notes", "details", "value"):
            text = _instruction_value(value.get(key))
            if text:
                return text
        return ""
    if isinstance(value, list):
        parts = [_instruction_value(item) for item in value]
        return "\n".join(part for part in parts if part)
    text = _string(value)
    if not text:
        return ""
    text = _HTML_BREAK.sub("\n", html.unescape(text))
    text = _HTML_TAG.sub("", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def extract_checkout_instructions(data: Any) -> str:
    """Find Guesty's listing checkout instructions across known API shapes."""
    if isinstance(data, Mapping):
        for key, value in data.items():
            if normalize_field_name(key) in _CHECKOUT_INSTRUCTION_KEYS:
                instructions = _instruction_value(value)
                if instructions:
                    return instructions
        for value in data.values():
            if isinstance(value, (Mapping, list)):
                instructions = extract_checkout_instructions(value)
                if instructions:
                    return instructions
    elif isinstance(data, list):
        for item in data:
            instructions = extract_checkout_instructions(item)
            if instructions:
                return instructions
    return ""


def extract_reservation_notes(data: Mapping[str, Any]) -> tuple[str, str, str]:
    """Return Guesty's general, cleaner and special-request reservation notes."""
    notes = data.get("notes")
    if not isinstance(notes, Mapping):
        notes = {}
    channel_metadata = data.get("channelMetadata")
    if not isinstance(channel_metadata, Mapping):
        channel_metadata = {}

    general = _instruction_value(
        notes.get("other")
        or notes.get("general")
        or data.get("generalNotes")
        or data.get("otherNotes")
    )
    cleaner = _instruction_value(
        notes.get("cleaning")
        or notes.get("cleaner")
        or data.get("cleaningNotes")
        or data.get("notesForCleaner")
    )
    special_requests = _instruction_value(
        notes.get("specialRequests")
        or notes.get("special_requests")
        or data.get("specialRequests")
        or channel_metadata.get("specialRequests")
    )
    return general, cleaner, special_requests


def first_present(mapping: Mapping[str, Any], *keys: str) -> str:
    """Return the first non-empty scalar from a mapping."""
    for key in keys:
        value = _string(mapping.get(key))
        if value:
            return value
    return ""


def reservation_listing_id(data: Mapping[str, Any]) -> str:
    """Return a listing ID from legacy or Reservations v3 data."""
    listing_id = first_present(data, "listingId")
    if listing_id:
        return listing_id

    nested_listing = data.get("listing")
    if isinstance(nested_listing, Mapping):
        listing_id = first_present(nested_listing, "_id", "id")
        if listing_id:
            return listing_id

    stay = data.get("stay")
    if isinstance(stay, list):
        for segment in stay:
            if not isinstance(segment, Mapping):
                continue
            listing_id = first_present(
                segment,
                "listingId",
                "unitId",
                "unitTypeId",
                "parentListingId",
            )
            if listing_id:
                return listing_id
    return ""


def extract_keycode_direct(data: Any) -> str:
    """Find a directly named keycode in a Guesty response.

    Guesty accounts may expose this as ``keycode``, ``keyCode`` or as a
    populated custom-field object that already contains its name. The field ID
    only case is resolved separately with account custom-field definitions.
    """
    if isinstance(data, Mapping):
        for key, value in data.items():
            if normalize_field_name(key) == "keycode":
                scalar = sanitize_door_code(value)
                if not scalar and isinstance(value, Mapping):
                    scalar = sanitize_door_code(first_present(value, "value", "code"))
                if scalar:
                    return scalar

        field_names = (
            data.get("name"),
            data.get("fieldName"),
            data.get("key"),
            data.get("slug"),
            data.get("variable"),
            data.get("placeholder"),
            data.get("fieldId"),
        )
        if any(normalize_field_name(name) == "keycode" for name in field_names):
            scalar = sanitize_door_code(data.get("value"))
            if scalar:
                return scalar

        for key in ("customFields", "customField", "fields", "notes"):
            if key in data:
                found = extract_keycode_direct(data[key])
                if found:
                    return found

    elif isinstance(data, list):
        for item in data:
            found = extract_keycode_direct(item)
            if found:
                return found
    return ""


def build_custom_field_name_map(definitions: Any) -> dict[str, str]:
    """Build ``field id -> normalized name`` from flexible Guesty responses."""
    if isinstance(definitions, Mapping):
        for key in ("results", "customFields", "fields", "data"):
            nested = definitions.get(key)
            if isinstance(nested, list):
                definitions = nested
                break

    output: dict[str, str] = {}
    if not isinstance(definitions, list):
        return output

    for item in definitions:
        if not isinstance(item, Mapping):
            continue
        field_id = first_present(item, "fieldId", "_id", "id")
        if not field_id:
            continue
        candidates = (
            item.get("name"),
            item.get("fieldName"),
            item.get("key"),
            item.get("slug"),
            item.get("variable"),
            item.get("placeholder"),
        )
        for candidate in candidates:
            normalized = normalize_field_name(candidate)
            if normalized:
                output[field_id] = normalized
                break
    return output


def extract_keycode_from_custom_fields(populated_fields: Any, definitions: Any) -> str:
    """Resolve ``keycode`` from populated values and account definitions."""
    direct = extract_keycode_direct(populated_fields)
    if direct:
        return direct

    name_by_id = build_custom_field_name_map(definitions)
    if isinstance(populated_fields, Mapping):
        fields = populated_fields.get(
            "customFields", populated_fields.get("fields", [])
        )
    else:
        fields = populated_fields
    if not isinstance(fields, list):
        return ""

    for item in fields:
        if not isinstance(item, Mapping):
            continue
        field_id = first_present(item, "fieldId", "_id", "id")
        if name_by_id.get(field_id) == "keycode":
            return sanitize_door_code(item.get("value"))
    return ""


def _parse_iso_datetime(value: Any) -> datetime | None:
    text = _string(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _parse_date(value: Any) -> date | None:
    text = _string(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_time(value: Any, fallback: time) -> time:
    text = _string(value)
    if not text:
        return fallback
    if "T" in text:
        parsed = _parse_iso_datetime(text)
        if parsed is not None:
            return parsed.timetz().replace(tzinfo=None)
    try:
        return time.fromisoformat(text[:8])
    except ValueError:
        return fallback


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


@dataclass(frozen=True, slots=True)
class Listing:
    """Guesty listing details needed by the display."""

    listing_id: str
    title: str
    nickname: str = ""
    timezone: str = "UTC"
    default_check_in: str = "15:00"
    default_check_out: str = "10:00"
    wifi_name: str = ""
    wifi_password: str = ""
    checkout_instructions: str = ""

    @property
    def display_name(self) -> str:
        """Prefer Guesty's internal nickname when available."""
        return self.nickname or self.title or "Unterkunft"

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> Listing:
        """Create a listing from a Guesty API object."""
        return cls(
            listing_id=first_present(data, "_id", "id"),
            title=first_present(data, "title", "nickname") or "Unterkunft",
            nickname=first_present(data, "nickname"),
            timezone=first_present(data, "timezone") or "UTC",
            default_check_in=first_present(data, "defaultCheckInTime") or "15:00",
            default_check_out=(
                first_present(data, "defaultCheckOutTime", "defaultCheckoutTime")
                or "10:00"
            ),
            wifi_name=first_present(data, "wifiName"),
            wifi_password=first_present(data, "wifiPassword"),
            checkout_instructions=extract_checkout_instructions(data),
        )


@dataclass(frozen=True, slots=True)
class Reservation:
    """Normalized Guesty reservation."""

    reservation_id: str
    listing_id: str
    status: str
    first_name: str
    check_in: datetime
    check_out: datetime
    guest_name: str = ""
    keycode: str = ""
    account_id: str = ""
    general_notes: str = ""
    cleaner_notes: str = ""
    special_requests: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_api(
        cls, data: Mapping[str, Any], listing: Listing, *, keycode: str = ""
    ) -> Reservation | None:
        """Create a normalized reservation, or ``None`` for invalid dates."""
        zone = _timezone(listing.timezone)

        # Guesty's localized dates are the safest basis for guest-facing local
        # times. The V3 UTC timestamps can represent a floating property time
        # on channel-imported reservations. An explicit planned time wins;
        # otherwise combine the local date with the listing default.
        stay = data.get("stay")
        stay_segment = (
            next((item for item in stay if isinstance(item, Mapping)), {})
            if isinstance(stay, list)
            else {}
        )

        check_in_date = _parse_date(
            data.get("checkInDateLocalized") or stay_segment.get("checkInDateLocalized")
        )
        if check_in_date is not None:
            check_in = datetime.combine(
                check_in_date,
                _parse_time(
                    data.get("plannedArrival")
                    or data.get("plannedArrivalTime")
                    or stay_segment.get("plannedArrival")
                    or stay_segment.get("plannedArrivalTime")
                    or stay_segment.get("eta"),
                    _parse_time(listing.default_check_in, time(15, 0)),
                ),
                zone,
            )
        else:
            check_in = _parse_iso_datetime(
                data.get("checkIn")
                or data.get("checkInDate")
                or stay_segment.get("checkIn")
            )
            if check_in is None:
                check_in = _parse_iso_datetime(
                    data.get("plannedArrival")
                    or data.get("plannedArrivalTime")
                    or stay_segment.get("plannedArrival")
                    or stay_segment.get("plannedArrivalTime")
                    or stay_segment.get("eta")
                )

        check_out_date = _parse_date(
            data.get("checkOutDateLocalized")
            or stay_segment.get("checkOutDateLocalized")
        )
        if check_out_date is not None:
            check_out = datetime.combine(
                check_out_date,
                _parse_time(
                    data.get("plannedDeparture")
                    or data.get("plannedDepartureTime")
                    or stay_segment.get("plannedDeparture")
                    or stay_segment.get("plannedDepartureTime")
                    or stay_segment.get("etd"),
                    _parse_time(listing.default_check_out, time(10, 0)),
                ),
                zone,
            )
        else:
            check_out = _parse_iso_datetime(
                data.get("checkOut")
                or data.get("checkOutDate")
                or stay_segment.get("checkOut")
            )
            if check_out is None:
                check_out = _parse_iso_datetime(
                    data.get("plannedDeparture")
                    or data.get("plannedDepartureTime")
                    or stay_segment.get("plannedDeparture")
                    or stay_segment.get("plannedDepartureTime")
                    or stay_segment.get("etd")
                )

        if check_in is None or check_out is None:
            return None

        if check_in.tzinfo is None:
            check_in = check_in.replace(tzinfo=zone)
        if check_out.tzinfo is None:
            check_out = check_out.replace(tzinfo=zone)

        guest = data.get("guest")
        if not isinstance(guest, Mapping):
            guest = {}
        full_name = first_present(guest, "fullName", "fullname", "name")
        first_name = first_present(guest, "firstName", "firstname")
        if not first_name:
            first_name = full_name.split()[0] if full_name else "Gast"
        last_name = first_present(guest, "lastName", "lastname")
        guest_name = full_name or " ".join(
            part for part in (first_name, last_name) if part
        )

        listing_id = reservation_listing_id(data)
        general_notes, cleaner_notes, special_requests = extract_reservation_notes(data)

        return cls(
            reservation_id=first_present(data, "reservationId", "_id", "id"),
            listing_id=listing_id or listing.listing_id,
            status=first_present(data, "status").lower(),
            first_name=first_name,
            check_in=check_in,
            check_out=check_out,
            guest_name=guest_name or first_name,
            keycode=sanitize_door_code(keycode or extract_keycode_direct(data)),
            account_id=first_present(data, "accountId"),
            general_notes=general_notes,
            cleaner_notes=cleaner_notes,
            special_requests=special_requests,
            raw=data,
        )


@dataclass(frozen=True, slots=True)
class MappingOptions:
    """Per-display configuration stored in the options flow."""

    endpoint_entity: str
    listing_id: str
    display_language: str = DEFAULT_DISPLAY_LANGUAGE
    welcome_title: str = DEFAULT_WELCOME_TITLE
    welcome_text: str = DEFAULT_WELCOME_TEXT
    idle_title: str = DEFAULT_IDLE_TITLE
    idle_text: str = DEFAULT_IDLE_TEXT
    door_code_label: str = DEFAULT_DOOR_CODE_LABEL
    wifi_label: str = DEFAULT_WIFI_LABEL
    wifi_name_label: str = DEFAULT_WIFI_NAME_LABEL
    wifi_key_label: str = DEFAULT_WIFI_KEY_LABEL
    checkout_label: str = DEFAULT_CHECKOUT_LABEL
    checkout_start_time: str = DEFAULT_CHECKOUT_START_TIME
    checkout_page_title: str = DEFAULT_CHECKOUT_PAGE_TITLE
    checkout_page_message: str = DEFAULT_CHECKOUT_PAGE_MESSAGE
    checkout_instructions_label: str = DEFAULT_CHECKOUT_INSTRUCTIONS_LABEL
    checkout_instructions_fallback: str = DEFAULT_CHECKOUT_INSTRUCTIONS_FALLBACK
    empty_page_title: str = DEFAULT_EMPTY_PAGE_TITLE
    empty_no_booking_text: str = DEFAULT_EMPTY_NO_BOOKING_TEXT
    general_notes_label: str = DEFAULT_GENERAL_NOTES_LABEL
    cleaner_notes_label: str = DEFAULT_CLEANER_NOTES_LABEL
    special_requests_label: str = DEFAULT_SPECIAL_REQUESTS_LABEL
    date_time_format: str = DEFAULT_DATE_TIME_FORMAT
    lead_hours: int = DEFAULT_LEAD_HOURS
    clear_after_minutes: int = DEFAULT_CLEAR_AFTER_MINUTES
    show_door_code: bool = True
    show_wifi: bool = True
    weather_entity: str = ""

    @classmethod
    def from_dict(cls, endpoint: str, data: Mapping[str, Any]) -> MappingOptions:
        """Create options with defaults for older stored entries."""
        language = normalize_display_language(
            data.get("display_language"), fallback=DEFAULT_DISPLAY_LANGUAGE
        )
        defaults = display_text_defaults(language)
        date_time_format = _string(data.get("date_time_format"))
        if date_time_format not in DATE_TIME_FORMATS:
            date_time_format = DEFAULT_DATE_TIME_FORMAT
        try:
            checkout_start = time.fromisoformat(
                _string(data.get("checkout_start_time")) or DEFAULT_CHECKOUT_START_TIME
            )
        except ValueError:
            checkout_start = time.fromisoformat(DEFAULT_CHECKOUT_START_TIME)
        checkout_start_time = checkout_start.replace(microsecond=0).isoformat()
        return cls(
            endpoint_entity=endpoint,
            listing_id=_string(data.get("listing_id")),
            display_language=language,
            welcome_title=(
                _string(data.get("welcome_title")) or defaults.welcome_title
            ),
            welcome_text=_string(data.get("welcome_text")) or defaults.welcome_text,
            idle_title=_string(data.get("idle_title")) or defaults.idle_title,
            idle_text=_string(data.get("idle_text")) or defaults.idle_text,
            door_code_label=(
                _string(data.get("door_code_label")) or defaults.door_code_label
            ),
            wifi_label=_string(data.get("wifi_label")) or defaults.wifi_label,
            wifi_name_label=(
                _string(data.get("wifi_name_label")) or defaults.wifi_name_label
            ),
            wifi_key_label=(
                _string(data.get("wifi_key_label")) or defaults.wifi_key_label
            ),
            checkout_label=(
                _string(data.get("checkout_label")) or defaults.checkout_label
            ),
            checkout_start_time=checkout_start_time,
            checkout_page_title=(
                _string(data.get("checkout_page_title")) or defaults.checkout_page_title
            ),
            checkout_page_message=(
                _string(data.get("checkout_page_message"))
                or defaults.checkout_page_message
            ),
            checkout_instructions_label=(
                _string(data.get("checkout_instructions_label"))
                or defaults.checkout_instructions_label
            ),
            checkout_instructions_fallback=(
                _string(data.get("checkout_instructions_fallback"))
                or defaults.checkout_instructions_fallback
            ),
            empty_page_title=(
                _string(data.get("empty_page_title")) or defaults.empty_page_title
            ),
            empty_no_booking_text=(
                _string(data.get("empty_no_booking_text"))
                or defaults.empty_no_booking_text
            ),
            general_notes_label=(
                _string(data.get("general_notes_label")) or defaults.general_notes_label
            ),
            cleaner_notes_label=(
                _string(data.get("cleaner_notes_label")) or defaults.cleaner_notes_label
            ),
            special_requests_label=(
                _string(data.get("special_requests_label"))
                or defaults.special_requests_label
            ),
            date_time_format=date_time_format,
            lead_hours=int(data.get("lead_hours", DEFAULT_LEAD_HOURS)),
            clear_after_minutes=int(
                data.get("clear_after_minutes", DEFAULT_CLEAR_AFTER_MINUTES)
            ),
            show_door_code=bool(data.get("show_door_code", True)),
            show_wifi=bool(data.get("show_wifi", True)),
            weather_entity=_string(data.get("weather_entity")),
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialize options for a config entry."""
        return {
            "listing_id": self.listing_id,
            "display_language": self.display_language,
            "welcome_title": self.welcome_title,
            "welcome_text": self.welcome_text,
            "idle_title": self.idle_title,
            "idle_text": self.idle_text,
            "door_code_label": self.door_code_label,
            "wifi_label": self.wifi_label,
            "wifi_name_label": self.wifi_name_label,
            "wifi_key_label": self.wifi_key_label,
            "checkout_label": self.checkout_label,
            "checkout_start_time": self.checkout_start_time,
            "checkout_page_title": self.checkout_page_title,
            "checkout_page_message": self.checkout_page_message,
            "checkout_instructions_label": self.checkout_instructions_label,
            "checkout_instructions_fallback": self.checkout_instructions_fallback,
            "empty_page_title": self.empty_page_title,
            "empty_no_booking_text": self.empty_no_booking_text,
            "general_notes_label": self.general_notes_label,
            "cleaner_notes_label": self.cleaner_notes_label,
            "special_requests_label": self.special_requests_label,
            "date_time_format": self.date_time_format,
            "lead_hours": self.lead_hours,
            "clear_after_minutes": self.clear_after_minutes,
            "show_door_code": self.show_door_code,
            "show_wifi": self.show_wifi,
            "weather_entity": self.weather_entity,
        }


class _FormatValues(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


def render_template(template: str, values: Mapping[str, str]) -> str:
    """Render a small, safe string template without evaluating code."""
    try:
        return template.format_map(_FormatValues(values))
    except (KeyError, ValueError):
        return template


def _shorten(value: str, maximum: int) -> str:
    value = value.strip()
    if len(value) <= maximum:
        return value
    return f"{value[: maximum - 1].rstrip()}…"


def _wrap_display_text(value: str, width: int = 34, maximum_lines: int = 3) -> str:
    """Wrap display copy without splitting words or Unicode code points."""
    lines: list[str] = []
    for paragraph in value.strip().splitlines() or [""]:
        wrapped = textwrap.wrap(
            paragraph,
            width=width,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=True,
        ) or [""]
        lines.extend(wrapped)
    if len(lines) <= maximum_lines:
        return "\n".join(lines)
    visible = lines[:maximum_lines]
    visible[-1] = _shorten(visible[-1], width)
    if not visible[-1].endswith("…"):
        visible[-1] = _shorten(f"{visible[-1]}…", width)
    return "\n".join(visible)


@dataclass(frozen=True, slots=True)
class DisplayPayload:
    """Data sent to a reTerminal ESPHome action."""

    mode: str
    property_name: str
    welcome_title: str
    welcome_text: str
    door_code: str
    wifi_name: str
    wifi_password: str
    checkout_label: str
    valid_until_epoch: int
    door_code_label: str = DEFAULT_DOOR_CODE_LABEL
    wifi_label: str = DEFAULT_WIFI_LABEL
    wifi_name_label: str = DEFAULT_WIFI_NAME_LABEL
    wifi_key_label: str = DEFAULT_WIFI_KEY_LABEL
    idle_title: str = DEFAULT_IDLE_TITLE
    idle_text: str = DEFAULT_IDLE_TEXT
    no_active_booking_label: str = DEFAULT_NO_ACTIVE_BOOKING_LABEL
    checkout_instructions_title: str = ""
    checkout_instructions: str = ""
    next_booking_title: str = ""
    next_booking_guest: str = ""
    next_booking_period: str = ""
    general_notes_label: str = ""
    general_notes: str = ""
    cleaner_notes_label: str = ""
    cleaner_notes: str = ""
    special_requests_label: str = ""
    special_requests: str = ""
    weather_condition: str = ""
    weather_temperature: str = ""
    booking_summary: str = ""
    reservation_id: str = field(default="", compare=False, repr=False)

    @classmethod
    def idle(
        cls, listing: Listing, options: MappingOptions | None = None
    ) -> DisplayPayload:
        """Return the neutral, non-sensitive screen."""
        language = options.display_language if options is not None else None
        defaults = display_text_defaults(language or DEFAULT_DISPLAY_LANGUAGE)
        return cls(
            mode=MODE_IDLE,
            property_name=_shorten(listing.display_name.upper(), 38),
            welcome_title=_shorten(
                options.empty_page_title if options else defaults.empty_page_title,
                36,
            ),
            welcome_text=_wrap_display_text(
                options.empty_no_booking_text
                if options
                else defaults.empty_no_booking_text,
                width=42,
                maximum_lines=2,
            ),
            door_code="",
            wifi_name="",
            wifi_password="",
            checkout_label="",
            valid_until_epoch=0,
            door_code_label=(
                options.door_code_label if options else defaults.door_code_label
            ),
            wifi_label=options.wifi_label if options else defaults.wifi_label,
            wifi_name_label=(
                options.wifi_name_label if options else defaults.wifi_name_label
            ),
            wifi_key_label=(
                options.wifi_key_label if options else defaults.wifi_key_label
            ),
            idle_title=_shorten(
                options.empty_page_title if options else defaults.empty_page_title,
                36,
            ),
            idle_text=_wrap_display_text(
                options.empty_no_booking_text
                if options
                else defaults.empty_no_booking_text,
                width=42,
                maximum_lines=2,
            ),
            no_active_booking_label=defaults.no_active_booking,
            next_booking_title=_shorten(
                options.empty_page_title if options else defaults.empty_page_title,
                36,
            ),
            weather_condition="",
            weather_temperature="",
            booking_summary=(
                options.empty_no_booking_text
                if options
                else defaults.empty_no_booking_text
            ),
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        """Return true when sensitive content must no longer be sent."""
        if self.mode not in SENSITIVE_DISPLAY_MODES or self.valid_until_epoch <= 0:
            return False
        current = now or datetime.now(UTC)
        return int(current.timestamp()) >= self.valid_until_epoch

    @property
    def content_id(self) -> str:
        """Return an opaque stable ID for the visible E-paper contents."""
        return self._content_id(include_weather=True)

    @property
    def base_content_id(self) -> str:
        """Return the visible-content ID without the volatile weather block."""
        return self._content_id(include_weather=False)

    def _content_id(self, *, include_weather: bool) -> str:
        """Return a fingerprint compatible with the target renderer version."""
        visible_fields = [
            self.mode,
            self.property_name,
            self.welcome_title,
            self.welcome_text,
            self.door_code,
            self.wifi_name,
            self.wifi_password,
            self.checkout_label,
            self.door_code_label,
            self.wifi_label,
            self.wifi_name_label,
            self.wifi_key_label,
            self.checkout_instructions_title,
            self.checkout_instructions,
            self.next_booking_title,
            self.next_booking_guest,
            self.next_booking_period,
        ]
        for label, note in (
            (self.general_notes_label, self.general_notes),
            (self.cleaner_notes_label, self.cleaner_notes),
            (self.special_requests_label, self.special_requests),
        ):
            if note:
                visible_fields.extend((label, note))
        if include_weather and (self.weather_condition or self.weather_temperature):
            visible_fields.extend((self.weather_condition, self.weather_temperature))
        # The high-entropy Guesty reservation ID salts credential-bearing
        # screens. Only the opaque digest is persisted by the device.
        serialized = "\0".join((self.reservation_id, *visible_fields))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:24]

    def as_service_data(
        self,
        *,
        include_content_id: bool = False,
        include_booking_summary: bool = False,
        include_weather: bool = False,
        include_labels: bool = False,
        include_checkout_page: bool = False,
        include_empty_page: bool = False,
    ) -> dict[str, Any]:
        """Return the exact ESPHome action payload."""
        data = {
            "mode": self.mode,
            "property_name": self.property_name,
            "welcome_title": self.welcome_title,
            "welcome_text": self.welcome_text,
            "door_code": self.door_code,
            "wifi_name": self.wifi_name,
            "wifi_password": self.wifi_password,
            "checkout_label": self.checkout_label,
            "valid_until_epoch": self.valid_until_epoch,
        }
        if include_content_id:
            data["content_id"] = self._content_id(include_weather=include_weather)
        if include_booking_summary:
            data["booking_summary"] = self.booking_summary
        if include_weather:
            data["weather_condition"] = self.weather_condition
            data["weather_temperature"] = self.weather_temperature
        if include_labels:
            data["door_code_label"] = self.door_code_label
            data["wifi_label"] = self.wifi_label
            data["wifi_name_label"] = self.wifi_name_label
            data["wifi_key_label"] = self.wifi_key_label
            data["idle_title"] = self.idle_title
            data["idle_text"] = self.idle_text
            data["no_active_booking_label"] = self.no_active_booking_label
        if include_checkout_page:
            data["checkout_instructions_title"] = self.checkout_instructions_title
            data["checkout_instructions"] = self.checkout_instructions
        if include_empty_page:
            data["next_booking_title"] = self.next_booking_title
            data["next_booking_guest"] = self.next_booking_guest
            data["next_booking_period"] = self.next_booking_period
            data["general_notes_label"] = self.general_notes_label
            data["general_notes"] = self.general_notes
            data["cleaner_notes_label"] = self.cleaner_notes_label
            data["cleaner_notes"] = self.cleaner_notes
            data["special_requests_label"] = self.special_requests_label
            data["special_requests"] = self.special_requests
        return data


def select_reservation(
    reservations: list[Reservation],
    listing: Listing,
    *,
    now: datetime | None = None,
    lead_hours: int = DEFAULT_LEAD_HOURS,
    clear_after_minutes: int = DEFAULT_CLEAR_AFTER_MINUTES,
) -> Reservation | None:
    """Select the active or imminent reservation for a listing."""
    current = now or datetime.now(UTC)
    candidates: list[Reservation] = []
    for reservation in reservations:
        if reservation.listing_id != listing.listing_id:
            continue
        if reservation.status not in ACTIVE_RESERVATION_STATUSES:
            continue
        visible_from = reservation.check_in - timedelta(hours=max(0, lead_hours))
        visible_until = reservation.check_out + timedelta(
            minutes=max(0, clear_after_minutes)
        )
        if visible_from <= current < visible_until:
            candidates.append(reservation)

    if not candidates:
        return None

    def _selection_priority(reservation: Reservation) -> tuple[int, datetime]:
        if reservation.check_in <= current < reservation.check_out:
            return (0, reservation.check_in)
        if current >= reservation.check_out:
            return (1, reservation.check_in)
        return (2, reservation.check_in)

    # Prefer the current stay, then keep a previous stay visible throughout its
    # configured post-checkout grace period. An imminent next arrival must not
    # replace the checkout page before that explicit grace period has elapsed.
    return min(candidates, key=_selection_priority)


def select_next_reservation(
    reservations: list[Reservation],
    listing: Listing,
    *,
    now: datetime | None = None,
) -> Reservation | None:
    """Return the first confirmed future reservation for an empty room."""
    current = now or datetime.now(UTC)
    candidates = [
        reservation
        for reservation in reservations
        if reservation.listing_id == listing.listing_id
        and reservation.status in ACTIVE_RESERVATION_STATUSES
        and reservation.check_in > current
    ]
    return min(candidates, key=lambda item: item.check_in, default=None)


def _empty_booking_period(
    reservation: Reservation, listing: Listing, options: MappingOptions
) -> str:
    """Format the next stay using the display's inherited date/time format."""
    zone = _timezone(listing.timezone)
    check_in = reservation.check_in.astimezone(zone)
    check_out = reservation.check_out.astimezone(zone)
    language = normalize_display_language(options.display_language)
    if options.date_time_format == DATE_TIME_FORMAT_US:
        start = check_in.strftime("%m/%d/%Y, %I:%M %p").replace(", 0", ", ")
        end = check_out.strftime("%m/%d/%Y, %I:%M %p").replace(", 0", ", ")
    else:
        date_pattern = "%d.%m.%Y" if language == "de" else "%d/%m/%Y"
        time_suffix = " Uhr" if language == "de" else ""
        start = check_in.strftime(f"{date_pattern}, %H:%M{time_suffix}")
        end = check_out.strftime(f"{date_pattern}, %H:%M{time_suffix}")
    return f"{start} – {end}"


def _empty_room_payload(
    listing: Listing,
    reservation: Reservation,
    options: MappingOptions,
    *,
    now: datetime,
) -> DisplayPayload:
    """Build the room-empty page with a dynamic set of note cards."""
    period = _empty_booking_period(reservation, listing, options)
    notes = (
        reservation.general_notes,
        reservation.cleaner_notes,
        reservation.special_requests,
    )
    note_count = sum(bool(_string(note)) for note in notes)
    note_width = 88 if note_count == 1 else 40 if note_count == 2 else 25

    def visible_note(value: str) -> str:
        if not _string(value):
            return ""
        return _wrap_display_text(
            _shorten(value, 540), width=note_width, maximum_lines=6
        )

    visible_until = now + timedelta(minutes=DISPLAY_LEASE_MINUTES)
    safe_fallback = _wrap_display_text(
        options.empty_no_booking_text, width=42, maximum_lines=2
    )
    return DisplayPayload(
        mode=MODE_EMPTY,
        property_name=_shorten(listing.display_name.upper(), 38),
        welcome_title=_shorten(options.empty_page_title, 36),
        welcome_text=safe_fallback,
        door_code="",
        wifi_name="",
        wifi_password="",
        checkout_label="",
        valid_until_epoch=int(visible_until.timestamp()),
        door_code_label=_shorten(options.door_code_label, 24),
        wifi_label=_shorten(options.wifi_label, 16),
        wifi_name_label=_shorten(options.wifi_name_label, 12),
        wifi_key_label=_shorten(options.wifi_key_label, 12),
        idle_title=_shorten(options.empty_page_title, 36),
        idle_text=safe_fallback,
        no_active_booking_label=display_text_defaults(
            options.display_language
        ).no_active_booking,
        next_booking_title=_shorten(options.empty_page_title, 36),
        next_booking_guest=_shorten(reservation.first_name, 32),
        next_booking_period=_shorten(period, 96),
        general_notes_label=_shorten(options.general_notes_label, 22),
        general_notes=visible_note(reservation.general_notes),
        cleaner_notes_label=_shorten(options.cleaner_notes_label, 22),
        cleaner_notes=visible_note(reservation.cleaner_notes),
        special_requests_label=_shorten(options.special_requests_label, 22),
        special_requests=visible_note(reservation.special_requests),
        weather_condition="",
        weather_temperature="",
        booking_summary=_shorten(
            f"{reservation.guest_name or reservation.first_name} · {period}", 160
        ),
        reservation_id=reservation.reservation_id,
    )


def build_display_payload(
    listing: Listing,
    reservations: list[Reservation],
    options: MappingOptions,
    *,
    now: datetime | None = None,
    weather_condition: str = "",
    weather_temperature: str = "",
) -> DisplayPayload:
    """Build the guest or idle screen for a configured display."""
    current = now or datetime.now(UTC)
    reservation = select_reservation(
        reservations,
        listing,
        now=current,
        lead_hours=options.lead_hours,
        clear_after_minutes=options.clear_after_minutes,
    )
    if reservation is None:
        next_reservation = select_next_reservation(reservations, listing, now=current)
        if next_reservation is None:
            return DisplayPayload.idle(listing, options)
        return _empty_room_payload(
            listing,
            next_reservation,
            options,
            now=current,
        )

    zone = _timezone(listing.timezone)
    check_in_local = reservation.check_in.astimezone(zone)
    checkout_local = reservation.check_out.astimezone(zone)
    language = normalize_display_language(options.display_language)
    defaults = display_text_defaults(language)
    checkout_prefix = _shorten(options.checkout_label, 18)
    if options.date_time_format == DATE_TIME_FORMAT_US:
        check_in_display = check_in_local.strftime("%m/%d/%Y · %I:%M %p").replace(
            "· 0", "· "
        )
        check_out_display = checkout_local.strftime("%m/%d/%Y · %I:%M %p").replace(
            "· 0", "· "
        )
        checkout_value = checkout_local.strftime("%m/%d - %I:%M %p").replace(
            "- 0", "- "
        )
        booking_check_in = check_in_local.strftime("%m/%d/%Y %I:%M %p").replace(
            " 0", " "
        )
        booking_check_out = checkout_local.strftime("%m/%d/%Y %I:%M %p").replace(
            " 0", " "
        )
    else:
        date_pattern = "%d.%m.%Y" if language == "de" else "%d/%m/%Y"
        short_date_pattern = "%d.%m." if language == "de" else "%d/%m"
        time_suffix = " Uhr" if language == "de" else ""
        check_in_display = check_in_local.strftime(
            f"{date_pattern} · %H:%M{time_suffix}"
        )
        check_out_display = checkout_local.strftime(
            f"{date_pattern} · %H:%M{time_suffix}"
        )
        checkout_value = checkout_local.strftime(
            f"{short_date_pattern} - %H:%M{time_suffix}"
        )
        booking_check_in = check_in_local.strftime("%d.%m.%Y %H:%M")
        booking_check_out = checkout_local.strftime("%d.%m.%Y %H:%M")

    checkout_label = f"{checkout_prefix} {checkout_value}".strip()

    values = {
        "first_name": reservation.first_name,
        "property_name": listing.display_name,
        "check_in": check_in_display,
        "check_out": check_out_display,
        "check_out_date": check_out_display.split(" · ", 1)[0],
        "check_out_time": check_out_display.split(" · ", 1)[-1],
    }
    stay_visible_until = checkout_local + timedelta(
        minutes=max(0, options.clear_after_minutes)
    )
    # A short renewable lease prevents E-paper from retaining credentials after
    # a mapping or integration is removed while the display is asleep. Normal
    # coordinator refreshes renew it until the configured checkout grace ends.
    visible_until = min(
        stay_visible_until,
        current + timedelta(minutes=DISPLAY_LEASE_MINUTES),
    )

    checkout_start = datetime.combine(
        checkout_local.date(),
        _parse_time(options.checkout_start_time, time(5, 0)),
        zone,
    )
    checkout_start = max(checkout_start, check_in_local)
    if checkout_start <= current.astimezone(zone):
        checkout_title = render_template(options.checkout_page_title, values)
        checkout_message = render_template(options.checkout_page_message, values)
        instructions_title = render_template(
            options.checkout_instructions_label, values
        )
        instructions = listing.checkout_instructions or render_template(
            options.checkout_instructions_fallback, values
        )
        return DisplayPayload(
            mode=MODE_CHECKOUT,
            property_name=_shorten(listing.display_name.upper(), 38),
            welcome_title=_shorten(checkout_title, 36),
            welcome_text=_wrap_display_text(
                _shorten(checkout_message, 150), width=62, maximum_lines=2
            ),
            door_code="",
            wifi_name="",
            wifi_password="",
            checkout_label=check_out_display.replace(" · ", " - "),
            valid_until_epoch=int(visible_until.timestamp()),
            door_code_label=_shorten(options.door_code_label, 24),
            wifi_label=_shorten(options.wifi_label, 16),
            wifi_name_label=_shorten(options.wifi_name_label, 12),
            wifi_key_label=_shorten(options.wifi_key_label, 12),
            idle_title=_shorten(options.empty_page_title, 36),
            idle_text=_wrap_display_text(
                options.empty_no_booking_text, width=42, maximum_lines=2
            ),
            no_active_booking_label=defaults.no_active_booking,
            checkout_instructions_title=_shorten(instructions_title, 64),
            checkout_instructions=_wrap_display_text(
                _shorten(instructions, 360), width=76, maximum_lines=4
            ),
            next_booking_title=_shorten(options.empty_page_title, 36),
            weather_condition=_shorten(_string(weather_condition).lower(), 32),
            weather_temperature=_shorten(_string(weather_temperature), 16),
            booking_summary=_shorten(
                f"{reservation.guest_name or reservation.first_name} · "
                f"{booking_check_in} – {booking_check_out}",
                160,
            ),
            reservation_id=reservation.reservation_id,
        )

    title = render_template(options.welcome_title, values)
    body = render_template(options.welcome_text, values)

    return DisplayPayload(
        mode=MODE_WELCOME,
        property_name=_shorten(listing.display_name.upper(), 38),
        welcome_title=_shorten(title, 36),
        welcome_text=_wrap_display_text(_shorten(body, 150)),
        door_code=(
            _shorten(sanitize_door_code(reservation.keycode), 16)
            if options.show_door_code
            else ""
        ),
        wifi_name=_shorten(listing.wifi_name, 48) if options.show_wifi else "",
        wifi_password=_shorten(listing.wifi_password, 64) if options.show_wifi else "",
        checkout_label=checkout_label,
        valid_until_epoch=int(visible_until.timestamp()),
        door_code_label=_shorten(options.door_code_label, 24),
        wifi_label=_shorten(options.wifi_label, 16),
        wifi_name_label=_shorten(options.wifi_name_label, 12),
        wifi_key_label=_shorten(options.wifi_key_label, 12),
        idle_title=_shorten(options.empty_page_title, 36),
        idle_text=_wrap_display_text(
            options.empty_no_booking_text, width=42, maximum_lines=2
        ),
        no_active_booking_label=defaults.no_active_booking,
        next_booking_title=_shorten(options.empty_page_title, 36),
        weather_condition=_shorten(_string(weather_condition).lower(), 32),
        weather_temperature=_shorten(_string(weather_temperature), 16),
        booking_summary=_shorten(
            f"{reservation.guest_name or reservation.first_name} · "
            f"{booking_check_in} – {booking_check_out}",
            160,
        ),
        reservation_id=reservation.reservation_id,
    )
