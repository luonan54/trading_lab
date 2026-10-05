from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from app.config import LongCallConfig, PolicyAction
from app.options.events import attach_event_risk
from app.options.models import (
    ContractFilterStatus,
    DataQualityFlag,
    DeltaRangeStatus,
    FilterStageCount,
    MoneynessStatus,
    OptionContract,
    OptionFilterResult,
    OptionType,
)
from app.options.quality import normalize_contract_quality, ordered_unique

StageEvaluator = Callable[
    [OptionContract], tuple[OptionContract, list[str]]
]


def _with_rejection_reasons(
    contract: OptionContract, reasons: list[str]
) -> OptionContract:
    return contract.model_copy(
        update={
            "filter_status": ContractFilterStatus.REJECTED,
            "rejection_reasons": ordered_unique(
                contract.rejection_reasons, *reasons
            ),
        }
    )


def _run_stage(
    stage: str,
    active: list[OptionContract],
    rejected: list[OptionContract],
    evaluator: StageEvaluator,
) -> tuple[list[OptionContract], list[OptionContract], FilterStageCount]:
    passed: list[OptionContract] = []
    newly_rejected = 0
    for contract in active:
        updated, reasons = evaluator(contract)
        if reasons:
            rejected.append(_with_rejection_reasons(updated, reasons))
            newly_rejected += 1
        else:
            passed.append(updated)
    return (
        passed,
        rejected,
        FilterStageCount(
            stage=stage,
            evaluated=len(active),
            passed=len(passed),
            rejected=newly_rejected,
        ),
    )


def _option_type_stage(
    contract: OptionContract,
) -> tuple[OptionContract, list[str]]:
    reasons = (
        [] if contract.option_type is OptionType.CALL else ["PUT contracts are excluded"]
    )
    return contract, reasons


def _dte_stage(
    contract: OptionContract, config: LongCallConfig
) -> tuple[OptionContract, list[str]]:
    if contract.dte < 0:
        return contract, ["DTE is negative"]
    if not config.min_dte <= contract.dte <= config.max_dte:
        return contract, [
            f"DTE {contract.dte} is outside {config.min_dte}-{config.max_dte}"
        ]
    return contract, []


def _moneyness_stage(
    contract: OptionContract, config: LongCallConfig
) -> tuple[OptionContract, list[str]]:
    if contract.moneyness_pct is None:
        return contract.model_copy(
            update={"moneyness_status": MoneynessStatus.INVALID}
        ), ["Moneyness cannot be calculated from invalid price or strike"]
    if contract.moneyness_pct < -config.max_otm_pct:
        return contract.model_copy(
            update={"moneyness_status": MoneynessStatus.TOO_FAR_OTM}
        ), [
            f"Call is more than {config.max_otm_pct:.1%} out of the money"
        ]
    if contract.moneyness_pct >= 0:
        return contract.model_copy(
            update={"moneyness_status": MoneynessStatus.ATM_OR_ITM}
        ), []
    warnings = list(contract.warnings)
    if config.prefer_atm_or_itm:
        warnings = ordered_unique(
            warnings, "Slightly OTM contract passed; ATM or ITM is preferred"
        )
    return contract.model_copy(
        update={
            "moneyness_status": MoneynessStatus.ACCEPTABLE_OTM,
            "warnings": warnings,
        }
    ), []


def _delta_stage(
    contract: OptionContract, config: LongCallConfig
) -> tuple[OptionContract, list[str]]:
    if contract.delta is None:
        updated = contract.model_copy(
            update={"delta_range_status": DeltaRangeStatus.MISSING}
        )
        if config.missing_delta_policy is PolicyAction.REJECT:
            return updated, ["Delta is unavailable"]
        return updated.model_copy(
            update={
                "warnings": ordered_unique(
                    updated.warnings,
                    "Delta is unavailable; contract retained by policy",
                )
            }
        ), []
    if not config.absolute_delta_min <= contract.delta <= config.absolute_delta_max:
        return contract.model_copy(
            update={"delta_range_status": DeltaRangeStatus.OUTSIDE}
        ), [
            f"Delta {contract.delta:.2f} is outside the absolute "
            f"{config.absolute_delta_min:.2f}-{config.absolute_delta_max:.2f} range"
        ]
    if config.preferred_delta_min <= contract.delta <= config.preferred_delta_max:
        return contract.model_copy(
            update={"delta_range_status": DeltaRangeStatus.PREFERRED}
        ), []
    return contract.model_copy(
        update={
            "delta_range_status": DeltaRangeStatus.ACCEPTABLE,
            "warnings": ordered_unique(
                contract.warnings,
                "Delta is inside the absolute range but outside the preferred range",
            ),
        }
    ), []


def _liquidity_stage(
    contract: OptionContract, config: LongCallConfig
) -> tuple[OptionContract, list[str]]:
    reasons: list[str] = []
    flags = set(contract.data_quality_flags)
    if DataQualityFlag.MISSING_QUOTE in flags:
        reasons.append("Bid/ask quote is unavailable")
    if DataQualityFlag.INVALID_BID in flags:
        reasons.append("Bid is negative")
    if DataQualityFlag.INVALID_ASK in flags:
        reasons.append("Ask must be greater than zero")
    if DataQualityFlag.CROSSED_MARKET in flags:
        reasons.append("Ask is below bid")
    if DataQualityFlag.ZERO_BID in flags:
        reasons.append("Bid is zero")
    if DataQualityFlag.WIDE_SPREAD in flags:
        reasons.append(
            f"Spread exceeds the {config.max_spread_pct:.1%} maximum"
        )

    if contract.open_interest is None:
        if config.missing_open_interest_policy is PolicyAction.REJECT:
            reasons.append("Open interest is unavailable")
    elif contract.open_interest < 0:
        reasons.append("Open interest is negative")
    elif contract.open_interest < config.min_open_interest:
        reasons.append(
            f"Open interest {contract.open_interest} is below "
            f"{config.min_open_interest}"
        )

    warnings = list(contract.warnings)
    if contract.open_interest is None and (
        config.missing_open_interest_policy is PolicyAction.WARN
    ):
        warnings = ordered_unique(
            warnings, "Open interest is unavailable; contract retained by policy"
        )

    if contract.volume is None:
        if config.missing_volume_policy is PolicyAction.REJECT:
            reasons.append("Volume is unavailable")
        else:
            warnings = ordered_unique(
                warnings, "Volume is unavailable; contract retained by policy"
            )
    elif contract.volume < 0:
        reasons.append("Volume is negative")
    elif contract.volume < config.min_volume:
        if config.low_volume_policy is PolicyAction.REJECT:
            reasons.append(
                f"Volume {contract.volume} is below {config.min_volume}"
            )
        else:
            warnings = ordered_unique(
                warnings,
                f"Volume {contract.volume} is below {config.min_volume}",
            )

    return contract.model_copy(update={"warnings": warnings}), reasons


def _attach_relative_iv(
    contracts: list[OptionContract], config: LongCallConfig
) -> list[OptionContract]:
    valid_values = [
        contract.implied_volatility
        for contract in contracts
        if contract.implied_volatility is not None
        and contract.implied_volatility >= 0
    ]
    if len(valid_values) < config.relative_iv_min_sample_size:
        return [
            contract.model_copy(
                update={
                    "data_quality_flags": ordered_unique(
                        contract.data_quality_flags,
                        DataQualityFlag.INSUFFICIENT_RELATIVE_IV_SAMPLE,
                    ),
                    "warnings": ordered_unique(
                        contract.warnings,
                        "Insufficient valid chain IV samples for a relative percentile",
                    ),
                }
            )
            for contract in contracts
        ]

    return [
        _attach_contract_iv_percentile(contract, valid_values, config)
        for contract in contracts
    ]


def _attach_contract_iv_percentile(
    contract: OptionContract,
    valid_values: list[float],
    config: LongCallConfig,
) -> OptionContract:
    if contract.implied_volatility is None or contract.implied_volatility < 0:
        return contract
    percentile = sum(
        value <= contract.implied_volatility for value in valid_values
    ) / len(valid_values)
    flags = list(contract.data_quality_flags)
    warnings = list(contract.warnings)
    if percentile >= config.high_relative_iv_percentile:
        flags = ordered_unique(flags, DataQualityFlag.HIGH_RELATIVE_IV)
        warnings = ordered_unique(
            warnings,
            "Chain-relative IV percentile is high; this is not a historical IV percentile",
        )
    return contract.model_copy(
        update={
            "chain_relative_iv_percentile": percentile,
            "data_quality_flags": flags,
            "warnings": warnings,
        }
    )


def filter_long_call_contracts(
    contracts: Sequence[OptionContract],
    config: LongCallConfig,
    *,
    as_of: datetime,
) -> OptionFilterResult:
    """Apply transparent Phase-1 filters without ranking or candidate caps."""

    active = [
        normalize_contract_quality(contract, config, as_of=as_of)
        for contract in contracts
    ]
    rejected: list[OptionContract] = []
    stage_counts: list[FilterStageCount] = []

    for stage, evaluator in (
        ("option_type", _option_type_stage),
        ("dte", lambda contract: _dte_stage(contract, config)),
        ("moneyness", lambda contract: _moneyness_stage(contract, config)),
        ("delta", lambda contract: _delta_stage(contract, config)),
        ("liquidity", lambda contract: _liquidity_stage(contract, config)),
    ):
        active, rejected, stats = _run_stage(
            stage, active, rejected, evaluator
        )
        stage_counts.append(stats)

    iv_evaluated = len(active)
    invalid_iv: list[OptionContract] = []
    valid_iv: list[OptionContract] = []
    for contract in active:
        if DataQualityFlag.INVALID_IV in contract.data_quality_flags:
            invalid_iv.append(
                _with_rejection_reasons(
                    contract, ["Implied volatility is negative"]
                )
            )
        else:
            valid_iv.append(contract)
    rejected.extend(invalid_iv)
    active = _attach_relative_iv(valid_iv, config)
    stage_counts.append(
        FilterStageCount(
            stage="relative_chain_iv",
            evaluated=iv_evaluated,
            passed=len(active),
            rejected=len(invalid_iv),
        )
    )

    active = [attach_event_risk(contract, as_of=as_of) for contract in active]
    stage_counts.append(
        FilterStageCount(
            stage="event_risk",
            evaluated=len(active),
            passed=len(active),
            rejected=0,
        )
    )
    accepted = [
        contract.model_copy(
            update={"filter_status": ContractFilterStatus.ACCEPTED}
        )
        for contract in active
    ]
    return OptionFilterResult(
        total=len(contracts),
        accepted=accepted,
        rejected=rejected,
        stage_counts=stage_counts,
    )
