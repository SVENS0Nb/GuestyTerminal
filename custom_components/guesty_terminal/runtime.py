"""Runtime orchestration between Guesty and sleeping ESPHome displays."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .api import GuestyClient
from .const import CONF_MAPPINGS, DISPLAY_ACTION_SUFFIX, DISPLAY_ACTION_V2_SUFFIX
from .coordinator import GuestyTerminalCoordinator
from .models import DisplayPayload, Listing

_LOGGER = logging.getLogger(__name__)
_ACTION_PATTERN = re.compile(r"^[a-z0-9_]+$")


async def async_send_display_payload(
    hass: HomeAssistant,
    endpoint_entity: str,
    payload: DisplayPayload,
    lock: asyncio.Lock | None = None,
    *,
    force_redraw: bool = False,
) -> bool:
    """Send one payload directly to a reachable ESPHome display."""
    endpoint_state = hass.states.get(endpoint_entity)
    if endpoint_state is None or endpoint_state.state in (
        STATE_UNKNOWN,
        STATE_UNAVAILABLE,
    ):
        return False

    action = endpoint_state.state.strip()
    if not _ACTION_PATTERN.fullmatch(action) or not action.endswith(
        (DISPLAY_ACTION_SUFFIX, DISPLAY_ACTION_V2_SUFFIX)
    ):
        _LOGGER.warning("Ignoring invalid ESPHome display endpoint %s", action)
        return False
    if not hass.services.has_service("esphome", action):
        _LOGGER.debug("ESPHome action %s is not available yet", action)
        return False

    send_lock = lock or asyncio.Lock()
    async with send_lock:
        try:
            include_content_id = action.endswith(DISPLAY_ACTION_V2_SUFFIX)
            service_data = payload.as_service_data(
                include_content_id=include_content_id
            )
            if force_redraw and include_content_id:
                # An empty fingerprint is the firmware's explicit one-shot
                # recovery signal. Normal duplicate suppression remains on.
                service_data["content_id"] = ""
            await hass.services.async_call(
                "esphome",
                action,
                service_data,
                blocking=True,
            )
        except Exception:  # Home Assistant service errors vary by ESPHome version.
            _LOGGER.debug(
                "Could not update sleeping ESPHome display %s",
                endpoint_entity,
                exc_info=True,
            )
            return False
    _LOGGER.debug(
        "Updated GuestyTerminal display %s in %s mode",
        endpoint_entity,
        payload.mode,
    )
    return True


async def async_clear_configured_displays(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Best-effort clear when a GuestyTerminal entry is permanently removed."""
    raw_mappings = entry.options.get(CONF_MAPPINGS, {})
    if not isinstance(raw_mappings, dict):
        return
    idle = DisplayPayload.idle(Listing("", "Unterkunft"))
    await asyncio.gather(
        *(
            async_send_display_payload(hass, endpoint, idle)
            for endpoint in raw_mappings
            if isinstance(endpoint, str)
        ),
        return_exceptions=True,
    )


@dataclass(slots=True)
class GuestyTerminalRuntime:
    """Hold entry objects and push payloads while displays are awake."""

    hass: HomeAssistant
    entry: ConfigEntry
    client: GuestyClient
    coordinator: GuestyTerminalCoordinator
    _unsubscribers: list[Callable[[], None]] = field(default_factory=list)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    async def async_start(self) -> None:
        """Start endpoint and coordinator listeners."""
        endpoints = [
            item.endpoint_entity for item in self.coordinator.mapping_options()
        ]
        if endpoints:
            self._unsubscribers.append(
                async_track_state_change_event(
                    self.hass, endpoints, self._handle_endpoint_state
                )
            )

        self._unsubscribers.append(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        await self.async_push_all()

    async def async_stop(self) -> None:
        """Stop all registered listeners."""
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()

    @callback
    def _handle_endpoint_state(self, event: Event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        endpoint = str(event.data.get("entity_id") or "")

        @callback
        def _delayed_push(_now: datetime) -> None:
            if cancel in self._unsubscribers:
                self._unsubscribers.remove(cancel)
            self.hass.async_create_task(self.async_push_endpoint(endpoint))

        # ESPHome publishes the endpoint entity just before its user-defined
        # action is registered. A short delay removes that connection race.
        cancel: Callable[[], None] = async_call_later(self.hass, 2, _delayed_push)
        self._unsubscribers.append(cancel)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.hass.async_create_task(self.async_push_all())

    async def async_push_all(self) -> None:
        """Push current payloads to every display that is online."""
        if self.coordinator.data is None:
            return
        await asyncio.gather(
            *(
                self.async_push_endpoint(endpoint)
                for endpoint in self.coordinator.data.payloads
            ),
            return_exceptions=True,
        )

    async def async_push_endpoint(self, endpoint_entity: str) -> bool:
        """Push one display payload through its ESPHome action."""
        payload = self._safe_payload_for_endpoint(endpoint_entity)
        if payload is None:
            return False
        return await self._async_send_payload(endpoint_entity, payload)

    async def async_force_redraw_all(self) -> None:
        """Redraw configured displays once using cached payloads."""
        if self.coordinator.data is None:
            return
        await asyncio.gather(
            *(
                self.async_force_redraw_endpoint(endpoint)
                for endpoint in self.coordinator.data.payloads
            ),
            return_exceptions=True,
        )

    async def async_force_redraw_endpoint(self, endpoint_entity: str) -> bool:
        """Force one redraw without fetching or changing Guesty data."""
        payload = self._safe_payload_for_endpoint(endpoint_entity)
        if payload is None:
            return False
        return await self._async_send_payload(
            endpoint_entity, payload, force_redraw=True
        )

    def _safe_payload_for_endpoint(self, endpoint_entity: str) -> DisplayPayload | None:
        """Return cached content, replacing an expired guest screen with idle."""
        if self.coordinator.data is None:
            return None
        payload = self.coordinator.data.payloads.get(endpoint_entity)
        if payload is None or not payload.is_expired(datetime.now(UTC)):
            return payload

        mapping = next(
            (
                item
                for item in self.coordinator.mapping_options()
                if item.endpoint_entity == endpoint_entity
            ),
            None,
        )
        listing = (
            self.coordinator.data.listings.get(mapping.listing_id)
            if mapping is not None
            else None
        )
        return DisplayPayload.idle(
            listing or Listing("", payload.property_name or "Unterkunft")
        )

    async def async_clear_endpoint(self, endpoint_entity: str) -> bool:
        """Replace a potentially sensitive E-paper image with an idle screen."""
        property_name = "Unterkunft"
        if self.coordinator.data is not None:
            current = self.coordinator.data.payloads.get(endpoint_entity)
            if current is not None and current.property_name:
                property_name = current.property_name
        return await self._async_send_payload(
            endpoint_entity,
            DisplayPayload.idle(Listing("", property_name)),
        )

    async def async_clear_all(self) -> None:
        """Best-effort clear of every display configured for this account."""
        await asyncio.gather(
            *(
                self.async_clear_endpoint(mapping.endpoint_entity)
                for mapping in self.coordinator.mapping_options()
            ),
            return_exceptions=True,
        )

    async def _async_send_payload(
        self,
        endpoint_entity: str,
        payload: DisplayPayload,
        *,
        force_redraw: bool = False,
    ) -> bool:
        """Send a prepared payload when the ESPHome endpoint is reachable."""
        lock = self._locks.setdefault(endpoint_entity, asyncio.Lock())
        return await async_send_display_payload(
            self.hass,
            endpoint_entity,
            payload,
            lock,
            force_redraw=force_redraw,
        )
