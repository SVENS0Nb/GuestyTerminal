"""Guesty data coordinator."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Coroutine, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    GuestyAuthenticationError,
    GuestyClient,
    GuestyError,
    GuestyRateLimitError,
)
from .const import (
    ACTIVE_RESERVATION_STATUSES,
    COMPLETED_RESERVATION_CACHE_HOURS,
    CONF_MAPPINGS,
    CONF_POLL_MINUTES,
    DEFAULT_POLL_MINUTES,
    DOMAIN,
    MAX_POLL_MINUTES,
    UPCOMING_RESERVATIONS_PER_LISTING,
    WEATHER_DISPLAY_MODES,
)
from .models import (
    DisplayPayload,
    Listing,
    MappingOptions,
    Reservation,
    build_custom_field_name_map,
    build_display_payload,
    extract_keycode_direct,
    extract_reservation_notes,
    first_present,
    normalize_field_name,
    reservation_listing_id_groups,
    sanitize_door_code,
)

_LOGGER = logging.getLogger(__name__)
_GUEST_CACHE_SECONDS = DEFAULT_POLL_MINUTES * 60
_COMPLETED_RESERVATION_RETENTION = timedelta(hours=COMPLETED_RESERVATION_CACHE_HOURS)
_MAX_KEYCODE_CACHE_ITEMS = 512
_MAX_GUEST_CACHE_ITEMS = 256
_MAX_CONCURRENT_GUESTY_REQUESTS = 4
_CUSTOM_FIELD_DEFINITION_CACHE_SECONDS = 60 * 60

type _ReservationObservation = tuple[str, dict[str, Any], bool]


@dataclass(frozen=True, slots=True)
class _ListingResolution:
    """Privacy-safe outcome of routing one reservation projection group."""

    listing_id: str = ""
    reason: str = "unmapped"


async def _async_gather_cancel_on_error[T](
    *coroutines: Coroutine[Any, Any, T],
) -> list[T]:
    """Gather coroutines and cancel every sibling after the first failure."""
    tasks = [asyncio.create_task(coroutine) for coroutine in coroutines]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    """Coerce a persisted option without making a config entry unloadable."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return min(maximum, max(minimum, number))


def _bounded_cache_set(cache: dict[Any, Any], key: Any, value: Any, limit: int) -> None:
    """Insert one cache item while keeping process-lifetime memory bounded."""
    cache[key] = value
    while len(cache) > limit:
        cache.pop(next(iter(cache)))


def _resolve_observation_listing_id(
    observations: list[_ReservationObservation],
    allowed_listing_ids: set[str],
    *,
    current: datetime,
    listings: Mapping[str, Listing],
) -> _ListingResolution:
    """Resolve multiple Guesty projections of one reservation exactly once."""
    for priority in range(4):
        candidates: list[str] = []
        for query_listing_id, raw, _include_keycode in observations:
            groups = reservation_listing_id_groups(
                raw,
                now=current,
                listing=listings.get(query_listing_id),
            )
            for listing_id in groups[priority]:
                if listing_id in allowed_listing_ids and listing_id not in candidates:
                    candidates.append(listing_id)
        if len(candidates) == 1:
            return _ListingResolution(candidates[0], "resolved")
        if candidates:
            # Never copy one ambiguous reservation to several displays.
            return _ListingResolution(reason="ambiguous")

    query_listing_ids = list(
        dict.fromkeys(
            query_listing_id
            for query_listing_id, _raw, _include_keycode in observations
            if query_listing_id in allowed_listing_ids
        )
    )
    if len(query_listing_ids) == 1:
        return _ListingResolution(query_listing_ids[0], "resolved")
    if query_listing_ids:
        return _ListingResolution(reason="ambiguous")
    return _ListingResolution()


def _projection_score(raw: Mapping[str, Any]) -> int:
    """Return a small deterministic completeness score for a search row."""
    required_fields = (
        "status",
        "checkIn",
        "checkOut",
        "checkInDateLocalized",
        "checkOutDateLocalized",
        "stay",
    )
    return sum(bool(raw.get(field)) for field in required_fields) + len(raw)


_SENSITIVE_PROJECTION_ROOTS = {
    "channelMetadata",
    "customField",
    "customFields",
    "fields",
    "guest",
    "guestId",
    "bookerId",
    "notes",
}
_SENSITIVE_PROJECTION_FIELDS = (
    "keycode",
    "keyCode",
    "doorCode",
)
_DOOR_CODE_FIELD_NAMES = {"keycode", "doorcode"}
_GUEST_PROJECTION_FIELDS = ("guest", "guestId", "bookerId")
_CUSTOM_FIELD_PROJECTION_FIELDS = ("customFields", "customField", "fields")
_CURRENT_KEYCODE_PROJECTIONS = "_guesty_current_keycode_projections"
_NOTE_PROJECTION_KEYS = {
    "general": (
        ("other", "general"),
        ("generalNotes", "otherNotes"),
    ),
    "cleaner": (
        ("cleaning", "cleaner"),
        ("cleaningNotes", "notesForCleaner"),
    ),
    "special": (
        ("specialRequests", "special_requests"),
        ("specialRequests",),
    ),
}


def _explicit_note_categories(raw: Mapping[str, Any]) -> set[str]:
    """Return note categories explicitly represented by one projection."""
    notes = raw.get("notes")
    if "notes" in raw and (not isinstance(notes, Mapping) or not notes):
        return set(_NOTE_PROJECTION_KEYS)

    categories: set[str] = set()
    channel_metadata = raw.get("channelMetadata")
    if "channelMetadata" in raw and (
        not isinstance(channel_metadata, Mapping) or not channel_metadata
    ):
        categories.add("special")
    if isinstance(channel_metadata, Mapping) and any(
        key in channel_metadata for key in ("specialRequests", "special_requests")
    ):
        categories.add("special")
    for category, (nested_keys, root_keys) in _NOTE_PROJECTION_KEYS.items():
        if (
            isinstance(notes, Mapping) and any(key in notes for key in nested_keys)
        ) or any(key in raw for key in root_keys):
            categories.add(category)
    return categories


def _cleared_note_categories(raw: Mapping[str, Any]) -> set[str]:
    """Return note categories explicitly cleared by one projection."""
    notes = raw.get("notes")
    if "notes" in raw and (not isinstance(notes, Mapping) or not notes):
        return set(_NOTE_PROJECTION_KEYS)

    category_indexes = {
        category: index for index, category in enumerate(_NOTE_PROJECTION_KEYS)
    }
    cleared: set[str] = set()
    for category, (nested_keys, root_keys) in _NOTE_PROJECTION_KEYS.items():
        index = category_indexes[category]
        if isinstance(notes, Mapping):
            for key in nested_keys:
                if (
                    key in notes
                    and not extract_reservation_notes({"notes": {key: notes[key]}})[
                        index
                    ]
                ):
                    cleared.add(category)
        for key in root_keys:
            if key in raw and not extract_reservation_notes({key: raw[key]})[index]:
                cleared.add(category)

    channel_metadata = raw.get("channelMetadata")
    if "channelMetadata" in raw and (
        not isinstance(channel_metadata, Mapping) or not channel_metadata
    ):
        cleared.add("special")
    elif isinstance(channel_metadata, Mapping):
        for key in ("specialRequests", "special_requests"):
            if (
                key in channel_metadata
                and not extract_reservation_notes(
                    {"channelMetadata": {key: channel_metadata[key]}}
                )[category_indexes["special"]]
            ):
                cleared.add("special")
    return cleared


def _projected_door_code_value(value: Any) -> str:
    """Return one sanitized scalar from a flexible projected value."""
    if isinstance(value, Mapping):
        for key in ("value", "code"):
            if key in value:
                return sanitize_door_code(value[key])
        return ""
    return sanitize_door_code(value)


def _named_keycode_projection_values(value: Any) -> list[str]:
    """Return every directly named keycode value, including explicit clears."""
    projected: list[str] = []
    if isinstance(value, Mapping):
        projected.extend(
            _projected_door_code_value(item)
            for key, item in value.items()
            if normalize_field_name(key) in _DOOR_CODE_FIELD_NAMES
        )
        if _mapping_identifies_keycode_field(value):
            projected.append(_projected_door_code_value(value))
        for item in value.values():
            if isinstance(item, (Mapping, list)):
                projected.extend(_named_keycode_projection_values(item))
    elif isinstance(value, list):
        for item in value:
            projected.extend(_named_keycode_projection_values(item))
    return projected


def _mapping_identifies_keycode_field(value: Mapping[str, Any]) -> bool:
    """Return whether one mapping is itself a named keycode field record."""
    return any(
        normalize_field_name(value.get(key)) in _DOOR_CODE_FIELD_NAMES
        for key in (
            "fieldId",
            "name",
            "fieldName",
            "key",
            "slug",
            "variable",
            "placeholder",
        )
    )


def _explicit_keycode_projection(raw: Mapping[str, Any]) -> tuple[bool, str]:
    """Return whether and how one projection explicitly supplies keycode."""
    projected_values: list[str] = []
    for field_name in _SENSITIVE_PROJECTION_FIELDS:
        if field_name in raw:
            projected_values.append(_projected_door_code_value(raw[field_name]))

    for field_name in _CUSTOM_FIELD_PROJECTION_FIELDS:
        if field_name not in raw:
            continue
        value = raw[field_name]
        if not value or not isinstance(value, (Mapping, list)):
            projected_values.append("")
        else:
            projected_values.extend(_named_keycode_projection_values(value))

    notes = raw.get("notes")
    if "notes" in raw:
        projected_values.extend(_named_keycode_projection_values(notes))
    if not projected_values:
        return False, ""
    # A clear in any alias is safer and more authoritative than a conflicting
    # populated sibling in the same current projection.
    if any(not value for value in projected_values):
        return True, ""
    return True, projected_values[0]


def _defined_keycode_projection(
    raw: Mapping[str, Any], definitions: Any
) -> tuple[bool, str]:
    """Resolve opaque current custom-field IDs without losing empty values."""
    name_by_id = build_custom_field_name_map(definitions)
    if not name_by_id:
        return False, ""

    projected_values: list[str] = []

    def inspect(value: Any) -> None:
        if isinstance(value, Mapping):
            field_id = first_present(value, "fieldId", "_id", "id")
            if name_by_id.get(field_id) in _DOOR_CODE_FIELD_NAMES:
                projected_values.append(_projected_door_code_value(value))
            for key, item in value.items():
                if name_by_id.get(str(key).strip()) in _DOOR_CODE_FIELD_NAMES:
                    projected_values.append(_projected_door_code_value(item))
                if isinstance(item, (Mapping, list)):
                    inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)

    if _CURRENT_KEYCODE_PROJECTIONS in raw:
        inspect(raw[_CURRENT_KEYCODE_PROJECTIONS])
    else:
        for field_name in (*_CUSTOM_FIELD_PROJECTION_FIELDS, "notes"):
            if field_name in raw:
                inspect(raw[field_name])

    if not projected_values:
        return False, ""
    if any(not value for value in projected_values):
        return True, ""
    return True, projected_values[0]


def _has_opaque_custom_field_candidates(raw: Mapping[str, Any]) -> bool:
    """Return whether definition lookup could identify a current keycode."""

    def contains_field_id(value: Any) -> bool:
        if isinstance(value, Mapping):
            if _mapping_identifies_keycode_field(value):
                return False
            if first_present(value, "fieldId", "_id", "id"):
                return True
            return any(contains_field_id(item) for item in value.values())
        if isinstance(value, list):
            return any(contains_field_id(item) for item in value)
        return False

    def custom_container_has_opaque_id(value: Any) -> bool:
        if isinstance(value, list):
            return any(custom_container_has_opaque_id(item) for item in value)
        if not isinstance(value, Mapping):
            return False
        if _mapping_identifies_keycode_field(value):
            return False
        if first_present(value, "fieldId", "_id", "id"):
            return True
        metadata_keys = {
            "fieldId",
            "_id",
            "id",
            "name",
            "fieldName",
            "key",
            "slug",
            "variable",
            "placeholder",
            "value",
            "code",
        }
        for key, item in value.items():
            if normalize_field_name(key) in _DOOR_CODE_FIELD_NAMES:
                continue
            if key in (*_CUSTOM_FIELD_PROJECTION_FIELDS, "results", "data"):
                if custom_container_has_opaque_id(item):
                    return True
                continue
            if key in metadata_keys:
                continue
            if isinstance(item, (Mapping, list)):
                if custom_container_has_opaque_id(item):
                    return True
            else:
                # Mapping-shaped collections can use the opaque field ID as
                # the key instead of a fieldId member.
                return True
        return False

    def source_has_opaque_id(source: Mapping[str, Any]) -> bool:
        return any(
            key in source and custom_container_has_opaque_id(source[key])
            for key in _CUSTOM_FIELD_PROJECTION_FIELDS
        ) or ("notes" in source and contains_field_id(source.get("notes")))

    sources: Any = raw
    if _CURRENT_KEYCODE_PROJECTIONS in raw:
        sources = raw[_CURRENT_KEYCODE_PROJECTIONS]
    if isinstance(sources, Mapping):
        return source_has_opaque_id(sources)
    if isinstance(sources, list):
        return any(
            isinstance(source, Mapping) and source_has_opaque_id(source)
            for source in sources
        )
    return False


def _blocks_keycode_fallback(raw: Mapping[str, Any]) -> bool:
    """Return whether an older projection may not provide a keycode alias."""
    explicit, _value = _explicit_keycode_projection(raw)
    return explicit or any(key in raw for key in _CUSTOM_FIELD_PROJECTION_FIELDS)


def _guest_projection_is_clear(raw: Mapping[str, Any]) -> bool:
    """Return whether one projection explicitly clears guest identity data."""
    if "guest" in raw and (
        not isinstance(raw.get("guest"), Mapping) or not raw.get("guest")
    ):
        return True
    return any(
        key in raw and not first_present(raw, key) for key in ("guestId", "bookerId")
    )


def _apply_sensitive_clears(
    merged: Mapping[str, Any],
    *,
    clear_guest: bool,
    clear_keycode: bool,
    clear_note_categories: set[str],
    clear_all_notes: bool,
) -> dict[str, Any]:
    """Apply privacy clears found in any equally authoritative projection."""
    cleared = dict(merged)
    if clear_guest:
        for key in _GUEST_PROJECTION_FIELDS:
            cleared.pop(key, None)
        cleared["guest"] = {}

    if clear_keycode:
        for key in _SENSITIVE_PROJECTION_FIELDS:
            cleared.pop(key, None)
        for key in _CUSTOM_FIELD_PROJECTION_FIELDS:
            if key in cleared:
                cleared[key] = _strip_keycode_projection(cleared[key])
        if "notes" in cleared:
            cleared["notes"] = _strip_keycode_projection(cleared["notes"])
        # A canonical explicit empty field prevents both later projection fill
        # and the populated-custom-field endpoint from reviving an old code.
        cleared["keycode"] = ""

    if clear_all_notes:
        cleared["notes"] = {}
        clear_note_categories = set(_NOTE_PROJECTION_KEYS)
    elif clear_note_categories:
        notes = cleared.get("notes")
        normalized_notes = dict(notes) if isinstance(notes, Mapping) else {}
        canonical_nested_keys = {
            "general": "other",
            "cleaner": "cleaning",
            "special": "specialRequests",
        }
        for category in clear_note_categories:
            for key in _NOTE_PROJECTION_KEYS[category][0]:
                normalized_notes.pop(key, None)
            normalized_notes[canonical_nested_keys[category]] = ""
        cleared["notes"] = normalized_notes

    for category in clear_note_categories:
        for key in _NOTE_PROJECTION_KEYS[category][1]:
            cleared.pop(key, None)
    if "special" in clear_note_categories:
        channel_metadata = cleared.get("channelMetadata")
        if isinstance(channel_metadata, Mapping):
            sanitized_channel = dict(channel_metadata)
            sanitized_channel.pop("specialRequests", None)
            sanitized_channel.pop("special_requests", None)
            cleared["channelMetadata"] = sanitized_channel
    return cleared


def _privacy_bounded_projection_fallback(
    primary: Mapping[str, Any],
    fallback: Mapping[str, Any],
) -> dict[str, Any]:
    """Remove cross-shape aliases blocked by explicit current data.

    Guesty can project the same value below ``notes``/``guest``/``customFields``
    or through older root aliases. Recursive merging alone cannot recognize
    those aliases, so bound the less-authoritative projection before it fills
    absent root keys.
    """
    bounded = dict(fallback)
    explicit_note_categories = _explicit_note_categories(primary)

    fallback_notes = bounded.get("notes")
    if isinstance(fallback_notes, Mapping) and explicit_note_categories:
        sanitized_notes = dict(fallback_notes)
        for category in explicit_note_categories:
            for key in _NOTE_PROJECTION_KEYS[category][0]:
                sanitized_notes.pop(key, None)
        bounded["notes"] = sanitized_notes
    for category in explicit_note_categories:
        for key in _NOTE_PROJECTION_KEYS[category][1]:
            bounded.pop(key, None)
    if "special" in explicit_note_categories:
        channel_metadata = bounded.get("channelMetadata")
        if isinstance(channel_metadata, Mapping):
            sanitized_channel = dict(channel_metadata)
            sanitized_channel.pop("specialRequests", None)
            sanitized_channel.pop("special_requests", None)
            bounded["channelMetadata"] = sanitized_channel

    explicit_guest_fields = {key for key in _GUEST_PROJECTION_FIELDS if key in primary}
    if explicit_guest_fields:
        for key in _GUEST_PROJECTION_FIELDS:
            if key not in explicit_guest_fields:
                bounded.pop(key, None)

    if _blocks_keycode_fallback(primary):
        for key in _SENSITIVE_PROJECTION_FIELDS:
            bounded.pop(key, None)
        for key in _CUSTOM_FIELD_PROJECTION_FIELDS:
            if key in bounded:
                bounded[key] = _strip_keycode_projection(bounded[key])
        if "notes" in bounded:
            bounded["notes"] = _strip_keycode_projection(bounded["notes"])

    return bounded


def _strip_keycode_projection(value: Any) -> Any:
    """Remove every keycode path understood by ``extract_keycode_direct``."""
    if isinstance(value, Mapping):
        if _mapping_identifies_keycode_field(value):
            return {}
        return {
            key: _strip_keycode_projection(item)
            for key, item in value.items()
            if normalize_field_name(key) not in _DOOR_CODE_FIELD_NAMES
        }
    if isinstance(value, list):
        stripped = [_strip_keycode_projection(item) for item in value]
        return [item for item in stripped if item != {}]
    return value


def _projection_identity(value: Any) -> str:
    """Return a stable identity for one populated projection object."""
    if isinstance(value, Mapping):
        return first_present(value, "fieldId", "_id", "id", "listingId", "name")
    return str(value).strip() if value is not None else ""


def _stay_projection_identities(segment: Mapping[str, Any]) -> set[str]:
    """Return all represented identities from one stay projection segment."""
    return {
        identity
        for key in ("unitId", "listingId", "unitTypeId", "parentListingId")
        if (identity := _projection_identity(segment.get(key)))
    }


def _merge_projection_lists(
    primary: list[Any], fallback: list[Any], path: tuple[str, ...]
) -> list[Any]:
    """Merge list-shaped projections only when their identity is unambiguous."""
    root = path[0] if path else ""
    if root == "stay" and all(isinstance(item, Mapping) for item in primary):
        result = list(primary)
        used_fallback: set[int] = set()
        fallback_segments = [item for item in fallback if isinstance(item, Mapping)]
        for index, primary_segment in enumerate(primary):
            primary_ids = _stay_projection_identities(primary_segment)
            matching_indexes = [
                fallback_index
                for fallback_index, fallback_segment in enumerate(fallback_segments)
                if fallback_index not in used_fallback
                and primary_ids & _stay_projection_identities(fallback_segment)
            ]
            if not matching_indexes and len(primary) == len(fallback_segments):
                matching_indexes = [index]
            if len(matching_indexes) != 1:
                continue
            fallback_index = matching_indexes[0]
            used_fallback.add(fallback_index)
            result[index] = _merge_projection_value(
                primary_segment,
                fallback_segments[fallback_index],
                (*path, str(index)),
            )
        result.extend(
            segment
            for index, segment in enumerate(fallback_segments)
            if index not in used_fallback
        )
        return result

    if root in _CUSTOM_FIELD_PROJECTION_FIELDS and all(
        isinstance(item, Mapping) for item in primary
    ):
        result = list(primary)
        index_by_identity = {
            identity: index
            for index, item in enumerate(primary)
            if (identity := _projection_identity(item))
        }
        for fallback_item in fallback:
            if not isinstance(fallback_item, Mapping):
                continue
            identity = _projection_identity(fallback_item)
            if identity and identity in index_by_identity:
                index = index_by_identity[identity]
                result[index] = _merge_projection_value(
                    result[index],
                    fallback_item,
                    (*path, identity),
                )
            elif identity:
                index_by_identity[identity] = len(result)
                result.append(fallback_item)
        return result

    if not primary:
        return [] if root in _SENSITIVE_PROJECTION_ROOTS else list(fallback)

    return list(primary)


def _merge_projection_value(
    primary: Any,
    fallback: Any,
    path: tuple[str, ...],
) -> Any:
    """Fill a projection recursively without reviving explicitly cleared PII."""
    root = path[0] if path else ""
    if isinstance(primary, Mapping) and isinstance(fallback, Mapping):
        if not primary and root in _SENSITIVE_PROJECTION_ROOTS:
            return dict(primary)
        merged = dict(primary)
        for key, value in fallback.items():
            if key not in merged:
                merged[key] = value
            else:
                merged[key] = _merge_projection_value(merged[key], value, (*path, key))
        return merged
    if isinstance(primary, list) and isinstance(fallback, list):
        return _merge_projection_lists(primary, fallback, path)

    explicitly_sensitive = root in _SENSITIVE_PROJECTION_ROOTS or (
        path and path[-1] in _SENSITIVE_PROJECTION_FIELDS
    )
    if not explicitly_sensitive and primary in (None, "", []):
        return fallback
    return primary


def _merge_reservation_observations(
    observations: list[_ReservationObservation],
) -> tuple[dict[str, Any], bool]:
    """Merge duplicate projections without restoring explicitly cleared data.

    A current/recent row is the primary projection because it is also eligible
    for access-code enrichment. Other projections fill only fields that are
    absent from that primary row. An explicitly supplied empty notes or custom
    fields collection remains authoritative and is never replaced by an older
    projection.
    """
    ordered_observations = sorted(
        observations,
        key=lambda observation: (
            not observation[2],
            -_projection_score(observation[1]),
            observation[0],
        ),
    )
    current_observations = [
        observation for observation in ordered_observations if observation[2]
    ]
    upcoming_observations = [
        observation for observation in ordered_observations if not observation[2]
    ]
    authoritative_observations = current_observations or upcoming_observations[:1]
    _query_listing_id, primary, _include_keycode = authoritative_observations[0]
    merged = dict(primary)
    for _query_listing_id, fallback, _include_keycode in authoritative_observations[1:]:
        bounded_fallback = _privacy_bounded_projection_fallback(merged, fallback)
        for key, value in bounded_fallback.items():
            if key not in merged:
                merged[key] = value
            else:
                merged[key] = _merge_projection_value(merged[key], value, (key,))

    if current_observations:
        merged[_CURRENT_KEYCODE_PROJECTIONS] = [
            {
                key: raw[key]
                for key in (
                    *_SENSITIVE_PROJECTION_FIELDS,
                    *_CUSTOM_FIELD_PROJECTION_FIELDS,
                    "notes",
                )
                if key in raw
            }
            for _query_listing_id, raw, _include_keycode in current_observations
        ]
        clear_all_notes = any(
            "notes" in raw
            and (not isinstance(raw.get("notes"), Mapping) or not raw.get("notes"))
            for _query_listing_id, raw, _include_keycode in current_observations
        )
        clear_note_categories = {
            category
            for _query_listing_id, raw, _include_keycode in current_observations
            for category in _cleared_note_categories(raw)
        }
        clear_keycode = any(
            explicit and not value
            for _query_listing_id, raw, _include_keycode in current_observations
            for explicit, value in (_explicit_keycode_projection(raw),)
        )
        merged = _apply_sensitive_clears(
            merged,
            clear_guest=any(
                _guest_projection_is_clear(raw)
                for _query_listing_id, raw, _include_keycode in current_observations
            ),
            clear_keycode=clear_keycode,
            clear_note_categories=clear_note_categories,
            clear_all_notes=clear_all_notes,
        )

    fallback_observations = (
        upcoming_observations if current_observations else upcoming_observations[1:]
    )
    for _query_listing_id, fallback, _include_keycode in fallback_observations:
        bounded_fallback = _privacy_bounded_projection_fallback(merged, fallback)
        for key, value in bounded_fallback.items():
            if key not in merged:
                merged[key] = value
            else:
                merged[key] = _merge_projection_value(merged[key], value, (key,))
    return merged, any(observation[2] for observation in observations)


@dataclass(frozen=True, slots=True)
class GuestyTerminalData:
    """One complete coordinator snapshot."""

    listings: dict[str, Listing]
    reservations: tuple[Reservation, ...]
    payloads: dict[str, DisplayPayload]
    stale_listing_ids: frozenset[str] = frozenset()


class GuestyTerminalCoordinator(DataUpdateCoordinator[GuestyTerminalData]):
    """Coordinate Guesty calls once for all configured displays."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry[Any],
        client: GuestyClient,
    ) -> None:
        poll_minutes = _bounded_int(
            entry.options.get(CONF_POLL_MINUTES),
            DEFAULT_POLL_MINUTES,
            2,
            MAX_POLL_MINUTES,
        )
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=poll_minutes),
            always_update=False,
        )
        self.entry = entry
        self.client = client
        self._keycode_cache: dict[tuple[str, str], str] = {}
        self._custom_field_definitions: dict[str, tuple[float, Any]] = {}
        self._guest_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._listing_detail_cache: dict[str, tuple[float, Listing]] = {}
        self._reservation_snapshot_cache: dict[str, tuple[Reservation, ...]] = {}
        self._account_id: str | None = None
        self._blocked_endpoints: set[str] = set()

    def block_endpoints(self, endpoints: set[str]) -> None:
        """Prevent a physical display from being driven by two Guesty entries."""
        self._blocked_endpoints = set(endpoints)

    def mapping_options(self) -> list[MappingOptions]:
        """Return all valid stored display mappings."""
        raw_mappings = self.entry.options.get(CONF_MAPPINGS, {})
        if not isinstance(raw_mappings, dict):
            return []
        mappings: list[MappingOptions] = []
        for endpoint, raw in raw_mappings.items():
            if not isinstance(raw, dict):
                continue
            if endpoint in getattr(self, "_blocked_endpoints", set()):
                continue
            mapping = MappingOptions.from_dict(endpoint, raw)
            if mapping.endpoint_entity and mapping.listing_id:
                mappings.append(mapping)
        return mappings

    def invalidate_guest_data_caches(self) -> None:
        """Discard API response caches before an explicit device sync."""
        self._keycode_cache.clear()
        self._guest_cache.clear()
        self._custom_field_definitions.clear()
        self._listing_detail_cache.clear()

    def _weather_values(self, mapping: MappingOptions) -> tuple[str, str]:
        """Return a compact weather condition and rounded outdoor temperature."""
        if not mapping.weather_entity:
            return "", ""
        state = self.hass.states.get(mapping.weather_entity)
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return "", ""

        condition = str(state.state).strip().lower().replace("_", "-")
        attributes = getattr(state, "attributes", {})
        if not isinstance(attributes, Mapping):
            return condition, ""
        temperature = attributes.get("temperature")
        if temperature is None:
            return condition, ""
        try:
            numeric_temperature = float(temperature)
        except (TypeError, ValueError):
            return condition, ""
        if not math.isfinite(numeric_temperature):
            return condition, ""

        unit = str(attributes.get("temperature_unit") or "").strip()
        if not unit:
            units = getattr(getattr(self.hass, "config", None), "units", None)
            unit = str(getattr(units, "temperature_unit", "")).strip()
        temperature_label = f"{numeric_temperature:.0f}"
        if unit:
            temperature_label = f"{temperature_label} {unit}"
        return condition, temperature_label

    def payload_with_current_weather(
        self, endpoint_entity: str, payload: DisplayPayload
    ) -> DisplayPayload:
        """Overlay a cached welcome payload with the live weather state.

        Guesty polling and Home Assistant weather startup are independent. A
        coordinator refresh can therefore capture ``unknown`` shortly before
        the weather entity becomes available. Read the local entity again at
        send time, while retaining the last valid snapshot during a temporary
        outage so a redraw never removes an otherwise valid weather widget.
        """
        if payload.mode not in WEATHER_DISPLAY_MODES:
            return payload
        mapping = next(
            (
                item
                for item in self.mapping_options()
                if item.endpoint_entity == endpoint_entity
            ),
            None,
        )
        if mapping is None or not mapping.weather_entity:
            return payload

        condition, temperature = self._weather_values(mapping)
        if not condition and not temperature:
            return payload
        if (
            condition == payload.weather_condition
            and temperature == payload.weather_temperature
        ):
            return payload
        return replace(
            payload,
            weather_condition=condition,
            weather_temperature=temperature,
        )

    async def _async_custom_field_definitions(
        self, raw: Mapping[str, Any]
    ) -> tuple[Any, bool]:
        """Return usable account definitions and whether lookup was reliable."""
        account_id = first_present(raw, "accountId") or self._account_id or ""
        if not account_id:
            try:
                account = await self.client.async_get_current_account()
            except (GuestyAuthenticationError, GuestyRateLimitError):
                raise
            except GuestyError as err:
                _LOGGER.debug("Could not load current Guesty account: %s", err)
                return [], False
            account_id = first_present(account, "id", "_id")
            self._account_id = account_id or None
        if not account_id:
            return [], False

        cached = self._custom_field_definitions.get(account_id)
        if (
            cached is not None
            and time.monotonic() - cached[0] < _CUSTOM_FIELD_DEFINITION_CACHE_SECONDS
        ):
            return cached[1], True
        try:
            definitions = await self.client.async_get_account_custom_fields(account_id)
        except (GuestyAuthenticationError, GuestyRateLimitError):
            raise
        except GuestyError as err:
            _LOGGER.debug("Could not load Guesty custom-field definitions: %s", err)
            # An expired definition set cannot prove that a newly projected
            # opaque field is unrelated to keycode. Fail closed until Guesty
            # confirms the current definitions.
            return [], False

        self._custom_field_definitions[account_id] = (
            time.monotonic(),
            definitions,
        )
        return definitions, True

    async def _async_keycode(self, raw: dict[str, Any]) -> str:
        reservation_id = first_present(raw, "reservationId", "_id", "id")
        channel_metadata = raw.get("channelMetadata")
        if not isinstance(channel_metadata, dict):
            channel_metadata = {}
        # Only cache against a Guesty change marker. When search omits one,
        # querying the custom-field endpoint again is safer than retaining an
        # access code indefinitely after it was changed or removed.
        version = first_present(raw, "lastUpdatedAt") or first_present(
            channel_metadata, "updatedAt"
        )
        cache_key = (reservation_id, version) if reservation_id and version else None

        def authoritative(value: str) -> str:
            if cache_key is None:
                return value
            if value:
                _bounded_cache_set(
                    self._keycode_cache,
                    cache_key,
                    value,
                    _MAX_KEYCODE_CACHE_ITEMS,
                )
            else:
                self._keycode_cache.pop(cache_key, None)
            return value

        explicit_keycode, explicit_value = _explicit_keycode_projection(raw)
        if explicit_keycode and not explicit_value:
            return authoritative("")
        has_opaque_current_fields = _has_opaque_custom_field_candidates(raw)
        definitions: Any = []
        definitions_loaded = False
        if has_opaque_current_fields and reservation_id:
            (
                definitions,
                definitions_usable,
            ) = await self._async_custom_field_definitions(raw)
            definitions_loaded = True
            if not definitions_usable:
                # Without definitions an opaque current field might be an
                # explicit keycode clear. Fail closed instead of trusting an
                # older populated endpoint or cache entry.
                return authoritative("")
            defined_keycode, defined_value = _defined_keycode_projection(
                raw, definitions
            )
            if defined_keycode:
                if not defined_value:
                    return authoritative("")
                if explicit_keycode and defined_value != explicit_value:
                    return authoritative("")
                return authoritative(defined_value)

        if explicit_keycode:
            # Every directly identified projection is authoritative even when
            # empty; do not revive a code through another shape or endpoint.
            return authoritative(explicit_value)
        direct = extract_keycode_direct(raw)
        if direct:
            return authoritative(direct)
        if not reservation_id:
            return ""

        if (
            not has_opaque_current_fields
            and cache_key is not None
            and cache_key in self._keycode_cache
        ):
            return self._keycode_cache[cache_key]

        try:
            populated = await self.client.async_get_reservation_custom_fields(
                reservation_id
            )
        except (GuestyAuthenticationError, GuestyRateLimitError):
            raise
        except GuestyError:
            _LOGGER.debug("Could not load optional Guesty reservation fields")
            return ""

        populated_mapping = populated if isinstance(populated, Mapping) else {}
        populated_explicit, populated_keycode = _explicit_keycode_projection(
            populated_mapping
        )
        populated_has_opaque = _has_opaque_custom_field_candidates(populated_mapping)
        if populated_has_opaque:
            if not definitions_loaded:
                (
                    definitions,
                    definitions_usable,
                ) = await self._async_custom_field_definitions(raw)
                definitions_loaded = True
                if not definitions_usable:
                    return authoritative("")
            defined_keycode, defined_value = _defined_keycode_projection(
                populated_mapping, definitions
            )
            if defined_keycode:
                if not defined_value:
                    return authoritative("")
                if populated_explicit and populated_keycode != defined_value:
                    return authoritative("")
                return authoritative(defined_value)
        if populated_explicit:
            return authoritative(populated_keycode)
        direct = extract_keycode_direct(populated)
        if direct:
            return authoritative(direct)

        if not definitions_loaded:
            (
                definitions,
                definitions_usable,
            ) = await self._async_custom_field_definitions(raw)
            if not definitions_usable:
                return authoritative("")
        defined_keycode, projected_keycode = _defined_keycode_projection(
            populated_mapping, definitions
        )
        return authoritative(projected_keycode if defined_keycode else "")

    async def _async_guest(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Return embedded or separately loaded guest name data."""
        guest = raw.get("guest")
        if isinstance(guest, dict) and guest:
            return guest
        if "guest" in raw:
            # An explicitly empty current guest object is authoritative across
            # the legacy guestId/bookerId aliases.
            return {}
        guest_id = ""
        for field_name in ("guestId", "bookerId"):
            if field_name in raw:
                # Presence is authoritative across aliases. In particular, an
                # explicit empty guestId must not fall through to bookerId.
                guest_id = first_present(raw, field_name)
                break
        if not guest_id:
            return {}
        cached = self._guest_cache.get(guest_id)
        if cached is not None and time.monotonic() - cached[0] < _GUEST_CACHE_SECONDS:
            return cached[1]
        try:
            guest = await self.client.async_get_guest(guest_id)
        except (GuestyAuthenticationError, GuestyRateLimitError):
            raise
        except GuestyError:
            _LOGGER.debug("Could not load optional Guesty guest details")
            return cached[1] if cached is not None else {}
        if guest:
            _bounded_cache_set(
                self._guest_cache,
                guest_id,
                (time.monotonic(), guest),
                _MAX_GUEST_CACHE_ITEMS,
            )
        else:
            self._guest_cache.pop(guest_id, None)
        return guest

    async def _async_normalize_reservation(
        self,
        raw: dict[str, Any],
        listing: Listing,
        *,
        include_keycode: bool,
        resolved_listing_id: str,
        current: datetime,
    ) -> Reservation | None:
        """Normalize one booking with the required optional enrichments."""
        guest = await self._async_guest(raw)
        if guest and not isinstance(raw.get("guest"), dict):
            raw = {**raw, "guest": guest}
        keycode = await self._async_keycode(raw) if include_keycode else None
        reservation = Reservation.from_api(
            raw,
            listing,
            keycode=keycode,
            resolved_listing_id=resolved_listing_id,
            now=current,
        )
        if (
            reservation is None
            or not reservation.reservation_id
            or reservation.status not in ACTIVE_RESERVATION_STATUSES
        ):
            return None
        return reservation

    def _reconcile_reservation_snapshots(
        self,
        fresh: dict[str, tuple[Reservation, ...]],
        mapped_listing_ids: set[str],
        current: datetime,
        *,
        refreshed_listing_ids: set[str] | None = None,
    ) -> None:
        """Replace only changed per-listing snapshots in the local RAM cache."""
        cache = self._reservation_snapshot_cache
        for listing_id in set(cache) - mapped_listing_ids:
            cache.pop(listing_id, None)
        reconciled_listing_ids = (
            mapped_listing_ids
            if refreshed_listing_ids is None
            else refreshed_listing_ids & mapped_listing_ids
        )
        # A time-dependent multi-stay reservation can move from listing A to B
        # while keeping the same reservation ID. Fresh ownership anywhere in
        # this successful refresh invalidates completed-retention copies on
        # every other reconciled listing; otherwise credentials and guest data
        # could remain visible on both displays during the transition.
        globally_fresh_ids = {
            reservation.reservation_id
            for listing_id in reconciled_listing_ids
            for reservation in fresh.get(listing_id, ())
        }
        for listing_id in reconciled_listing_ids:
            current_snapshot = tuple(
                reservation
                for reservation in fresh.get(listing_id, ())
                if reservation.check_in > current
                or current < reservation.check_out + _COMPLETED_RESERVATION_RETENTION
            )
            retained_completed = tuple(
                reservation
                for reservation in cache.get(listing_id, ())
                if reservation.reservation_id not in globally_fresh_ids
                and reservation.check_out <= current
                and current < reservation.check_out + _COMPLETED_RESERVATION_RETENTION
            )
            snapshot = tuple(
                sorted(
                    (*current_snapshot, *retained_completed),
                    key=lambda reservation: (
                        reservation.check_in,
                        reservation.reservation_id,
                    ),
                )
            )
            if cache.get(listing_id) != snapshot:
                cache[listing_id] = snapshot

    def _prune_expired_reservation_snapshots(self, current: datetime) -> None:
        """Expire completed bookings even when the next Guesty request fails."""
        cache = self._reservation_snapshot_cache
        for listing_id, snapshot in tuple(cache.items()):
            retained = tuple(
                reservation
                for reservation in snapshot
                if reservation.check_in > current
                or current < reservation.check_out + _COMPLETED_RESERVATION_RETENTION
            )
            if retained != snapshot:
                cache[listing_id] = retained

    async def _async_update_data(self) -> GuestyTerminalData:
        try:
            current = datetime.now(UTC)
            self._prune_expired_reservation_snapshots(current)
            raw_listings = await self.client.async_get_listings()
            listings = {
                listing.listing_id: listing
                for raw in raw_listings
                if (listing := Listing.from_api(raw)).listing_id
            }

            mappings = self.mapping_options()
            mapped_listing_ids = sorted(
                {mapping.listing_id for mapping in mappings if mapping.listing_id}
            )
            mapped_listing_id_set = set(mapped_listing_ids)
            self._listing_detail_cache = {
                key: value
                for key, value in self._listing_detail_cache.items()
                if key in mapped_listing_id_set
            }
            snapshot_cache = getattr(self, "_reservation_snapshot_cache", None)
            if snapshot_cache is None:
                snapshot_cache = self._reservation_snapshot_cache = {}

            # The listing collection may omit guest-facing detail fields. Load
            # those mapped listings on every poll as well, then reconcile the
            # result against the last successful record. This makes changed or
            # explicitly cleared instructions and Wi-Fi data visible within the
            # same five-minute window as reservation changes.
            detail_cache = getattr(self, "_listing_detail_cache", None)
            if detail_cache is None:
                detail_cache = self._listing_detail_cache = {}
            api_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_GUESTY_REQUESTS)

            async def _listing_details(
                listing_id: str,
            ) -> tuple[str, Listing | None, bool]:
                listing = listings.get(listing_id)
                cached = detail_cache.get(listing_id)
                try:
                    async with api_semaphore:
                        full = await self.client.async_get_listing(listing_id)
                except (GuestyAuthenticationError, GuestyRateLimitError):
                    raise
                except GuestyError as err:
                    _LOGGER.warning(
                        "Could not load optional details for Guesty listing %s: %s",
                        listing_id,
                        err,
                    )
                    # The collection response requested every display-relevant
                    # field and is fresh for this refresh. Prefer that safe
                    # projection over cached details: otherwise an explicitly
                    # cleared Wi-Fi password could be reissued indefinitely
                    # while the detail endpoint is unavailable.
                    return listing_id, listing, False
                if full and (full_listing := Listing.from_api(full)).listing_id:
                    if cached is not None and cached[1] == full_listing:
                        return listing_id, cached[1], False
                    return listing_id, full_listing, True
                elif listing is not None:
                    # Treat an empty/invalid detail projection like a failed
                    # detail lookup and keep the fresh collection row. Cached
                    # Wi-Fi credentials must never be revived by a malformed
                    # HTTP-200 body.
                    return listing_id, listing, True
                return listing_id, None, False

            detail_results = await _async_gather_cancel_on_error(
                *(_listing_details(listing_id) for listing_id in mapped_listing_ids)
            )
            for listing_id, resolved_listing, update_cache in detail_results:
                if resolved_listing is None:
                    continue
                listings[listing_id] = resolved_listing
                if update_cache:
                    detail_cache[listing_id] = (time.monotonic(), resolved_listing)

            available_listing_ids = [
                listing_id
                for listing_id in mapped_listing_ids
                if listing_id in listings
            ]
            raw_by_listing: dict[str, list[tuple[dict[str, Any], bool]]] = {
                listing_id: [] for listing_id in mapped_listing_ids
            }
            routable_listing_ids = set(available_listing_ids)

            # Current/recent searches are deliberately scoped to one mapped
            # listing at a time. Guesty can match a multi-unit filter through
            # the configured unit type while projecting only the assigned
            # concrete unit in the result. The query context then preserves
            # ownership even after Home Assistant restarts.
            async def _account_current_reservations() -> tuple[
                str, list[dict[str, Any]] | None
            ]:
                async with api_semaphore:
                    return (
                        "",
                        await self.client.async_get_current_reservations(as_of=current),
                    )

            async def _current_reservations(
                listing_id: str,
            ) -> tuple[str, list[dict[str, Any]] | None]:
                try:
                    async with api_semaphore:
                        reservations = await self.client.async_get_reservations(
                            [listing_id], as_of=current
                        )
                except (GuestyAuthenticationError, GuestyRateLimitError):
                    raise
                except GuestyError as err:
                    _LOGGER.warning(
                        "Could not load current Guesty reservations for listing %s: %s",
                        listing_id,
                        err,
                    )
                    return listing_id, None
                return listing_id, reservations

            account_current_rows: list[dict[str, Any]] = []
            current_results: list[tuple[str, list[dict[str, Any]] | None]] = []
            if available_listing_ids:
                account_and_listing_current = await _async_gather_cancel_on_error(
                    _account_current_reservations(),
                    *(
                        _current_reservations(listing_id)
                        for listing_id in available_listing_ids
                    ),
                )
                account_current_rows = account_and_listing_current[0][1] or []
                current_results = account_and_listing_current[1:]

            # Fetch an authoritative, ordered future snapshot on every normal
            # poll. There is deliberately no query TTL here: additions and
            # future cancellations are detected within five minutes. The
            # reconciliation layer separately retains completed stays for
            # twelve hours. The short collection above remains responsible for
            # a current or just-ended stay and its access code.
            async def _upcoming_reservations(
                listing_id: str,
            ) -> tuple[str, list[dict[str, Any]] | None]:
                try:
                    async with api_semaphore:
                        upcoming = await self.client.async_get_upcoming_reservations(
                            listing_id,
                            limit=UPCOMING_RESERVATIONS_PER_LISTING,
                            as_of=current,
                        )
                except (GuestyAuthenticationError, GuestyRateLimitError):
                    raise
                except GuestyError as err:
                    _LOGGER.warning(
                        "Could not load upcoming Guesty reservations for listing "
                        "%s: %s",
                        listing_id,
                        err,
                    )
                    return listing_id, None
                return listing_id, upcoming

            upcoming_results = await _async_gather_cancel_on_error(
                *(
                    _upcoming_reservations(listing_id)
                    for listing_id in available_listing_ids
                )
            )
            current_by_listing = dict(current_results)
            upcoming_by_listing = dict(upcoming_results)
            refreshed_listing_ids = {
                listing_id
                for listing_id in available_listing_ids
                if current_by_listing.get(listing_id) is not None
                and upcoming_by_listing.get(listing_id) is not None
            }
            observations_by_reservation: dict[str, list[_ReservationObservation]] = {}
            for raw in account_current_rows:
                reservation_id = first_present(raw, "reservationId", "_id", "id")
                if reservation_id:
                    observations_by_reservation.setdefault(reservation_id, []).append(
                        ("", raw, True)
                    )
            for include_keycode, rows_by_listing in (
                (True, current_by_listing),
                (False, upcoming_by_listing),
            ):
                for query_listing_id in sorted(refreshed_listing_ids):
                    rows = rows_by_listing[query_listing_id]
                    assert rows is not None
                    for raw in rows:
                        reservation_id = first_present(
                            raw, "reservationId", "_id", "id"
                        )
                        if not reservation_id:
                            continue
                        observations_by_reservation.setdefault(
                            reservation_id, []
                        ).append((query_listing_id, raw, include_keycode))

            # A successful filtered search can still omit a running stay after
            # Guesty assigns or relocates a concrete unit. Before interpreting
            # that omission as removal, verify only already-known in-house IDs
            # through the authoritative by-ID endpoint. Future rows deliberately
            # do not use this fallback: their absence from the upcoming snapshot
            # remains an immediate cancellation/removal signal.
            cached_active_contexts: dict[str, list[str]] = {}
            for cached_listing_id, cached_reservations in snapshot_cache.items():
                if cached_listing_id not in refreshed_listing_ids:
                    continue
                for reservation in cached_reservations:
                    if (
                        reservation.status in ACTIVE_RESERVATION_STATUSES
                        and reservation.check_in <= current < reservation.check_out
                    ):
                        cached_active_contexts.setdefault(
                            reservation.reservation_id, []
                        ).append(cached_listing_id)

            def _active_observation_is_complete(reservation_id: str) -> bool:
                observations = observations_by_reservation.get(reservation_id)
                if not observations:
                    return False
                resolution = _resolve_observation_listing_id(
                    observations,
                    routable_listing_ids,
                    current=current,
                    listings=listings,
                )
                resolved_listing_id = resolution.listing_id
                listing = listings.get(resolved_listing_id)
                if not resolved_listing_id or listing is None:
                    return False
                merged, _include_keycode = _merge_reservation_observations(observations)
                status = first_present(merged, "status").lower()
                if status not in ACTIVE_RESERVATION_STATUSES:
                    return bool(status)
                candidate = Reservation.from_api(
                    merged,
                    listing,
                    resolved_listing_id=resolved_listing_id,
                    now=current,
                )
                return (
                    candidate is not None and candidate.reservation_id == reservation_id
                )

            verification_ids = [
                reservation_id
                for reservation_id in cached_active_contexts
                if not _active_observation_is_complete(reservation_id)
            ]
            if verification_ids:
                try:
                    async with api_semaphore:
                        verified_rows = await self.client.async_get_reservations_by_ids(
                            verification_ids
                        )
                except (GuestyAuthenticationError, GuestyRateLimitError):
                    raise
                except GuestyError as err:
                    _LOGGER.warning(
                        "Could not verify %d active Guesty reservation(s): %s",
                        len(verification_ids),
                        err,
                    )
                    protected_listing_ids = {
                        listing_id
                        for reservation_id in verification_ids
                        for listing_id in cached_active_contexts[reservation_id]
                    }
                    refreshed_listing_ids -= protected_listing_ids
                    for reservation_id in verification_ids:
                        observations_by_reservation.pop(reservation_id, None)
                    verified_rows = []
                verified_by_id = {
                    reservation_id: raw
                    for raw in verified_rows
                    if (
                        reservation_id := first_present(
                            raw, "reservationId", "_id", "id"
                        )
                    )
                }
                for reservation_id in verification_ids:
                    if any(
                        cached_listing_id not in refreshed_listing_ids
                        for cached_listing_id in cached_active_contexts[reservation_id]
                    ):
                        continue
                    verified_raw = verified_by_id.get(reservation_id)
                    if verified_raw is None:
                        observations_by_reservation.pop(reservation_id, None)
                        continue
                    # A by-ID response has no listing-filter query context.
                    # Never turn old cache ownership into a routing fallback;
                    # the verified row itself must represent a mapped identity.
                    observations_by_reservation[reservation_id] = [
                        ("", verified_raw, True)
                    ]

                    verified_resolution = _resolve_observation_listing_id(
                        observations_by_reservation[reservation_id],
                        routable_listing_ids,
                        current=current,
                        listings=listings,
                    )
                    resolved_verified_listing_id = verified_resolution.listing_id
                    if (
                        not resolved_verified_listing_id
                        or resolved_verified_listing_id not in refreshed_listing_ids
                    ):
                        refreshed_listing_ids -= set(
                            cached_active_contexts[reservation_id]
                        )
                        observations_by_reservation.pop(reservation_id, None)

            if available_listing_ids and not refreshed_listing_ids:
                # Preserve DataUpdateCoordinator's previous complete data and
                # failure diagnostics when no mapped listing produced an
                # authoritative snapshot. Partial success is handled below on
                # a per-listing basis without renewing failed display leases.
                raise GuestyError("Could not refresh any mapped Guesty listing")

            ambiguous_reservations = 0
            unmapped_reservations = 0
            unverified_reservations = 0
            for observations in observations_by_reservation.values():
                resolution = _resolve_observation_listing_id(
                    observations,
                    routable_listing_ids,
                    current=current,
                    listings=listings,
                )
                listing_id = resolution.listing_id
                if not listing_id:
                    if resolution.reason == "ambiguous":
                        ambiguous_reservations += 1
                    else:
                        unmapped_reservations += 1
                    continue
                if listing_id not in refreshed_listing_ids:
                    unverified_reservations += 1
                    continue
                # Prefer the current/recent projection because that path also
                # resolves the access code. A future projection remains a
                # complete fallback for the empty-room page.
                raw, include_keycode = _merge_reservation_observations(observations)
                raw_by_listing[listing_id].append((raw, include_keycode))
            if ambiguous_reservations:
                _LOGGER.warning(
                    "Skipped %d Guesty reservation(s) with ambiguous listing "
                    "associations",
                    ambiguous_reservations,
                )
            if unmapped_reservations:
                _LOGGER.debug(
                    "Skipped %d Guesty reservation(s) outside configured listings",
                    unmapped_reservations,
                )
            if unverified_reservations:
                _LOGGER.debug(
                    "Skipped %d Guesty reservation(s) for unverified listings",
                    unverified_reservations,
                )

            async def _normalized_listing(
                listing_id: str,
            ) -> tuple[str, tuple[Reservation, ...] | None]:
                listing = listings.get(listing_id)
                if listing is None:
                    return listing_id, ()
                normalized: list[Reservation] = []
                async with api_semaphore:
                    for raw, include_keycode in raw_by_listing[listing_id]:
                        status = first_present(raw, "status").lower()
                        if not status:
                            _LOGGER.warning(
                                "Guesty returned an incomplete reservation "
                                "projection for listing %s",
                                listing_id,
                            )
                            return listing_id, None
                        if status not in ACTIVE_RESERVATION_STATUSES:
                            continue
                        reservation = await self._async_normalize_reservation(
                            raw,
                            listing,
                            include_keycode=include_keycode,
                            resolved_listing_id=listing_id,
                            current=current,
                        )
                        if reservation is None:
                            _LOGGER.warning(
                                "Guesty returned an incomplete reservation "
                                "projection for listing %s",
                                listing_id,
                            )
                            return listing_id, None
                        normalized.append(reservation)
                normalized.sort(
                    key=lambda reservation: (
                        reservation.check_in,
                        reservation.reservation_id,
                    )
                )
                current_or_recent = [
                    reservation
                    for reservation in normalized
                    if reservation.check_in <= current
                ]
                upcoming = [
                    reservation
                    for reservation in normalized
                    if reservation.check_in > current
                ][:UPCOMING_RESERVATIONS_PER_LISTING]
                return listing_id, tuple(current_or_recent + upcoming)

            normalized_results = await _async_gather_cancel_on_error(
                *(
                    _normalized_listing(listing_id)
                    for listing_id in sorted(refreshed_listing_ids)
                )
            )
            invalid_projection_listing_ids = {
                listing_id
                for listing_id, snapshot in normalized_results
                if snapshot is None
            }
            refreshed_listing_ids -= invalid_projection_listing_ids
            fresh_snapshots = {
                listing_id: snapshot
                for listing_id, snapshot in normalized_results
                if snapshot is not None
            }
            if available_listing_ids and not refreshed_listing_ids:
                raise GuestyError("Could not refresh any mapped Guesty listing")

            self._reconcile_reservation_snapshots(
                fresh_snapshots,
                mapped_listing_id_set,
                current,
                refreshed_listing_ids=refreshed_listing_ids,
            )
            reservations = [
                reservation
                for listing_id in mapped_listing_ids
                for reservation in snapshot_cache.get(listing_id, ())
            ]

            active_reservation_ids = {
                reservation.reservation_id for reservation in reservations
            }
            self._keycode_cache = {
                key: value
                for key, value in self._keycode_cache.items()
                if key[0] in active_reservation_ids
            }

            payloads: dict[str, DisplayPayload] = {}
            for mapping in mappings:
                mapped_listing = listings.get(mapping.listing_id)
                if (
                    mapped_listing is None
                    or mapping.listing_id not in refreshed_listing_ids
                ):
                    # Keep the last successful reservation snapshot in process
                    # memory, but do not turn a partial Guesty failure into a
                    # new display lease. An awake display can then expire and
                    # clear stale sensitive content locally; a newly started
                    # Home Assistant instance also avoids sending false idle
                    # content for an unverified listing.
                    continue
                weather_condition, weather_temperature = self._weather_values(mapping)
                payloads[mapping.endpoint_entity] = build_display_payload(
                    mapped_listing,
                    reservations,
                    mapping,
                    now=current,
                    weather_condition=weather_condition,
                    weather_temperature=weather_temperature,
                )

            return GuestyTerminalData(
                listings=listings,
                reservations=tuple(reservations),
                payloads=payloads,
                stale_listing_ids=frozenset(
                    set(available_listing_ids) - refreshed_listing_ids
                ),
            )
        except GuestyAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except GuestyRateLimitError as err:
            raise UpdateFailed(
                "Guesty rate limit reached", retry_after=err.retry_after
            ) from err
        except GuestyError as err:
            raise UpdateFailed(str(err)) from err
