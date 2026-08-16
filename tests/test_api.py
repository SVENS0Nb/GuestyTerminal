"""Tests for the authenticated Guesty HTTP client."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import pytest
from aiohttp import ClientConnectionError

from custom_components.guesty_terminal.api import (
    API_BASE_URL,
    GuestyAuthenticationError,
    GuestyClient,
    GuestyError,
    GuestyRateLimitError,
)


class FakeResponse:
    """Minimal aiohttp response context manager."""

    def __init__(
        self,
        status: int,
        payload: Any = None,
        *,
        headers: dict[str, str] | None = None,
        text: str = "",
        invalid_json: bool = False,
    ) -> None:
        self.status = status
        self.payload = payload
        self.headers = headers or {}
        self.response_text = text
        self.invalid_json = invalid_json

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self, **_kwargs):
        if self.invalid_json:
            raise json.JSONDecodeError("invalid", "x", 0)
        return self.payload

    async def text(self):
        return self.response_text


class FakeSession:
    """Queue responses and record aiohttp calls."""

    def __init__(self, *, posts=(), requests=()) -> None:
        self.posts = list(posts)
        self.requests = list(requests)
        self.post_calls: list[tuple] = []
        self.request_calls: list[tuple] = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        response = self.posts.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def request(self, method, url, **kwargs):
        self.request_calls.append((method, url, kwargs))
        response = self.requests.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _valid_token(value: str = "cached") -> dict[str, Any]:
    return {
        "access_token": value,
        "expires_at": datetime.now(UTC).timestamp() + 3600,
    }


def test_token_is_reused_and_new_token_is_saved() -> None:
    cached_session = FakeSession()
    cached = GuestyClient(cached_session, "id", "secret", token_data=_valid_token())
    assert asyncio.run(cached._access_token()) == "cached"
    assert cached_session.post_calls == []

    saved: list[dict[str, Any]] = []

    async def save_token(data):
        saved.append(data)

    session = FakeSession(
        posts=[FakeResponse(200, {"access_token": "fresh", "expires_in": "120"})]
    )
    client = GuestyClient(session, " id ", " secret ", token_saver=save_token)
    assert asyncio.run(client._access_token()) == "fresh"
    assert saved[0]["access_token"] == "fresh"
    assert saved[0]["expires_at"] > datetime.now(UTC).timestamp()


def test_corrupt_token_timing_and_expiry_values_fall_back_safely() -> None:
    saved = []

    async def save_token(data):
        saved.append(data)

    client = GuestyClient(
        FakeSession(
            posts=[FakeResponse(200, {"access_token": "fresh", "expires_in": "bad"})]
        ),
        "id",
        "secret",
        token_data={"access_token": "stale", "expires_at": "bad"},
        token_saver=save_token,
    )

    assert asyncio.run(client._access_token()) == "fresh"
    assert saved[0]["expires_at"] > datetime.now(UTC).timestamp() + 86000


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (FakeResponse(401, {}), GuestyAuthenticationError),
        (FakeResponse(500, {}), GuestyError),
        (FakeResponse(200, {}), GuestyAuthenticationError),
        (ClientConnectionError("offline"), GuestyError),
    ],
)
def test_token_errors_are_classified(response, error) -> None:
    client = GuestyClient(FakeSession(posts=[response]), "id", "secret")
    with pytest.raises(error):
        asyncio.run(client._access_token())


def test_response_decoding_falls_back_to_text() -> None:
    client = GuestyClient(FakeSession(), "id", "secret")
    result = asyncio.run(
        client._decode_response(
            FakeResponse(500, invalid_json=True, text="not json" * 100)
        )
    )
    assert result["message"].startswith("not json")
    assert len(result["message"]) == 300


def test_request_retries_auth_once_and_handles_http_errors() -> None:
    session = FakeSession(
        posts=[FakeResponse(200, {"access_token": "new"})],
        requests=[FakeResponse(401, {}), FakeResponse(200, {"ok": True})],
    )
    client = GuestyClient(session, "id", "secret", token_data=_valid_token("old"))
    assert asyncio.run(client._request("GET", "/test")) == {"ok": True}
    assert session.request_calls[0][2]["headers"]["Authorization"] == "Bearer old"
    assert session.request_calls[1][2]["headers"]["Authorization"] == "Bearer new"

    for response, error in (
        (FakeResponse(403, {}), GuestyAuthenticationError),
        (FakeResponse(429, {}, headers={"Retry-After": "17"}), GuestyRateLimitError),
        (FakeResponse(500, {"message": "broken"}), GuestyError),
        (ClientConnectionError("offline"), GuestyError),
    ):
        failing = GuestyClient(
            FakeSession(requests=[response]),
            "id",
            "secret",
            token_data=_valid_token(),
        )
        with pytest.raises(error) as caught:
            asyncio.run(failing._request("GET", "/failure", retry_auth=False))
        if isinstance(caught.value, GuestyRateLimitError):
            assert caught.value.retry_after == 17


@pytest.mark.parametrize(
    ("header", "expected"),
    [("invalid", 60), ("1.2", 2), ("-5", 60)],
)
def test_rate_limit_retry_after_is_parsed_defensively(header, expected) -> None:
    client = GuestyClient(
        FakeSession(requests=[FakeResponse(429, {}, headers={"Retry-After": header})]),
        "id",
        "secret",
        token_data=_valid_token(),
    )

    with pytest.raises(GuestyRateLimitError) as error:
        asyncio.run(client._request("GET", "/limited"))
    assert error.value.retry_after == expected


def test_collection_endpoints_filter_and_paginate_results() -> None:
    first_page = [{"_id": str(index)} for index in range(100)]
    session = FakeSession(
        requests=[
            FakeResponse(200, {"results": first_page}),
            FakeResponse(200, {"results": [{"_id": "last"}, "ignored"]}),
            FakeResponse(
                200,
                {"results": first_page, "pagination": {"hasMore": True}},
            ),
            FakeResponse(
                200,
                {
                    "results": [{"reservationId": "reservation"}, None],
                    "pagination": {"hasMore": False},
                },
            ),
        ]
    )
    client = GuestyClient(session, "id", "secret", token_data=_valid_token())

    listings = asyncio.run(client.async_get_listings())
    reservations = asyncio.run(client.async_get_reservations(["listing-1"]))

    assert len(listings) == 101
    assert len(reservations) == 101
    assert session.request_calls[1][2]["params"]["skip"] == 100
    reservation_params = session.request_calls[2][2]["params"]
    assert session.request_calls[2][1] == f"{API_BASE_URL}/reservations-v3/search"
    assert reservation_params["filter[listingId]"] == "listing-1"
    assert reservation_params["filter[status]"] == "confirmed"
    assert "balanceDue" not in reservation_params


def test_collection_pagination_rejects_repeated_and_invalid_pages() -> None:
    repeated = [{"_id": str(index)} for index in range(100)]
    client = GuestyClient(
        FakeSession(
            requests=[
                FakeResponse(200, {"results": repeated}),
                FakeResponse(200, {"results": repeated}),
            ]
        ),
        "id",
        "secret",
        token_data=_valid_token(),
    )
    with pytest.raises(GuestyError, match="repeated"):
        asyncio.run(client.async_get_listings())

    invalid = GuestyClient(
        FakeSession(requests=[FakeResponse(200, {"results": {"bad": "shape"}})]),
        "id",
        "secret",
        token_data=_valid_token(),
    )
    with pytest.raises(GuestyError, match="invalid reservation"):
        asyncio.run(invalid.async_get_reservations(["listing-1"]))


def test_single_resource_endpoints_and_empty_reservation_request() -> None:
    session = FakeSession(
        requests=[
            FakeResponse(200, {"_id": "listing-1"}),
            FakeResponse(200, []),
            FakeResponse(200, {"customFields": []}),
            FakeResponse(200, [{"name": "keycode"}]),
            FakeResponse(200, {"_id": "guest-1", "firstName": "Anna"}),
            FakeResponse(200, {"id": "account-1"}),
        ]
    )
    client = GuestyClient(session, "id", "secret", token_data=_valid_token())

    assert asyncio.run(client.async_get_reservations([])) == []
    assert asyncio.run(client.async_get_listing("listing-1"))["_id"] == "listing-1"
    assert asyncio.run(client.async_get_listing("missing")) == {}
    assert asyncio.run(client.async_get_reservation_custom_fields("res-1")) == {
        "customFields": []
    }
    assert asyncio.run(client.async_get_account_custom_fields("account-1")) == [
        {"name": "keycode"}
    ]
    assert asyncio.run(client.async_get_guest("guest-1"))["firstName"] == "Anna"
    assert asyncio.run(client.async_get_current_account())["id"] == "account-1"
    assert session.request_calls[0][1] == f"{API_BASE_URL}/listings/listing-1"


def test_next_reservation_query_returns_only_the_first_valid_result() -> None:
    session = FakeSession(
        requests=[
            FakeResponse(
                200,
                {
                    "results": [
                        {"reservationId": "next", "status": "confirmed"},
                        {"reservationId": "later", "status": "confirmed"},
                    ]
                },
            ),
            FakeResponse(200, {"results": []}),
        ]
    )
    client = GuestyClient(session, "id", "secret", token_data=_valid_token())

    assert (
        asyncio.run(client.async_get_next_reservation("listing-1"))["reservationId"]
        == "next"
    )
    assert asyncio.run(client.async_get_next_reservation("listing-1")) == {}

    method, url, kwargs = session.request_calls[0]
    assert method == "GET"
    assert url == f"{API_BASE_URL}/reservations-v3/search"
    params = kwargs["params"]
    assert params["filter[listingId]"] == "listing-1"
    assert params["filter[status]"] == "confirmed"
    assert params["sort"] == "checkIn"
    assert params["limit"] == 1
    assert params["skip"] == 0
    assert "filter[checkIn][gte]" in params
