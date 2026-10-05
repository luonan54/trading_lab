from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
import pandas as pd

LOGGER = logging.getLogger(__name__)


class MarketDataError(RuntimeError):
    def __init__(self, message: str, *, request_id: str | None = None) -> None:
        suffix = f" (request_id={request_id})" if request_id else ""
        super().__init__(f"{message}{suffix}")
        self.request_id = request_id


class MissingAlpacaCredentialsError(MarketDataError):
    pass


class AlpacaMarketDataClient:
    BASE_URL = "https://data.alpaca.markets"

    def __init__(
        self,
        api_key: str | None,
        api_secret: str | None,
        *,
        feed: str = "iex",
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.feed = feed
        self.timeout = timeout
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        if not self.api_key or not self.api_secret:
            raise MissingAlpacaCredentialsError(
                "Alpaca credentials are missing; set ALPACA_API_KEY and "
                "ALPACA_API_SECRET"
            )
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
        }

    def fetch_bars(
        self,
        symbols: list[str],
        timeframe: str,
        *,
        start: datetime,
        end: datetime,
    ) -> dict[str, pd.DataFrame]:
        all_bars: dict[str, list[dict]] = {symbol: [] for symbol in symbols}
        params: dict[str, str | int] = {
            "symbols": ",".join(symbols),
            "timeframe": timeframe,
            "start": start.astimezone(UTC).isoformat(),
            "end": end.astimezone(UTC).isoformat(),
            "limit": 10000,
            "adjustment": "raw",
            "feed": self.feed,
            "sort": "asc",
        }

        with httpx.Client(
            base_url=self.BASE_URL,
            headers=self._headers(),
            timeout=self.timeout,
            transport=self.transport,
        ) as client:
            while True:
                try:
                    response = client.get("/v2/stocks/bars", params=params)
                except httpx.HTTPError as exc:
                    raise MarketDataError(f"Alpaca request failed: {exc}") from exc

                request_id = response.headers.get("x-request-id") or response.headers.get(
                    "apca-request-id"
                )
                if response.is_error:
                    detail = response.text[:500]
                    LOGGER.error(
                        "Alpaca request failed status=%s request_id=%s detail=%s",
                        response.status_code,
                        request_id,
                        detail,
                    )
                    raise MarketDataError(
                        f"Alpaca returned HTTP {response.status_code}: {detail}",
                        request_id=request_id,
                    )

                payload = response.json()
                for symbol, bars in payload.get("bars", {}).items():
                    all_bars.setdefault(symbol, []).extend(bars)
                token = payload.get("next_page_token")
                if not token:
                    break
                params["page_token"] = token

        return {
            symbol: self._to_frame(bars, timeframe)
            for symbol, bars in all_bars.items()
        }

    @staticmethod
    def _to_frame(bars: list[dict], timeframe: str) -> pd.DataFrame:
        columns = ["timestamp", "open", "high", "low", "close", "volume", "vwap"]
        if not bars:
            return pd.DataFrame(columns=columns)
        frame = pd.DataFrame(
            {
                "timestamp": [item["t"] for item in bars],
                "open": [item["o"] for item in bars],
                "high": [item["h"] for item in bars],
                "low": [item["l"] for item in bars],
                "close": [item["c"] for item in bars],
                "volume": [item["v"] for item in bars],
                "vwap": [item.get("vw") for item in bars],
            }
        )
        frame["timestamp"] = pd.to_datetime(
            frame["timestamp"], utc=True, format="mixed"
        )
        now = pd.Timestamp.now(tz="UTC")
        if timeframe == "15Min":
            completed_before = now.floor("15min")
        else:
            completed_before = now.normalize()
        return (
            frame.loc[frame["timestamp"] < completed_before]
            .drop_duplicates("timestamp")
            .sort_values("timestamp")
            .reset_index(drop=True)
        )

    def fetch_analysis_bars(
        self,
        symbols: list[str],
        *,
        intraday_lookback_days: int,
        daily_lookback_days: int,
        now: datetime | None = None,
    ) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
        end = now or datetime.now(UTC)
        intraday = self.fetch_bars(
            symbols,
            "15Min",
            start=end - timedelta(days=intraday_lookback_days),
            end=end,
        )
        daily = self.fetch_bars(
            symbols,
            "1Day",
            start=end - timedelta(days=daily_lookback_days),
            end=end,
        )
        return intraday, daily
