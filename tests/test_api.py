"""Tests for the authenticated Guesty HTTP client."""

from __future__ import annotations

import asyncio
import json
import traceback
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import pytest
from aiohttp import ClientConnectionError

from custom_components.guesty_terminal.api import (
    API_BASE_URL,
    GUESTY_REQUEST_LIMITS,
    GuestyAuthenticationError,
    GuestyClient,
    GuestyConnectionError,
    GuestyError,
    GuestyRateLimitError,
    GuestyRequestError,
    GuestyRequestLimiter,
    GuestyResponseError,
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


class FakeClock:
    """Monotonic clock with a non-blocking asynchronous sleep."""

    def __init__(self) -> None:
        self.current = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.current

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.current += seconds


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


def test_request_limiter_enforces_guesty_windows_without_busy_waiting() -> None:
    assert GUESTY_REQUEST_LIMITS == (
        (15, 1.0),
        (120, 60.0),
        (5000, 3600.0),
    )
    clock = FakeClock()
    limiter = GuestyRequestLimiter(
        limits=((2, 1.0), (3, 10.0)),
        clock=clock,
        sleep=clock.sleep,
    )

    async def acquire_four() -> None:
        for _request in range(4):
            await limiter.acquire()

    asyncio.run(acquire_four())

    assert clock.sleeps == [1.0, 9.0]
    assert clock.current == 10.0


def test_rate_limit_defers_the_next_retry_without_hiding_retry_after() -> None:
    clock = FakeClock()
    limiter = GuestyRequestLimiter(clock=clock, sleep=clock.sleep)
    session = FakeSession(
        requests=[
            FakeResponse(429, {}, headers={"Retry-After": "17"}),
            FakeResponse(200, {"ok": True}),
        ]
    )
    client = GuestyClient(
        session,
        "id",
        "secret",
        token_data=_valid_token(),
        request_limiter=limiter,
    )

    with pytest.raises(GuestyRateLimitError) as error:
        asyncio.run(client._request("GET", "/limited"))
    assert error.value.retry_after == 17

    with pytest.raises(GuestyRateLimitError) as deferred:
        asyncio.run(client._request("GET", "/retry"))
    assert deferred.value.retry_after == 17
    assert clock.sleeps == []

    clock.current += 17
    assert asyncio.run(client._request("GET", "/retry")) == {"ok": True}


def test_rate_limit_slot_is_reserved_after_a_delayed_token_refresh() -> None:
    clock = FakeClock()

    class DelayedTokenResponse(FakeResponse):
        async def __aenter__(self):
            clock.current += 10.0
            return await super().__aenter__()

    limiter = GuestyRequestLimiter(
        limits=((1, 1.0),),
        clock=clock,
        sleep=clock.sleep,
    )
    client = GuestyClient(
        FakeSession(
            posts=[DelayedTokenResponse(200, {"access_token": "fresh"})],
            requests=[FakeResponse(200, {}), FakeResponse(200, {})],
        ),
        "id",
        "secret",
        request_limiter=limiter,
    )

    async def request_twice() -> None:
        await client._request("GET", "/first")
        await client._request("GET", "/second")

    asyncio.run(request_twice())

    assert clock.sleeps == [1.0]
    assert clock.current == 11.0


def test_request_errors_are_typed_and_do_not_expose_response_identifiers() -> None:
    reservation_id = "sensitive-reservation-id"
    server_message = f"Could not load {reservation_id}"
    request_client = GuestyClient(
        FakeSession(requests=[FakeResponse(500, {"message": server_message})]),
        "id",
        "secret",
        token_data=_valid_token(),
    )

    with pytest.raises(GuestyRequestError) as request_error:
        asyncio.run(
            request_client._request(
                "GET", f"/reservations-v3/{reservation_id}/custom-fields"
            )
        )
    assert request_error.value.status_code == 500
    assert request_error.value.retryable is True
    assert reservation_id not in str(request_error.value)

    connection_client = GuestyClient(
        FakeSession(requests=[ClientConnectionError(server_message)]),
        "id",
        "secret",
        token_data=_valid_token(),
    )
    with pytest.raises(GuestyConnectionError) as connection_error:
        asyncio.run(
            connection_client._request(
                "GET", f"/reservations-v3/{reservation_id}/custom-fields"
            )
        )
    assert reservation_id not in str(connection_error.value)
    assert connection_error.value.__cause__ is None
    assert connection_error.value.__context__ is None
    assert reservation_id not in "".join(
        traceback.format_exception(connection_error.value)
    )

    authentication_client = GuestyClient(
        FakeSession(posts=[ClientConnectionError(server_message)]),
        "id",
        "secret",
    )
    with pytest.raises(GuestyConnectionError) as authentication_error:
        asyncio.run(authentication_client._access_token())
    assert authentication_error.value.__cause__ is None
    assert authentication_error.value.__context__ is None
    assert reservation_id not in "".join(
        traceback.format_exception(authentication_error.value)
    )


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


def test_rate_limit_retry_after_accepts_http_date() -> None:
    retry_at = datetime.now(UTC) + timedelta(seconds=120)
    client = GuestyClient(
        FakeSession(
            requests=[
                FakeResponse(
                    429,
                    {},
                    headers={"Retry-After": format_datetime(retry_at, usegmt=True)},
                )
            ]
        ),
        "id",
        "secret",
        token_data=_valid_token(),
    )

    with pytest.raises(GuestyRateLimitError) as error:
        asyncio.run(client._request("GET", "/limited"))
    assert 118 <= error.value.retry_after <= 120


def test_collection_endpoints_filter_and_paginate_results() -> None:
    first_page = [{"_id": str(index)} for index in range(100)]
    session = FakeSession(
        requests=[
            FakeResponse(200, {"results": first_page}),
            FakeResponse(200, {"results": [{"_id": "last"}]}),
            FakeResponse(
                200,
                {"results": first_page, "pagination": {"hasMore": True}},
            ),
            FakeResponse(
                200,
                {
                    "results": [{"reservationId": "reservation"}],
                    "pagination": {"hasMore": False},
                },
            ),
        ]
    )
    client = GuestyClient(session, "id", "secret", token_data=_valid_token())

    listings = asyncio.run(client.async_get_listings())
    as_of = datetime(2030, 5, 6, 23, 59, tzinfo=UTC)
    reservations = asyncio.run(
        client.async_get_reservations(["listing-1"], as_of=as_of)
    )

    assert len(listings) == 101
    assert len(reservations) == 101
    assert session.request_calls[1][2]["params"]["skip"] == 100
    reservation_params = session.request_calls[2][2]["params"]
    assert session.request_calls[2][1] == f"{API_BASE_URL}/reservations-v3/search"
    assert reservation_params["filter[listingId]"] == "listing-1"
    assert reservation_params["filter[status]"] == "confirmed"
    assert reservation_params["filter[checkOut][gte]"] == "2030-05-05"
    assert reservation_params["filter[checkIn][lt]"] == "2030-05-10"
    assert "balanceDue" not in reservation_params


def test_current_search_preserves_the_documented_v3_stay_projection() -> None:
    row = {
        "reservationId": "reservation-v3",
        "status": "confirmed",
        "guestId": "guest-v3",
        "checkIn": "2030-05-06T13:00:00Z",
        "checkOut": "2030-05-08T08:00:00Z",
        "checkInDateLocalized": "2030-05-06",
        "checkOutDateLocalized": "2030-05-08",
        "stay": [
            {
                "listingId": "assigned-unit",
                "parentListingId": "mapped-unit-type",
                "checkInDateLocalized": "2030-05-06",
                "checkOutDateLocalized": "2030-05-08",
            }
        ],
    }
    client = GuestyClient(
        FakeSession(
            requests=[
                FakeResponse(
                    200,
                    {"results": [row], "pagination": {"hasMore": False}},
                )
            ]
        ),
        "id",
        "secret",
        token_data=_valid_token(),
    )

    assert asyncio.run(
        client.async_get_reservations(
            ["mapped-unit-type"],
            as_of=datetime(2030, 5, 6, tzinfo=UTC),
        )
    ) == [row]


def test_account_current_search_omits_the_first_stay_listing_filter() -> None:
    row = {
        "reservationId": "relocated",
        "status": "confirmed",
        "stay": [
            {
                "listingId": "unit-b",
                "checkIn": "2030-05-06T13:00:00Z",
                "checkOut": "2030-05-08T08:00:00Z",
            }
        ],
    }
    session = FakeSession(
        requests=[
            FakeResponse(
                200,
                {"results": [row], "pagination": {"hasMore": False}},
            )
        ]
    )
    client = GuestyClient(session, "id", "secret", token_data=_valid_token())

    assert asyncio.run(
        client.async_get_current_reservations(as_of=datetime(2030, 5, 6, tzinfo=UTC))
    ) == [row]
    params = session.request_calls[0][2]["params"]
    assert "filter[listingId]" not in params
    assert params["filter[status]"] == "confirmed"


def test_reservation_verification_batches_v3_ids_and_preserves_request_order() -> None:
    reservation_ids = [f"reservation-{index}" for index in range(11)]
    first_batch = [
        {
            "_id": reservation_id,
            "status": "confirmed",
            "stay": [
                {
                    "unitId": "assigned-unit",
                    "unitTypeId": "mapped-unit-type",
                    "checkInDateLocalized": "2030-05-06",
                    "checkOutDateLocalized": "2030-05-08",
                }
            ],
        }
        for reservation_id in reversed(reservation_ids[:10])
    ]
    session = FakeSession(
        requests=[
            FakeResponse(200, first_batch),
            # A missing ID is a valid authoritative result, for example after
            # Guesty removes or cancels a formerly known reservation.
            FakeResponse(200, []),
        ]
    )
    client = GuestyClient(session, "id", "secret", token_data=_valid_token())

    verified = asyncio.run(
        client.async_get_reservations_by_ids([*reservation_ids, reservation_ids[0]])
    )

    assert [item["_id"] for item in verified] == reservation_ids[:10]
    assert len(session.request_calls) == 2
    assert session.request_calls[0][1] == f"{API_BASE_URL}/reservations-v3"
    assert session.request_calls[0][2]["params"] == {
        "reservationIds[]": reservation_ids[:10]
    }
    assert session.request_calls[1][2]["params"] == {
        "reservationIds[]": reservation_ids[10:]
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"results": []},
        [{"_id": "known"}, "invalid-row"],
        [{"_id": "unexpected"}],
        [{"status": "confirmed"}],
        [{"_id": "known"}, {"_id": "known", "status": "confirmed"}],
    ],
)
def test_reservation_verification_rejects_inconsistent_v3_data(payload) -> None:
    client = GuestyClient(
        FakeSession(requests=[FakeResponse(200, payload)]),
        "id",
        "secret",
        token_data=_valid_token(),
    )

    with pytest.raises(GuestyResponseError) as error:
        asyncio.run(client.async_get_reservations_by_ids(["known"]))
    assert "known" not in str(error.value)
    assert "unexpected" not in str(error.value)


def test_reservation_verification_handles_empty_and_invalid_requests_locally() -> None:
    session = FakeSession()
    client = GuestyClient(session, "id", "secret", token_data=_valid_token())

    assert asyncio.run(client.async_get_reservations_by_ids([])) == []
    with pytest.raises(ValueError, match="non-empty strings"):
        asyncio.run(client.async_get_reservations_by_ids([""]))
    assert session.request_calls == []


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


def test_current_search_rejects_empty_page_that_claims_more_results() -> None:
    client = GuestyClient(
        FakeSession(
            requests=[
                FakeResponse(
                    200,
                    {"results": [], "pagination": {"hasMore": True}},
                )
            ]
        ),
        "id",
        "secret",
        token_data=_valid_token(),
    )

    with pytest.raises(GuestyResponseError, match="inconsistent reservation"):
        asyncio.run(client.async_get_reservations(["listing-1"]))


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(200, {}),
        FakeResponse(200, {"message": "proxy body"}),
        FakeResponse(200, invalid_json=True, text="proxy body"),
    ],
)
def test_missing_collection_results_are_never_treated_as_empty(response) -> None:
    client = GuestyClient(
        FakeSession(requests=[response]),
        "id",
        "secret",
        token_data=_valid_token(),
    )

    with pytest.raises(GuestyResponseError, match="invalid listing"):
        asyncio.run(client.async_get_listings())


def test_missing_reservation_results_are_never_authoritative_empty_snapshots() -> None:
    current = GuestyClient(
        FakeSession(requests=[FakeResponse(200, {"message": "proxy body"})]),
        "id",
        "secret",
        token_data=_valid_token(),
    )
    upcoming = GuestyClient(
        FakeSession(requests=[FakeResponse(200, {})]),
        "id",
        "secret",
        token_data=_valid_token(),
    )

    with pytest.raises(GuestyResponseError, match="invalid reservation"):
        asyncio.run(current.async_get_reservations(["listing-1"]))
    with pytest.raises(GuestyResponseError, match="invalid upcoming"):
        asyncio.run(upcoming.async_get_upcoming_reservations("listing-1"))


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
    with pytest.raises(GuestyResponseError, match="invalid listing detail"):
        asyncio.run(client.async_get_listing("missing"))
    assert asyncio.run(client.async_get_reservation_custom_fields("res-1")) == {
        "customFields": []
    }
    assert asyncio.run(client.async_get_account_custom_fields("account-1")) == [
        {"name": "keycode"}
    ]
    assert asyncio.run(client.async_get_guest("guest-1"))["firstName"] == "Anna"
    assert asyncio.run(client.async_get_current_account())["id"] == "account-1"
    assert session.request_calls[0][1] == f"{API_BASE_URL}/listings/listing-1"


def test_upcoming_reservation_query_returns_a_bounded_ordered_snapshot() -> None:
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

    assert [
        item["reservationId"]
        for item in asyncio.run(
            client.async_get_upcoming_reservations(
                "listing-1",
                limit=5,
                as_of=datetime(2030, 5, 6, 23, 59, tzinfo=UTC),
            )
        )
    ] == ["next", "later"]
    assert (
        asyncio.run(client.async_get_upcoming_reservations("listing-1", limit=5)) == []
    )

    method, url, kwargs = session.request_calls[0]
    assert method == "GET"
    assert url == f"{API_BASE_URL}/reservations-v3/search"
    params = kwargs["params"]
    assert params["filter[listingId]"] == "listing-1"
    assert params["filter[status]"] == "confirmed"
    assert params["sort"] == "checkIn"
    assert params["limit"] == 6
    assert params["skip"] == 0
    assert params["filter[checkIn][gte]"] == "2030-05-06"


def test_upcoming_reservation_query_rejects_an_invalid_result_shape() -> None:
    client = GuestyClient(
        FakeSession(requests=[FakeResponse(200, {"results": {"bad": "shape"}})]),
        "id",
        "secret",
        token_data=_valid_token(),
    )

    with pytest.raises(GuestyError, match="invalid upcoming"):
        asyncio.run(client.async_get_upcoming_reservations("listing-1"))
