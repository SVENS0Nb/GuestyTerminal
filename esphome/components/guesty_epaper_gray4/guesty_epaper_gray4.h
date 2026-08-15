#pragma once

#include "esphome/components/display/display_buffer.h"
#include "esphome/components/spi/spi.h"
#include "esphome/core/component.h"

namespace esphome::guesty_epaper_gray4 {

/**
 * Four-level grayscale driver for the Good Display GDEY075T7 panel used by
 * the Seeed Studio reTerminal E1001.
 *
 * The 96 KiB framebuffer stores four pixels per byte, with 0 representing
 * black and 3 white. A refresh sends the least- and most-significant pixel
 * bits as separate, wire-inverted UC8179 DTM1 and DTM2 planes. The waveform
 * and register sequence are ported from Seeed's MIT-licensed E1001 Gray4
 * example.
 */
class GuestyEPaperGray4
    : public display::DisplayBuffer,
      public spi::SPIDevice<spi::BIT_ORDER_MSB_FIRST, spi::CLOCK_POLARITY_LOW,
                            spi::CLOCK_PHASE_LEADING, spi::DATA_RATE_2MHZ> {
 public:
  static constexpr uint16_t WIDTH = 800;
  static constexpr uint16_t HEIGHT = 480;
  static constexpr uint32_t IDLE_TIMEOUT_MS = 45000;

  void set_dc_pin(GPIOPin *dc_pin) { this->dc_pin_ = dc_pin; }
  void set_reset_pin(GPIOPin *reset_pin) { this->reset_pin_ = reset_pin; }
  void set_busy_pin(GPIOPin *busy_pin) { this->busy_pin_ = busy_pin; }
  void set_reset_duration(uint32_t duration) { this->reset_duration_ = duration; }

  float get_setup_priority() const override;
  void setup() override;
  void update() override;
  void dump_config() override;
  void on_safe_shutdown() override;
  void fill(Color color) override;

  display::DisplayType get_display_type() override {
    return display::DisplayType::DISPLAY_TYPE_GRAYSCALE;
  }

 protected:
  void draw_absolute_pixel_internal(int x, int y, Color color) override;
  int get_width_internal() override { return WIDTH; }
  int get_height_internal() override { return HEIGHT; }

  static uint8_t color_to_panel_gray_(Color color);
  static constexpr uint32_t get_buffer_length_() { return WIDTH * HEIGHT / 4U; }

  void command_(uint8_t value);
  void data_(uint8_t value);
  void start_data_();
  void end_data_();
  bool wait_until_idle_(const char *phase);
  bool reset_panel_();
  bool init_gray_mode_();
  void write_lut_(uint8_t command, const uint8_t *lut, size_t length);
  void write_plane_(uint8_t command, uint8_t bit_index);
  bool refresh_();
  void display_();
  void deep_sleep_panel_();

  GPIOPin *dc_pin_{nullptr};
  GPIOPin *reset_pin_{nullptr};
  GPIOPin *busy_pin_{nullptr};
  uint32_t reset_duration_{10};
  bool panel_asleep_{true};
};

}  // namespace esphome::guesty_epaper_gray4
