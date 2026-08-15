#include "guesty_epaper_gray4.h"

#include <algorithm>
#include <cstring>

#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"

namespace esphome::guesty_epaper_gray4 {

static const char *const TAG = "guesty_epaper_gray4";

// UC8179 four-gray waveforms from GxEPD2_4G's production-tested
// GxEPD2_750_T7 implementation. Each lookup table contains seven phases of
// six bytes. The border LUT has one meaningful phase and is zero-padded.
static constexpr uint8_t LUT_VCOM_GRAY[42] = {
    0x00, 0x0A, 0x00, 0x00, 0x00, 0x01, 0x60, 0x14, 0x14, 0x00, 0x00, 0x01, 0x00, 0x14,
    0x00, 0x00, 0x00, 0x01, 0x00, 0x13, 0x0A, 0x01, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
};

static constexpr uint8_t LUT_WW_GRAY[42] = {
    0x40, 0x0A, 0x00, 0x00, 0x00, 0x01, 0x90, 0x14, 0x14, 0x00, 0x00, 0x01, 0x10, 0x14,
    0x0A, 0x00, 0x00, 0x01, 0xA0, 0x13, 0x01, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
};

static constexpr uint8_t LUT_KW_GRAY[42] = {
    0x40, 0x0A, 0x00, 0x00, 0x00, 0x01, 0x90, 0x14, 0x14, 0x00, 0x00, 0x01, 0x00, 0x14,
    0x0A, 0x00, 0x00, 0x01, 0x99, 0x0C, 0x01, 0x03, 0x04, 0x01, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
};

static constexpr uint8_t LUT_WK_GRAY[42] = {
    0x40, 0x0A, 0x00, 0x00, 0x00, 0x01, 0x90, 0x14, 0x14, 0x00, 0x00, 0x01, 0x00, 0x14,
    0x0A, 0x00, 0x00, 0x01, 0x99, 0x0B, 0x04, 0x04, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
};

static constexpr uint8_t LUT_KK_GRAY[42] = {
    0x80, 0x0A, 0x00, 0x00, 0x00, 0x01, 0x90, 0x14, 0x14, 0x00, 0x00, 0x01, 0x20, 0x14,
    0x0A, 0x00, 0x00, 0x01, 0x50, 0x13, 0x01, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
};

static constexpr uint8_t LUT_BORDER_GRAY[42] = {
    0x00, 0x1E, 0x05, 0x1E, 0x05, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
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

bool GuestyEPaperGray4::wait_for_busy_cycle_(const char *phase) {
  // A refresh that never asserts BUSY was not accepted by the controller.
  // Do not report this as success merely because BUSY was already high.
  const uint32_t assertion_started = millis();
  while (this->busy_pin_->digital_read()) {
    if (millis() - assertion_started > 1000U) {
      ESP_LOGE(TAG, "Display BUSY never asserted (%s)", phase);
      this->status_set_warning();
      return false;
    }
    App.feed_wdt();
    delay(1);
  }
  return this->wait_until_idle_(phase);
}

bool GuestyEPaperGray4::reset_panel_() {
  // The initial high period powers the E1001's panel/reset circuit before the
  // actual reset pulse, matching Good Display and GxEPD2.
  this->reset_pin_->digital_write(true);
  delay(10);
  this->reset_pin_->digital_write(false);
  delay(this->reset_duration_);  // NOLINT
  this->reset_pin_->digital_write(true);
  delay(10);
  this->panel_asleep_ = false;
  return this->wait_until_idle_("after reset");
}

bool GuestyEPaperGray4::select_lut_mode_() {
  if (this->lut_mode_selected_)
    return true;
  this->lut_mode_selected_ = true;
  if (this->configured_lut_mode_ == LUT_MODE_OTP)
    ESP_LOGW(TAG, "OTP grayscale mode is unsupported; using register LUTs");
  ESP_LOGI(TAG, "Selected grayscale waveform: GxEPD2_4G register LUTs");
  return true;
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
  this->data_(0x07);
  this->data_(0x3F);
  this->data_(0x3F);

  this->command_(0x00);  // KW mode; waveform loaded from registers
  this->data_(0x3F);

  this->command_(0x61);  // 800x480 resolution
  this->data_(WIDTH >> 8);
  this->data_(WIDTH & 0xFF);
  this->data_(HEIGHT >> 8);
  this->data_(HEIGHT & 0xFF);

  this->command_(0x15);  // Single SPI mode
  this->data_(0x00);

  this->command_(0x50);  // VCOM AND DATA INTERVAL
  this->data_(0x31);     // LUTBD enabled for four-gray mode
  this->data_(0x07);

  this->command_(0x60);  // TCON SETTING
  this->data_(0x22);

  this->write_lut_(0x20, LUT_VCOM_GRAY, sizeof(LUT_VCOM_GRAY));
  this->write_lut_(0x21, LUT_WW_GRAY, sizeof(LUT_WW_GRAY));
  this->write_lut_(0x22, LUT_KW_GRAY, sizeof(LUT_KW_GRAY));
  this->write_lut_(0x23, LUT_WK_GRAY, sizeof(LUT_WK_GRAY));
  this->write_lut_(0x24, LUT_KK_GRAY, sizeof(LUT_KK_GRAY));
  this->write_lut_(0x25, LUT_BORDER_GRAY, sizeof(LUT_BORDER_GRAY));

  this->command_(0x04);  // POWER ON
  if (!this->wait_for_busy_cycle_("after power on"))
    return false;
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
      // The register-LUT four-gray mode uses the levels directly:
      // 00=black, 01=dark gray, 10=light gray, 11=white.
      output |= ((first >> (6U + bit_index)) & 0x01U) << 7U;
      output |= ((first >> (4U + bit_index)) & 0x01U) << 6U;
      output |= ((first >> (2U + bit_index)) & 0x01U) << 5U;
      output |= ((first >> bit_index) & 0x01U) << 4U;
      output |= ((second >> (6U + bit_index)) & 0x01U) << 3U;
      output |= ((second >> (4U + bit_index)) & 0x01U) << 2U;
      output |= ((second >> (2U + bit_index)) & 0x01U) << 1U;
      output |= (second >> bit_index) & 0x01U;
      row_buffer[column] = output;
    }
    this->write_array(row_buffer, BYTES_PER_ROW);
    App.feed_wdt();
  }
  this->end_data_();
}

void GuestyEPaperGray4::log_frame_levels_() {
  uint32_t levels[4] = {0, 0, 0, 0};
  for (uint32_t index = 0; index < this->get_buffer_length_(); index++) {
    const uint8_t packed = this->buffer_[index];
    levels[(packed >> 6U) & 0x03U]++;
    levels[(packed >> 4U) & 0x03U]++;
    levels[(packed >> 2U) & 0x03U]++;
    levels[packed & 0x03U]++;
  }
  ESP_LOGI(TAG,
           "Framebuffer levels: black=%lu, dark=%lu, light=%lu, white=%lu",
           static_cast<unsigned long>(levels[0]),
           static_cast<unsigned long>(levels[1]),
           static_cast<unsigned long>(levels[2]),
           static_cast<unsigned long>(levels[3]));
}

bool GuestyEPaperGray4::refresh_() {
  const uint32_t started = millis();
  this->command_(0x12);  // DISPLAY REFRESH
  if (!this->wait_for_busy_cycle_("during grayscale refresh"))
    return false;
  ESP_LOGI(TAG, "Four-level refresh completed in %lu ms",
           static_cast<unsigned long>(millis() - started));
  this->status_clear_warning();
  return true;
}

void GuestyEPaperGray4::display_() {
  if (!this->select_lut_mode_() || !this->reset_panel_())
    return;
  if (!this->init_gray_mode_())
    return;
  this->log_frame_levels_();
  this->write_plane_(0x10, 1);  // DTM1: most-significant grayscale bit
  this->write_plane_(0x13, 0);  // DTM2: least-significant grayscale bit
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
  const char *configured_mode = "auto (register LUTs)";
  if (this->configured_lut_mode_ == LUT_MODE_CUSTOM)
    configured_mode = "register LUTs";
  else if (this->configured_lut_mode_ == LUT_MODE_OTP)
    configured_mode = "otp requested; register LUT fallback";
  ESP_LOGCONFIG(TAG, "  Grayscale waveform: %s", configured_mode);
  LOG_PIN("  CS Pin: ", this->cs_);
  LOG_PIN("  Clock Pin: ", this->clock_pin_);
  LOG_PIN("  Bidirectional Data Pin: ", this->data_pin_);
  LOG_PIN("  DC Pin: ", this->dc_pin_);
  LOG_PIN("  Reset Pin: ", this->reset_pin_);
  LOG_PIN("  Busy Pin: ", this->busy_pin_);
  LOG_UPDATE_INTERVAL(this);
}

}  // namespace esphome::guesty_epaper_gray4
