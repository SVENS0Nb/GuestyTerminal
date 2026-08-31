"""Runtime orchestration between Guesty and sleeping ESPHome displays."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
from collections.abc import Callable, Coroutine
from contextlib import suppress
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
    DATA_ENDPOINT_ACTIONS,
    DISPLAY_ACTION_SUFFIX,
    DISPLAY_ACTION_V2_SUFFIX,
    DISPLAY_ACTION_V3_SUFFIX,
    DISPLAY_ACTION_V4_SUFFIX,
    DISPLAY_ACTION_V5_SUFFIX,
    DISPLAY_ACTION_V6_SUFFIX,
    DISPLAY_ACTION_V7_SUFFIX,
    DISPLAY_ACTION_V8_SUFFIX,
    DISPLAY_ACTION_V9_SUFFIX,
    DISPLAY_ACTION_V10_SUFFIX,
    DISPLAY_DELIVERY_ERROR_PREFIX,
    DISPLAY_DELIVERY_RECEIVED_PREFIX,
    DISPLAY_DELIVERY_RENDERING_PREFIX,
    DISPLAY_DELIVERY_SUCCESS_PREFIX,
    DISPLAY_DELIVERY_UNCHANGED_PREFIX,
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
_DISPLAY_ACTION_SUFFIXES = (
    DISPLAY_ACTION_SUFFIX,
    DISPLAY_ACTION_V2_SUFFIX,
    DISPLAY_ACTION_V3_SUFFIX,
    DISPLAY_ACTION_V4_SUFFIX,
    DISPLAY_ACTION_V5_SUFFIX,
    DISPLAY_ACTION_V6_SUFFIX,
    DISPLAY_ACTION_V7_SUFFIX,
    DISPLAY_ACTION_V8_SUFFIX,
    DISPLAY_ACTION_V9_SUFFIX,
    DISPLAY_ACTION_V10_SUFFIX,
)
_ENDPOINT_RETRY_DELAYS = (0.0, 1.0, 2.0, 4.0, 8.0, 8.0)
_DELIVERY_ID_PATTERN = re.compile(r"^[0-9a-f]{24}$")
_DELIVERY_RECEIPT_TIMEOUT = 5.0
_DELIVERY_COMPLETION_TIMEOUT = 135.0
_DELIVERY_READY_TIMEOUT = 5.0
_DELIVERY_ERROR_CODES = {
    "busy",
    "panel_error",
    "panel_timeout",
    "preparation_timeout",
}
_NON_RETRYABLE_PANEL_STATUSES = frozenset({"panel_error", "panel_timeout"})


def _is_display_action(state: str) -> bool:
    """Return whether a state is a supported ESPHome display action name."""
    return bool(
        _ACTION_PATTERN.fullmatch(state) and state.endswith(_DISPLAY_ACTION_SUFFIXES)
    )


def _is_transport_state(state: str) -> bool:
    """Return whether a mutable legacy endpoint state is a transport pulse."""
    if state in (DISPLAY_RECONNECT_STATE, DISPLAY_REFRESH_REQUEST_STATE):
        return True
    for prefix in (
        DISPLAY_DELIVERY_RECEIVED_PREFIX,
        DISPLAY_DELIVERY_RENDERING_PREFIX,
        DISPLAY_DELIVERY_SUCCESS_PREFIX,
        DISPLAY_DELIVERY_UNCHANGED_PREFIX,
        DISPLAY_DELIVERY_ERROR_PREFIX,
    ):
        if not state.startswith(prefix):
            continue
        delivery_id, separator, error_code = state[len(prefix) :].partition(":")
        if not _DELIVERY_ID_PATTERN.fullmatch(delivery_id):
            return False
        if prefix == DISPLAY_DELIVERY_ERROR_PREFIX:
            return bool(separator and error_code in _DELIVERY_ERROR_CODES)
        return not separator
    return False


@dataclass(slots=True)
class _DeliveryAcknowledgement:
    """Track one privacy-safe v10 delivery across endpoint state pulses."""

    received: asyncio.Event
    ready: asyncio.Event
    finished: asyncio.Future[bool]


@dataclass(frozen=True, slots=True)
class DisplayDeliveryDiagnostic:
    """Non-sensitive delivery state exposed through diagnostics."""

    status: str = "never"
    attempted_at: str | None = None
    confirmed_at: str | None = None
    failures: int = 0


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
    action: str | None = None,
    force_redraw: bool = False,
    logo_data: str = "",
    delivery_id: str = "",
) -> bool:
    """Submit one payload directly to a reachable ESPHome display."""
    endpoint_state = hass.states.get(endpoint_entity)
    if endpoint_state is None or endpoint_state.state in (
        STATE_UNKNOWN,
        STATE_UNAVAILABLE,
    ):
        return False

    resolved_action = action or str(endpoint_state.state).strip()
    if not _is_display_action(resolved_action):
        _LOGGER.warning("Ignoring an invalid ESPHome display endpoint state")
        return False
    if not hass.services.has_service("esphome", resolved_action):
        _LOGGER.debug("ESPHome action %s is not available yet", resolved_action)
        return False
    if resolved_action.endswith(DISPLAY_ACTION_V10_SUFFIX) and not delivery_id:
        delivery_id = secrets.token_hex(12)

    send_lock = lock or asyncio.Lock()
    async with send_lock:
        try:
            include_content_id = resolved_action.endswith(
                (
                    DISPLAY_ACTION_V2_SUFFIX,
                    DISPLAY_ACTION_V3_SUFFIX,
                    DISPLAY_ACTION_V4_SUFFIX,
                    DISPLAY_ACTION_V5_SUFFIX,
                    DISPLAY_ACTION_V6_SUFFIX,
                    DISPLAY_ACTION_V7_SUFFIX,
                    DISPLAY_ACTION_V8_SUFFIX,
                    DISPLAY_ACTION_V9_SUFFIX,
                    DISPLAY_ACTION_V10_SUFFIX,
                )
            )
            service_data = payload.as_service_data(
                include_content_id=include_content_id,
                include_booking_summary=resolved_action.endswith(
                    (
                        DISPLAY_ACTION_V4_SUFFIX,
                        DISPLAY_ACTION_V5_SUFFIX,
                        DISPLAY_ACTION_V6_SUFFIX,
                        DISPLAY_ACTION_V7_SUFFIX,
                        DISPLAY_ACTION_V8_SUFFIX,
                        DISPLAY_ACTION_V9_SUFFIX,
                        DISPLAY_ACTION_V10_SUFFIX,
                    )
                ),
                include_weather=resolved_action.endswith(
                    (
                        DISPLAY_ACTION_V5_SUFFIX,
                        DISPLAY_ACTION_V6_SUFFIX,
                        DISPLAY_ACTION_V7_SUFFIX,
                        DISPLAY_ACTION_V8_SUFFIX,
                        DISPLAY_ACTION_V9_SUFFIX,
                        DISPLAY_ACTION_V10_SUFFIX,
                    )
                ),
                include_labels=resolved_action.endswith(
                    (
                        DISPLAY_ACTION_V7_SUFFIX,
                        DISPLAY_ACTION_V8_SUFFIX,
                        DISPLAY_ACTION_V9_SUFFIX,
                        DISPLAY_ACTION_V10_SUFFIX,
                    )
                ),
                include_checkout_page=resolved_action.endswith(
                    (
                        DISPLAY_ACTION_V8_SUFFIX,
                        DISPLAY_ACTION_V9_SUFFIX,
                        DISPLAY_ACTION_V10_SUFFIX,
                    )
                ),
                include_empty_page=resolved_action.endswith(
                    (DISPLAY_ACTION_V9_SUFFIX, DISPLAY_ACTION_V10_SUFFIX)
                ),
                delivery_id=(
                    delivery_id
                    if resolved_action.endswith(DISPLAY_ACTION_V10_SUFFIX)
                    else ""
                ),
            )
            if resolved_action.endswith(
                (
                    DISPLAY_ACTION_V3_SUFFIX,
                    DISPLAY_ACTION_V4_SUFFIX,
                    DISPLAY_ACTION_V5_SUFFIX,
                    DISPLAY_ACTION_V6_SUFFIX,
                    DISPLAY_ACTION_V7_SUFFIX,
                    DISPLAY_ACTION_V8_SUFFIX,
                    DISPLAY_ACTION_V9_SUFFIX,
                    DISPLAY_ACTION_V10_SUFFIX,
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
            if resolved_action.endswith(
                (
                    DISPLAY_ACTION_V6_SUFFIX,
                    DISPLAY_ACTION_V7_SUFFIX,
                    DISPLAY_ACTION_V8_SUFFIX,
                    DISPLAY_ACTION_V9_SUFFIX,
                    DISPLAY_ACTION_V10_SUFFIX,
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
            v10_action = resolved_action.endswith(DISPLAY_ACTION_V10_SUFFIX)
            if v10_action and not _DELIVERY_ID_PATTERN.fullmatch(delivery_id):
                return False
            await hass.services.async_call(
                "esphome",
                resolved_action,
                service_data,
                # Wait only until Home Assistant has handed the fire-and-forget
                # action to ESPHome. This keeps service failures inside this
                # privacy-safe exception boundary; a detached service task can
                # otherwise make Home Assistant core log the complete request,
                # including guest-visible access data. Physical completion is
                # acknowledged separately through the v10 endpoint pulses.
                blocking=True,
            )
        except Exception:  # Home Assistant service errors vary by ESPHome version.
            # ESPHome exceptions can embed the complete service request. Never
            # attach their text or traceback because that request contains
            # guest-visible access data for welcome screens.
            _LOGGER.debug("Could not submit a GuestyTerminal display update")
            return False
    _LOGGER.debug(
        "Submitted GuestyTerminal display %s in %s mode",
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
    domain_data = getattr(hass, "data", {}).get(DOMAIN, {})
    action_cache = (
        domain_data.get(DATA_ENDPOINT_ACTIONS, {})
        if isinstance(domain_data, dict)
        else {}
    )
    if not isinstance(action_cache, dict):
        action_cache = {}
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
                action=action_cache.get(endpoint),
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
    _delivery_generations: dict[str, int] = field(default_factory=dict)
    _delivery_waiters: dict[tuple[str, str], _DeliveryAcknowledgement] = field(
        default_factory=dict
    )
    _delivery_status_restores: set[str] = field(default_factory=set)
    _delivery_diagnostics: dict[str, DisplayDeliveryDiagnostic] = field(
        default_factory=dict
    )
    _endpoint_actions: dict[str, str] = field(default_factory=dict)
    _tasks: set[asyncio.Future[Any]] = field(default_factory=set)
    _manual_refresh_requests: int = 0
    _stopped: bool = False

    def _attach_shared_action_cache(self) -> None:
        """Keep non-sensitive action identities across config-entry reloads."""
        domain_data = self.hass.data.setdefault(DOMAIN, {})
        shared = domain_data.setdefault(DATA_ENDPOINT_ACTIONS, {})
        if not isinstance(shared, dict):
            shared = {}
            domain_data[DATA_ENDPOINT_ACTIONS] = shared
        shared.update(self._endpoint_actions)
        self._endpoint_actions = shared

    def _remember_endpoint_action(self, endpoint: str, state: str) -> None:
        """Remember only validated action identities, never transport pulses."""
        if endpoint and _is_display_action(state):
            self._endpoint_actions[endpoint] = state

    def _resolve_endpoint_action(self, endpoint: str) -> str | None:
        """Resolve a callable action without trusting a mutable receipt state."""
        endpoint_state = self.hass.states.get(endpoint)
        if endpoint_state is None or endpoint_state.state in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        ):
            return None

        state = str(endpoint_state.state).strip()
        if _is_display_action(state):
            self._remember_endpoint_action(endpoint, state)
            action = state
        elif _is_transport_state(state):
            action = self._endpoint_actions.get(endpoint, "")
        else:
            return None
        if not _is_display_action(action):
            return None
        if not self.hass.services.has_service("esphome", action):
            _LOGGER.debug("ESPHome action %s is not available yet", action)
            return None
        return action

    def delivery_diagnostic(self, endpoint: str) -> DisplayDeliveryDiagnostic:
        """Return a privacy-safe snapshot of the last delivery attempt."""
        return self._delivery_diagnostics.get(endpoint, DisplayDeliveryDiagnostic())

    def _record_delivery(
        self,
        endpoint: str,
        status: str,
        *,
        attempted: bool = False,
        confirmed: bool = False,
        failed: bool = False,
    ) -> None:
        """Record bounded neutral delivery metadata without payload values."""
        previous = self.delivery_diagnostic(endpoint)
        now = datetime.now(UTC).isoformat(timespec="seconds")
        self._delivery_diagnostics[endpoint] = DisplayDeliveryDiagnostic(
            status=status,
            attempted_at=now if attempted else previous.attempted_at,
            confirmed_at=now if confirmed else previous.confirmed_at,
            failures=previous.failures + int(failed),
        )

    def _endpoint_has_delivery_waiter(self, endpoint: str) -> bool:
        """Return whether a v10 call is still awaiting device completion."""
        return any(key[0] == endpoint for key in self._delivery_waiters)

    def _handle_delivery_state(self, endpoint: str, state: str) -> bool:
        """Resolve one v10 delivery pulse without exposing its opaque token."""
        prefixes = (
            (DISPLAY_DELIVERY_RECEIVED_PREFIX, "received"),
            (DISPLAY_DELIVERY_RENDERING_PREFIX, "rendering"),
            (DISPLAY_DELIVERY_SUCCESS_PREFIX, "success"),
            (DISPLAY_DELIVERY_UNCHANGED_PREFIX, "unchanged"),
            (DISPLAY_DELIVERY_ERROR_PREFIX, "error"),
        )
        matched = next(
            (
                (prefix, status)
                for prefix, status in prefixes
                if state.startswith(prefix)
            ),
            None,
        )
        if matched is None:
            return False
        prefix, status = matched
        remainder = state[len(prefix) :]
        delivery_id, separator, error_code = remainder.partition(":")
        if not _DELIVERY_ID_PATTERN.fullmatch(delivery_id):
            return True
        acknowledgement = self._delivery_waiters.get((endpoint, delivery_id))
        self._delivery_status_restores.add(endpoint)
        if acknowledgement is None:
            return True
        acknowledgement.received.set()
        if status in ("success", "unchanged"):
            self._record_delivery(endpoint, status, confirmed=True)
            if not acknowledgement.finished.done():
                acknowledgement.finished.set_result(True)
        elif status == "error":
            safe_code = (
                error_code
                if separator and error_code in _DELIVERY_ERROR_CODES
                else "device_error"
            )
            self._record_delivery(endpoint, safe_code, failed=True)
            if not acknowledgement.finished.done():
                acknowledgement.finished.set_result(False)
        else:
            self._record_delivery(endpoint, status)
        return True

    def _create_task(self, coroutine: Coroutine[Any, Any, Any], *, name: str) -> None:
        """Create a cancellable task that never delays Home Assistant startup."""
        if self._stopped:
            coroutine.close()
            return
        # Physical E-paper delivery can legitimately take longer than Home
        # Assistant's bootstrap timeout. These jobs are tracked locally for a
        # clean unload, but they must not be registered as setup tasks or Home
        # Assistant will report a blocked startup while waiting for the panel.
        task = self.hass.async_create_background_task(coroutine, name)
        if isinstance(task, asyncio.Future):
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def async_start(self) -> None:
        """Start endpoint and coordinator listeners."""
        self._stopped = False
        self._attach_shared_action_cache()
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
            for endpoint in endpoints:
                endpoint_state = self.hass.states.get(endpoint)
                self._remember_endpoint_action(
                    endpoint, str(getattr(endpoint_state, "state", "")).strip()
                )
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
        # Setup must not wait for a physical E-paper acknowledgement. Start one
        # tracked best-effort delivery per known endpoint; sleeping displays
        # will request a fresh bounded sequence through their reconnect pulse.
        data = getattr(self.coordinator, "data", None)
        if data is not None:
            for endpoint in data.payloads:
                self._create_task(
                    self.async_push_endpoint(endpoint),
                    name="guesty_terminal_initial_display_delivery",
                )

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
        remembered_action = self._endpoint_actions.pop(old_endpoint, "")
        if remembered_action:
            self._endpoint_actions[new_endpoint] = remembered_action
        self.hass.config_entries.async_update_entry(self.entry, options=options)
        self.hass.config_entries.async_schedule_reload(self.entry.entry_id)

    async def async_stop(self) -> None:
        """Stop all registered listeners."""
        self._stopped = True
        for acknowledgement in self._delivery_waiters.values():
            acknowledgement.received.set()
            acknowledgement.ready.set()
            if not acknowledgement.finished.done():
                acknowledgement.finished.set_result(False)
        self._delivery_waiters.clear()
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
        self._delivery_status_restores.clear()

    @callback
    def _handle_endpoint_state(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data.get("new_state")
        endpoint = str(event.data.get("entity_id") or "")
        if new_state is None or not endpoint:
            return
        if new_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            # A battery device can publish its final success and enter deep
            # sleep before restoring the callable action state. Once physical
            # completion is known, unavailability is therefore also a valid
            # terminal-ready signal and must not add the normal five-second
            # restore wait to every battery wake.
            for (waiting_endpoint, _delivery_id), acknowledgement in tuple(
                self._delivery_waiters.items()
            ):
                if waiting_endpoint == endpoint and acknowledgement.finished.done():
                    acknowledgement.ready.set()
                    self._delivery_status_restores.discard(endpoint)
            return
        state = str(new_state.state)
        if self._handle_delivery_state(endpoint, state):
            return
        if _is_display_action(state):
            self._remember_endpoint_action(endpoint, state)
            has_waiter = False
            for (waiting_endpoint, _delivery_id), acknowledgement in tuple(
                self._delivery_waiters.items()
            ):
                if waiting_endpoint == endpoint:
                    has_waiter = True
                    acknowledgement.ready.set()
            if endpoint in self._delivery_status_restores:
                # v10 restores the normal endpoint action after its final
                # acknowledgement. That restore is not a reconnect and must
                # not submit the same payload again.
                self._delivery_status_restores.discard(endpoint)
                return
            if has_waiter:
                # An action-state replay during a v10 refresh is discovery,
                # not a request to submit a second credential-bearing job.
                return
        if state == DISPLAY_RECONNECT_STATE:
            # Current firmware emits this pulse only after Home Assistant has
            # subscribed to device states, then restores the actual action.
            # Schedule from both states for legacy firmware and for reconnects
            # where one of the two events is coalesced.
            if not self._endpoint_has_delivery_waiter(endpoint):
                self._schedule_endpoint_push(endpoint)
            return
        if state == DISPLAY_REFRESH_REQUEST_STATE:
            if endpoint in self._sync_requests:
                return
            self._sync_requests.add(endpoint)
            self._create_task(
                self._async_sync_and_force_redraw_endpoint(endpoint),
                name="guesty_terminal_requested_display_refresh",
            )
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
            self._create_task(
                self._async_push_endpoint_with_retry(endpoint),
                name="guesty_terminal_reconnect_display_delivery",
            )

        # The service is normally registered before the subscribed reconnect
        # pulse arrives. Keep retries for legacy firmware, slow connections and
        # brief ESPHome API interruptions during battery wakes.
        self._pending_endpoint_pushes.add(endpoint)
        cancel: Callable[[], None] = async_call_later(self.hass, 2, _delayed_push)
        self._unsubscribers.append(cancel)

    async def _async_push_endpoint_with_retry(self, endpoint: str) -> bool:
        """Deliver one authoritative payload across ESPHome reconnect races."""
        return await self._async_deliver_endpoint_with_retry(endpoint)

    async def _async_deliver_endpoint_with_retry(
        self,
        endpoint: str,
        *,
        force_redraw: bool = False,
        owns_sync_request: bool = False,
    ) -> bool:
        """Retry one acknowledged delivery without retaining stale payloads."""
        try:
            for delay in _ENDPOINT_RETRY_DELAYS:
                if endpoint in self._sync_requests and not owns_sync_request:
                    return False
                if delay:
                    await asyncio.sleep(delay)
                if endpoint in self._sync_requests and not owns_sync_request:
                    return False
                delivered = (
                    await self.async_force_redraw_endpoint(endpoint)
                    if force_redraw
                    else await self.async_push_endpoint(endpoint)
                )
                if delivered:
                    return True
                if (
                    self.delivery_diagnostic(endpoint).status
                    in _NON_RETRYABLE_PANEL_STATUSES
                ):
                    # The device accepted and rendered this payload, then the
                    # physical controller failed. Repeating the same image in
                    # this reconnect sequence only flashes the panel again;
                    # a changed payload, explicit refresh or device restart
                    # remains able to start a fresh attempt.
                    _LOGGER.warning(
                        "ESPHome display %s reported a physical panel error; "
                        "the unchanged payload will not be retried immediately",
                        endpoint,
                    )
                    return False
            _LOGGER.warning(
                "ESPHome display %s did not confirm the display update",
                endpoint,
            )
            return False
        finally:
            self._pending_endpoint_pushes.discard(endpoint)

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._manual_refresh_requests:
            return
        self._create_task(
            self.async_push_all(exclude=frozenset(self._sync_requests)),
            name="guesty_terminal_coordinator_display_delivery",
        )

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
            action = self._resolve_endpoint_action(endpoint)
            if action is None or not action.endswith(
                (
                    DISPLAY_ACTION_V6_SUFFIX,
                    DISPLAY_ACTION_V7_SUFFIX,
                    DISPLAY_ACTION_V8_SUFFIX,
                    DISPLAY_ACTION_V9_SUFFIX,
                    DISPLAY_ACTION_V10_SUFFIX,
                )
            ):
                # Older firmware cannot perform the hybrid weather refresh.
                # It will still receive live weather on its next normal or
                # explicitly forced payload without adding full panel flashes
                # for every weather-entity state change.
                continue
            if endpoint not in self._sync_requests:
                self._create_task(
                    self._async_push_endpoint_with_retry(endpoint),
                    name="guesty_terminal_weather_display_delivery",
                )

    async def async_push_all(
        self, *, exclude: frozenset[str] = frozenset()
    ) -> DisplayDeliveryResult:
        """Push current payloads to every display that is online."""
        data = getattr(self.coordinator, "data", None)
        if data is None:
            return DisplayDeliveryResult(0, 0)
        return await _async_delivery_result(
            [
                self._async_deliver_endpoint_with_retry(endpoint)
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
                await self._async_deliver_endpoint_with_retry(
                    endpoint, force_redraw=True, owns_sync_request=True
                )
            elif self._endpoint_has_stale_listing(endpoint):
                _LOGGER.warning(
                    "Guesty refresh was incomplete; not clearing display %s",
                    endpoint,
                )
            else:
                await self.async_clear_endpoint(endpoint)
        finally:
            self._sync_requests.discard(endpoint)

    def _endpoint_has_stale_listing(self, endpoint_entity: str) -> bool:
        """Return whether a partial refresh left this endpoint unverified."""
        data = getattr(self.coordinator, "data", None)
        stale_listing_ids: frozenset[str] = getattr(
            data, "stale_listing_ids", frozenset()
        )
        return any(
            mapping.endpoint_entity == endpoint_entity
            and mapping.listing_id in stale_listing_ids
            for mapping in self.coordinator.mapping_options()
        )

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
            [
                self._async_deliver_endpoint_with_retry(endpoint, force_redraw=True)
                for endpoint in data.payloads
            ]
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
        """Send only the latest payload and require a v10 device acknowledgement."""
        generation = self._delivery_generations.get(endpoint_entity, 0) + 1
        self._delivery_generations[endpoint_entity] = generation
        lock = self._locks.setdefault(endpoint_entity, asyncio.Lock())
        async with lock:
            if self._delivery_generations.get(endpoint_entity) != generation:
                # A newer payload now owns this endpoint. Coalescing is a
                # successful outcome for the obsolete caller because the
                # newest state will be delivered by its own waiting task.
                return True

            action = self._resolve_endpoint_action(endpoint_entity)
            if action is None:
                self._record_delivery(
                    endpoint_entity, "unavailable", attempted=True, failed=True
                )
                return False
            if not action.endswith(DISPLAY_ACTION_V10_SUFFIX):
                accepted = await async_send_display_payload(
                    self.hass,
                    endpoint_entity,
                    payload,
                    action=action,
                    force_redraw=force_redraw,
                    logo_data=valid_logo_data(self.entry.options.get(CONF_LOGO_DATA)),
                )
                self._record_delivery(
                    endpoint_entity,
                    "legacy_submitted" if accepted else "unavailable",
                    attempted=True,
                    failed=not accepted,
                )
                return accepted

            delivery_id = secrets.token_hex(12)
            loop = asyncio.get_running_loop()
            acknowledgement = _DeliveryAcknowledgement(
                received=asyncio.Event(),
                ready=asyncio.Event(),
                finished=loop.create_future(),
            )
            waiter_key = (endpoint_entity, delivery_id)
            self._delivery_waiters[waiter_key] = acknowledgement
            self._record_delivery(endpoint_entity, "submitting", attempted=True)
            try:
                submitted = await async_send_display_payload(
                    self.hass,
                    endpoint_entity,
                    payload,
                    action=action,
                    force_redraw=force_redraw,
                    logo_data=valid_logo_data(self.entry.options.get(CONF_LOGO_DATA)),
                    delivery_id=delivery_id,
                )
                if not submitted:
                    self._record_delivery(endpoint_entity, "unavailable", failed=True)
                    return False

                try:
                    await asyncio.wait_for(
                        acknowledgement.received.wait(),
                        timeout=_DELIVERY_RECEIPT_TIMEOUT,
                    )
                except TimeoutError:
                    self._record_delivery(endpoint_entity, "not_received", failed=True)
                    return False

                try:
                    successful = await asyncio.wait_for(
                        asyncio.shield(acknowledgement.finished),
                        timeout=_DELIVERY_COMPLETION_TIMEOUT,
                    )
                except TimeoutError:
                    self._record_delivery(
                        endpoint_entity, "completion_timeout", failed=True
                    )
                    return False

                # The final status is published before the endpoint restores
                # its callable action name. Wait briefly so a following
                # coalesced payload cannot mistake that status for an action.
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        acknowledgement.ready.wait(),
                        timeout=_DELIVERY_READY_TIMEOUT,
                    )
                return successful
            finally:
                self._delivery_waiters.pop(waiter_key, None)
                if not acknowledgement.finished.done():
                    acknowledgement.finished.cancel()


type GuestyTerminalConfigEntry = ConfigEntry[GuestyTerminalRuntime]
