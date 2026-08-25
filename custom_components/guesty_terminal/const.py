"""Constants for the GuestyTerminal integration."""

from datetime import timedelta

DOMAIN = "guesty_terminal"
DATA_PENDING_TOKENS = "pending_tokens"
DATA_FIRMWARE_UPDATE_LOCK = "firmware_update_lock"

CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_MAPPINGS = "mappings"
CONF_ENDPOINT_ENTITY = "endpoint_entity"
CONF_ENDPOINT_ID = "endpoint_id"
CONF_LISTING_ID = "listing_id"
CONF_WELCOME_TITLE = "welcome_title"
CONF_WELCOME_TEXT = "welcome_text"
CONF_DISPLAY_LANGUAGE = "display_language"
CONF_DOOR_CODE_LABEL = "door_code_label"
CONF_WIFI_LABEL = "wifi_label"
CONF_WIFI_NAME_LABEL = "wifi_name_label"
CONF_WIFI_KEY_LABEL = "wifi_key_label"
CONF_CHECKOUT_LABEL = "checkout_label"
CONF_CHECKOUT_START_TIME = "checkout_start_time"
CONF_CHECKOUT_PAGE_TITLE = "checkout_page_title"
CONF_CHECKOUT_PAGE_MESSAGE = "checkout_page_message"
CONF_CHECKOUT_INSTRUCTIONS_LABEL = "checkout_instructions_label"
CONF_CHECKOUT_INSTRUCTIONS_FALLBACK = "checkout_instructions_fallback"
CONF_EMPTY_PAGE_TITLE = "empty_page_title"
CONF_EMPTY_NO_BOOKING_TEXT = "empty_no_booking_text"
CONF_GENERAL_NOTES_LABEL = "general_notes_label"
CONF_CLEANER_NOTES_LABEL = "cleaner_notes_label"
CONF_SPECIAL_REQUESTS_LABEL = "special_requests_label"
CONF_DATE_TIME_FORMAT = "date_time_format"
CONF_WEATHER_ENTITY = "weather_entity"
CONF_LEAD_HOURS = "lead_hours"
CONF_CLEAR_AFTER_MINUTES = "clear_after_minutes"
CONF_SHOW_DOOR_CODE = "show_door_code"
CONF_SHOW_WIFI = "show_wifi"
CONF_REMOVE_MAPPING = "remove_mapping"
CONF_POLL_MINUTES = "poll_minutes"
CONF_LOGO_DATA = "logo_data"
CONF_LOGO_UPLOAD = "logo_upload"
CONF_REMOVE_LOGO = "remove_logo"
CONF_FIRMWARE_DEVICE_NAME = "firmware_device_name"
CONF_FIRMWARE_FRIENDLY_NAME = "firmware_friendly_name"
CONF_FIRMWARE_POWER_MODE = "firmware_power_mode"
CONF_FIRMWARE_WAKE_MINUTES = "firmware_wake_minutes"
CONF_FIRMWARE_AWAKE_SECONDS = "firmware_awake_seconds"
CONF_FIRMWARE_FLASH_LAYOUT = "firmware_flash_layout"
CONF_FIRMWARE_CONFIRM_USB_MIGRATION = "firmware_confirm_usb_migration"
CONF_FIRMWARE_OVERWRITE = "firmware_overwrite"

DEFAULT_WELCOME_TITLE = "Willkommen, {first_name}!"
DEFAULT_WELCOME_TEXT = (
    "Schön, dass du da bist.\n"
    "Wir wünschen dir einen entspannten und angenehmen Aufenthalt."
)
DEFAULT_DISPLAY_LANGUAGE = "de"
DEFAULT_DOOR_CODE_LABEL = "TÜRCODE"
DEFAULT_WIFI_LABEL = "WIFI"
DEFAULT_WIFI_NAME_LABEL = "Name:"
DEFAULT_WIFI_KEY_LABEL = "Key:"
DEFAULT_CHECKOUT_LABEL = "Check-out:"
DEFAULT_CHECKOUT_START_TIME = "05:00:00"
DEFAULT_CHECKOUT_PAGE_TITLE = "Heute ist Check-out, {first_name}"
DEFAULT_CHECKOUT_PAGE_MESSAGE = (
    "Danke, dass du unser Gast warst.\n"
    "Wir wünschen dir eine gute und entspannte Heimreise!"
)
DEFAULT_CHECKOUT_INSTRUCTIONS_LABEL = "CHECK-OUT BIS {check_out_time}"
DEFAULT_CHECKOUT_INSTRUCTIONS_FALLBACK = (
    "Bitte beachte die vereinbarte Check-out-Zeit. Vielen Dank!"
)
DEFAULT_EMPTY_PAGE_TITLE = "NÄCHSTE BUCHUNG"
DEFAULT_EMPTY_NO_BOOKING_TEXT = "Keine bevorstehende Buchung"
DEFAULT_GENERAL_NOTES_LABEL = "ALLGEMEINE NOTIZEN"
DEFAULT_CLEANER_NOTES_LABEL = "FÜR DIE REINIGUNG"
DEFAULT_SPECIAL_REQUESTS_LABEL = "SONDERWÜNSCHE"
DEFAULT_NO_ACTIVE_BOOKING_LABEL = "Keine aktive Buchung"
DATE_TIME_FORMAT_EU = "eu"
DATE_TIME_FORMAT_US = "us"
DATE_TIME_FORMATS = (DATE_TIME_FORMAT_EU, DATE_TIME_FORMAT_US)
DEFAULT_DATE_TIME_FORMAT = DATE_TIME_FORMAT_EU
DEFAULT_LEAD_HOURS = 1
DEFAULT_CLEAR_AFTER_MINUTES = 30
DEFAULT_POLL_MINUTES = 5
MAX_POLL_MINUTES = 10
DEFAULT_UPDATE_INTERVAL = timedelta(minutes=DEFAULT_POLL_MINUTES)
UPCOMING_RESERVATIONS_PER_LISTING = 5
COMPLETED_RESERVATION_CACHE_HOURS = 12
DISPLAY_LEASE_MINUTES = 15
DEFAULT_FIRMWARE_DEVICE_NAME = "guestyterminal-display-1"
DEFAULT_FIRMWARE_FRIENDLY_NAME = "GuestyTerminal Display 1"
DEFAULT_FIRMWARE_POWER_MODE = "auto"
DEFAULT_FIRMWARE_WAKE_MINUTES = 30
DEFAULT_FIRMWARE_AWAKE_SECONDS = 90
DEFAULT_FIRMWARE_FLASH_LAYOUT = "legacy_4mb"

ENDPOINT_ORIGINAL_NAME = "GuestyTerminal Endpoint"
ENDPOINT_ENTITY_SUFFIX = "_guesty_terminal_endpoint"
DISPLAY_ACTION_SUFFIX = "_guesty_terminal_update_display"
DISPLAY_ACTION_V2_SUFFIX = "_guesty_terminal_update_display_v2"
DISPLAY_ACTION_V3_SUFFIX = "_guesty_terminal_update_display_v3"
DISPLAY_ACTION_V4_SUFFIX = "_guesty_terminal_update_display_v4"
DISPLAY_ACTION_V5_SUFFIX = "_guesty_terminal_update_display_v5"
DISPLAY_ACTION_V6_SUFFIX = "_guesty_terminal_update_display_v6"
DISPLAY_ACTION_V7_SUFFIX = "_guesty_terminal_update_display_v7"
DISPLAY_ACTION_V8_SUFFIX = "_guesty_terminal_update_display_v8"
DISPLAY_ACTION_V9_SUFFIX = "_guesty_terminal_update_display_v9"
DISPLAY_ACTION_V10_SUFFIX = "_guesty_terminal_update_display_v10"
DISPLAY_RECONNECT_STATE = "__guesty_reconnecting__"
DISPLAY_REFRESH_REQUEST_STATE = "__guesty_refresh_requested__"
DISPLAY_DELIVERY_RECEIVED_PREFIX = "__guesty_delivery_received__:"
DISPLAY_DELIVERY_RENDERING_PREFIX = "__guesty_delivery_rendering__:"
DISPLAY_DELIVERY_SUCCESS_PREFIX = "__guesty_delivery_success__:"
DISPLAY_DELIVERY_UNCHANGED_PREFIX = "__guesty_delivery_unchanged__:"
DISPLAY_DELIVERY_ERROR_PREFIX = "__guesty_delivery_error__:"

SERVICE_REFRESH = "refresh"
SERVICE_FORCE_REDRAW = "force_redraw"
TOKEN_STORE_VERSION = 1
TOKEN_REFRESH_MARGIN_SECONDS = 30 * 60

MODE_IDLE = "idle"
MODE_EMPTY = "empty"
MODE_WELCOME = "welcome"
MODE_CHECKOUT = "checkout"

SENSITIVE_DISPLAY_MODES = (MODE_WELCOME, MODE_CHECKOUT, MODE_EMPTY)
WEATHER_DISPLAY_MODES = (MODE_WELCOME, MODE_CHECKOUT)
LOGO_DISPLAY_MODES = (MODE_WELCOME, MODE_CHECKOUT)

ACTIVE_RESERVATION_STATUSES = ("confirmed",)
