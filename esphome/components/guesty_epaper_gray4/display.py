"""ESPHome display platform for the E1001's four-level grayscale panel."""

import esphome.codegen as cg
import esphome.config_validation as cv
from esphome.const import (
    CONF_BUSY_PIN,
    CONF_DC_PIN,
    CONF_ID,
    CONF_LAMBDA,
    CONF_PAGES,
    CONF_RESET_DURATION,
    CONF_RESET_PIN,
)

from esphome import core, pins
from esphome.components import display, spi

DEPENDENCIES = ["spi"]

CONF_CLOCK_PIN = "clock_pin"
CONF_DATA_PIN = "data_pin"
CONF_GRAY_GAMMA = "gray_gamma"
CONF_LUT_MODE = "lut_mode"
CONF_PARTIAL_REFRESH = "partial_refresh"
CONF_X = "x"
CONF_Y = "y"
CONF_WIDTH = "width"
CONF_HEIGHT = "height"
CONF_MAX_UPDATES = "max_updates"


def _validate_partial_refresh(config):
    """Keep the retained monochrome window bounded and byte aligned."""
    if config[CONF_X] + config[CONF_WIDTH] > 800:
        raise cv.Invalid("partial refresh window exceeds display width")
    if config[CONF_Y] + config[CONF_HEIGHT] > 480:
        raise cv.Invalid("partial refresh window exceeds display height")
    if config[CONF_X] % 8 or config[CONF_WIDTH] % 8:
        raise cv.Invalid("partial refresh x and width must be multiples of 8")
    if config[CONF_WIDTH] * config[CONF_HEIGHT] // 8 > 2048:
        raise cv.Invalid("partial refresh window exceeds the 2048-byte limit")
    return config


PARTIAL_REFRESH_SCHEMA = cv.All(
    cv.Schema(
        {
            cv.Required(CONF_X): cv.int_range(min=0, max=799),
            cv.Required(CONF_Y): cv.int_range(min=0, max=479),
            cv.Required(CONF_WIDTH): cv.int_range(min=8, max=800),
            cv.Required(CONF_HEIGHT): cv.int_range(min=1, max=480),
            cv.Optional(CONF_MAX_UPDATES, default=5): cv.int_range(min=1, max=20),
        }
    ),
    _validate_partial_refresh,
)

guesty_epaper_gray4_ns = cg.esphome_ns.namespace("guesty_epaper_gray4")
GuestyEPaperGray4 = guesty_epaper_gray4_ns.class_(
    "GuestyEPaperGray4",
    cg.PollingComponent,
    spi.SPIDevice,
    display.DisplayBuffer,
)
LutMode = guesty_epaper_gray4_ns.enum("LutMode")
LUT_MODES = {
    "auto": LutMode.LUT_MODE_AUTO,
    "custom": LutMode.LUT_MODE_CUSTOM,
    "otp": LutMode.LUT_MODE_OTP,
}

CONFIG_SCHEMA = cv.All(
    display.FULL_DISPLAY_SCHEMA.extend(
        {
            cv.GenerateID(): cv.declare_id(GuestyEPaperGray4),
            cv.Required(CONF_DC_PIN): pins.gpio_output_pin_schema,
            cv.Required(CONF_RESET_PIN): pins.gpio_output_pin_schema,
            cv.Required(CONF_BUSY_PIN): pins.gpio_input_pin_schema,
            cv.Required(CONF_CLOCK_PIN): pins.gpio_output_pin_schema,
            cv.Required(CONF_DATA_PIN): pins.gpio_output_pin_schema,
            cv.Optional(CONF_GRAY_GAMMA, default=1.35): cv.float_range(
                min=1.0, max=2.2
            ),
            cv.Optional(CONF_LUT_MODE, default="auto"): cv.enum(LUT_MODES, lower=True),
            cv.Optional(CONF_PARTIAL_REFRESH): PARTIAL_REFRESH_SCHEMA,
            cv.Optional(CONF_RESET_DURATION): cv.All(
                cv.positive_time_period_milliseconds,
                cv.Range(max=core.TimePeriod(milliseconds=500)),
            ),
        }
    )
    .extend(cv.polling_component_schema("never"))
    .extend(spi.spi_device_schema()),
    cv.has_at_most_one_key(CONF_PAGES, CONF_LAMBDA),
)

FINAL_VALIDATE_SCHEMA = spi.final_validate_device_schema(
    "guesty_epaper_gray4", require_miso=False, require_mosi=True
)


async def to_code(config):
    """Generate the display component and connect its configured pins."""
    var = cg.new_Pvariable(config[CONF_ID])

    await display.register_display(var, config)
    await spi.register_spi_device(var, config, write_only=True)

    dc_pin = await cg.gpio_pin_expression(config[CONF_DC_PIN])
    cg.add(var.set_dc_pin(dc_pin))
    reset_pin = await cg.gpio_pin_expression(config[CONF_RESET_PIN])
    cg.add(var.set_reset_pin(reset_pin))
    busy_pin = await cg.gpio_pin_expression(config[CONF_BUSY_PIN])
    cg.add(var.set_busy_pin(busy_pin))
    clock_pin = await cg.gpio_pin_expression(config[CONF_CLOCK_PIN])
    cg.add(var.set_clock_pin(clock_pin))
    data_pin = await cg.gpio_pin_expression(config[CONF_DATA_PIN])
    cg.add(var.set_data_pin(data_pin))
    cg.add(var.set_gray_gamma(config[CONF_GRAY_GAMMA]))
    cg.add(var.set_lut_mode(config[CONF_LUT_MODE]))

    if partial := config.get(CONF_PARTIAL_REFRESH):
        cg.add(
            var.set_partial_refresh_window(
                partial[CONF_X],
                partial[CONF_Y],
                partial[CONF_WIDTH],
                partial[CONF_HEIGHT],
            )
        )
        cg.add(var.set_max_partial_updates(partial[CONF_MAX_UPDATES]))

    if CONF_RESET_DURATION in config:
        cg.add(var.set_reset_duration(config[CONF_RESET_DURATION]))

    if CONF_LAMBDA in config:
        writer = await cg.process_lambda(
            config[CONF_LAMBDA],
            [(display.DisplayRef, "it")],
            return_type=cg.void,
        )
        cg.add(var.set_writer(writer))
