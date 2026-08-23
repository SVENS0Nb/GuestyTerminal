"""GuestyTerminal integration."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import GuestyClient
from .const import (
    CONF_CLEAR_AFTER_MINUTES,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_ENDPOINT_ID,
    CONF_LEAD_HOURS,
    CONF_MAPPINGS,
    CONF_POLL_MINUTES,
    DATA_PENDING_TOKENS,
    DEFAULT_CLEAR_AFTER_MINUTES,
    DEFAULT_LEAD_HOURS,
    DEFAULT_POLL_MINUTES,
    DOMAIN,
    MAX_POLL_MINUTES,
    SERVICE_FORCE_REDRAW,
    SERVICE_REFRESH,
    TOKEN_STORE_VERSION,
)
from .coordinator import GuestyTerminalCoordinator
from .models import endpoint_stable_id
from .runtime import (
    DisplayDeliveryResult,
    GuestyTerminalConfigEntry,
    GuestyTerminalRuntime,
    async_clear_configured_displays,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = (Platform.BUTTON, Platform.SENSOR)
CONFIG_ENTRY_VERSION = 3


def _service_error(key: str, *, failed: int, total: int) -> HomeAssistantError:
    """Return a translated, privacy-safe action error."""
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders={"failed": str(failed), "total": str(total)},
    )


def _active_runtimes(hass: HomeAssistant) -> list[GuestyTerminalRuntime]:
    """Return only config-entry runtimes from shared domain data."""
    return [
        runtime
        for runtime in hass.data.get(DOMAIN, {}).values()
        if isinstance(runtime, GuestyTerminalRuntime)
    ]


def _validate_delivery(results: list[DisplayDeliveryResult]) -> None:
    """Raise when a manual action could not reach any configured display."""
    attempted = sum(result.attempted for result in results)
    succeeded = sum(result.succeeded for result in results)
    if attempted and not succeeded:
        raise _service_error(
            "display_delivery_failed", failed=attempted, total=attempted
        )
    failed = attempted - succeeded
    if failed:
        _LOGGER.warning(
            "GuestyTerminal action reached %d of %d configured displays",
            succeeded,
            attempted,
        )


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Set up integration-level refresh and recovery actions."""
    hass.data.setdefault(DOMAIN, {})

    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH):

        async def _handle_refresh(_call: ServiceCall) -> None:
            runtimes = _active_runtimes(hass)
            outcomes = await asyncio.gather(
                *(runtime.async_refresh_and_push() for runtime in runtimes),
                return_exceptions=True,
            )
            failed_refreshes = sum(
                isinstance(outcome, BaseException)
                or not runtime.coordinator.last_update_success
                for runtime, outcome in zip(runtimes, outcomes, strict=True)
            )
            if failed_refreshes:
                raise _service_error(
                    "data_refresh_failed",
                    failed=failed_refreshes,
                    total=len(runtimes),
                )
            deliveries = [
                outcome
                for outcome in outcomes
                if isinstance(outcome, DisplayDeliveryResult)
            ]
            _validate_delivery(deliveries)

        hass.services.async_register(DOMAIN, SERVICE_REFRESH, _handle_refresh)

    if not hass.services.has_service(DOMAIN, SERVICE_FORCE_REDRAW):

        async def _handle_force_redraw(_call: ServiceCall) -> None:
            runtimes = _active_runtimes(hass)
            deliveries = await asyncio.gather(
                *(runtime.async_force_redraw_all() for runtime in runtimes)
            )
            _validate_delivery(deliveries)

        hass.services.async_register(DOMAIN, SERVICE_FORCE_REDRAW, _handle_force_redraw)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: GuestyTerminalConfigEntry
) -> bool:
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
    endpoint_owners: dict[str, str] = {}
    for configured_entry in hass.config_entries.async_entries(DOMAIN):
        mappings = configured_entry.options.get(CONF_MAPPINGS, {})
        if not isinstance(mappings, dict):
            continue
        for endpoint, mapping in mappings.items():
            if isinstance(endpoint, str) and isinstance(mapping, dict):
                endpoint_owners.setdefault(endpoint, configured_entry.entry_id)
    current_mappings = entry.options.get(CONF_MAPPINGS, {})
    if not isinstance(current_mappings, dict):
        current_mappings = {}
    blocked_endpoints = {
        endpoint
        for endpoint in current_mappings
        if isinstance(endpoint, str)
        if endpoint_owners.get(endpoint, entry.entry_id) != entry.entry_id
    }
    if blocked_endpoints:
        _LOGGER.error(
            "Ignoring %d GuestyTerminal display mapping(s) already owned by "
            "another Guesty config entry",
            len(blocked_endpoints),
        )
        coordinator.block_endpoints(blocked_endpoints)
    await coordinator.async_config_entry_first_refresh()

    runtime = GuestyTerminalRuntime(hass, entry, client, coordinator)
    entry.runtime_data = runtime
    domain_data[entry.entry_id] = runtime

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await runtime.async_start()
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry[Any]) -> bool:
    """Migrate timing defaults and stable display identities."""
    if entry.version >= CONFIG_ENTRY_VERSION:
        return True

    options = deepcopy(dict(entry.options))
    mappings = options.get(CONF_MAPPINGS, {})
    if isinstance(mappings, dict):
        for endpoint, raw_mapping in mappings.items():
            if not isinstance(raw_mapping, dict):
                continue
            if entry.version < 2:
                raw_mapping[CONF_LEAD_HOURS] = DEFAULT_LEAD_HOURS
                raw_mapping[CONF_CLEAR_AFTER_MINUTES] = DEFAULT_CLEAR_AFTER_MINUTES
            if isinstance(endpoint, str):
                raw_mapping.setdefault(CONF_ENDPOINT_ID, endpoint_stable_id(endpoint))
    if entry.version < 2 and CONF_POLL_MINUTES in options:
        try:
            poll_minutes = int(options[CONF_POLL_MINUTES])
        except (TypeError, ValueError):
            poll_minutes = DEFAULT_POLL_MINUTES
        options[CONF_POLL_MINUTES] = min(MAX_POLL_MINUTES, max(2, poll_minutes))
    hass.config_entries.async_update_entry(
        entry,
        options=options,
        version=CONFIG_ENTRY_VERSION,
    )
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: GuestyTerminalConfigEntry
) -> bool:
    """Unload a Guesty account."""
    runtime: GuestyTerminalRuntime = entry.runtime_data
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await runtime.async_stop()
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def async_remove_entry(
    hass: HomeAssistant, entry: GuestyTerminalConfigEntry
) -> None:
    """Clear displays and delete the cached OAuth token on permanent removal."""
    await async_clear_configured_displays(hass, entry)
    token_store: Store[dict] = Store(
        hass,
        TOKEN_STORE_VERSION,
        f"{DOMAIN}.{entry.entry_id}.token",
        private=True,
    )
    await token_store.async_remove()
