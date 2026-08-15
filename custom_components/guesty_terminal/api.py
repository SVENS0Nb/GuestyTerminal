"""Async client for the Guesty Open API."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from aiohttp import ClientError, ClientResponse, ClientSession

from .const import ACTIVE_RESERVATION_STATUSES, TOKEN_REFRESH_MARGIN_SECONDS

API_BASE_URL = "https://open-api.guesty.com/v1"
TOKEN_URL = "https://open-api.guesty.com/oauth2/token"


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
        expires_at = float(self._token_data.get("expires_at", 0))
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

            expires_in = int(data.get("expires_in", 86400))
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
                    retry_after = int(response.headers.get("Retry-After", "60"))
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
            )
        )
        results: list[dict[str, Any]] = []
        skip = 0
        while True:
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
            results.extend(item for item in page if isinstance(item, dict))
            if len(page) < 100:
                break
            skip += 100
        return results

    async def async_get_listing(self, listing_id: str) -> dict[str, Any]:
        """Return one full listing, including Wi-Fi fields."""
        data = await self._request("GET", f"/listings/{listing_id}")
        return data if isinstance(data, dict) else {}

    async def async_get_reservations(
        self, listing_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Return current/imminent confirmed or reserved reservations."""
        if not listing_ids:
            return []
        filters = [
            {
                "field": "listingId",
                "operator": "$in",
                "value": listing_ids,
            },
            {
                "field": "status",
                "operator": "$in",
                "value": list(ACTIVE_RESERVATION_STATUSES),
            },
            {
                "field": "checkOutDateLocalized",
                "operator": "$gt",
                # `$gt` yesterday includes reservations that check out today.
                # Those remain valid until their local departure time (plus the
                # configured grace period) in the payload selection logic.
                "value": (datetime.now(UTC).date() - timedelta(days=1)).isoformat(),
            },
            {
                "field": "checkInDateLocalized",
                "operator": "$lt",
                # Mapping options allow at most 48 hours of lead time. Four
                # calendar days safely cover that window across time zones and
                # avoid loading keycodes for every future booking in Guesty.
                "value": (datetime.now(UTC).date() + timedelta(days=4)).isoformat(),
            },
        ]
        fields = " ".join(
            (
                "_id",
                "accountId",
                "listingId",
                "listing",
                "status",
                "guest",
                "guest.firstName",
                "guest.fullName",
                "checkIn",
                "checkOut",
                "checkInDateLocalized",
                "checkOutDateLocalized",
                "plannedArrival",
                "plannedDeparture",
                "lastUpdatedAt",
                "keycode",
                "customFields",
            )
        )
        results: list[dict[str, Any]] = []
        skip = 0
        while True:
            data = await self._request(
                "GET",
                "/reservations",
                params={
                    "fields": fields,
                    "filters": json.dumps(filters, separators=(",", ":")),
                    "sort": "_id",
                    "limit": 100,
                    "skip": skip,
                },
            )
            page = data.get("results", []) if isinstance(data, dict) else []
            results.extend(item for item in page if isinstance(item, dict))
            if len(page) < 100:
                break
            skip += 100
        return results

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
