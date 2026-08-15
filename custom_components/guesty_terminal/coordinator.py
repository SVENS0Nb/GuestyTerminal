"""Guesty data coordinator."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GuestyAuthenticationError, GuestyClient, GuestyError
from .const import (
    CONF_MAPPINGS,
    CONF_POLL_MINUTES,
    DEFAULT_POLL_MINUTES,
    DOMAIN,
)
from .models import (
    DisplayPayload,
    Listing,
    MappingOptions,
    Reservation,
    build_display_payload,
    extract_keycode_direct,
    extract_keycode_from_custom_fields,
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
        poll_minutes = max(
            2, int(entry.options.get(CONF_POLL_MINUTES, DEFAULT_POLL_MINUTES))
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

    async def _async_keycode(self, raw: dict[str, Any]) -> str:
        direct = extract_keycode_direct(raw)
        if direct:
            return direct

        reservation_id = str(raw.get("_id") or raw.get("id") or "")
        if not reservation_id:
            return ""
        version = str(raw.get("lastUpdatedAt") or "")
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
            self._keycode_cache[cache_key] = ""
            return ""

        direct = extract_keycode_direct(populated)
        if direct:
            self._keycode_cache[cache_key] = direct
            return direct

        account_id = str(raw.get("accountId") or "")
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
                    self._custom_field_definitions[account_id] = []
            definitions = self._custom_field_definitions[account_id]

        keycode = extract_keycode_from_custom_fields(populated, definitions)
        self._keycode_cache[cache_key] = keycode
        return keycode

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
                listing_id = str(raw.get("listingId") or "")
                if not listing_id:
                    nested = raw.get("listing")
                    if isinstance(nested, dict):
                        listing_id = str(nested.get("_id") or nested.get("id") or "")
                listing = listings.get(listing_id)
                if listing is None:
                    continue
                keycode = await self._async_keycode(raw)
                reservation = Reservation.from_api(raw, listing, keycode=keycode)
                if reservation is not None:
                    reservations.append(reservation)

            payloads: dict[str, DisplayPayload] = {}
            for mapping in mappings:
                listing = listings.get(mapping.listing_id)
                if listing is None:
                    continue
                payloads[mapping.endpoint_entity] = build_display_payload(
                    listing, reservations, mapping
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
