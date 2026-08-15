"""Tests for pushing payloads to awake ESPHome displays."""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from types import SimpleNamespace

from custom_components.guesty_terminal.const import CONF_MAPPINGS
from custom_components.guesty_terminal.models import (
    DisplayPayload,
    Listing,
    MappingOptions,
)
from custom_components.guesty_terminal.runtime import (
    GuestyTerminalRuntime,
    async_clear_configured_displays,
)

ENDPOINT = "sensor.guestyterminal_display_1_guesty_terminal_endpoint"
ACTION = "guestyterminal_display_1_guesty_terminal_update_display"


class FakeServices:
    def __init__(self, *, available=True, failure: Exception | None = None) -> None:
        self.available = available
        self.failure = failure
        self.calls = []

    def has_service(self, domain, action):
        return self.available and domain == "esphome" and action == ACTION

    async def async_call(self, domain, action, data, *, blocking):
        self.calls.append((domain, action, data, blocking))
        if self.failure:
            raise self.failure


class FakeStates:
    def __init__(self, state=None) -> None:
        self.state = state

    def get(self, _entity_id):
        return self.state


class FakeHass:
    def __init__(self, state=None, *, available=True, failure=None) -> None:
        self.states = FakeStates(state)
        self.services = FakeServices(available=available, failure=failure)
        self.tasks = []

    def async_create_task(self, coroutine):
        self.tasks.append(coroutine)
        coroutine.close()


class FakeCoordinator:
    def __init__(self, data=None, mappings=None) -> None:
        self.data = data
        self._mappings = mappings or []
        self.listener = None

    def mapping_options(self):
        return self._mappings

    def async_add_listener(self, listener):
        self.listener = listener
        return lambda: None


def _listing() -> Listing:
    return Listing("listing-1", "Loft", wifi_name="WiFi", wifi_password="secret")


def _runtime(*, state=ACTION, payload=None, available=True, failure=None):
    listing = _listing()
    mapping = MappingOptions(ENDPOINT, listing.listing_id)
    data = SimpleNamespace(
        payloads={ENDPOINT: payload or DisplayPayload.idle(listing)},
        listings={listing.listing_id: listing},
    )
    coordinator = FakeCoordinator(data, [mapping])
    hass = FakeHass(
        None if state is None else SimpleNamespace(state=state),
        available=available,
        failure=failure,
    )
    runtime = GuestyTerminalRuntime(hass, SimpleNamespace(), None, coordinator)
    return runtime, hass, coordinator


def test_pushes_valid_payload_and_push_all() -> None:
    runtime, hass, _coordinator = _runtime()
    asyncio.run(runtime.async_push_endpoint(ENDPOINT))
    assert hass.services.calls[0][:2] == ("esphome", ACTION)
    assert hass.services.calls[0][2]["mode"] == "idle"

    hass.services.calls.clear()
    asyncio.run(runtime.async_push_all())
    assert len(hass.services.calls) == 1


def test_push_ignores_missing_offline_and_invalid_endpoints() -> None:
    runtime, hass, coordinator = _runtime()
    coordinator.data = None
    asyncio.run(runtime.async_push_all())
    asyncio.run(runtime.async_push_endpoint(ENDPOINT))
    assert hass.services.calls == []

    coordinator.data = SimpleNamespace(payloads={}, listings={})
    asyncio.run(runtime.async_push_endpoint(ENDPOINT))

    for state in (None, "unknown", "unavailable", "unsafe.action", "other_action"):
        candidate, candidate_hass, _ = _runtime(state=state)
        asyncio.run(candidate.async_push_endpoint(ENDPOINT))
        assert candidate_hass.services.calls == []

    unavailable, unavailable_hass, _ = _runtime(available=False)
    asyncio.run(unavailable.async_push_endpoint(ENDPOINT))
    assert unavailable_hass.services.calls == []


def test_expired_payload_is_replaced_with_privacy_safe_idle_screen() -> None:
    expired = DisplayPayload(
        mode="welcome",
        property_name="LOFT",
        welcome_title="Hallo Anna",
        welcome_text="Willkommen",
        door_code="4827",
        wifi_name="WiFi",
        wifi_password="secret",
        checkout_label="gestern",
        valid_until_epoch=int(datetime(2020, 1, 1, tzinfo=UTC).timestamp()),
    )
    runtime, hass, _ = _runtime(payload=expired)
    asyncio.run(runtime.async_push_endpoint(ENDPOINT))
    sent = hass.services.calls[0][2]
    assert sent["mode"] == "idle"
    assert sent["door_code"] == ""
    assert sent["wifi_password"] == ""

    runtime.coordinator._mappings = []
    hass.services.calls.clear()
    asyncio.run(runtime.async_push_endpoint(ENDPOINT))
    assert hass.services.calls[0][2]["door_code"] == ""


def test_service_errors_are_isolated() -> None:
    runtime, hass, _ = _runtime(failure=RuntimeError("disconnected"))
    asyncio.run(runtime.async_push_endpoint(ENDPOINT))
    assert len(hass.services.calls) == 1


def test_clear_endpoint_all_and_removed_entry() -> None:
    runtime, hass, _ = _runtime()
    assert asyncio.run(runtime.async_clear_endpoint(ENDPOINT))
    assert hass.services.calls[-1][2]["mode"] == "idle"
    assert hass.services.calls[-1][2]["door_code"] == ""

    hass.services.calls.clear()
    asyncio.run(runtime.async_clear_all())
    assert len(hass.services.calls) == 1

    hass.services.calls.clear()
    entry = SimpleNamespace(
        options={CONF_MAPPINGS: {ENDPOINT: {"listing_id": "listing-1"}}}
    )
    asyncio.run(async_clear_configured_displays(hass, entry))
    assert hass.services.calls[-1][2]["mode"] == "idle"

    entry.options = {CONF_MAPPINGS: []}
    asyncio.run(async_clear_configured_displays(hass, entry))


def test_start_stop_and_callbacks(monkeypatch) -> None:
    callbacks = {}
    unsubscribed = []

    def track(_hass, endpoints, callback):
        callbacks["state"] = callback
        callbacks["endpoints"] = endpoints
        return lambda: unsubscribed.append("state")

    def call_later(_hass, delay, callback):
        callbacks["later"] = callback
        callbacks["delay"] = delay

        def cancel():
            unsubscribed.append("timer")

        return cancel

    runtime_module = sys.modules[GuestyTerminalRuntime.__module__]
    monkeypatch.setattr(runtime_module, "async_track_state_change_event", track)
    monkeypatch.setattr(runtime_module, "async_call_later", call_later)

    runtime, hass, coordinator = _runtime(state=None)
    asyncio.run(runtime.async_start())
    assert callbacks["endpoints"] == [ENDPOINT]
    assert callbacks["delay"] if "delay" in callbacks else True

    callbacks["state"](SimpleNamespace(data={"new_state": None}))
    callbacks["state"](
        SimpleNamespace(data={"new_state": SimpleNamespace(state="unknown")})
    )
    callbacks["state"](
        SimpleNamespace(
            data={"new_state": SimpleNamespace(state="online"), "entity_id": ENDPOINT}
        )
    )
    assert callbacks["delay"] == 2
    callbacks["later"](datetime.now(UTC))
    assert len(hass.tasks) == 1

    coordinator.listener()
    assert len(hass.tasks) == 2
    asyncio.run(runtime.async_stop())
    assert runtime._unsubscribers == []
    assert "state" in unsubscribed


def test_start_without_mappings_only_registers_coordinator_listener() -> None:
    runtime, _hass, coordinator = _runtime()
    coordinator._mappings = []
    asyncio.run(runtime.async_start())
    assert len(runtime._unsubscribers) == 1
