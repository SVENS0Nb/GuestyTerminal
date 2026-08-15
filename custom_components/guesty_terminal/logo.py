"""Prepare one global logo for all GuestyTerminal displays."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

LOGO_WIDTH = 144
LOGO_HEIGHT = 48
LOGO_PIXELS_PER_BYTE = 4
LOGO_DATA_BYTES = LOGO_WIDTH * LOGO_HEIGHT // LOGO_PIXELS_PER_BYTE
LOGO_DATA_HEX_LENGTH = LOGO_DATA_BYTES * 2
MAX_LOGO_FILE_BYTES = 5 * 1024 * 1024
MAX_LOGO_PIXELS = 20_000_000


class LogoError(ValueError):
    """Raised when an uploaded logo cannot be used."""


def _panel_level(gray: int) -> int:
    """Quantize an 8-bit grayscale pixel to black, dark, light, or white."""
    if gray < 64:
        return 0
    if gray < 160:
        return 1
    if gray < 232:
        return 2
    return 3


def _right_align_packed(data: bytes) -> bytes:
    """Move visible pixels to the right edge of the fixed logo canvas."""
    rightmost_ink = -1
    for index in range(LOGO_WIDTH * LOGO_HEIGHT):
        byte_index = index // LOGO_PIXELS_PER_BYTE
        shift = (3 - (index % LOGO_PIXELS_PER_BYTE)) * 2
        if ((data[byte_index] >> shift) & 0x03) < 3:
            rightmost_ink = max(rightmost_ink, index % LOGO_WIDTH)

    if rightmost_ink < 0 or rightmost_ink == LOGO_WIDTH - 1:
        return data

    offset = LOGO_WIDTH - 1 - rightmost_ink
    aligned = bytearray([0xFF] * LOGO_DATA_BYTES)
    for index in range(LOGO_WIDTH * LOGO_HEIGHT):
        source_byte = index // LOGO_PIXELS_PER_BYTE
        source_shift = (3 - (index % LOGO_PIXELS_PER_BYTE)) * 2
        level = (data[source_byte] >> source_shift) & 0x03
        if level == 3:
            continue
        target = index + offset
        target_byte = target // LOGO_PIXELS_PER_BYTE
        target_shift = (3 - (target % LOGO_PIXELS_PER_BYTE)) * 2
        aligned[target_byte] = (aligned[target_byte] & ~(0x03 << target_shift)) | (
            level << target_shift
        )
    return bytes(aligned)


def encode_logo(path: Path) -> str:
    """Return a fixed-size, four-gray, two-bits-per-pixel logo as hex."""
    try:
        if path.stat().st_size > MAX_LOGO_FILE_BYTES:
            raise LogoError("Logo file is too large")

        with Image.open(path) as source:
            width, height = source.size
            if width <= 0 or height <= 0 or width * height > MAX_LOGO_PIXELS:
                raise LogoError("Logo dimensions are invalid")
            rgba = source.convert("RGBA")
    except (OSError, UnidentifiedImageError) as err:
        raise LogoError("Logo is not a readable PNG or JPEG image") from err
    except Image.DecompressionBombError as err:
        raise LogoError("Logo dimensions are too large") from err

    white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
    white.alpha_composite(rgba)
    grayscale = ImageOps.grayscale(white)
    ink = ImageOps.invert(grayscale)
    visible_ink = ink.point(lambda value: 255 if value >= 8 else 0)
    bounding_box = visible_ink.getbbox()
    if bounding_box is None:
        raise LogoError("Logo does not contain visible artwork")

    cropped = grayscale.crop(bounding_box)
    cropped.thumbnail((LOGO_WIDTH, LOGO_HEIGHT), Image.Resampling.LANCZOS)
    canvas = Image.new("L", (LOGO_WIDTH, LOGO_HEIGHT), 255)
    canvas.paste(
        cropped,
        (LOGO_WIDTH - cropped.width, (LOGO_HEIGHT - cropped.height) // 2),
    )

    packed = bytearray(LOGO_DATA_BYTES)
    for index, gray in enumerate(canvas.getdata()):
        level = _panel_level(gray)
        byte_index = index // LOGO_PIXELS_PER_BYTE
        shift = (3 - (index % LOGO_PIXELS_PER_BYTE)) * 2
        packed[byte_index] |= level << shift
    return packed.hex()


def logo_fingerprint(logo_data: str) -> str:
    """Return a short opaque identifier for duplicate refresh suppression."""
    if not logo_data:
        return ""
    return hashlib.sha256(logo_data.encode("ascii")).hexdigest()[:16]


def valid_logo_data(value: object) -> str:
    """Return valid stored logo data or an empty string."""
    if not isinstance(value, str) or len(value) != LOGO_DATA_HEX_LENGTH:
        return ""
    try:
        data = bytes.fromhex(value)
    except ValueError:
        return ""
    return _right_align_packed(data).hex()
