#include "guesty_epaper_gray4.h"

#include <algorithm>
#include <cstring>

#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"

namespace esphome::guesty_epaper_gray4 {

static const char *const TAG = "guesty_epaper_gray4";

// UC8179 grayscale waveforms from Seeed's reTerminal E1001 Gray4 example.
// Each lookup table contains seven phases of six bytes.
static constexpr uint8_t LUT_VCOM_GRAY[42] = {
    0x00, 0x00, 0x06, 0x08, 0x07, 0x01, 0x00, 0x06, 0x0A, 0x0B, 0x0A, 0x01, 0x00, 0x03,
    0x03, 0x00, 0x00, 0x03, 0x00, 0x05, 0x09, 0x06, 0x06, 0x01, 0x00, 0x02, 0x02, 0x0A,
    0x0A, 0x01, 0x00, 0x0A, 0x11, 0x06, 0x07, 0x01, 0x00, 0x02, 0x01, 0x02, 0x01, 0x01,
};

static constexpr uint8_t LUT_WW_GRAY[42] = {
    0x15, 0x00, 0x06, 0x08, 0x07, 0x01, 0x54, 0x06, 0x0A, 0x0B, 0x0A, 0x01, 0x90, 0x03,
    0x03, 0x00, 0x00, 0x03, 0x2A, 0x05, 0x09, 0x06, 0x06, 0x01, 0xAA, 0x02, 0x02, 0x0A,
    0x0A, 0x01, 0x00, 0x0A, 0x11, 0x06, 0x07, 0x01, 0x28, 0x02, 0x01, 0x02, 0x01, 0x01,
};

static constexpr uint8_t LUT_KW_GRAY[42] = {
    0x2A, 0x00, 0x06, 0x08, 0x07, 0x01, 0x59, 0x06, 0x0A, 0x0B, 0x0A, 0x01, 0x90, 0x03,
    0x03, 0x00, 0x00, 0x03, 0x5A, 0x05, 0x09, 0x06, 0x06, 0x01, 0xA8, 0x02, 0x02, 0x0A,
    0x0A, 0x01, 0x45, 0x0A, 0x11, 0x06, 0x07, 0x01, 0xA8, 0x02, 0x01, 0x02, 0x01, 0x01,
};

static constexpr uint8_t LUT_WK_GRAY[42] = {
    0x16, 0x00, 0x06, 0x08, 0x07, 0x01, 0xA0, 0x06, 0x0A, 0x0B, 0x0A, 0x01, 0x90, 0x03,
    0x03, 0x00, 0x00, 0x03, 0x99, 0x05, 0x09, 0x06, 0x06, 0x01, 0xA0, 0x02, 0x02, 0x0A,
    0x0A, 0x01, 0x40, 0x0A, 0x11, 0x06, 0x07, 0x01, 0x20, 0x02, 0x01, 0x02, 0x01, 0x01,
};

static constexpr uint8_t LUT_KK_GRAY[42] = {
    0x26, 0x00, 0x06, 0x08, 0x07, 0x01, 0x6A, 0x06, 0x0A, 0x0B, 0x0A, 0x01, 0x90, 0x03,
    0x03, 0x00, 0x00, 0x03, 0x65, 0x05, 0x09, 0x06, 0x06, 0x01, 0x50, 0x02, 0x02, 0x0A,
    0x0A, 0x01, 0x10, 0x0A, 0x11, 0x06, 0x07, 0x01, 0x10, 0x02, 0x01, 0x02, 0x01, 0x01,
};

float GuestyEPaperGray4::get_setup_priority() const { return setup_priority::PROCESSOR; }

void GuestyEPaperGray4::setup() {
  this->init_internal_(this->get_buffer_length_());
  if (this->buffer_ == nullptr) {
    ESP_LOGE(TAG, "Could not allocate the 96 KiB grayscale framebuffer");
    this->mark_failed();
    return;
  }

  this->dc_pin_->setup();
  this->dc_pin_->digital_write(false);
  this->reset_pin_->setup();
  this->reset_pin_->digital_write(true);
  this->busy_pin_->setup();
  this->spi_setup();
}

void GuestyEPaperGray4::update() {
  this->do_update_();
  if (!this->is_failed())
    this->display_();
}

void GuestyEPaperGray4::on_safe_shutdown() { this->deep_sleep_panel_(); }

uint8_t GuestyEPaperGray4::color_to_panel_gray_(Color color) {
  // ESPHome treats COLOR_ON as ink and COLOR_OFF as paper. Preserve those
  // semantics while quantizing intermediate anti-alias coverage to four
  // physical levels: 0=black, 1=dark gray, 2=light gray, 3=white.
  const uint8_t coverage = std::max({color.red, color.green, color.blue, color.white});
  const uint8_t ink_level = (static_cast<uint16_t>(coverage) * 3U + 127U) / 255U;
  return 3U - ink_level;
}

void GuestyEPaperGray4::fill(Color color) {
  if (this->get_clipping().is_set()) {
    display::Display::fill(color);
    return;
  }
  const uint8_t gray = this->color_to_panel_gray_(color);
  std::memset(this->buffer_, gray * 0x55U, this->get_buffer_length_());
}

void HOT GuestyEPaperGray4::draw_absolute_pixel_internal(int x, int y, Color color) {
  if (x < 0 || x >= WIDTH || y < 0 || y >= HEIGHT)
    return;

  const uint8_t gray = this->color_to_panel_gray_(color);
  const uint32_t position = (static_cast<uint32_t>(y) * WIDTH + x) / 4U;
  const uint8_t shift = (3U - (x & 0x03U)) * 2U;
  this->buffer_[position] =
      (this->buffer_[position] & ~(0x03U << shift)) | (gray << shift);
}

void GuestyEPaperGray4::command_(uint8_t value) {
  this->dc_pin_->digital_write(false);
  this->enable();
  this->write_byte(value);
  this->disable();
}

void GuestyEPaperGray4::data_(uint8_t value) {
  this->start_data_();
  this->write_byte(value);
  this->end_data_();
}

void GuestyEPaperGray4::start_data_() {
  this->dc_pin_->digital_write(true);
  this->enable();
}

void GuestyEPaperGray4::end_data_() { this->disable(); }

bool GuestyEPaperGray4::wait_until_idle_(const char *phase) {
  // The E1001 exposes UC8179 BUSY_N: LOW means busy, HIGH means idle. The YAML
  // must therefore use a non-inverted GPIO input for this driver.
  delay(10);
  const uint32_t started = millis();
  while (!this->busy_pin_->digital_read()) {
    if (millis() - started > IDLE_TIMEOUT_MS) {
      ESP_LOGE(TAG, "Display BUSY timeout (%s)", phase);
      this->status_set_warning();
      return false;
    }
    App.feed_wdt();
    delay(10);
  }
  return true;
}

bool GuestyEPaperGray4::reset_panel_() {
  this->reset_pin_->digital_write(false);
  delay(this->reset_duration_);  // NOLINT
  this->reset_pin_->digital_write(true);
  delay(10);
  this->panel_asleep_ = false;
  return this->wait_until_idle_("after reset");
}

void GuestyEPaperGray4::write_lut_(uint8_t command, const uint8_t *lut, size_t length) {
  this->command_(command);
  this->start_data_();
  this->write_array(lut, length);
  this->end_data_();
}

bool GuestyEPaperGray4::init_gray_mode_() {
  this->command_(0x01);  // POWER SETTING
  this->data_(0x07);
  this->data_(0x17);
  this->data_(0x3F);
  this->data_(0x3F);
  this->data_(0x07);

  this->command_(0x30);  // PLL CONTROL
  this->data_(0x06);

  this->command_(0x82);  // VCOM DC SETTING
  this->data_(0x12);

  this->command_(0x06);  // BOOSTER SOFT START
  this->data_(0x27);
  this->data_(0x27);
  this->data_(0x28);
  this->data_(0x17);

  this->command_(0x04);  // POWER ON
  delay(100);
  if (!this->wait_until_idle_("after power on"))
    return false;

  this->command_(0x00);  // KW mode; waveform loaded from registers
  this->data_(0x3F);

  this->command_(0xE3);  // POWER SAVING
  this->data_(0x88);

  this->command_(0x50);  // VCOM AND DATA INTERVAL
  this->data_(0x10);
  this->data_(0x07);

  this->command_(0x52);
  this->data_(0x00);

  this->command_(0x61);  // 800x480 resolution
  this->data_(WIDTH >> 8);
  this->data_(WIDTH & 0xFF);
  this->data_(HEIGHT >> 8);
  this->data_(HEIGHT & 0xFF);

  this->write_lut_(0x20, LUT_VCOM_GRAY, sizeof(LUT_VCOM_GRAY));
  if (!this->wait_until_idle_("after VCOM LUT"))
    return false;
  this->write_lut_(0x21, LUT_WW_GRAY, sizeof(LUT_WW_GRAY));
  if (!this->wait_until_idle_("after WW LUT"))
    return false;
  this->write_lut_(0x22, LUT_KW_GRAY, sizeof(LUT_KW_GRAY));
  if (!this->wait_until_idle_("after KW LUT"))
    return false;
  this->write_lut_(0x23, LUT_WK_GRAY, sizeof(LUT_WK_GRAY));
  this->write_lut_(0x24, LUT_KK_GRAY, sizeof(LUT_KK_GRAY));
  return true;
}

void GuestyEPaperGray4::write_plane_(uint8_t command, uint8_t bit_index) {
  static constexpr uint16_t BYTES_PER_ROW = WIDTH / 8U;
  uint8_t row_buffer[BYTES_PER_ROW];

  this->command_(command);
  this->start_data_();
  for (uint16_t row = 0; row < HEIGHT; row++) {
    const uint8_t *source = this->buffer_ + static_cast<uint32_t>(row) * (WIDTH / 4U);
    for (uint16_t column = 0; column < BYTES_PER_ROW; column++) {
      const uint8_t first = source[column * 2U];
      const uint8_t second = source[column * 2U + 1U];
      uint8_t output = 0;
      // The UC8179 wire representation is inverted: the logical panel level
      // 0 (black) is transmitted as binary 11, while 3 (white) is 00.
      output |= (1U - ((first >> (6U + bit_index)) & 0x01U)) << 7U;
      output |= (1U - ((first >> (4U + bit_index)) & 0x01U)) << 6U;
      output |= (1U - ((first >> (2U + bit_index)) & 0x01U)) << 5U;
      output |= (1U - ((first >> bit_index) & 0x01U)) << 4U;
      output |= (1U - ((second >> (6U + bit_index)) & 0x01U)) << 3U;
      output |= (1U - ((second >> (4U + bit_index)) & 0x01U)) << 2U;
      output |= (1U - ((second >> (2U + bit_index)) & 0x01U)) << 1U;
      output |= 1U - ((second >> bit_index) & 0x01U);
      row_buffer[column] = output;
    }
    this->write_array(row_buffer, BYTES_PER_ROW);
    App.feed_wdt();
  }
  this->end_data_();
}

bool GuestyEPaperGray4::refresh_() {
  const uint32_t started = millis();
  this->command_(0x12);  // DISPLAY REFRESH
  delay(100);
  if (!this->wait_until_idle_("during grayscale refresh"))
    return false;
  ESP_LOGI(TAG, "Four-level refresh completed in %lu ms",
           static_cast<unsigned long>(millis() - started));
  this->status_clear_warning();
  return true;
}

void GuestyEPaperGray4::display_() {
  if (!this->reset_panel_() || !this->init_gray_mode_())
    return;
  this->write_plane_(0x10, 0);  // DTM1: least-significant grayscale bit
  this->write_plane_(0x13, 1);  // DTM2: most-significant grayscale bit
  if (this->refresh_())
    this->deep_sleep_panel_();
}

void GuestyEPaperGray4::deep_sleep_panel_() {
  if (this->panel_asleep_)
    return;
  this->command_(0x02);  // POWER OFF
  if (!this->wait_until_idle_("after power off"))
    return;
  this->command_(0x07);  // DEEP SLEEP
  this->data_(0xA5);
  this->panel_asleep_ = true;
}

void GuestyEPaperGray4::dump_config() {
  LOG_DISPLAY("", "GuestyTerminal UC8179 Four-Gray E-Paper", this)
  ESP_LOGCONFIG(TAG, "  Panel: GDEY075T7, 800x480, 2 bits per pixel");
  ESP_LOGCONFIG(TAG, "  Framebuffer: %lu bytes",
                static_cast<unsigned long>(this->get_buffer_length_()));
  LOG_PIN("  CS Pin: ", this->cs_);
  LOG_PIN("  DC Pin: ", this->dc_pin_);
  LOG_PIN("  Reset Pin: ", this->reset_pin_);
  LOG_PIN("  Busy Pin: ", this->busy_pin_);
  LOG_UPDATE_INTERVAL(this);
}

}  // namespace esphome::guesty_epaper_gray4
