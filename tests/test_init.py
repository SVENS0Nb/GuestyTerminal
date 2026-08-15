"""Tests for Home Assistant setup, migration, unload, and removal."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import custom_components.guesty_terminal as integration
from custom_components.guesty_terminal.const import (
    CONF_CLEAR_AFTER_MINUTES,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_LEAD_HOURS,
    CONF_MAPPINGS,
    CONF_POLL_MINUTES,
    DATA_PENDING_TOKENS,
    DOMAIN,
    SERVICE_FORCE_REDRAW,
    SERVICE_REFRESH,
)
from custom_components.guesty_terminal.runtime import GuestyTerminalRuntime


class FakeServices:
    def __init__(self) -> None:
        self.registered = {}

    def has_service(self, domain, action):
        return (domain, action) in self.registered

    def async_register(self, domain, action, handler):
        self.registered[(domain, action)] = handler


class FakeConfigEntries:
    def __init__(self, *, unload_result=True) -> None:
        self.forwarded = []
        self.unloaded = []
        self.updated = []
        self.unload_result = unload_result

    async def async_forward_entry_setups(self, entry, platforms):
        self.forwarded.append((entry, platforms))

    async def async_unload_platforms(self, entry, platforms):
        self.unloaded.append((entry, platforms))
        return self.unload_result

    def async_update_entry(self, entry, **changes):
        self.updated.append((entry, changes))
        entry.options = changes.get("options", entry.options)
        entry.version = changes.get("version", entry.version)


class FakeStore:
    stored = {"access_token": "stored"}
    instances = []

    def __init__(self, hass, version, key, *, private):
        self.hass = hass
        self.version = version
        self.key = key
        self.private = private
        self.saved = []
        self.removed = False
        self.__class__.instances.append(self)

    async def async_load(self):
        return self.stored

    async def async_save(self, data):
        self.saved.append(data)

    async def async_remove(self):
        self.removed = True


def _entry(*, version=2, options=None):
    return SimpleNamespace(
        entry_id="entry-1",
        version=version,
        data={CONF_CLIENT_ID: "client", CONF_CLIENT_SECRET: "secret"},
        options=options or {},
        runtime_data=None,
    )


def test_async_setup_registers_and_runs_refresh_service() -> None:
    refreshed = []
    redrawn = []

    class Coordinator:
        async def async_request_refresh(self):
            refreshed.append(True)

    class Runtime(GuestyTerminalRuntime):
        async def async_force_redraw_all(self):
            redrawn.append(True)

    runtime = Runtime(None, None, None, Coordinator())
    hass = SimpleNamespace(data={DOMAIN: {"entry": runtime}}, services=FakeServices())

    assert asyncio.run(integration.async_setup(hass, {}))
    assert asyncio.run(integration.async_setup(hass, {}))
    handler = hass.services.registered[(DOMAIN, SERVICE_REFRESH)]
    asyncio.run(handler(None))
    assert refreshed == [True]
    redraw_handler = hass.services.registered[(DOMAIN, SERVICE_FORCE_REDRAW)]
    asyncio.run(redraw_handler(None))
    assert redrawn == [True]


def test_setup_and_unload_entry(monkeypatch) -> None:
    FakeStore.instances.clear()
    created = {}

    class FakeClient:
        def __init__(self, session, client_id, client_secret, **kwargs):
            created["client"] = self
            self.session = session
            self.client_id = client_id
            self.client_secret = client_secret
            self.token_data = kwargs["token_data"]
            self.token_saver = kwargs["token_saver"]

    class FakeCoordinator:
        def __init__(self, hass, entry, client):
            created["coordinator"] = self
            self.refreshed = False

        async def async_config_entry_first_refresh(self):
            self.refreshed = True

    class FakeRuntime:
        def __init__(self, hass, entry, client, coordinator):
            created["runtime"] = self
            self.coordinator = coordinator
            self.started = False
            self.stopped = False

        async def async_start(self):
            self.started = True

        async def async_stop(self):
            self.stopped = True

    monkeypatch.setattr(integration, "Store", FakeStore)
    monkeypatch.setattr(integration, "GuestyClient", FakeClient)
    monkeypatch.setattr(integration, "GuestyTerminalCoordinator", FakeCoordinator)
    monkeypatch.setattr(integration, "GuestyTerminalRuntime", FakeRuntime)
    monkeypatch.setattr(integration, "async_get_clientsession", lambda _hass: "session")

    config_entries = FakeConfigEntries()
    hass = SimpleNamespace(
        data={
            DOMAIN: {
                DATA_PENDING_TOKENS: {
                    "client": {"access_token": "fresh", "expires_at": 123}
                }
            }
        },
        config_entries=config_entries,
    )
    entry = _entry()

    assert asyncio.run(integration.async_setup_entry(hass, entry))
    assert created["client"].token_data["access_token"] == "fresh"
    assert FakeStore.instances[0].saved[0]["access_token"] == "fresh"
    asyncio.run(created["client"].token_saver({"access_token": "renewed"}))
    assert FakeStore.instances[0].saved[-1]["access_token"] == "renewed"
    assert created["coordinator"].refreshed
    assert created["runtime"].started
    assert config_entries.forwarded

    assert asyncio.run(integration.async_unload_entry(hass, entry))
    assert created["runtime"].stopped
    assert "entry-1" not in hass.data[DOMAIN]


def test_unload_failure_retains_runtime(monkeypatch) -> None:
    runtime = SimpleNamespace(async_stop=lambda: None)

    async def stop():
        return None

    runtime.async_stop = stop
    entry = _entry()
    entry.runtime_data = runtime
    hass = SimpleNamespace(
        data={DOMAIN: {entry.entry_id: runtime}},
        config_entries=FakeConfigEntries(unload_result=False),
    )
    assert not asyncio.run(integration.async_unload_entry(hass, entry))
    assert entry.entry_id in hass.data[DOMAIN]


def test_migration_updates_existing_timing_and_skips_current_version() -> None:
    options = {
        CONF_POLL_MINUTES: 60,
        CONF_MAPPINGS: {
            "sensor.display": {
                CONF_LEAD_HOURS: 4,
                CONF_CLEAR_AFTER_MINUTES: 0,
            },
            "invalid": "ignored",
        },
    }
    entry = _entry(version=1, options=options)
    config_entries = FakeConfigEntries()
    hass = SimpleNamespace(config_entries=config_entries)

    assert asyncio.run(integration.async_migrate_entry(hass, entry))
    mapping = entry.options[CONF_MAPPINGS]["sensor.display"]
    assert mapping[CONF_LEAD_HOURS] == 1
    assert mapping[CONF_CLEAR_AFTER_MINUTES] == 30
    assert entry.options[CONF_POLL_MINUTES] == 10
    assert entry.version == 2

    config_entries.updated.clear()
    assert asyncio.run(integration.async_migrate_entry(hass, entry))
    assert config_entries.updated == []


def test_remove_entry_clears_displays_and_token(monkeypatch) -> None:
    FakeStore.instances.clear()
    cleared = []

    async def clear_displays(hass, entry):
        cleared.append((hass, entry))

    monkeypatch.setattr(integration, "Store", FakeStore)
    monkeypatch.setattr(integration, "async_clear_configured_displays", clear_displays)
    hass = SimpleNamespace()
    entry = _entry()
    asyncio.run(integration.async_remove_entry(hass, entry))
    assert cleared == [(hass, entry)]
    assert FakeStore.instances[0].removed
