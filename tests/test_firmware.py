"""Tests for device-specific ESPHome configuration generation."""

from __future__ import annotations

import base64
import math
import re
import stat
from pathlib import Path

import pytest

from custom_components.guesty_terminal.firmware import (
    FIRMWARE_HEADER,
    FLASH_LAYOUT_EXPANDED,
    FLASH_LAYOUT_LEGACY,
    FirmwareConfigError,
    FirmwareFileExistsError,
    FirmwareFlashLayoutMigrationRequired,
    FirmwareOptions,
    render_firmware_config,
    update_managed_firmware_configs,
    write_firmware_config,
)

PACKAGE_FILE = (
    Path(__file__).parents[1]
    / "esphome"
    / "packages"
    / "reterminal-e1001-guesty-terminal.yaml"
)
DRIVER_FILE = (
    Path(__file__).parents[1]
    / "esphome"
    / "components"
    / "guesty_epaper_gray4"
    / "guesty_epaper_gray4.cpp"
)


def _options(**updates) -> FirmwareOptions:
    values = {
        "device_name": "guestyterminal-display-2",
        "friendly_name": "GuestyTerminal Display 2",
        "power_mode": "auto",
        "wake_interval_minutes": 30,
        "awake_seconds": 90,
        "flash_layout": FLASH_LAYOUT_EXPANDED,
    }
    values.update(updates)
    return FirmwareOptions(**values)


def test_render_firmware_config_is_secure_and_device_specific(monkeypatch) -> None:
    monkeypatch.setattr(
        "custom_components.guesty_terminal.firmware.secrets.token_bytes",
        lambda length: b"a" * length,
    )
    monkeypatch.setattr(
        "custom_components.guesty_terminal.firmware.secrets.token_hex",
        lambda length: "b" * (length * 2),
    )
    monkeypatch.setattr(
        "custom_components.guesty_terminal.firmware.secrets.token_urlsafe",
        lambda _length: "fallback-password-value",
    )

    rendered = render_firmware_config(_options())
    expected_key = base64.b64encode(b"a" * 32).decode()
    assert rendered.startswith(FIRMWARE_HEADER)
    assert "device_name: guestyterminal-display-2" in rendered
    assert 'friendly_name: "GuestyTerminal Display 2"' in rendered
    assert "power_mode: auto" in rendered
    assert "battery_sleep_duration: 30min" in rendered
    assert "usb_power_probe_interval" not in rendered
    assert f'key: "{expected_key}"' in rendered
    assert "ssid: !secret wifi_ssid" in rendered
    assert "password: !secret wifi_password" in rendered
    assert "client_secret" not in rendered
    assert "gray_lut_mode: auto" in rendered
    assert "gray_waveform_profile: lighter" in rendered
    assert 'gray_gamma: "1.35"' in rendered
    assert 'environment_temperature_offset: "0.0"' in rendered
    assert 'environment_humidity_offset: "0.0"' in rendered
    assert rendered.count("ref: v0.3.55") == 2
    assert "external_components:" in rendered
    assert "components:\n      - guesty_epaper_gray4" in rendered
    assert "guesty_power_wake" not in rendered
    assert "flash_layout: expanded_32mb" in rendered
    assert "flash_size: 32MB" in rendered
    assert "enable_idf_experimental_features: true" in rendered


def test_firmware_options_default_to_safe_legacy_flash_layout() -> None:
    options = FirmwareOptions(
        device_name="guestyterminal-display-3",
        friendly_name="GuestyTerminal Display 3",
    )

    assert options.validated().flash_layout == FLASH_LAYOUT_LEGACY


def test_display_package_uses_revision_aware_four_gray_rendering() -> None:
    package = PACKAGE_FILE.read_text(encoding="utf-8")

    assert package.count("bpp: 2") == 12
    assert "lut_mode: ${gray_lut_mode}" in package
    assert "gray_waveform_profile: ${gray_waveform_profile}" in package
    assert "gray_gamma: ${gray_gamma}" in package
    expected_revision = re.search(r"id\(guesty_render_revision\) == (\d+);", package)
    stored_revision = re.search(r"id\(guesty_render_revision\) = (\d+);", package)
    assert expected_revision is not None
    assert stored_revision is not None
    assert expected_revision.group(1) == "36"
    assert expected_revision.group(1) == stored_revision.group(1)
    assert "guesty_terminal_update_display_v10" in package
    assert (
        'std::string action = "${device_name}_guesty_terminal_update_display_v10";'
        in package
    )
    assert "    auto_clear_enabled: true\n" in package
    assert '"Bei Fragen sind wir für dich da."' not in package
    assert "id(guesty_logo_data).size() == logo_hex_length" in package
    assert "it.line(32, 402, 768, 402)" in package
    assert "it.rectangle(32, 250, 345, 105)" not in package
    assert "it.rectangle(qr_x - 10, qr_y - 10" not in package
    assert "it.filled_rectangle(qr_x - 10, qr_y - 10" not in package
    assert "draw_rounded_panel(32, 242, 360, 136, 12)" in package
    assert "draw_rounded_panel(408, 242, 360, 136, 12)" in package
    assert "id(guesty_door_code_label).c_str()" in package
    assert "id(guesty_wifi_label).c_str()" in package
    assert 'file: "gfonts://Inter@800"\n    id: guesty_font_label' in package
    assert "id(guesty_wifi_name_label).c_str()" in package
    assert "id(guesty_wifi_key_label).c_str()" in package
    assert "idle_title: string" in package
    assert "idle_text: string" in package
    assert "no_active_booking_label: string" in package
    assert "id(guesty_next_booking_title).empty()" in package
    assert "empty_title.c_str()" in package
    assert "id(guesty_idle_text).c_str()" in package
    assert "return id(guesty_no_active_booking_label)" in package
    assert "checkout_instructions_title: string" in package
    assert "checkout_instructions: string" in package
    assert "next_booking_title: string" in package
    assert "next_booking_guest: string" in package
    assert "next_booking_period: string" in package
    assert "general_notes_label: string" in package
    assert "general_notes: string" in package
    assert "cleaner_notes_label: string" in package
    assert "cleaner_notes: string" in package
    assert "special_requests_label: string" in package
    assert "special_requests: string" in package
    assert "id: guesty_checkout_page" in package
    assert "draw_rounded_panel(32, 218, 736, 154, 12)" in package
    assert "id(guesty_checkout_instructions_title).c_str()" in package
    assert "id(guesty_checkout_instructions)" in package
    assert "id: guesty_idle_page" in package
    idle_start = package.index("      - id: guesty_idle_page\n")
    idle_end = package.index("\ndeep_sleep:\n", idle_start)
    idle_page = package[idle_start:idle_end]
    assert "id(guesty_has_weather)" not in idle_page
    assert "id(guesty_weather_condition)" not in idle_page
    assert "id(guesty_font_battery_icon)" in idle_page
    assert "battery_codepoint_for_percent(" in idle_page
    assert "battery_percent, battery_charging" in idle_page
    assert "return 0xF008EUL" in idle_page
    for threshold, glyph in zip(
        range(20, 101, 10), range(0xF007A, 0xF0083), strict=True
    ):
        assert f"if (percent < {threshold}) return 0x{glyph:X}UL;" in idle_page
    assert "return 0xF0079UL" in idle_page
    assert "id(guesty_font_battery_icon).find_glyph(codepoint)" in idle_page
    assert "id(guesty_font_battery_icon).get_bpp()" in idle_page
    assert "esphome::progmem_read_byte(" in idle_page
    assert "const int destination_x = right - 1 - source_y" in idle_page
    assert "center_y - glyph->width / 2 + source_x" in idle_page
    assert "Color(ink, ink, ink)" in idle_page
    assert "it.printf(660, 24, id(guesty_font_weather_temperature)" in idle_page
    assert 'TextAlign::TOP_LEFT, "%d %%", battery_percent' in idle_page
    assert "id(guesty_display_battery_charging)" in idle_page
    assert "if (charging)" in idle_page
    assert "return 0xF0085UL" in idle_page
    assert "return 0xF089FUL" in idle_page
    assert "id: guesty_font_battery_icon\n    size: 36" in package
    assert "it.print(682, 26, id(guesty_font_battery_icon)" not in idle_page
    assert "id(guesty_display_battery_percent)" in idle_page
    assert "id(guesty_battery_only_changed)" in package
    assert "id(guesty_rendered_battery_percent)" in package
    assert 'const bool empty_page = mode != "welcome" && mode != "checkout"' in package
    assert "&& !empty_page;" in package
    assert "((rounded + 2) / 5) * 5" in package
    assert "const int note_count" in package
    assert "constexpr int cards_width = 736" in package
    assert "(cards_width - gap * (note_count - 1)) / note_count" in package
    assert "cards.push_back({id(guesty_special_requests_label)" in package
    assert "const int guest_y = note_count == 0 ? 190 : 142" in package
    assert "const int period_y = note_count == 0 ? 252 : 202" in package
    for sensitive_global in (
        "guesty_next_booking_guest",
        "guesty_next_booking_period",
        "guesty_general_notes",
        "guesty_cleaner_notes",
        "guesty_special_requests",
    ):
        start = package.index(f"  - id: {sensitive_global}\n")
        end = package.find("\n  - id:", start + 1)
        assert "restore_value: true" not in package[start:end]
    assert "detail_value_x(id(guesty_wifi_name_label))" in package
    assert "detail_value_x(id(guesty_wifi_key_label))" in package
    assert "const int qr_modules = id(guesty_wifi_qr).get_size()" in package
    assert "const int qr_margin = (136 - qr_size) / 2" in package
    assert "const int qr_x = 768 - qr_margin - qr_size" in package
    assert "MaterialDesign-Webfont/v7.4.47" in package
    battery_font_start = package.index("    id: guesty_font_battery_icon\n")
    weather_font_start = package.index("    id: guesty_font_weather_icon\n")
    battery_font = package[battery_font_start:weather_font_start]
    assert "    size: 36\n" in battery_font
    for glyph in range(0xF0079, 0xF0083):
        assert f'"\\U{glyph:08X}"' in battery_font
    assert '"\\U000F008E"' in battery_font
    for glyph in (0xF0085, 0xF0086, 0xF0087, 0xF0088, 0xF0089, 0xF008A, 0xF008B):
        assert f'"\\U{glyph:08X}"' in battery_font
    for glyph in (0xF089C, 0xF089D, 0xF089E, 0xF089F):
        assert f'"\\U{glyph:08X}"' in battery_font
    assert "id: guesty_font_weather_icon" in package
    assert 'return "\\U000F0599"' in package
    assert "draw_weather_icon" not in package
    assert "id(guesty_font_weather_temperature)" in package
    assert "base_content_id: string" in package
    assert "force_redraw: bool" in package
    assert "id(guesty_weather_only_changed)" in package
    assert "request_partial_update()" in package
    assert "partial_refresh:" in package
    assert "max_updates: 5" in package
    assert "on_client_connected:" in package
    assert 'state: "__guesty_reconnecting__"' in package
    reconnect_start = package.index("  on_client_connected:\n")
    reconnect_end = package.index("  actions:\n", reconnect_start)
    reconnect = package[reconnect_start:reconnect_end]
    assert reconnect.count("state_subscription_only: true") == 2
    assert "timeout: 20s" in reconnect
    subscribed_wait = reconnect.index("- wait_until:\n")
    reconnect_pulse = reconnect.index('state: "__guesty_reconnecting__"')
    restore_action = reconnect.index("component.update: guesty_terminal_endpoint")
    assert subscribed_wait < reconnect_pulse < restore_action
    assert "id: guesty_battery_level" in package
    assert "accuracy_decimals: 0" in package
    battery_voltage_start = package.index("    id: guesty_battery_voltage\n")
    battery_voltage_end = package.index(
        "  - platform: template\n    id: guesty_battery_level\n",
        battery_voltage_start,
    )
    battery_voltage = package[battery_voltage_start:battery_voltage_end]
    assert "samples: 16" in battery_voltage
    assert "sampling_mode: avg" in battery_voltage
    battery_level_end = package.index(
        "  - platform: template\n    id: guesty_awake_duration\n",
        battery_voltage_end,
    )
    battery_level = package[battery_voltage_end:battery_level_end]
    assert "method: exact" in battery_level
    assert "datapoints:" in battery_level
    assert battery_level.index("3.27 -> 0.0") < battery_level.index("4.15 -> 100.0")
    assert "id(guesty_charge_status_code) == 3" in battery_level
    assert "return charge_complete ? 4.15f" in battery_level
    assert "id: guesty_awake_duration" in package
    assert "lambda: return millis() / 1000.0f;" in package
    assert "id: guesty_wake_reason" in package
    assert "esp_sleep_get_wakeup_cause()" in package
    assert "id: guesty_reset_reason" in package
    assert "esp_reset_reason()" in package
    assert "id: guesty_refresh_display" in package
    assert "name: Display aktualisieren" in package
    refresh_start = package.index("    id: guesty_refresh_display\n")
    refresh_end = package.index("  - platform: restart\n", refresh_start)
    refresh_block = package[refresh_start:refresh_end]
    assert 'state: "__guesty_refresh_requested__"' in refresh_block
    assert "component.update: guesty_terminal_endpoint" in refresh_block
    assert "component.update: guesty_epaper" not in refresh_block
    assert "Page selection is runtime state and does not survive a reboot" in package
    v10_start = package.index("    - action: guesty_terminal_update_display_v10\n")
    v9_start = package.index(
        "    - action: guesty_terminal_update_display_v9\n", v10_start
    )
    v10_action = package[v10_start:v9_start]
    assert v10_action.index("Page selection is volatile") < v10_action.index(
        "return id(guesty_content_changed)"
    )
    assert "initial_value: '\"Willkommen\"'" not in package
    assert "initial_value: '\"Die Unterkunft ist bereit.\"'" not in package
    assert "id: guesty_restart" in package
    assert "name: Neustart" in package
    assert "- interval: 5min" in package
    assert "id: guesty_last_booking" in package
    assert "name: Angezeigte Buchung" in package
    assert "name: Display delivery status" in package
    assert "name: E-paper phase" in package
    assert "name: E-paper error" in package
    assert "name: E-paper waveform" in package
    assert "name: E-paper border mode" in package
    assert "last_update_successful()" in package
    assert 'state: "Keine aktive Buchung"' not in package
    assert "usb_power_probe_interval" not in package
    assert "id: guesty_enter_battery_sleep" in package
    assert "guesty_power_wake" not in package
    # Current v10, frozen v9 and the awake-window watchdog all route through
    # the same cleanup/sleep script.
    assert package.count("script.execute: guesty_enter_battery_sleep") == 3
    assert package.count("deep_sleep.enter: guesty_deep_sleep") == 1
    assert package.count("safe_mode.mark_successful") == 1
    assert "safe_mode:\n  boot_is_good_after: 10s" in package
    sleep_script_start = package.index("  - id: guesty_enter_battery_sleep\n")
    sleep_script_end = package.index(
        "  - id: guesty_read_external_power\n", sleep_script_start
    )
    sleep_script = package[sleep_script_start:sleep_script_end]
    assert "output.turn_off: guesty_battery_enable" in sleep_script
    assert "component.update: guesty_awake_duration" in sleep_script
    assert sleep_script.index("safe_mode.mark_successful") < sleep_script.index(
        "deep_sleep.enter: guesty_deep_sleep"
    )
    assert "sleep_duration: ${battery_sleep_duration}" in package
    assert "id: guesty_read_external_power" in package
    assert "id(guesty_external_power).publish_state(external_power)" in package
    gray_driver_path = (
        Path(__file__).parents[1]
        / "esphome"
        / "components"
        / "guesty_epaper_gray4"
        / "guesty_epaper_gray4.cpp"
    )
    gray_driver = gray_driver_path.read_text(encoding="utf-8")
    assert "RTC_DATA_ATTR static RetainedPartialFrame" in gray_driver
    assert "display_partial_" in gray_driver
    assert "retained_partial_frame.partial_count" in gray_driver
    assert "RTC_DATA_ATTR static RetainedLutSelection" in gray_driver
    assert "this->command_(0x90)" in gray_driver
    assert "this->command_(0x91)" in gray_driver
    assert "this->data_(0xA9)" in gray_driver
    assert "this->command_(0x12)" in gray_driver
    driver_path = (
        Path(__file__).parents[1]
        / "esphome"
        / "components"
        / "guesty_epaper_gray4"
        / "guesty_epaper_gray4.cpp"
    )
    driver = driver_path.read_text(encoding="utf-8")
    assert '"Framebuffer levels:' in driver
    assert "const uint8_t controller_gray = 3U - framebuffer_gray" in driver
    assert "0=black, 3=white" in driver
    assert "1U - ((first >>" not in driver
    assert "read_otp_profile_" in driver
    assert "BANK0_READ_LENGTH = 0x0BED" in driver
    assert "BANK1_READ_LENGTH = 0x17ED" in driver
    assert "BANK0_BASE = 0x0000" in driver
    assert "BANK1_BASE = 0x0C00" in driver
    assert "RETAINED_LUT_SELECTION_MAGIC" in driver
    assert "RETAINED_LUT_SELECTION_MAGIC = 0x47544C34UL" in driver
    assert "0x47544C33UL" not in driver
    assert "0x47544C32UL" not in driver
    assert "0x47544C31UL" not in driver
    assert "init_custom_gray_mode_" in driver
    assert "init_otp_gray_mode_" in driver
    assert "write_lut_(0x24, LUT_KK_GRAY" in driver
    assert "write_lut_(0x25" not in driver
    assert "border_lut_" not in driver
    assert "LUT_BORDER_GRAY" not in driver  # never bundle a panel OTP dump
    assert "write_plane_(0x10, 0)" in driver
    assert "write_plane_(0x13, 1)" in driver
    assert "inverted least-significant gray bit" in driver
    assert "inverted most-significant gray bit" in driver
    assert "GxEPD2" not in driver
    assert "Display BUSY never asserted" not in driver
    assert "wait_after_controller_command_" in driver
    assert "const bool successful = this->display_()" in driver
    assert "this->last_update_successful_.store(successful)" in driver
    assert "bool GuestyEPaperGray4::perform_full_refresh_(bool reset_panel)" in driver
    assert "bool GuestyEPaperGray4::recover_for_custom_fallback_()" in driver
    assert "const bool initialized = this->active_lut_mode_" in driver
    assert "return this->refresh_();" in driver
    assert (
        "if (!this->init_partial_mode_()) {\n    this->deep_sleep_panel_();" in driver
    )
    assert "Power-off timeout; attempting panel deep sleep anyway" in driver
    assert "this->panel_asleep_ = powered_off" in driver
    sleep = driver[driver.index("void GuestyEPaperGray4::deep_sleep_panel_()") :]
    power_off = sleep.index("this->command_(0x02)")
    wait_for_power_off = sleep.index('this->wait_until_idle_("after power off"')
    deep_sleep = sleep.index("this->command_(0x07)")
    assert power_off < wait_for_power_off < deep_sleep
    assert "this->command_(0x50)" not in sleep[:power_off]
    custom_init = driver[
        driver.index("bool GuestyEPaperGray4::init_custom_gray_mode_(") : driver.index(
            "bool GuestyEPaperGray4::init_otp_gray_mode_()"
        )
    ]
    border_register = custom_init.index("this->command_(0x50)")
    border_select = custom_init.index("this->data_(0x90)", border_register)
    border_interval = custom_init.index("this->data_(0x07)", border_select)
    end_voltage = custom_init.index("this->command_(0x52)", border_interval)
    end_value = custom_init.index("this->data_(0x00)", end_voltage)
    pixel_luts = custom_init.index("this->write_lut_(0x20", end_value)
    assert border_register < border_select < border_interval
    assert border_interval < end_voltage < end_value < pixel_luts
    header = driver_path.with_suffix(".h").read_text(encoding="utf-8")
    assert "bool last_update_successful() const" in header
    assert "bool update_in_progress() const" in header
    assert "const char *update_phase_name() const" in header
    assert "const char *last_error_name() const" in header
    assert "const char *active_lut_mode_name() const" in header
    assert "const char *border_mode_name() const" in header
    component_dir = driver_path.parent
    assert "MIT License" in (component_dir / "LICENSE").read_text(encoding="utf-8")
    seeed_gfx_license = (component_dir / "SEEED_GFX_LICENSE.txt").read_text(
        encoding="utf-8"
    )
    assert "Copyright (c) 2023 Bodmer" in seeed_gfx_license
    assert "Copyright (c) 2012 Adafruit Industries" in seeed_gfx_license


def test_wifi_qr_generation_has_stack_headroom_and_neutral_boot_value() -> None:
    """Avoid loop-task overflow and credential-like QR config logging."""
    package = PACKAGE_FILE.read_text(encoding="utf-8")

    assert (
        '"wjtje/qr-code-generator-library='
        "https://github.com/wjtje/QR-Code-generator-esphome.git#"
        '5f7449c095cf975bb14a34e1813b191205f78ccb"'
    ) in package
    assert package.count("loop_task_stack_size: 16384") == 1
    assert package.count("id(guesty_wifi_qr).set_value(qr_value);") == 2
    assert "id(guesty_wifi_qr).generate_qr_code();" not in package
    assert 'value: "GuestyTerminal"' in package
    assert "id: guesty_prepare_wifi_qr" in package
    assert package.count('set_value("GuestyTerminal")') >= 4
    assert package.index("component.update: guesty_epaper") < package.index(
        'set_value("GuestyTerminal")'
    )
    assert "WIFI:T:WPA;S:Guest;P:Guest" not in package
    assert package.count("id(guesty_wifi_qr).get_size()") == 1


def test_unused_sd_rail_is_explicitly_disabled_on_boot_and_sleep() -> None:
    package = PACKAGE_FILE.read_text(encoding="utf-8")

    assert "id: guesty_sd_power\n    pin: GPIO16" in package
    boot = package[package.index("esphome:\n") : package.index("\napi:\n")]
    assert "- output.turn_off: guesty_sd_power" in boot
    sleep_start = package.index("  - id: guesty_enter_battery_sleep\n")
    sleep_end = package.index("  - id: guesty_read_external_power\n", sleep_start)
    assert "- output.turn_off: guesty_sd_power" in package[sleep_start:sleep_end]


def test_panel_self_test_is_neutral_serialized_and_restores_payload() -> None:
    package = PACKAGE_FILE.read_text(encoding="utf-8")

    script_start = package.index("  - id: guesty_run_panel_self_test\n")
    script_end = package.index("  # The former ESPHome 7.50inv2 path", script_start)
    self_test = package[script_start:script_end]
    assert "id: guesty_self_test_page" in package
    assert '"Vier Graustufen · weißer Außenbereich · Teilrefresh"' in package
    assert "it.fill(COLOR_OFF)" in package
    assert "id(guesty_epaper).request_partial_update()" in self_test
    assert "id(guesty_epaper).last_update_was_partial()" in self_test
    assert "id(guesty_content_id).clear()" in self_test
    assert "id(guesty_self_test_saved_content_id)" in self_test
    assert "script.execute: guesty_restore_payload_page" in self_test
    assert "script.execute: guesty_prepare_wifi_qr" in self_test
    assert 'id(guesty_wifi_qr).set_value("GuestyTerminal")' in self_test
    assert self_test.count("timeout: 120s") == 3
    assert '"requires_external_power"' in self_test
    assert 'const std::string profile = "${power_mode}";' not in self_test
    assert self_test.count("id(guesty_external_power).state") >= 2
    assert "id(guesty_self_test_active)" in package
    assert "|| id(guesty_self_test_active);" in package
    assert "name: E-paper Hardwaretest" in package
    assert "name: E-paper self-test" in package


def test_default_entity_profile_exposes_only_everyday_entities() -> None:
    """Keep support diagnostics available locally without cluttering HA."""
    package = PACKAGE_FILE.read_text(encoding="utf-8")
    assert 'advanced_diagnostics_internal: "true"' in package

    def entity_block(entity_id: str) -> str:
        declaration = re.search(
            rf"(?m)^  - platform: [^\n]+\n    id: {re.escape(entity_id)}$", package
        )
        assert declaration is not None
        start = declaration.start()
        candidates = [
            position
            for marker in ("\n  - platform:", "\nbutton:\n", "\ntime:\n")
            if (position := package.find(marker, start + 1)) >= 0
        ]
        return package[start : min(candidates)]

    advanced_entities = (
        "guesty_battery_voltage",
        "guesty_awake_duration",
        "guesty_wake_reason",
        "guesty_reset_reason",
        "guesty_power_detection_method",
        "guesty_flash_layout",
        "guesty_delivery_status",
        "guesty_panel_phase",
        "guesty_panel_error",
        "guesty_waveform_mode",
        "guesty_border_mode",
        "guesty_self_test_status",
        "guesty_border_recovery_status",
        "guesty_microphone_status",
        "guesty_border_recovery",
    )
    for entity_id in advanced_entities:
        assert "internal: ${advanced_diagnostics_internal}" in entity_block(entity_id)

    everyday_entities = (
        "guesty_battery_level",
        "guesty_charging_status",
        "guesty_last_booking",
        "guesty_terminal_endpoint",
        "guesty_external_power",
        "guesty_refresh_display",
        "guesty_restart",
        "guesty_panel_self_test",
        "guesty_button_green",
        "guesty_button_middle",
        "guesty_button_left",
    )
    for entity_id in everyday_entities:
        assert "internal:" not in entity_block(entity_id)


def test_sound_level_is_a_private_mains_only_thirty_second_rms() -> None:
    """Measure locally only while confirmed external power is present."""
    package = PACKAGE_FILE.read_text(encoding="utf-8")

    assert "id: guesty_microphone_i2s\n    i2s_lrclk_pin: GPIO42" in package
    assert "id: guesty_microphone\n    i2s_audio_id: guesty_microphone_i2s" in package
    assert "pdm: true\n    i2s_din_pin: GPIO41" in package
    assert "    channel: left\n" in package
    assert "correct_dc_offset: true" in package
    microphone_start = package.index("microphone:\n")
    microphone_end = package.index("\noutput:\n", microphone_start)
    assert "on_data:" not in package[microphone_start:microphone_end]

    sound_level_start = package.index("  - platform: sound_level\n")
    sound_level_end = package.index("\ntext_sensor:\n", sound_level_start)
    sound_level = package[sound_level_start:sound_level_end]
    assert "passive: true" in sound_level
    assert "measurement_duration: 30s" in sound_level
    assert "microphone: guesty_microphone" in sound_level
    assert "id: guesty_sound_level_30_seconds" in sound_level
    assert "name: Relativer Schallpegel (30 Sekunden)" in sound_level
    assert "internal:" not in sound_level
    assert "peak:" not in sound_level
    assert "std::isfinite(x)" in sound_level
    assert 'id(guesty_microphone_status_value) = "running"' in sound_level

    external_power_start = package.index("    id: guesty_external_power\n")
    external_power_end = package.index("  - platform: gpio\n", external_power_start)
    external_power = package[external_power_start:external_power_end]
    assert "on_press:" in external_power
    assert "lambda: return id(guesty_component_setup_complete);" in external_power
    assert "id(guesty_microphone_start_attempts) = 0;" in external_power
    assert "script.execute: guesty_start_microphone" in external_power
    assert "on_release:" in external_power
    assert "script.stop: guesty_start_microphone" in external_power
    assert "script.stop: guesty_verify_microphone_window" in external_power
    assert "microphone.stop_capture: guesty_microphone" in external_power
    assert "return id(guesty_microphone).is_stopped();" in external_power
    assert "timeout: 500ms" in external_power
    assert "output.turn_off: guesty_microphone_power" in external_power

    start_script_start = package.index("  - id: guesty_start_microphone\n")
    start_script_end = package.index("  # A running I2S task alone", start_script_start)
    start_script = package[start_script_start:start_script_end]
    assert "output.turn_on: guesty_microphone_power" in start_script
    assert "id(guesty_microphone_start_attempts)++;" in start_script
    assert '"Starting PDM capture after component setup (attempt %u/3)"' in start_script
    assert "id(guesty_sound_level_30_seconds).publish_state(NAN);" in start_script
    assert "delay: 200ms" in start_script
    assert "binary_sensor.is_on: guesty_external_power" in start_script
    assert "microphone.capture: guesty_microphone" in start_script
    assert "id(guesty_microphone).is_running()" in start_script
    assert "id(guesty_microphone).is_failed()" in start_script
    assert "timeout: 5s" in start_script
    assert '"capture_start_timeout"' in start_script
    assert '"initialization_failed"' in start_script
    assert '"PDM capture reached the running state"' in start_script
    assert "script.execute: guesty_verify_microphone_window" in start_script

    verify_script_start = package.index("  - id: guesty_verify_microphone_window\n")
    verify_script_end = package.index(
        "  # Keep every battery sleep entry", verify_script_start
    )
    verify_script = package[verify_script_start:verify_script_end]
    assert "delay: 40s" in verify_script
    assert "id(guesty_sound_level_30_seconds).has_state()" in verify_script
    assert "std::isfinite(id(guesty_sound_level_30_seconds).state)" in verify_script
    assert '"no_valid_rms_value"' in verify_script
    assert '"PDM capture produced its first finite RMS value"' in verify_script

    assert "id: guesty_microphone_status" in package
    assert "name: Microphone status" in package
    assert "lambda: return {id(guesty_microphone_status_value)};" in package

    sleep_start = package.index("  - id: guesty_enter_battery_sleep\n")
    sleep_end = package.index("  - id: guesty_read_external_power\n", sleep_start)
    sleep_script = package[sleep_start:sleep_end]
    stop_position = sleep_script.index("microphone.stop_capture: guesty_microphone")
    stopped_position = sleep_script.index("return id(guesty_microphone).is_stopped();")
    power_off_position = sleep_script.index("output.turn_off: guesty_microphone_power")
    assert stop_position < stopped_position < power_off_position
    assert "script.stop: guesty_start_microphone" in sleep_script
    assert "script.stop: guesty_verify_microphone_window" in sleep_script

    late_boot_start = package.index("    - priority: -100\n")
    late_boot_end = package.index("\napi:\n", late_boot_start)
    late_boot = package[late_boot_start:late_boot_end]
    assert "component.update: guesty_microphone_status" in late_boot
    assert "id(guesty_component_setup_complete) = true;" in late_boot
    assert "id(guesty_microphone_start_attempts) = 0;" in late_boot
    assert "id(guesty_microphone).is_running()" in late_boot
    assert "script.execute: guesty_verify_microphone_window" in late_boot
    assert "script.execute: guesty_start_microphone" in late_boot

    interval_start = package.index("interval:\n")
    interval_block = package[interval_start:]
    assert "id(guesty_component_setup_complete)" in interval_block
    assert "!id(guesty_microphone).is_running()" in interval_block
    assert "!id(guesty_start_microphone).is_running()" in interval_block
    # A template binary sensor does not fire on_press for its first published
    # state. Attempt zero must therefore be eligible after the first completed
    # power observation when a unit boots with USB already connected.
    assert "id(guesty_microphone_start_attempts) > 0" not in interval_block
    assert "id(guesty_microphone_start_attempts) < 3" in interval_block
    assert "script.execute: guesty_start_microphone" in interval_block


def test_environment_sensor_is_smoothed_calibratable_and_mains_refreshed() -> None:
    """Keep factory calibration by default and avoid battery polling."""
    package = PACKAGE_FILE.read_text(encoding="utf-8")

    assert 'environment_temperature_offset: "0.0"' in package
    assert 'environment_humidity_offset: "0.0"' in package
    environment_start = package.index("  - platform: sht4x\n")
    environment_end = package.index("  # ESPHome computes RMS", environment_start)
    environment = package[environment_start:environment_end]
    assert "id: guesty_environment" in environment
    assert "precision: High" in environment
    assert "heater_max_duty: 0.0" in environment
    assert "update_interval: never" in environment
    assert "offset: ${environment_temperature_offset}" in environment
    assert "offset: ${environment_humidity_offset}" in environment
    assert environment.count("sliding_window_moving_average:") == 2
    assert environment.count("window_size: 3") == 2
    assert environment.count("send_every: 1") == 2
    assert environment.count("send_first_at: 1") == 2
    assert "min_value: 0.0" in environment
    assert "max_value: 100.0" in environment

    boot_start = package.index("    - priority: 600\n")
    boot_end = package.index("    - priority: 500\n", boot_start)
    assert "component.update: guesty_environment" in package[boot_start:boot_end]

    interval_start = package.index("  - interval: 5min\n")
    interval_end = package.index("  - interval: 15s\n", interval_start)
    environment_interval = package[interval_start:interval_end]
    assert "id(guesty_external_power).has_state()" in environment_interval
    assert "id(guesty_external_power).state" in environment_interval
    assert "component.update: guesty_environment" in environment_interval


def test_border_recovery_tracks_every_unconditioned_full_refresh() -> None:
    """Protect real full refreshes while leaving partial/unchanged frames alone."""
    package = PACKAGE_FILE.read_text(encoding="utf-8")
    script_start = package.index("  - id: guesty_run_border_recovery\n")
    script_end = package.index("  # Keep every battery sleep entry", script_start)
    recovery = package[script_start:script_end]

    assert "id(guesty_epaper).request_border_recovery()" in recovery
    assert "script.execute: guesty_restore_payload_page" in recovery
    assert "script.execute: guesty_prepare_wifi_qr" in recovery
    assert 'id(guesty_wifi_qr).set_value("GuestyTerminal")' in recovery
    assert "id(guesty_external_power).state" in recovery
    assert '"requires_external_power"' in recovery
    assert "timeout: 120s" in recovery
    assert "id(guesty_content_id).clear()" not in recovery
    assert "id(guesty_base_content_id).clear()" not in recovery
    assert "id(guesty_render_revision)" not in recovery
    assert "id(guesty_border_conditioning_revision) = 1" in recovery
    assert "name: E-paper Randkorrektur" in package
    assert "name: E-paper border recovery" in package
    assert package.count("request_border_recovery()") == 5
    assert (
        len(re.findall(r"id\(guesty_border_conditioning_revision\)\s*!= 1", package))
        == 4
    )
    assert "id(guesty_render_revision) != 31" not in package
    border_revision_start = package.index(
        "  - id: guesty_border_conditioning_revision\n"
    )
    border_revision_end = package.index("\n  - id:", border_revision_start + 1)
    border_revision = package[border_revision_start:border_revision_end]
    assert "restore_value: true" in border_revision
    assert package.count("last_update_was_partial()") >= 2
    assert package.count("id(guesty_border_conditioning_revision) = 0") >= 8
    assert "const bool partial_change" in package
    assert "&& (!partial_change" in package

    self_test_start = package.index("  - id: guesty_run_panel_self_test\n")
    self_test_end = package.index("  - id: guesty_run_border_recovery\n")
    self_test = package[self_test_start:self_test_end]
    restore = self_test.index('state: "restoring"')
    recovery_request = self_test.index("request_border_recovery()", restore)
    restore_update = self_test.index(
        "component.update: guesty_epaper", recovery_request
    )
    assert restore < recovery_request < restore_update

    assert package.count("fill_rounded(x, y, width, height, radius, light_gray)") == 3
    assert "fill_rounded(x + 2, y + 2" not in package
    assert "std::max(1, radius - 2), COLOR_OFF" not in package


def test_grayscale_tone_curve_uses_native_levels_without_spatial_dither() -> None:
    """Keep panel-native two-bit antialiasing without a visible pixel grid."""
    package = PACKAGE_FILE.read_text(encoding="utf-8")
    driver = DRIVER_FILE.read_text(encoding="utf-8")
    header = DRIVER_FILE.with_suffix(".h").read_text(encoding="utf-8")
    platform = DRIVER_FILE.with_name("display.py").read_text(encoding="utf-8")

    assert 'gray_gamma: "1.35"' in package
    assert "gray_waveform_profile: lighter" in package
    assert "cv.Optional(CONF_GRAY_GAMMA, default=1.35)" in platform
    assert "min=1.0, max=2.2" in platform
    assert "var.set_gray_gamma(config[CONF_GRAY_GAMMA])" in platform
    assert (
        "var.set_gray_waveform_profile(config[CONF_GRAY_WAVEFORM_PROFILE])" in platform
    )
    assert "float gray_gamma_{1.35f};" in header
    assert "GRAY_WAVEFORM_PROFILE_STANDARD" in header
    assert "GRAY_WAVEFORM_PROFILE_LIGHTER" in header
    assert "std::array<uint8_t, 256> tone_curve_{};" in header
    assert "std::pow(normalized, this->gray_gamma_)" in driver
    assert "static constexpr uint8_t BAYER_4X4[16]" not in driver
    assert "threshold < fraction" not in driver
    assert "color_to_dithered_panel_gray_" not in driver
    assert "color_to_panel_gray_(Color color)" in driver
    assert "return 3U - ink_level;" in driver
    assert package.count("const bool tone_curve_current") == 2
    assert package.count("|| !tone_curve_current") == 2
    assert package.count("const bool waveform_profile_current") == 2
    assert package.count("|| !waveform_profile_current") == 2
    assert package.count("&& waveform_profile_current") == 4
    assert package.count("id(guesty_rendered_gray_gamma_x100) =") == 2
    assert package.count("id(guesty_rendered_waveform_profile) =") == 2
    gamma_state_start = package.index("  - id: guesty_rendered_gray_gamma_x100\n")
    gamma_state_end = package.index("\n  - id:", gamma_state_start + 1)
    assert "restore_value: true" in package[gamma_state_start:gamma_state_end]
    profile_state_start = package.index("  - id: guesty_rendered_waveform_profile\n")
    profile_state_end = package.index("\n  - id:", profile_state_start + 1)
    assert "restore_value: true" in package[profile_state_start:profile_state_end]

    def rendered_level(coverage: int) -> int:
        return 3 - round(math.pow(coverage / 255, 1.35) * 3)

    assert rendered_level(0) == 3
    assert rendered_level(255) == 0
    assert rendered_level(85) == 2
    assert rendered_level(170) == 1


def test_firmware_flash_layout_requires_explicit_usb_migration(tmp_path) -> None:
    expanded = render_firmware_config(_options(flash_layout=FLASH_LAYOUT_EXPANDED))
    legacy = render_firmware_config(_options(flash_layout=FLASH_LAYOUT_LEGACY))
    assert "flash_size: 32MB" in expanded
    assert "flash_size: 4MB" in legacy
    assert "enable_idf_experimental_features: true" in expanded
    assert "enable_idf_experimental_features" not in legacy

    destination = tmp_path / "guestyterminal-display-2.yaml"
    # Model a managed pre-0.3.40 file: no explicit flash size means ESPHome's
    # historic 4 MB default and must never be inferred as expanded.
    pre_migration = legacy.replace("  flash_layout: legacy_4mb\n", "").replace(
        "  flash_size: 4MB\n", ""
    )
    destination.write_text(pre_migration, encoding="utf-8")
    destination.chmod(0o600)

    with pytest.raises(FirmwareFlashLayoutMigrationRequired):
        write_firmware_config(
            tmp_path,
            _options(flash_layout=FLASH_LAYOUT_EXPANDED),
            overwrite=True,
        )
    assert destination.read_text(encoding="utf-8") == pre_migration

    write_firmware_config(
        tmp_path,
        _options(flash_layout=FLASH_LAYOUT_EXPANDED),
        overwrite=True,
        confirm_usb_flash_migration=True,
    )
    migrated = destination.read_text(encoding="utf-8")
    assert "flash_layout: expanded_32mb" in migrated
    assert "flash_size: 32MB" in migrated


def test_v10_action_acknowledges_only_confirmed_panel_delivery() -> None:
    """Require bounded received/rendered/result signals for current firmware."""
    package = PACKAGE_FILE.read_text(encoding="utf-8")
    start = package.index("    - action: guesty_terminal_update_display_v10\n")
    end = package.index("    - action: guesty_terminal_update_display_v9\n", start)
    action = package[start:end]

    assert "supports_response: none" in action
    assert "batch_delay: 0ms" in package
    assert "delivery_id: string" in action
    assert "delivery_id.size() == 24" in action
    assert "character >= 'a' && character <= 'f'" in action
    assert "std::string(24, '0')" in action
    assert "id(guesty_active_delivery_id)" in action
    assert '"__guesty_delivery_received__:" + delivery_id' not in action
    assert '"__guesty_delivery_rendering__:" + delivery_id' not in action
    assert '"__guesty_delivery_success__:" + delivery_id' not in action
    assert "id(guesty_delivery_handler_busy)" in action
    assert "__guesty_delivery_received__:" in action
    assert "__guesty_delivery_rendering__:" in action
    assert "__guesty_delivery_success__:" in action
    assert "__guesty_delivery_unchanged__:" in action
    assert "__guesty_delivery_error__:" in action
    assert "timeout: 5s" in action
    assert "timeout: 120s" in action
    assert 'id(guesty_delivery_error) = "preparation_timeout"' in action
    assert 'id(guesty_delivery_error) = "panel_timeout"' in action
    assert 'id(guesty_delivery_error) = "panel_error"' in action
    assert "id(guesty_failed_content_id) = content_id" in action
    failed_suppression = (
        "id(guesty_failed_content_suppressed) =\n"
        "                            id(guesty_content_changed)\n"
        "                            && !force_redraw\n"
        "                            && !border_conditioning_needed\n"
        "                            && !content_id.empty()\n"
        "                            && content_id == id(guesty_failed_content_id);"
    )
    assert failed_suppression in action
    assert "!id(guesty_failed_content_suppressed)" in action
    assert "id(guesty_failed_content_id).clear()" in action
    suppressed_error = (
        "Unchanged payload suppressed after the previous E-paper panel error"
    )
    assert suppressed_error in action
    assert 'id(guesty_wifi_qr).set_value("GuestyTerminal")' in action
    assert "api.respond:" not in action
    assert action.index('publish_state("received")') < action.index("delay: 150ms")
    assert action.index("delay: 150ms") < action.index(
        "component.update: guesty_epaper"
    )
    assert action.index("__guesty_delivery_received__:") < action.index(
        "component.update: guesty_epaper"
    )
    assert action.index("component.update: guesty_epaper") < action.index(
        "last_update_successful()"
    )
    assert action.index("last_update_successful()") < action.index(
        "if (id(guesty_delivery_unchanged))"
    )
    # Failed v10 submissions must remain awake for the normal retry window;
    # only physical success or a proven unchanged image counts as delivered.
    success_check = action.index("last_update_successful()")
    update_received_positions = [
        match.start()
        for match in re.finditer(
            r"id\(guesty_update_received_this_boot\)\s*=\s*true", action
        )
    ]
    assert len(update_received_positions) == 2
    assert all(position > success_check for position in update_received_positions)
    assert action.index("id(guesty_delivery_handler_busy) = false") > action.index(
        "if (id(guesty_delivery_result))"
    )
    assert action.index("id(guesty_delivery_handler_busy) = false") < action.rindex(
        "component.update: guesty_terminal_endpoint"
    )
    assert "script.execute: guesty_enter_battery_sleep" in action
    assert "Failed payloads stay awake for a retry" in action


def test_panel_diagnostics_are_neutral_and_thread_safe() -> None:
    """Expose controller progress without copying payload or identifiers."""
    driver = DRIVER_FILE.read_text(encoding="utf-8")
    header = DRIVER_FILE.with_suffix(".h").read_text(encoding="utf-8")

    assert "std::atomic<uint8_t> update_phase_" in header
    assert "std::atomic<uint8_t> last_error_" in header
    assert "std::atomic<uint8_t> active_lut_diagnostic_" in header
    assert "std::atomic<uint8_t> border_mode_" in header
    assert "std::atomic<bool> border_recovery_requested_" in header
    assert 'return "busy_timeout";' in driver
    assert 'return "conditioning_mono_otp";' in driver
    assert 'return "lutkw_floating_end";' not in driver
    assert 'return "validated_lutbd";' not in driver
    assert 'return "high_z";' in driver
    assert "this->update_phase_.store(UPDATE_PHASE_TRANSFER)" in driver
    assert "this->update_phase_.store(UPDATE_PHASE_REFRESH)" in driver
    assert "this->last_error_.store(UPDATE_ERROR_BUSY_TIMEOUT)" in driver
    assert "this->active_lut_diagnostic_.store(LUT_MODE_AUTO)" in driver
    assert "this->border_mode_.store(BORDER_MODE_UNKNOWN)" in driver


def test_uc8179_uses_isolated_monochrome_border_conditioning() -> None:
    """Reproduce the old mono controller path, then restore four-gray output."""
    driver = DRIVER_FILE.read_text(encoding="utf-8")
    mono_start = driver.index("bool GuestyEPaperGray4::init_monochrome_border_mode_()")
    custom_start = driver.index("bool GuestyEPaperGray4::init_custom_gray_mode_()")
    otp_start = driver.index("bool GuestyEPaperGray4::init_otp_gray_mode_()")
    partial_start = driver.index("bool GuestyEPaperGray4::init_partial_mode_()")
    mono = driver[mono_start:custom_start]
    custom = driver[custom_start:otp_start]
    otp = driver[otp_start:partial_start]

    power_setting = mono.index("this->command_(0x01)")
    border_register = mono.index("this->command_(0x50)", power_setting)
    border_select = mono.index("this->data_(0x10)", border_register)
    tcon = mono.index("this->command_(0x60)", border_select)
    kw_mode = mono.index("this->command_(0x00)", tcon)
    kw_value = mono.index("this->data_(0x1F)", kw_mode)
    resolution = mono.index("this->command_(0x61)", kw_value)
    single_spi = mono.index("this->command_(0x15)", resolution)
    power_off = mono.index("this->command_(0x02)", single_spi)
    assert power_setting < border_register < border_select < tcon
    assert tcon < kw_mode < kw_value < resolution < single_spi < power_off
    assert "BORDER_MODE_CONDITIONING_MONO_OTP" in mono
    assert "this->command_(0x52)" not in mono
    assert "this->command_(0xE5)" not in mono
    assert "this->write_lut_(" not in mono

    border_register = custom.index("this->command_(0x50)")
    border_select = custom.index("this->data_(0x90)", border_register)
    border_interval = custom.index("this->data_(0x07)", border_select)
    end_voltage = custom.index("this->command_(0x52)", border_interval)
    end_value = custom.index("this->data_(0x00)", end_voltage)
    pixel_lut_start = custom.index("this->write_lut_(0x20", end_value)
    assert border_register < border_select < border_interval
    assert border_interval < end_voltage < end_value < pixel_lut_start
    assert "drive_border_white" not in custom
    assert "this->data_(0x10);" not in custom
    assert "BORDER_MODE_HIGH_Z" in custom
    assert "this->data_(0x00);" in custom
    assert "this->write_lut_(0x25" not in custom
    assert "this->data_(0x80)" not in custom

    otp_waveform = otp.index("this->data_(0x5F)")
    otp_prepare_register = otp.index("this->command_(0x50)")
    otp_prepare_value = otp.index("this->data_(0x90)", otp_prepare_register)
    otp_interval = otp.index("this->data_(0x07)", otp_prepare_value)
    assert otp_prepare_register < otp_prepare_value < otp_interval < otp_waveform
    assert (
        "this->command_(0x50);  // VCOM AND DATA INTERVAL\n"
        "  this->data_(0x90);     // BDZ=1, BDV ignored, DDX=00\n"
        "  this->data_(0x07);"
    ) in otp
    assert otp.count("this->command_(0x50)") == 1
    assert "this->command_(0x52)" not in otp
    assert "this->write_lut_(0x25" not in otp

    recovery = driver[
        driver.index(
            "bool GuestyEPaperGray4::perform_monochrome_border_recovery_()"
        ) : driver.index(
            "bool GuestyEPaperGray4::perform_full_refresh_(bool reset_panel)"
        )
    ]
    recovery_reset = recovery.index("this->reset_panel_()")
    recovery_init = recovery.index("this->init_monochrome_border_mode_()")
    recovery_power_on = recovery.index("this->command_(0x04)")
    recovery_transfer = recovery.index("this->write_monochrome_frame_(0x13, nullptr)")
    recovery_refresh = recovery.index("this->command_(0x12)")
    assert recovery_reset < recovery_init < recovery_power_on
    assert recovery_power_on < recovery_transfer < recovery_refresh
    assert "this->write_monochrome_frame_(0x10" not in recovery
    assert "this->write_plane_(" not in recovery
    assert "this->buffer_[" not in recovery

    full_refresh = driver[
        driver.index(
            "bool GuestyEPaperGray4::perform_full_refresh_(bool reset_panel)"
        ) : driver.index("bool GuestyEPaperGray4::recover_for_custom_fallback_()")
    ]
    reset = full_refresh.index("this->reset_panel_()")
    first_plane = full_refresh.index("this->write_plane_(0x10, 0)")
    second_plane = full_refresh.index("this->write_plane_(0x13, 1)")
    refresh = full_refresh.index("this->refresh_()")
    assert reset < first_plane < second_plane < refresh

    display = driver[
        driver.index("bool GuestyEPaperGray4::display_()") : driver.index(
            "void GuestyEPaperGray4::deep_sleep_panel_()"
        )
    ]
    mode_selection = display.index("this->select_lut_mode_()")
    conditioning = display.index("this->perform_monochrome_border_recovery_()")
    conditioning_shutdown = display.index("this->deep_sleep_panel_()", conditioning)
    selected_restore = display.index("this->active_lut_mode_ = selected_lut_mode")
    full_attempt = display.index("this->perform_full_refresh_()", selected_restore)
    fallback = display.index("this->recover_for_custom_fallback_()", full_attempt)
    retry = display.index("this->perform_full_refresh_(false)", fallback)
    retained_fallback = display.index(
        "retained_lut_selection.mode = LUT_MODE_CUSTOM", retry
    )
    shutdown = display.index("this->deep_sleep_panel_()", retained_fallback)
    assert mode_selection < conditioning < conditioning_shutdown
    assert conditioning_shutdown < selected_restore < full_attempt
    assert "ensure_custom_border_lut_" not in display
    assert full_attempt < fallback < retry < retained_fallback < shutdown
    assert "this->configured_lut_mode_ == LUT_MODE_AUTO" in display
    assert "this->active_lut_mode_ == LUT_MODE_OTP" in display
    assert "this->last_error_.load() == UPDATE_ERROR_BUSY_TIMEOUT" in display


def test_uc8179_otp_profile_is_bank_ordered_and_read_twice() -> None:
    """Retain a waveform decision only from a consistent selected OTP bank."""
    driver = DRIVER_FILE.read_text(encoding="utf-8")
    profile = driver[
        driver.index("bool GuestyEPaperGray4::read_otp_profile_(") : driver.index(
            "bool GuestyEPaperGray4::select_lut_mode_()"
        )
    ]

    bank0_reads = re.findall(
        r"read_otp_bank_\(\s*BANK0_READ_LENGTH, BANK0_BASE", profile
    )
    bank1_reads = re.findall(
        r"read_otp_bank_\(\s*BANK1_READ_LENGTH, BANK1_BASE", profile
    )
    assert len(bank0_reads) == 2
    assert len(bank1_reads) == 2
    assert profile.index("bank0_check_a == bank0_check_b") < profile.index(
        "if (probe_ok && bank0_checks_match && !bank0_valid)"
    )
    assert "VALID_BANK_CHECK_CODE = 0xA5" in profile
    assert "BORDER_OFFSET" not in driver
    assert "BORDER_LUT_LENGTH" not in DRIVER_FILE.with_suffix(".h").read_text(
        encoding="utf-8"
    )
    assert "std::memcmp(" not in profile
    assert "bank0_marker_a == 0x01" in profile
    assert "bank1_marker_a == 0x01" in profile
    assert "marker_1 == 0x01 || marker_2 == 0x01" not in driver
    assert "this->gpio_write_command_(0xA2)" in driver
    assert "this->gpio_write_command_(0xA0)" not in driver
    assert "this->gpio_write_command_(0xA1)" not in driver
    validation = profile.index("if (!bank0_checks_match")
    bank0_choice = profile.index("if (bank0_valid)", validation)
    bank1_fallback = profile.index("else if (bank1_valid)", bank0_choice)
    assert validation < bank0_choice < bank1_fallback
    assert "No valid UC8179 OTP bank; using register LUTs" in profile
    assert "write_lut_(0x25" not in driver


def test_panel_io_does_not_block_the_esphome_api_loop() -> None:
    """Keep long E-paper transactions away from reconnect delivery handling."""
    driver = DRIVER_FILE.read_text(encoding="utf-8")
    header = DRIVER_FILE.with_suffix(".h").read_text(encoding="utf-8")
    package = PACKAGE_FILE.read_text(encoding="utf-8")

    update_start = driver.index("void GuestyEPaperGray4::update()")
    worker_start = driver.index("void GuestyEPaperGray4::perform_prepared_update_()")
    update = driver[update_start:worker_start]
    worker_end = driver.index("void GuestyEPaperGray4::on_safe_shutdown()")
    worker = driver[worker_start:worker_end]
    assert "this->do_update_()" in update
    assert "xTaskCreate(" in update
    assert "this->display_()" not in update
    assert "this->display_()" in worker
    assert "update_in_progress_.store(false)" in worker
    assert "std::atomic<bool> update_in_progress_" in header
    assert "OTP_IDLE_TIMEOUT_MS = 3000" in header
    assert "RESET_IDLE_TIMEOUT_MS = 5000" in header
    assert "POWER_ON_IDLE_TIMEOUT_MS = 10000" in header
    assert "REFRESH_IDLE_TIMEOUT_MS = 45000" in header
    assert "POWER_OFF_IDLE_TIMEOUT_MS = 10000" in header
    assert driver.count("OTP_IDLE_TIMEOUT_MS") >= 3
    service_start = driver.index("void GuestyEPaperGray4::service_long_operation_()")
    service_end = driver.index("void GuestyEPaperGray4::on_safe_shutdown()")
    service = driver[service_start:service_end]
    assert "if (this->update_in_progress_.load())" in service
    assert "vTaskDelay(1)" in service
    assert service.index("    vTaskDelay(1);") < service.index("  App.feed_wdt();")
    assert driver.count("App.feed_wdt();") == 2
    for function_name in (
        "wait_until_idle_",
        "read_otp_bank_",
        "write_plane_",
        "write_monochrome_frame_",
    ):
        function_start = driver.index(f"GuestyEPaperGray4::{function_name}")
        function_end = driver.index("\n}", function_start)
        function = driver[function_start:function_end]
        assert "service_long_operation_()" in function
        assert "App.feed_wdt()" not in function

    action_start = package.index("    - action: guesty_terminal_update_display_v9")
    action_end = package.index("\nglobals:\n", action_start)
    action = package[action_start:action_end]
    first_mutation = action.index("id(guesty_update_received_this_boot) = true")
    initial_wait = action.index("return !id(guesty_self_test_active)")
    update_call = action.index("component.update: guesty_epaper", first_mutation)
    completion_wait = action.index(
        "lambda: return !id(guesty_epaper).update_in_progress();", update_call
    )
    success = action.index("last_update_successful()", completion_wait)
    assert initial_wait < first_mutation < update_call < completion_wait < success
    assert "delay: 7s" not in package


def test_uc8179_partial_refresh_and_shutdown_do_not_override_full_border() -> None:
    """Do not re-drive a corrected full-refresh border during shutdown."""
    driver = DRIVER_FILE.read_text(encoding="utf-8")
    partial_area = driver[
        driver.index("void GuestyEPaperGray4::set_partial_ram_area_()") : driver.index(
            "bool GuestyEPaperGray4::refresh_partial_()"
        )
    ]
    partial_refresh = driver[
        driver.index("bool GuestyEPaperGray4::refresh_partial_()") : driver.index(
            "bool GuestyEPaperGray4::display_partial_("
        )
    ]
    partial_init = driver[
        driver.index("bool GuestyEPaperGray4::init_partial_mode_()") : driver.index(
            "void GuestyEPaperGray4::write_plane_("
        )
    ]
    assert "this->border_mode_.store(BORDER_MODE_HIGH_Z)" in partial_init
    assert (
        "this->command_(0x50);  // N2OCP copies the new plane after refresh\n"
        "  this->data_(0x90);"
    ) in partial_init
    assert "this->data_(0x10);" not in partial_init
    assert "this->data_(0xA9);\n  this->data_(0x07);" in partial_area
    partial_setup = partial_refresh.index("this->set_partial_ram_area_()")
    partial_command = partial_refresh.index("this->command_(0x12)")
    assert partial_setup < partial_command

    shutdown = driver[driver.index("void GuestyEPaperGray4::deep_sleep_panel_()") :]
    power_off = shutdown.index("this->command_(0x02)")
    deep_sleep = shutdown.index("this->command_(0x07)", power_off)
    assert power_off < deep_sleep
    assert "this->command_(0x50)" not in shutdown[:power_off]
    # One POWER OFF establishes the retained-register state before the isolated
    # monochrome recovery; the other is the shared final shutdown path.
    assert driver.count("this->command_(0x02)") == 2


def test_grayscale_framebuffer_polarity_matches_uc8179_wire_format() -> None:
    """Keep ESPHome colors logical while inverting both controller DTM bits."""
    controller_codes = {
        "black": 3 - 0,
        "dark_gray": 3 - 1,
        "light_gray": 3 - 2,
        "white": 3 - 3,
    }

    assert controller_codes == {
        "black": 0b11,
        "dark_gray": 0b10,
        "light_gray": 0b01,
        "white": 0b00,
    }

    # Auto-clear fills every packed pixel with logical white (0b11). The
    # transfer inversion must therefore emit zeroes for both complete planes,
    # including the first and last byte of the first and last rows.
    white_framebuffer = bytes([0xFF]) * (800 * 480 // 4)
    edge_bytes = (
        white_framebuffer[:2],
        white_framebuffer[198:200],
        white_framebuffer[-200:-198],
        white_framebuffer[-2:],
    )
    for packed_edge in edge_bytes:
        for packed in packed_edge:
            controller_grays = [
                3 - ((packed >> shift) & 0x03) for shift in (6, 4, 2, 0)
            ]
            assert controller_grays == [0, 0, 0, 0]


def test_otp_probe_releases_and_reinitializes_the_esp32_spi_bus() -> None:
    """Prevent restoring only the device while its bus pins remain GPIOs."""
    package = PACKAGE_FILE.read_text(encoding="utf-8")
    driver = DRIVER_FILE.read_text(encoding="utf-8")

    release = re.search(
        r"bool GuestyEPaperGray4::release_spi_bus_for_gpio_read_\(\) \{(.*?)\n\}",
        driver,
        re.DOTALL,
    )
    restore = re.search(
        r"bool GuestyEPaperGray4::restore_spi_bus_after_gpio_read_\(\) \{(.*?)\n\}",
        driver,
        re.DOTALL,
    )
    assert release is not None
    assert restore is not None
    spi_config = package[package.index("spi:\n") : package.index("\ni2c:\n")]
    assert "interface: spi2" in spi_config
    assert release.group(1).index("this->spi_teardown()") < release.group(1).index(
        "spi_bus_free(SPI2_HOST)"
    )
    assert "this->spi_setup()" in release.group(1)  # release-failure recovery
    assert "spi_bus_initialize(SPI2_HOST" in restore.group(1)
    assert restore.group(1).index("spi_bus_initialize(SPI2_HOST") < restore.group(
        1
    ).index("this->spi_setup()")
    assert "this->spi_is_ready()" in restore.group(1)
    assert "bus_config.mosi_io_num = data_pin->get_pin();" in restore.group(1)
    assert "bus_config.miso_io_num = 8;" in restore.group(1)
    assert "bus_config.sclk_io_num = clock_pin->get_pin();" in restore.group(1)
    assert "bus_config.max_transfer_sz = 4092;" in restore.group(1)
    assert (
        "bus_config.flags = SPICOMMON_BUSFLAG_MASTER | SPICOMMON_BUSFLAG_SCLK;"
    ) in restore.group(1)
    assert "if (!this->release_spi_bus_for_gpio_read_())" in driver
    assert "if (!this->restore_spi_bus_after_gpio_read_())" in driver
    assert "if (this->is_failed())\n          return false;" in driver


def test_uc8179_power_on_and_refresh_use_the_seeed_busy_guard() -> None:
    """Wait 100 ms and then for idle without requiring a sampled BUSY edge."""
    driver = DRIVER_FILE.read_text(encoding="utf-8")
    helper = re.search(
        r"bool GuestyEPaperGray4::wait_after_controller_command_\("
        r"const char \*phase,\s*uint32_t timeout_ms\) \{(.*?)\n\}",
        driver,
        re.DOTALL,
    )
    assert helper is not None
    body = helper.group(1)
    assert body.index("delay(100)") < body.index("wait_until_idle_(phase, timeout_ms)")
    assert "BUSY never asserted" not in driver
    assert "assertion_started" not in driver
    for phase in (
        "after custom-LUT power on",
        "after OTP power on",
        "after partial power on",
        "during partial refresh",
        "during grayscale refresh",
    ):
        assert f'wait_after_controller_command_("{phase}",' in driver


def test_four_gray_tables_match_the_licensed_seeed_reference() -> None:
    """Pin the panel-sensitive MIT-licensed Seeed waveform bytes."""
    driver = DRIVER_FILE.read_text(encoding="utf-8")
    expected = {
        "LUT_VCOM_GRAY": (
            "00 00 06 08 07 01 00 06 0A 0B 0A 01 00 03 03 00 00 03 "
            "00 05 09 06 06 01 00 02 02 0A 0A 01 00 0A 11 06 07 01 "
            "00 02 01 02 01 01"
        ),
        "LUT_WW_GRAY": (
            "15 00 06 08 07 01 54 06 0A 0B 0A 01 90 03 03 00 00 03 "
            "2A 05 09 06 06 01 AA 02 02 0A 0A 01 00 0A 11 06 07 01 "
            "28 02 01 02 01 01"
        ),
        "LUT_KW_GRAY": (
            "2A 00 06 08 07 01 59 06 0A 0B 0A 01 90 03 03 00 00 03 "
            "5A 05 09 06 06 01 A8 02 02 0A 0A 01 45 0A 11 06 07 01 "
            "A8 02 01 02 01 01"
        ),
        "LUT_WK_GRAY": (
            "16 00 06 08 07 01 A0 06 0A 0B 0A 01 90 03 03 00 00 03 "
            "99 05 09 06 06 01 A0 02 02 0A 0A 01 40 0A 11 06 07 01 "
            "20 02 01 02 01 01"
        ),
        "LUT_KK_GRAY": (
            "26 00 06 08 07 01 6A 06 0A 0B 0A 01 90 03 03 00 00 03 "
            "65 05 09 06 06 01 50 02 02 0A 0A 01 10 0A 11 06 07 01 "
            "10 02 01 02 01 01"
        ),
    }

    for name, expected_hex in expected.items():
        match = re.search(
            rf"static constexpr uint8_t {name}\[42\] = \{{(.*?)\n\}};",
            driver,
            re.DOTALL,
        )
        assert match is not None
        actual = " ".join(re.findall(r"0x([0-9A-F]{2})", match.group(1)))
        assert actual == expected_hex


def test_lighter_profile_changes_only_the_final_light_gray_drive_selector() -> None:
    """Keep the first hardware experiment isolated from every other waveform."""
    driver = DRIVER_FILE.read_text(encoding="utf-8")
    header = DRIVER_FILE.with_suffix(".h").read_text(encoding="utf-8")
    platform = DRIVER_FILE.with_name("display.py").read_text(encoding="utf-8")

    def lut(name: str) -> list[int]:
        match = re.search(
            rf"static constexpr uint8_t {name}\[42\] = \{{(.*?)\n\}};",
            driver,
            re.DOTALL,
        )
        assert match is not None
        return [
            int(value, 16) for value in re.findall(r"0x([0-9A-F]{2})", match.group(1))
        ]

    standard = lut("LUT_KW_GRAY")
    lighter = lut("LUT_KW_GRAY_LIGHTER")
    white = lut("LUT_WW_GRAY")
    assert len(standard) == len(lighter) == 42
    assert [
        index
        for index, pair in enumerate(zip(standard, lighter, strict=True))
        if pair[0] != pair[1]
    ] == [36]
    assert standard[36] == 0xA8
    assert lighter[36] == white[36] == 0x28
    assert standard[37:] == lighter[37:]

    assert "CONF_GRAY_WAVEFORM_PROFILE" in platform
    assert '"lighter": GrayWaveformProfile.GRAY_WAVEFORM_PROFILE_LIGHTER' in platform
    assert "requires lut_mode 'auto' or 'custom'" in platform
    assert "void set_gray_waveform_profile(GrayWaveformProfile profile)" in header
    assert "uint8_t waveform_profile_id() const" in header
    assert "this->active_lut_mode_ = LUT_MODE_CUSTOM;" in driver
    assert '"custom_lighter"' in driver
    assert "? LUT_KW_GRAY_LIGHTER" in driver


def test_auto_power_detection_supports_both_e1001_hardware_revisions() -> None:
    package = PACKAGE_FILE.read_text(encoding="utf-8")

    quiesce_start = package.index("  - id: guesty_quiesce_uart0\n")
    restore_start = package.index("  - id: guesty_restore_uart0\n", quiesce_start)
    sleep_start = package.index("  - id: guesty_enter_battery_sleep\n", restore_start)
    power_start = package.index("  - id: guesty_read_external_power\n")
    power_end = package.index("\nfont:\n", power_start)
    quiesce_script = package[quiesce_start:restore_start]
    restore_script = package[restore_start:sleep_start]
    sleep_script = package[sleep_start:power_start]
    power_script = package[power_start:power_end]

    boot = package[:quiesce_start]
    assert boot.index("script.execute: guesty_quiesce_uart0") < boot.index(
        "priority: 700"
    )
    assert "(part_id & 0x78) != 0x40" in boot
    assert "id(guesty_sy6974_seen_this_boot) = true" in boot

    globals_start = package.index("\nglobals:\n")
    globals_block = package[globals_start:quiesce_start]
    detected_start = globals_block.index("  - id: guesty_sy6974_detected\n")
    detected_end = globals_block.index(
        "  - id: guesty_sy6974_seen_this_boot\n", detected_start
    )
    assert "restore_value: true" in globals_block[detected_start:detected_end]

    assert "mode: single" in quiesce_script
    assert "uart_is_driver_installed(UART_NUM_0)" in quiesce_script
    assert "logger->set_baud_rate(0)" in quiesce_script
    assert "uart_wait_tx_done(UART_NUM_0" in quiesce_script
    assert "gpio_reset_pin(GPIO_NUM_43)" in quiesce_script
    assert "gpio_pullup_dis(GPIO_NUM_43)" in quiesce_script
    assert "gpio_pulldown_dis(GPIO_NUM_43)" in quiesce_script
    assert "gpio_input_enable(GPIO_NUM_44)" in quiesce_script
    assert "gpio_pullup_dis(GPIO_NUM_44)" in quiesce_script
    assert "gpio_pulldown_en(GPIO_NUM_44)" in quiesce_script
    assert "gpio_pulldown_dis(GPIO_NUM_44)" not in quiesce_script
    first_low = quiesce_script.index("gpio_set_level(GPIO_NUM_43, 0)")
    output_enable = quiesce_script.index(
        "gpio_set_direction(GPIO_NUM_43, GPIO_MODE_OUTPUT)"
    )
    assert first_low < output_enable

    assert "mode: single" in restore_script
    assert "uart_is_driver_installed(UART_NUM_0)" in restore_script
    assert "uart_set_pin(" in restore_script
    assert "gpio_pulldown_dis(GPIO_NUM_44)" in restore_script
    assert "gpio_pullup_en(GPIO_NUM_44)" not in restore_script
    assert restore_script.index("uart_set_pin(") < restore_script.index(
        "logger->set_baud_rate(id(guesty_uart_logger_baud_rate))"
    )

    assert "script.execute: guesty_quiesce_uart0" in sleep_script
    assert sleep_script.index("script.wait: guesty_quiesce_uart0") < sleep_script.index(
        "deep_sleep.enter: guesty_deep_sleep"
    )

    assert "mode: single" in power_script
    assert "id(guesty_uart_logger_baud_rate) = 0" not in power_script
    assert power_script.index(
        "script.execute: guesty_quiesce_uart0"
    ) < power_script.index("count: 3")
    assert "delay: 60ms" in power_script
    assert "count: 3" in power_script
    assert "uint8_t reg = 0x0B" in power_script
    assert "(part_id & 0x78) == 0x40" in power_script
    assert "reg = 0x0A" in power_script
    assert "(status & 0x80) != 0" in power_script
    assert "reg = 0x08" in power_script
    assert "reg = 0x09" in power_script
    assert "(charge_status >> 3) & 0x03" in power_script
    assert "(fault_status & 0x30) != 0" in power_script
    assert "BUS_STAT" not in power_script
    assert "id(guesty_sy6974_seen_this_boot) = true" in power_script
    assert "id(guesty_sy6974_id_matches) == 3" in power_script
    assert "id(guesty_sy6974_detected) = true" in power_script
    assert "id(guesty_sy6974_status_reads) == 3" in power_script
    assert "id(guesty_sy6974_bus_good_reads) == 3" in power_script
    assert "id(guesty_sy6974_bus_good_reads) == 0" in power_script
    assert "&& !id(guesty_sy6974_seen_this_boot)" in power_script
    assert "gpio_get_level(GPIO_NUM_44)" in power_script
    assert "for (uint8_t sample = 0; sample < 64; sample++)" in power_script
    assert "high_samples >= 4" in power_script
    assert "id(guesty_usb_uart_powered_windows) == 3" in power_script
    assert "id(guesty_usb_uart_unpowered_windows) == 3" in power_script
    sample_position = power_script.index("gpio_get_level(GPIO_NUM_44)")
    restore_request = power_script.index("script.execute: guesty_restore_uart0")
    assert sample_position < restore_request
    restore_condition = power_script[
        power_script.rfind("      - if:", 0, restore_request) : restore_request
    ]
    assert "modern_external || legacy_external" in restore_condition
    assert "guesty_usb_uart_unpowered_windows" not in restore_condition
    assert "method_code = 1;  // SY6974B BUS_GD" in power_script
    assert "method_code = 2;  // USB-UART" in power_script
    assert "id(guesty_external_power_invalid_batches) >= 2" in power_script
    assert "publish_state(external_power)" in power_script
    assert "publish_state(false)" in power_script
    assert "publish_state((status & 0x80) != 0)" not in power_script
    assert "id(guesty_sy6974_charge_status_reads) == 3" in power_script
    assert "id(guesty_sy6974_charge_status_matches) == 3" in power_script
    assert "id(guesty_charge_status_invalid_batches) >= 2" in power_script
    assert 'charge_state = "complete"' in power_script
    assert "state != external_power" in power_script
    assert power_script.count("id(guesty_battery_level_refresh_requested) = true;") == 2
    assert "component.update: guesty_battery_level" in power_script

    detector_start = package.index("    id: guesty_power_detection_method\n")
    detector_end = package.index("  # This diagnostic state", detector_start)
    detector = package[detector_start:detector_end]
    assert "name: Power detection method" in detector
    assert "entity_category: diagnostic" in detector
    assert "update_interval: never" in detector

    charging_start = package.index("    id: guesty_charging_status\n")
    charging_end = package.index("  - platform: template\n", charging_start + 1)
    charging = package[charging_start:charging_end]
    assert "name: Battery charging status" in charging
    assert 'case -2: return {"unsupported"};' in charging
    assert 'case 3: return {"complete"};' in charging
    assert 'case 4: return {"charge_fault"};' in charging
    assert "internal:" not in charging


@pytest.mark.parametrize(
    ("reg08", "reg09", "expected"),
    [
        (0x00, 0x00, 0),
        (0x08, 0x00, 1),
        (0x10, 0x00, 2),
        (0x18, 0x00, 3),
        (0x18, 0x10, 4),
        (0x18, 0x08, 5),
        (0x18, 0x02, 6),
        # Battery and temperature faults take precedence over a generic
        # charging fault so the published status remains actionable.
        (0x18, 0x1A, 5),
    ],
)
def test_sy6974_charge_status_classifier(reg08: int, reg09: int, expected: int) -> None:
    """Mirror the firmware's privacy-safe REG08/REG09 classification."""
    charge_code = (reg08 >> 3) & 0x03
    if reg09 & 0x08:
        charge_code = 5
    elif reg09 & 0x07:
        charge_code = 6
    elif reg09 & 0x30:
        charge_code = 4

    assert charge_code == expected


@pytest.mark.parametrize(
    (
        "charger_detected",
        "charger_seen_this_boot",
        "status_reads",
        "bus_good",
        "uart_powered_windows",
        "uart_unpowered_windows",
        "expected",
    ),
    [
        (True, False, 3, 3, 0, 3, (True, True, "SY6974B BUS_GD")),
        (True, False, 3, 0, 3, 0, (True, False, "SY6974B BUS_GD")),
        (False, False, 0, 0, 3, 0, (True, True, "USB-UART")),
        (False, False, 0, 0, 0, 3, (True, False, "USB-UART")),
        (True, False, 3, 1, 3, 0, (False, False, "Unavailable")),
        # Once identified, a transient v1.2 status failure must not enter the
        # legacy path even when that path happens to read high.
        (True, False, 0, 0, 3, 0, (False, False, "Unavailable")),
        (True, False, 2, 2, 3, 0, (False, False, "Unavailable")),
        # A single exact part-ID match is already sticky for the current boot,
        # even before three matches persist the hardware revision.
        (False, True, 3, 3, 0, 3, (True, True, "SY6974B BUS_GD")),
        (False, True, 0, 0, 3, 0, (False, False, "Unavailable")),
        (False, False, 0, 0, 2, 1, (False, False, "Unavailable")),
    ],
)
def test_revision_aware_power_classifier_contract(
    charger_detected: bool,
    charger_seen_this_boot: bool,
    status_reads: int,
    bus_good: int,
    uart_powered_windows: int,
    uart_unpowered_windows: int,
    expected: tuple[bool, bool, str],
) -> None:
    """Exercise the documented decision table independently of hardware I/O."""
    valid = False
    external = False
    method = "Unavailable"
    charger_known = charger_detected or charger_seen_this_boot
    if charger_known and status_reads == 3:
        if bus_good == 3:
            valid, external, method = True, True, "SY6974B BUS_GD"
        elif bus_good == 0:
            valid, external, method = True, False, "SY6974B BUS_GD"
    elif not charger_known:
        if uart_powered_windows == 3:
            valid, external, method = True, True, "USB-UART"
        elif uart_unpowered_windows == 3:
            valid, external, method = True, False, "USB-UART"

    assert (valid, external, method) == expected


@pytest.mark.parametrize(
    ("previous_external", "invalid_batches", "expected_external", "expected_batches"),
    [
        (None, 0, False, 1),
        (False, 0, False, 1),
        (True, 0, True, 1),
        (True, 1, False, 2),
        (True, 2, False, 2),
    ],
)
def test_unresolved_power_measurements_fail_safe_after_one_retained_batch(
    previous_external: bool | None,
    invalid_batches: int,
    expected_external: bool,
    expected_batches: int,
) -> None:
    """Retain one confirmed cable observation, then fail safely to battery."""
    next_batches = min(2, invalid_batches + 1)
    was_confirmed = previous_external is True
    next_external = was_confirmed and next_batches < 2

    assert (next_external, next_batches) == (expected_external, expected_batches)


def test_battery_wake_cycle_cannot_wake_loop() -> None:
    package = PACKAGE_FILE.read_text(encoding="utf-8")

    action_start = package.index("    - action: guesty_terminal_update_display_v9\n")
    globals_start = package.index("\nglobals:\n", action_start)
    action = package[action_start:globals_start]
    final_power_read = action.rindex(
        "        - script.execute: guesty_read_external_power\n"
    )
    sleep_decision = action.rindex(
        '                const std::string profile = "${power_mode}";\n'
    )
    assert final_power_read < sleep_decision

    deep_sleep_start = package.index("\ndeep_sleep:\n")
    interval_start = package.index("\ninterval:\n", deep_sleep_start)
    deep_sleep = package[deep_sleep_start:interval_start]
    assert "wakeup_pin:\n" in deep_sleep
    assert "number: GPIO3" in deep_sleep
    assert "inverted: true" in deep_sleep
    assert "wakeup_pin_mode: INVERT_WAKEUP" in deep_sleep
    assert "esp32_ext1_wakeup" not in deep_sleep

    green_start = package.index("    id: guesty_button_green\n")
    middle_start = package.index(
        "  - platform: gpio\n    id: guesty_button_middle", green_start
    )
    green_button = package[green_start:middle_start]
    assert "on_press:" not in green_button

    interval = package[interval_start:]
    assert "id(guesty_update_received_this_boot)" in interval
    assert "static_cast<uint32_t>(${awake_duration_seconds})" in interval


def test_privacy_state_changes_only_after_a_successful_physical_refresh() -> None:
    package = PACKAGE_FILE.read_text(encoding="utf-8")

    action_start = package.index("    - action: guesty_terminal_update_display_v9\n")
    globals_start = package.index("\nglobals:\n", action_start)
    action = package[action_start:globals_start]
    first_update = action.index("              - component.update: guesty_epaper\n")
    success_check = action.index("last_update_successful()", first_update)
    privacy_commit = action.index(
        'id(guesty_screen_sensitive) = mode != "idle";', first_update
    )
    assert success_check < privacy_commit
    assert 'id(guesty_screen_sensitive) = mode != "idle";' not in action[:first_update]
    assert "&& !(id(guesty_privacy_clear_pending)" in action

    interval_start = package.index("\ninterval:\n", globals_start)
    interval = package[interval_start:]
    battery_clear = interval.index(
        'id(guesty_mode) = "idle";\n',
    )
    battery_update = interval.index(
        "                  - component.update: guesty_epaper\n", battery_clear
    )
    battery_success = interval.index("last_update_successful()", battery_update)
    battery_commit = interval.index(
        "id(guesty_screen_sensitive) = false;", battery_success
    )
    assert battery_update < battery_success < battery_commit
    assert (
        "id(guesty_screen_sensitive) = false;"
        not in interval[battery_clear:battery_update]
    )
    assert "return !id(guesty_screen_sensitive)" in interval
    assert "id(guesty_update_received_this_boot)" in interval
    assert 'id(guesty_mode) != "idle"' in interval
    assert "!id(guesty_privacy_clear_pending)" in interval
    assert "Privacy clear failed; keeping the device awake" in interval
    battery_wait = interval[battery_update:battery_success]
    assert "timeout: 120s" in battery_wait
    assert "!id(guesty_epaper).update_in_progress()" in battery_wait

    mains_clear = interval.index('id(guesty_mode) = "idle";', battery_commit)
    mains_update = interval.index(
        "            - component.update: guesty_epaper\n", mains_clear
    )
    mains_success = interval.index("last_update_successful()", mains_update)
    mains_commit = interval.index("id(guesty_screen_sensitive) = false;", mains_success)
    assert mains_update < mains_success < mains_commit
    assert (
        "id(guesty_screen_sensitive) = false;" not in interval[mains_clear:mains_update]
    )
    assert "Privacy clear failed; retrying while external power" in interval
    mains_wait = interval[mains_update:mains_success]
    assert "timeout: 120s" in mains_wait
    assert "!id(guesty_epaper).update_in_progress()" in mains_wait
    assert "&& (id(guesty_privacy_clear_pending)" in interval
    assert "id: guesty_privacy_clear_pending" in package
    lease_start = package.index("  - id: guesty_valid_until_epoch\n")
    lease_end = package.index("\n  - id:", lease_start + 1)
    assert "restore_value: true" not in package[lease_start:lease_end]
    assert "|| id(guesty_valid_until_epoch) == 0" in interval


def test_partial_refresh_rehydrates_both_complete_controller_planes() -> None:
    driver_path = (
        Path(__file__).parents[1]
        / "esphome"
        / "components"
        / "guesty_epaper_gray4"
        / "guesty_epaper_gray4.cpp"
    )
    driver = driver_path.read_text(encoding="utf-8")
    header = driver_path.with_suffix(".h").read_text(encoding="utf-8")

    assert "MONOCHROME_FRAME_LENGTH = WIDTH * HEIGHT / 8U" in header
    assert "write_monochrome_frame_(0x10, previous)" in driver
    assert "write_monochrome_frame_(0x13, current)" in driver
    assert "row < HEIGHT" in driver
    assert "column < BYTES_PER_ROW" in driver
    assert "partial_override[override_index]" in driver
    assert "write_partial_bitmap_" not in driver
    assert "this->command_(0x91)" in driver
    assert "this->data_(0xA9)" in driver
    assert "both %lu-byte controller planes" in driver


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"device_name": "Invalid Name"}, "Device name"),
        ({"friendly_name": ""}, "Friendly name"),
        ({"power_mode": "magic"}, "power mode"),
        ({"wake_interval_minutes": 4}, "Wake interval"),
        ({"awake_seconds": 10}, "Awake time"),
        ({"flash_layout": "unsafe"}, "flash layout"),
    ],
)
def test_firmware_options_reject_invalid_values(updates, message) -> None:
    with pytest.raises(FirmwareConfigError, match=message):
        _options(**updates).validated()


def test_write_firmware_config_is_atomic_and_protects_user_files(tmp_path) -> None:
    destination = write_firmware_config(tmp_path, _options())
    assert destination.name == "guestyterminal-display-2.yaml"
    original = destination.read_text(encoding="utf-8")
    assert original.startswith(FIRMWARE_HEADER)
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert not list(tmp_path.glob("*.tmp"))

    with pytest.raises(FirmwareFileExistsError):
        write_firmware_config(tmp_path, _options())

    replaced = write_firmware_config(
        tmp_path,
        _options(wake_interval_minutes=45, power_mode="battery"),
        overwrite=True,
    )
    assert replaced == destination
    updated = destination.read_text(encoding="utf-8")
    assert "battery_sleep_duration: 45min" in updated
    original_api_key = next(line for line in original.splitlines() if "key:" in line)
    assert original_api_key in updated

    destination.write_text(f"{FIRMWARE_HEADER}\n# malformed\n", encoding="utf-8")
    with pytest.raises(FirmwareFileExistsError):
        write_firmware_config(tmp_path, _options(), overwrite=True)

    destination.write_text("# User-owned ESPHome configuration\n", encoding="utf-8")
    with pytest.raises(FirmwareFileExistsError):
        write_firmware_config(tmp_path, _options(), overwrite=True)
    assert destination.read_text(encoding="utf-8").startswith("# User-owned")


def test_update_managed_firmware_configs_preserves_credentials_and_permissions(
    tmp_path,
) -> None:
    managed = tmp_path / "display.yaml"
    old_content = render_firmware_config(_options()).replace("0.3.55", "0.3.10")
    managed.write_text(old_content, encoding="utf-8")
    managed.chmod(0o600)
    user_owned = tmp_path / "other.yaml"
    user_owned.write_text("# User-owned\nesphome:\n", encoding="utf-8")

    result = update_managed_firmware_configs(tmp_path)

    assert [(item.path.name, item.changed) for item in result] == [
        ("display.yaml", True)
    ]
    updated = managed.read_text(encoding="utf-8")
    assert updated.count("ref: v0.3.55") == 2
    assert 'version: "0.3.55"' in updated
    assert "guesty_power_wake" not in updated
    assert next(line for line in old_content.splitlines() if "key:" in line) in updated
    assert stat.S_IMODE(managed.stat().st_mode) == 0o600
    assert user_owned.read_text(encoding="utf-8").startswith("# User-owned")
    assert not list(tmp_path.glob("*.tmp"))

    repeated = update_managed_firmware_configs(tmp_path)
    assert [(item.path.name, item.changed) for item in repeated] == [
        ("display.yaml", False)
    ]

    managed.chmod(0o644)
    secured = update_managed_firmware_configs(tmp_path)
    assert [(item.path.name, item.changed) for item in secured] == [
        ("display.yaml", True)
    ]
    assert stat.S_IMODE(managed.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "broken_line",
    (
        '    key: "not-a-valid-api-key"',
        '    password: "short"',
        '    password: "tiny"',
    ),
)
def test_update_managed_firmware_configs_rejects_invalid_credentials(
    tmp_path, broken_line
) -> None:
    valid = render_firmware_config(_options()).replace("0.3.55", "0.3.10")
    if "key:" in broken_line:
        invalid = valid.replace(
            next(line for line in valid.splitlines() if "key:" in line), broken_line
        )
    elif "short" in broken_line:
        invalid = valid.replace(
            next(
                line
                for line in valid.splitlines()
                if line.strip().startswith("password:") and "!secret" not in line
            ),
            broken_line,
            1,
        )
    else:
        invalid = valid.replace(
            next(
                line
                for line in reversed(valid.splitlines())
                if line.strip().startswith("password:")
            ),
            broken_line,
            1,
        )
    managed = tmp_path / "display.yaml"
    managed.write_text(invalid, encoding="utf-8")

    with pytest.raises(FirmwareConfigError, match="invalid credentials"):
        update_managed_firmware_configs(tmp_path)
    assert managed.read_text(encoding="utf-8") == invalid


def test_update_managed_firmware_configs_never_downgrades_or_partially_writes(
    tmp_path,
) -> None:
    future = tmp_path / "future.yaml"
    future_content = render_firmware_config(_options()).replace("0.3.55", "0.4.0")
    future.write_text(future_content, encoding="utf-8")
    future.chmod(0o600)
    assert update_managed_firmware_configs(tmp_path)[0].changed is False
    assert future.read_text(encoding="utf-8") == future_content

    old = tmp_path / "a-old.yaml"
    old_content = render_firmware_config(_options()).replace("0.3.55", "0.3.9")
    old.write_text(old_content, encoding="utf-8")
    malformed = tmp_path / "z-malformed.yaml"
    malformed.write_text(f"{FIRMWARE_HEADER}\n# malformed\n", encoding="utf-8")
    with pytest.raises(FirmwareConfigError, match="malformed"):
        update_managed_firmware_configs(tmp_path)
    assert old.read_text(encoding="utf-8") == old_content

    assert update_managed_firmware_configs(tmp_path / "missing") == []
