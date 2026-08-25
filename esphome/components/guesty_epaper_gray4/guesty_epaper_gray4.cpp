#include "guesty_epaper_gray4.h"

#include <algorithm>
#include <cstring>

#include "esphome/core/application.h"
#include "esphome/core/hal.h"
#include "esphome/core/log.h"

#ifdef USE_ESP32
#include "driver/spi_master.h"
#include "esp_attr.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#endif

namespace esphome::guesty_epaper_gray4 {

static const char *const TAG = "guesty_epaper_gray4";
static constexpr uint32_t RETAINED_PARTIAL_MAGIC = 0x47545031UL;
// Version 2 invalidates the older marker1 || marker2 decision. UC8179 always
// prefers a valid bank 0, so only that bank's grayscale marker may decide the
// retained mode when both banks contain data.
static constexpr uint32_t RETAINED_LUT_SELECTION_MAGIC = 0x47544C32UL;

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

const char *GuestyEPaperGray4::update_phase_name() const {
  switch (this->update_phase_.load()) {
    case UPDATE_PHASE_PREPARING:
      return "preparing";
    case UPDATE_PHASE_PARTIAL:
      return "partial";
    case UPDATE_PHASE_WAVEFORM:
      return "waveform";
    case UPDATE_PHASE_RESET:
      return "reset";
    case UPDATE_PHASE_TRANSFER:
      return "transfer";
    case UPDATE_PHASE_REFRESH:
      return "refresh";
    case UPDATE_PHASE_SHUTDOWN:
      return "shutdown";
    case UPDATE_PHASE_FAILED:
      return "failed";
    default:
      return "idle";
  }
}

const char *GuestyEPaperGray4::last_error_name() const {
  switch (this->last_error_.load()) {
    case UPDATE_ERROR_COMPONENT:
      return "component";
    case UPDATE_ERROR_TASK_START:
      return "task_start";
    case UPDATE_ERROR_BUSY_TIMEOUT:
      return "busy_timeout";
    case UPDATE_ERROR_SPI:
      return "spi";
    case UPDATE_ERROR_PANEL:
      return "panel";
    default:
      return "none";
  }
}

const char *GuestyEPaperGray4::active_lut_mode_name() const {
  switch (this->active_lut_diagnostic_.load()) {
    case LUT_MODE_CUSTOM:
      return "custom";
    case LUT_MODE_OTP:
      return "otp";
    default:
      return "undetermined";
  }
}

const char *GuestyEPaperGray4::border_mode_name() const {
  switch (this->border_mode_.load()) {
    case BORDER_MODE_PANEL_OTP:
      return "panel_otp";
    case BORDER_MODE_VALIDATED_LUTBD:
      return "validated_lutbd";
    case BORDER_MODE_HIGH_Z:
      return "high_z";
    default:
      return "undetermined";
  }
}

void GuestyEPaperGray4::setup() {
  this->init_internal_(this->get_buffer_length_());
  if (this->buffer_ == nullptr) {
    ESP_LOGE(TAG, "Could not allocate the 96 KiB grayscale framebuffer");
    this->last_error_.store(UPDATE_ERROR_COMPONENT);
    this->update_phase_.store(UPDATE_PHASE_FAILED);
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
  if (this->update_in_progress_.exchange(true)) {
    ESP_LOGW(TAG, "Ignoring overlapping E-paper update request");
    return;
  }
  this->update_phase_.store(UPDATE_PHASE_PREPARING);
  this->last_error_.store(UPDATE_ERROR_NONE);
  this->last_update_successful_.store(false);
  this->last_update_was_partial_.store(false);

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
  if (this->is_failed()) {
    this->last_error_.store(UPDATE_ERROR_COMPONENT);
    this->update_phase_.store(UPDATE_PHASE_FAILED);
    this->update_in_progress_.store(false);
    return;
  }

  this->prepared_partial_available_ = partial_available;
  this->prepared_partial_requested_ = partial_requested;

#ifdef USE_ESP32
  // OTP inspection, plane transfer and a physical E-paper refresh can take
  // longer than the native API's handshake timeout. Keep those hardware-only
  // operations off ESPHome's main loop so Home Assistant remains connected
  // and can observe the final success state instead of creating a reconnect
  // and redraw loop.
  const BaseType_t task_created = xTaskCreate(
      GuestyEPaperGray4::update_task_, "guesty_epaper", 8192, this, 1, nullptr);
  if (task_created != pdPASS) {
    ESP_LOGE(TAG, "Could not start the E-paper refresh task");
    this->last_error_.store(UPDATE_ERROR_TASK_START);
    this->update_phase_.store(UPDATE_PHASE_FAILED);
    this->status_set_warning();
    this->update_in_progress_.store(false);
  }
#else
  this->perform_prepared_update_();
#endif
}

void GuestyEPaperGray4::perform_prepared_update_() {
  const bool partial_available = this->prepared_partial_available_;
  const bool partial_requested = this->prepared_partial_requested_;

  if (partial_available) {
    this->update_phase_.store(UPDATE_PHASE_PARTIAL);
    this->extract_partial_bitmap_(this->partial_current_.data());
    if (std::memcmp(this->partial_previous_.data(), this->partial_current_.data(),
                    this->partial_buffer_length_()) == 0) {
      this->last_update_successful_.store(true);
      this->update_phase_.store(UPDATE_PHASE_IDLE);
      this->update_in_progress_.store(false);
      return;
    }
    if (this->display_partial_(this->partial_previous_.data(),
                               this->partial_current_.data())) {
      this->last_update_successful_.store(true);
      this->last_update_was_partial_.store(true);
      this->update_phase_.store(UPDATE_PHASE_IDLE);
      this->store_retained_partial_frame_(retained_partial_frame.partial_count + 1);
      this->update_in_progress_.store(false);
      return;
    }
    ESP_LOGW(TAG, "Partial refresh failed; falling back to full grayscale refresh");
  } else if (partial_requested && this->partial_refresh_configured_) {
    ESP_LOGI(TAG,
             "Partial refresh baseline unavailable or limit reached; "
             "performing full refresh");
  }

  const bool successful = this->display_();
  this->last_update_successful_.store(successful);
  if (successful) {
    this->update_phase_.store(UPDATE_PHASE_IDLE);
    this->store_retained_partial_frame_(0);
  } else {
    if (this->last_error_.load() == UPDATE_ERROR_NONE)
      this->last_error_.store(UPDATE_ERROR_PANEL);
    this->update_phase_.store(UPDATE_PHASE_FAILED);
    this->invalidate_retained_partial_frame_();
  }
  this->update_in_progress_.store(false);
}

#ifdef USE_ESP32
void GuestyEPaperGray4::update_task_(void *parameter) {
  auto *display = static_cast<GuestyEPaperGray4 *>(parameter);
  const uint32_t started = millis();
  ESP_LOGI(TAG, "E-paper hardware transaction started");
  display->perform_prepared_update_();
  ESP_LOGI(TAG, "E-paper hardware transaction finished in %lu ms (%s)",
           static_cast<unsigned long>(millis() - started),
           display->last_update_successful() ? "successful" : "failed");
  vTaskDelete(nullptr);
}
#endif

void GuestyEPaperGray4::service_long_operation_() {
#ifdef USE_ESP32
  if (this->update_in_progress_.load()) {
    // ESPHome 2026.8 registers only its loop task with the task watchdog.
    // App.feed_wdt() from this worker would try to feed an unregistered task
    // while advancing Application's shared feed timestamp. That prevents the
    // real loop task from feeding itself and eventually reboots the device.
    // Block this low-priority worker for one tick instead, allowing the loop,
    // network stack and idle tasks to run on either CPU core.
    vTaskDelay(1);
    return;
  }
#endif
  // Safe-shutdown panel operations run synchronously on ESPHome's loop task.
  // Keep that registered task alive while a controller phase is still busy.
  App.feed_wdt();
  delay(1);
}

void GuestyEPaperGray4::on_safe_shutdown() {
  // A normal battery sleep is requested only after the YAML action has waited
  // for this flag. Keep manual restarts and OTA shutdowns safe as well: never
  // drive shutdown commands concurrently with an active panel transaction.
  while (this->update_in_progress_.load()) {
    // This wait runs on ESPHome's registered loop task, not the panel worker.
    App.feed_wdt();
    delay(10);
  }
  this->deep_sleep_panel_();
}

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

bool GuestyEPaperGray4::wait_until_idle_(const char *phase,
                                         uint32_t timeout_ms) {
  // The E1001 exposes UC8179 BUSY_N: LOW means busy, HIGH means idle. The YAML
  // must therefore use a non-inverted GPIO input for this driver.
  delay(10);
  const uint32_t started = millis();
  while (!this->busy_pin_->digital_read()) {
    if (millis() - started > timeout_ms) {
      ESP_LOGE(TAG, "Display BUSY timeout (%s)", phase);
      this->last_error_.store(UPDATE_ERROR_BUSY_TIMEOUT);
      this->status_set_warning();
      return false;
    }
    this->service_long_operation_();
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
      this->last_error_.store(UPDATE_ERROR_SPI);
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
    this->last_error_.store(UPDATE_ERROR_SPI);
    this->status_set_warning();
    this->mark_failed();
    return false;
  }
  this->spi_setup();
  if (!this->spi_is_ready()) {
    ESP_LOGE(TAG, "Could not restore the E-paper SPI device after OTP read");
    this->last_error_.store(UPDATE_ERROR_SPI);
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

bool GuestyEPaperGray4::read_otp_bank_(uint16_t read_length,
                                       uint16_t bank_base,
                                       uint16_t marker_offset,
                                       uint8_t *check_code, uint8_t *marker,
                                       uint8_t *border_lut) {
  static constexpr uint16_t BORDER_OFFSET = 0x001F;
  if (check_code == nullptr || marker == nullptr || border_lut == nullptr ||
      bank_base >= read_length || marker_offset >= read_length ||
      bank_base + BORDER_OFFSET + BORDER_LUT_LENGTH > read_length)
    return false;

  this->reset_pin_->digital_write(false);
  delay(20);
  this->reset_pin_->digital_write(true);
  delay(20);
  if (!this->wait_until_idle_("during OTP bank read", OTP_IDLE_TIMEOUT_MS))
    return false;

  *check_code = 0;
  *marker = 0;
  std::memset(border_lut, 0, BORDER_LUT_LENGTH);
  this->gpio_write_command_(0xA2);  // READ OTP
  for (uint16_t index = 0; index < read_length; index++) {
    const uint8_t value = this->gpio_read_byte_();
    if (index == bank_base)
      *check_code = value;
    const uint16_t border_start = bank_base + BORDER_OFFSET;
    if (index >= border_start && index < border_start + BORDER_LUT_LENGTH)
      border_lut[index - border_start] = value;
    if (index == marker_offset)
      *marker = value;
    if ((index & 0x3FU) == 0)
      this->service_long_operation_();
  }
  delay(20);
  return true;
}

bool GuestyEPaperGray4::read_otp_profile_(bool *grayscale_supported) {
  static constexpr uint16_t BANK0_READ_LENGTH = 0x0BED;
  static constexpr uint16_t BANK1_READ_LENGTH = 0x17ED;
  static constexpr uint16_t BANK0_BASE = 0x0000;
  static constexpr uint16_t BANK1_BASE = 0x0C00;
  static constexpr uint16_t BANK0_MARKER = 0x0BE3;
  static constexpr uint16_t BANK1_MARKER = 0x17E3;
  static constexpr uint8_t VALID_BANK_CHECK_CODE = 0xA5;

  if (grayscale_supported == nullptr)
    return false;
  this->otp_profile_attempted_this_refresh_ = true;
  *grayscale_supported = false;
  this->border_lut_available_ = false;
  this->border_lut_unavailable_ = false;

  // Read the panel's factory OTP through Seeed_GFX's bidirectional SDA/MOSI
  // sequence. Besides the grayscale marker, retain the selected bank's common
  // 42-byte border LUT. The same bytes can then be written to R25 when the
  // pixel waveforms come from registers; no waveform bytes are bundled here.
  if (!this->release_spi_bus_for_gpio_read_())
    return false;
  this->clock_pin_->setup();
  this->data_pin_->setup();
  this->clock_pin_->pin_mode(gpio::FLAG_OUTPUT);
  this->data_pin_->pin_mode(gpio::FLAG_OUTPUT);
  this->cs_->digital_write(true);

  this->reset_pin_->digital_write(false);
  delay(20);
  this->reset_pin_->digital_write(true);
  delay(20);
  bool probe_ok =
      this->wait_until_idle_("during OTP probe", OTP_IDLE_TIMEOUT_MS);
  if (probe_ok) {
    this->gpio_write_command_(0x40);  // READ INTERNAL TEMPERATURE
    probe_ok = this->wait_until_idle_("before OTP temperature read",
                                      OTP_IDLE_TIMEOUT_MS);
    if (probe_ok) {
      (void) this->gpio_read_byte_();
      (void) this->gpio_read_byte_();
    }
  }

  uint8_t bank0_check_a = 0;
  uint8_t bank0_check_b = 0;
  uint8_t bank0_marker_a = 0;
  uint8_t bank0_marker_b = 0;
  std::array<uint8_t, BORDER_LUT_LENGTH> bank0_border_a{};
  std::array<uint8_t, BORDER_LUT_LENGTH> bank0_border_b{};
  if (probe_ok)
    probe_ok = this->read_otp_bank_(
        BANK0_READ_LENGTH, BANK0_BASE, BANK0_MARKER, &bank0_check_a,
        &bank0_marker_a, bank0_border_a.data());
  if (probe_ok)
    probe_ok = this->read_otp_bank_(
        BANK0_READ_LENGTH, BANK0_BASE, BANK0_MARKER, &bank0_check_b,
        &bank0_marker_b, bank0_border_b.data());

  const bool bank0_checks_match = bank0_check_a == bank0_check_b;
  const bool bank0_valid = bank0_checks_match &&
                           bank0_check_a == VALID_BANK_CHECK_CODE;
  const bool bank0_payload_matches =
      bank0_marker_a == bank0_marker_b &&
      std::memcmp(bank0_border_a.data(), bank0_border_b.data(),
                  BORDER_LUT_LENGTH) == 0;

  uint8_t bank1_check_a = 0;
  uint8_t bank1_check_b = 0;
  uint8_t bank1_marker_a = 0;
  uint8_t bank1_marker_b = 0;
  std::array<uint8_t, BORDER_LUT_LENGTH> bank1_border_a{};
  std::array<uint8_t, BORDER_LUT_LENGTH> bank1_border_b{};
  if (probe_ok && bank0_checks_match && !bank0_valid) {
    probe_ok = this->read_otp_bank_(
        BANK1_READ_LENGTH, BANK1_BASE, BANK1_MARKER, &bank1_check_a,
        &bank1_marker_a, bank1_border_a.data());
    if (probe_ok)
      probe_ok = this->read_otp_bank_(
          BANK1_READ_LENGTH, BANK1_BASE, BANK1_MARKER, &bank1_check_b,
          &bank1_marker_b, bank1_border_b.data());
  }

  const bool bank1_checks_match = bank1_check_a == bank1_check_b;
  const bool bank1_valid = bank1_checks_match &&
                           bank1_check_a == VALID_BANK_CHECK_CODE;
  const bool bank1_payload_matches =
      bank1_marker_a == bank1_marker_b &&
      std::memcmp(bank1_border_a.data(), bank1_border_b.data(),
                  BORDER_LUT_LENGTH) == 0;

  this->clock_pin_->pin_mode(gpio::FLAG_OUTPUT);
  this->clock_pin_->digital_write(false);
  this->data_pin_->pin_mode(gpio::FLAG_OUTPUT);
  this->data_pin_->digital_write(true);
  this->cs_->digital_write(true);
  if (!this->restore_spi_bus_after_gpio_read_())
    return false;

  if (!probe_ok) {
    ESP_LOGW(TAG, "Could not read the UC8179 OTP profile safely");
    return false;
  }

  if (!bank0_checks_match || (bank0_valid && !bank0_payload_matches) ||
      (!bank0_valid && (!bank1_checks_match ||
                        (bank1_valid && !bank1_payload_matches)))) {
    ESP_LOGW(TAG, "Repeated UC8179 OTP reads did not match; keeping border high-Z");
    return false;
  }

  if (bank0_valid) {
    this->border_lut_ = bank0_border_a;
    *grayscale_supported = bank0_marker_a == 0x01;
    ESP_LOGI(TAG, "Using validated UC8179 OTP bank 0 profile");
  } else if (bank1_valid) {
    this->border_lut_ = bank1_border_a;
    *grayscale_supported = bank1_marker_a == 0x01;
    ESP_LOGI(TAG, "Using validated UC8179 OTP bank 1 profile");
  } else {
    this->border_lut_unavailable_ = true;
    ESP_LOGW(TAG, "No valid UC8179 OTP bank; keeping border high-Z");
    return true;
  }

  this->border_lut_available_ = true;
  ESP_LOGI(TAG, "UC8179 OTP grayscale support: %s",
           *grayscale_supported ? "available" : "not available");
  return true;
}

bool GuestyEPaperGray4::ensure_custom_border_lut_() {
  if (this->border_lut_available_ || this->border_lut_unavailable_ ||
      this->otp_profile_attempted_this_refresh_)
    return true;
  bool unused_grayscale_support = false;
  if (this->read_otp_profile_(&unused_grayscale_support))
    return true;
  // A failed SPI restore marks the whole component failed. Other read errors
  // fall back to a high-impedance border and may be retried on a later full
  // refresh without risking partially read bytes in the high-voltage LUT.
  return !this->is_failed();
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
      if (this->read_otp_profile_(&otp_supported)) {
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
  this->active_lut_diagnostic_.store(this->active_lut_mode_);
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
  this->border_mode_.store(this->border_lut_available_
                               ? BORDER_MODE_VALIDATED_LUTBD
                               : BORDER_MODE_HIGH_Z);
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

  // Keep the border at VCOM_DC after its LUT has completed. The older 0x00
  // value selected 0 V for BDEND, which can leave a visible dark border during
  // the controller's final VCOM frames. 0x02 is the documented UC8179 default.
  this->command_(0x52);  // END VOLTAGE SETTING
  this->data_(0x02);     // VCEND=VCOM_DC, BDEND=VCOM_DC

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
  if (this->border_lut_available_) {
    // R25 has different voltage-level semantics from the pixel LUTs. Mirror
    // only the panel's own twice-read, check-code-selected common LUTBD.
    this->write_lut_(0x25, this->border_lut_.data(), BORDER_LUT_LENGTH);
    this->command_(0x50);  // VCOM AND DATA INTERVAL
    this->data_(0x00);     // BDZ=0, BDV=00 selects LUTBD, DDX=00
  } else {
    this->command_(0x50);  // VCOM AND DATA INTERVAL
    this->data_(0x80);     // No validated LUTBD: keep border high-Z
  }
  this->data_(0x07);
  return true;
}

bool GuestyEPaperGray4::init_otp_gray_mode_() {
  this->border_mode_.store(BORDER_MODE_PANEL_OTP);
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

  this->command_(0xE0);  // CASCADE SETTING
  this->data_(0x02);
  this->command_(0xE5);  // Select OTP four-gray waveform
  this->data_(0x5F);
  this->command_(0x50);  // Use the panel's common OTP border LUT directly
  this->data_(0x00);     // BDZ=0, BDV=00 selects LUTBD, DDX=00
  this->data_(0x07);
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
    this->service_long_operation_();
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
    this->service_long_operation_();
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
  // AUTO selection and custom-border preparation share the same OTP reader.
  // Allow one complete attempt per physical full refresh so a transient error
  // cannot immediately consume a second 45-second BUSY timeout. A later full
  // refresh may retry; partial and unchanged-content paths never read OTP.
  this->otp_profile_attempted_this_refresh_ = false;
  // Never report a previous full refresh's waveform or border path while the
  // current attempt is still selecting and validating its controller profile.
  this->active_lut_diagnostic_.store(LUT_MODE_AUTO);
  this->border_mode_.store(BORDER_MODE_UNKNOWN);
  this->update_phase_.store(UPDATE_PHASE_WAVEFORM);
  if (!this->select_lut_mode_())
    return false;
  if (this->active_lut_mode_ == LUT_MODE_CUSTOM &&
      !this->ensure_custom_border_lut_())
    return false;
  this->update_phase_.store(UPDATE_PHASE_RESET);
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
  this->update_phase_.store(UPDATE_PHASE_TRANSFER);
  this->write_plane_(0x10, 0);  // DTM1: inverted least-significant gray bit
  this->write_plane_(0x13, 1);  // DTM2: inverted most-significant gray bit
  this->update_phase_.store(UPDATE_PHASE_REFRESH);
  const bool refreshed = this->refresh_();
  this->deep_sleep_panel_();
  return refreshed;
}

void GuestyEPaperGray4::deep_sleep_panel_() {
  if (this->panel_asleep_)
    return;
  this->update_phase_.store(UPDATE_PHASE_SHUTDOWN);
  // The UC8179 border is a separate electrode outside the 800x480 pixel RAM.
  // Its visible pigment state is established by LUTBD during DISPLAY REFRESH;
  // this step only releases the electrode before power-off. Keep the already
  // hardware-tested shutdown register while BDZ makes its BDV selection inert.
  this->command_(0x50);  // VCOM AND DATA INTERVAL SETTING
  this->data_(0x90);     // BDZ=1, BDV=01, N2OCP=0, DDX=00
  this->data_(0x07);     // Documented VCOM/data interval
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
