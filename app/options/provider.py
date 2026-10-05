from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import re
import time
from typing import Any, Protocol

import httpx

from app.config import OptionsCacheConfig, OptionsFeed, OptionsProviderConfig
from app.options.cache import BoundedTTLCache, CacheResult
from app.options.models import (
    OptionChainMetadata,
    OptionChainResult,
    OptionContract,
    OptionType,
    EventDataStatus,
    ProviderErrorKind,
    ProviderResponseMetadata,
)

_SAFE_HEADER_VALUE = re.compile(r"[^A-Za-z0-9._:/+\-]")


class OptionsProviderError(RuntimeError):
    def __init__(
        self,
        kind: ProviderErrorKind,
        message: str,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
        retry_after: str | None = None,
        feed: str | None = None,
        rate_limit_remaining: int | None = None,
        rate_limit_reset: str | None = None,
        response_time_ms: float | None = None,
        request_count: int = 0,
        cache_hits: int = 0,
        cache_misses: int = 0,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.request_id = request_id
        self.retry_after = retry_after
        self.feed = feed
        self.rate_limit_remaining = rate_limit_remaining
        self.rate_limit_reset = rate_limit_reset
        self.response_time_ms = response_time_ms
        self.request_count = request_count
        self.cache_hits = cache_hits
        self.cache_misses = cache_misses


class MissingOptionsCredentialsError(OptionsProviderError):
    def __init__(self, message: str, **metadata: object) -> None:
        super().__init__(
            ProviderErrorKind.CREDENTIALS_MISSING, message, **metadata
        )


class OptionsAuthenticationError(OptionsProviderError):
    def __init__(self, message: str, **metadata: object) -> None:
        super().__init__(ProviderErrorKind.UNAUTHORIZED, message, **metadata)


class OptionsAuthorizationError(OptionsProviderError):
    def __init__(self, message: str, **metadata: object) -> None:
        super().__init__(ProviderErrorKind.FORBIDDEN, message, **metadata)


class OptionsEntitlementError(OptionsProviderError):
    def __init__(self, message: str, **metadata: object) -> None:
        super().__init__(
            ProviderErrorKind.ENTITLEMENT_REQUIRED, message, **metadata
        )


class OptionsRateLimitError(OptionsProviderError):
    def __init__(self, message: str, **metadata: object) -> None:
        super().__init__(ProviderErrorKind.RATE_LIMITED, message, **metadata)


class OptionsServerError(OptionsProviderError):
    def __init__(self, message: str, **metadata: object) -> None:
        super().__init__(ProviderErrorKind.SERVER_ERROR, message, **metadata)


class OptionsNetworkError(OptionsProviderError):
    def __init__(self, message: str, **metadata: object) -> None:
        super().__init__(ProviderErrorKind.NETWORK_ERROR, message, **metadata)


class OptionsInvalidResponseError(OptionsProviderError):
    def __init__(self, message: str, **metadata: object) -> None:
        super().__init__(
            ProviderErrorKind.INVALID_RESPONSE, message, **metadata
        )


class OptionsPaginationError(OptionsProviderError):
    def __init__(self, message: str, **metadata: object) -> None:
        super().__init__(ProviderErrorKind.PAGINATION_LIMIT, message, **metadata)


class OptionsDataProvider(Protocol):
    @property
    def name(self) -> str: ...

    def get_option_chain(
        self,
        ticker: str,
        *,
        as_of: datetime,
        underlying_price: float,
        max_otm_pct: float | None = None,
        min_dte: int = 60,
        max_dte: int = 120,
    ) -> OptionChainResult: ...


@dataclass(frozen=True)
class _Resource:
    data: Any
    responses: tuple[ProviderResponseMetadata, ...]
    warnings: tuple[str, ...] = ()


class AlpacaOptionsDataProvider:
    """Read-only adapter for Alpaca option snapshots and contract metadata."""

    def __init__(
        self,
        api_key: str | None,
        api_secret: str | None,
        *,
        config: OptionsProviderConfig | None = None,
        cache_config: OptionsCacheConfig | None = None,
        transport: httpx.BaseTransport | None = None,
        cache: BoundedTTLCache[tuple[object, ...], _Resource] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        timer: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self.config = config or OptionsProviderConfig()
        self.cache_config = cache_config or OptionsCacheConfig()
        self._transport = transport
        self._clock = clock
        self._timer = timer
        self._cache = (
            cache
            if cache is not None
            else BoundedTTLCache(self.cache_config.max_entries)
        )

    @property
    def name(self) -> str:
        return "alpaca_options"

    @property
    def feed(self) -> str:
        return self.config.feed.value

    def _headers(self) -> dict[str, str]:
        if not self._api_key or not self._api_secret:
            raise MissingOptionsCredentialsError(
                "Alpaca options credentials are missing; configure "
                "ALPACA_API_KEY and ALPACA_API_SECRET",
            )
        return {
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._api_secret,
        }

    @staticmethod
    def _safe_header(value: str | None) -> str | None:
        if not value:
            return None
        return _SAFE_HEADER_VALUE.sub("", value)[:128] or None

    def _request_json(
        self,
        client: httpx.Client,
        url: str,
        *,
        params: dict[str, str | int | float],
        endpoint: str,
    ) -> tuple[dict[str, Any], ProviderResponseMetadata]:
        started = self._timer()
        try:
            response = client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise OptionsNetworkError(
                f"Alpaca options network request failed ({type(exc).__name__})",
                feed=self.feed,
                response_time_ms=max(
                    0.0, (self._timer() - started) * 1000
                ),
                request_count=1,
                cache_misses=1,
            ) from exc
        elapsed_ms = max(0.0, (self._timer() - started) * 1000)
        request_id = self._safe_header(
            response.headers.get("x-request-id")
            or response.headers.get("apca-request-id")
        )
        retry_after = self._safe_header(response.headers.get("retry-after"))
        remaining = _optional_int(response.headers.get("x-ratelimit-remaining"))
        if remaining is not None and remaining < 0:
            remaining = None
        rate_limit_reset = self._safe_header(
            response.headers.get("x-ratelimit-reset")
        )
        error_metadata = {
            "status_code": response.status_code,
            "request_id": request_id,
            "retry_after": retry_after,
            "feed": self.feed,
            "rate_limit_remaining": remaining,
            "rate_limit_reset": rate_limit_reset,
            "response_time_ms": elapsed_ms,
            "request_count": 1,
            "cache_misses": 1,
        }
        if response.status_code == 401:
            raise OptionsAuthenticationError(
                "Alpaca options authentication was rejected",
                **error_metadata,
            )
        if response.status_code == 403:
            if self.config.feed is OptionsFeed.OPRA:
                message = (
                    "OPRA options data is not entitled for this account; "
                    "Alpaca Basic users should configure the indicative feed"
                )
                error_type = OptionsEntitlementError
            else:
                message = "Alpaca options access was forbidden"
                error_type = OptionsAuthorizationError
            raise error_type(
                message,
                **error_metadata,
            )
        if response.status_code == 429:
            raise OptionsRateLimitError(
                "Alpaca options rate limit was exceeded",
                **error_metadata,
            )
        if response.status_code >= 500:
            raise OptionsServerError(
                "Alpaca options service returned a server error",
                **error_metadata,
            )
        if response.is_error:
            raise OptionsInvalidResponseError(
                f"Alpaca options request returned HTTP {response.status_code}",
                **error_metadata,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise OptionsInvalidResponseError(
                "Alpaca options response was not valid JSON",
                **error_metadata,
            ) from exc
        if not isinstance(payload, dict):
            raise OptionsInvalidResponseError(
                "Alpaca options response must be a JSON object",
                **error_metadata,
            )
        metadata = ProviderResponseMetadata(
            endpoint=endpoint,
            request_id=request_id,
            status_code=response.status_code,
            rate_limit_remaining=remaining,
            rate_limit_reset=rate_limit_reset,
            response_time_ms=elapsed_ms,
            fetched_at=self._now(),
        )
        return payload, metadata

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("provider clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    def _contracts_resource(
        self,
        client: httpx.Client,
        *,
        ticker: str,
        expiration_gte: date,
        expiration_lte: date,
        strike_lte: float | None,
    ) -> _Resource:
        params: dict[str, str | int | float] = {
            "underlying_symbols": ticker,
            "status": "active",
            "type": "call",
            "expiration_date_gte": expiration_gte.isoformat(),
            "expiration_date_lte": expiration_lte.isoformat(),
            "limit": self.config.contracts_page_size,
        }
        if strike_lte is not None:
            params["strike_price_lte"] = round(strike_lte, 8)
        records: list[Any] = []
        responses: list[ProviderResponseMetadata] = []
        warnings: list[str] = []
        for page in range(self.config.max_contract_pages):
            try:
                payload, response = self._request_json(
                    client,
                    f"{self.config.trading_base_url}/v2/options/contracts",
                    params=params,
                    endpoint="contracts",
                )
            except OptionsProviderError as exc:
                exc.request_count += len(responses)
                raise
            responses.append(response)
            items = payload.get("option_contracts", [])
            if not isinstance(items, list):
                raise OptionsInvalidResponseError(
                    "Alpaca contracts payload has an invalid option_contracts field",
                    **_resource_error_metadata(responses),
                    cache_misses=1,
                )
            records.extend(items)
            if len(records) >= self.config.max_chain_contracts:
                records = records[: self.config.max_chain_contracts]
                warnings.append("Configured maximum chain contract count was reached")
                break
            token = payload.get("next_page_token")
            if not token:
                break
            if page + 1 >= self.config.max_contract_pages:
                raise OptionsPaginationError(
                    "Alpaca contract pagination exceeded the configured page cap",
                    **_resource_error_metadata(responses),
                    cache_misses=1,
                )
            params["page_token"] = str(token)
        return _Resource(records, tuple(responses), tuple(warnings))

    def _snapshots_resource(
        self,
        client: httpx.Client,
        *,
        ticker: str,
        expiration_gte: date,
        expiration_lte: date,
        strike_lte: float | None,
    ) -> _Resource:
        params: dict[str, str | int | float] = {
            "feed": self.feed,
            "type": "call",
            "expiration_date_gte": expiration_gte.isoformat(),
            "expiration_date_lte": expiration_lte.isoformat(),
            "limit": self.config.snapshot_page_size,
        }
        if strike_lte is not None:
            params["strike_price_lte"] = round(strike_lte, 8)
        snapshots: dict[str, Any] = {}
        responses: list[ProviderResponseMetadata] = []
        warnings: list[str] = []
        for page in range(self.config.max_snapshot_pages):
            try:
                payload, response = self._request_json(
                    client,
                    f"{self.config.data_base_url}/v1beta1/options/snapshots/{ticker}",
                    params=params,
                    endpoint="snapshots",
                )
            except OptionsProviderError as exc:
                exc.request_count += len(responses)
                raise
            responses.append(response)
            items = payload.get("snapshots", {})
            if not isinstance(items, dict):
                raise OptionsInvalidResponseError(
                    "Alpaca snapshots payload has an invalid snapshots field",
                    **_resource_error_metadata(responses),
                    cache_misses=1,
                )
            for symbol, item in items.items():
                if isinstance(symbol, str):
                    snapshots[symbol] = item
            if len(snapshots) >= self.config.max_chain_contracts:
                snapshots = dict(
                    list(snapshots.items())[: self.config.max_chain_contracts]
                )
                warnings.append("Configured maximum chain snapshot count was reached")
                break
            token = payload.get("next_page_token")
            if not token:
                break
            if page + 1 >= self.config.max_snapshot_pages:
                raise OptionsPaginationError(
                    "Alpaca snapshot pagination exceeded the configured page cap",
                    **_resource_error_metadata(responses),
                    cache_misses=1,
                )
            params["page_token"] = str(token)
        return _Resource(snapshots, tuple(responses), tuple(warnings))

    @staticmethod
    def _cached_responses(
        lookup: CacheResult[_Resource],
    ) -> list[ProviderResponseMetadata]:
        return [
            response.model_copy(
                update={
                    "cache_hit": lookup.hit,
                    "source_age_seconds": lookup.age_seconds,
                }
            )
            for response in lookup.value.responses
        ]

    def get_option_chain(
        self,
        ticker: str,
        *,
        as_of: datetime,
        underlying_price: float,
        max_otm_pct: float | None = None,
        min_dte: int = 60,
        max_dte: int = 120,
    ) -> OptionChainResult:
        normalized = ticker.strip().upper()
        if not normalized:
            raise ValueError("ticker must not be empty")
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must be timezone-aware")
        if underlying_price <= 0:
            raise ValueError("underlying_price must be positive")
        expiration_gte = as_of.astimezone(UTC).date() + timedelta(days=min_dte)
        expiration_lte = as_of.astimezone(UTC).date() + timedelta(days=max_dte)
        if expiration_gte > expiration_lte:
            raise ValueError("min_dte must not exceed max_dte")
        strike_lte = (
            underlying_price * (1 + max_otm_pct)
            if max_otm_pct is not None
            else None
        )
        metadata_key = (
            "contract_metadata",
            normalized,
            expiration_gte,
            expiration_lte,
            strike_lte,
        )
        chain_key = (
            "chain",
            normalized,
            expiration_gte,
            expiration_lte,
            strike_lte,
            self.feed,
        )

        headers = self._headers()
        with httpx.Client(
            headers=headers,
            timeout=self.config.request_timeout_seconds,
            transport=self._transport,
            follow_redirects=False,
        ) as client:
            try:
                contract_lookup = self._cache.get_or_load(
                    metadata_key,
                    ttl_seconds=self.cache_config.contract_metadata_ttl_seconds,
                    loader=lambda: self._contracts_resource(
                        client,
                        ticker=normalized,
                        expiration_gte=expiration_gte,
                        expiration_lte=expiration_lte,
                        strike_lte=strike_lte,
                    ),
                )
                snapshot_lookup = self._cache.get_or_load(
                    chain_key,
                    ttl_seconds=self.cache_config.chain_ttl_seconds,
                    loader=lambda: self._snapshots_resource(
                        client,
                        ticker=normalized,
                        expiration_gte=expiration_gte,
                        expiration_lte=expiration_lte,
                        strike_lte=strike_lte,
                    ),
                )
            except OptionsProviderError as exc:
                if "contract_lookup" in locals():
                    exc.request_count += (
                        0 if contract_lookup.hit else len(contract_lookup.value.responses)
                    )
                    exc.cache_hits += int(contract_lookup.hit)
                    exc.cache_misses += int(not contract_lookup.hit)
                raise

        contracts, malformed = self._normalize(
            normalized,
            contract_lookup.value.data,
            snapshot_lookup.value.data,
            underlying_price=underlying_price,
            as_of=as_of,
        )
        responses = [
            *self._cached_responses(contract_lookup),
            *self._cached_responses(snapshot_lookup),
        ]
        request_count = sum(not response.cache_hit for response in responses)
        hits = int(contract_lookup.hit) + int(snapshot_lookup.hit)
        misses = 2 - hits
        source_age = max(
            contract_lookup.age_seconds, snapshot_lookup.age_seconds
        )
        return OptionChainResult(
            contracts=contracts,
            metadata=OptionChainMetadata(
                provider_name=self.name,
                feed=self.feed,
                responses=responses,
                request_count=request_count,
                cache_hits=hits,
                cache_misses=misses,
                malformed_items=len(malformed),
                malformed_item_messages=malformed[:20],
                warnings=[
                    *contract_lookup.value.warnings,
                    *snapshot_lookup.value.warnings,
                ],
                source_age_seconds=source_age,
            ),
        )

    def _normalize(
        self,
        ticker: str,
        metadata_items: list[Any],
        snapshots: dict[str, Any],
        *,
        underlying_price: float,
        as_of: datetime,
    ) -> tuple[list[OptionContract], list[str]]:
        contracts: list[OptionContract] = []
        malformed: list[str] = []
        for index, item in enumerate(metadata_items):
            if not isinstance(item, dict):
                malformed.append(f"item-{index}: invalid metadata object")
                continue
            symbol = str(item.get("symbol") or "").strip()
            try:
                if not symbol:
                    raise ValueError("missing contract symbol")
                expiration = date.fromisoformat(str(item["expiration_date"]))
                strike = float(item["strike_price"])
                option_type = OptionType(str(item.get("type", "")).upper())
                snapshot = snapshots.get(symbol, {})
                if not isinstance(snapshot, dict):
                    raise ValueError("invalid snapshot object")
                quote = _mapping(snapshot.get("latestQuote"))
                trade = _mapping(snapshot.get("latestTrade"))
                daily = _mapping(snapshot.get("dailyBar"))
                greeks = _mapping(snapshot.get("greeks"))
                contracts.append(
                    OptionContract(
                        ticker=ticker,
                        contract_symbol=symbol,
                        option_type=option_type,
                        expiration=expiration,
                        dte=(expiration - as_of.astimezone(UTC).date()).days,
                        strike=strike,
                        underlying_price=underlying_price,
                        bid=_optional_float(quote.get("bp")),
                        ask=_optional_float(quote.get("ap")),
                        last=_optional_float(trade.get("p")),
                        volume=_optional_int(daily.get("v")),
                        open_interest=_optional_int(item.get("open_interest")),
                        implied_volatility=_optional_float(
                            snapshot.get("impliedVolatility")
                        ),
                        delta=_optional_float(greeks.get("delta")),
                        gamma=_optional_float(greeks.get("gamma")),
                        theta=_optional_float(greeks.get("theta")),
                        vega=_optional_float(greeks.get("vega")),
                        quote_timestamp=_optional_datetime(quote.get("t")),
                        trade_timestamp=_optional_datetime(trade.get("t")),
                        data_provider=self.name,
                        earnings_date=None,
                        event_data_status=EventDataStatus.UNAVAILABLE,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                label = symbol or f"item-{index}"
                malformed.append(f"{label}: {type(exc).__name__}")
        return contracts, malformed


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and abs(parsed) != float("inf") else None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _resource_error_metadata(
    responses: list[ProviderResponseMetadata],
) -> dict[str, object]:
    latest = responses[-1]
    return {
        "status_code": latest.status_code,
        "request_id": latest.request_id,
        "feed": None,
        "rate_limit_remaining": latest.rate_limit_remaining,
        "rate_limit_reset": latest.rate_limit_reset,
        "response_time_ms": latest.response_time_ms,
        "request_count": len(responses),
    }
