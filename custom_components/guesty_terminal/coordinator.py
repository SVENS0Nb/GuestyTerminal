"""Guesty data coordinator."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Mapping
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
    build_display_payload,
    extract_keycode_direct,
    extract_keycode_from_custom_fields,
    first_present,
    reservation_listing_id,
)

_LOGGER = logging.getLogger(__name__)
_GUEST_CACHE_SECONDS = DEFAULT_POLL_MINUTES * 60
_COMPLETED_RESERVATION_RETENTION = timedelta(hours=COMPLETED_RESERVATION_CACHE_HOURS)
_MAX_KEYCODE_CACHE_ITEMS = 512
_MAX_GUEST_CACHE_ITEMS = 256
_MAX_CONCURRENT_GUESTY_REQUESTS = 4
_CUSTOM_FIELD_DEFINITION_CACHE_SECONDS = 60 * 60


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


@dataclass(frozen=True, slots=True)
class GuestyTerminalData:
    """One complete coordinator snapshot."""

    listings: dict[str, Listing]
    reservations: tuple[Reservation, ...]
    payloads: dict[str, DisplayPayload]


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

    async def _async_keycode(self, raw: dict[str, Any]) -> str:
        direct = extract_keycode_direct(raw)
        if direct:
            return direct

        reservation_id = first_present(raw, "reservationId", "_id", "id")
        if not reservation_id:
            return ""
        channel_metadata = raw.get("channelMetadata")
        if not isinstance(channel_metadata, dict):
            channel_metadata = {}
        # Only cache against a Guesty change marker. When search omits one,
        # querying the custom-field endpoint again is safer than retaining an
        # access code indefinitely after it was changed or removed.
        version = first_present(raw, "lastUpdatedAt") or first_present(
            channel_metadata, "updatedAt"
        )
        cache_key = (reservation_id, version) if version else None
        if cache_key is not None and cache_key in self._keycode_cache:
            return self._keycode_cache[cache_key]

        try:
            populated = await self.client.async_get_reservation_custom_fields(
                reservation_id
            )
        except (GuestyAuthenticationError, GuestyRateLimitError):
            raise
        except GuestyError as err:
            _LOGGER.debug(
                "Could not load custom fields for reservation %s: %s",
                reservation_id,
                err,
            )
            return ""

        direct = extract_keycode_direct(populated)
        if direct:
            if cache_key is not None:
                _bounded_cache_set(
                    self._keycode_cache,
                    cache_key,
                    direct,
                    _MAX_KEYCODE_CACHE_ITEMS,
                )
            return direct

        account_id = str(raw.get("accountId") or self._account_id or "")
        if not account_id:
            try:
                account = await self.client.async_get_current_account()
            except (GuestyAuthenticationError, GuestyRateLimitError):
                raise
            except GuestyError as err:
                _LOGGER.debug("Could not load current Guesty account: %s", err)
            else:
                account_id = first_present(account, "id", "_id")
                self._account_id = account_id or None
        definitions: Any = []
        if account_id:
            cached_definitions = self._custom_field_definitions.get(account_id)
            if (
                cached_definitions is not None
                and time.monotonic() - cached_definitions[0]
                < _CUSTOM_FIELD_DEFINITION_CACHE_SECONDS
            ):
                definitions = cached_definitions[1]
            else:
                try:
                    definitions = await self.client.async_get_account_custom_fields(
                        account_id
                    )
                except (GuestyAuthenticationError, GuestyRateLimitError):
                    raise
                except GuestyError as err:
                    _LOGGER.debug(
                        "Could not load Guesty custom-field definitions: %s", err
                    )
                    if cached_definitions is not None:
                        definitions = cached_definitions[1]
                else:
                    self._custom_field_definitions[account_id] = (
                        time.monotonic(),
                        definitions,
                    )

        keycode = extract_keycode_from_custom_fields(populated, definitions)
        if keycode and cache_key is not None:
            _bounded_cache_set(
                self._keycode_cache,
                cache_key,
                keycode,
                _MAX_KEYCODE_CACHE_ITEMS,
            )
        return keycode

    async def _async_guest(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Return embedded or separately loaded guest name data."""
        guest = raw.get("guest")
        if isinstance(guest, dict) and guest:
            return guest
        guest_id = first_present(raw, "guestId", "bookerId")
        if not guest_id:
            return {}
        cached = self._guest_cache.get(guest_id)
        if cached is not None and time.monotonic() - cached[0] < _GUEST_CACHE_SECONDS:
            return cached[1]
        try:
            guest = await self.client.async_get_guest(guest_id)
        except (GuestyAuthenticationError, GuestyRateLimitError):
            raise
        except GuestyError as err:
            _LOGGER.debug("Could not load Guesty guest %s: %s", guest_id, err)
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
    ) -> Reservation | None:
        """Normalize one booking with the required optional enrichments."""
        guest = await self._async_guest(raw)
        if guest and not isinstance(raw.get("guest"), dict):
            raw = {**raw, "guest": guest}
        keycode = await self._async_keycode(raw) if include_keycode else ""
        reservation = Reservation.from_api(raw, listing, keycode=keycode)
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
    ) -> None:
        """Replace only changed per-listing snapshots in the local RAM cache."""
        cache = self._reservation_snapshot_cache
        for listing_id in set(cache) - mapped_listing_ids:
            cache.pop(listing_id, None)
        for listing_id in mapped_listing_ids:
            current_snapshot = tuple(
                reservation
                for reservation in fresh.get(listing_id, ())
                if reservation.check_in > current
                or current < reservation.check_out + _COMPLETED_RESERVATION_RETENTION
            )
            fresh_ids = {reservation.reservation_id for reservation in current_snapshot}
            retained_completed = tuple(
                reservation
                for reservation in cache.get(listing_id, ())
                if reservation.reservation_id not in fresh_ids
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
                    # One removed or temporarily failing mapping must not stop
                    # unrelated displays. Retain an older detail record only
                    # when the active listing still exists in the collection.
                    if listing is not None and cached is not None:
                        return listing_id, cached[1], False
                    return listing_id, listing, False
                if full and (full_listing := Listing.from_api(full)).listing_id:
                    if cached is not None and cached[1] == full_listing:
                        return listing_id, cached[1], False
                    return listing_id, full_listing, True
                elif listing is not None:
                    if cached is not None:
                        return listing_id, cached[1], False
                    return listing_id, listing, True
                return listing_id, None, False

            detail_results = await asyncio.gather(
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
            raw_reservations = await self.client.async_get_reservations(
                available_listing_ids
            )
            raw_by_listing: dict[str, list[tuple[dict[str, Any], bool]]] = {
                listing_id: [] for listing_id in mapped_listing_ids
            }
            known_ids: dict[str, set[str]] = {
                listing_id: set() for listing_id in mapped_listing_ids
            }
            for raw in raw_reservations:
                listing_id = reservation_listing_id(raw)
                if listing_id not in raw_by_listing or listing_id not in listings:
                    continue
                reservation_id = first_present(raw, "reservationId", "_id", "id")
                if reservation_id:
                    known_ids[listing_id].add(reservation_id)
                raw_by_listing[listing_id].append((raw, True))

            # Fetch an authoritative, ordered future snapshot on every normal
            # poll. There is deliberately no query TTL here: additions and
            # future cancellations are detected within five minutes. The
            # reconciliation layer separately retains completed stays for
            # twelve hours. The short collection above remains responsible for
            # a current or just-ended stay and its access code.
            async def _upcoming_reservations(
                listing_id: str,
            ) -> tuple[str, list[dict[str, Any]]]:
                async with api_semaphore:
                    upcoming = await self.client.async_get_upcoming_reservations(
                        listing_id,
                        limit=UPCOMING_RESERVATIONS_PER_LISTING,
                    )
                return listing_id, upcoming

            upcoming_results = await asyncio.gather(
                *(
                    _upcoming_reservations(listing_id)
                    for listing_id in available_listing_ids
                )
            )
            for listing_id, upcoming in upcoming_results:
                for raw in upcoming:
                    reservation_id = first_present(raw, "reservationId", "_id", "id")
                    if reservation_id and reservation_id in known_ids[listing_id]:
                        continue
                    if reservation_id:
                        known_ids[listing_id].add(reservation_id)
                    raw_by_listing[listing_id].append((raw, False))

            async def _normalized_listing(
                listing_id: str,
            ) -> tuple[str, tuple[Reservation, ...]]:
                listing = listings.get(listing_id)
                if listing is None:
                    return listing_id, ()
                normalized: list[Reservation] = []
                async with api_semaphore:
                    for raw, include_keycode in raw_by_listing[listing_id]:
                        reservation = await self._async_normalize_reservation(
                            raw,
                            listing,
                            include_keycode=include_keycode,
                        )
                        if reservation is not None:
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

            normalized_results = await asyncio.gather(
                *(
                    _normalized_listing(listing_id)
                    for listing_id in mapped_listing_ids
                    if listing_id in listings
                )
            )
            fresh_snapshots = dict(normalized_results)

            self._reconcile_reservation_snapshots(
                fresh_snapshots,
                mapped_listing_id_set,
                current,
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
                if mapped_listing is None:
                    continue
                weather_condition, weather_temperature = self._weather_values(mapping)
                payloads[mapping.endpoint_entity] = build_display_payload(
                    mapped_listing,
                    reservations,
                    mapping,
                    weather_condition=weather_condition,
                    weather_temperature=weather_temperature,
                )

            return GuestyTerminalData(
                listings=listings,
                reservations=tuple(reservations),
                payloads=payloads,
            )
        except GuestyAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except GuestyRateLimitError as err:
            raise UpdateFailed(
                "Guesty rate limit reached", retry_after=err.retry_after
            ) from err
        except GuestyError as err:
            raise UpdateFailed(str(err)) from err
