"""Guesty data coordinator."""

from __future__ import annotations

import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
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

            # The listing collection may omit location-detail fields on some Guesty
            # accounts. Fetch mapped listings individually when Wi-Fi data is absent.
            for listing_id in mapped_listing_ids:
                listing = listings.get(listing_id)
                if listing is not None and listing.wifi_name and listing.wifi_password:
                    continue
                full = await self.client.async_get_listing(listing_id)
                if full:
                    listings[listing_id] = Listing.from_api(full)

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
