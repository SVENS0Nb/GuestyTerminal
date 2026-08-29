# Third-party notices

## QR Code Generator Library 1.7.0

ESPHome's `qr_code` component uses Wouter van der Wal's ESPHome packaging of
Project Nayuki's QR Code Generator C library. GuestyTerminal pins the upstream
source commit directly so firmware compilation does not depend on the
availability of the PlatformIO registry:

- Source: <https://github.com/wjtje/QR-Code-generator-esphome>
- Fixed revision: `5f7449c095cf975bb14a34e1813b191205f78ccb`
- PlatformIO package: `wjtje/qr-code-generator-library` version `1.7.0`
- License: MIT

The fixed revision's C source and header are content-identical to the
PlatformIO 1.7.0 package after normalizing line endings. They are downloaded
during the ESPHome build and are not bundled in this repository.

## Material Design Icons 7.4.47

GuestyTerminal uses selected weather and battery/charging glyphs from the
Material Design Icons webfont published by Pictogrammers/Templarian:

- Source: <https://github.com/Templarian/MaterialDesign-Webfont/tree/v7.4.47>
- Project license notice: <https://github.com/Templarian/MaterialDesign-Webfont/blob/v7.4.47/LICENSE>
- Font and icon license: Apache License 2.0
- Apache License 2.0: <https://www.apache.org/licenses/LICENSE-2.0>

Only the selected weather, battery-level, and battery-charging glyphs are
converted into firmware bitmap data by ESPHome. The full webfont is not
distributed in the firmware image.

## Seeed reTerminal E1001 four-gray example

The UC8179 register waveforms and the corresponding E1001 initialization
sequence are adapted from Seeed's Open Source Hardware repository:

- Source revision: <https://github.com/Seeed-Projects/OSHW-reTerminal-Series-E-D/tree/b3dbc5e6232d8e5945706bf8c0b7b7466dee144a>
- E1001 Gray4 example: <https://github.com/Seeed-Projects/OSHW-reTerminal-Series-E-D/blob/b3dbc5e6232d8e5945706bf8c0b7b7466dee144a/examples/base/GxEPD2_reTerminal_E1001_Gray4/GxEPD2_reTerminal_E1001_Gray4.ino>
- License: MIT
- Local license copy: `esphome/components/guesty_epaper_gray4/LICENSE`

The two-plane transfer retains the reference's explicit `3 - gray` conversion
between the logical `0=black, 3=white` canvas and the UC8179 DTM wire polarity.
The `standard` profile preserves all five referenced register tables
byte-for-byte. The experimental `lighter` table is a one-byte derivative of
Seeed's MIT-licensed `LUTKW`: its phase-7 selector changes from `0xA8` to
`0x28`, the value used in the same position by Seeed's `LUTWW`; every duration
and all other table bytes remain unchanged. This introduces no additional
source or license.

## UC8179 controller documentation

GuestyTerminal uses the UC8179 register descriptions published by UltraChip
and hosted by Seeed Studio to interpret hardware control fields that are not
part of the pixel data:

- Datasheet: <https://files.seeedstudio.com/wiki/Other_Display/750-epaper/IC%20Driver%20UC8179.pdf>
- Relevant command: `R25h/LUTBD`, the dedicated 42-byte, seven-group border
  waveform table; GuestyTerminal documents it but does not write it
- Relevant fields: `R50h.BDZ=1` leaves the border electrode high-impedance;
  during the explicit monochrome recovery pass, KW mode with `DDX=00` and
  `BDV=01` selects the panel's black-to-white OTP waveform for that separate
  electrode
- Relevant field: `R00h.PSR.REG`, which selects panel OTP or register LUTs
- Relevant commands: `R21h` through `R24h`, whose seven groups encode a
  selector, four frame counts and a repeat count for the WW, KW, WK and KK
  transitions
- Relevant power-off behavior: `R02h` releases Source, Gate, Border, and VCOM
  to floating, so GuestyTerminal does not add a late `R50h` override
- Relevant OTP mapping: bank check codes at `0x0000`/`0x0C00` and the common
  LUTBD ranges `0x001F..0x0048`/`0x0C1F..0x0C48`

GuestyTerminal reads only the selected banks' check codes and grayscale support
markers, twice, for its retained auto-mode decision. It does not retain or
replay the panel-resident LUTBD and never writes R25. Raw OTP waveform bytes are
not logged, bundled, committed, or redistributed. Normal full refreshes leave
the border high-impedance. The optional recovery independently programs only
the documented monochrome KW mode, geometry, timing and power registers,
transfers the current framebuffer's monochrome DTM2 projection, and then
restores the selected four-gray pixel waveform. No datasheet content is
bundled in this repository.

## Historical ESPHome `7.50inv2` behavior comparison

GuestyTerminal used ESPHome's built-in Waveshare `7.50inv2` model through
version 0.3.2. Its fixed 2026.7.4 implementation was inspected only to identify
the controller behavior that had previously produced a border-free monochrome
image:

- Source: <https://github.com/esphome/esphome/blob/2026.7.4/esphome/components/waveshare_epaper/waveshare_epaper.cpp#L3935>
- ESPHome license: <https://github.com/esphome/esphome/blob/2026.7.4/LICENSE>
- Fixed version: `2026.7.4`
- License of the inspected C++ implementation: GNU GPL v3

No C++ source, comments, class structure, or waveform data from that GPL
implementation is copied into GuestyTerminal's MIT-licensed external
component. The new optional recovery sequence is an independent implementation
of the corresponding UC8179 register functions from the official controller
documentation above. This comparison does not change the firmware's active
driver: the GuestyTerminal four-gray component remains responsible for the
framebuffer, final refresh, partial updates, timing, diagnostics and power
handling.

## Seeed_GFX UC8179 support

The bidirectional OTP read pattern, bus-teardown concept, panel-OTP detection,
OTP grayscale setup, and differential partial-refresh sequence are adapted
from Seeed_GFX's UC8179 implementation. GuestyTerminal's explicit ESP32-S3 SPI2
host reinitialization restores the E1001 bus with its original ESPHome pins,
MISO, DMA, flags, and transfer size after that read:

- Source revision: <https://github.com/Seeed-Studio/Seeed_GFX/tree/a2de1abca0597c202193f22d01e9fa35d1ff613b>
- UC8179 definitions: <https://github.com/Seeed-Studio/Seeed_GFX/blob/a2de1abca0597c202193f22d01e9fa35d1ff613b/TFT_Drivers/UC8179_Defines.h>
- OTP implementation: <https://github.com/Seeed-Studio/Seeed_GFX/blob/a2de1abca0597c202193f22d01e9fa35d1ff613b/TFT_eSPI.cpp>
- Licenses: MIT/BSD and FreeBSD as documented upstream
- Local license copy:
  `esphome/components/guesty_epaper_gray4/SEEED_GFX_LICENSE.txt`

The current GuestyTerminal driver does not contain waveform tables or driver
sequences from the previously evaluated unlicensed reference implementation.
