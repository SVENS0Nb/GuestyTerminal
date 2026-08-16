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
  four-level/partial-refresh panel driver.
- `esphome/guestyterminal-display-1.yaml`: local reference configuration.
- `tests/`: unit and contract tests for both Python behavior and important
  firmware/YAML invariants.
- `.github/workflows/tests.yml`: authoritative CI commands.

Generated ESPHome build files under `esphome/.esphome/`, Python caches, coverage
artifacts, and real `secrets.yaml` files are not source. Do not inspect or edit
them as if they were part of the implementation.

## End-to-end data flow

1. `GuestyClient` obtains a Client Credentials token and fetches listings and
   confirmed reservations from Guesty's API.
2. `GuestyTerminalCoordinator` resolves full listing details, guest names, the
   `keycode` custom field, and optional Home Assistant weather data.
3. `build_display_payload()` selects the visible reservation and produces one
   bounded `DisplayPayload` per configured ESPHome endpoint.
4. `GuestyTerminalRuntime` reads the endpoint sensor's action name and sends
   only fields supported by that action version.
5. The current ESPHome `...update_display_v9` action updates RAM state, compares
   opaque fingerprints, redraws only when necessary, and returns to deep sleep
   on battery.

When changing a field or behavior, follow this flow in both directions. A field
that exists only on one side of the Home Assistant/ESPHome boundary is an
incomplete change.

## Non-negotiable product behavior

### Reservation selection and time semantics

- A reservation becomes visible one hour before check-in and is removed 30
  minutes after checkout by default. Both values are configurable per display.
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
  direct `keycode`/`keyCode`, nested populated custom fields, and field-ID
  resolution through account custom-field definitions.

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
  added to `restore_value` globals or log messages.
- Home Assistant diagnostics may report flags, listing names, entity IDs,
  weather configuration, and lease timestamps, but never guest names, codes,
  SSIDs, or passwords. The device's displayed-booking text sensor is the one
  intentional remote confirmation and must not include access credentials.
- Keep the renewable display lease (currently 15 minutes). Lease renewal must
  not itself change the visible-content fingerprint or force an E-paper flash.
  Expired cached payloads must be replaced with an idle payload before any
  normal or forced redraw.

### E-paper refresh behavior

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
- `guesty_render_revision` invalidates otherwise-identical images after a
  rendering or driver change. When a visible rendering change requires one
  repaint, increment the expected value and the stored-success value together,
  and update their tests.
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
- The default battery cycle is 30 minutes with a maximum awake window of 90
  seconds. After Home Assistant delivers a payload, the device may sleep
  earlier.
- A device already in deep sleep is expected to notice newly connected USB
  power at its next scheduled wake and then stay online. Do not reintroduce a
  separate periodic USB wake/probe mechanism unless the product requirement is
  explicitly changed.
- If a battery wake receives no payload while sensitive content may still be on
  screen, clear to the localized idle screen before sleeping. On permanent
  power, enforce lease expiry continuously because no next wake is guaranteed.
- Keep the status/charging LEDs, buzzer, and microphone power disabled. The
  charger STAT output is disabled over its dedicated I2C bus; GPIO-only changes
  are insufficient.
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

- The endpoint entity is discovered by original name `GuestyTerminal Endpoint`
  or the `_guesty_terminal_endpoint` suffix. Its state is the exact ESPHome
  action name, not a status value.
- The runtime accepts legacy action suffixes through v8 and sends fields only
  when that version supports them. Preserve old action handling unless a
  deliberate compatibility break is documented and released.
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
  is pending, so stale RAM cannot win the race.
- The central integration button updates every GuestyTerminal-managed YAML to
  `FIRMWARE_VERSION` and queues OTA jobs through ESPHome Device Builder. It must
  ignore user-owned YAML and report only non-sensitive counts/status.
- `hacs.json` declares Home Assistant 2025.12 as the minimum; the test suite is
  pinned to Home Assistant 2026.2.3. Do not lower compatibility accidentally.

## Change-impact checklist

Use the smallest applicable row, then inspect all named layers:

| Change | Required impact review |
| --- | --- |
| Guesty API shape or endpoint | `api.py`, coordinator normalization/cache behavior, API and coordinator tests |
| Booking timing/status/timezone | `models.py`, coordinator query window, privacy lease, model/coordinator/runtime tests |
| New per-display option or text | constants, localization presets, `MappingOptions` load/save, config flow, translations, payload, action, renderer, tests |
| New visible payload field | fingerprints, versioned ESPHome action, runtime version negotiation, globals/rendering, tests |
| Layout/font/logo/weather rendering | package YAML, `content_id`, render revision, partial-window containment, firmware tests, hardware check |
| Panel/LUT/partial-refresh code | component Python schema, C++/header, package geometry, compile, hardware full/partial/deep-sleep tests |
| Power/deep-sleep behavior | boot/action/interval paths, privacy fallback, external-power detection, README, firmware tests, battery and USB hardware checks |
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
pytest
python3 -m compileall custom_components/guesty_terminal
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
- State clearly when hardware behavior was compiled but not tested on a real
  E1001.

## Release and versioning rules

Do not commit, push, tag, publish a release, or queue real OTA jobs unless the
user explicitly requests that external action.

For a release, use one semantic version consistently in:

- `custom_components/guesty_terminal/manifest.json`
- `custom_components/guesty_terminal/firmware.py` (`FIRMWARE_VERSION`)
- `esphome/guestyterminal-display-1.yaml`
- version-specific tests and the release section in `README.md`

Generated managed YAML contains two GitHub refs and one ESPHome project version.
The updater intentionally requires exactly those three versions to match and
updates them atomically while preserving credentials and permissions. If the
template structure changes, update the parser and its malformed/future-version
tests together.

Firmware generation pins both the package and external component to
`v<FIRMWARE_VERSION>`. That Git tag must contain the referenced files before
users can compile newly generated configurations. Run the complete Python
suite, ESPHome config validation, and preferably a firmware compile before
tagging. Hardware-affecting releases also require checks of:

- full four-gray refresh and legible fonts;
- unchanged-content suppression;
- weather-only partial refresh across reset/deep sleep and fallback after five
  partial updates;
- forced redraw and displayed-booking confirmation;
- battery sleep/wake and the next-wake USB detection behavior;
- LEDs, charging indicator, buzzer, and microphone remaining off.

Update `THIRD_PARTY_NOTICES.md` whenever a bundled or downloaded asset family,
version, source, or license changes.

## Definition of done

A change is complete only when the implementation, persistence/migration,
HA/ESPHome protocol, localization, privacy behavior, tests, and user-facing
documentation affected by that change agree. Report the validation commands
actually run, any real-device testing performed, and any remaining limitation.
