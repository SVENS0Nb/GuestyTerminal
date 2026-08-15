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

DEFAULT_WELCOME_TITLE = "Willkommen, {first_name}!"
DEFAULT_WELCOME_TEXT = (
    "Schön, dass du da bist.\n"
    "Wir wünschen dir einen entspannten und angenehmen Aufenthalt."
)
DEFAULT_LEAD_HOURS = 4
DEFAULT_CLEAR_AFTER_MINUTES = 0
DEFAULT_POLL_MINUTES = 5
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=DEFAULT_POLL_MINUTES)

ENDPOINT_ORIGINAL_NAME = "GuestyTerminal Endpoint"
ENDPOINT_ENTITY_SUFFIX = "_guesty_terminal_endpoint"
DISPLAY_ACTION_SUFFIX = "_guesty_terminal_update_display"

SERVICE_REFRESH = "refresh"
TOKEN_STORE_VERSION = 1
TOKEN_REFRESH_MARGIN_SECONDS = 30 * 60

MODE_IDLE = "idle"
MODE_WELCOME = "welcome"

ACTIVE_RESERVATION_STATUSES = ("confirmed", "reserved")
