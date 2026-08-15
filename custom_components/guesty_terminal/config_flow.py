"""UI configuration for GuestyTerminal."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult, OptionsFlowWithReload
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import GuestyAuthenticationError, GuestyClient, GuestyError
from .const import (
    CONF_CLEAR_AFTER_MINUTES,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_ENDPOINT_ENTITY,
    CONF_FIRMWARE_AWAKE_SECONDS,
    CONF_FIRMWARE_DEVICE_NAME,
    CONF_FIRMWARE_FRIENDLY_NAME,
    CONF_FIRMWARE_OVERWRITE,
    CONF_FIRMWARE_POWER_MODE,
    CONF_FIRMWARE_WAKE_MINUTES,
    CONF_LEAD_HOURS,
    CONF_LISTING_ID,
    CONF_MAPPINGS,
    CONF_POLL_MINUTES,
    CONF_REMOVE_MAPPING,
    CONF_SHOW_DOOR_CODE,
    CONF_SHOW_WIFI,
    CONF_WELCOME_TEXT,
    CONF_WELCOME_TITLE,
    DATA_PENDING_TOKENS,
    DEFAULT_CLEAR_AFTER_MINUTES,
    DEFAULT_FIRMWARE_AWAKE_SECONDS,
    DEFAULT_FIRMWARE_DEVICE_NAME,
    DEFAULT_FIRMWARE_FRIENDLY_NAME,
    DEFAULT_FIRMWARE_POWER_MODE,
    DEFAULT_FIRMWARE_WAKE_MINUTES,
    DEFAULT_LEAD_HOURS,
    DEFAULT_POLL_MINUTES,
    DEFAULT_WELCOME_TEXT,
    DEFAULT_WELCOME_TITLE,
    DOMAIN,
    ENDPOINT_ENTITY_SUFFIX,
    ENDPOINT_ORIGINAL_NAME,
    MAX_POLL_MINUTES,
)
from .firmware import (
    POWER_MODES,
    FirmwareConfigError,
    FirmwareFileExistsError,
    FirmwareOptions,
    write_firmware_config,
)
from .models import MappingOptions
from .runtime import GuestyTerminalRuntime


async def _validate_credentials(
    hass, client_id: str, client_secret: str
) -> list[dict[str, Any]]:
    captured_token: dict[str, Any] = {}

    async def _capture_token(data: dict[str, Any]) -> None:
        captured_token.update(data)

    client = GuestyClient(
        async_get_clientsession(hass),
        client_id.strip(),
        client_secret.strip(),
        token_saver=_capture_token,
    )
    listings = await client.async_get_listings()
    if captured_token:
        domain_data = hass.data.setdefault(DOMAIN, {})
        pending_tokens = domain_data.setdefault(DATA_PENDING_TOKENS, {})
        pending_tokens[client_id.strip()] = captured_token
    return listings


class GuestyTerminalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a Guesty account."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect and validate Guesty application credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client_id = user_input[CONF_CLIENT_ID].strip()
            client_secret = user_input[CONF_CLIENT_SECRET].strip()
            if any(
                entry.unique_id == client_id for entry in self._async_current_entries()
            ):
                return self.async_abort(reason="already_configured")
            try:
                await _validate_credentials(self.hass, client_id, client_secret)
            except GuestyAuthenticationError:
                errors["base"] = "invalid_auth"
            except GuestyError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(client_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="GuestyTerminal",
                    data={
                        CONF_CLIENT_ID: client_id,
                        CONF_CLIENT_SECRET: client_secret,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLIENT_ID): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.TEXT)
                    ),
                    vol.Required(CONF_CLIENT_SECRET): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Start credential replacement after an authentication failure."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate and store replacement credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await _validate_credentials(
                    self.hass,
                    user_input[CONF_CLIENT_ID],
                    user_input[CONF_CLIENT_SECRET],
                )
            except GuestyAuthenticationError:
                errors["base"] = "invalid_auth"
            except GuestyError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    self._reauth_entry,
                    data_updates={
                        CONF_CLIENT_ID: user_input[CONF_CLIENT_ID].strip(),
                        CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET].strip(),
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CLIENT_ID,
                        default=self._reauth_entry.data[CONF_CLIENT_ID],
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.TEXT)),
                    vol.Required(CONF_CLIENT_SECRET): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                }
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry) -> GuestyTerminalOptionsFlow:
        """Return the options flow."""
        return GuestyTerminalOptionsFlow()


class GuestyTerminalOptionsFlow(OptionsFlowWithReload):
    """Configure display mappings and refresh behavior."""

    async def async_step_init(
        self, _user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init", menu_options=("mapping", "firmware", "general")
        )

    def _runtime(self) -> GuestyTerminalRuntime:
        return self.config_entry.runtime_data

    def _endpoint_choices(self) -> list[SelectOptionDict]:
        entity_registry = er.async_get(self.hass)
        device_registry = dr.async_get(self.hass)
        choices: list[SelectOptionDict] = []
        for entry in entity_registry.entities.values():
            if not (
                entry.original_name == ENDPOINT_ORIGINAL_NAME
                or entry.entity_id.endswith(ENDPOINT_ENTITY_SUFFIX)
            ):
                continue
            label = entry.entity_id
            if entry.device_id:
                device = device_registry.async_get(entry.device_id)
                if device is not None:
                    label = device.name_by_user or device.name or label
            choices.append(SelectOptionDict(value=entry.entity_id, label=label))
        return sorted(choices, key=lambda item: str(item["label"]).lower())

    def _listing_choices(self) -> list[SelectOptionDict]:
        runtime = self._runtime()
        if runtime.coordinator.data is None:
            return []
        return [
            SelectOptionDict(value=listing.listing_id, label=listing.display_name)
            for listing in sorted(
                runtime.coordinator.data.listings.values(),
                key=lambda item: item.display_name.lower(),
            )
        ]

    async def async_step_mapping(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add, replace, or remove one listing-to-display mapping."""
        endpoints = self._endpoint_choices()
        listings = self._listing_choices()
        if not endpoints:
            return self.async_abort(reason="no_displays")
        if not listings:
            return self.async_abort(reason="no_listings")

        if user_input is not None:
            endpoint = user_input[CONF_ENDPOINT_ENTITY]
            options = deepcopy(dict(self.config_entry.options))
            mappings = deepcopy(options.get(CONF_MAPPINGS, {}))
            if user_input.get(CONF_REMOVE_MAPPING):
                # Clear reachable E-paper immediately. A short payload lease is
                # the fallback when the battery display is currently asleep.
                await self._runtime().async_clear_endpoint(endpoint)
                mappings.pop(endpoint, None)
            else:
                mapping = MappingOptions(
                    endpoint_entity=endpoint,
                    listing_id=user_input[CONF_LISTING_ID],
                    welcome_title=user_input[CONF_WELCOME_TITLE],
                    welcome_text=user_input[CONF_WELCOME_TEXT],
                    lead_hours=int(user_input[CONF_LEAD_HOURS]),
                    clear_after_minutes=int(user_input[CONF_CLEAR_AFTER_MINUTES]),
                    show_door_code=bool(user_input[CONF_SHOW_DOOR_CODE]),
                    show_wifi=bool(user_input[CONF_SHOW_WIFI]),
                )
                mappings[endpoint] = mapping.as_dict()
            options[CONF_MAPPINGS] = mappings
            return self.async_create_entry(data=options)

        return self.async_show_form(
            step_id="mapping",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_ENDPOINT_ENTITY): SelectSelector(
                        SelectSelectorConfig(
                            options=endpoints, mode=SelectSelectorMode.DROPDOWN
                        )
                    ),
                    vol.Required(CONF_LISTING_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=listings, mode=SelectSelectorMode.DROPDOWN
                        )
                    ),
                    vol.Required(
                        CONF_WELCOME_TITLE, default=DEFAULT_WELCOME_TITLE
                    ): TextSelector(TextSelectorConfig(multiline=False)),
                    vol.Required(
                        CONF_WELCOME_TEXT, default=DEFAULT_WELCOME_TEXT
                    ): TextSelector(TextSelectorConfig(multiline=True)),
                    vol.Required(
                        CONF_LEAD_HOURS, default=DEFAULT_LEAD_HOURS
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=48, step=1, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_CLEAR_AFTER_MINUTES,
                        default=DEFAULT_CLEAR_AFTER_MINUTES,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=120, step=5, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(CONF_SHOW_DOOR_CODE, default=True): BooleanSelector(),
                    vol.Required(CONF_SHOW_WIFI, default=True): BooleanSelector(),
                    vol.Optional(CONF_REMOVE_MAPPING, default=False): BooleanSelector(),
                }
            ),
        )

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure the Guesty polling interval."""
        if user_input is not None:
            options = dict(self.config_entry.options)
            options[CONF_POLL_MINUTES] = int(user_input[CONF_POLL_MINUTES])
            return self.async_create_entry(data=options)

        return self.async_show_form(
            step_id="general",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_MINUTES,
                        default=self.config_entry.options.get(
                            CONF_POLL_MINUTES, DEFAULT_POLL_MINUTES
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=2,
                            max=MAX_POLL_MINUTES,
                            step=1,
                            mode=NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
        )

    async def async_step_firmware(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create a device-specific ESPHome configuration through the UI."""
        errors: dict[str, str] = {}
        if user_input is not None:
            firmware_options = FirmwareOptions(
                device_name=user_input[CONF_FIRMWARE_DEVICE_NAME],
                friendly_name=user_input[CONF_FIRMWARE_FRIENDLY_NAME],
                power_mode=user_input[CONF_FIRMWARE_POWER_MODE],
                wake_interval_minutes=int(user_input[CONF_FIRMWARE_WAKE_MINUTES]),
                awake_seconds=int(user_input[CONF_FIRMWARE_AWAKE_SECONDS]),
            )
            try:
                firmware_options = firmware_options.validated()
                destination = await self.hass.async_add_executor_job(
                    write_firmware_config,
                    Path(self.hass.config.path("esphome")),
                    firmware_options,
                    bool(user_input[CONF_FIRMWARE_OVERWRITE]),
                )
            except FirmwareFileExistsError:
                errors["base"] = "firmware_file_exists"
            except FirmwareConfigError:
                errors["base"] = "invalid_firmware_options"
            except OSError:
                errors["base"] = "firmware_write_failed"
            else:
                return self.async_abort(
                    reason="firmware_created",
                    description_placeholders={
                        "path": str(destination),
                        "device_name": firmware_options.device_name,
                    },
                )

        return self.async_show_form(
            step_id="firmware",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_FIRMWARE_DEVICE_NAME,
                        default=DEFAULT_FIRMWARE_DEVICE_NAME,
                    ): TextSelector(TextSelectorConfig(multiline=False)),
                    vol.Required(
                        CONF_FIRMWARE_FRIENDLY_NAME,
                        default=DEFAULT_FIRMWARE_FRIENDLY_NAME,
                    ): TextSelector(TextSelectorConfig(multiline=False)),
                    vol.Required(
                        CONF_FIRMWARE_POWER_MODE,
                        default=DEFAULT_FIRMWARE_POWER_MODE,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=list(POWER_MODES),
                            mode=SelectSelectorMode.DROPDOWN,
                            translation_key="firmware_power_mode",
                        )
                    ),
                    vol.Required(
                        CONF_FIRMWARE_WAKE_MINUTES,
                        default=DEFAULT_FIRMWARE_WAKE_MINUTES,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=5, max=180, step=5, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_FIRMWARE_AWAKE_SECONDS,
                        default=DEFAULT_FIRMWARE_AWAKE_SECONDS,
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=30, max=300, step=15, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_FIRMWARE_OVERWRITE, default=False
                    ): BooleanSelector(),
                }
            ),
            errors=errors,
        )
