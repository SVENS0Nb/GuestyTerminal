"""Async client for the Guesty Open API."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime
from math import ceil, isfinite
from time import monotonic
from typing import Any

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout

from .const import (
    ACTIVE_RESERVATION_STATUSES,
    TOKEN_REFRESH_MARGIN_SECONDS,
    UPCOMING_RESERVATIONS_PER_LISTING,
)

API_BASE_URL = "https://open-api.guesty.com/v1"
TOKEN_URL = "https://open-api.guesty.com/oauth2/token"
MAX_PAGINATION_PAGES = 100
DEFAULT_RETRY_AFTER_SECONDS = 60
MAX_RETRY_AFTER_SECONDS = 24 * 60 * 60
RESERVATION_ID_BATCH_SIZE = 10
GUESTY_REQUEST_LIMITS: tuple[tuple[int, float], ...] = (
    (15, 1.0),
    (120, 60.0),
    (5000, 60.0 * 60.0),
)


class GuestyError(Exception):
    """Base Guesty client error."""


class GuestyConnectionError(GuestyError):
    """The Guesty API could not be reached."""


class GuestyRequestError(GuestyError):
    """Guesty rejected a non-authentication API request."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"Guesty request failed ({status_code})")
        self.status_code = status_code
        self.retryable = status_code >= 500


class GuestyResponseError(GuestyError):
    """Guesty returned a response that cannot be reconciled safely."""


class GuestyAuthenticationError(GuestyError):
    """Guesty rejected the configured credentials."""


class GuestyRateLimitError(GuestyError):
    """Guesty rate-limited the request."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Guesty rate limit reached; retry after {retry_after}s")
        self.retry_after = retry_after


TokenSaver = Callable[[dict[str, Any]], Awaitable[None]]
MonotonicClock = Callable[[], float]
AsyncSleep = Callable[[float], Awaitable[None]]


class GuestyRequestLimiter:
    """Queue one client's API traffic inside Guesty's sliding-window limits."""

    def __init__(
        self,
        *,
        limits: tuple[tuple[int, float], ...] = GUESTY_REQUEST_LIMITS,
        clock: MonotonicClock = monotonic,
        sleep: AsyncSleep = asyncio.sleep,
    ) -> None:
        if not limits or any(count <= 0 or period <= 0 for count, period in limits):
            raise ValueError("Guesty request limits must be positive")
        self._limits = tuple(sorted(limits, key=lambda item: item[1]))
        self._longest_period = max(period for _count, period in self._limits)
        self._clock = clock
        self._sleep = sleep
        self._requests: deque[float] = deque()
        self._blocked_until = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until one request is allowed by every configured window."""
        while True:
            async with self._lock:
                current = self._clock()
                while (
                    self._requests
                    and current - self._requests[0] >= self._longest_period
                ):
                    self._requests.popleft()

                if self._blocked_until > current:
                    # Server-directed backoff is not ordinary queue pressure.
                    # Surface it immediately so coordinator/manual callers can
                    # report a bounded retry time instead of appearing hung for
                    # minutes or hours before the HTTP timeout even begins.
                    raise GuestyRateLimitError(
                        max(1, ceil(self._blocked_until - current))
                    )

                wait_seconds = 0.0
                for request_count, period in self._limits:
                    if len(self._requests) < request_count:
                        continue
                    boundary = self._requests[-request_count]
                    wait_seconds = max(
                        wait_seconds,
                        boundary + period - current,
                    )

                if wait_seconds <= 0:
                    self._requests.append(current)
                    return
            await self._sleep(wait_seconds)

    async def defer(self, seconds: int) -> None:
        """Apply Guesty's Retry-After value to subsequent requests."""
        async with self._lock:
            self._blocked_until = max(
                self._blocked_until,
                self._clock() + max(0, seconds),
            )


def _positive_seconds(value: Any, default: int) -> int:
    """Return a bounded positive duration from an untrusted API value."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return default
    if not isfinite(seconds) or seconds <= 0:
        return default
    return max(1, ceil(seconds))


def _retry_after_seconds(value: Any) -> int:
    """Parse either Retry-After seconds or its HTTP-date representation."""
    parsed = _positive_seconds(value, 0)
    if parsed:
        return min(parsed, MAX_RETRY_AFTER_SECONDS)
    try:
        retry_at = parsedate_to_datetime(str(value))
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_RETRY_AFTER_SECONDS
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    seconds = ceil((retry_at.astimezone(UTC) - datetime.now(UTC)).total_seconds())
    if seconds <= 0:
        return DEFAULT_RETRY_AFTER_SECONDS
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


def _page_signature(page: list[Any]) -> tuple[str, ...]:
    """Return a non-sensitive marker used to detect repeated API pages."""
    return tuple(
        str(
            item.get("reservationId")
            or item.get("_id")
            or item.get("id")
            or f"missing-id-{index}"
        )
        for index, item in enumerate(page)
        if isinstance(item, dict)
    )


def _query_date(as_of: datetime | None) -> date:
    """Return one stable UTC date for all filters in an update cycle."""
    current = as_of or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).date()


def _reservation_response_id(data: dict[str, Any]) -> str:
    """Return one scalar reservation ID without stringifying response objects."""
    for key in ("reservationId", "_id", "id"):
        value = data.get(key)
        if isinstance(value, str) and (identifier := value.strip()):
            return identifier
    return ""


def _listing_response_id(data: dict[str, Any]) -> str:
    """Return one scalar listing ID from a collection/detail projection."""
    for key in ("_id", "id"):
        value = data.get(key)
        if isinstance(value, str) and (identifier := value.strip()):
            return identifier
    return ""


class GuestyClient:
    """Small authenticated Guesty Open API client."""

    def __init__(
        self,
        session: ClientSession,
        client_id: str,
        client_secret: str,
        *,
        token_data: dict[str, Any] | None = None,
        token_saver: TokenSaver | None = None,
        request_limiter: GuestyRequestLimiter | None = None,
    ) -> None:
        self._session = session
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_data = token_data or {}
        self._token_saver = token_saver
        self._token_lock = asyncio.Lock()
        self._request_limiter = request_limiter or GuestyRequestLimiter()

    def _token_is_valid(self) -> bool:
        token = self._token_data.get("access_token")
        try:
            expires_at = float(self._token_data.get("expires_at", 0))
        except (TypeError, ValueError):
            return False
        return (
            bool(token)
            and expires_at - TOKEN_REFRESH_MARGIN_SECONDS
            > datetime.now(UTC).timestamp()
        )

    async def _access_token(self) -> str:
        if self._token_is_valid():
            return str(self._token_data["access_token"])

        async with self._token_lock:
            if self._token_is_valid():
                return str(self._token_data["access_token"])
            try:
                async with self._session.post(
                    TOKEN_URL,
                    data={
                        "grant_type": "client_credentials",
                        "scope": "open-api",
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                    },
                    headers={"Accept": "application/json"},
                    timeout=ClientTimeout(total=20),
                ) as response:
                    data = await self._decode_response(response)
            except (TimeoutError, ClientError):
                # Raise the public error after leaving the exception handler.
                # This prevents the transport exception (and any URL or
                # identifier it contains) from becoming __context__/__cause__
                # or appearing in a formatted Home Assistant traceback.
                pass
            else:
                if response.status in (400, 401, 403):
                    raise GuestyAuthenticationError("Invalid Guesty credentials")
                if response.status >= 400:
                    raise GuestyError(
                        f"Guesty token request failed ({response.status})"
                    )

                token = data.get("access_token") if isinstance(data, dict) else None
                if not token:
                    raise GuestyAuthenticationError("Guesty returned no access token")

                expires_in = _positive_seconds(data.get("expires_in"), 86400)
                self._token_data = {
                    "access_token": token,
                    "expires_at": datetime.now(UTC).timestamp() + expires_in,
                }
                if self._token_saver is not None:
                    await self._token_saver(dict(self._token_data))
                return str(token)

            raise GuestyConnectionError("Could not reach Guesty authentication")

    async def _decode_response(self, response: ClientResponse) -> Any:
        try:
            return await response.json(content_type=None)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"message": (await response.text())[:300]}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> Any:
        token = await self._access_token()
        # Reserve the rate-limit slot immediately before the API request. A
        # delayed OAuth refresh must not age a slot before any Guesty traffic
        # has actually been sent and then release a burst outside the window.
        await self._request_limiter.acquire()
        try:
            async with self._session.request(
                method,
                f"{API_BASE_URL}{path}",
                params=params,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                timeout=ClientTimeout(total=30),
            ) as response:
                data = await self._decode_response(response)
                if response.status == 401 and retry_auth:
                    self._token_data = {}
                    return await self._request(
                        method, path, params=params, retry_auth=False
                    )
                if response.status in (401, 403):
                    raise GuestyAuthenticationError("Guesty authorization failed")
                if response.status == 429:
                    retry_after = _retry_after_seconds(
                        response.headers.get("Retry-After")
                    )
                    await self._request_limiter.defer(retry_after)
                    raise GuestyRateLimitError(retry_after)
                if response.status >= 400:
                    raise GuestyRequestError(response.status)
                return data
        except GuestyError:
            raise
        except (TimeoutError, ClientError):
            # Leave the handler before raising the sanitized public exception;
            # otherwise Python retains the transport error as traceback context.
            pass
        raise GuestyConnectionError("Could not reach Guesty API")

    async def async_get_listings(self) -> list[dict[str, Any]]:
        """Return active Guesty listings with display-relevant fields."""
        fields = " ".join(
            (
                "_id",
                "title",
                "nickname",
                "timezone",
                "defaultCheckInTime",
                "defaultCheckOutTime",
                "wifiName",
                "wifiPassword",
                "checkoutInstructions",
                "checkOutInstructions",
                "departureInstructions",
                "terms",
            )
        )
        results: list[dict[str, Any]] = []
        skip = 0
        seen_pages: set[tuple[str, ...]] = set()
        for _page_number in range(MAX_PAGINATION_PAGES):
            data = await self._request(
                "GET",
                "/listings",
                params={
                    "active": "true",
                    "pmsActive": "true",
                    "fields": fields,
                    "limit": 100,
                    "skip": skip,
                    "sort": "_id",
                },
            )
            if not isinstance(data, dict) or "results" not in data:
                raise GuestyResponseError(
                    "Guesty returned invalid listing pagination data"
                )
            page = data["results"]
            if not isinstance(page, list):
                raise GuestyResponseError(
                    "Guesty returned invalid listing pagination data"
                )
            if not page:
                break
            if any(
                not isinstance(item, dict) or not _listing_response_id(item)
                for item in page
            ):
                raise GuestyResponseError(
                    "Guesty returned invalid listing pagination data"
                )
            signature = _page_signature(page)
            if signature in seen_pages:
                raise GuestyResponseError("Guesty repeated a listing pagination page")
            seen_pages.add(signature)
            results.extend(page)
            if len(page) < 100:
                break
            skip += 100
        else:
            raise GuestyResponseError(
                "Guesty listing pagination exceeded the safety limit"
            )
        return results

    async def async_get_listing(self, listing_id: str) -> dict[str, Any]:
        """Return one full listing, including Wi-Fi fields."""
        data = await self._request("GET", f"/listings/{listing_id}")
        if not isinstance(data, dict) or _listing_response_id(data) != listing_id:
            raise GuestyResponseError("Guesty returned invalid listing detail data")
        return data

    async def async_get_reservations(
        self,
        listing_ids: list[str],
        *,
        as_of: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return current or imminent confirmed reservations through v3 search."""
        if not listing_ids:
            return []
        return await self._async_get_current_reservation_rows(
            listing_ids,
            as_of=as_of,
        )

    async def async_get_current_reservations(
        self,
        *,
        as_of: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Discover current/imminent rows without Guesty's first-stay filter.

        Guesty's V3 ``filter[listingId]`` only evaluates the first stay
        segment. The account-scoped companion snapshot lets Home Assistant
        discover a reservation whose active later segment owns a mapped unit
        even after a restart, while the coordinator still routes each row only
        to explicitly configured listing identities.
        """
        return await self._async_get_current_reservation_rows(None, as_of=as_of)

    async def _async_get_current_reservation_rows(
        self,
        listing_ids: list[str] | None,
        *,
        as_of: datetime | None,
    ) -> list[dict[str, Any]]:
        """Return one paginated current/recent V3 search projection."""
        query_date = _query_date(as_of)
        results: list[dict[str, Any]] = []
        skip = 0
        seen_pages: set[tuple[str, ...]] = set()
        for _page_number in range(MAX_PAGINATION_PAGES):
            params: dict[str, Any] = {
                "filter[status]": ",".join(ACTIVE_RESERVATION_STATUSES),
                # Yesterday safely covers checkouts around UTC/local-date
                # boundaries. Exact visibility is enforced locally.
                "filter[checkOut][gte]": (query_date - timedelta(days=1)).isoformat(),
                # Up to 48 hours of configurable lead time plus timezone
                # headroom, without loading every future reservation.
                "filter[checkIn][lt]": (query_date + timedelta(days=4)).isoformat(),
                "sort": "_id",
                "limit": 100,
                "skip": skip,
            }
            if listing_ids is not None:
                params["filter[listingId]"] = ",".join(listing_ids)
            data = await self._request(
                "GET",
                "/reservations-v3/search",
                params=params,
            )
            if not isinstance(data, dict) or "results" not in data:
                raise GuestyResponseError(
                    "Guesty returned invalid reservation pagination data"
                )
            page = data["results"]
            if not isinstance(page, list):
                raise GuestyResponseError(
                    "Guesty returned invalid reservation pagination data"
                )
            pagination = data.get("pagination", {})
            has_more = (
                pagination.get("hasMore") if isinstance(pagination, dict) else None
            )
            if not page:
                if has_more is True:
                    raise GuestyResponseError(
                        "Guesty returned inconsistent reservation pagination data"
                    )
                break
            if any(
                not isinstance(item, dict) or not _reservation_response_id(item)
                for item in page
            ):
                raise GuestyResponseError(
                    "Guesty returned invalid reservation pagination data"
                )
            signature = _page_signature(page)
            if signature in seen_pages:
                raise GuestyResponseError(
                    "Guesty repeated a reservation pagination page"
                )
            seen_pages.add(signature)
            results.extend(page)
            if has_more is not True and (has_more is not None or len(page) < 100):
                break
            skip += 100
        else:
            raise GuestyResponseError(
                "Guesty reservation pagination exceeded the safety limit"
            )
        return results

    async def async_get_reservations_by_ids(
        self, reservation_ids: Iterable[str]
    ) -> list[dict[str, Any]]:
        """Verify known reservations in batches accepted by Guesty's V3 API."""
        ordered_ids: list[str] = []
        seen_ids: set[str] = set()
        for value in reservation_ids:
            if not isinstance(value, str) or not (identifier := value.strip()):
                raise ValueError("Reservation IDs must be non-empty strings")
            if identifier not in seen_ids:
                seen_ids.add(identifier)
                ordered_ids.append(identifier)
        if not ordered_ids:
            return []

        reservations_by_id: dict[str, dict[str, Any]] = {}
        for start in range(0, len(ordered_ids), RESERVATION_ID_BATCH_SIZE):
            batch = ordered_ids[start : start + RESERVATION_ID_BATCH_SIZE]
            batch_ids = set(batch)
            data = await self._request(
                "GET",
                "/reservations-v3",
                params={"reservationIds[]": batch},
            )
            if not isinstance(data, list) or any(
                not isinstance(item, dict) for item in data
            ):
                raise GuestyResponseError(
                    "Guesty returned invalid reservation verification data"
                )
            for item in data:
                reservation_id = _reservation_response_id(item)
                if not reservation_id or reservation_id not in batch_ids:
                    raise GuestyResponseError(
                        "Guesty returned inconsistent reservation verification data"
                    )
                if reservation_id in reservations_by_id:
                    raise GuestyResponseError(
                        "Guesty returned inconsistent reservation verification data"
                    )
                reservations_by_id[reservation_id] = item

        return [
            reservations_by_id[reservation_id]
            for reservation_id in ordered_ids
            if reservation_id in reservations_by_id
        ]

    async def async_get_guest(self, guest_id: str) -> dict[str, Any]:
        """Return the guest name fields needed by the welcome screen."""
        data = await self._request(
            "GET",
            f"/guests-crud/{guest_id}",
            params={"fields": "_id firstName fullName"},
        )
        return data if isinstance(data, dict) else {}

    async def async_get_upcoming_reservations(
        self,
        listing_id: str,
        *,
        limit: int = UPCOMING_RESERVATIONS_PER_LISTING,
        as_of: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Return an ordered booking snapshot for one listing.

        One extra row provides headroom for a stay that began earlier on the
        current UTC date. The coordinator applies exact timezone-aware checks
        and retains at least the next ``limit`` future reservations.
        """
        requested = max(1, int(limit))
        query_date = _query_date(as_of)
        data = await self._request(
            "GET",
            "/reservations-v3/search",
            params={
                "filter[listingId]": listing_id,
                "filter[status]": ",".join(ACTIVE_RESERVATION_STATUSES),
                # Query from today rather than the short display window so
                # additions, edits and cancellations are reconciled on every
                # normal poll even when the booking is months away.
                "filter[checkIn][gte]": query_date.isoformat(),
                "sort": "checkIn",
                "limit": requested + 1,
                "skip": 0,
            },
        )
        if not isinstance(data, dict) or "results" not in data:
            raise GuestyResponseError(
                "Guesty returned invalid upcoming reservation data"
            )
        results = data["results"]
        if not isinstance(results, list):
            raise GuestyResponseError(
                "Guesty returned invalid upcoming reservation data"
            )
        if any(
            not isinstance(item, dict) or not _reservation_response_id(item)
            for item in results
        ):
            raise GuestyResponseError(
                "Guesty returned invalid upcoming reservation data"
            )
        return results[: requested + 1]

    async def async_get_current_account(self) -> dict[str, Any]:
        """Return the current Guesty account for custom-field resolution."""
        data = await self._request("GET", "/accounts/me")
        return data if isinstance(data, dict) else {}

    async def async_get_reservation_custom_fields(
        self, reservation_id: str
    ) -> dict[str, Any]:
        """Return populated v3 custom fields for one reservation."""
        data = await self._request(
            "GET", f"/reservations-v3/{reservation_id}/custom-fields"
        )
        return data if isinstance(data, dict) else {}

    async def async_get_account_custom_fields(self, account_id: str) -> Any:
        """Return the account's custom field definitions."""
        return await self._request("GET", f"/accounts/{account_id}/custom-fields")
