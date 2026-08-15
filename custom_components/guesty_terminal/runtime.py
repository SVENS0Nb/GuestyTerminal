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
from .const import DISPLAY_ACTION_SUFFIX
from .coordinator import GuestyTerminalCoordinator
from .models import DisplayPayload

_LOGGER = logging.getLogger(__name__)
_ACTION_PATTERN = re.compile(r"^[a-z0-9_]+$")


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

    async def async_push_endpoint(self, endpoint_entity: str) -> None:
        """Push one display payload through its ESPHome action."""
        if self.coordinator.data is None:
            return
        payload = self.coordinator.data.payloads.get(endpoint_entity)
        if payload is None:
            return

        endpoint_state = self.hass.states.get(endpoint_entity)
        if endpoint_state is None or endpoint_state.state in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        ):
            return

        action = endpoint_state.state.strip()
        if not _ACTION_PATTERN.fullmatch(action) or not action.endswith(
            DISPLAY_ACTION_SUFFIX
        ):
            _LOGGER.warning("Ignoring invalid ESPHome display endpoint %s", action)
            return
        if not self.hass.services.has_service("esphome", action):
            _LOGGER.debug("ESPHome action %s is not available yet", action)
            return

        if payload.is_expired(datetime.now(UTC)):
            mapping = next(
                (
                    item
                    for item in self.coordinator.mapping_options()
                    if item.endpoint_entity == endpoint_entity
                ),
                None,
            )
            if mapping is not None:
                listing = self.coordinator.data.listings.get(mapping.listing_id)
                if listing is not None:
                    payload = DisplayPayload.idle(listing)

        lock = self._locks.setdefault(endpoint_entity, asyncio.Lock())
        async with lock:
            try:
                await self.hass.services.async_call(
                    "esphome", action, payload.as_service_data(), blocking=True
                )
            except Exception:  # Home Assistant service errors vary by ESPHome version.
                _LOGGER.debug(
                    "Could not update sleeping ESPHome display %s",
                    endpoint_entity,
                    exc_info=True,
                )
                return
        _LOGGER.debug(
            "Updated GuestyTerminal display %s in %s mode",
            endpoint_entity,
            payload.mode,
        )
