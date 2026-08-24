"""Tests for device-specific ESPHome configuration generation."""

from __future__ import annotations

import base64
import stat
from pathlib import Path

import pytest

from custom_components.guesty_terminal.firmware import (
    FIRMWARE_HEADER,
    FirmwareConfigError,
    FirmwareFileExistsError,
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


def _options(**updates) -> FirmwareOptions:
    values = {
        "device_name": "guestyterminal-display-2",
        "friendly_name": "GuestyTerminal Display 2",
        "power_mode": "auto",
        "wake_interval_minutes": 30,
        "awake_seconds": 90,
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
    assert rendered.count("ref: v0.3.30") == 2
    assert "external_components:" in rendered
    assert "components:\n      - guesty_epaper_gray4" in rendered
    assert "guesty_power_wake" not in rendered


def test_display_package_uses_revision_aware_four_gray_rendering() -> None:
    package = PACKAGE_FILE.read_text(encoding="utf-8")

    assert package.count("bpp: 2") == 12
    assert "lut_mode: ${gray_lut_mode}" in package
    assert "id(guesty_render_revision) == 21" in package
    assert "guesty_terminal_update_display_v9" in package
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
    assert "battery_codepoint_for_percent(battery_percent)" in idle_page
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
    assert "768, 38, battery_codepoint_for_percent(battery_percent)" in idle_page
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
    assert "id: guesty_awake_duration" in package
    assert "lambda: return millis() / 1000.0f;" in package
    assert "id: guesty_wake_reason" in package
    assert "esp_sleep_get_wakeup_cause()" in package
    assert "id: guesty_refresh_display" in package
    assert "name: Display aktualisieren" in package
    refresh_start = package.index("    id: guesty_refresh_display\n")
    refresh_end = package.index("  - platform: restart\n", refresh_start)
    refresh_block = package[refresh_start:refresh_end]
    assert 'state: "__guesty_refresh_requested__"' in refresh_block
    assert "component.update: guesty_terminal_endpoint" in refresh_block
    assert "component.update: guesty_epaper" not in refresh_block
    assert "Page selection is runtime state and does not survive a reboot" in package
    assert package.index("Page selection is runtime state") < package.index(
        "lambda: return id(guesty_content_changed);"
    )
    assert "initial_value: '\"Willkommen\"'" not in package
    assert "initial_value: '\"Die Unterkunft ist bereit.\"'" not in package
    assert "id: guesty_restart" in package
    assert "name: Neustart" in package
    assert "- interval: 5min" in package
    assert "id: guesty_last_booking" in package
    assert "name: Angezeigte Buchung" in package
    assert "last_update_successful()" in package
    assert 'state: "Keine aktive Buchung"' not in package
    assert "usb_power_probe_interval" not in package
    assert "id: guesty_enter_battery_sleep" in package
    assert "guesty_power_wake" not in package
    assert package.count("script.execute: guesty_enter_battery_sleep") == 2
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
    assert "id(guesty_external_power).publish_state(true)" in package
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
    assert "this->command_(0x90)" in gray_driver
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
    assert "00=black, 01=dark gray, 10=light gray, 11=white" in driver
    assert "1U - ((first >>" not in driver
    assert "probe_otp_support_" not in driver
    assert "write_lut_(0x25, LUT_BORDER_GRAY" in driver
    assert "write_plane_(0x10, 1)" in driver
    assert "write_plane_(0x13, 0)" in driver
    assert "Display BUSY never asserted" in driver
    assert "this->last_update_successful_ = this->display_()" in driver
    assert "if (!this->reset_panel_()) {\n    this->deep_sleep_panel_();" in driver
    assert "if (!this->init_gray_mode_()) {\n    this->deep_sleep_panel_();" in driver
    assert (
        "if (!this->init_partial_mode_()) {\n    this->deep_sleep_panel_();" in driver
    )
    assert "Power-off timeout; attempting panel deep sleep anyway" in driver
    assert "this->panel_asleep_ = powered_off" in driver
    header = driver_path.with_suffix(".h").read_text(encoding="utf-8")
    assert "bool last_update_successful() const" in header


def test_battery_wake_cycle_requires_confirmed_bus_good_and_cannot_wake_loop() -> None:
    package = PACKAGE_FILE.read_text(encoding="utf-8")

    power_start = package.index("  - id: guesty_read_external_power\n")
    power_end = package.index("\nfont:\n", power_start)
    power_script = package[power_start:power_end]
    assert "count: 3" in power_script
    assert "uint8_t reg = 0x0A" in power_script
    assert "const bool bus_good = (status & 0x80) != 0" in power_script
    assert "uint8_t reg = 0x08" not in power_script
    assert "bus_status" not in power_script
    assert "id(guesty_external_power_valid_reads) == 3" in power_script
    assert "id(guesty_external_power_invalid_batches) >= 2" in power_script
    assert "publish_state(true)" in power_script
    assert "publish_state(false)" in power_script
    assert "publish_state((status & 0x80) != 0)" not in power_script

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
    assert "this->command_(0x91)" not in driver
    assert "both %lu-byte controller planes" in driver


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"device_name": "Invalid Name"}, "Device name"),
        ({"friendly_name": ""}, "Friendly name"),
        ({"power_mode": "magic"}, "power mode"),
        ({"wake_interval_minutes": 4}, "Wake interval"),
        ({"awake_seconds": 10}, "Awake time"),
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
    old_content = render_firmware_config(_options()).replace("0.3.30", "0.3.10")
    managed.write_text(old_content, encoding="utf-8")
    managed.chmod(0o600)
    user_owned = tmp_path / "other.yaml"
    user_owned.write_text("# User-owned\nesphome:\n", encoding="utf-8")

    result = update_managed_firmware_configs(tmp_path)

    assert [(item.path.name, item.changed) for item in result] == [
        ("display.yaml", True)
    ]
    updated = managed.read_text(encoding="utf-8")
    assert updated.count("ref: v0.3.30") == 2
    assert 'version: "0.3.30"' in updated
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
    valid = render_firmware_config(_options()).replace("0.3.30", "0.3.10")
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
    future_content = render_firmware_config(_options()).replace("0.3.30", "0.4.0")
    future.write_text(future_content, encoding="utf-8")
    future.chmod(0o600)
    assert update_managed_firmware_configs(tmp_path)[0].changed is False
    assert future.read_text(encoding="utf-8") == future_content

    old = tmp_path / "a-old.yaml"
    old_content = render_firmware_config(_options()).replace("0.3.30", "0.3.9")
    old.write_text(old_content, encoding="utf-8")
    malformed = tmp_path / "z-malformed.yaml"
    malformed.write_text(f"{FIRMWARE_HEADER}\n# malformed\n", encoding="utf-8")
    with pytest.raises(FirmwareConfigError, match="malformed"):
        update_managed_firmware_configs(tmp_path)
    assert old.read_text(encoding="utf-8") == old_content

    assert update_managed_firmware_configs(tmp_path / "missing") == []
