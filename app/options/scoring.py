from __future__ import annotations

from app.config import CombinedScoreConfig, LongCallConfig, OptionsConfig
from app.options.models import (
    DataQualityFlag,
    OptionContract,
    OptionsScoreBreakdown,
    ScoredOptionCandidate,
)
from app.options.quality import ordered_unique

_SCORE_DIGITS = 4


def _rounded(value: float, *, upper: float = 2.0) -> float:
    return round(max(0.0, min(upper, value)), _SCORE_DIGITS)


def _plateau_taper(
    value: float,
    *,
    absolute_min: float,
    preferred_min: float,
    preferred_max: float,
    absolute_max: float,
) -> float:
    if preferred_min <= value <= preferred_max:
        return 2.0
    if value <= absolute_min or value >= absolute_max:
        return 0.0
    if value < preferred_min:
        return 2.0 * (value - absolute_min) / (
            preferred_min - absolute_min
        )
    return 2.0 * (absolute_max - value) / (
        absolute_max - preferred_max
    )


def _delta_score(contract: OptionContract, config: LongCallConfig) -> float:
    if contract.delta is None:
        return 1.0
    return _rounded(
        _plateau_taper(
            contract.delta,
            absolute_min=config.absolute_delta_min,
            preferred_min=config.preferred_delta_min,
            preferred_max=config.preferred_delta_max,
            absolute_max=config.absolute_delta_max,
        )
    )


def _dte_score(contract: OptionContract, config: LongCallConfig) -> float:
    if not config.min_dte <= contract.dte <= config.max_dte:
        raise ValueError("only contracts inside the filtered DTE range can be scored")
    return _rounded(
        _plateau_taper(
            float(contract.dte),
            absolute_min=float(config.min_dte),
            preferred_min=float(config.preferred_dte_min),
            preferred_max=float(config.preferred_dte_max),
            absolute_max=float(config.max_dte),
        )
    )


def _threshold_score(value: int, threshold: int) -> float:
    if threshold == 0:
        return 2.0
    cap = threshold * 2
    return _rounded(1.0 + min(max(value - threshold, 0), threshold) / threshold)


def _spread_score(contract: OptionContract, config: LongCallConfig) -> float:
    spread_pct = contract.spread_pct
    if spread_pct is None and (
        contract.bid is not None
        and contract.ask is not None
        and contract.bid > 0
        and contract.ask >= contract.bid
    ):
        mid = (contract.bid + contract.ask) / 2
        spread_pct = (contract.ask - contract.bid) / mid
    if spread_pct is None:
        return 1.0
    if config.max_spread_pct == 0:
        return 2.0 if spread_pct == 0 else 0.0
    return _rounded(2.0 * (1.0 - spread_pct / config.max_spread_pct))


def _liquidity_score(
    contract: OptionContract, config: LongCallConfig
) -> tuple[float, str]:
    spread = _spread_score(contract, config)
    open_interest = (
        1.0
        if contract.open_interest is None
        else _threshold_score(contract.open_interest, config.min_open_interest)
    )
    volume = (
        1.0
        if contract.volume is None
        else _threshold_score(contract.volume, config.min_volume)
    )
    score = _rounded(0.50 * spread + 0.30 * open_interest + 0.20 * volume)
    explanation = (
        "Liquidity uses spread 50%, open interest 30%, and volume 20%: "
        f"{spread:.4f}, {open_interest:.4f}, {volume:.4f}; count metrics "
        "reach their caps at twice the configured minimum."
    )
    return score, explanation


def _iv_score(contract: OptionContract) -> float:
    percentile = contract.chain_relative_iv_percentile
    if percentile is None:
        return 1.0
    if not 0 <= percentile <= 1:
        raise ValueError("chain_relative_iv_percentile must be between 0 and 1")
    if percentile <= 0.50:
        return 2.0
    return _rounded(4.0 * (1.0 - percentile))


def _moneyness_value(contract: OptionContract) -> float:
    if contract.moneyness_pct is not None:
        return contract.moneyness_pct
    if contract.underlying_price <= 0:
        raise ValueError("underlying price must be positive to score moneyness")
    return (
        contract.underlying_price - contract.strike
    ) / contract.underlying_price


def _moneyness_score(contract: OptionContract, config: LongCallConfig) -> float:
    moneyness = _moneyness_value(contract)
    if moneyness < -config.max_otm_pct:
        raise ValueError("contracts rejected as too far OTM cannot be scored")
    if moneyness < 0:
        if config.max_otm_pct == 0:
            return 0.0
        return _rounded(2.0 * (1.0 + moneyness / config.max_otm_pct))
    if moneyness <= 0.05:
        return 2.0
    return _rounded(2.0 * (0.30 - moneyness) / 0.25)


def _confidence(
    contract: OptionContract,
) -> tuple[float, list[str]]:
    penalties: list[tuple[float, str]] = []
    has_usable_spread = contract.spread_pct is not None or (
        contract.bid is not None
        and contract.ask is not None
        and contract.bid > 0
        and contract.ask >= contract.bid
    )
    if not has_usable_spread:
        penalties.append((0.15, "missing bid/ask spread (significant)"))
    if contract.delta is None:
        penalties.append((0.25, "missing delta (significant)"))
    if contract.open_interest is None:
        penalties.append((0.20, "missing open interest (significant)"))
    if contract.chain_relative_iv_percentile is None:
        penalties.append(
            (0.12, "missing or insufficient chain-relative IV sample (moderate)")
        )
    if contract.volume is None:
        penalties.append((0.10, "missing volume (moderate)"))

    for greek in ("gamma", "theta", "vega"):
        if getattr(contract, greek) is None:
            penalties.append((0.02, f"missing {greek} (small)"))

    flags = set(contract.data_quality_flags)
    if (
        contract.quote_timestamp is None
        or DataQualityFlag.MISSING_QUOTE_TIMESTAMP in flags
    ):
        penalties.append((0.10, "missing or unageable quote timestamp"))
    elif DataQualityFlag.STALE_QUOTE in flags:
        penalties.append((0.10, "stale quote timestamp"))

    explanations = [
        f"-{amount:.2f}: {reason}" for amount, reason in penalties
    ]
    return _rounded(
        1.0 - sum(amount for amount, _ in penalties), upper=1.0
    ), explanations


def score_option_candidate(
    contract: OptionContract,
    equity_score: float,
    config: OptionsConfig | LongCallConfig,
    combined_config: CombinedScoreConfig | None = None,
) -> ScoredOptionCandidate:
    """Score one Phase-1-accepted contract without mutating its market data."""

    if not 0 <= equity_score <= 10:
        raise ValueError("equity_score must be between 0 and 10")
    if isinstance(config, OptionsConfig):
        long_call = config.long_call
        weights = config.combined_score
    else:
        long_call = config
        weights = combined_config or CombinedScoreConfig()

    delta_fit = _delta_score(contract, long_call)
    dte_fit = _dte_score(contract, long_call)
    liquidity, liquidity_reason = _liquidity_score(contract, long_call)
    iv_quality = _iv_score(contract)
    moneyness = _moneyness_score(contract, long_call)
    breakdown = OptionsScoreBreakdown(
        delta_fit=delta_fit,
        dte_fit=dte_fit,
        liquidity=liquidity,
        iv_quality=iv_quality,
        moneyness=moneyness,
    )
    confidence, penalties = _confidence(contract)

    percentile = contract.chain_relative_iv_percentile
    warnings = list(contract.warnings)
    if (
        percentile is not None
        and percentile >= long_call.high_relative_iv_percentile
    ):
        warnings = ordered_unique(
            warnings,
            "High chain-relative IV percentile reduced IV quality; "
            "this is not a historical IV percentile.",
        )
    reasons = [
        f"Delta fit component: {delta_fit:.4f}/2",
        f"DTE fit component: {dte_fit:.4f}/2",
        liquidity_reason,
        (
            "IV quality uses only chain-relative IV percentile: "
            f"{iv_quality:.4f}/2"
        ),
        f"Moneyness component: {moneyness:.4f}/2",
        (
            "Confidence is a data-trust/completeness measure, not a "
            "probability."
        ),
    ]
    options_score = breakdown.total
    combined_score = round(
        weights.equity_weight * equity_score
        + weights.options_weight * options_score,
        _SCORE_DIGITS,
    )
    return ScoredOptionCandidate(
        contract=contract,
        breakdown=breakdown,
        options_quality_score=options_score,
        options_score_confidence=confidence,
        combined_score=combined_score,
        reasons=reasons,
        warnings=warnings,
        confidence_penalties=penalties,
    )


score_option_contract = score_option_candidate
