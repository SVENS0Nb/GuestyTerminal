#include "guesty_epaper_gray4.h"

#include <algorithm>
#include <cstring>

#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"

#ifdef USE_ESP32
#include "driver/spi_master.h"
#include "esp_attr.h"
#endif

namespace esphome::guesty_epaper_gray4 {

static const char *const TAG = "guesty_epaper_gray4";
static constexpr uint32_t RETAINED_PARTIAL_MAGIC = 0x47545031UL;
static constexpr uint32_t RETAINED_LUT_SELECTION_MAGIC = 0x47544C31UL;

struct RetainedPartialFrame {
  uint32_t magic;
  uint16_t x;
  uint16_t y;
  uint16_t width;
  uint16_t height;
  uint8_t partial_count;
  uint8_t reserved[3];
  uint8_t bitmap[GuestyEPaperGray4::PARTIAL_BUFFER_CAPACITY];
};

struct RetainedLutSelection {
  uint32_t magic;
  uint8_t mode;
  uint8_t reserved[3];
};

#ifdef USE_ESP32
RTC_DATA_ATTR static RetainedPartialFrame retained_partial_frame;
RTC_DATA_ATTR static RetainedLutSelection retained_lut_selection;
#else
static RetainedPartialFrame retained_partial_frame;
static RetainedLutSelection retained_lut_selection;
#endif

// UC8179 four-gray waveforms from Seeed's MIT-licensed reTerminal E1001 Gray4
// example. Each lookup table contains seven phases of six bytes.
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
  this->last_update_successful_ = false;
  this->last_update_was_partial_ = false;

  const bool partial_requested = this->partial_update_requested_;
  const bool partial_available =
      partial_requested && this->retained_partial_frame_valid_() &&
      retained_partial_frame.partial_count < this->max_partial_updates_;
  if (partial_available) {
    std::memcpy(this->partial_previous_.data(), retained_partial_frame.bitmap,
                this->partial_buffer_length_());
  }
  this->partial_update_requested_ = false;

  this->do_update_();
  if (this->is_failed())
    return;

  if (partial_available) {
    this->extract_partial_bitmap_(this->partial_current_.data());
    if (std::memcmp(this->partial_previous_.data(), this->partial_current_.data(),
                    this->partial_buffer_length_()) == 0) {
      this->last_update_successful_ = true;
      return;
    }
    if (this->display_partial_(this->partial_previous_.data(),
                               this->partial_current_.data())) {
      this->last_update_successful_ = true;
      this->last_update_was_partial_ = true;
      this->store_retained_partial_frame_(retained_partial_frame.partial_count + 1);
      return;
    }
    ESP_LOGW(TAG, "Partial refresh failed; falling back to full grayscale refresh");
  } else if (partial_requested && this->partial_refresh_configured_) {
    ESP_LOGI(TAG,
             "Partial refresh baseline unavailable or limit reached; "
             "performing full refresh");
  }

  this->last_update_successful_ = this->display_();
  if (this->last_update_successful_)
    this->store_retained_partial_frame_(0);
  else
    this->invalidate_retained_partial_frame_();
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

  uint8_t gray = this->color_to_panel_gray_(color);
  if (this->partial_refresh_configured_ && x >= this->partial_x_ &&
      x < this->partial_x_ + this->partial_width_ && y >= this->partial_y_ &&
      y < this->partial_y_ + this->partial_height_) {
    // Differential partial refresh is monochrome. Quantize this small window
    // during every full render too, so its retained bitmap exactly matches the
    // physical pixels used as the next partial-update baseline.
    gray = gray < 2 ? 0 : 3;
  }
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

bool GuestyEPaperGray4::wait_after_controller_command_(const char *phase) {
  // Seeed's UC8179 sequences leave a fixed 100 ms guard after POWER ON and
  // DISPLAY REFRESH, then wait for BUSY_N to return HIGH. Requiring this driver
  // to witness the LOW edge is too strict: a valid controller revision may
  // assert it before the first sampled edge or complete a short power-on cycle
  // during the guard period.
  delay(100);
  return this->wait_until_idle_(phase);
}

bool GuestyEPaperGray4::reset_panel_() {
  // The initial high period powers the E1001's panel/reset circuit before the
  // actual reset pulse, matching Seeed's E1001 hardware sequence.
  this->reset_pin_->digital_write(true);
  delay(10);
  this->reset_pin_->digital_write(false);
  delay(this->reset_duration_);  // NOLINT
  this->reset_pin_->digital_write(true);
  delay(10);
  this->panel_asleep_ = false;
  return this->wait_until_idle_("after reset");
}

bool GuestyEPaperGray4::release_spi_bus_for_gpio_read_() {
#ifdef USE_ESP32
  if (!this->clock_pin_->is_internal() || !this->data_pin_->is_internal()) {
    ESP_LOGW(TAG, "OTP probing requires internal ESP32 clock and data pins");
    return false;
  }

  // SPIClient::spi_teardown() removes only this device. It deliberately does
  // not release the ESP-IDF bus or its GPIO matrix. The OTP read switches MOSI
  // to a bidirectional GPIO, so release the otherwise-exclusive E1001 SPI2 bus
  // as Seeed_GFX does with SPI.end() before touching either bus pin.
  this->spi_teardown();
  const esp_err_t error = spi_bus_free(SPI2_HOST);
  if (error != ESP_OK) {
    ESP_LOGW(TAG, "Could not release SPI2 for OTP read (error 0x%X)",
             static_cast<unsigned int>(error));
    this->spi_setup();
    if (!this->spi_is_ready()) {
      ESP_LOGE(TAG, "Could not recover the E-paper SPI device");
      this->status_set_warning();
      this->mark_failed();
    }
    return false;
  }
  return true;
#else
  ESP_LOGW(TAG, "OTP probing is only supported on the ESP32 E1001 target");
  return false;
#endif
}

bool GuestyEPaperGray4::restore_spi_bus_after_gpio_read_() {
#ifdef USE_ESP32
  const auto *clock_pin = static_cast<InternalGPIOPin *>(this->clock_pin_);
  const auto *data_pin = static_cast<InternalGPIOPin *>(this->data_pin_);
  spi_bus_config_t bus_config{};
  bus_config.mosi_io_num = data_pin->get_pin();
  // Match ESPHome's original E1001 bus configuration exactly. GPIO8 is the
  // board's MISO pin even though normal panel writes use only GPIO9/MOSI.
  bus_config.miso_io_num = 8;
  bus_config.sclk_io_num = clock_pin->get_pin();
  bus_config.quadwp_io_num = -1;
  bus_config.quadhd_io_num = -1;
  bus_config.max_transfer_sz = 4092;
  bus_config.flags = SPICOMMON_BUSFLAG_MASTER | SPICOMMON_BUSFLAG_SCLK;

  // Reinitializing the bus is essential. Calling spi_setup() alone would only
  // add a new device handle while GPIO7/GPIO9 remained detached from the SPI
  // peripheral after the manual OTP read.
  const esp_err_t error =
      spi_bus_initialize(SPI2_HOST, &bus_config, SPI_DMA_CH_AUTO);
  if (error != ESP_OK) {
    ESP_LOGE(TAG, "Could not restore SPI2 after OTP read (error 0x%X)",
             static_cast<unsigned int>(error));
    this->status_set_warning();
    this->mark_failed();
    return false;
  }
  this->spi_setup();
  if (!this->spi_is_ready()) {
    ESP_LOGE(TAG, "Could not restore the E-paper SPI device after OTP read");
    this->status_set_warning();
    this->mark_failed();
    return false;
  }
  return true;
#else
  return false;
#endif
}

void GuestyEPaperGray4::gpio_write_command_(uint8_t command) {
  this->cs_->digital_write(true);
  this->clock_pin_->digital_write(false);
  this->dc_pin_->digital_write(false);
  this->data_pin_->pin_mode(gpio::FLAG_OUTPUT);
  this->cs_->digital_write(false);
  for (uint8_t bit = 0; bit < 8; bit++) {
    this->data_pin_->digital_write((command & 0x80U) != 0);
    this->clock_pin_->digital_write(true);
    this->clock_pin_->digital_write(false);
    command <<= 1U;
  }
  this->cs_->digital_write(true);
}

uint8_t GuestyEPaperGray4::gpio_read_byte_() {
  uint8_t value = 0;
  this->cs_->digital_write(false);
  this->dc_pin_->digital_write(true);
  this->clock_pin_->digital_write(false);
  this->data_pin_->pin_mode(gpio::FLAG_INPUT);
  for (uint8_t bit = 0; bit < 8; bit++) {
    value <<= 1U;
    this->clock_pin_->digital_write(true);
    if (this->data_pin_->digital_read())
      value |= 0x01U;
    this->clock_pin_->digital_write(false);
  }
  this->data_pin_->pin_mode(gpio::FLAG_OUTPUT);
  this->data_pin_->digital_write(true);
  this->cs_->digital_write(true);
  return value;
}

bool GuestyEPaperGray4::read_otp_marker_(uint16_t read_length,
                                         uint16_t marker_offset,
                                         uint8_t *marker) {
  if (marker == nullptr || marker_offset >= read_length)
    return false;

  this->gpio_write_command_(0xA2);  // READ OTP
  for (uint16_t index = 0; index < read_length; index++) {
    const uint8_t value = this->gpio_read_byte_();
    if (index == marker_offset)
      *marker = value;
    if ((index & 0x3FU) == 0)
      App.feed_wdt();
  }
  delay(20);
  return true;
}

bool GuestyEPaperGray4::probe_otp_support_(bool *supported) {
  if (supported == nullptr)
    return false;
  *supported = false;

  // Seeed_GFX probes two UC8179 user-data banks over the bidirectional
  // SDA/MOSI line. Hardware SPI must be fully released while GPIO9 is an input.
  if (!this->release_spi_bus_for_gpio_read_())
    return false;
  this->clock_pin_->setup();
  this->data_pin_->setup();
  this->clock_pin_->pin_mode(gpio::FLAG_OUTPUT);
  this->data_pin_->pin_mode(gpio::FLAG_OUTPUT);
  this->cs_->digital_write(true);

  const auto reset_for_read = [&]() {
    this->reset_pin_->digital_write(false);
    delay(20);
    this->reset_pin_->digital_write(true);
    delay(20);
    return this->wait_until_idle_("during OTP probe");
  };

  bool probe_ok = reset_for_read();
  if (probe_ok) {
    this->gpio_write_command_(0x40);  // READ INTERNAL TEMPERATURE
    probe_ok = this->wait_until_idle_("before OTP temperature read");
    if (probe_ok) {
      (void) this->gpio_read_byte_();
      (void) this->gpio_read_byte_();
    }
  }

  uint8_t marker_1 = 0;
  uint8_t marker_2 = 0;
  if (probe_ok && reset_for_read())
    probe_ok = this->read_otp_marker_(0x0BED, 0x0BE3, &marker_1);
  else
    probe_ok = false;
  if (probe_ok && reset_for_read())
    probe_ok = this->read_otp_marker_(0x17ED, 0x17E3, &marker_2);
  else
    probe_ok = false;

  this->clock_pin_->pin_mode(gpio::FLAG_OUTPUT);
  this->clock_pin_->digital_write(false);
  this->data_pin_->pin_mode(gpio::FLAG_OUTPUT);
  this->data_pin_->digital_write(true);
  this->cs_->digital_write(true);
  if (!this->restore_spi_bus_after_gpio_read_())
    return false;

  if (!probe_ok) {
    ESP_LOGW(TAG, "Could not read OTP markers; using Seeed register LUTs");
    return false;
  }

  *supported = marker_1 == 0x01 || marker_2 == 0x01;
  ESP_LOGI(TAG, "UC8179 OTP grayscale support: %s",
           *supported ? "available" : "not available");
  return true;
}

bool GuestyEPaperGray4::select_lut_mode_() {
  if (this->lut_mode_selected_)
    return true;

  if (this->configured_lut_mode_ == LUT_MODE_AUTO) {
    const bool retained_valid =
        retained_lut_selection.magic == RETAINED_LUT_SELECTION_MAGIC &&
        (retained_lut_selection.mode == LUT_MODE_CUSTOM ||
         retained_lut_selection.mode == LUT_MODE_OTP);
    if (retained_valid) {
      this->active_lut_mode_ =
          static_cast<LutMode>(retained_lut_selection.mode);
      ESP_LOGI(TAG, "Restored grayscale waveform selection from RTC memory");
    } else {
      bool otp_supported = false;
      if (this->probe_otp_support_(&otp_supported)) {
        this->active_lut_mode_ =
            otp_supported ? LUT_MODE_OTP : LUT_MODE_CUSTOM;
        retained_lut_selection.magic = 0;
        retained_lut_selection.mode = this->active_lut_mode_;
        retained_lut_selection.magic = RETAINED_LUT_SELECTION_MAGIC;
      } else {
        if (this->is_failed())
          return false;
        this->active_lut_mode_ = LUT_MODE_CUSTOM;
      }
    }
  } else {
    this->active_lut_mode_ = this->configured_lut_mode_;
  }

  this->lut_mode_selected_ = true;
  ESP_LOGI(TAG, "Selected grayscale waveform: %s",
           this->active_lut_mode_ == LUT_MODE_OTP ? "panel OTP"
                                                  : "Seeed register LUTs");
  return true;
}

void GuestyEPaperGray4::write_lut_(uint8_t command, const uint8_t *lut, size_t length) {
  this->command_(command);
  this->start_data_();
  this->write_array(lut, length);
  this->end_data_();
}

bool GuestyEPaperGray4::init_custom_gray_mode_() {
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
  if (!this->wait_after_controller_command_("after custom-LUT power on"))
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
  this->write_lut_(0x21, LUT_WW_GRAY, sizeof(LUT_WW_GRAY));
  this->write_lut_(0x22, LUT_KW_GRAY, sizeof(LUT_KW_GRAY));
  this->write_lut_(0x23, LUT_WK_GRAY, sizeof(LUT_WK_GRAY));
  this->write_lut_(0x24, LUT_KK_GRAY, sizeof(LUT_KK_GRAY));
  return true;
}

bool GuestyEPaperGray4::init_otp_gray_mode_() {
  this->command_(0x01);  // POWER SETTING
  this->data_(0x07);
  this->data_(0x07);
  this->data_(0x3F);
  this->data_(0x3F);

  this->command_(0x06);  // BOOSTER SOFT START
  this->data_(0x27);
  this->data_(0x27);
  this->data_(0x18);
  this->data_(0x17);

  this->command_(0x04);  // POWER ON
  if (!this->wait_after_controller_command_("after OTP power on"))
    return false;

  this->command_(0x00);  // KW mode; waveform loaded from panel OTP
  this->data_(0x1F);

  this->command_(0x61);  // 800x480 resolution
  this->data_(WIDTH >> 8);
  this->data_(WIDTH & 0xFF);
  this->data_(HEIGHT >> 8);
  this->data_(HEIGHT & 0xFF);

  this->command_(0x50);  // VCOM AND DATA INTERVAL
  this->data_(0x10);
  this->data_(0x07);

  this->command_(0xE0);  // CASCADE SETTING
  this->data_(0x02);
  this->command_(0xE5);  // Select OTP four-gray waveform
  this->data_(0x5F);
  return true;
}

bool GuestyEPaperGray4::init_partial_mode_() {
  // Seeed's UC8179 OTP differential mode uses only black and white inside the
  // configured window; the rest of the panel keeps its four-gray image.
  this->command_(0x01);  // POWER SETTING
  this->data_(0x07);
  this->data_(0x07);
  this->data_(0x3F);
  this->data_(0x3F);

  this->command_(0x06);  // BOOSTER SOFT START
  this->data_(0x17);
  this->data_(0x17);
  this->data_(0x28);
  this->data_(0x17);

  this->command_(0x04);  // POWER ON
  if (!this->wait_after_controller_command_("after partial power on"))
    return false;

  this->command_(0x00);  // PANEL SETTING: monochrome OTP waveform
  this->data_(0x1F);

  this->command_(0x61);  // 800x480 resolution
  this->data_(WIDTH >> 8);
  this->data_(WIDTH & 0xFF);
  this->data_(HEIGHT >> 8);
  this->data_(HEIGHT & 0xFF);

  this->command_(0x15);  // Single SPI mode
  this->data_(0x00);

  this->command_(0x50);  // N2OCP copies the new plane after refresh
  this->data_(0x10);
  this->data_(0x07);

  this->command_(0x60);  // TCON SETTING
  this->data_(0x22);

  this->command_(0xE0);  // Use controller temperature override
  this->data_(0x02);
  this->command_(0xE5);  // OTP fast-partial waveform selection
  this->data_(0x6E);
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
      uint8_t output = 0;
      for (uint8_t pixel = 0; pixel < 8U; pixel++) {
        const uint8_t packed = source[column * 2U + pixel / 4U];
        const uint8_t shift = (3U - (pixel & 0x03U)) * 2U;
        const uint8_t framebuffer_gray = (packed >> shift) & 0x03U;
        // ESPHome/framebuffer: 0=black, 3=white. UC8179 four-gray DTM data
        // uses the opposite two-bit polarity. Seeed's E1001 reference applies
        // this same 3-gray conversion before splitting the two planes.
        const uint8_t controller_gray = 3U - framebuffer_gray;
        if ((controller_gray & (1U << bit_index)) != 0U)
          output |= 1U << (7U - pixel);
      }
      row_buffer[column] = output;
    }
    this->write_array(row_buffer, BYTES_PER_ROW);
    App.feed_wdt();
  }
  this->end_data_();
}

uint8_t GuestyEPaperGray4::monochrome_byte_(uint16_t row,
                                            uint16_t byte_column) const {
  const uint8_t *source =
      this->buffer_ + static_cast<uint32_t>(row) * (WIDTH / 4U) +
      byte_column * 2U;
  uint8_t output = 0;
  for (uint8_t pixel = 0; pixel < 8; pixel++) {
    const uint8_t packed = source[pixel / 4U];
    const uint8_t shift = (3U - (pixel & 0x03U)) * 2U;
    const uint8_t gray = (packed >> shift) & 0x03U;
    if (gray >= 2U)
      output |= 1U << (7U - pixel);
  }
  return output;
}

void GuestyEPaperGray4::write_monochrome_frame_(
    uint8_t command, const uint8_t *partial_override) {
  static constexpr uint16_t BYTES_PER_ROW = WIDTH / 8U;
  uint8_t row_buffer[BYTES_PER_ROW];
  const uint16_t partial_byte_start = this->partial_x_ / 8U;
  const uint16_t partial_bytes_per_row = this->partial_width_ / 8U;
  const uint16_t partial_byte_end = partial_byte_start + partial_bytes_per_row;

  this->command_(command);
  this->start_data_();
  for (uint16_t row = 0; row < HEIGHT; row++) {
    const bool override_row = partial_override != nullptr &&
                              row >= this->partial_y_ &&
                              row < this->partial_y_ + this->partial_height_;
    for (uint16_t column = 0; column < BYTES_PER_ROW; column++) {
      if (override_row && column >= partial_byte_start &&
          column < partial_byte_end) {
        const size_t override_index =
            static_cast<size_t>(row - this->partial_y_) *
                partial_bytes_per_row +
            (column - partial_byte_start);
        row_buffer[column] = partial_override[override_index];
      } else {
        // Equal previous/current values outside the weather window tell the
        // differential LUT not to drive those pixels. This also reconstructs
        // both complete controller RAM planes after every reset/deep sleep.
        row_buffer[column] = this->monochrome_byte_(row, column);
      }
    }
    this->write_array(row_buffer, BYTES_PER_ROW);
    App.feed_wdt();
  }
  this->end_data_();
}

void GuestyEPaperGray4::set_partial_ram_area_() {
  const uint16_t x_end = this->partial_x_ + this->partial_width_ - 1;
  const uint16_t y_end = this->partial_y_ + this->partial_height_ - 1;
  this->command_(0x50);  // VCOM AND DATA INTERVAL for partial refresh
  this->data_(0xA9);
  this->data_(0x07);
  this->command_(0x91);  // PARTIAL IN
  this->command_(0x90);  // PARTIAL WINDOW
  this->data_(this->partial_x_ >> 8);
  this->data_(this->partial_x_ & 0xFF);
  this->data_(x_end >> 8);
  this->data_(x_end & 0xFF);
  this->data_(this->partial_y_ >> 8);
  this->data_(this->partial_y_ & 0xFF);
  this->data_(y_end >> 8);
  this->data_(y_end & 0xFF);
  this->data_(0x01);
}

bool GuestyEPaperGray4::refresh_partial_() {
  const uint32_t started = millis();
  // Both complete RAM planes have already been restored. The controller's
  // partial window constrains the differential update to the status header.
  this->set_partial_ram_area_();
  this->command_(0x12);  // DISPLAY REFRESH
  if (!this->wait_after_controller_command_("during partial refresh"))
    return false;
  ESP_LOGI(TAG, "Partial weather refresh completed in %lu ms",
           static_cast<unsigned long>(millis() - started));
  this->status_clear_warning();
  return true;
}

bool GuestyEPaperGray4::display_partial_(const uint8_t *previous,
                                         const uint8_t *current) {
  if (!this->partial_refresh_configured_)
    return false;
  if (!this->reset_panel_()) {
    this->deep_sleep_panel_();
    return false;
  }
  if (!this->init_partial_mode_()) {
    this->deep_sleep_panel_();
    return false;
  }
  // A controller reset invalidates both RAM planes even though the physical
  // E-paper image remains. Rebuild the complete 0x10/0x13 planes so pixels
  // outside the weather window are always defined and compare equal. Only
  // the retained old and newly rendered weather bitmaps differ.
  ESP_LOGI(TAG,
           "Restoring both %lu-byte controller planes before partial refresh",
           static_cast<unsigned long>(MONOCHROME_FRAME_LENGTH));
  this->write_monochrome_frame_(0x10, previous);
  this->write_monochrome_frame_(0x13, current);
  const bool refreshed = this->refresh_partial_();
  this->deep_sleep_panel_();
  return refreshed;
}

size_t GuestyEPaperGray4::partial_buffer_length_() const {
  if (!this->partial_refresh_configured_ || this->partial_width_ == 0 ||
      this->partial_height_ == 0)
    return 0;
  return static_cast<size_t>(this->partial_width_ / 8U) * this->partial_height_;
}

void GuestyEPaperGray4::extract_partial_bitmap_(uint8_t *destination) const {
  const uint16_t bytes_per_row = this->partial_width_ / 8U;
  for (uint16_t row = 0; row < this->partial_height_; row++) {
    for (uint16_t byte_column = 0; byte_column < bytes_per_row; byte_column++) {
      uint8_t output = 0;
      for (uint8_t bit = 0; bit < 8; bit++) {
        const uint16_t x = this->partial_x_ + byte_column * 8U + bit;
        const uint16_t y = this->partial_y_ + row;
        const uint32_t position =
            (static_cast<uint32_t>(y) * WIDTH + x) / 4U;
        const uint8_t shift = (3U - (x & 0x03U)) * 2U;
        const uint8_t gray = (this->buffer_[position] >> shift) & 0x03U;
        if (gray >= 2)
          output |= 1U << (7U - bit);
      }
      destination[static_cast<size_t>(row) * bytes_per_row + byte_column] =
          output;
    }
  }
}

bool GuestyEPaperGray4::retained_partial_frame_valid_() const {
  const size_t length = this->partial_buffer_length_();
  return length > 0 && length <= PARTIAL_BUFFER_CAPACITY &&
         retained_partial_frame.magic == RETAINED_PARTIAL_MAGIC &&
         retained_partial_frame.x == this->partial_x_ &&
         retained_partial_frame.y == this->partial_y_ &&
         retained_partial_frame.width == this->partial_width_ &&
         retained_partial_frame.height == this->partial_height_;
}

void GuestyEPaperGray4::store_retained_partial_frame_(uint8_t partial_count) {
  const size_t length = this->partial_buffer_length_();
  if (length == 0 || length > PARTIAL_BUFFER_CAPACITY)
    return;
  retained_partial_frame.magic = 0;
  retained_partial_frame.x = this->partial_x_;
  retained_partial_frame.y = this->partial_y_;
  retained_partial_frame.width = this->partial_width_;
  retained_partial_frame.height = this->partial_height_;
  retained_partial_frame.partial_count = partial_count;
  this->extract_partial_bitmap_(retained_partial_frame.bitmap);
  retained_partial_frame.magic = RETAINED_PARTIAL_MAGIC;
}

void GuestyEPaperGray4::invalidate_retained_partial_frame_() {
  retained_partial_frame.magic = 0;
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
  if (!this->wait_after_controller_command_("during grayscale refresh"))
    return false;
  ESP_LOGI(TAG, "Four-level refresh completed in %lu ms",
           static_cast<unsigned long>(millis() - started));
  this->status_clear_warning();
  return true;
}

bool GuestyEPaperGray4::display_() {
  if (!this->select_lut_mode_())
    return false;
  if (!this->reset_panel_()) {
    this->deep_sleep_panel_();
    return false;
  }
  const bool initialized = this->active_lut_mode_ == LUT_MODE_OTP
                               ? this->init_otp_gray_mode_()
                               : this->init_custom_gray_mode_();
  if (!initialized) {
    this->deep_sleep_panel_();
    return false;
  }
  this->log_frame_levels_();
  this->write_plane_(0x10, 0);  // DTM1: inverted least-significant gray bit
  this->write_plane_(0x13, 1);  // DTM2: inverted most-significant gray bit
  const bool refreshed = this->refresh_();
  this->deep_sleep_panel_();
  return refreshed;
}

void GuestyEPaperGray4::deep_sleep_panel_() {
  if (this->panel_asleep_)
    return;
  // The UC8179 border is a separate electrode outside the 800x480 pixel RAM.
  // Release it before power-off; leaving it driven can retain a narrow dark
  // frame even when every framebuffer edge pixel is white. R50h.BDZ=1 makes
  // the border high-impedance, as required by the controller documentation.
  this->command_(0x50);  // VCOM AND DATA INTERVAL SETTING
  this->data_(0xF7);     // Border Hi-Z before POWER OFF
  this->command_(0x02);  // POWER OFF
  const bool powered_off = this->wait_until_idle_("after power off");
  if (!powered_off)
    ESP_LOGW(TAG, "Power-off timeout; attempting panel deep sleep anyway");
  this->command_(0x07);  // DEEP SLEEP
  this->data_(0xA5);
  // When BUSY timed out, keep this false so a later safe-shutdown hook can
  // make one more best-effort attempt instead of assuming the command landed.
  this->panel_asleep_ = powered_off;
}

void GuestyEPaperGray4::dump_config() {
  LOG_DISPLAY("", "GuestyTerminal UC8179 Four-Gray E-Paper", this)
  ESP_LOGCONFIG(TAG, "  Panel: GDEY075T7, 800x480, 2 bits per pixel");
  ESP_LOGCONFIG(TAG, "  Framebuffer: %lu bytes",
                static_cast<unsigned long>(this->get_buffer_length_()));
  const char *configured_mode = "auto (OTP detection with Seeed LUT fallback)";
  if (this->configured_lut_mode_ == LUT_MODE_CUSTOM)
    configured_mode = "Seeed register LUTs";
  else if (this->configured_lut_mode_ == LUT_MODE_OTP)
    configured_mode = "panel OTP";
  ESP_LOGCONFIG(TAG, "  Grayscale waveform: %s", configured_mode);
  if (this->partial_refresh_configured_) {
    ESP_LOGCONFIG(TAG, "  Partial weather window: x=%u, y=%u, %ux%u",
                  this->partial_x_, this->partial_y_, this->partial_width_,
                  this->partial_height_);
    ESP_LOGCONFIG(TAG, "  Maximum consecutive partial refreshes: %u",
                  this->max_partial_updates_);
  }
  LOG_PIN("  CS Pin: ", this->cs_);
  LOG_PIN("  Clock Pin: ", this->clock_pin_);
  LOG_PIN("  Bidirectional Data Pin: ", this->data_pin_);
  LOG_PIN("  DC Pin: ", this->dc_pin_);
  LOG_PIN("  Reset Pin: ", this->reset_pin_);
  LOG_PIN("  Busy Pin: ", this->busy_pin_);
  LOG_UPDATE_INTERVAL(this);
}

}  // namespace esphome::guesty_epaper_gray4
