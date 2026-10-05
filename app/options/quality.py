from __future__ import annotations

from datetime import datetime

from app.config import LongCallConfig
from app.options.models import DataQualityFlag, OptionContract, OptionType


def ordered_unique[T](values: list[T], *new_values: T) -> list[T]:
    result = list(values)
    for value in new_values:
        if value not in result:
            result.append(value)
    return result


def normalize_contract_quality(
    contract: OptionContract,
    config: LongCallConfig,
    *,
    as_of: datetime,
) -> OptionContract:
    """Calculate deterministic derived fields and attach data-quality flags."""

    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")

    flags = ordered_unique([], *contract.data_quality_flags)
    warnings = ordered_unique([], *contract.warnings)
    rejection_reasons = ordered_unique([], *contract.rejection_reasons)
    dte = (contract.expiration - as_of.date()).days

    if dte < 0:
        flags = ordered_unique(flags, DataQualityFlag.INVALID_DTE)
    if contract.underlying_price <= 0:
        flags = ordered_unique(
            flags, DataQualityFlag.INVALID_UNDERLYING_PRICE
        )
    if contract.strike <= 0:
        flags = ordered_unique(flags, DataQualityFlag.INVALID_STRIKE)

    bid = contract.bid
    ask = contract.ask
    mid = spread_abs = spread_pct = None
    if bid is None or ask is None:
        flags = ordered_unique(flags, DataQualityFlag.MISSING_QUOTE)
        warnings = ordered_unique(warnings, "Bid/ask quote is unavailable")
    else:
        if bid < 0:
            flags = ordered_unique(flags, DataQualityFlag.INVALID_BID)
        if bid == 0:
            flags = ordered_unique(flags, DataQualityFlag.ZERO_BID)
        if ask <= 0:
            flags = ordered_unique(flags, DataQualityFlag.INVALID_ASK)
        if ask < bid:
            flags = ordered_unique(flags, DataQualityFlag.CROSSED_MARKET)
        if bid > 0 and ask >= bid:
            mid = (bid + ask) / 2
            spread_abs = ask - bid
            spread_pct = spread_abs / mid
            if spread_pct > config.max_spread_pct:
                flags = ordered_unique(flags, DataQualityFlag.WIDE_SPREAD)

    if contract.quote_timestamp is None:
        flags = ordered_unique(
            flags, DataQualityFlag.MISSING_QUOTE_TIMESTAMP
        )
        warnings = ordered_unique(warnings, "Quote timestamp is unavailable")
    elif contract.quote_timestamp.tzinfo is None:
        flags = ordered_unique(
            flags, DataQualityFlag.MISSING_QUOTE_TIMESTAMP
        )
        warnings = ordered_unique(
            warnings, "Quote timestamp has no timezone and cannot be aged"
        )
    else:
        quote_age_minutes = (
            as_of - contract.quote_timestamp
        ).total_seconds() / 60
        if quote_age_minutes > config.stale_quote_minutes:
            flags = ordered_unique(flags, DataQualityFlag.STALE_QUOTE)
            warnings = ordered_unique(
                warnings,
                f"Quote is older than {config.stale_quote_minutes} minutes",
            )

    missing_greeks = [
        name
        for name in ("delta", "gamma", "theta", "vega")
        if getattr(contract, name) is None
    ]
    if missing_greeks:
        flags = ordered_unique(flags, DataQualityFlag.MISSING_GREEKS)
        warnings = ordered_unique(
            warnings, f"Missing Greeks: {', '.join(missing_greeks)}"
        )
    if contract.implied_volatility is None:
        flags = ordered_unique(flags, DataQualityFlag.MISSING_IV)
        warnings = ordered_unique(warnings, "Implied volatility is unavailable")
    elif contract.implied_volatility < 0:
        flags = ordered_unique(flags, DataQualityFlag.INVALID_IV)

    if contract.open_interest is None:
        flags = ordered_unique(flags, DataQualityFlag.MISSING_OPEN_INTEREST)
    elif contract.open_interest < 0:
        flags = ordered_unique(flags, DataQualityFlag.INVALID_OPEN_INTEREST)
    if contract.volume is None:
        flags = ordered_unique(flags, DataQualityFlag.MISSING_VOLUME)
    elif contract.volume < 0:
        flags = ordered_unique(flags, DataQualityFlag.INVALID_VOLUME)

    moneyness_pct = intrinsic_value = extrinsic_value = breakeven = None
    if contract.underlying_price > 0 and contract.strike > 0:
        moneyness_pct = (
            contract.underlying_price - contract.strike
        ) / contract.underlying_price
        if contract.option_type is OptionType.CALL:
            intrinsic_value = max(
                contract.underlying_price - contract.strike, 0
            )
        else:
            intrinsic_value = max(
                contract.strike - contract.underlying_price, 0
            )
        premium = mid
        if premium is None and contract.last is not None and contract.last >= 0:
            premium = contract.last
        if premium is not None:
            extrinsic_value = premium - intrinsic_value
            breakeven = (
                contract.strike + premium
                if contract.option_type is OptionType.CALL
                else contract.strike - premium
            )

    return contract.model_copy(
        update={
            "dte": dte,
            "mid": mid,
            "spread_abs": spread_abs,
            "spread_pct": spread_pct,
            "moneyness_pct": moneyness_pct,
            "intrinsic_value": intrinsic_value,
            "extrinsic_value": extrinsic_value,
            "breakeven_at_expiration": breakeven,
            "data_quality_flags": flags,
            "warnings": warnings,
            "rejection_reasons": rejection_reasons,
        }
    )
