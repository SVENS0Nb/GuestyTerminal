"""Async client for the Guesty Open API."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from math import ceil, isfinite
from typing import Any

from aiohttp import ClientError, ClientResponse, ClientSession

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


class GuestyError(Exception):
    """Base Guesty client error."""


class GuestyAuthenticationError(GuestyError):
    """Guesty rejected the configured credentials."""


class GuestyRateLimitError(GuestyError):
    """Guesty rate-limited the request."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Guesty rate limit reached; retry after {retry_after}s")
        self.retry_after = retry_after


TokenSaver = Callable[[dict[str, Any]], Awaitable[None]]


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
    ) -> None:
        self._session = session
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_data = token_data or {}
        self._token_saver = token_saver
        self._token_lock = asyncio.Lock()

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
                    timeout=20,
                ) as response:
                    data = await self._decode_response(response)
            except (TimeoutError, ClientError) as err:
                raise GuestyError("Could not reach Guesty authentication") from err

            if response.status in (400, 401, 403):
                raise GuestyAuthenticationError("Invalid Guesty credentials")
            if response.status >= 400:
                raise GuestyError(f"Guesty token request failed ({response.status})")

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
        try:
            async with self._session.request(
                method,
                f"{API_BASE_URL}{path}",
                params=params,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                timeout=30,
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
                    raise GuestyRateLimitError(retry_after)
                if response.status >= 400:
                    message = data.get("message") if isinstance(data, dict) else None
                    raise GuestyError(
                        f"Guesty request failed ({response.status}): {message or path}"
                    )
                return data
        except GuestyError:
            raise
        except (TimeoutError, ClientError) as err:
            raise GuestyError(f"Could not reach Guesty endpoint {path}") from err

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
            page = data.get("results", []) if isinstance(data, dict) else []
            if not isinstance(page, list):
                raise GuestyError("Guesty returned invalid listing pagination data")
            if not page:
                break
            signature = _page_signature(page)
            if signature in seen_pages:
                raise GuestyError("Guesty repeated a listing pagination page")
            seen_pages.add(signature)
            results.extend(item for item in page if isinstance(item, dict))
            if len(page) < 100:
                break
            skip += 100
        else:
            raise GuestyError("Guesty listing pagination exceeded the safety limit")
        return results

    async def async_get_listing(self, listing_id: str) -> dict[str, Any]:
        """Return one full listing, including Wi-Fi fields."""
        data = await self._request("GET", f"/listings/{listing_id}")
        return data if isinstance(data, dict) else {}

    async def async_get_reservations(
        self, listing_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Return current or imminent confirmed reservations through v3 search."""
        if not listing_ids:
            return []
        results: list[dict[str, Any]] = []
        skip = 0
        seen_pages: set[tuple[str, ...]] = set()
        for _page_number in range(MAX_PAGINATION_PAGES):
            data = await self._request(
                "GET",
                "/reservations-v3/search",
                params={
                    "filter[listingId]": ",".join(listing_ids),
                    "filter[status]": ",".join(ACTIVE_RESERVATION_STATUSES),
                    # Yesterday safely covers checkouts around UTC/local-date
                    # boundaries. Exact visibility is enforced locally.
                    "filter[checkOut][gte]": (
                        datetime.now(UTC).date() - timedelta(days=1)
                    ).isoformat(),
                    # Up to 48 hours of configurable lead time plus timezone
                    # headroom, without loading every future reservation.
                    "filter[checkIn][lt]": (
                        datetime.now(UTC).date() + timedelta(days=4)
                    ).isoformat(),
                    "sort": "_id",
                    "limit": 100,
                    "skip": skip,
                },
            )
            page = data.get("results", []) if isinstance(data, dict) else []
            if not isinstance(page, list):
                raise GuestyError("Guesty returned invalid reservation pagination data")
            if not page:
                break
            signature = _page_signature(page)
            if signature in seen_pages:
                raise GuestyError("Guesty repeated a reservation pagination page")
            seen_pages.add(signature)
            results.extend(item for item in page if isinstance(item, dict))
            pagination = data.get("pagination", {}) if isinstance(data, dict) else {}
            has_more = (
                pagination.get("hasMore") if isinstance(pagination, dict) else None
            )
            if has_more is not True and (has_more is not None or len(page) < 100):
                break
            skip += 100
        else:
            raise GuestyError("Guesty reservation pagination exceeded the safety limit")
        return results

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
    ) -> list[dict[str, Any]]:
        """Return an ordered booking snapshot for one listing.

        One extra row provides headroom for a stay that began earlier on the
        current UTC date. The coordinator applies exact timezone-aware checks
        and retains at least the next ``limit`` future reservations.
        """
        requested = max(1, int(limit))
        data = await self._request(
            "GET",
            "/reservations-v3/search",
            params={
                "filter[listingId]": listing_id,
                "filter[status]": ",".join(ACTIVE_RESERVATION_STATUSES),
                # Query from today rather than the short display window so
                # additions, edits and cancellations are reconciled on every
                # normal poll even when the booking is months away.
                "filter[checkIn][gte]": (datetime.now(UTC).date()).isoformat(),
                "sort": "checkIn",
                "limit": requested + 1,
                "skip": 0,
            },
        )
        results = data.get("results", []) if isinstance(data, dict) else []
        if not isinstance(results, list):
            raise GuestyError("Guesty returned invalid upcoming reservation data")
        return [item for item in results if isinstance(item, dict)][: requested + 1]

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
