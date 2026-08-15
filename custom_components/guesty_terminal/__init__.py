"""GuestyTerminal integration."""

from __future__ import annotations

import logging
from copy import deepcopy

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import GuestyClient
from .const import (
    CONF_CLEAR_AFTER_MINUTES,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_LEAD_HOURS,
    CONF_MAPPINGS,
    CONF_POLL_MINUTES,
    DATA_PENDING_TOKENS,
    DEFAULT_CLEAR_AFTER_MINUTES,
    DEFAULT_LEAD_HOURS,
    DOMAIN,
    MAX_POLL_MINUTES,
    SERVICE_FORCE_REDRAW,
    SERVICE_REFRESH,
    TOKEN_STORE_VERSION,
)
from .coordinator import GuestyTerminalCoordinator
from .runtime import GuestyTerminalRuntime, async_clear_configured_displays

_LOGGER = logging.getLogger(__name__)
PLATFORMS = (Platform.BUTTON, Platform.SENSOR)
CONFIG_ENTRY_VERSION = 2


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Set up integration-level refresh and recovery actions."""
    hass.data.setdefault(DOMAIN, {})

    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH):

        async def _handle_refresh(_call: ServiceCall) -> None:
            runtimes = list(hass.data.get(DOMAIN, {}).values())
            for runtime in runtimes:
                if isinstance(runtime, GuestyTerminalRuntime):
                    await runtime.coordinator.async_request_refresh()

        hass.services.async_register(DOMAIN, SERVICE_REFRESH, _handle_refresh)

    if not hass.services.has_service(DOMAIN, SERVICE_FORCE_REDRAW):

        async def _handle_force_redraw(_call: ServiceCall) -> None:
            runtimes = list(hass.data.get(DOMAIN, {}).values())
            for runtime in runtimes:
                if isinstance(runtime, GuestyTerminalRuntime):
                    await runtime.async_force_redraw_all()

        hass.services.async_register(DOMAIN, SERVICE_FORCE_REDRAW, _handle_force_redraw)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one Guesty account."""
    token_store: Store[dict] = Store(
        hass,
        TOKEN_STORE_VERSION,
        f"{DOMAIN}.{entry.entry_id}.token",
        private=True,
    )
    stored_token = await token_store.async_load()
    domain_data = hass.data.setdefault(DOMAIN, {})
    pending_tokens = domain_data.setdefault(DATA_PENDING_TOKENS, {})
    token_data = pending_tokens.pop(entry.data[CONF_CLIENT_ID], None) or stored_token
    if token_data is not None and token_data is not stored_token:
        await token_store.async_save(token_data)

    async def _save_token(data: dict) -> None:
        await token_store.async_save(data)

    client = GuestyClient(
        async_get_clientsession(hass),
        entry.data[CONF_CLIENT_ID],
        entry.data[CONF_CLIENT_SECRET],
        token_data=token_data,
        token_saver=_save_token,
    )
    coordinator = GuestyTerminalCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    runtime = GuestyTerminalRuntime(hass, entry, client, coordinator)
    entry.runtime_data = runtime
    domain_data[entry.entry_id] = runtime

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await runtime.async_start()
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate early installations to the confirmed-reservation timing policy."""
    if entry.version >= CONFIG_ENTRY_VERSION:
        return True

    options = deepcopy(dict(entry.options))
    mappings = options.get(CONF_MAPPINGS, {})
    if isinstance(mappings, dict):
        for raw_mapping in mappings.values():
            if not isinstance(raw_mapping, dict):
                continue
            raw_mapping[CONF_LEAD_HOURS] = DEFAULT_LEAD_HOURS
            raw_mapping[CONF_CLEAR_AFTER_MINUTES] = DEFAULT_CLEAR_AFTER_MINUTES
    if CONF_POLL_MINUTES in options:
        options[CONF_POLL_MINUTES] = min(
            MAX_POLL_MINUTES,
            max(2, int(options[CONF_POLL_MINUTES])),
        )
    hass.config_entries.async_update_entry(
        entry,
        options=options,
        version=CONFIG_ENTRY_VERSION,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Guesty account."""
    runtime: GuestyTerminalRuntime = entry.runtime_data
    await runtime.async_stop()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clear displays and delete the cached OAuth token on permanent removal."""
    await async_clear_configured_displays(hass, entry)
    token_store: Store[dict] = Store(
        hass,
        TOKEN_STORE_VERSION,
        f"{DOMAIN}.{entry.entry_id}.token",
        private=True,
    )
    await token_store.async_remove()
