"""Per-display language presets for guest-facing copy."""

from __future__ import annotations

from dataclasses import dataclass

from .const import DEFAULT_DISPLAY_LANGUAGE

DISPLAY_LANGUAGES = ("de", "en", "fr", "es")


@dataclass(frozen=True, slots=True)
class DisplayTextDefaults:
    """Default guest-facing copy for one supported display language."""

    welcome_title: str
    welcome_text: str
    idle_title: str
    idle_text: str
    door_code_label: str
    wifi_label: str
    wifi_name_label: str
    wifi_key_label: str
    checkout_label: str
    no_active_booking: str


_DEFAULTS = {
    "de": DisplayTextDefaults(
        welcome_title="Willkommen, {first_name}!",
        welcome_text=(
            "Schön, dass du da bist.\n"
            "Wir wünschen dir einen entspannten und angenehmen Aufenthalt."
        ),
        idle_title="Willkommen",
        idle_text="Die Unterkunft ist für den nächsten Aufenthalt bereit.",
        door_code_label="TÜRCODE",
        wifi_label="WIFI",
        wifi_name_label="Name:",
        wifi_key_label="Key:",
        checkout_label="Check-out:",
        no_active_booking="Keine aktive Buchung",
    ),
    "en": DisplayTextDefaults(
        welcome_title="Welcome, {first_name}!",
        welcome_text=(
            "It is great to have you here.\nWe wish you a relaxing and pleasant stay."
        ),
        idle_title="Welcome",
        idle_text="The property is ready for the next stay.",
        door_code_label="DOOR CODE",
        wifi_label="WIFI",
        wifi_name_label="Name:",
        wifi_key_label="Key:",
        checkout_label="Check-out:",
        no_active_booking="No active booking",
    ),
    "fr": DisplayTextDefaults(
        welcome_title="Bienvenue, {first_name} !",
        welcome_text=(
            "Nous sommes ravis de vous accueillir.\n"
            "Nous vous souhaitons un séjour agréable et reposant."
        ),
        idle_title="Bienvenue",
        idle_text="Le logement est prêt pour le prochain séjour.",
        door_code_label="CODE PORTE",
        wifi_label="WIFI",
        wifi_name_label="Nom :",
        wifi_key_label="Clé :",
        checkout_label="Départ :",
        no_active_booking="Aucune réservation active",
    ),
    "es": DisplayTextDefaults(
        welcome_title="¡Bienvenido, {first_name}!",
        welcome_text=(
            "Nos alegra tenerte aquí.\nTe deseamos una estancia agradable y relajante."
        ),
        idle_title="Bienvenido",
        idle_text="El alojamiento está listo para la próxima estancia.",
        door_code_label="CÓDIGO DE PUERTA",
        wifi_label="WIFI",
        wifi_name_label="Nombre:",
        wifi_key_label="Clave:",
        checkout_label="Salida:",
        no_active_booking="No hay ninguna reserva activa",
    ),
}


def normalize_display_language(
    value: object, *, fallback: str = DEFAULT_DISPLAY_LANGUAGE
) -> str:
    """Normalize Home Assistant locale strings to a supported language code."""
    language = str(value or "").strip().lower().replace("_", "-").split("-", 1)[0]
    if language in DISPLAY_LANGUAGES:
        return language
    return fallback if fallback in DISPLAY_LANGUAGES else DEFAULT_DISPLAY_LANGUAGE


def display_text_defaults(language: object) -> DisplayTextDefaults:
    """Return immutable presets for a supported display language."""
    return _DEFAULTS[normalize_display_language(language)]
