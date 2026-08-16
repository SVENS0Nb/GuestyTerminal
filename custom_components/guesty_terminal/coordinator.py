"""Guesty data coordinator."""

from __future__ import annotations

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

from .api import GuestyAuthenticationError, GuestyClient, GuestyError
from .const import (
    CONF_MAPPINGS,
    CONF_POLL_MINUTES,
    DEFAULT_POLL_MINUTES,
    DOMAIN,
    MAX_POLL_MINUTES,
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
_LISTING_DETAIL_CACHE_SECONDS = 30 * 60


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
        entry: ConfigEntry,
        client: GuestyClient,
    ) -> None:
        poll_minutes = min(
            MAX_POLL_MINUTES,
            max(2, int(entry.options.get(CONF_POLL_MINUTES, DEFAULT_POLL_MINUTES))),
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
        self._custom_field_definitions: dict[str, Any] = {}
        self._guest_cache: dict[str, dict[str, Any]] = {}
        self._listing_detail_cache: dict[str, tuple[float, Listing]] = {}
        self._next_reservation_cache: dict[
            str, tuple[float, dict[str, Any] | None]
        ] = {}
        self._account_id: str | None = None

    def mapping_options(self) -> list[MappingOptions]:
        """Return all valid stored display mappings."""
        raw_mappings = self.entry.options.get(CONF_MAPPINGS, {})
        if not isinstance(raw_mappings, dict):
            return []
        mappings: list[MappingOptions] = []
        for endpoint, raw in raw_mappings.items():
            if not isinstance(raw, dict):
                continue
            mapping = MappingOptions.from_dict(endpoint, raw)
            if mapping.endpoint_entity and mapping.listing_id:
                mappings.append(mapping)
        return mappings

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
        version = (
            first_present(raw, "lastUpdatedAt")
            or first_present(channel_metadata, "updatedAt")
            or repr(raw.get("customFields", ""))
            or first_present(raw, "createdAt")
        )
        cache_key = (reservation_id, version)
        if cache_key in self._keycode_cache:
            return self._keycode_cache[cache_key]

        try:
            populated = await self.client.async_get_reservation_custom_fields(
                reservation_id
            )
        except GuestyError as err:
            _LOGGER.debug(
                "Could not load custom fields for reservation %s: %s",
                reservation_id,
                err,
            )
            return ""

        direct = extract_keycode_direct(populated)
        if direct:
            self._keycode_cache[cache_key] = direct
            return direct

        account_id = str(raw.get("accountId") or self._account_id or "")
        if not account_id:
            try:
                account = await self.client.async_get_current_account()
            except GuestyError as err:
                _LOGGER.debug("Could not load current Guesty account: %s", err)
            else:
                account_id = first_present(account, "id", "_id")
                self._account_id = account_id or None
        definitions: Any = []
        if account_id:
            if account_id not in self._custom_field_definitions:
                try:
                    self._custom_field_definitions[
                        account_id
                    ] = await self.client.async_get_account_custom_fields(account_id)
                except GuestyError as err:
                    _LOGGER.debug(
                        "Could not load Guesty custom-field definitions: %s", err
                    )
                else:
                    definitions = self._custom_field_definitions[account_id]
            else:
                definitions = self._custom_field_definitions[account_id]

        keycode = extract_keycode_from_custom_fields(populated, definitions)
        if keycode:
            self._keycode_cache[cache_key] = keycode
        return keycode

    async def _async_guest(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Return embedded or separately loaded guest name data."""
        guest = raw.get("guest")
        if isinstance(guest, dict) and guest:
            return guest
        guest_id = first_present(raw, "guestId", "bookerId")
        if not guest_id:
            return {}
        if guest_id in self._guest_cache:
            return self._guest_cache[guest_id]
        try:
            guest = await self.client.async_get_guest(guest_id)
        except GuestyError as err:
            _LOGGER.debug("Could not load Guesty guest %s: %s", guest_id, err)
            return {}
        if guest:
            self._guest_cache[guest_id] = guest
        return guest

    async def _async_update_data(self) -> GuestyTerminalData:
        try:
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

            # The listing collection may omit guest-facing detail fields. Cache
            # full mapped listings for one battery wake cycle so missing optional
            # instructions do not create an extra API request on every poll.
            detail_cache = getattr(self, "_listing_detail_cache", None)
            if detail_cache is None:
                detail_cache = self._listing_detail_cache = {}
            for listing_id in mapped_listing_ids:
                listing = listings.get(listing_id)
                if (
                    listing is not None
                    and listing.wifi_name
                    and listing.wifi_password
                    and listing.checkout_instructions
                ):
                    continue
                cached = detail_cache.get(listing_id)
                if cached is not None and time.monotonic() - cached[0] < (
                    _LISTING_DETAIL_CACHE_SECONDS
                ):
                    listings[listing_id] = cached[1]
                    continue
                full = await self.client.async_get_listing(listing_id)
                if full and (full_listing := Listing.from_api(full)).listing_id:
                    listings[listing_id] = full_listing
                    detail_cache[listing_id] = (time.monotonic(), full_listing)
                elif listing is not None:
                    detail_cache[listing_id] = (time.monotonic(), listing)

            raw_reservations = await self.client.async_get_reservations(
                mapped_listing_ids
            )
            reservations: list[Reservation] = []
            for raw in raw_reservations:
                listing_id = reservation_listing_id(raw)
                listing = listings.get(listing_id)
                if listing is None:
                    continue
                guest = await self._async_guest(raw)
                if guest and not isinstance(raw.get("guest"), dict):
                    raw = {**raw, "guest": guest}
                keycode = await self._async_keycode(raw)
                reservation = Reservation.from_api(raw, listing, keycode=keycode)
                if reservation is not None:
                    reservations.append(reservation)

            # The regular poll deliberately remains narrow for battery and API
            # efficiency. Fetch only one farther-future reservation per listing
            # when that window contains no upcoming stay, and cache the result
            # for one normal battery wake cycle.
            current = datetime.now(UTC)
            next_cache = getattr(self, "_next_reservation_cache", None)
            if next_cache is None:
                next_cache = self._next_reservation_cache = {}
            known_ids = {reservation.reservation_id for reservation in reservations}
            for listing_id in mapped_listing_ids:
                if any(
                    reservation.listing_id == listing_id
                    and reservation.check_in > current
                    for reservation in reservations
                ):
                    continue
                cached = next_cache.get(listing_id)
                if cached is not None and time.monotonic() - cached[0] < (
                    _LISTING_DETAIL_CACHE_SECONDS
                ):
                    raw_next = cached[1]
                else:
                    try:
                        raw_next = await self.client.async_get_next_reservation(
                            listing_id
                        )
                    except GuestyError as err:
                        _LOGGER.debug(
                            "Could not load next reservation for listing %s: %s",
                            listing_id,
                            err,
                        )
                        raw_next = None
                    next_cache[listing_id] = (time.monotonic(), raw_next or None)
                if not raw_next:
                    continue
                reservation_id = first_present(raw_next, "reservationId", "_id", "id")
                if reservation_id in known_ids:
                    continue
                listing = listings.get(listing_id)
                if listing is None:
                    continue
                guest = await self._async_guest(raw_next)
                if guest and not isinstance(raw_next.get("guest"), dict):
                    raw_next = {**raw_next, "guest": guest}
                next_reservation = Reservation.from_api(raw_next, listing)
                if next_reservation is not None and next_reservation.check_in > current:
                    reservations.append(next_reservation)
                    known_ids.add(next_reservation.reservation_id)

            payloads: dict[str, DisplayPayload] = {}
            for mapping in mappings:
                listing = listings.get(mapping.listing_id)
                if listing is None:
                    continue
                weather_condition, weather_temperature = self._weather_values(mapping)
                payloads[mapping.endpoint_entity] = build_display_payload(
                    listing,
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
        except GuestyError as err:
            raise UpdateFailed(str(err)) from err
