from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
import math
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.models import TechnicalFeatures

ET = ZoneInfo("America/New_York")


class InsufficientMarketDataError(ValueError):
    pass


@dataclass(frozen=True)
class MarketSessionValues:
    previous_close: float | None
    session_open: float | None
    session_date: date | None
    today_return_pct: float | None


def _finite_positive(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def derive_market_session_values(
    intraday: pd.DataFrame,
    daily: pd.DataFrame,
) -> MarketSessionValues:
    """Derive current-session values from completed Alpaca bars only."""

    unavailable = MarketSessionValues(None, None, None, None)
    if (
        intraday.empty
        or "timestamp" not in intraday
        or "open" not in intraday
        or "close" not in intraday
    ):
        return unavailable

    intraday = intraday.copy().sort_values("timestamp").reset_index(drop=True)
    local_timestamps = pd.to_datetime(
        intraday["timestamp"], utc=True, format="mixed"
    ).dt.tz_convert(ET)
    latest_date = local_timestamps.iloc[-1].date()
    local_times = local_timestamps.dt.time
    regular_session = intraday.loc[
        (local_timestamps.dt.date == latest_date)
        & (local_times >= time(9, 30))
        & (local_times < time(16))
    ]
    if regular_session.empty:
        return unavailable

    session_open = _finite_positive(regular_session.iloc[0]["open"])
    if (
        session_open is None
        or daily.empty
        or "timestamp" not in daily
        or "close" not in daily
    ):
        return MarketSessionValues(None, session_open, latest_date, None)

    daily = daily.copy().sort_values("timestamp").reset_index(drop=True)
    daily_dates = pd.to_datetime(
        daily["timestamp"], utc=True, format="mixed"
    ).dt.tz_convert(ET).dt.date
    prior_sessions = daily.loc[daily_dates < latest_date]
    if prior_sessions.empty:
        return MarketSessionValues(None, session_open, latest_date, None)

    previous_close = _finite_positive(prior_sessions.iloc[-1]["close"])
    current_price = _finite_positive(intraday.iloc[-1]["close"])
    today_return_pct = (
        (current_price / previous_close - 1) * 100
        if current_price is not None and previous_close is not None
        else None
    )
    return MarketSessionValues(
        previous_close=previous_close,
        session_open=session_open,
        session_date=latest_date,
        today_return_pct=today_return_pct,
    )


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.astype(float).ewm(span=span, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.astype(float).diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)
    average_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    average_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    relative_strength = average_gain / average_loss.replace(0, np.nan)
    result = 100 - (100 / (1 + relative_strength))
    result = result.where(average_loss != 0, 100.0)
    return result.where(average_gain != 0, 0.0)


def macd(series: pd.Series) -> tuple[pd.Series, pd.Series]:
    line = ema(series, 12) - ema(series, 26)
    return line, ema(line, 9)


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous_close).abs(),
            (frame["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def detect_low_structure(
    daily: pd.DataFrame,
    *,
    swing_window: int,
    tolerance_pct: float,
) -> tuple[bool, bool]:
    required = swing_window * 2
    if len(daily) < required:
        return False, False
    previous_low = float(daily["low"].iloc[-required:-swing_window].min())
    recent_low = float(daily["low"].iloc[-swing_window:].min())
    tolerance = tolerance_pct / 100
    return (
        recent_low > previous_low * (1 + tolerance),
        recent_low < previous_low * (1 - tolerance),
    )


def calculate_features(
    intraday: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    swing_window: int = 3,
    support_resistance_window: int = 20,
    local_structure_window: int = 20,
    local_pivot_span: int = 2,
    structure_tolerance_pct: float = 0.2,
) -> TechnicalFeatures:
    if len(intraday) < 30:
        raise InsufficientMarketDataError("At least 30 completed 15-minute bars are required")
    if len(daily) < max(30, support_resistance_window + 1):
        raise InsufficientMarketDataError("At least 30 completed daily bars are required")

    intraday = intraday.copy().sort_values("timestamp").reset_index(drop=True)
    daily = daily.copy().sort_values("timestamp").reset_index(drop=True)
    close_15m = intraday["close"].astype(float)
    daily_close = daily["close"].astype(float)
    ema9_series = ema(close_15m, 9)
    ema20_series = ema(close_15m, 20)
    rsi_series = rsi(close_15m, 14)
    macd_line, macd_signal = macd(close_15m)
    atr_series = atr(daily, 14)

    prior_daily = daily.iloc[-support_resistance_window:]
    major_swing_support = float(prior_daily["low"].min())
    major_swing_resistance = float(prior_daily["high"].max())
    current_price = float(close_15m.iloc[-1])

    confirmation_history = intraday.iloc[:-2].tail(local_structure_window)
    if len(confirmation_history) < local_pivot_span * 2 + 1:
        raise InsufficientMarketDataError(
            "Insufficient completed 15-minute bars for local structure"
        )
    local_highs = confirmation_history["high"].astype(float).reset_index(drop=True)
    local_lows = confirmation_history["low"].astype(float).reset_index(drop=True)
    pivot_highs: list[float] = []
    pivot_lows: list[float] = []
    for index in range(local_pivot_span, len(confirmation_history) - local_pivot_span):
        high_window = local_highs.iloc[
            index - local_pivot_span : index + local_pivot_span + 1
        ]
        low_window = local_lows.iloc[
            index - local_pivot_span : index + local_pivot_span + 1
        ]
        if (
            local_highs.iloc[index] == high_window.max()
            and int((high_window == local_highs.iloc[index]).sum()) == 1
        ):
            pivot_highs.append(float(local_highs.iloc[index]))
        if (
            local_lows.iloc[index] == low_window.min()
            and int((low_window == local_lows.iloc[index]).sum()) == 1
        ):
            pivot_lows.append(float(local_lows.iloc[index]))
    local_resistance = (
        pivot_highs[-1] if pivot_highs else float(local_highs.max())
    )
    local_support = pivot_lows[-1] if pivot_lows else float(local_lows.min())

    local_dates = intraday["timestamp"].dt.tz_convert(ET).dt.date
    latest_session = intraday.loc[local_dates == local_dates.iloc[-1]]
    typical_price = (
        latest_session["high"] + latest_session["low"] + latest_session["close"]
    ) / 3
    volume = latest_session["volume"].astype(float)
    session_vwap = float((typical_price * volume).sum() / volume.sum())

    higher_low, lower_low = detect_low_structure(
        daily,
        swing_window=swing_window,
        tolerance_pct=structure_tolerance_pct,
    )
    last_three_closes = close_15m.iloc[-3:]
    two_bar_acceptance = bool(
        last_three_closes.iloc[-2:].gt(local_resistance).all()
        and last_three_closes.iloc[0] <= local_resistance
    )
    two_bar_reclaim = bool(
        last_three_closes.iloc[-2:].gt(local_support).all()
        and last_three_closes.iloc[0] <= local_support
    )

    recent_high = float(daily["high"].iloc[-support_resistance_window:].max())
    session_values = derive_market_session_values(intraday, daily)
    return TechnicalFeatures(
        current_price=current_price,
        daily_return_pct=float((daily_close.iloc[-1] / daily_close.iloc[-2] - 1) * 100),
        return_15m_pct=float((close_15m.iloc[-1] / close_15m.iloc[-2] - 1) * 100),
        previous_close=session_values.previous_close,
        session_open=session_values.session_open,
        session_date=session_values.session_date,
        today_return_pct=session_values.today_return_pct,
        vwap=session_vwap,
        ema9=float(ema9_series.iloc[-1]),
        ema20=float(ema20_series.iloc[-1]),
        rsi14=float(rsi_series.iloc[-1]),
        macd=float(macd_line.iloc[-1]),
        macd_signal=float(macd_signal.iloc[-1]),
        atr14=float(atr_series.iloc[-1]),
        support=major_swing_support,
        resistance=major_swing_resistance,
        local_support=local_support,
        local_resistance=local_resistance,
        major_swing_support=major_swing_support,
        major_swing_resistance=major_swing_resistance,
        drawdown_pct=float((current_price / recent_high - 1) * 100),
        higher_low=higher_low,
        lower_low=lower_low,
        two_bar_acceptance=two_bar_acceptance,
        two_bar_reclaim=two_bar_reclaim,
    )
