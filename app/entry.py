from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
import math
from zoneinfo import ZoneInfo

import pandas as pd

from app.entry_models import (
    EntryAnchor,
    EntryEvaluation,
    EntryPolicy,
    EntrySetup,
    EntryStatus,
)
from app.indicators import atr, ema

ET = ZoneInfo("America/New_York")


def current_entry(
    plan: EntryEvaluation | None, *, now: datetime | None = None,
    policy: EntryPolicy | None = None, momentum_rsi: float | None = None,
) -> EntryEvaluation:
    now = now or datetime.now(UTC)
    if now.utcoffset() is None:
        raise ValueError("entry evaluation requires a timezone-aware clock")
    if plan is None:
        return EntryEvaluation(
            status=EntryStatus.UNAVAILABLE,
            evaluated_at=now,
            blockers=["No entry plan in this snapshot. Run a new equity scan."],
            next_trigger="Refresh equities to derive a factual entry, stop and target.",
        )
    if (
        (policy is not None and plan.policy != policy)
        or (momentum_rsi is not None and plan.momentum_rsi != momentum_rsi)
    ):
        return plan.model_copy(update={
            "status": EntryStatus.UNAVAILABLE,
            "blockers": ["Entry settings changed; run a new equity scan."],
            "next_trigger": "Refresh the entry plan with the current risk and momentum settings.",
        })
    if plan.price_as_of is None and not plan.ready:
        return plan
    if (
        plan.expires_at is None
        or plan.price_as_of is None
        or not plan.price_as_of <= now <= plan.expires_at
        or now < plan.evaluated_at
    ):
        return plan.model_copy(update={
            "status": EntryStatus.STALE,
            "blockers": ["Entry price is stale or not yet available. Refresh equities."],
            "next_trigger": "Run a new equity scan; old readiness is not a current entry.",
        })
    return plan


def evaluate_levels(
    *,
    anchor: EntryAnchor,
    price: float,
    daily_atr: float,
    intraday_atr: float,
    daily_ema: float,
    daily_trend_confirmed: bool,
    confirmed: bool,
    now: datetime,
    price_as_of: datetime,
    policy: EntryPolicy,
    invalidated: bool = False,
    invalidated_at: datetime | None = None,
    momentum_rsi: float = 50,
    relative_strength_pct: float | None = None,
) -> EntryEvaluation:
    """Evaluate a fixed structural plan; never move levels to manufacture R."""
    values = (price, daily_atr, intraday_atr, daily_ema)
    if not all(math.isfinite(value) and value > 0 for value in values):
        raise ValueError("entry prices and volatility must be finite and positive")
    risk = price - anchor.invalidation_level
    reward = anchor.target_level - price if anchor.target_level is not None else None
    rr = reward / risk if reward is not None and reward > 0 and risk > 0 else None
    noise = policy.min_stop_noise_atr * intraday_atr
    zone_low = max(anchor.reference_level, anchor.invalidation_level + noise)
    caps = [
        anchor.reference_level + policy.max_extension_atr * daily_atr,
        anchor.invalidation_level + policy.max_stop_distance_atr * daily_atr,
        daily_ema + policy.max_daily_ema_extension_atr * daily_atr,
    ]
    if anchor.target_level is not None:
        caps.append(
            (anchor.target_level + policy.min_reward_risk * anchor.invalidation_level)
            / (1 + policy.min_reward_risk)
        )
    zone_high = min(caps)
    extension = (price - anchor.reference_level) / daily_atr
    blockers: list[str] = []
    status = EntryStatus.READY
    if anchor.target_level is None:
        status = EntryStatus.UNAVAILABLE
        blockers.append("No confirmed overhead target; do not invent one to meet the R threshold.")
    if not daily_trend_confirmed:
        status = EntryStatus.WAIT_CONFIRMATION
        blockers.append("Daily trend is not confirmed (close > EMA20 >= EMA50).")
    if not confirmed or price <= anchor.reference_level:
        status = EntryStatus.WAIT_CONFIRMATION
        blockers.append("Wait for distinct completed 15-minute bars to confirm support.")
    if risk > 0 and risk < noise:
        status = EntryStatus.WAIT_CONFIRMATION
        blockers.append("Stop is inside normal 15-minute noise; do not tighten it to inflate R.")
    if extension > policy.max_extension_atr:
        status = EntryStatus.WAIT_PULLBACK
        blockers.append(
            f"Extended {extension:.2f} daily ATR above structure; "
            f"limit {policy.max_extension_atr:.2f}. Wait for a confirmed retest."
        )
    if risk > policy.max_stop_distance_atr * daily_atr:
        status = EntryStatus.WAIT_PULLBACK
        blockers.append("Structural stop is too far away; keep the stop and wait.")
    if price > daily_ema + policy.max_daily_ema_extension_atr * daily_atr:
        status = EntryStatus.WAIT_PULLBACK
        blockers.append("Price is too extended above daily EMA20.")
    if rr is not None and rr < policy.min_reward_risk:
        if status is EntryStatus.READY:
            status = EntryStatus.INSUFFICIENT_REWARD
        blockers.append(f"Reward/risk {rr:.2f}R is below {policy.min_reward_risk:.2f}R.")
    if zone_high < zone_low:
        if status is EntryStatus.READY:
            status = EntryStatus.INSUFFICIENT_REWARD
        blockers.append("No feasible entry zone for this structure, volatility and target.")
    if invalidated or risk <= 0 or (reward is not None and reward <= 0):
        status = EntryStatus.INVALIDATED
        invalidated_at = invalidated_at or price_as_of
        blockers.append("Stop was breached or the original target is reached; require a new setup.")

    expires_at = price_expiry(price_as_of, policy)
    plan = EntryEvaluation(
        status=status,
        evaluated_at=now,
        price_as_of=price_as_of,
        expires_at=expires_at,
        invalidated_at=invalidated_at,
        entry_price=price,
        anchor=anchor,
        entry_zone_low=zone_low if zone_high >= zone_low else None,
        entry_zone_high=zone_high if zone_high >= zone_low else None,
        risk_per_share=risk if risk > 0 else None,
        reward_per_share=reward if reward is not None and reward > 0 else None,
        reward_risk=rr,
        daily_atr=daily_atr,
        intraday_atr=intraday_atr,
        extension_atr=extension,
        daily_trend_confirmed=daily_trend_confirmed,
        bar_confirmation=confirmed,
        relative_strength_pct=relative_strength_pct,
        momentum_rsi=momentum_rsi,
        policy=policy,
        blockers=blockers,
        next_trigger=(
            "Structure/price gates passed. Require RSI, benchmark and leader readiness; "
            "verify an executable quote and assess option premium/IV separately. Not an order."
            if not blockers else
            "Wait for a confirmed retest inside the entry zone, or a new base; "
            "keep the structural stop and target unchanged."
        ),
    )
    return current_entry(plan, now=now)


def _bars(frame: pd.DataFrame, now: datetime, *, intraday: bool) -> pd.DataFrame:
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp")
    local = frame["timestamp"].dt.tz_convert(ET)
    if intraday:
        mask = (
            (frame["timestamp"] + pd.Timedelta(minutes=15) <= now)
            & (local.dt.time >= time(9, 30))
            & (local.dt.time < time(16))
            & (local.dt.weekday < 5)
        )
    else:
        # Conservatively exclude the current session, including its unfinished bar.
        mask = local.dt.date < now.astimezone(ET).date()
    return frame.loc[mask].reset_index(drop=True)


def price_expiry(price_as_of: datetime, policy: EntryPolicy) -> datetime:
    close_et = datetime.combine(price_as_of.astimezone(ET).date(), time(16), ET)
    return min(
        price_as_of + timedelta(minutes=policy.max_bar_age_minutes),
        close_et - timedelta(microseconds=1),
    )


def completed_price_time(frame: pd.DataFrame, now: datetime) -> datetime | None:
    bars = _bars(frame, now, intraday=True)
    if bars.empty:
        return None
    return (bars["timestamp"].iloc[-1] + pd.Timedelta(minutes=15)).to_pydatetime()


def _pivot_levels(frame: pd.DataFrame, column: str, *, high: bool) -> list[float]:
    series = frame[column].astype(float)
    result = []
    for index in range(2, len(series) - 2):
        window = series.iloc[index - 2:index + 3]
        value = series.iloc[index]
        extremum = window.max() if high else window.min()
        if value == extremum and int((window == value).sum()) == 1:
            result.append(float(value))
    return result


def _relative_strength(daily: pd.DataFrame, benchmarks: list[pd.DataFrame]) -> float | None:
    def closes(frame: pd.DataFrame) -> pd.Series:
        dates = frame["timestamp"].dt.tz_convert(ET).dt.date
        return pd.Series(frame["close"].to_numpy(), index=dates)

    if not benchmarks:
        return None
    stock = closes(daily)
    spreads = []
    for benchmark in benchmarks:
        joined = pd.concat([stock, closes(benchmark)], axis=1, join="inner").dropna()
        if len(joined) < 21:
            return None
        window = joined.tail(21)
        returns = (window.iloc[-1] / window.iloc[0] - 1) * 100
        spreads.append(float(returns.iloc[0] - returns.iloc[1]))
    return min(spreads)


def _ohlc_problem(frame: pd.DataFrame) -> str | None:
    for column in ("open", "high", "low", "close"):
        if not frame[column].map(lambda x: math.isfinite(x) and x > 0).all():
            return "Non-finite or non-positive OHLC data; entry is unavailable."
    if (
        (frame["high"] < frame[["open", "low", "close"]].max(axis=1)).any()
        or (frame["low"] > frame[["open", "high", "close"]].min(axis=1)).any()
    ):
        return "Inconsistent OHLC bounds; entry is unavailable."
    return None


def build_entry_plan(
    intraday: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    policy: EntryPolicy,
    now: datetime,
    previous: EntryEvaluation | None = None,
    benchmarks: list[pd.DataFrame] | None = None,
    momentum_rsi: float = 50,
) -> EntryEvaluation:
    if now.utcoffset() is None:
        raise ValueError("entry evaluation requires a timezone-aware clock")
    price: float | None = None
    price_as_of: datetime | None = None

    def unavailable(reason: str, status: EntryStatus = EntryStatus.UNAVAILABLE):
        plan = EntryEvaluation(
            status=status, evaluated_at=now, policy=policy,
            entry_price=price, price_as_of=price_as_of,
            expires_at=price_expiry(price_as_of, policy) if price_as_of is not None else None,
            invalidated_at=previous.invalidated_at if previous else None,
            momentum_rsi=momentum_rsi, blockers=[reason],
            next_trigger="Wait for sufficient completed bars and a confirmed structural setup.",
        )
        return current_entry(plan, now=now)

    required = {"timestamp", "open", "high", "low", "close"}
    if not required.issubset(intraday.columns):
        return unavailable("OHLC timestamps are missing; entry cannot be evaluated.")
    bars = _bars(intraday, now, intraday=True)
    problem = _ohlc_problem(bars)
    if problem:
        return unavailable(problem)
    if bars.empty:
        return unavailable("No completed regular-session intraday bars are available.")
    price = float(bars["close"].iloc[-1])
    price_as_of = (bars["timestamp"].iloc[-1] + pd.Timedelta(minutes=15)).to_pydatetime()
    if not required.issubset(daily.columns):
        return unavailable("Daily OHLC timestamps are missing; entry cannot be evaluated.")
    days = _bars(daily, now, intraday=False)
    problem = _ohlc_problem(days)
    if problem:
        return unavailable(problem)
    count = policy.confirmation_bars
    if len(bars) < policy.consolidation_bars + count or len(days) < 50:
        return unavailable("Need a full intraday base and at least 50 completed daily bars.")
    if now.astimezone(ET).date() - days["timestamp"].iloc[-1].astimezone(ET).date() > timedelta(days=7):
        return unavailable("Daily trend data is stale; refresh the daily history.")
    atr_day = float(atr(days).iloc[-1])
    atr_15m = float(atr(bars).iloc[-1])
    if min(atr_day, atr_15m) <= 0:
        return unavailable("Zero volatility cannot define a risk distance.")
    ema20 = float(ema(days["close"], 20).iloc[-1])
    ema50 = float(ema(days["close"], 50).iloc[-1])
    trend = float(days["close"].iloc[-1]) > ema20 >= ema50 and price > ema20
    confirmations = bars.tail(count)
    consecutive = (
        confirmations["timestamp"].diff().iloc[1:] == pd.Timedelta(minutes=15)
    ).all()
    same_session = (
        confirmations["timestamp"].dt.tz_convert(ET).dt.date.nunique() == 1
    )
    reset_after = previous.invalidated_at if previous is not None else None
    anchor = previous.anchor if previous is not None and reset_after is None else None
    if anchor is not None and (
        now < anchor.formed_at
        or now - anchor.formed_at > timedelta(days=policy.max_setup_age_days)
        or previous.status is EntryStatus.INVALIDATED
    ):
        anchor = None
    confirmed = False
    invalidated = False
    invalidated_at = None
    if anchor is not None:
        if bars["timestamp"].iloc[0] > anchor.formed_at:
            return unavailable(
                "History does not cover the anchored setup; cannot verify intervening stop breaches."
            ).model_copy(update={"anchor": anchor})
        since = bars.loc[bars["timestamp"] + pd.Timedelta(minutes=15) > anchor.formed_at]
        breaches = since["low"] <= anchor.invalidation_level
        if anchor.target_level is not None:
            breaches |= since["high"] >= anchor.target_level
        invalidated = bool(breaches.any())
        if invalidated:
            invalidated_at = (
                since.loc[breaches, "timestamp"].iloc[0] + pd.Timedelta(minutes=15)
            ).to_pydatetime()
        confirmed = bool(consecutive and same_session and (
            confirmations["close"] > anchor.reference_level
        ).all())
        retest = bars.iloc[-count - 1]
        if (
            confirmed and retest["timestamp"] >= anchor.formed_at
            and retest["low"] <= anchor.reference_level + policy.retest_tolerance_atr * atr_day
            and retest["low"] > anchor.invalidation_level
            and price > float(retest["close"])
            and anchor.setup_type is EntrySetup.BREAKOUT
        ):
            anchor = anchor.model_copy(update={"setup_type": EntrySetup.BREAKOUT_RETEST})
    else:
        base = bars.iloc[:-count].tail(policy.consolidation_bars)
        high, low = float(base["high"].max()), float(base["low"].min())
        previous_close = float(base["close"].iloc[-1])
        balanced_base = (
            high - low <= policy.max_base_width_atr * atr_day
            and abs(previous_close - float(base["close"].iloc[0])) <= policy.max_base_drift_atr * atr_day
        )
        setup = None
        reference = high
        stop = low - policy.stop_buffer_atr * atr_15m
        source = "Completed pre-breakout consolidation high / low"
        if balanced_base and previous_close <= high and (confirmations["close"] > high).all():
            setup = EntrySetup.BREAKOUT
        else:
            pivots = _pivot_levels(base, "low", high=False)
            if pivots:
                reference = pivots[-1]
                if previous_close <= reference and (confirmations["close"] > reference).all():
                    setup = EntrySetup.SUPPORT_RECLAIM
                    stop = float(bars.tail(count + 1)["low"].min()) - policy.stop_buffer_atr * atr_15m
                    source = "Confirmed pre-reclaim local pivot low / pullback low"
        if setup is not None and consecutive and same_session and stop > 0:
            if (
                reset_after is not None and base["timestamp"].iloc[0] < reset_after
            ):
                return unavailable("Old setup invalidated; wait for a genuinely new base.", EntryStatus.INVALIDATED)
            targets = [level for level in _pivot_levels(days, "high", high=True) if level > reference]
            anchor = EntryAnchor(
                setup_type=setup,
                formed_at=price_as_of,
                reference_level=reference,
                invalidation_level=stop,
                target_level=min(targets) if targets else None,
                reference_source=source,
            )
            confirmed = True
            invalidated = bool(
                (confirmations["low"] <= stop).any()
                or (anchor.target_level is not None and (confirmations["high"] >= anchor.target_level).any())
            )
    if anchor is None:
        return unavailable(
            "No confirmed low-extension breakout or support reclaim. Trend alone is not an entry.",
            EntryStatus.INVALIDATED if reset_after else EntryStatus.WAIT_CONFIRMATION,
        )
    return evaluate_levels(
        anchor=anchor, price=price, daily_atr=atr_day, intraday_atr=atr_15m,
        daily_ema=ema20, daily_trend_confirmed=trend, confirmed=confirmed,
        now=now, price_as_of=price_as_of, policy=policy, invalidated=invalidated,
        invalidated_at=invalidated_at,
        momentum_rsi=momentum_rsi,
        relative_strength_pct=_relative_strength(
            days, [_bars(frame, now, intraday=False) for frame in benchmarks or []]
        ),
    )
