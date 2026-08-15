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
CONF_LUT_MODE = "lut_mode"

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
            cv.Optional(CONF_LUT_MODE, default="auto"): cv.enum(LUT_MODES, lower=True),
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
    cg.add(var.set_lut_mode(config[CONF_LUT_MODE]))

    if CONF_RESET_DURATION in config:
        cg.add(var.set_reset_duration(config[CONF_RESET_DURATION]))

    if CONF_LAMBDA in config:
        writer = await cg.process_lambda(
            config[CONF_LAMBDA],
            [(display.DisplayRef, "it")],
            return_type=cg.void,
        )
        cg.add(var.set_writer(writer))
