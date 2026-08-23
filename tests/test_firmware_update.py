"""Tests for ESPHome Device Builder fleet firmware updates."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import aiohttp
import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.guesty_terminal import firmware_update
from custom_components.guesty_terminal.const import DATA_FIRMWARE_UPDATE_LOCK, DOMAIN
from custom_components.guesty_terminal.firmware import (
    FirmwareOptions,
    render_firmware_config,
)


class FakeWebSocket:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def receive_json(self):
        return self.responses.pop(0)

    async def send_json(self, data):
        self.sent.append(data)


class FakeSession:
    def __init__(self, websocket=None, failure=None) -> None:
        self.websocket = websocket
        self.failure = failure
        self.urls = []

    def ws_connect(self, url):
        self.urls.append(url)
        if self.failure:
            raise self.failure
        return self.websocket


class FakeHass:
    def __init__(self, config_root) -> None:
        self.config = SimpleNamespace(path=lambda name: str(config_root / name))
        self.data = {}

    async def async_add_executor_job(self, target, *args):
        return target(*args)


def _config(device_name: str) -> str:
    return render_firmware_config(
        FirmwareOptions(device_name=device_name, friendly_name=device_name)
    )


def _translation_key(error: pytest.ExceptionInfo[HomeAssistantError]) -> str:
    return error.value.translation_key


def test_queue_device_builder_bulk_update_and_ignore_other_messages() -> None:
    websocket = FakeWebSocket(
        [
            {"requires_auth": False},
            {"message_id": "other", "result": []},
            {
                "message_id": "placeholder",
                "result": [{"job_id": "one"}, {"job_id": "two"}],
            },
        ]
    )
    session = FakeSession(websocket)

    original_send = websocket.send_json

    async def send_and_retarget(data):
        websocket.responses[-1]["message_id"] = data["message_id"]
        await original_send(data)

    websocket.send_json = send_and_retarget
    queued = asyncio.run(
        firmware_update.async_queue_device_builder_updates(
            session, "http://device-builder:6052/", ["one.yaml", "two.yaml"]
        )
    )

    assert queued == 2
    assert session.urls == ["http://device-builder:6052/ws"]
    assert websocket.sent[0]["command"] == "firmware/install_bulk"
    assert websocket.sent[0]["args"] == {
        "configurations": ["one.yaml", "two.yaml"],
        "port": "OTA",
    }


@pytest.mark.parametrize(
    ("responses", "expected_key"),
    [
        ([{"requires_auth": True}], "firmware_builder_auth_required"),
        (
            [
                {"requires_auth": False},
                {"message_id": "placeholder", "error_code": "unknown_command"},
            ],
            "firmware_builder_too_old",
        ),
        (
            [
                {"requires_auth": False},
                {"message_id": "placeholder", "error_code": "internal_error"},
            ],
            "firmware_queue_failed",
        ),
        (
            [
                {"requires_auth": False},
                {"message_id": "placeholder", "result": []},
            ],
            "firmware_builder_invalid_response",
        ),
    ],
)
def test_queue_device_builder_translates_protocol_errors(
    responses, expected_key
) -> None:
    websocket = FakeWebSocket(responses)

    async def retarget(data):
        if len(websocket.responses) > 1 or (
            websocket.responses and "message_id" in websocket.responses[-1]
        ):
            websocket.responses[-1]["message_id"] = data["message_id"]
        websocket.sent.append(data)

    websocket.send_json = retarget
    with pytest.raises(HomeAssistantError) as error:
        asyncio.run(
            firmware_update.async_queue_device_builder_updates(
                FakeSession(websocket), "http://builder", ["display.yaml"]
            )
        )
    assert _translation_key(error) == expected_key


def test_queue_device_builder_translates_connection_errors() -> None:
    with pytest.raises(HomeAssistantError) as error:
        asyncio.run(
            firmware_update.async_queue_device_builder_updates(
                FakeSession(failure=aiohttp.ClientError("offline")),
                "http://builder",
                ["display.yaml"],
            )
        )
    assert _translation_key(error) == "firmware_builder_unavailable"


def test_update_all_managed_firmware_prepares_files_and_queues_jobs(
    tmp_path, monkeypatch
) -> None:
    esphome_dir = tmp_path / "esphome"
    esphome_dir.mkdir()
    (esphome_dir / "one.yaml").write_text(
        _config("display-one").replace("0.3.28", "0.3.12"), encoding="utf-8"
    )
    (esphome_dir / "two.yaml").write_text(_config("display-two"), encoding="utf-8")
    (esphome_dir / "one.yaml").chmod(0o600)
    (esphome_dir / "two.yaml").chmod(0o600)
    hass = FakeHass(tmp_path)
    queued = []

    monkeypatch.setattr(
        firmware_update,
        "_get_esphome_dashboard",
        lambda _hass: SimpleNamespace(url="http://builder:6052"),
    )
    monkeypatch.setattr(
        firmware_update, "async_get_clientsession", lambda _hass: "session"
    )

    async def queue(session, url, configurations):
        queued.append((session, url, configurations))
        return len(configurations)

    monkeypatch.setattr(firmware_update, "async_queue_device_builder_updates", queue)

    result = asyncio.run(firmware_update.async_update_all_managed_firmware(hass))

    assert result.managed_configurations == 2
    assert result.updated_configurations == 1
    assert result.queued_jobs == 2
    assert result.firmware_version == "0.3.28"
    assert queued == [("session", "http://builder:6052", ["one.yaml", "two.yaml"])]
    assert "0.3.28" in (esphome_dir / "one.yaml").read_text(encoding="utf-8")


def test_update_all_managed_firmware_reports_missing_config_or_builder(
    tmp_path, monkeypatch
) -> None:
    hass = FakeHass(tmp_path)
    with pytest.raises(HomeAssistantError) as error:
        asyncio.run(firmware_update.async_update_all_managed_firmware(hass))
    assert _translation_key(error) == "firmware_no_managed_configs"

    esphome_dir = tmp_path / "esphome"
    esphome_dir.mkdir()
    (esphome_dir / "display.yaml").write_text(_config("display-one"), encoding="utf-8")
    monkeypatch.setattr(firmware_update, "_get_esphome_dashboard", lambda _hass: None)
    with pytest.raises(HomeAssistantError) as error:
        asyncio.run(firmware_update.async_update_all_managed_firmware(hass))
    assert _translation_key(error) == "firmware_builder_unavailable"


def test_update_all_managed_firmware_rejects_cross_entry_concurrency(tmp_path) -> None:
    hass = FakeHass(tmp_path)

    async def exercise():
        lock = asyncio.Lock()
        await lock.acquire()
        hass.data[DOMAIN] = {DATA_FIRMWARE_UPDATE_LOCK: lock}
        with pytest.raises(HomeAssistantError) as error:
            await firmware_update.async_update_all_managed_firmware(hass)
        assert _translation_key(error) == "firmware_update_in_progress"

    asyncio.run(exercise())
