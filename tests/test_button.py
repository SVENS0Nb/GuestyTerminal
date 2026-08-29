"""Tests for GuestyTerminal fleet operation buttons."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.guesty_terminal import button
from custom_components.guesty_terminal.firmware_update import BulkFirmwareUpdateResult


def test_button_platform_adds_one_central_firmware_button() -> None:
    added = []

    def add_entities(entities):
        added.extend(entities)

    entry = SimpleNamespace(entry_id="entry-1")
    asyncio.run(button.async_setup_entry(None, entry, add_entities))

    assert len(added) == 1
    entity = added[0]
    assert entity.unique_id == "guesty_terminal_entry-1_update_all_firmware"
    assert entity.translation_key == "update_all_firmware"
    assert entity.extra_state_attributes == {"target_firmware_version": "0.3.54"}


def test_firmware_button_queues_all_and_reports_non_sensitive_counts(
    monkeypatch,
) -> None:
    entity = button.GuestyTerminalFirmwareUpdateButton("entry-1")
    entity.hass = SimpleNamespace()
    writes = []
    monkeypatch.setattr(entity, "async_write_ha_state", lambda: writes.append(True))

    async def update_all(hass):
        assert hass is entity.hass
        return BulkFirmwareUpdateResult(3, 2, 3)

    monkeypatch.setattr(button, "async_update_all_managed_firmware", update_all)
    asyncio.run(entity.async_press())

    assert entity.extra_state_attributes == {
        "target_firmware_version": "0.3.54",
        "managed_displays": 3,
        "updated_configurations": 2,
        "queued_jobs": 3,
    }
    assert writes == [True]


def test_firmware_button_rejects_parallel_presses(monkeypatch) -> None:
    entity = button.GuestyTerminalFirmwareUpdateButton("entry-1")
    entity.hass = SimpleNamespace()
    monkeypatch.setattr(entity, "async_write_ha_state", lambda: None)
    started = asyncio.Event()
    finish = asyncio.Event()

    async def update_all(_hass):
        started.set()
        await finish.wait()
        return BulkFirmwareUpdateResult(1, 1, 1)

    monkeypatch.setattr(button, "async_update_all_managed_firmware", update_all)

    async def run_test():
        first = asyncio.create_task(entity.async_press())
        await started.wait()
        with pytest.raises(HomeAssistantError) as error:
            await entity.async_press()
        assert error.value.translation_key == "firmware_update_in_progress"
        finish.set()
        await first

    asyncio.run(run_test())
