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

## Seeed_GFX UC8179 support

The panel-OTP detection, OTP grayscale setup, and differential partial-refresh
sequence are adapted from Seeed_GFX's UC8179 implementation:

- Source revision: <https://github.com/Seeed-Studio/Seeed_GFX/tree/a2de1abca0597c202193f22d01e9fa35d1ff613b>
- UC8179 definitions: <https://github.com/Seeed-Studio/Seeed_GFX/blob/a2de1abca0597c202193f22d01e9fa35d1ff613b/TFT_Drivers/UC8179_Defines.h>
- OTP implementation: <https://github.com/Seeed-Studio/Seeed_GFX/blob/a2de1abca0597c202193f22d01e9fa35d1ff613b/TFT_eSPI.cpp>
- Licenses: MIT/BSD and FreeBSD as documented upstream
- Local license copy:
  `esphome/components/guesty_epaper_gray4/SEEED_GFX_LICENSE.txt`

The current GuestyTerminal driver does not contain waveform tables or driver
sequences from the previously evaluated unlicensed reference implementation.
