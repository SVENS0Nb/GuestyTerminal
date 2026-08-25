# Third-party notices

## Material Design Icons 7.4.47

GuestyTerminal uses selected weather glyphs from the Material Design Icons
webfont published by Pictogrammers/Templarian:

- Source: <https://github.com/Templarian/MaterialDesign-Webfont/tree/v7.4.47>
- Project license notice: <https://github.com/Templarian/MaterialDesign-Webfont/blob/v7.4.47/LICENSE>
- Font and icon license: Apache License 2.0
- Apache License 2.0: <https://www.apache.org/licenses/LICENSE-2.0>

Only the selected weather glyphs are converted into firmware bitmap data by
ESPHome. The full webfont is not distributed in the firmware image.

## Seeed reTerminal E1001 four-gray example

The UC8179 register waveforms and the corresponding E1001 initialization
sequence are adapted from Seeed's Open Source Hardware repository:

- Source revision: <https://github.com/Seeed-Projects/OSHW-reTerminal-Series-E-D/tree/b3dbc5e6232d8e5945706bf8c0b7b7466dee144a>
- E1001 Gray4 example: <https://github.com/Seeed-Projects/OSHW-reTerminal-Series-E-D/blob/b3dbc5e6232d8e5945706bf8c0b7b7466dee144a/examples/base/GxEPD2_reTerminal_E1001_Gray4/GxEPD2_reTerminal_E1001_Gray4.ino>
- License: MIT
- Local license copy: `esphome/components/guesty_epaper_gray4/LICENSE`

The two-plane transfer retains the reference's explicit `3 - gray` conversion
between the logical `0=black, 3=white` canvas and the UC8179 DTM wire polarity.

## UC8179 controller documentation

GuestyTerminal uses the UC8179 register descriptions published by UltraChip
and hosted by Seeed Studio to interpret hardware control fields that are not
part of the pixel data:

- Datasheet: <https://files.seeedstudio.com/wiki/Other_Display/750-epaper/IC%20Driver%20UC8179.pdf>
- Relevant command: `R25h/LUTBD`, the dedicated 42-byte, seven-group border
  waveform table
- Relevant fields: `R50h.BDV=00`, which selects LUTBD, and `R50h.BDZ`, which
  releases the separate border electrode to high impedance before panel
  power-off
- Relevant field: `R00h.PSR.REG`, which selects panel OTP or register LUTs
- Relevant field: `R52h.BDEND`, whose documented default `10b` holds the border
  at `VCOM_DC` after its refresh LUT completes
- Relevant OTP mapping: bank check codes at `0x0000`/`0x0C00` and the common
  LUTBD ranges `0x001F..0x0048`/`0x0C1F..0x0C48`

In register-LUT mode, the panel-resident 42-byte LUTBD is read twice at runtime
and written back to R25 on the same controller only after both reads match. OTP
mode uses that table internally without a host-side copy. The bytes are not
logged, bundled, committed, or redistributed. No datasheet content is bundled
in this repository.

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
