"""Runtime orchestration between Guesty and sleeping ESPHome displays."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections.abc import Callable, Coroutine
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_state_change_event

from .api import GuestyClient
from .const import (
    CONF_ENDPOINT_ID,
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
    DOMAIN,
    LOGO_DISPLAY_MODES,
)
from .coordinator import GuestyTerminalCoordinator
from .logo import logo_fingerprint, valid_logo_data
from .models import DisplayPayload, Listing, MappingOptions

_LOGGER = logging.getLogger(__name__)
_ACTION_PATTERN = re.compile(r"^[a-z0-9_]+$")
_ENDPOINT_RETRY_DELAYS = (0.0, 1.0, 2.0, 4.0, 8.0, 8.0)


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
    hass: HomeAssistant, entry: ConfigEntry[Any]
) -> None:
    """Best-effort clear when a GuestyTerminal entry is permanently removed."""
    raw_mappings = entry.options.get(CONF_MAPPINGS, {})
    if not isinstance(raw_mappings, dict):
        return
    endpoints_owned_elsewhere: set[str] = set()
    config_entries = getattr(hass, "config_entries", None)
    async_entries = getattr(config_entries, "async_entries", None)
    if callable(async_entries):
        current_entry_id = str(getattr(entry, "entry_id", ""))
        for configured_entry in async_entries(DOMAIN):
            if configured_entry is entry or (
                current_entry_id
                and str(getattr(configured_entry, "entry_id", "")) == current_entry_id
            ):
                continue
            other_mappings = getattr(configured_entry, "options", {}).get(
                CONF_MAPPINGS, {}
            )
            if isinstance(other_mappings, dict):
                endpoints_owned_elsewhere.update(
                    endpoint
                    for endpoint, mapping in other_mappings.items()
                    if isinstance(endpoint, str) and isinstance(mapping, dict)
                )
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
            if endpoint not in endpoints_owned_elsewhere
        ),
        return_exceptions=True,
    )


@dataclass(frozen=True, slots=True)
class DisplayDeliveryResult:
    """Non-sensitive aggregate for one multi-display delivery attempt."""

    attempted: int
    succeeded: int

    @property
    def failed(self) -> int:
        """Return the number of displays that did not accept the payload."""
        return self.attempted - self.succeeded


async def _async_delivery_result(
    deliveries: list[Coroutine[Any, Any, bool]],
) -> DisplayDeliveryResult:
    """Run independent deliveries and reduce their results without identifiers."""
    if not deliveries:
        return DisplayDeliveryResult(0, 0)
    results = await asyncio.gather(*deliveries, return_exceptions=True)
    return DisplayDeliveryResult(
        attempted=len(results),
        succeeded=sum(result is True for result in results),
    )


@dataclass(slots=True)
class GuestyTerminalRuntime:
    """Hold entry objects and push payloads while displays are awake."""

    hass: HomeAssistant
    entry: ConfigEntry[GuestyTerminalRuntime]
    client: GuestyClient
    coordinator: GuestyTerminalCoordinator
    _unsubscribers: list[Callable[[], None]] = field(default_factory=list)
    _locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    _sync_requests: set[str] = field(default_factory=set)
    _pending_endpoint_pushes: set[str] = field(default_factory=set)
    _tasks: set[asyncio.Future[Any]] = field(default_factory=set)
    _manual_refresh_requests: int = 0
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
        bus = getattr(self.hass, "bus", None)
        async_listen = getattr(bus, "async_listen", None)
        if callable(async_listen):
            self._unsubscribers.append(
                async_listen(
                    er.EVENT_ENTITY_REGISTRY_UPDATED,
                    self._handle_entity_registry_update,
                )
            )
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

    @callback
    def _handle_entity_registry_update(self, event: Event) -> None:
        """Move a mapping when Home Assistant renames its endpoint entity."""
        if event.data.get("action") != "update":
            return
        old_endpoint = str(event.data.get("old_entity_id") or "")
        new_endpoint = str(event.data.get("entity_id") or "")
        if not old_endpoint or not new_endpoint or old_endpoint == new_endpoint:
            return

        raw_mappings = self.entry.options.get(CONF_MAPPINGS, {})
        if not isinstance(raw_mappings, dict) or old_endpoint not in raw_mappings:
            return
        if new_endpoint in raw_mappings:
            _LOGGER.error(
                "Cannot migrate a renamed GuestyTerminal endpoint because the "
                "new entity ID is already mapped"
            )
            return

        async_entries = getattr(self.hass.config_entries, "async_entries", None)
        if callable(async_entries):
            for configured_entry in async_entries(DOMAIN):
                if configured_entry is self.entry:
                    continue
                other_mappings = configured_entry.options.get(CONF_MAPPINGS, {})
                if isinstance(other_mappings, dict) and new_endpoint in other_mappings:
                    _LOGGER.error(
                        "Cannot migrate a renamed GuestyTerminal endpoint because "
                        "another config entry already owns it"
                    )
                    return

        options = deepcopy(dict(self.entry.options))
        mappings = deepcopy(raw_mappings)
        raw_mapping = mappings.pop(old_endpoint)
        if isinstance(raw_mapping, dict):
            raw_mapping.setdefault(
                CONF_ENDPOINT_ID,
                hashlib.sha256(old_endpoint.encode()).hexdigest()[:12],
            )
        mappings[new_endpoint] = raw_mapping
        options[CONF_MAPPINGS] = mappings
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        self.hass.config_entries.async_schedule_reload(self.entry.entry_id)

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
        self._pending_endpoint_pushes.clear()

    @callback
    def _handle_endpoint_state(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        endpoint = str(event.data.get("entity_id") or "")
        if not endpoint:
            return
        if new_state.state == DISPLAY_RECONNECT_STATE:
            # Current firmware emits this pulse only after Home Assistant has
            # subscribed to device states, then restores the actual action.
            # Schedule from both states for legacy firmware and for reconnects
            # where one of the two events is coalesced.
            self._schedule_endpoint_push(endpoint)
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
        self._schedule_endpoint_push(endpoint)

    def _schedule_endpoint_push(self, endpoint: str) -> None:
        """Schedule one bounded delivery sequence for an awake endpoint."""
        if endpoint in self._pending_endpoint_pushes:
            # One reconnect can publish the endpoint more than once while
            # ESPHome finishes registering its user-defined action. Keep one
            # bounded retry sequence per display instead of creating a task
            # storm on a noisy connection.
            return

        @callback
        def _delayed_push(_now: datetime) -> None:
            if cancel in self._unsubscribers:
                self._unsubscribers.remove(cancel)
            self._create_task(self._async_push_endpoint_with_retry(endpoint))

        # The service is normally registered before the subscribed reconnect
        # pulse arrives. Keep retries for legacy firmware, slow connections and
        # brief ESPHome API interruptions during battery wakes.
        self._pending_endpoint_pushes.add(endpoint)
        cancel: Callable[[], None] = async_call_later(self.hass, 2, _delayed_push)
        self._unsubscribers.append(cancel)

    async def _async_push_endpoint_with_retry(self, endpoint: str) -> bool:
        """Deliver one authoritative payload across ESPHome reconnect races."""
        try:
            for delay in _ENDPOINT_RETRY_DELAYS:
                if endpoint in self._sync_requests:
                    return False
                if delay:
                    await asyncio.sleep(delay)
                if endpoint in self._sync_requests:
                    return False
                if await self.async_push_endpoint(endpoint):
                    return True
            _LOGGER.debug(
                "ESPHome display %s stayed unavailable during reconnect",
                endpoint,
            )
            return False
        finally:
            self._pending_endpoint_pushes.discard(endpoint)

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._manual_refresh_requests:
            return
        self._create_task(self.async_push_all(exclude=frozenset(self._sync_requests)))

    @callback
    def _handle_weather_state(self, event: Event[EventStateChangedData]) -> None:
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

    async def async_push_all(
        self, *, exclude: frozenset[str] = frozenset()
    ) -> DisplayDeliveryResult:
        """Push current payloads to every display that is online."""
        data = getattr(self.coordinator, "data", None)
        if data is None:
            return DisplayDeliveryResult(0, 0)
        return await _async_delivery_result(
            [
                self.async_push_endpoint(endpoint)
                for endpoint in data.payloads
                if endpoint not in exclude
            ]
        )

    async def async_refresh_and_push(self) -> DisplayDeliveryResult:
        """Refresh Guesty and synchronously report the resulting deliveries."""
        self._manual_refresh_requests += 1
        try:
            await self.coordinator.async_request_refresh()
        finally:
            self._manual_refresh_requests -= 1
        if not self.coordinator.last_update_success:
            return DisplayDeliveryResult(0, 0)
        return await self.async_push_all()

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

    async def async_force_redraw_all(self) -> DisplayDeliveryResult:
        """Redraw configured displays once using cached payloads."""
        data = getattr(self.coordinator, "data", None)
        if data is None:
            return DisplayDeliveryResult(0, 0)
        return await _async_delivery_result(
            [self.async_force_redraw_endpoint(endpoint) for endpoint in data.payloads]
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
        data = getattr(self.coordinator, "data", None)
        if data is None:
            return None
        payload = data.payloads.get(endpoint_entity)
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
        listing = data.listings.get(mapping.listing_id) if mapping is not None else None
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

    async def async_clear_all(self) -> DisplayDeliveryResult:
        """Best-effort clear of every display configured for this account."""
        return await _async_delivery_result(
            [
                self.async_clear_endpoint(mapping.endpoint_entity)
                for mapping in self.coordinator.mapping_options()
            ]
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


type GuestyTerminalConfigEntry = ConfigEntry[GuestyTerminalRuntime]
