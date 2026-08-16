"""Tests for the Home Assistant configuration and options flows."""

from __future__ import annotations

import asyncio
import sys
from contextlib import contextmanager
from types import SimpleNamespace

from custom_components.guesty_terminal.config_flow import (
    GuestyTerminalConfigFlow,
    GuestyTerminalOptionsFlow,
    _validate_credentials,
)
from custom_components.guesty_terminal.const import (
    CONF_CHECKOUT_INSTRUCTIONS_FALLBACK,
    CONF_CHECKOUT_INSTRUCTIONS_LABEL,
    CONF_CHECKOUT_LABEL,
    CONF_CHECKOUT_PAGE_MESSAGE,
    CONF_CHECKOUT_PAGE_TITLE,
    CONF_CHECKOUT_START_TIME,
    CONF_CLEANER_NOTES_LABEL,
    CONF_CLEAR_AFTER_MINUTES,
    CONF_CLIENT_ID,
    CONF_DATE_TIME_FORMAT,
    CONF_DISPLAY_LANGUAGE,
    CONF_DOOR_CODE_LABEL,
    CONF_EMPTY_NO_BOOKING_TEXT,
    CONF_EMPTY_PAGE_TITLE,
    CONF_ENDPOINT_ENTITY,
    CONF_FIRMWARE_AWAKE_SECONDS,
    CONF_FIRMWARE_DEVICE_NAME,
    CONF_FIRMWARE_FRIENDLY_NAME,
    CONF_FIRMWARE_OVERWRITE,
    CONF_FIRMWARE_POWER_MODE,
    CONF_FIRMWARE_WAKE_MINUTES,
    CONF_GENERAL_NOTES_LABEL,
    CONF_LEAD_HOURS,
    CONF_LISTING_ID,
    CONF_LOGO_DATA,
    CONF_LOGO_UPLOAD,
    CONF_MAPPINGS,
    CONF_POLL_MINUTES,
    CONF_REMOVE_LOGO,
    CONF_REMOVE_MAPPING,
    CONF_SHOW_DOOR_CODE,
    CONF_SHOW_WIFI,
    CONF_SPECIAL_REQUESTS_LABEL,
    CONF_WEATHER_ENTITY,
    CONF_WELCOME_TEXT,
    CONF_WELCOME_TITLE,
    CONF_WIFI_KEY_LABEL,
    CONF_WIFI_LABEL,
    CONF_WIFI_NAME_LABEL,
    DATA_PENDING_TOKENS,
    DOMAIN,
)
from custom_components.guesty_terminal.logo import LOGO_DATA_BYTES
from custom_components.guesty_terminal.models import Listing

MODULE = sys.modules[GuestyTerminalConfigFlow.__module__]


class FakeConfigEntries:
    def __init__(self, entry=None, entries=None) -> None:
        self.entry = entry
        self.entries = entries or []

    def async_get_known_entry(self, _entry_id):
        return self.entry

    def async_entries(self, _domain):
        return self.entries


def _options_flow(entry):
    flow = GuestyTerminalOptionsFlow()
    flow.hass = SimpleNamespace(config_entries=FakeConfigEntries(entry))
    flow.handler = "entry-1"
    flow.context = {"source": "user"}
    return flow


def test_validate_credentials_caches_fresh_token(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, session, client_id, client_secret, *, token_saver):
            assert session == "session"
            assert client_id == "client"
            assert client_secret == "secret"
            self.token_saver = token_saver

        async def async_get_listings(self):
            await self.token_saver({"access_token": "token", "expires_at": 123})
            return [{"_id": "listing-1"}]

    monkeypatch.setattr(MODULE, "GuestyClient", FakeClient)
    monkeypatch.setattr(MODULE, "async_get_clientsession", lambda _hass: "session")
    hass = SimpleNamespace(data={})
    result = asyncio.run(_validate_credentials(hass, " client ", " secret "))
    assert result == [{"_id": "listing-1"}]
    assert hass.data[DOMAIN][DATA_PENDING_TOKENS]["client"]["access_token"] == "token"


def test_options_choice_helpers_use_friendly_names(monkeypatch) -> None:
    entity_entries = {
        "one": SimpleNamespace(
            entity_id="sensor.one",
            original_name="GuestyTerminal Endpoint",
            device_id="device-1",
        ),
        "two": SimpleNamespace(
            entity_id="sensor.z_guesty_terminal_endpoint",
            original_name="Other",
            device_id=None,
        ),
        "ignored": SimpleNamespace(
            entity_id="sensor.unrelated", original_name="Other", device_id=None
        ),
    }
    entity_registry = SimpleNamespace(entities=entity_entries)
    device_registry = SimpleNamespace(
        async_get=lambda device_id: SimpleNamespace(
            name_by_user="Apartment A" if device_id == "device-1" else None,
            name="Fallback",
        )
    )
    monkeypatch.setattr(MODULE.er, "async_get", lambda _hass: entity_registry)
    monkeypatch.setattr(MODULE.dr, "async_get", lambda _hass: device_registry)

    coordinator = SimpleNamespace(
        data=SimpleNamespace(
            listings={
                "b": Listing("b", "Zulu"),
                "a": Listing("a", "Alpha"),
            }
        )
    )
    entry = SimpleNamespace(
        options={}, runtime_data=SimpleNamespace(coordinator=coordinator)
    )
    flow = _options_flow(entry)

    assert [item["label"] for item in flow._endpoint_choices()] == [
        "Apartment A",
        "sensor.z_guesty_terminal_endpoint",
    ]
    assert [item["label"] for item in flow._listing_choices()] == ["Alpha", "Zulu"]

    coordinator.data = None
    assert flow._listing_choices() == []


def test_endpoint_choices_exclude_displays_owned_by_another_account(
    monkeypatch,
) -> None:
    endpoint = "sensor.shared_guesty_terminal_endpoint"
    entity_registry = SimpleNamespace(
        entities={
            "shared": SimpleNamespace(
                entity_id=endpoint,
                original_name="GuestyTerminal Endpoint",
                device_id=None,
            )
        }
    )
    monkeypatch.setattr(MODULE.er, "async_get", lambda _hass: entity_registry)
    monkeypatch.setattr(
        MODULE.dr,
        "async_get",
        lambda _hass: SimpleNamespace(async_get=lambda _device_id: None),
    )
    current = SimpleNamespace(entry_id="entry-1", options={}, runtime_data=None)
    other = SimpleNamespace(
        entry_id="entry-2",
        options={CONF_MAPPINGS: {endpoint: {CONF_LISTING_ID: "other-listing"}}},
    )
    flow = GuestyTerminalOptionsFlow()
    flow.hass = SimpleNamespace(
        config_entries=FakeConfigEntries(current, [current, other])
    )
    flow.handler = current.entry_id
    flow.context = {"source": "user"}

    assert flow._endpoint_choices() == []


def test_endpoint_choices_reject_legacy_duplicate_from_later_account(
    monkeypatch,
) -> None:
    endpoint = "sensor.shared_guesty_terminal_endpoint"
    entity_registry = SimpleNamespace(
        entities={
            "shared": SimpleNamespace(
                entity_id=endpoint,
                original_name="GuestyTerminal Endpoint",
                device_id=None,
            )
        }
    )
    monkeypatch.setattr(MODULE.er, "async_get", lambda _hass: entity_registry)
    monkeypatch.setattr(
        MODULE.dr,
        "async_get",
        lambda _hass: SimpleNamespace(async_get=lambda _device_id: None),
    )
    mapping = {CONF_MAPPINGS: {endpoint: {CONF_LISTING_ID: "listing"}}}
    owner = SimpleNamespace(entry_id="entry-1", options=mapping)
    duplicate = SimpleNamespace(entry_id="entry-2", options=mapping, runtime_data=None)
    flow = GuestyTerminalOptionsFlow()
    flow.hass = SimpleNamespace(
        config_entries=FakeConfigEntries(duplicate, [owner, duplicate])
    )
    flow.handler = duplicate.entry_id
    flow.context = {"source": "user"}

    assert flow._endpoint_choices() == []


def test_options_mapping_can_add_remove_and_show_forms(monkeypatch) -> None:
    endpoint = "sensor.one_guesty_terminal_endpoint"
    coordinator = SimpleNamespace(
        data=SimpleNamespace(listings={"listing-1": Listing("listing-1", "Loft")})
    )
    cleared = []

    async def clear_endpoint(endpoint_entity):
        cleared.append(endpoint_entity)
        return True

    entry = SimpleNamespace(
        options={CONF_POLL_MINUTES: 5},
        runtime_data=SimpleNamespace(
            coordinator=coordinator,
            async_clear_endpoint=clear_endpoint,
        ),
    )
    flow = _options_flow(entry)
    monkeypatch.setattr(
        flow,
        "_endpoint_choices",
        lambda: [{"value": endpoint, "label": "Display"}],
    )

    form = asyncio.run(flow.async_step_mapping())
    assert form["type"] == "form"
    assert form["step_id"] == "mapping"

    language_form = asyncio.run(
        flow.async_step_mapping({CONF_ENDPOINT_ENTITY: endpoint})
    )
    assert language_form["step_id"] == "mapping_language"
    assert language_form["data_schema"]({})[CONF_DISPLAY_LANGUAGE] == "en"
    details_form = asyncio.run(
        flow.async_step_mapping_language({CONF_DISPLAY_LANGUAGE: "en"})
    )
    assert details_form["type"] == "form"
    assert details_form["step_id"] == "mapping_details"

    created = asyncio.run(
        flow.async_step_mapping_details(
            {
                CONF_LISTING_ID: "listing-1",
                CONF_WELCOME_TITLE: "Hallo {first_name}",
                CONF_WELCOME_TEXT: "Willkommen",
                CONF_DOOR_CODE_LABEL: "DOOR CODE",
                CONF_WIFI_LABEL: "WIFI",
                CONF_WIFI_NAME_LABEL: "Name:",
                CONF_WIFI_KEY_LABEL: "Key:",
                CONF_CHECKOUT_LABEL: "Check-out:",
                CONF_DATE_TIME_FORMAT: "eu",
                CONF_LEAD_HOURS: 6,
                CONF_CLEAR_AFTER_MINUTES: 30,
                CONF_SHOW_DOOR_CODE: True,
                CONF_SHOW_WIFI: False,
                CONF_WEATHER_ENTITY: "weather.home",
                CONF_REMOVE_MAPPING: False,
            }
        )
    )
    assert created["data"][CONF_MAPPINGS][endpoint][CONF_LISTING_ID] == "listing-1"
    assert created["data"][CONF_MAPPINGS][endpoint][CONF_DISPLAY_LANGUAGE] == "en"
    assert (
        created["data"][CONF_MAPPINGS][endpoint][CONF_WEATHER_ENTITY] == "weather.home"
    )

    entry.options = created["data"]
    checkout_selection = asyncio.run(flow.async_step_checkout())
    assert checkout_selection["step_id"] == "checkout"
    checkout_form = asyncio.run(
        flow.async_step_checkout({CONF_ENDPOINT_ENTITY: endpoint})
    )
    checkout_defaults = checkout_form["data_schema"]({})
    assert checkout_form["step_id"] == "checkout_details"
    assert checkout_form["description_placeholders"] == {
        "display_language": "EN",
        "date_time_format": "EU",
    }
    assert checkout_defaults[CONF_CHECKOUT_START_TIME] == "05:00:00"
    assert checkout_defaults[CONF_CHECKOUT_PAGE_TITLE] == (
        "Today is check-out, {first_name}"
    )
    checkout_saved = asyncio.run(
        flow.async_step_checkout_details(
            {
                CONF_CHECKOUT_START_TIME: "06:30:00",
                CONF_CHECKOUT_PAGE_TITLE: "Time to leave, {first_name}",
                CONF_CHECKOUT_PAGE_MESSAGE: "Thanks for staying.",
                CONF_CHECKOUT_INSTRUCTIONS_LABEL: "LEAVE BY {check_out_time}",
                CONF_CHECKOUT_INSTRUCTIONS_FALLBACK: "Close all windows.",
            }
        )
    )
    saved_mapping = checkout_saved["data"][CONF_MAPPINGS][endpoint]
    assert saved_mapping[CONF_LISTING_ID] == "listing-1"
    assert saved_mapping[CONF_CHECKOUT_START_TIME] == "06:30:00"
    assert saved_mapping[CONF_CHECKOUT_PAGE_TITLE] == ("Time to leave, {first_name}")

    entry.options = checkout_saved["data"]
    empty_selection = asyncio.run(flow.async_step_empty_room())
    assert empty_selection["step_id"] == "empty_room"
    empty_form = asyncio.run(
        flow.async_step_empty_room({CONF_ENDPOINT_ENTITY: endpoint})
    )
    empty_defaults = empty_form["data_schema"]({})
    assert empty_form["step_id"] == "empty_room_details"
    assert empty_form["description_placeholders"] == {
        "display_language": "EN",
        "date_time_format": "EU",
    }
    assert empty_defaults[CONF_EMPTY_PAGE_TITLE] == "NEXT BOOKING"
    empty_saved = asyncio.run(
        flow.async_step_empty_room_details(
            {
                CONF_EMPTY_PAGE_TITLE: "UPCOMING STAY",
                CONF_EMPTY_NO_BOOKING_TEXT: "No stay planned",
                CONF_GENERAL_NOTES_LABEL: "GENERAL",
                CONF_CLEANER_NOTES_LABEL: "CLEANING",
                CONF_SPECIAL_REQUESTS_LABEL: "REQUESTS",
            }
        )
    )
    saved_mapping = empty_saved["data"][CONF_MAPPINGS][endpoint]
    assert saved_mapping[CONF_EMPTY_PAGE_TITLE] == "UPCOMING STAY"
    assert saved_mapping[CONF_CLEANER_NOTES_LABEL] == "CLEANING"

    entry.options = empty_saved["data"]
    reopened_empty = asyncio.run(flow.async_step_empty_room_details())
    reopened_defaults = reopened_empty["data_schema"]({})
    assert reopened_defaults[CONF_EMPTY_PAGE_TITLE] == "UPCOMING STAY"
    assert reopened_defaults[CONF_EMPTY_NO_BOOKING_TEXT] == "No stay planned"
    assert reopened_defaults[CONF_SPECIAL_REQUESTS_LABEL] == "REQUESTS"

    removed = asyncio.run(
        flow.async_step_mapping_details(
            {
                CONF_REMOVE_MAPPING: True,
            }
        )
    )
    assert removed["data"][CONF_MAPPINGS] == {}
    assert cleared == [endpoint]

    general_form = asyncio.run(flow.async_step_general())
    assert general_form["type"] == "form"
    general = asyncio.run(flow.async_step_general({CONF_POLL_MINUTES: 10}))
    assert general["data"][CONF_POLL_MINUTES] == 10
    menu = asyncio.run(flow.async_step_init())
    assert menu["menu_options"] == {
        "mapping": "Assign a listing to a display",
        "checkout": "Configure checkout page",
        "empty_room": "Configure empty-room page",
        "firmware": "Create E1001 firmware",
        "general": "General settings",
    }

    flow.hass.config = SimpleNamespace(language="de-DE")
    menu = asyncio.run(flow.async_step_init())
    assert menu["menu_options"]["firmware"] == "E1001-Firmware erstellen"
    assert menu["menu_options"]["checkout"] == "Checkout-Seite konfigurieren"
    assert menu["menu_options"]["empty_room"] == (
        "Seite für leeres Zimmer konfigurieren"
    )


def test_options_mapping_remembers_each_configured_display(monkeypatch) -> None:
    endpoints = (
        "sensor.one_guesty_terminal_endpoint",
        "sensor.two_guesty_terminal_endpoint",
    )
    coordinator = SimpleNamespace(
        data=SimpleNamespace(
            listings={
                "listing-1": Listing("listing-1", "Loft"),
                "listing-2": Listing("listing-2", "Garden"),
            }
        )
    )
    entry = SimpleNamespace(
        options={
            CONF_MAPPINGS: {
                endpoints[0]: {
                    CONF_LISTING_ID: "listing-1",
                    CONF_WELCOME_TITLE: "Hallo {first_name}",
                    CONF_WELCOME_TEXT: "Willkommen im Loft",
                    CONF_DATE_TIME_FORMAT: "eu",
                    CONF_LEAD_HOURS: 2,
                    CONF_CLEAR_AFTER_MINUTES: 35,
                    CONF_SHOW_DOOR_CODE: True,
                    CONF_SHOW_WIFI: False,
                    CONF_WEATHER_ENTITY: "weather.loft",
                },
                endpoints[1]: {
                    CONF_LISTING_ID: "listing-2",
                    CONF_WELCOME_TITLE: "Moin {first_name}",
                    CONF_WELCOME_TEXT: "Willkommen im Garten",
                    CONF_DATE_TIME_FORMAT: "us",
                    CONF_LEAD_HOURS: 4,
                    CONF_CLEAR_AFTER_MINUTES: 45,
                    CONF_SHOW_DOOR_CODE: False,
                    CONF_SHOW_WIFI: True,
                    CONF_WEATHER_ENTITY: "weather.garden",
                },
            }
        },
        runtime_data=SimpleNamespace(coordinator=coordinator),
    )
    flow = _options_flow(entry)
    monkeypatch.setattr(
        flow,
        "_endpoint_choices",
        lambda: [
            {"value": endpoints[0], "label": "Display Loft"},
            {"value": endpoints[1], "label": "Display Garten"},
        ],
    )

    selection = asyncio.run(flow.async_step_mapping())
    assert selection["data_schema"]({})[CONF_ENDPOINT_ENTITY] == endpoints[0]

    first_language = asyncio.run(
        flow.async_step_mapping({CONF_ENDPOINT_ENTITY: endpoints[0]})
    )
    assert first_language["data_schema"]({})[CONF_DISPLAY_LANGUAGE] == "de"
    first_form = asyncio.run(
        flow.async_step_mapping_language({CONF_DISPLAY_LANGUAGE: "de"})
    )
    first = first_form["data_schema"]({})
    assert first[CONF_LISTING_ID] == "listing-1"
    assert first[CONF_WELCOME_TITLE] == "Hallo {first_name}"
    assert first[CONF_WELCOME_TEXT] == "Willkommen im Loft"
    assert first[CONF_DATE_TIME_FORMAT] == "eu"
    assert first[CONF_LEAD_HOURS] == 2
    assert first[CONF_CLEAR_AFTER_MINUTES] == 35
    assert first[CONF_SHOW_DOOR_CODE] is True
    assert first[CONF_SHOW_WIFI] is False
    assert first[CONF_WEATHER_ENTITY] == "weather.loft"

    second_language = asyncio.run(
        flow.async_step_mapping({CONF_ENDPOINT_ENTITY: endpoints[1]})
    )
    assert second_language["data_schema"]({})[CONF_DISPLAY_LANGUAGE] == "de"
    second_form = asyncio.run(
        flow.async_step_mapping_language({CONF_DISPLAY_LANGUAGE: "de"})
    )
    second = second_form["data_schema"]({})
    assert second[CONF_LISTING_ID] == "listing-2"
    assert second[CONF_WELCOME_TITLE] == "Moin {first_name}"
    assert second[CONF_WELCOME_TEXT] == "Willkommen im Garten"
    assert second[CONF_DATE_TIME_FORMAT] == "us"
    assert second[CONF_LEAD_HOURS] == 4
    assert second[CONF_CLEAR_AFTER_MINUTES] == 45
    assert second[CONF_SHOW_DOOR_CODE] is False
    assert second[CONF_SHOW_WIFI] is True
    assert second[CONF_WEATHER_ENTITY] == "weather.garden"


def test_display_language_uses_system_default_and_refills_copy_on_change(
    monkeypatch,
) -> None:
    endpoint = "sensor.one_guesty_terminal_endpoint"
    coordinator = SimpleNamespace(
        data=SimpleNamespace(listings={"listing-1": Listing("listing-1", "Loft")})
    )
    entry = SimpleNamespace(
        options={
            CONF_MAPPINGS: {
                endpoint: {
                    CONF_LISTING_ID: "listing-1",
                    CONF_DISPLAY_LANGUAGE: "en",
                    CONF_WELCOME_TITLE: "Our custom welcome",
                    CONF_WELCOME_TEXT: "Our saved copy",
                    CONF_DOOR_CODE_LABEL: "ACCESS",
                    CONF_WIFI_LABEL: "NETWORK",
                    CONF_WIFI_NAME_LABEL: "SSID:",
                    CONF_WIFI_KEY_LABEL: "Password:",
                    CONF_CHECKOUT_LABEL: "Departure:",
                }
            }
        },
        runtime_data=SimpleNamespace(coordinator=coordinator),
    )
    flow = _options_flow(entry)
    flow.hass.config = SimpleNamespace(language="es-ES")
    monkeypatch.setattr(
        flow,
        "_endpoint_choices",
        lambda: [{"value": endpoint, "label": "Display"}],
    )

    language_form = asyncio.run(
        flow.async_step_mapping({CONF_ENDPOINT_ENTITY: endpoint})
    )
    assert language_form["data_schema"]({})[CONF_DISPLAY_LANGUAGE] == "en"

    unchanged = asyncio.run(
        flow.async_step_mapping_language({CONF_DISPLAY_LANGUAGE: "en"})
    )["data_schema"]({})
    assert unchanged[CONF_WELCOME_TITLE] == "Our custom welcome"
    assert unchanged[CONF_DOOR_CODE_LABEL] == "ACCESS"

    flow._mapping_endpoint = endpoint
    changed = asyncio.run(
        flow.async_step_mapping_language({CONF_DISPLAY_LANGUAGE: "fr"})
    )["data_schema"]({})
    assert changed[CONF_WELCOME_TITLE] == "Bienvenue, {first_name} !"
    assert changed[CONF_DOOR_CODE_LABEL] == "CODE PORTE"
    assert changed[CONF_WIFI_NAME_LABEL] == "Nom :"
    assert changed[CONF_CHECKOUT_LABEL] == "Départ :"

    new_entry = SimpleNamespace(
        options={}, runtime_data=SimpleNamespace(coordinator=coordinator)
    )
    new_flow = _options_flow(new_entry)
    new_flow.hass.config = SimpleNamespace(language="es-ES")
    new_flow._mapping_endpoint = endpoint
    default_language = asyncio.run(new_flow.async_step_mapping_language())
    assert default_language["data_schema"]({})[CONF_DISPLAY_LANGUAGE] == "es"


def test_general_options_upload_and_remove_one_global_logo(
    monkeypatch, tmp_path
) -> None:
    entry = SimpleNamespace(options={CONF_POLL_MINUTES: 5}, runtime_data=None)
    flow = _options_flow(entry)
    flow.hass.config = SimpleNamespace(language="de-DE")
    uploaded_path = tmp_path / "logo.png"
    uploaded_path.touch()
    logo_data = "ff" * LOGO_DATA_BYTES

    @contextmanager
    def uploaded_file(_hass, file_id):
        assert file_id == "00000000-0000-0000-0000-000000000001"
        yield uploaded_path

    async def executor_job(function, *args):
        return function(*args)

    monkeypatch.setattr(MODULE, "process_uploaded_file", uploaded_file)
    monkeypatch.setattr(MODULE, "encode_logo", lambda path: logo_data)
    flow.hass.async_add_executor_job = executor_job

    uploaded = asyncio.run(
        flow.async_step_general(
            {
                CONF_POLL_MINUTES: 7,
                CONF_LOGO_UPLOAD: "00000000-0000-0000-0000-000000000001",
                CONF_REMOVE_LOGO: False,
            }
        )
    )
    assert uploaded["data"][CONF_POLL_MINUTES] == 7
    assert uploaded["data"][CONF_LOGO_DATA] == logo_data

    entry.options = uploaded["data"]
    form = asyncio.run(flow.async_step_general())
    assert form["description_placeholders"]["logo_status"] == "vorhanden"

    removed = asyncio.run(
        flow.async_step_general(
            {
                CONF_POLL_MINUTES: 7,
                CONF_REMOVE_LOGO: True,
            }
        )
    )
    assert CONF_LOGO_DATA not in removed["data"]


def test_options_firmware_writes_esphome_config(tmp_path) -> None:
    entry = SimpleNamespace(options={}, runtime_data=None)
    flow = _options_flow(entry)
    flow.hass.config = SimpleNamespace(path=lambda name: str(tmp_path / name))

    async def executor_job(function, *args):
        return function(*args)

    flow.hass.async_add_executor_job = executor_job
    form = asyncio.run(flow.async_step_firmware())
    assert form["type"] == "form"
    assert form["step_id"] == "firmware"

    result = asyncio.run(
        flow.async_step_firmware(
            {
                CONF_FIRMWARE_DEVICE_NAME: "guestyterminal-lobby",
                CONF_FIRMWARE_FRIENDLY_NAME: "GuestyTerminal Lobby",
                CONF_FIRMWARE_POWER_MODE: "auto",
                CONF_FIRMWARE_WAKE_MINUTES: 30,
                CONF_FIRMWARE_AWAKE_SECONDS: 90,
                CONF_FIRMWARE_OVERWRITE: False,
            }
        )
    )
    assert result["type"] == "abort"
    assert result["reason"] == "firmware_created"
    generated = tmp_path / "esphome" / "guestyterminal-lobby.yaml"
    assert generated.exists()
    assert "battery_sleep_duration: 30min" in generated.read_text(encoding="utf-8")


def test_options_mapping_aborts_without_displays_or_listings(monkeypatch) -> None:
    coordinator = SimpleNamespace(data=SimpleNamespace(listings={}))
    entry = SimpleNamespace(
        options={}, runtime_data=SimpleNamespace(coordinator=coordinator)
    )
    flow = _options_flow(entry)
    monkeypatch.setattr(flow, "_endpoint_choices", lambda: [])
    assert asyncio.run(flow.async_step_mapping())["reason"] == "no_displays"

    monkeypatch.setattr(
        flow, "_endpoint_choices", lambda: [{"value": "x", "label": "x"}]
    )
    assert asyncio.run(flow.async_step_mapping())["reason"] == "no_listings"

    flow._checkout_endpoint = "missing"
    assert asyncio.run(flow.async_step_checkout())["reason"] == "no_mappings"
    assert asyncio.run(flow.async_step_checkout_details())["reason"] == "no_mappings"
    flow._empty_endpoint = "missing"
    assert asyncio.run(flow.async_step_empty_room())["reason"] == "no_mappings"
    assert asyncio.run(flow.async_step_empty_room_details())["reason"] == (
        "no_mappings"
    )


def test_user_flow_shows_form_and_aborts_duplicate(monkeypatch) -> None:
    flow = GuestyTerminalConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {"source": "user"}
    monkeypatch.setattr(flow, "_async_current_entries", lambda: [])
    form = asyncio.run(flow.async_step_user())
    assert form["type"] == "form"

    monkeypatch.setattr(
        flow,
        "_async_current_entries",
        lambda: [SimpleNamespace(unique_id="existing")],
    )
    duplicate = asyncio.run(
        flow.async_step_user(
            {CONF_CLIENT_ID: " existing ", "client_secret": " secret "}
        )
    )
    assert duplicate["reason"] == "already_configured"
    assert isinstance(
        GuestyTerminalConfigFlow.async_get_options_flow(None), GuestyTerminalOptionsFlow
    )


def test_reauth_updates_unique_id_and_rejects_another_existing_account(
    monkeypatch,
) -> None:
    flow = GuestyTerminalConfigFlow()
    flow.hass = SimpleNamespace()
    flow.context = {"source": "reauth"}
    flow._reauth_entry = SimpleNamespace(
        entry_id="entry-1",
        unique_id="old-client",
        data={CONF_CLIENT_ID: "old-client"},
    )

    async def validate(_hass, _client_id, _client_secret):
        return []

    monkeypatch.setattr(MODULE, "_validate_credentials", validate)
    monkeypatch.setattr(
        flow,
        "_async_current_entries",
        lambda: [SimpleNamespace(entry_id="entry-2", unique_id="other-client")],
    )
    duplicate = asyncio.run(
        flow.async_step_reauth_confirm(
            {CONF_CLIENT_ID: " other-client ", "client_secret": " secret "}
        )
    )
    assert duplicate["reason"] == "already_configured"

    captured = {}

    def update(entry, **kwargs):
        captured.update(kwargs)
        return {"type": "abort", "reason": "reauth_successful"}

    monkeypatch.setattr(flow, "async_update_reload_and_abort", update)
    result = asyncio.run(
        flow.async_step_reauth_confirm(
            {CONF_CLIENT_ID: " new-client ", "client_secret": " new-secret "}
        )
    )
    assert result["reason"] == "reauth_successful"
    assert captured["unique_id"] == "new-client"
    assert captured["data_updates"] == {
        CONF_CLIENT_ID: "new-client",
        "client_secret": "new-secret",
    }
