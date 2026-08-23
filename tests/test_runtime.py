"""Tests for pushing payloads to awake ESPHome displays."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

from custom_components.guesty_terminal.const import (
    CONF_LOGO_DATA,
    CONF_MAPPINGS,
    DISPLAY_RECONNECT_STATE,
    DISPLAY_REFRESH_REQUEST_STATE,
)
from custom_components.guesty_terminal.logo import LOGO_DATA_BYTES
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
SECOND_ENDPOINT = "sensor.guestyterminal_display_2_guesty_terminal_endpoint"
ACTION = "guestyterminal_display_1_guesty_terminal_update_display"
ACTION_V2 = "guestyterminal_display_1_guesty_terminal_update_display_v2"
ACTION_V3 = "guestyterminal_display_1_guesty_terminal_update_display_v3"
ACTION_V4 = "guestyterminal_display_1_guesty_terminal_update_display_v4"
ACTION_V5 = "guestyterminal_display_1_guesty_terminal_update_display_v5"
ACTION_V6 = "guestyterminal_display_1_guesty_terminal_update_display_v6"
ACTION_V7 = "guestyterminal_display_1_guesty_terminal_update_display_v7"
ACTION_V8 = "guestyterminal_display_1_guesty_terminal_update_display_v8"
ACTION_V9 = "guestyterminal_display_1_guesty_terminal_update_display_v9"
SECOND_ACTION_V9 = "guestyterminal_display_2_guesty_terminal_update_display_v9"


class FakeServices:
    def __init__(self, *, available=True, failure: Exception | None = None) -> None:
        self.available = available
        self.failure = failure
        self.calls = []

    def has_service(self, domain, action):
        return (
            self.available
            and domain == "esphome"
            and action
            in (
                ACTION,
                ACTION_V2,
                ACTION_V3,
                ACTION_V4,
                ACTION_V5,
                ACTION_V6,
                ACTION_V7,
                ACTION_V8,
                ACTION_V9,
                SECOND_ACTION_V9,
            )
        )

    async def async_call(self, domain, action, data, *, blocking):
        self.calls.append((domain, action, data, blocking))
        if self.failure:
            raise self.failure


class FakeStates:
    def __init__(self, state=None, states=None) -> None:
        self.state = state
        self.states = states or {}

    def get(self, entity_id):
        return self.states.get(entity_id, self.state)


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
        self.refreshes = 0
        self.cache_invalidations = 0
        self.last_update_success = True

    def mapping_options(self):
        return self._mappings

    def async_add_listener(self, listener):
        self.listener = listener
        return lambda: None

    def payload_with_current_weather(self, _endpoint, payload):
        return payload

    async def async_request_refresh(self):
        self.refreshes += 1

    def invalidate_guest_data_caches(self):
        self.cache_invalidations += 1


def _listing() -> Listing:
    return Listing("listing-1", "Loft", wifi_name="WiFi", wifi_password="secret")


def _runtime(*, state=ACTION, payload=None, available=True, failure=None, options=None):
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
    runtime = GuestyTerminalRuntime(
        hass, SimpleNamespace(options=options or {}), None, coordinator
    )
    return runtime, hass, coordinator


def test_pushes_valid_payload_and_push_all() -> None:
    runtime, hass, _coordinator = _runtime()
    asyncio.run(runtime.async_push_endpoint(ENDPOINT))
    assert hass.services.calls[0][:2] == ("esphome", ACTION)
    assert hass.services.calls[0][2]["mode"] == "idle"

    hass.services.calls.clear()
    asyncio.run(runtime.async_push_all())
    assert len(hass.services.calls) == 1


def test_v2_action_receives_stable_content_id() -> None:
    runtime, hass, _coordinator = _runtime(state=ACTION_V2)
    asyncio.run(runtime.async_push_endpoint(ENDPOINT))
    sent = hass.services.calls[0][2]
    assert sent["content_id"] == runtime.coordinator.data.payloads[ENDPOINT].content_id
    assert len(sent["content_id"]) == 24


def test_v3_action_receives_one_global_logo_and_logo_aware_content_id() -> None:
    logo_data = "ff" * LOGO_DATA_BYTES
    welcome = DisplayPayload(
        mode="welcome",
        property_name="LOFT",
        welcome_title="Hallo Anna",
        welcome_text="Willkommen",
        door_code="4827",
        wifi_name="WiFi",
        wifi_password="secret",
        checkout_label="morgen",
        valid_until_epoch=int(datetime(2100, 1, 1, tzinfo=UTC).timestamp()),
    )
    runtime, hass, _coordinator = _runtime(
        state=ACTION_V3,
        payload=welcome,
        options={CONF_LOGO_DATA: logo_data},
    )
    asyncio.run(runtime.async_push_endpoint(ENDPOINT))
    sent = hass.services.calls[0][2]
    assert sent["logo_data"] == logo_data
    assert len(sent["content_id"]) == 24
    assert sent["content_id"] != welcome.content_id

    runtime.coordinator.data.payloads[ENDPOINT] = DisplayPayload.idle(_listing())
    hass.services.calls.clear()
    asyncio.run(runtime.async_push_endpoint(ENDPOINT))
    assert hass.services.calls[0][2]["logo_data"] == ""


def test_v4_action_receives_confirmed_booking_summary() -> None:
    welcome = DisplayPayload(
        mode="welcome",
        property_name="LOFT",
        welcome_title="Hallo Anna",
        welcome_text="Willkommen",
        door_code="4827",
        wifi_name="WiFi",
        wifi_password="secret",
        checkout_label="morgen",
        valid_until_epoch=int(datetime(2100, 1, 1, tzinfo=UTC).timestamp()),
        booking_summary="Anna Beispiel · 14.08.2026 15:00 – 17.08.2026 11:00",
    )
    runtime, hass, _coordinator = _runtime(state=ACTION_V4, payload=welcome)

    asyncio.run(runtime.async_push_endpoint(ENDPOINT))

    sent = hass.services.calls[0][2]
    assert sent["booking_summary"] == welcome.booking_summary
    assert len(sent["content_id"]) == 24
    assert sent["logo_data"] == ""


def test_v5_action_receives_weather_and_booking_data() -> None:
    welcome = DisplayPayload(
        mode="welcome",
        property_name="LOFT",
        welcome_title="Hallo Anna",
        welcome_text="Willkommen",
        door_code="4827",
        wifi_name="WiFi",
        wifi_password="secret",
        checkout_label="morgen",
        valid_until_epoch=int(datetime(2100, 1, 1, tzinfo=UTC).timestamp()),
        weather_condition="partlycloudy",
        weather_temperature="18 °C",
        booking_summary="Anna Beispiel · 14.08.2026 15:00 – 17.08.2026 11:00",
    )
    runtime, hass, _coordinator = _runtime(state=ACTION_V5, payload=welcome)

    asyncio.run(runtime.async_push_endpoint(ENDPOINT))

    sent = hass.services.calls[0][2]
    assert sent["weather_condition"] == "partlycloudy"
    assert sent["weather_temperature"] == "18 °C"
    assert sent["booking_summary"] == welcome.booking_summary
    assert len(sent["content_id"]) == 24
    assert sent["logo_data"] == ""


def test_v6_action_receives_hybrid_refresh_fingerprints() -> None:
    welcome = DisplayPayload(
        mode="welcome",
        property_name="LOFT",
        welcome_title="Hallo Anna",
        welcome_text="Willkommen",
        door_code="4827",
        wifi_name="WiFi",
        wifi_password="secret",
        checkout_label="morgen",
        valid_until_epoch=int(datetime(2100, 1, 1, tzinfo=UTC).timestamp()),
        weather_condition="sunny",
        weather_temperature="19 °C",
        booking_summary="Anna · 14.08.2026 – 17.08.2026",
    )
    runtime, hass, _coordinator = _runtime(state=ACTION_V6, payload=welcome)

    asyncio.run(runtime.async_push_endpoint(ENDPOINT))

    sent = hass.services.calls[0][2]
    assert sent["weather_condition"] == "sunny"
    assert sent["weather_temperature"] == "19 °C"
    assert len(sent["content_id"]) == 24
    assert len(sent["base_content_id"]) == 24
    assert sent["content_id"] != sent["base_content_id"]
    assert sent["force_redraw"] is False


def test_v6_force_redraw_keeps_real_fingerprints() -> None:
    runtime, hass, _coordinator = _runtime(state=ACTION_V6)

    assert asyncio.run(runtime.async_force_redraw_endpoint(ENDPOINT))

    sent = hass.services.calls[0][2]
    assert len(sent["content_id"]) == 24
    assert len(sent["base_content_id"]) == 24
    assert sent["force_redraw"] is True


def test_v7_action_receives_custom_display_labels() -> None:
    welcome = DisplayPayload(
        mode="welcome",
        property_name="LOFT",
        welcome_title="Bienvenue, Anna !",
        welcome_text="Bienvenue",
        door_code="4827",
        wifi_name="WiFi",
        wifi_password="secret",
        checkout_label="Départ : 17/08 - 11:00",
        valid_until_epoch=int(datetime(2100, 1, 1, tzinfo=UTC).timestamp()),
        door_code_label="ACCÈS",
        wifi_label="RÉSEAU",
        wifi_name_label="Nom :",
        wifi_key_label="Clé :",
        idle_title="Bienvenue",
        idle_text="Le logement est prêt pour le prochain séjour.",
        no_active_booking_label="Aucune réservation active",
        weather_condition="sunny",
        weather_temperature="19 °C",
    )
    runtime, hass, _coordinator = _runtime(state=ACTION_V7, payload=welcome)

    asyncio.run(runtime.async_push_endpoint(ENDPOINT))

    sent = hass.services.calls[0][2]
    assert sent["door_code_label"] == "ACCÈS"
    assert sent["wifi_label"] == "RÉSEAU"
    assert sent["wifi_name_label"] == "Nom :"
    assert sent["wifi_key_label"] == "Clé :"
    assert sent["idle_title"] == "Bienvenue"
    assert sent["idle_text"] == "Le logement est prêt pour le prochain séjour."
    assert sent["no_active_booking_label"] == "Aucune réservation active"
    assert len(sent["base_content_id"]) == 24
    assert sent["force_redraw"] is False
    assert "checkout_instructions" not in sent


def test_v8_action_receives_checkout_page_and_global_logo() -> None:
    logo_data = "aa" * LOGO_DATA_BYTES
    checkout = DisplayPayload(
        mode="checkout",
        property_name="LOFT",
        welcome_title="Today is check-out, Anna",
        welcome_text="Thank you for staying with us.",
        door_code="",
        wifi_name="",
        wifi_password="",
        checkout_label="08/17/2026 · 11:00 AM",
        valid_until_epoch=int(datetime(2100, 1, 1, tzinfo=UTC).timestamp()),
        checkout_instructions_title="CHECK-OUT BY 11:00 AM",
        checkout_instructions="Close all windows and return the key.",
        weather_condition="sunny",
        weather_temperature="19 °C",
    )
    runtime, hass, _coordinator = _runtime(
        state=ACTION_V8,
        payload=checkout,
        options={CONF_LOGO_DATA: logo_data},
    )

    asyncio.run(runtime.async_push_endpoint(ENDPOINT))

    sent = hass.services.calls[0][2]
    assert sent["checkout_instructions_title"] == "CHECK-OUT BY 11:00 AM"
    assert sent["checkout_instructions"] == ("Close all windows and return the key.")
    assert sent["logo_data"] == logo_data
    assert len(sent["base_content_id"]) == 24


def test_v9_action_receives_empty_room_page_without_global_logo() -> None:
    logo_data = "aa" * LOGO_DATA_BYTES
    empty_room = DisplayPayload(
        mode="empty",
        property_name="LOFT",
        welcome_title="NEXT BOOKING",
        welcome_text="No upcoming booking",
        door_code="",
        wifi_name="",
        wifi_password="",
        checkout_label="",
        valid_until_epoch=int(datetime(2100, 1, 1, tzinfo=UTC).timestamp()),
        next_booking_title="NEXT BOOKING",
        next_booking_guest="Mia",
        next_booking_period="09/10/2099, 4:00 PM – 09/13/2099, 10:00 AM",
        general_notes_label="GENERAL NOTES",
        general_notes="Arriving with a dog",
        cleaner_notes_label="FOR CLEANING",
        cleaner_notes="Prepare a dog bowl",
        special_requests_label="SPECIAL REQUESTS",
        special_requests="Allergy-friendly pillow",
        weather_condition="cloudy",
        weather_temperature="18 °C",
        booking_summary="Mia · 09/10/2099 – 09/13/2099",
    )
    runtime, hass, _coordinator = _runtime(
        state=ACTION_V9,
        payload=empty_room,
        options={CONF_LOGO_DATA: logo_data},
    )

    asyncio.run(runtime.async_push_endpoint(ENDPOINT))

    sent = hass.services.calls[0][2]
    assert sent["next_booking_title"] == "NEXT BOOKING"
    assert sent["next_booking_guest"] == "Mia"
    assert sent["general_notes"] == "Arriving with a dog"
    assert sent["cleaner_notes"] == "Prepare a dog bowl"
    assert sent["special_requests"] == "Allergy-friendly pillow"
    assert sent["weather_condition"] == "cloudy"
    assert sent["logo_data"] == ""
    assert len(sent["content_id"]) == 24
    assert len(sent["base_content_id"]) == 24


def test_v8_action_stays_compatible_without_empty_room_fields() -> None:
    runtime, hass, _coordinator = _runtime(state=ACTION_V8)

    asyncio.run(runtime.async_push_endpoint(ENDPOINT))

    assert "next_booking_title" not in hass.services.calls[0][2]
    assert "general_notes" not in hass.services.calls[0][2]


def test_v3_push_all_uses_the_same_global_logo_for_every_display() -> None:
    logo_data = "aa" * LOGO_DATA_BYTES
    welcome = DisplayPayload(
        mode="welcome",
        property_name="LOFT",
        welcome_title="Hallo",
        welcome_text="Willkommen",
        door_code="",
        wifi_name="",
        wifi_password="",
        checkout_label="morgen",
        valid_until_epoch=int(datetime(2100, 1, 1, tzinfo=UTC).timestamp()),
    )
    runtime, hass, coordinator = _runtime(
        state=ACTION_V3,
        payload=welcome,
        options={CONF_LOGO_DATA: logo_data},
    )
    coordinator.data.payloads["sensor.second_guesty_terminal_endpoint"] = welcome

    asyncio.run(runtime.async_push_all())

    assert len(hass.services.calls) == 2
    assert {call[2]["logo_data"] for call in hass.services.calls} == {logo_data}


def test_push_all_routes_each_payload_to_its_own_display_action() -> None:
    first_listing = Listing("listing-1", "Loft One")
    second_listing = Listing("listing-2", "Loft Two")
    first_payload = DisplayPayload.idle(first_listing)
    second_payload = DisplayPayload.idle(second_listing)
    runtime, hass, coordinator = _runtime(state=None, payload=first_payload)
    coordinator.data.payloads[SECOND_ENDPOINT] = second_payload
    coordinator.data.listings[second_listing.listing_id] = second_listing
    coordinator._mappings.append(
        MappingOptions(SECOND_ENDPOINT, second_listing.listing_id)
    )
    hass.states.states = {
        ENDPOINT: SimpleNamespace(state=ACTION_V9),
        SECOND_ENDPOINT: SimpleNamespace(state=SECOND_ACTION_V9),
    }

    asyncio.run(runtime.async_push_all())

    sent_by_action = {
        action: data["property_name"]
        for _domain, action, data, _blocking in hass.services.calls
    }
    assert sent_by_action == {
        ACTION_V9: "LOFT ONE",
        SECOND_ACTION_V9: "LOFT TWO",
    }


def test_force_redraw_uses_empty_v2_content_id() -> None:
    runtime, hass, _coordinator = _runtime(state=ACTION_V2)
    assert asyncio.run(runtime.async_force_redraw_endpoint(ENDPOINT))
    assert hass.services.calls[0][2]["content_id"] == ""

    hass.services.calls.clear()
    asyncio.run(runtime.async_force_redraw_all())
    assert hass.services.calls[0][2]["content_id"] == ""

    runtime.coordinator.data = None
    assert not asyncio.run(runtime.async_force_redraw_endpoint(ENDPOINT))
    asyncio.run(runtime.async_force_redraw_all())


def test_force_redraw_keeps_legacy_action_compatible() -> None:
    runtime, hass, _coordinator = _runtime(state=ACTION)
    assert asyncio.run(runtime.async_force_redraw_endpoint(ENDPOINT))
    assert "content_id" not in hass.services.calls[0][2]


def test_force_redraw_never_restores_expired_credentials() -> None:
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
    runtime, hass, _coordinator = _runtime(state=ACTION_V2, payload=expired)
    assert asyncio.run(runtime.async_force_redraw_endpoint(ENDPOINT))
    sent = hass.services.calls[0][2]
    assert sent["mode"] == "idle"
    assert sent["door_code"] == ""
    assert sent["wifi_password"] == ""
    assert sent["content_id"] == ""


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


def test_expired_empty_room_page_does_not_resend_guest_notes() -> None:
    expired = DisplayPayload(
        mode="empty",
        property_name="LOFT",
        welcome_title="NEXT BOOKING",
        welcome_text="No upcoming booking",
        door_code="",
        wifi_name="",
        wifi_password="",
        checkout_label="",
        valid_until_epoch=int(datetime(2020, 1, 1, tzinfo=UTC).timestamp()),
        next_booking_title="NEXT BOOKING",
        next_booking_guest="Mia",
        next_booking_period="09/10/2099 – 09/13/2099",
        special_requests_label="SPECIAL REQUESTS",
        special_requests="Private reservation note",
    )
    runtime, hass, _ = _runtime(state=ACTION_V9, payload=expired)

    asyncio.run(runtime.async_push_endpoint(ENDPOINT))

    sent = hass.services.calls[0][2]
    assert sent["mode"] == "idle"
    assert sent["next_booking_guest"] == ""
    assert sent["next_booking_period"] == ""
    assert sent["special_requests"] == ""


def test_service_errors_are_isolated() -> None:
    runtime, hass, _ = _runtime(failure=RuntimeError("disconnected"))
    asyncio.run(runtime.async_push_endpoint(ENDPOINT))
    assert len(hass.services.calls) == 1


def test_endpoint_entity_rename_migrates_mapping_and_schedules_reload() -> None:
    runtime, hass, _ = _runtime(
        options={CONF_MAPPINGS: {ENDPOINT: {"listing_id": "listing-1"}}}
    )
    runtime.entry.entry_id = "entry-1"
    updates = []
    reloads = []

    class ConfigEntries:
        def async_entries(self, _domain):
            return [runtime.entry]

        def async_update_entry(self, entry, *, options):
            entry.options = options
            updates.append(options)

        def async_schedule_reload(self, entry_id):
            reloads.append(entry_id)

    hass.config_entries = ConfigEntries()
    renamed = "sensor.renamed_guesty_terminal_endpoint"

    runtime._handle_entity_registry_update(
        SimpleNamespace(
            data={
                "action": "update",
                "old_entity_id": ENDPOINT,
                "entity_id": renamed,
            }
        )
    )

    assert ENDPOINT not in runtime.entry.options[CONF_MAPPINGS]
    migrated = runtime.entry.options[CONF_MAPPINGS][renamed]
    assert migrated["listing_id"] == "listing-1"
    assert migrated["endpoint_id"]
    assert updates
    assert reloads == ["entry-1"]


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


def test_removed_duplicate_entry_never_clears_another_accounts_display() -> None:
    unique_endpoint = "sensor.unique_guesty_terminal_endpoint"
    runtime, hass, _ = _runtime()
    del runtime
    entry = SimpleNamespace(
        entry_id="entry-removed",
        options={
            CONF_MAPPINGS: {
                ENDPOINT: {"listing_id": "listing-1"},
                unique_endpoint: {"listing_id": "listing-2"},
            }
        },
    )
    other = SimpleNamespace(
        entry_id="entry-owner",
        options={CONF_MAPPINGS: {ENDPOINT: {"listing_id": "listing-3"}}},
    )
    hass.config_entries = SimpleNamespace(async_entries=lambda _domain: [entry, other])

    asyncio.run(async_clear_configured_displays(hass, entry))

    assert len(hass.services.calls) == 1
    assert hass.services.calls[0][2]["mode"] == "idle"


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
    assert callbacks.get("delay", True)

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
    assert ENDPOINT in runtime._pending_endpoint_pushes

    coordinator.listener()
    assert len(hass.tasks) == 2
    asyncio.run(runtime.async_stop())
    assert runtime._unsubscribers == []
    assert "state" in unsubscribed
    assert runtime._pending_endpoint_pushes == set()


def test_reconnect_push_retries_until_esphome_action_is_registered(
    monkeypatch,
) -> None:
    runtime, _hass, _coordinator = _runtime(state=ACTION_V9)
    attempts = 0
    delays = []

    async def push(_runtime, _endpoint):
        nonlocal attempts
        attempts += 1
        return attempts == 3

    async def no_wait(delay):
        delays.append(delay)

    monkeypatch.setattr(GuestyTerminalRuntime, "async_push_endpoint", push)
    monkeypatch.setattr(asyncio, "sleep", no_wait)
    runtime._pending_endpoint_pushes.add(ENDPOINT)

    assert asyncio.run(runtime._async_push_endpoint_with_retry(ENDPOINT))
    assert attempts == 3
    assert delays == [1.0, 2.0]
    assert ENDPOINT not in runtime._pending_endpoint_pushes


def test_reconnect_push_spans_slow_esphome_action_registration(monkeypatch) -> None:
    runtime, _hass, _coordinator = _runtime(state=ACTION_V9)
    attempts = 0
    delays = []

    async def push(_runtime, _endpoint):
        nonlocal attempts
        attempts += 1
        return attempts == 6

    async def no_wait(delay):
        delays.append(delay)

    monkeypatch.setattr(GuestyTerminalRuntime, "async_push_endpoint", push)
    monkeypatch.setattr(asyncio, "sleep", no_wait)
    runtime._pending_endpoint_pushes.add(ENDPOINT)

    assert asyncio.run(runtime._async_push_endpoint_with_retry(ENDPOINT))
    assert attempts == 6
    assert delays == [1.0, 2.0, 4.0, 8.0, 8.0]
    assert ENDPOINT not in runtime._pending_endpoint_pushes


def test_reconnect_push_stops_when_forced_sync_takes_ownership(monkeypatch) -> None:
    runtime, _hass, _coordinator = _runtime(state=ACTION_V9)
    attempts = 0

    async def push(_runtime, _endpoint):
        nonlocal attempts
        attempts += 1
        return True

    monkeypatch.setattr(GuestyTerminalRuntime, "async_push_endpoint", push)
    runtime._pending_endpoint_pushes.add(ENDPOINT)
    runtime._sync_requests.add(ENDPOINT)

    assert not asyncio.run(runtime._async_push_endpoint_with_retry(ENDPOINT))
    assert attempts == 0
    assert ENDPOINT not in runtime._pending_endpoint_pushes


def test_reconnect_retry_yields_to_sync_requested_during_backoff(monkeypatch) -> None:
    runtime, _hass, _coordinator = _runtime(state=ACTION_V9)
    attempts = 0

    async def push(_runtime, _endpoint):
        nonlocal attempts
        attempts += 1
        return False

    async def request_sync(_delay):
        runtime._sync_requests.add(ENDPOINT)

    monkeypatch.setattr(GuestyTerminalRuntime, "async_push_endpoint", push)
    monkeypatch.setattr(asyncio, "sleep", request_sync)
    runtime._pending_endpoint_pushes.add(ENDPOINT)

    assert not asyncio.run(runtime._async_push_endpoint_with_retry(ENDPOINT))
    assert attempts == 1
    assert ENDPOINT not in runtime._pending_endpoint_pushes


def test_device_refresh_request_synchronizes_then_forces_one_redraw(
    monkeypatch,
) -> None:
    runtime, hass, coordinator = _runtime(state=ACTION_V9)

    async def no_wait(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    runtime._sync_requests.add(ENDPOINT)
    asyncio.run(runtime._async_sync_and_force_redraw_endpoint(ENDPOINT))

    assert coordinator.cache_invalidations == 1
    assert coordinator.refreshes == 1
    assert len(hass.services.calls) == 1
    assert hass.services.calls[0][2]["force_redraw"] is True
    assert ENDPOINT not in runtime._sync_requests


def test_device_refresh_does_not_redraw_stale_data_after_failed_sync(
    monkeypatch,
) -> None:
    runtime, hass, coordinator = _runtime(state=ACTION_V9)
    coordinator.last_update_success = False

    async def no_wait(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    runtime._sync_requests.add(ENDPOINT)
    asyncio.run(runtime._async_sync_and_force_redraw_endpoint(ENDPOINT))

    assert hass.services.calls == []
    assert ENDPOINT not in runtime._sync_requests


def test_device_refresh_clears_when_authoritative_payload_disappeared(
    monkeypatch,
) -> None:
    runtime, hass, coordinator = _runtime(state=ACTION_V9)
    coordinator.data.payloads = {}

    async def no_wait(_delay):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    runtime._sync_requests.add(ENDPOINT)
    asyncio.run(runtime._async_sync_and_force_redraw_endpoint(ENDPOINT))

    assert hass.services.calls[0][2]["mode"] == "idle"
    assert hass.services.calls[0][2]["force_redraw"] is False


def test_stop_cancels_runtime_owned_tasks() -> None:
    runtime, hass, _coordinator = _runtime()
    created = []

    def create_task(coroutine):
        task = asyncio.create_task(coroutine)
        created.append(task)
        return task

    hass.async_create_task = create_task

    async def exercise():
        started = asyncio.Event()

        async def wait_forever():
            started.set()
            await asyncio.Event().wait()

        runtime._create_task(wait_forever())
        await started.wait()
        await runtime.async_stop()

    asyncio.run(exercise())

    assert created[0].cancelled()
    assert runtime._tasks == set()


def test_device_refresh_pulse_is_deduplicated_and_suppresses_restore_event() -> None:
    runtime, hass, _coordinator = _runtime(state=ACTION_V9)
    request = SimpleNamespace(
        data={
            "new_state": SimpleNamespace(state=DISPLAY_REFRESH_REQUEST_STATE),
            "entity_id": ENDPOINT,
        }
    )

    runtime._handle_endpoint_state(request)
    runtime._handle_endpoint_state(request)
    runtime._handle_endpoint_state(
        SimpleNamespace(
            data={"new_state": SimpleNamespace(state=ACTION_V9), "entity_id": ENDPOINT}
        )
    )

    assert ENDPOINT in runtime._sync_requests
    assert len(hass.tasks) == 1


def test_reconnect_discovery_pulse_schedules_one_deduplicated_retry(
    monkeypatch,
) -> None:
    callbacks = {}

    def call_later(_hass, delay, callback):
        callbacks["delay"] = delay
        callbacks["later"] = callback
        return lambda: None

    runtime_module = sys.modules[GuestyTerminalRuntime.__module__]
    monkeypatch.setattr(runtime_module, "async_call_later", call_later)
    runtime, hass, _coordinator = _runtime(state=ACTION_V9)

    pulse = SimpleNamespace(
        data={
            "new_state": SimpleNamespace(state=DISPLAY_RECONNECT_STATE),
            "entity_id": ENDPOINT,
        }
    )
    runtime._handle_endpoint_state(pulse)
    runtime._handle_endpoint_state(pulse)

    assert hass.tasks == []
    assert callbacks["delay"] == 2
    assert ENDPOINT in runtime._pending_endpoint_pushes
    assert len(runtime._unsubscribers) == 1


def test_start_without_mappings_only_registers_coordinator_listener() -> None:
    runtime, _hass, coordinator = _runtime()
    coordinator._mappings = []
    asyncio.run(runtime.async_start())
    assert len(runtime._unsubscribers) == 1


def test_weather_state_change_pushes_only_matching_displays(monkeypatch) -> None:
    tracked = []

    def track(_hass, entities, callback):
        tracked.append((entities, callback))
        return lambda: None

    runtime_module = sys.modules[GuestyTerminalRuntime.__module__]
    monkeypatch.setattr(runtime_module, "async_track_state_change_event", track)

    runtime, hass, coordinator = _runtime(state=ACTION_V7)
    coordinator._mappings = [
        MappingOptions(
            ENDPOINT,
            "listing-1",
            weather_entity="weather.home",
        ),
        MappingOptions(
            "sensor.other_guesty_terminal_endpoint",
            "listing-2",
            weather_entity="weather.other",
        ),
    ]

    asyncio.run(runtime.async_start())

    weather_callback = next(
        callback
        for entities, callback in tracked
        if entities == ["weather.home", "weather.other"]
    )
    previous_tasks = len(hass.tasks)
    weather_callback(SimpleNamespace(data={"entity_id": "weather.home"}))
    assert len(hass.tasks) == previous_tasks + 1

    hass.states.state = SimpleNamespace(state=ACTION_V5)
    previous_tasks = len(hass.tasks)
    weather_callback(SimpleNamespace(data={"entity_id": "weather.home"}))
    assert len(hass.tasks) == previous_tasks


def test_force_redraw_uses_live_weather_overlay() -> None:
    welcome = DisplayPayload(
        mode="welcome",
        property_name="LOFT",
        welcome_title="Hallo Anna",
        welcome_text="Willkommen",
        door_code="4827",
        wifi_name="WiFi",
        wifi_password="secret",
        checkout_label="morgen",
        valid_until_epoch=int(datetime(2100, 1, 1, tzinfo=UTC).timestamp()),
    )
    runtime, hass, coordinator = _runtime(state=ACTION_V7, payload=welcome)

    def overlay(_endpoint, payload):
        return replace(
            payload,
            weather_condition="sunny",
            weather_temperature="23 °C",
        )

    coordinator.payload_with_current_weather = overlay

    assert asyncio.run(runtime.async_force_redraw_endpoint(ENDPOINT))
    sent = hass.services.calls[0][2]
    assert sent["weather_condition"] == "sunny"
    assert sent["weather_temperature"] == "23 °C"
