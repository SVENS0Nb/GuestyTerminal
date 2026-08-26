# GuestyTerminal agent guide

This file applies to the entire repository. It is the working guide for coding
agents and contributors; `README.md` remains the user-facing product and setup
documentation.

## Project at a glance

GuestyTerminal connects Guesty reservations to Seeed Studio reTerminal E1001
E-paper displays through Home Assistant and ESPHome. The repository contains
two coupled deliverables:

1. A Home Assistant custom integration that polls Guesty, normalizes listings
   and reservations, builds privacy-bounded display payloads, and sends them to
   awake ESPHome devices.
2. ESPHome firmware for the E1001, including a custom UC8179/GDEY075T7
   four-grayscale driver, layout rendering, duplicate suppression, weather-only
   partial refresh, power management, and diagnostic entities.

The supported product name is **GuestyTerminal** everywhere. Preserve that
spelling in UI copy, device project metadata, documentation, and releases.

## Repository map

- `custom_components/guesty_terminal/`: Home Assistant integration.
  - `api.py`: Guesty OAuth and HTTP client.
  - `models.py`: Guesty normalization, reservation selection, localized display
    payloads, content fingerprints, and privacy leases.
  - `coordinator.py`: polling, lookup caches, weather extraction, and payload
    assembly.
  - `runtime.py`: ESPHome endpoint discovery and version-aware action calls.
  - `config_flow.py`: credentials, per-display mappings, global logo, and
    firmware-generation UI.
  - `firmware.py` / `firmware_update.py`: managed ESPHome YAML generation and
    fleet OTA queueing through ESPHome Device Builder.
  - `button.py` / `sensor.py`: central firmware-update button and privacy-safe
    integration diagnostics.
  - `localization.py`: guest-facing display presets for German, English,
    French, and Spanish.
  - `strings.json` and `translations/*.json`: Home Assistant UI translations.
  - `brand/`: Home Assistant brand assets.
- `esphome/packages/reterminal-e1001-guesty-terminal.yaml`: device behavior,
  action schema, power logic, entities, fonts, and display layout.
- `esphome/components/guesty_epaper_gray4/`: external ESPHome component and
  four-level/partial-refresh panel driver. Its `LICENSE` and
  `SEEED_GFX_LICENSE.txt` files preserve the notices for the fixed Seeed source
  revisions documented in `THIRD_PARTY_NOTICES.md`.
- `esphome/guestyterminal-display-1.yaml`: local reference configuration.
- `tests/`: unit and contract tests for both Python behavior and important
  firmware/YAML invariants.
- `.github/workflows/tests.yml`: authoritative CI commands.
- `README.md` / `CHANGELOG.md`: user-facing setup, architecture, compatibility,
  release notes, and the chronological product history.
- `TROUBLESHOOTING.md`: confirmed incident causes, acknowledgement-based fault
  isolation, and regression-prevention rules. Keep conclusions precise about
  what logs and real-device checks actually prove.
- `CONTRIBUTING.md` / `SECURITY.md`: contributor workflow and private security
  reporting rules.
- `LICENSE_STATUS.md` / `THIRD_PARTY_NOTICES.md`: current distribution status,
  remaining owner decisions, asset and driver provenance, fixed versions, and
  licenses.

Generated ESPHome build files under `esphome/.esphome/`, Python caches, coverage
artifacts, and real `secrets.yaml` files are not source. Do not inspect or edit
them as if they were part of the implementation.

## End-to-end data flow

1. `GuestyClient` obtains a Client Credentials token and fetches listings,
   current/recent confirmed reservations, and an ordered upcoming snapshot for
   every mapped listing from Guesty's API. It queues its own requests according
   to Guesty's documented account-wide limits and can verify already-known
   active reservations by V3 ID in batches of at most ten.
2. `GuestyTerminalCoordinator` resolves full listing details, guest names, the
   `keycode` custom field, and optional Home Assistant weather data.
3. `build_display_payload()` selects the visible reservation and produces one
   bounded `DisplayPayload` per configured ESPHome endpoint.
4. `GuestyTerminalRuntime` reads the endpoint sensor's action name and sends
   only fields supported by that action version.
5. The current ESPHome `...update_display_v10` action adds a random transport
   correlation token to the v9 visible schema, publishes received/rendering/
   physical-result acknowledgements, updates RAM state, compares opaque
   fingerprints, redraws only when necessary, and returns to deep sleep on
   battery only after confirmed delivery. v1 through v9 remain legacy inputs.

When changing a field or behavior, follow this flow in both directions. A field
that exists only on one side of the Home Assistant/ESPHome boundary is an
incomplete change.

## Non-negotiable product behavior

### Reservation selection and time semantics

- A reservation becomes visible one hour before check-in and is removed 30
  minutes after checkout by default. Both values are configurable per display.
- Guesty is polled every five minutes by default. Every successful poll must
  reconcile current/recent stays plus at least the next five confirmed
  reservations per mapped listing. Additions, visible-field changes, and rows
  that disappear because of cancellation replace that listing's RAM snapshot;
  an equal normalized snapshot must be retained without a cache write.
- A confirmed reservation that has completed remains in the Home Assistant RAM
  snapshot until 12 hours after checkout, even if it disappears from a later
  successful Guesty response. This retention does not extend the display's
  configured post-checkout visibility. Future cancellations are removed
  immediately and are never retained until their planned checkout. If the same
  reservation ID is freshly owned by another listing after a timed stay
  transition, remove the previous listing copy immediately instead of applying
  completed-stay retention to both.
- Upcoming snapshot queries are authoritative and must not use a TTL. Isolate a
  current/upcoming or active-ID verification failure to every affected listing
  and retain those listings' last successful data rather than interpreting the
  failure as a cancellation. Other listings may still reconcile normally.
  Do not build or send a new payload for a failed listing: retaining its RAM
  snapshot must never renew the 15-minute display lease. If no mapped listing
  succeeds, fail the coordinator refresh and retain its previous complete data.
  Authentication, account-discovery and rate-limit failures remain
  refresh-wide failures. The display lease limits how long stale sensitive
  content can remain visible.
- If a cached confirmed reservation is active at the captured refresh instant
  but filtered search omits it or no longer routes it, verify that known ID via
  `GET /reservations-v3` with `reservationIds[]` batches of at most ten before
  removing it. A successful response that omits the requested ID is
  authoritative removal. A failed verification preserves every affected
  listing snapshot. A by-ID response has no filtered query context and must
  represent a mapped identity itself; never route it from old cache ownership.
  An incomplete active projection is verified or protected rather than treated
  as a cancellation. Never apply this fallback to future reservations: absence
  from a successful upcoming snapshot remains an immediate cancellation.
- Capture one timezone-aware UTC timestamp at the beginning of a coordinator
  refresh and pass it as `as_of` to API date filters and as `now` to stay
  routing and normalization. Use the same value for snapshot pruning,
  reconciliation, reservation selection, and every payload built during that
  refresh. Do not take separate wall-clock readings at those layers; crossing
  a check-in, checkout, or local checkout-page boundary mid-refresh must not
  produce contradictory screens.
- Guesty multi-unit reservations may expose a concrete `unitId`, a legacy
  `listingId`, an overlying `unitTypeId`, and a `parentListingId` across the
  top-level response, nested `listing`, or any `stay` segment. Preserve all
  represented identities and resolve them only against listings mapped and
  available in the current coordinator refresh.
- A reservation may contain several chronological `stay` segments. At the
  captured refresh instant prefer the active timed segment, otherwise the next
  one, otherwise the most recently completed one. That segment's identities
  override stale top-level identities. Use V3 `stay.checkIn`/`stay.checkOut`
  for ownership boundaries; localized dates combine with explicit planned or
  exact segment times for display copy. If any segment window is incomplete,
  preserve every represented identity and normalize a uniquely matched segment
  only when its own window is complete, otherwise use safe whole-reservation
  boundaries.
- Route each normalized reservation to exactly one listing. Prefer a concrete
  `unitId`, then a direct/legacy `listingId`, then `unitTypeId`, then
  `parentListingId`. If both a concrete unit and its unit type are mapped, the
  concrete unit owns the assigned stay. Current/recent and upcoming searches
  are scoped to each distinct mapped listing. Add one account-scoped
  current/recent discovery snapshot because Guesty's V3 `filter[listingId]`
  evaluates only the first stay segment; locally discard every row that cannot
  be resolved to a mapped identity. Then resolve all projections of the same
  reservation together. The query listing is a fallback only for a genuinely
  filtered search when no projection contains a mapped identity and exactly one
  query context remains. Account-wide and by-ID rows never receive such a
  fallback. If several contexts remain ambiguous, skip the reservation rather
  than copying sensitive content to multiple listings.
- Merge duplicate projections before normalization with current/recent data as
  the primary observation. Merge every current projection before upcoming
  rows; other projections may fill only absent data.
  Explicitly empty `notes`, `customFields`/`customField`/`fields`,
  `guest`/`guestId`/`bookerId`, channel metadata, door-code fields, and
  identified list entries remain authoritative across all Guesty alias shapes.
  A clear in any equally authoritative current/recent projection overrides a
  populated sibling before upcoming data is merged; never revive sensitive
  content from an older projection or optional enrichment endpoint.
- Queue every Open API request made by one client through sliding limits of
  15 requests per second, 120 per minute, and 5,000 per hour. On HTTP 429,
  expose the bounded `Retry-After` value to the coordinator and defer subsequent
  client requests by immediately returning the remaining rate-limit error; do
  not hide it behind a long automatic retry. Cancel sibling requests after the
  first parallel failure. Reserve a sliding-window slot only immediately before
  the API request, after any OAuth refresh. Keep
  connection/request/response exceptions typed and free of paths, Guesty
  response messages, reservation IDs, and other sensitive values.
- Treat a missing `results` member, a non-array collection, non-object rows,
  missing row IDs, an empty page that claims `pagination.hasMore`, duplicate
  by-ID rows, and invalid listing-detail identities as response errors. Never
  turn a malformed or internally inconsistent HTTP-200 body into an
  authoritative empty snapshot. Sanitized transport errors must also have no
  chained cause/context that could expose request paths or reservation IDs in
  a traceback.
- Guesty applies those limits account-wide across all API tokens. The
  per-client queue is a conservative in-process guarantee, not permission for
  separate clients or Home Assistant instances to spend the full quota each.
- On the local checkout date, the checkout page replaces the welcome page from
  the per-display start time (05:00 by default) until the normal checkout grace
  expires. It never renders door or WiFi credentials. Its weather and global
  logo remain available.
- Outside the welcome/check-out visibility window, the empty-room page shows
  the earliest later confirmed reservation. It contains the first name and
  inherited localized booking period, plus only non-empty General notes, Notes
  for cleaner, and Special requests. With zero/one/two/three notes, render
  zero/one/two/three cards; never reserve empty columns. This page has no
  footer, door code, WiFi data, or global logo.
- Selection is based on Guesty status `confirmed`. Never make display
  eligibility depend on payment, balance, payout, or Airbnb settlement state.
- Prefer a current stay, then a just-ended stay still inside its configured
  checkout grace period, then the next arrival. This keeps the checkout page
  visible for the full explicitly configured grace period; a new current stay
  takes over immediately at its check-in time.
- Guest-facing times use `checkInDateLocalized` / `checkOutDateLocalized`
  combined with planned times or the listing defaults. This avoids treating
  channel-imported floating local timestamps as trustworthy UTC instants.
- Perform comparisons with timezone-aware datetimes and render in the listing's
  timezone. Invalid/missing timezones fall back safely to UTC.
- The door code comes from Guesty's `keycode` data. Keep tolerant support for
  direct `keycode`/`keyCode`/`doorCode`, nested populated custom fields with
  `value` or `code`, and field-ID resolution through account custom-field
  definitions. Resolve opaque current-projection field IDs before consulting
  the keycode cache or populated-fields endpoint. An explicit current empty
  value must remain empty through merge, enrichment, and normalization; never
  revive it from raw aliases, stale cache data, or an older projection. If
  refreshing expired field definitions fails, fail closed instead of treating
  the expired definitions as authoritative.

### Privacy and secret handling

- Never log, expose in exceptions, publish as diagnostic attributes, or commit
  Guesty credentials, OAuth tokens, door codes, WiFi passwords, API encryption
  keys, OTA passwords, or fallback AP passwords.
- OAuth tokens belong in Home Assistant's private `Store`; Guesty credentials
  remain in config-entry data. Devices receive guest-visible data only, never
  Guesty API credentials.
- Generated ESPHome files are private (`0600`), use `!secret` for WiFi, and get
  independent random API/OTA/fallback credentials. Regeneration must preserve
  those credentials so OTA access is not broken.
- Only overwrite an ESPHome YAML bearing `FIRMWARE_HEADER` and containing
  recoverable managed credentials. Never overwrite a user-owned or malformed
  file.
- Door and WiFi values remain in ESP32 RAM. Flash/RTC persistence is limited to
  non-sensitive neutral copy, privacy state, render revision, and opaque salted
  fingerprints. Do not add credential-bearing `restore_value` globals.
- Empty-room guest names, dates, and internal reservation notes are also
  sensitive RAM-only content. They use the display lease and must never be
  added to `restore_value` globals, a Home Assistant disk cache, or log
  messages. The five-booking Home Assistant snapshot is process-memory only.
- Home Assistant diagnostics may report flags, listing names, entity IDs,
  weather configuration, and lease timestamps, but never guest names, codes,
  SSIDs, or passwords. The device's displayed-booking text sensor is the one
  intentional remote confirmation and must not include access credentials.
- Keep the renewable display lease (currently 15 minutes). Lease renewal must
  not itself change the visible-content fingerprint or force an E-paper flash.
  Expired cached payloads must be replaced with an idle payload before any
  normal or forced redraw.

### E-paper refresh behavior

- Keep logical and controller color polarity separate. The ESPHome framebuffer
  stores `0=black` through `3=white`; UC8179 four-gray DTM data must receive
  `3 - framebuffer_gray` before its least- and most-significant bits are sent
  to `0x10` and `0x13`. The monochrome differential path keeps its independent
  convention of `0=black`, `1=white`.
- Do not refresh the physical panel when visible content is unchanged. The
  `content_id` includes every visible field and a high-entropy reservation ID;
  `base_content_id` intentionally excludes weather.
- A full redraw is required for booking, access data, copy, logo, layout, or
  renderer changes. A weather-only change may request a partial refresh. On the
  empty-room page, the same header window contains the local battery icon and a
  percentage quantized to five-percent steps; a battery-only change may also
  use the partial-refresh path.
- The supported partial window is the monochrome header-status region at
  `x=640, y=8, width=136, height=64`, with at most five consecutive partial
  updates before a full grayscale refresh.
- The driver must retain the previous header bitmap across deep sleep and
  rebuild both complete UC8179 controller RAM planes after reset before a
  differential refresh. Updating only the small RAM window causes panel-wide
  noise and is not acceptable.
- The partial window is deliberately quantized to black/white while the rest of
  the display retains four grayscale levels. Keep window bounds byte-aligned
  and within the driver's 2048-byte retained buffer.
- In `auto` mode, probe the two Seeed-documented UC8179 OTP markers once, use
  the panel's internal four-gray waveform when supported, and otherwise use
  the MIT-licensed Seeed E1001 register LUTs. Retain the non-sensitive result in
  RTC memory across deep sleep; a failed probe falls back safely without
  persisting an uncertain result. Keep explicit `custom` and `otp` modes for
  existing configurations.
- The E1001 `auto` OTP probe temporarily uses SDA/MOSI as a bidirectional GPIO.
  Tear down the SPI device, free the dedicated ESP32-S3 SPI2 host, perform the
  GPIO read, then initialize SPI2 with the same pins, MISO, transfer size,
  flags, and DMA configuration before recreating the device. A failed bus
  restore must fail closed; `spi_setup()` alone is not a bus reinitialization.
- After UC8179 `POWER ON` and `DISPLAY REFRESH`, preserve Seeed's fixed 100 ms
  guard and then wait until active-low `BUSY_N` is inactive/high. Do not require
  witnessing a low assertion edge that may already have completed during the
  guard period.
- Keep the UC8179 pixel waveform and its separate border electrode decoupled.
  Every normal OTP or register-LUT full refresh uses `R50h=0x90,0x07`, whose
  documented `BDZ=1` leaves the border high-impedance without changing either
  DTM pixel plane. Differential partial refreshes must preserve the same
  high-Z border state, including the `R50h=0xA9,0x07` partial-window value.
  A bounded border recovery may run only on confirmed external power. It
  independently reconstructs the former monochrome controller behavior from
  the UC8179 register documentation: program `R01h=07,07,3F,3F`,
  `R50h=0x10,0x07`, `R60h=0x22`, `R00h=0x1F`, the 800x480 `R61h` geometry and
  single-SPI `R15h=0x00`; power the controller off and on; transfer the current
  framebuffer quantized to monochrome only through DTM2/R13h; then refresh and
  power down. Immediately redraw the untouched four-level framebuffer with the
  selected OTP/register pixel waveform and high-Z border. This is a functional
  compatibility sequence, not a driver switch. Never copy GPL ESPHome driver
  code, turn the recovery into a periodic refresh, or let it change content
  fingerprints. Do not copy panel OTP bytes into `R25h`: the previously added
  `R25/LUTBD` path left `BUSY_N` asserted after the visible frame settled on
  the real E1001 and produced repeated identical redraw attempts. The `auto`
  probe may read check codes and grayscale markers twice, with bank 0 priority,
  but it must not retain, log, bundle, or replay raw OTP waveform bytes.
  Do not write `R50h` immediately before `POWER OFF`; the UC8179 command itself
  releases Source, Gate, Border, and VCOM to floating, and the late R50 variants
  tested in 0.3.34 through 0.3.43 did not whiten an already-dark bistable
  border. Retain the shared full, partial, failure, and safe-shutdown path.
- The static LUTs, bidirectional OTP read pattern, base initialization, plane
  order, and partial-window sequence come from the fixed permissively licensed
  Seeed revisions in `THIRD_PARTY_NOTICES.md`. Bank priority, check codes,
  register fields, and OTP address mapping are independently implemented from
  the official UC8179 datasheet documented there. Preserve the component's two
  local license files and distinguish source-derived sequences from datasheet
  facts when changing this path. Do not introduce driver sequences or waveform
  tables without clear redistribution terms.
- `guesty_render_revision` invalidates otherwise-identical images after a
  rendering or driver change. When a visible rendering change requires one
  repaint, increment the expected value and the stored-success value together,
  and update their tests. The current source revision is 31.
- Publish the displayed-booking confirmation only after a successful physical
  refresh, or when a restored matching fingerprint proves the same content was
  previously drawn.
- Page selection is volatile ESP32 runtime state. Restore the payload's page on
  every received action, even when the retained fingerprint suppresses the
  physical refresh; otherwise a later local update can repaint the first page.
- Treat panel timing, BUSY polarity, LUTs, plane order, reset sequence, and
  partial-refresh commands as hardware-sensitive. Do not simplify them without
  an ESPHome compile and real-device verification.

### Power and hardware behavior

- `auto` mode sleeps on battery and remains online on external power. `battery`
  always sleeps; `mains` always remains online.
- Detect E1001 v1.2 through an identified SY6974B (`REG0B` part-ID mask) and
  its dedicated `REG0A.BUS_GD` bit on `guesty_power_i2c`. Do not substitute the
  BC1.2 source classification in `REG08.BUS_STAT`: CDP, unknown, and
  non-standard adapters are still valid external power. One exact ID match is
  sticky for that boot; three matches may persist the non-sensitive hardware
  revision. A known v1.2 board must still attempt `REG0A` when an individual
  later ID read fails, and it must never enter the legacy fallback.
- E1001 v1.0 has an ETA6003 without a readable VBUS status. Only while no
  SY6974B has been identified, use the TYPEC_5V-powered USB-UART bridge TXD on
  UART0 RX/GPIO44 as the legacy signal. Before every power observation, pause
  UART0 console writes, detach GPIO43 from UART0, drive it low for at least 50
  ms to prevent phantom power through bridge RX, and enable GPIO44 input with a
  pull-down. Require three consistent multi-sample windows. Restore UART0
  through `uart_set_pin()` only after a raw external-power observation; absent
  or unresolved observations leave GPIO43 low. Quiesce UART0 again immediately
  before every deep-sleep entry. A single-mode script prevents cancellation or
  stale queued observations while another caller waits for the active probe.
  A continuously asserted UART BREAK is physically indistinguishable from an
  unpowered legacy bridge through GPIO44 alone; keep that limitation in the
  hardware test matrix and release notes.
- Require three consistent samples or windows. A previously confirmed cable
  may survive one unresolved measurement batch, but two unresolved batches
  fail safely to battery behavior. Preserve the diagnostic entities
  `External power` and `Power detection method` so the active hardware path is
  observable without exposing sensitive data.
- The default battery cycle is 30 minutes with a maximum awake window of 90
  seconds. After Home Assistant delivers a payload, the device may sleep
  earlier.
- Battery voltage uses 16 averaged ADC samples with the board's 2x divider.
  Convert voltage to percent with ESPHome's exact piecewise calibration points
  from 3.27 V/0% through 4.15 V/100%; do not replace them with a least-squares
  line. This remains a voltage estimate rather than a coulomb counter.
- Preserve the diagnostic entities `Battery voltage`, `Battery level`,
  `Wake-up reason`, and `Awake duration`, plus `External power` and
  `Power detection method`. Publish awake duration through the shared sleep
  script immediately before deep sleep, and keep timer, button, cold-boot, and
  other wake reasons distinguishable.
- Route every normal battery sleep entry through that shared script. It must
  disable the battery measurement circuit and unused peripherals, publish the
  awake duration, mark the OTA boot successful, and only then enter deep sleep;
  do not duplicate partial sleep sequences in action or watchdog paths.
- A device already in deep sleep is expected to notice newly connected USB
  power at its next scheduled wake and then stay online. Do not reintroduce a
  separate periodic USB wake/probe mechanism unless the product requirement is
  explicitly changed.
- If a battery wake receives no payload while sensitive content may still be on
  screen, clear to the localized idle screen before sleeping. On permanent
  power, enforce lease expiry continuously because no next wake is guaranteed.
- Keep the status LED, buzzer, and microphone power disabled. On v1.2 the
  charging LED's STAT output is disabled over the charger's dedicated I2C bus;
  GPIO-only changes are insufficient. The v1.0 ETA6003 has no equivalent
  software-disable bit, so documentation must not promise that its hardware
  charging LED is off.
- Keep the unused SD-card load switch explicitly disabled through active-high
  GPIO16 during boot and every normal battery-sleep path. Its TPS22916 pulldown
  is a hardware fallback, not a replacement for a defined firmware output.
- Preserve the E1001 pin assignments and the non-inverted active-low BUSY
  interpretation unless verified against the hardware schematic and device.

### Configuration persistence and localization

- Mappings are per endpoint and must retain the selected listing, language,
  custom copy, labels, timing, EU/US format, visibility switches, and weather
  entity when reopened.
- Checkout-page copy and start time are stored in that same mapping but edited
  through their own options-flow page. They inherit the mapping language and
  date/time format. An explicit language change resets checkout copy to that
  language's presets just like welcome/idle copy.
- Empty-room copy and its three note headings are stored in the same mapping
  and edited through their own options-flow page. They inherit language and
  EU/US formatting; an explicit language change resets them to the selected
  language presets while reopening the page preserves manual edits.
- A new mapping starts in Home Assistant's supported system language. Keeping
  the same display language preserves custom text; explicitly changing the
  language replaces text fields with that language's presets, after which edits
  are persisted.
- Guest-facing language presets and Home Assistant UI translations are separate
  layers. For new display text, update `localization.py`, `MappingOptions`, the
  config flow, payload/action schema, renderer, and tests. For UI text, update
  `strings.json` plus every file in `translations/` (`de`, `en`, `fr`, `es`).
- The uploaded footer logo is global for the config entry, not per display. It
  is cropped, resized, right-aligned on a 144x48 canvas, quantized to four
  levels, and rendered without a border.

## Home Assistant and ESPHome compatibility

- Query every distinct mapped listing once per coordinator refresh, then build
  one independent payload per endpoint. Multiple displays may share a listing
  while retaining different language, copy, date/time format, visibility, and
  weather options. Reservations, credentials, and notes from different listing
  IDs must never cross into another endpoint's payload.
- One physical ESPHome endpoint may be owned by only one Guesty config entry.
  Continue blocking legacy duplicate mappings at setup and in the options flow.
  Entry removal must not clear an endpoint that remains mapped by another
  Guesty entry.
- The endpoint entity is discovered by original name `GuestyTerminal Endpoint`
  or the `_guesty_terminal_endpoint` suffix. Its state is the exact ESPHome
  action name, not a status value.
- The runtime accepts legacy action suffixes through v9 and sends fields only
  when that version supports them. Preserve old action handling unless a
  deliberate compatibility break is documented and released.
- The v10 transport is acknowledged through privacy-safe endpoint sensor
  pulses. Keep the ESPHome action in `supports_response: none` mode: native
  action-response timeouts are shorter than the safe panel completion window.
  Submit the Home Assistant service with `blocking=True` so connection errors
  remain inside GuestyTerminal's neutral exception boundary, then wait for the
  endpoint pulses independently. Generate a fresh high-entropy correlation
  token per submitted job;
  validate the fixed lowercase-hex token format before firmware state
  publication, and never publish an arbitrary caller-supplied token;
  require received plus success/unchanged before reporting delivery, use
  bounded receipt/completion/endpoint-restore waits, and keep retries
  serialized per endpoint. Reconnect replay may complete the current waiter
  but must never schedule a second renderer job. A failed v10 action must not
  mark the battery wake as delivered; leave time for retry and preserve the
  normal privacy-clear-at-awake-deadline behavior. Integration setup must
  schedule initial delivery without awaiting physical completion. After a
  confirmed battery result, endpoint unavailability is a valid terminal-ready
  signal because deep sleep cannot restore the action name.
- Treat the last v10 acknowledgement as a strict fault boundary: no
  `received` means discovery or transport; `received` without `rendering`
  means the synchronous ESPHome action path before the renderer; `rendering`
  without a physical result means renderer, serialization, or panel work. Do
  not blame Guesty selection or the panel driver across those boundaries
  without contradictory evidence.
- Never call `generate_qr_code()` from a payload action. Set the volatile value
  only and let the renderer's single `get_size()` call generate it after the
  action arguments have unwound. Preserve the 16 KiB ESP32 loop-task stack;
  the QR encoder needs roughly 4 KiB of temporary stack and the 8 KiB default
  overflowed in the argument-heavy welcome action before `rendering`. A panel
  hardware test bypasses this QR path and therefore cannot validate normal
  booking delivery. ESPHome's QR `dump_config()` prints its current value, so
  reset the component to the neutral `GuestyTerminal` placeholder immediately
  after synchronous framebuffer construction; reconstruct it briefly before a
  self-test restores a welcome page.
  Keep the MIT-licensed QR generator pinned to the fixed upstream Git revision
  documented in `THIRD_PARTY_NOTICES.md`; do not reintroduce a release-time
  dependency on the PlatformIO registry without an equally reproducible
  fallback.
- A v10 `panel_error` or `panel_timeout` is a deterministic physical failure,
  not an action-registration race. Do not retry the same payload immediately.
  The firmware keeps the failed content fingerprint only in volatile RAM and
  reports later identical normal deliveries without another panel refresh.
  Changed content, an explicit forced refresh, or a reboot may try again.
- Schedule physical display jobs with Home Assistant background tasks, not
  setup-tracked tasks. Retain local cancellation ownership so integration
  unload still stops every outstanding delivery.
- ESPHome service exceptions can contain the complete credential-bearing
  request. Log only a neutral fixed message: never include the exception text,
  traceback, chained cause, or serialized service data.
- For a new payload schema, add a new versioned action rather than silently
  changing the arguments of an existing one. Update, at minimum:
  `const.py`, `DisplayPayload.as_service_data()`, `runtime.py`, the ESPHome
  package action and endpoint state, and runtime/firmware tests.
- The endpoint pulse in `api.on_client_connected` works around the race where
  ESPHome publishes the sensor before registering the user-defined action. Keep
  the delayed resend behavior when changing discovery.
- The per-device **Display aktualisieren** button publishes a one-shot endpoint
  request. The integration must refresh Guesty first and then send one forced,
  authoritative redraw to that display. Suppress the endpoint's immediate
  action-state restore and the coordinator's ordinary push while this request
  is pending, so stale RAM cannot win the race. If another listing succeeds but
  the requested endpoint's listing remains unverified, neither redraw nor clear
  it; let its existing lease expire instead.
- The central integration button updates every GuestyTerminal-managed YAML to
  `FIRMWARE_VERSION` and queues OTA jobs through ESPHome Device Builder. It must
  ignore user-owned YAML and report only non-sensitive counts/status.
- Managed files without `flash_size` are legacy 4 MB layouts. New USB installs
  may use the E1001's complete 32 MB flash, but overwriting an existing managed
  device with a different layout requires an explicit USB-migration
  confirmation. Version-only fleet updates must preserve every layout line and
  must never imply that an OTA application image rewrote the partition table.
  Keep 4 MB as the safe default until the experimental ESPHome 32 MB path and a
  complete USB migration have passed the real-device release matrix.
- `hacs.json` declares Home Assistant 2025.12 as the minimum; CI tests both the
  minimum 2025.12.0 release and the 2026.2.3 baseline. Do not lower
  compatibility accidentally.

## Change-impact checklist

Use the smallest applicable row, then inspect all named layers:

| Change | Required impact review |
| --- | --- |
| Guesty API shape, endpoint, or limit | `api.py`, V3 ID batching, 429/Retry-After behavior, privacy-safe exception shape, coordinator failure isolation, API and coordinator tests |
| Guesty listing or multi-unit identity | `reservation_listing_ids()`, contextual coordinator routing, per-listing deduplication, snapshot ownership, model/coordinator isolation and three-screen transition tests |
| Booking timing/status/timezone | `models.py`, coordinator query window, privacy lease, model/coordinator/runtime tests |
| New per-display option or text | constants, localization presets, `MappingOptions` load/save, config flow, translations, payload, action, renderer, tests |
| New visible payload field | fingerprints, versioned ESPHome action, runtime version negotiation, globals/rendering, tests |
| Layout/font/logo/weather rendering | package YAML, `content_id`, render revision, partial-window containment, firmware tests, hardware check |
| Panel/LUT/partial-refresh code | component Python schema, C++/header, SPI2 teardown/reinitialization, 100-ms/BUSY timing, render revision, package geometry, compile, hardware full/partial/deep-sleep tests |
| Power/deep-sleep behavior | boot/action/interval paths, privacy fallback, external-power detection, README, firmware tests, battery and USB hardware checks |
| Battery estimate, VBUS detection, or power diagnostics | 16-sample ADC path, exact piecewise curve, sticky `REG0B`/`REG0A.BUS_GD` v1.2 path, UART0 GPIO43/GPIO44 anti-backfeed v1.0 path, sleep script, diagnostic entities, firmware contract tests, battery and USB hardware checks on both revisions |
| Home Assistant entity/service | platform forwarding, entity IDs/unique IDs, strings/translations, tests, README |
| Firmware generation/update | managed header, exact template structure, credential preservation, atomic writes, updater parser, tests |

## Development workflow

Before editing:

1. Read `git status --short --branch` and preserve unrelated user changes.
2. Read the source and tests on both sides of any HA/ESPHome boundary involved.
3. Make the smallest coherent change; do not edit generated caches or compiled
   ESPHome output.

Python targets 3.13, uses 88-character Ruff formatting, and is tested with
Home Assistant's real Python package. In an activated virtual environment:

```bash
python3 -m pip install -r requirements-test.txt
ruff check .
ruff format --check .
mypy custom_components/guesty_terminal
python3 -m compileall -q custom_components/guesty_terminal
pytest
```

`pytest` enforces at least **80% branch coverage** for
`custom_components/guesty_terminal` via `pyproject.toml`. New logic needs
behavioral tests, including failure/privacy paths; do not satisfy the gate with
tests that merely mirror implementation details.

For an autofix during development, use `ruff check --fix .` and `ruff format .`,
then review the diff. CI uses the non-mutating commands in
`.github/workflows/tests.yml`.

For ESPHome changes, create an untracked `esphome/secrets.yaml` from
`esphome/secrets.example.yaml`, use non-production values, and run:

```bash
esphome config esphome/guestyterminal-display-1.yaml
esphome compile esphome/guestyterminal-display-1.yaml
```

CI overrides the reference configuration's flash substitutions and compiles
the safe 4 MB and optional 32 MB profiles as parallel jobs. Keep both matrix
entries and their distinct 95% app-partition budgets when changing firmware.

The reference YAML loads the component locally. Compilation needs network
access for ESPHome dependencies, Google fonts, and the pinned Material Design
Icons webfont. Never commit the real secrets or `.esphome/` build directory.
For a documentation-only change, a full firmware compile is unnecessary.

After editing:

- Review `git diff --check` and `git diff`.
- Validate modified JSON files (for example with `python3 -m json.tool`).
- Confirm UI translation keys remain aligned across `strings.json` and all four
  translation files.
- Run the tests proportional to the change, then the complete CI suite before a
  release or when shared models/runtime/firmware contracts changed.
- Ensure `README.md`, `CHANGELOG.md`, `AGENTS.md`, and `CONTRIBUTING.md` still
  describe the behavior, commands, compatibility, and release requirements
  affected by the change.
- State clearly when hardware behavior was compiled but not tested on a real
  E1001.

## Release and versioning rules

Do not commit, push, tag, publish a release, or queue real OTA jobs unless the
user explicitly requests that external action.

Every public release must use `.github/workflows/release.yml`; do not create or
push a release tag with local Git commands and do not call `gh release create`
directly. After an explicit publication request, first put the intended commit
on `main` and wait for the `Tests` workflow for that exact commit to succeed.
Then dispatch `Release` from `main` with the truthful real-device hardware
status and the explicit distribution-review confirmation, and wait for that
workflow to finish. The workflow derives the version from the repository,
revalidates the metadata and notices, confirms that `main` has not advanced,
requires the exact successful CI revision, generates the release notes, and
only then creates the tag and GitHub release. A tag push is deliberately
excluded from `Tests`, so publishing does not repeat the already-green build.

When subagents are available, every release preparation includes one read-only
mechanical audit by the fastest suitable lower-cost model (currently
`gpt-5.6-luna`): version agreement, changed-file inventory, CI result for the
exact SHA, generated-note completeness, and tag/release collision checks. That
subagent must not edit files, decide rights or hardware safety, handle secrets,
push, tag, or publish. The primary agent retains all privacy-, driver-,
distribution-, hardware-, and final-publication decisions and independently
checks the audit result. If no suitable subagent is available, the primary
agent performs the same audit; no release gate may be skipped.

For a release, use one semantic version consistently in:

- `custom_components/guesty_terminal/manifest.json`
- `custom_components/guesty_terminal/firmware.py` (`FIRMWARE_VERSION`)
- `esphome/guestyterminal-display-1.yaml`
- version-specific tests, `CHANGELOG.md`, and the release section in
  `README.md`

Before any public release or redistribution, read `LICENSE_STATUS.md` and
`THIRD_PARTY_NOTICES.md`. If they document an unresolved right or redistribution
blocker that applies to the release, stop and request an explicit project-owner
decision; a generic request to publish does not resolve third-party rights or
select a project-wide license. The machine-readable marker in
`LICENSE_STATUS.md` records the owner's existing proprietary-source decision,
but every workflow run still requires a fresh distribution-review confirmation.
This check is required even when no asset or driver file changed.

Generated managed YAML contains two GitHub refs and one ESPHome project version.
The updater intentionally requires exactly those three versions to match and
updates them atomically while preserving credentials and permissions. If the
template structure changes, update the parser and its malformed/future-version
tests together.

Firmware generation pins both the package and external component to
`v<FIRMWARE_VERSION>`. That Git tag must contain the referenced files before
users can compile newly generated configurations. Run the complete Python
suite, ESPHome config validation, and preferably a firmware compile before
tagging. State in `README.md` and the GitHub release whether existing displays
need a firmware update; integration-only changes may remain compatible with the
previous device firmware even though all release version markers advance
together. Release notes must name the tested Home Assistant/ESPHome versions,
coverage result, firmware build status, and any missing real-device test.
Hardware-affecting releases also require checks of:

- full four-gray refresh and legible fonts;
- no dark outer border after repeated `auto`, `otp`, and `custom` full refreshes,
  including cold boot, deep sleep, and a partial-to-full fallback;
- unchanged-content suppression;
- weather-only partial refresh across reset/deep sleep and fallback after five
  partial updates;
- forced redraw and displayed-booking confirmation;
- v10 received/rendering/success acknowledgement, reconnect replay during a
  full refresh, bounded failure reporting, and no duplicate panel job;
- neutral reset/delivery/panel/waveform/border diagnostics matching the actual
  hardware path without payload values or correlation tokens in downloads;
- the externally powered neutral panel self-test completing one four-gray full
  refresh, one real partial header refresh and restoration of the prior page;
- GPIO16 remaining low during boot and every shared sleep entry;
- legacy 4 MB OTA retention plus a separate full-USB 32 MB installation test;
- battery sleep/wake and the next-wake USB detection behavior;
- LEDs, charging indicator, buzzer, and microphone remaining off.

Update `THIRD_PARTY_NOTICES.md` whenever a bundled or downloaded asset family,
version, source, or license changes.

## Definition of done

A change is complete only when the implementation, persistence/migration,
HA/ESPHome protocol, localization, privacy behavior, tests, user-facing
documentation, agent guidance, changelog, and applicable distribution notices
agree. Report the validation commands actually run, any real-device testing
performed, and any remaining technical or distribution limitation.
