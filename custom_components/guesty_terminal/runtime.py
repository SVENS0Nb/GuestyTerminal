"""Runtime orchestration between Guesty and sleeping ESPHome displays."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .api import GuestyClient
from .const import (
    CONF_LOGO_DATA,
    CONF_MAPPINGS,
    DISPLAY_ACTION_SUFFIX,
    DISPLAY_ACTION_V2_SUFFIX,
    DISPLAY_ACTION_V3_SUFFIX,
    DISPLAY_ACTION_V4_SUFFIX,
    DISPLAY_ACTION_V5_SUFFIX,
    DISPLAY_ACTION_V6_SUFFIX,
    DISPLAY_ACTION_V7_SUFFIX,
    DISPLAY_ACTION_V8_SUFFIX,
    DISPLAY_ACTION_V9_SUFFIX,
    DISPLAY_RECONNECT_STATE,
    DISPLAY_REFRESH_REQUEST_STATE,
    LOGO_DISPLAY_MODES,
)
from .coordinator import GuestyTerminalCoordinator
from .logo import logo_fingerprint, valid_logo_data
from .models import DisplayPayload, Listing, MappingOptions

_LOGGER = logging.getLogger(__name__)
_ACTION_PATTERN = re.compile(r"^[a-z0-9_]+$")


def _logo_aware_content_id(content_id: str, logo_data: str) -> str:
    """Include the global logo in an opaque visible-content fingerprint."""
    visible_id = "\0".join((content_id, logo_fingerprint(logo_data)))
    return hashlib.sha256(visible_id.encode("ascii")).hexdigest()[:24]


async def async_send_display_payload(
    hass: HomeAssistant,
    endpoint_entity: str,
    payload: DisplayPayload,
    lock: asyncio.Lock | None = None,
    *,
    force_redraw: bool = False,
    logo_data: str = "",
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
        (
            DISPLAY_ACTION_SUFFIX,
            DISPLAY_ACTION_V2_SUFFIX,
            DISPLAY_ACTION_V3_SUFFIX,
            DISPLAY_ACTION_V4_SUFFIX,
            DISPLAY_ACTION_V5_SUFFIX,
            DISPLAY_ACTION_V6_SUFFIX,
            DISPLAY_ACTION_V7_SUFFIX,
            DISPLAY_ACTION_V8_SUFFIX,
            DISPLAY_ACTION_V9_SUFFIX,
        )
    ):
        _LOGGER.warning("Ignoring invalid ESPHome display endpoint %s", action)
        return False
    if not hass.services.has_service("esphome", action):
        _LOGGER.debug("ESPHome action %s is not available yet", action)
        return False

    send_lock = lock or asyncio.Lock()
    async with send_lock:
        try:
            include_content_id = action.endswith(
                (
                    DISPLAY_ACTION_V2_SUFFIX,
                    DISPLAY_ACTION_V3_SUFFIX,
                    DISPLAY_ACTION_V4_SUFFIX,
                    DISPLAY_ACTION_V5_SUFFIX,
                    DISPLAY_ACTION_V6_SUFFIX,
                    DISPLAY_ACTION_V7_SUFFIX,
                    DISPLAY_ACTION_V8_SUFFIX,
                    DISPLAY_ACTION_V9_SUFFIX,
                )
            )
            service_data = payload.as_service_data(
                include_content_id=include_content_id,
                include_booking_summary=action.endswith(
                    (
                        DISPLAY_ACTION_V4_SUFFIX,
                        DISPLAY_ACTION_V5_SUFFIX,
                        DISPLAY_ACTION_V6_SUFFIX,
                        DISPLAY_ACTION_V7_SUFFIX,
                        DISPLAY_ACTION_V8_SUFFIX,
                        DISPLAY_ACTION_V9_SUFFIX,
                    )
                ),
                include_weather=action.endswith(
                    (
                        DISPLAY_ACTION_V5_SUFFIX,
                        DISPLAY_ACTION_V6_SUFFIX,
                        DISPLAY_ACTION_V7_SUFFIX,
                        DISPLAY_ACTION_V8_SUFFIX,
                        DISPLAY_ACTION_V9_SUFFIX,
                    )
                ),
                include_labels=action.endswith(
                    (
                        DISPLAY_ACTION_V7_SUFFIX,
                        DISPLAY_ACTION_V8_SUFFIX,
                        DISPLAY_ACTION_V9_SUFFIX,
                    )
                ),
                include_checkout_page=action.endswith(
                    (DISPLAY_ACTION_V8_SUFFIX, DISPLAY_ACTION_V9_SUFFIX)
                ),
                include_empty_page=action.endswith(DISPLAY_ACTION_V9_SUFFIX),
            )
            if action.endswith(
                (
                    DISPLAY_ACTION_V3_SUFFIX,
                    DISPLAY_ACTION_V4_SUFFIX,
                    DISPLAY_ACTION_V5_SUFFIX,
                    DISPLAY_ACTION_V6_SUFFIX,
                    DISPLAY_ACTION_V7_SUFFIX,
                    DISPLAY_ACTION_V8_SUFFIX,
                    DISPLAY_ACTION_V9_SUFFIX,
                )
            ):
                active_logo = (
                    valid_logo_data(logo_data)
                    if payload.mode in LOGO_DISPLAY_MODES
                    else ""
                )
                service_data["logo_data"] = active_logo
                if include_content_id:
                    service_data["content_id"] = _logo_aware_content_id(
                        service_data["content_id"], active_logo
                    )
            if action.endswith(
                (
                    DISPLAY_ACTION_V6_SUFFIX,
                    DISPLAY_ACTION_V7_SUFFIX,
                    DISPLAY_ACTION_V8_SUFFIX,
                    DISPLAY_ACTION_V9_SUFFIX,
                )
            ):
                service_data["base_content_id"] = _logo_aware_content_id(
                    payload.base_content_id, active_logo
                )
                service_data["force_redraw"] = force_redraw
            elif force_redraw and include_content_id:
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
    logo_data = valid_logo_data(entry.options.get(CONF_LOGO_DATA))
    await asyncio.gather(
        *(
            async_send_display_payload(
                hass,
                endpoint,
                DisplayPayload.idle(
                    Listing("", "Unterkunft"),
                    MappingOptions.from_dict(endpoint, raw_mapping),
                ),
                logo_data=logo_data,
            )
            for endpoint, raw_mapping in raw_mappings.items()
            if isinstance(endpoint, str) and isinstance(raw_mapping, dict)
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
    _sync_requests: set[str] = field(default_factory=set)
    _tasks: set[asyncio.Future[Any]] = field(default_factory=set)
    _stopped: bool = False

    def _create_task(self, coroutine: Coroutine[Any, Any, Any]) -> None:
        """Create a Home Assistant task that can be cancelled during unload."""
        if self._stopped:
            coroutine.close()
            return
        task = self.hass.async_create_task(coroutine)
        if isinstance(task, asyncio.Future):
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def async_start(self) -> None:
        """Start endpoint and coordinator listeners."""
        self._stopped = False
        mappings = self.coordinator.mapping_options()
        endpoints = [item.endpoint_entity for item in mappings]
        if endpoints:
            self._unsubscribers.append(
                async_track_state_change_event(
                    self.hass, endpoints, self._handle_endpoint_state
                )
            )
        weather_entities = sorted(
            {item.weather_entity for item in mappings if item.weather_entity}
        )
        if weather_entities:
            self._unsubscribers.append(
                async_track_state_change_event(
                    self.hass, weather_entities, self._handle_weather_state
                )
            )

        self._unsubscribers.append(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        await self.async_push_all()

    async def async_stop(self) -> None:
        """Stop all registered listeners."""
        self._stopped = True
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        pending = [task for task in self._tasks if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()
        self._sync_requests.clear()

    @callback
    def _handle_endpoint_state(self, event: Event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        endpoint = str(event.data.get("entity_id") or "")
        if not endpoint:
            return
        if new_state.state == DISPLAY_RECONNECT_STATE:
            # The firmware emits this short-lived discovery pulse before
            # restoring the actual ESPHome action. Wait for that real state
            # instead of scheduling a guaranteed invalid service call.
            return
        if new_state.state == DISPLAY_REFRESH_REQUEST_STATE:
            if endpoint in self._sync_requests:
                return
            self._sync_requests.add(endpoint)
            self._create_task(self._async_sync_and_force_redraw_endpoint(endpoint))
            return
        if endpoint in self._sync_requests:
            # The firmware restores the real action state immediately after
            # publishing its one-shot sync request. The request task performs
            # the authoritative push after Guesty has been refreshed.
            return

        @callback
        def _delayed_push(_now: datetime) -> None:
            if cancel in self._unsubscribers:
                self._unsubscribers.remove(cancel)
            self._create_task(self.async_push_endpoint(endpoint))

        # ESPHome publishes the endpoint entity just before its user-defined
        # action is registered. A short delay removes that connection race.
        cancel: Callable[[], None] = async_call_later(self.hass, 2, _delayed_push)
        self._unsubscribers.append(cancel)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._create_task(self.async_push_all(exclude=frozenset(self._sync_requests)))

    @callback
    def _handle_weather_state(self, event: Event) -> None:
        """Push live weather to displays mapped to the changed entity."""
        weather_entity = str(event.data.get("entity_id") or "")
        endpoints = {
            mapping.endpoint_entity
            for mapping in self.coordinator.mapping_options()
            if mapping.weather_entity == weather_entity
        }
        for endpoint in endpoints:
            endpoint_state = self.hass.states.get(endpoint)
            action = str(getattr(endpoint_state, "state", "")).strip()
            if not action.endswith(
                (
                    DISPLAY_ACTION_V6_SUFFIX,
                    DISPLAY_ACTION_V7_SUFFIX,
                    DISPLAY_ACTION_V8_SUFFIX,
                    DISPLAY_ACTION_V9_SUFFIX,
                )
            ):
                # Older firmware cannot perform the hybrid weather refresh.
                # It will still receive live weather on its next normal or
                # explicitly forced payload without adding full panel flashes
                # for every weather-entity state change.
                continue
            self._create_task(self.async_push_endpoint(endpoint))

    async def async_push_all(self, *, exclude: frozenset[str] = frozenset()) -> None:
        """Push current payloads to every display that is online."""
        if self.coordinator.data is None:
            return
        await asyncio.gather(
            *(
                self.async_push_endpoint(endpoint)
                for endpoint in self.coordinator.data.payloads
                if endpoint not in exclude
            ),
            return_exceptions=True,
        )

    async def _async_sync_and_force_redraw_endpoint(self, endpoint: str) -> None:
        """Refresh Guesty, then redraw the requesting display once."""
        try:
            # Let the firmware restore the endpoint sensor's real ESPHome
            # action before the refreshed payload is sent back.
            await asyncio.sleep(0.5)
            self.coordinator.invalidate_guest_data_caches()
            await self.coordinator.async_request_refresh()
            if not self.coordinator.last_update_success:
                _LOGGER.warning(
                    "Guesty refresh failed; not redrawing display %s with stale data",
                    endpoint,
                )
                return
            if (
                self.coordinator.data is not None
                and endpoint in self.coordinator.data.payloads
            ):
                await self.async_force_redraw_endpoint(endpoint)
            else:
                await self.async_clear_endpoint(endpoint)
        finally:
            self._sync_requests.discard(endpoint)

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
        if payload is None:
            return payload
        mapping = next(
            (
                item
                for item in self.coordinator.mapping_options()
                if item.endpoint_entity == endpoint_entity
            ),
            None,
        )
        if not payload.is_expired(datetime.now(UTC)):
            return self.coordinator.payload_with_current_weather(
                endpoint_entity, payload
            )
        listing = (
            self.coordinator.data.listings.get(mapping.listing_id)
            if mapping is not None
            else None
        )
        return DisplayPayload.idle(
            listing or Listing("", payload.property_name or "Unterkunft"), mapping
        )

    async def async_clear_endpoint(self, endpoint_entity: str) -> bool:
        """Replace a potentially sensitive E-paper image with an idle screen."""
        property_name = "Unterkunft"
        mapping = next(
            (
                item
                for item in self.coordinator.mapping_options()
                if item.endpoint_entity == endpoint_entity
            ),
            None,
        )
        if self.coordinator.data is not None:
            current = self.coordinator.data.payloads.get(endpoint_entity)
            if current is not None and current.property_name:
                property_name = current.property_name
        return await self._async_send_payload(
            endpoint_entity,
            DisplayPayload.idle(Listing("", property_name), mapping),
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
            logo_data=valid_logo_data(self.entry.options.get(CONF_LOGO_DATA)),
        )
