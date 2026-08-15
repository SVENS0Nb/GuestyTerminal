"""Constants for the GuestyTerminal integration."""

from datetime import timedelta

DOMAIN = "guesty_terminal"
DATA_PENDING_TOKENS = "pending_tokens"

CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_MAPPINGS = "mappings"
CONF_ENDPOINT_ENTITY = "endpoint_entity"
CONF_LISTING_ID = "listing_id"
CONF_WELCOME_TITLE = "welcome_title"
CONF_WELCOME_TEXT = "welcome_text"
CONF_LEAD_HOURS = "lead_hours"
CONF_CLEAR_AFTER_MINUTES = "clear_after_minutes"
CONF_SHOW_DOOR_CODE = "show_door_code"
CONF_SHOW_WIFI = "show_wifi"
CONF_REMOVE_MAPPING = "remove_mapping"
CONF_POLL_MINUTES = "poll_minutes"
CONF_FIRMWARE_DEVICE_NAME = "firmware_device_name"
CONF_FIRMWARE_FRIENDLY_NAME = "firmware_friendly_name"
CONF_FIRMWARE_POWER_MODE = "firmware_power_mode"
CONF_FIRMWARE_WAKE_MINUTES = "firmware_wake_minutes"
CONF_FIRMWARE_AWAKE_SECONDS = "firmware_awake_seconds"
CONF_FIRMWARE_OVERWRITE = "firmware_overwrite"

DEFAULT_WELCOME_TITLE = "Willkommen, {first_name}!"
DEFAULT_WELCOME_TEXT = (
    "Schön, dass du da bist.\n"
    "Wir wünschen dir einen entspannten und angenehmen Aufenthalt."
)
DEFAULT_LEAD_HOURS = 1
DEFAULT_CLEAR_AFTER_MINUTES = 30
DEFAULT_POLL_MINUTES = 5
MAX_POLL_MINUTES = 10
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=DEFAULT_POLL_MINUTES)
DISPLAY_LEASE_MINUTES = 15
DEFAULT_FIRMWARE_DEVICE_NAME = "guestyterminal-display-1"
DEFAULT_FIRMWARE_FRIENDLY_NAME = "GuestyTerminal Display 1"
DEFAULT_FIRMWARE_POWER_MODE = "auto"
DEFAULT_FIRMWARE_WAKE_MINUTES = 30
DEFAULT_FIRMWARE_AWAKE_SECONDS = 90

ENDPOINT_ORIGINAL_NAME = "GuestyTerminal Endpoint"
ENDPOINT_ENTITY_SUFFIX = "_guesty_terminal_endpoint"
DISPLAY_ACTION_SUFFIX = "_guesty_terminal_update_display"
DISPLAY_ACTION_V2_SUFFIX = "_guesty_terminal_update_display_v2"

SERVICE_REFRESH = "refresh"
TOKEN_STORE_VERSION = 1
TOKEN_REFRESH_MARGIN_SECONDS = 30 * 60

MODE_IDLE = "idle"
MODE_WELCOME = "welcome"

ACTIVE_RESERVATION_STATUSES = ("confirmed",)
