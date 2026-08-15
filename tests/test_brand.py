"""Tests for Home Assistant brand assets."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

BRAND_DIRECTORY = (
    Path(__file__).parents[1] / "custom_components" / "guesty_terminal" / "brand"
)


@pytest.mark.parametrize(
    ("filename", "size"),
    [
        ("icon.png", 256),
        ("icon@2x.png", 512),
        ("logo.png", 256),
        ("logo@2x.png", 512),
        ("dark_icon.png", 256),
        ("dark_icon@2x.png", 512),
        ("dark_logo.png", 256),
        ("dark_logo@2x.png", 512),
    ],
)
def test_brand_asset_is_square_png(filename: str, size: int) -> None:
    content = (BRAND_DIRECTORY / filename).read_bytes()
    assert content.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", content[16:24]) == (size, size)


def test_dark_brand_asset_is_theme_optimized() -> None:
    assert (BRAND_DIRECTORY / "dark_icon.png").read_bytes() != (
        BRAND_DIRECTORY / "icon.png"
    ).read_bytes()
