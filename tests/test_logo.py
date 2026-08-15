"""Tests for global E-paper logo processing."""

from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from custom_components.guesty_terminal.logo import (
    LOGO_DATA_BYTES,
    LOGO_DATA_HEX_LENGTH,
    LOGO_HEIGHT,
    LOGO_WIDTH,
    LogoError,
    encode_logo,
    logo_fingerprint,
    valid_logo_data,
)


def _write_logo(path: Path) -> None:
    image = Image.new("RGBA", (400, 160), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((20, 20, 140, 140), fill=(0, 0, 0, 255))
    draw.rectangle((170, 50, 380, 110), fill=(90, 90, 90, 255))
    image.save(path)


def _ink_bounds(encoded: str) -> tuple[int, int] | None:
    packed = bytes.fromhex(encoded)
    columns: list[int] = []
    for index in range(LOGO_WIDTH * LOGO_HEIGHT):
        byte_index = index // 4
        shift = (3 - (index % 4)) * 2
        if ((packed[byte_index] >> shift) & 0x03) < 3:
            columns.append(index % LOGO_WIDTH)
    return (min(columns), max(columns)) if columns else None


def test_logo_is_cropped_scaled_and_packed_into_four_gray_data(tmp_path) -> None:
    path = tmp_path / "logo.png"
    _write_logo(path)

    encoded = encode_logo(path)

    assert len(encoded) == LOGO_DATA_HEX_LENGTH
    assert len(bytes.fromhex(encoded)) == LOGO_DATA_BYTES
    assert encoded != "ff" * LOGO_DATA_BYTES
    assert valid_logo_data(encoded.upper()) == encoded
    assert _ink_bounds(encoded)[1] == LOGO_WIDTH - 1
    assert len(logo_fingerprint(encoded)) == 16
    assert logo_fingerprint(encoded) == logo_fingerprint(encoded)


def test_existing_centered_logo_is_right_aligned_without_reupload() -> None:
    legacy = bytearray([0xFF] * LOGO_DATA_BYTES)
    pixel = 20
    byte_index = pixel // 4
    shift = (3 - (pixel % 4)) * 2
    legacy[byte_index] &= ~(0x03 << shift)

    aligned = valid_logo_data(legacy.hex())

    assert _ink_bounds(aligned) == (LOGO_WIDTH - 1, LOGO_WIDTH - 1)


def test_logo_rejects_blank_unreadable_and_invalid_stored_data(tmp_path) -> None:
    blank = tmp_path / "blank.png"
    Image.new("RGB", (100, 50), "white").save(blank)
    with pytest.raises(LogoError, match="visible artwork"):
        encode_logo(blank)

    unreadable = tmp_path / "broken.png"
    unreadable.write_text("not an image", encoding="utf-8")
    with pytest.raises(LogoError, match="readable PNG or JPEG"):
        encode_logo(unreadable)

    assert valid_logo_data(None) == ""
    assert valid_logo_data("00") == ""
    assert valid_logo_data("z" * LOGO_DATA_HEX_LENGTH) == ""
    assert logo_fingerprint("") == ""
