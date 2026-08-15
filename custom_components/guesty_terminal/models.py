"""Pure data models and selection logic for GuestyTerminal."""

from __future__ import annotations

import re
import textwrap
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .const import (
    ACTIVE_RESERVATION_STATUSES,
    DEFAULT_CLEAR_AFTER_MINUTES,
    DEFAULT_LEAD_HOURS,
    DEFAULT_WELCOME_TEXT,
    DEFAULT_WELCOME_TITLE,
    DISPLAY_LEASE_MINUTES,
    MODE_IDLE,
    MODE_WELCOME,
)

_FIELD_NORMALIZER = re.compile(r"[^a-z0-9]+")


def _string(value: Any) -> str:
    """Return a stripped string for scalar API values."""
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value).strip()


def normalize_field_name(value: Any) -> str:
    """Normalize a Guesty field name for tolerant matching."""
    return _FIELD_NORMALIZER.sub("", _string(value).lower())


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
                scalar = _string(value)
                if not scalar and isinstance(value, Mapping):
                    scalar = first_present(value, "value", "code")
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
            scalar = _string(data.get("value"))
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
            return _string(item.get("value"))
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
            default_check_out=first_present(data, "defaultCheckOutTime") or "10:00",
            wifi_name=first_present(data, "wifiName"),
            wifi_password=first_present(data, "wifiPassword"),
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
    keycode: str = ""
    account_id: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_api(
        cls, data: Mapping[str, Any], listing: Listing, *, keycode: str = ""
    ) -> Reservation | None:
        """Create a normalized reservation, or ``None`` for invalid dates."""
        zone = _timezone(listing.timezone)

        check_in = _parse_iso_datetime(data.get("plannedArrival"))
        if check_in is None:
            check_in = _parse_iso_datetime(data.get("checkIn"))
        if check_in is None:
            local_date = _parse_date(data.get("checkInDateLocalized"))
            if local_date is not None:
                local_time = _parse_time(
                    data.get("plannedArrival"),
                    _parse_time(listing.default_check_in, time(15, 0)),
                )
                check_in = datetime.combine(local_date, local_time, zone)

        check_out = _parse_iso_datetime(data.get("plannedDeparture"))
        if check_out is None:
            check_out = _parse_iso_datetime(data.get("checkOut"))
        if check_out is None:
            local_date = _parse_date(data.get("checkOutDateLocalized"))
            if local_date is not None:
                local_time = _parse_time(
                    data.get("plannedDeparture"),
                    _parse_time(listing.default_check_out, time(10, 0)),
                )
                check_out = datetime.combine(local_date, local_time, zone)

        if check_in is None or check_out is None:
            return None

        if check_in.tzinfo is None:
            check_in = check_in.replace(tzinfo=zone)
        if check_out.tzinfo is None:
            check_out = check_out.replace(tzinfo=zone)

        guest = data.get("guest")
        if not isinstance(guest, Mapping):
            guest = {}
        first_name = first_present(guest, "firstName", "firstname")
        if not first_name:
            full_name = first_present(guest, "fullName", "fullname", "name")
            first_name = full_name.split()[0] if full_name else "Gast"

        listing_id = reservation_listing_id(data)

        return cls(
            reservation_id=first_present(data, "reservationId", "_id", "id"),
            listing_id=listing_id or listing.listing_id,
            status=first_present(data, "status").lower(),
            first_name=first_name,
            check_in=check_in,
            check_out=check_out,
            keycode=keycode or extract_keycode_direct(data),
            account_id=first_present(data, "accountId"),
            raw=data,
        )


@dataclass(frozen=True, slots=True)
class MappingOptions:
    """Per-display configuration stored in the options flow."""

    endpoint_entity: str
    listing_id: str
    welcome_title: str = DEFAULT_WELCOME_TITLE
    welcome_text: str = DEFAULT_WELCOME_TEXT
    lead_hours: int = DEFAULT_LEAD_HOURS
    clear_after_minutes: int = DEFAULT_CLEAR_AFTER_MINUTES
    show_door_code: bool = True
    show_wifi: bool = True

    @classmethod
    def from_dict(cls, endpoint: str, data: Mapping[str, Any]) -> MappingOptions:
        """Create options with defaults for older stored entries."""
        return cls(
            endpoint_entity=endpoint,
            listing_id=_string(data.get("listing_id")),
            welcome_title=_string(data.get("welcome_title")) or DEFAULT_WELCOME_TITLE,
            welcome_text=_string(data.get("welcome_text")) or DEFAULT_WELCOME_TEXT,
            lead_hours=int(data.get("lead_hours", DEFAULT_LEAD_HOURS)),
            clear_after_minutes=int(
                data.get("clear_after_minutes", DEFAULT_CLEAR_AFTER_MINUTES)
            ),
            show_door_code=bool(data.get("show_door_code", True)),
            show_wifi=bool(data.get("show_wifi", True)),
        )

    def as_dict(self) -> dict[str, Any]:
        """Serialize options for a config entry."""
        return {
            "listing_id": self.listing_id,
            "welcome_title": self.welcome_title,
            "welcome_text": self.welcome_text,
            "lead_hours": self.lead_hours,
            "clear_after_minutes": self.clear_after_minutes,
            "show_door_code": self.show_door_code,
            "show_wifi": self.show_wifi,
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
    reservation_id: str = field(default="", compare=False, repr=False)

    @classmethod
    def idle(cls, listing: Listing) -> DisplayPayload:
        """Return the neutral, non-sensitive screen."""
        return cls(
            mode=MODE_IDLE,
            property_name=_shorten(listing.display_name.upper(), 38),
            welcome_title="Willkommen",
            welcome_text="Die Unterkunft ist für den nächsten Aufenthalt bereit.",
            door_code="",
            wifi_name="",
            wifi_password="",
            checkout_label="",
            valid_until_epoch=0,
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        """Return true when sensitive content must no longer be sent."""
        if self.mode != MODE_WELCOME or self.valid_until_epoch <= 0:
            return False
        current = now or datetime.now(UTC)
        return int(current.timestamp()) >= self.valid_until_epoch

    def as_service_data(self) -> dict[str, Any]:
        """Return the exact ESPHome action payload."""
        return {
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
        if current < reservation.check_in:
            return (1, reservation.check_in)
        return (2, reservation.check_in)

    # Prefer the current stay, then the next arrival, and only then a previous
    # stay that is still inside its configured post-checkout grace period.
    return min(candidates, key=_selection_priority)


def build_display_payload(
    listing: Listing,
    reservations: list[Reservation],
    options: MappingOptions,
    *,
    now: datetime | None = None,
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
        return DisplayPayload.idle(listing)

    zone = _timezone(listing.timezone)
    values = {
        "first_name": reservation.first_name,
        "property_name": listing.display_name,
        "check_in": reservation.check_in.astimezone(zone).strftime("%d.%m.%Y"),
        "check_out": reservation.check_out.astimezone(zone).strftime("%d.%m.%Y"),
    }
    title = render_template(options.welcome_title, values)
    body = render_template(options.welcome_text, values)
    checkout_local = reservation.check_out.astimezone(zone)
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

    return DisplayPayload(
        mode=MODE_WELCOME,
        property_name=_shorten(listing.display_name.upper(), 38),
        welcome_title=_shorten(title, 36),
        welcome_text=_wrap_display_text(_shorten(body, 150)),
        door_code=_shorten(reservation.keycode, 16) if options.show_door_code else "",
        wifi_name=_shorten(listing.wifi_name, 48) if options.show_wifi else "",
        wifi_password=_shorten(listing.wifi_password, 64) if options.show_wifi else "",
        checkout_label=checkout_local.strftime("Check-out: %d.%m. · %H:%M Uhr"),
        valid_until_epoch=int(visible_until.timestamp()),
        reservation_id=reservation.reservation_id,
    )
