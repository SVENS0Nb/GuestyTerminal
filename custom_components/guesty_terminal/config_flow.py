"""UI configuration for GuestyTerminal."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.config_entries import ConfigFlowResult, OptionsFlowWithReload
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    FileSelector,
    FileSelectorConfig,
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
    TimeSelector,
)

from .api import GuestyAuthenticationError, GuestyClient, GuestyError
from .const import (
    CONF_CHECKOUT_INSTRUCTIONS_FALLBACK,
    CONF_CHECKOUT_INSTRUCTIONS_LABEL,
    CONF_CHECKOUT_LABEL,
    CONF_CHECKOUT_PAGE_MESSAGE,
    CONF_CHECKOUT_PAGE_TITLE,
    CONF_CHECKOUT_START_TIME,
    CONF_CLEANER_NOTES_LABEL,
    CONF_CLEAR_AFTER_MINUTES,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
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
    DATE_TIME_FORMAT_EU,
    DATE_TIME_FORMAT_US,
    DEFAULT_CHECKOUT_START_TIME,
    DEFAULT_CLEAR_AFTER_MINUTES,
    DEFAULT_DATE_TIME_FORMAT,
    DEFAULT_FIRMWARE_AWAKE_SECONDS,
    DEFAULT_FIRMWARE_DEVICE_NAME,
    DEFAULT_FIRMWARE_FRIENDLY_NAME,
    DEFAULT_FIRMWARE_POWER_MODE,
    DEFAULT_FIRMWARE_WAKE_MINUTES,
    DEFAULT_LEAD_HOURS,
    DEFAULT_POLL_MINUTES,
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
from .localization import display_text_defaults, normalize_display_language
from .logo import LogoError, encode_logo, valid_logo_data
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

    _mapping_endpoint: str | None = None
    _mapping_language: str | None = None
    _mapping_language_changed: bool = False
    _checkout_endpoint: str | None = None
    _empty_endpoint: str | None = None

    async def async_step_init(
        self, _user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        language = str(
            getattr(getattr(self.hass, "config", None), "language", "en")
        ).lower()
        if language.startswith("de"):
            menu_options = {
                "mapping": "Listing einem Display zuordnen",
                "checkout": "Checkout-Seite konfigurieren",
                "empty_room": "Seite für leeres Zimmer konfigurieren",
                "firmware": "E1001-Firmware erstellen",
                "general": "Allgemeine Einstellungen",
            }
        elif language.startswith("fr"):
            menu_options = {
                "mapping": "Associer une annonce à un écran",
                "checkout": "Configurer la page de départ",
                "empty_room": "Configurer la page du logement libre",
                "firmware": "Créer le firmware E1001",
                "general": "Paramètres généraux",
            }
        elif language.startswith("es"):
            menu_options = {
                "mapping": "Asignar un alojamiento a una pantalla",
                "checkout": "Configurar la página de salida",
                "empty_room": "Configurar la página del alojamiento libre",
                "firmware": "Crear firmware E1001",
                "general": "Ajustes generales",
            }
        else:
            menu_options = {
                "mapping": "Assign a listing to a display",
                "checkout": "Configure checkout page",
                "empty_room": "Configure empty-room page",
                "firmware": "Create E1001 firmware",
                "general": "General settings",
            }
        return self.async_show_menu(step_id="init", menu_options=menu_options)

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

    def _stored_mapping(self, endpoint: str) -> MappingOptions | None:
        """Return one persisted mapping without mutating entry options."""
        raw_mappings = self.config_entry.options.get(CONF_MAPPINGS, {})
        if not isinstance(raw_mappings, dict):
            return None
        raw_mapping = raw_mappings.get(endpoint)
        if not isinstance(raw_mapping, dict):
            return None
        return MappingOptions.from_dict(endpoint, raw_mapping)

    def _system_display_language(self) -> str:
        """Use the Home Assistant language for a newly configured display."""
        language = getattr(getattr(self.hass, "config", None), "language", "en")
        return normalize_display_language(language, fallback="en")

    async def async_step_mapping(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select the display whose mapping should be edited."""
        endpoints = self._endpoint_choices()
        listings = self._listing_choices()
        if not endpoints:
            return self.async_abort(reason="no_displays")
        if not listings:
            return self.async_abort(reason="no_listings")

        if user_input is not None:
            self._mapping_endpoint = user_input[CONF_ENDPOINT_ENTITY]
            self._mapping_language = None
            self._mapping_language_changed = False
            return await self.async_step_mapping_language()

        endpoint_values = {str(choice["value"]) for choice in endpoints}
        raw_mappings = self.config_entry.options.get(CONF_MAPPINGS, {})
        mapped_endpoint = (
            next(
                (endpoint for endpoint in raw_mappings if endpoint in endpoint_values),
                None,
            )
            if isinstance(raw_mappings, dict)
            else None
        )
        default_endpoint = mapped_endpoint or str(endpoints[0]["value"])

        return self.async_show_form(
            step_id="mapping",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENDPOINT_ENTITY, default=default_endpoint
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=endpoints, mode=SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
        )

    async def async_step_mapping_language(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose a display language before editing its localized copy."""
        endpoint = self._mapping_endpoint
        if endpoint is None:
            return await self.async_step_mapping()

        current = self._stored_mapping(endpoint)
        current_language = (
            current.display_language
            if current is not None
            else self._system_display_language()
        )
        if user_input is not None:
            selected = normalize_display_language(
                user_input[CONF_DISPLAY_LANGUAGE], fallback=current_language
            )
            self._mapping_language = selected
            self._mapping_language_changed = (
                current is not None and selected != current.display_language
            )
            return await self.async_step_mapping_details()

        return self.async_show_form(
            step_id="mapping_language",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_DISPLAY_LANGUAGE, default=current_language
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value="de", label="Deutsch"),
                                SelectOptionDict(value="en", label="English"),
                                SelectOptionDict(value="fr", label="Français"),
                                SelectOptionDict(value="es", label="Español"),
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_mapping_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit or remove the selected display mapping."""
        endpoint = self._mapping_endpoint
        if endpoint is None:
            return await self.async_step_mapping()

        listings = self._listing_choices()
        if not listings:
            return self.async_abort(reason="no_listings")

        options = deepcopy(dict(self.config_entry.options))
        raw_mappings = options.get(CONF_MAPPINGS, {})
        mappings = deepcopy(raw_mappings) if isinstance(raw_mappings, dict) else {}
        stored_mapping = self._stored_mapping(endpoint)

        if user_input is not None:
            if user_input.get(CONF_REMOVE_MAPPING):
                # Clear reachable E-paper immediately. A short payload lease is
                # the fallback when the battery display is currently asleep.
                await self._runtime().async_clear_endpoint(endpoint)
                mappings.pop(endpoint, None)
            else:
                language = self._mapping_language or self._system_display_language()
                checkout_defaults = display_text_defaults(language)
                keep_checkout_text = (
                    stored_mapping is not None and not self._mapping_language_changed
                )

                def checkout_value(attribute: str) -> str:
                    if keep_checkout_text:
                        return str(getattr(stored_mapping, attribute))
                    return str(getattr(checkout_defaults, attribute))

                mapping = MappingOptions(
                    endpoint_entity=endpoint,
                    listing_id=user_input[CONF_LISTING_ID],
                    display_language=(
                        self._mapping_language or self._system_display_language()
                    ),
                    welcome_title=user_input[CONF_WELCOME_TITLE],
                    welcome_text=user_input[CONF_WELCOME_TEXT],
                    idle_title=(
                        stored_mapping.idle_title
                        if keep_checkout_text
                        else checkout_defaults.idle_title
                    ),
                    idle_text=(
                        stored_mapping.idle_text
                        if keep_checkout_text
                        else checkout_defaults.idle_text
                    ),
                    door_code_label=user_input[CONF_DOOR_CODE_LABEL],
                    wifi_label=user_input[CONF_WIFI_LABEL],
                    wifi_name_label=user_input[CONF_WIFI_NAME_LABEL],
                    wifi_key_label=user_input[CONF_WIFI_KEY_LABEL],
                    checkout_label=user_input[CONF_CHECKOUT_LABEL],
                    checkout_start_time=(
                        stored_mapping.checkout_start_time
                        if stored_mapping is not None
                        else DEFAULT_CHECKOUT_START_TIME
                    ),
                    checkout_page_title=checkout_value("checkout_page_title"),
                    checkout_page_message=checkout_value("checkout_page_message"),
                    checkout_instructions_label=checkout_value(
                        "checkout_instructions_label"
                    ),
                    checkout_instructions_fallback=checkout_value(
                        "checkout_instructions_fallback"
                    ),
                    empty_page_title=checkout_value("empty_page_title"),
                    empty_no_booking_text=checkout_value("empty_no_booking_text"),
                    general_notes_label=checkout_value("general_notes_label"),
                    cleaner_notes_label=checkout_value("cleaner_notes_label"),
                    special_requests_label=checkout_value("special_requests_label"),
                    date_time_format=user_input[CONF_DATE_TIME_FORMAT],
                    lead_hours=int(user_input[CONF_LEAD_HOURS]),
                    clear_after_minutes=int(user_input[CONF_CLEAR_AFTER_MINUTES]),
                    show_door_code=bool(user_input[CONF_SHOW_DOOR_CODE]),
                    show_wifi=bool(user_input[CONF_SHOW_WIFI]),
                    weather_entity=str(user_input.get(CONF_WEATHER_ENTITY, "")).strip(),
                )
                mappings[endpoint] = mapping.as_dict()
            options[CONF_MAPPINGS] = mappings
            return self.async_create_entry(data=options)

        raw_mapping = mappings.get(endpoint)
        current = (
            MappingOptions.from_dict(endpoint, raw_mapping)
            if isinstance(raw_mapping, dict)
            else None
        )
        language = self._mapping_language or (
            current.display_language
            if current is not None
            else self._system_display_language()
        )
        language_defaults = display_text_defaults(language)
        keep_current_text = current is not None and not self._mapping_language_changed

        def text_default(attribute: str) -> str:
            if keep_current_text:
                return str(getattr(current, attribute))
            return str(getattr(language_defaults, attribute))

        listing_values = {str(choice["value"]) for choice in listings}
        listing_field = (
            vol.Required(CONF_LISTING_ID, default=current.listing_id)
            if current is not None and current.listing_id in listing_values
            else vol.Required(CONF_LISTING_ID)
        )
        weather_field = (
            vol.Optional(CONF_WEATHER_ENTITY, default=current.weather_entity)
            if current is not None and current.weather_entity
            else vol.Optional(CONF_WEATHER_ENTITY)
        )

        return self.async_show_form(
            step_id="mapping_details",
            data_schema=vol.Schema(
                {
                    listing_field: SelectSelector(
                        SelectSelectorConfig(
                            options=listings, mode=SelectSelectorMode.DROPDOWN
                        )
                    ),
                    vol.Required(
                        CONF_WELCOME_TITLE,
                        default=text_default("welcome_title"),
                    ): TextSelector(TextSelectorConfig(multiline=False)),
                    vol.Required(
                        CONF_WELCOME_TEXT,
                        default=text_default("welcome_text"),
                    ): TextSelector(TextSelectorConfig(multiline=True)),
                    vol.Required(
                        CONF_DOOR_CODE_LABEL,
                        default=text_default("door_code_label"),
                    ): TextSelector(TextSelectorConfig(multiline=False)),
                    vol.Required(
                        CONF_WIFI_LABEL, default=text_default("wifi_label")
                    ): TextSelector(TextSelectorConfig(multiline=False)),
                    vol.Required(
                        CONF_WIFI_NAME_LABEL,
                        default=text_default("wifi_name_label"),
                    ): TextSelector(TextSelectorConfig(multiline=False)),
                    vol.Required(
                        CONF_WIFI_KEY_LABEL,
                        default=text_default("wifi_key_label"),
                    ): TextSelector(TextSelectorConfig(multiline=False)),
                    vol.Required(
                        CONF_CHECKOUT_LABEL,
                        default=text_default("checkout_label"),
                    ): TextSelector(TextSelectorConfig(multiline=False)),
                    vol.Required(
                        CONF_DATE_TIME_FORMAT,
                        default=(
                            current.date_time_format
                            if current is not None
                            else DEFAULT_DATE_TIME_FORMAT
                        ),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    value=DATE_TIME_FORMAT_EU,
                                    label="EU – 17.08.2026 · 14:00 Uhr",
                                ),
                                SelectOptionDict(
                                    value=DATE_TIME_FORMAT_US,
                                    label="US – 08/17/2026 · 2:00 PM",
                                ),
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_LEAD_HOURS,
                        default=(
                            current.lead_hours
                            if current is not None
                            else DEFAULT_LEAD_HOURS
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=48, step=1, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_CLEAR_AFTER_MINUTES,
                        default=(
                            current.clear_after_minutes
                            if current is not None
                            else DEFAULT_CLEAR_AFTER_MINUTES
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=0, max=120, step=5, mode=NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_SHOW_DOOR_CODE,
                        default=(
                            current.show_door_code if current is not None else True
                        ),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_SHOW_WIFI,
                        default=current.show_wifi if current is not None else True,
                    ): BooleanSelector(),
                    weather_field: EntitySelector(
                        EntitySelectorConfig(domain="weather")
                    ),
                    vol.Optional(CONF_REMOVE_MAPPING, default=False): BooleanSelector(),
                }
            ),
        )

    def _configured_display_choices(self) -> list[SelectOptionDict]:
        """Return only displays that already have a persisted listing mapping."""
        labels = {
            str(choice["value"]): str(choice["label"])
            for choice in self._endpoint_choices()
        }
        raw_mappings = self.config_entry.options.get(CONF_MAPPINGS, {})
        if not isinstance(raw_mappings, dict):
            return []
        choices = [
            SelectOptionDict(value=endpoint, label=labels.get(endpoint, endpoint))
            for endpoint, raw in raw_mappings.items()
            if isinstance(endpoint, str)
            and isinstance(raw, dict)
            and MappingOptions.from_dict(endpoint, raw).listing_id
        ]
        return sorted(choices, key=lambda item: str(item["label"]).lower())

    async def async_step_checkout(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the configured display whose checkout page should be edited."""
        displays = self._configured_display_choices()
        if not displays:
            return self.async_abort(reason="no_mappings")
        if user_input is not None:
            self._checkout_endpoint = user_input[CONF_ENDPOINT_ENTITY]
            return await self.async_step_checkout_details()

        return self.async_show_form(
            step_id="checkout",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENDPOINT_ENTITY, default=str(displays[0]["value"])
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=displays, mode=SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
        )

    async def async_step_checkout_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the localized checkout-day page for one configured display."""
        endpoint = self._checkout_endpoint
        if endpoint is None:
            return await self.async_step_checkout()
        current = self._stored_mapping(endpoint)
        if current is None or not current.listing_id:
            return self.async_abort(reason="no_mappings")

        if user_input is not None:
            updated = replace(
                current,
                checkout_start_time=str(user_input[CONF_CHECKOUT_START_TIME]),
                checkout_page_title=str(user_input[CONF_CHECKOUT_PAGE_TITLE]),
                checkout_page_message=str(user_input[CONF_CHECKOUT_PAGE_MESSAGE]),
                checkout_instructions_label=str(
                    user_input[CONF_CHECKOUT_INSTRUCTIONS_LABEL]
                ),
                checkout_instructions_fallback=str(
                    user_input[CONF_CHECKOUT_INSTRUCTIONS_FALLBACK]
                ),
            )
            options = deepcopy(dict(self.config_entry.options))
            raw_mappings = options.get(CONF_MAPPINGS, {})
            mappings = deepcopy(raw_mappings) if isinstance(raw_mappings, dict) else {}
            mappings[endpoint] = updated.as_dict()
            options[CONF_MAPPINGS] = mappings
            return self.async_create_entry(data=options)

        return self.async_show_form(
            step_id="checkout_details",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CHECKOUT_START_TIME,
                        default=current.checkout_start_time,
                    ): TimeSelector(),
                    vol.Required(
                        CONF_CHECKOUT_PAGE_TITLE,
                        default=current.checkout_page_title,
                    ): TextSelector(TextSelectorConfig(multiline=False)),
                    vol.Required(
                        CONF_CHECKOUT_PAGE_MESSAGE,
                        default=current.checkout_page_message,
                    ): TextSelector(TextSelectorConfig(multiline=True)),
                    vol.Required(
                        CONF_CHECKOUT_INSTRUCTIONS_LABEL,
                        default=current.checkout_instructions_label,
                    ): TextSelector(TextSelectorConfig(multiline=False)),
                    vol.Required(
                        CONF_CHECKOUT_INSTRUCTIONS_FALLBACK,
                        default=current.checkout_instructions_fallback,
                    ): TextSelector(TextSelectorConfig(multiline=True)),
                }
            ),
            description_placeholders={
                "display_language": current.display_language.upper(),
                "date_time_format": current.date_time_format.upper(),
            },
        )

    async def async_step_empty_room(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose the configured display whose empty-room page is edited."""
        displays = self._configured_display_choices()
        if not displays:
            return self.async_abort(reason="no_mappings")
        if user_input is not None:
            self._empty_endpoint = user_input[CONF_ENDPOINT_ENTITY]
            return await self.async_step_empty_room_details()

        return self.async_show_form(
            step_id="empty_room",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_ENDPOINT_ENTITY, default=str(displays[0]["value"])
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=displays, mode=SelectSelectorMode.DROPDOWN
                        )
                    )
                }
            ),
        )

    async def async_step_empty_room_details(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit localized copy for one display's empty-room page."""
        endpoint = self._empty_endpoint
        if endpoint is None:
            return await self.async_step_empty_room()
        current = self._stored_mapping(endpoint)
        if current is None or not current.listing_id:
            return self.async_abort(reason="no_mappings")

        if user_input is not None:
            updated = replace(
                current,
                empty_page_title=str(user_input[CONF_EMPTY_PAGE_TITLE]),
                empty_no_booking_text=str(user_input[CONF_EMPTY_NO_BOOKING_TEXT]),
                general_notes_label=str(user_input[CONF_GENERAL_NOTES_LABEL]),
                cleaner_notes_label=str(user_input[CONF_CLEANER_NOTES_LABEL]),
                special_requests_label=str(user_input[CONF_SPECIAL_REQUESTS_LABEL]),
            )
            options = deepcopy(dict(self.config_entry.options))
            raw_mappings = options.get(CONF_MAPPINGS, {})
            mappings = deepcopy(raw_mappings) if isinstance(raw_mappings, dict) else {}
            mappings[endpoint] = updated.as_dict()
            options[CONF_MAPPINGS] = mappings
            return self.async_create_entry(data=options)

        return self.async_show_form(
            step_id="empty_room_details",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_EMPTY_PAGE_TITLE,
                        default=current.empty_page_title,
                    ): TextSelector(TextSelectorConfig(multiline=False)),
                    vol.Required(
                        CONF_EMPTY_NO_BOOKING_TEXT,
                        default=current.empty_no_booking_text,
                    ): TextSelector(TextSelectorConfig(multiline=True)),
                    vol.Required(
                        CONF_GENERAL_NOTES_LABEL,
                        default=current.general_notes_label,
                    ): TextSelector(TextSelectorConfig(multiline=False)),
                    vol.Required(
                        CONF_CLEANER_NOTES_LABEL,
                        default=current.cleaner_notes_label,
                    ): TextSelector(TextSelectorConfig(multiline=False)),
                    vol.Required(
                        CONF_SPECIAL_REQUESTS_LABEL,
                        default=current.special_requests_label,
                    ): TextSelector(TextSelectorConfig(multiline=False)),
                }
            ),
            description_placeholders={
                "display_language": current.display_language.upper(),
                "date_time_format": current.date_time_format.upper(),
            },
        )

    async def async_step_general(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure global settings shared by every display."""
        errors: dict[str, str] = {}
        if user_input is not None:
            options = dict(self.config_entry.options)
            options[CONF_POLL_MINUTES] = int(user_input[CONF_POLL_MINUTES])
            if user_input.get(CONF_REMOVE_LOGO):
                options.pop(CONF_LOGO_DATA, None)
            elif upload_id := user_input.get(CONF_LOGO_UPLOAD):
                try:
                    with process_uploaded_file(self.hass, upload_id) as path:
                        logo_data = await self.hass.async_add_executor_job(
                            encode_logo, path
                        )
                except (LogoError, OSError, ValueError):
                    errors["base"] = "invalid_logo"
                else:
                    options[CONF_LOGO_DATA] = logo_data
            if not errors:
                return self.async_create_entry(data=options)

        has_logo = bool(valid_logo_data(self.config_entry.options.get(CONF_LOGO_DATA)))
        language = str(
            getattr(getattr(self.hass, "config", None), "language", "en")
        ).lower()
        if language.startswith("de"):
            logo_status = "vorhanden" if has_logo else "nicht eingerichtet"
        elif language.startswith("fr"):
            logo_status = "configuré" if has_logo else "non configuré"
        elif language.startswith("es"):
            logo_status = "configurado" if has_logo else "no configurado"
        else:
            logo_status = "configured" if has_logo else "not configured"

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
                    ),
                    vol.Optional(CONF_LOGO_UPLOAD): FileSelector(
                        FileSelectorConfig(
                            accept="image/png,image/jpeg,.png,.jpg,.jpeg"
                        )
                    ),
                    vol.Optional(CONF_REMOVE_LOGO, default=False): BooleanSelector(),
                }
            ),
            errors=errors,
            description_placeholders={"logo_status": logo_status},
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
