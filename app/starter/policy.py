from __future__ import annotations

from datetime import timedelta
import math

from app.readiness_models import CallRequirementCode, RequirementStatus
from app.starter.config import StarterConfigV1, StarterMode
from app.starter.models import (
    ConfirmationQuality,
    ConfirmationSummary,
    EntryProximity,
    EventResultQuality,
    InvalidationSource,
    OptionsResultSource,
    ProximitySummary,
    SelloffDriver,
    StarterBlockerCode,
    StarterEvaluationStatus,
    StarterEvidenceCode,
    StarterPolicyEvaluation,
    StarterPolicyInput,
    StarterOptionsScanStatus,
    StarterOptionsFeed,
    StarterWarningCode,
    StructuredInvalidation,
    ThesisImpact,
)
from app.states import SetupState
from app.universe import AssetClass, TickerGroup


_ALL_REQUIREMENTS = frozenset({
    CallRequirementCode.LEADER_WORKFLOW_ENABLED,
    CallRequirementCode.PRIOR_REPAIR_CONTEXT,
    CallRequirementCode.HIGHER_LOW,
    CallRequirementCode.COMPLETED_BAR_CONFIRMATION,
    CallRequirementCode.BENCHMARK_CONFIRMATION,
})
_PRELIMINARY_PASS = frozenset(
    {
        CallRequirementCode.LEADER_WORKFLOW_ENABLED,
        CallRequirementCode.PRIOR_REPAIR_CONTEXT,
        CallRequirementCode.HIGHER_LOW,
        CallRequirementCode.BENCHMARK_CONFIRMATION,
    }
)
_PRELIMINARY_FAIL = frozenset(
    {CallRequirementCode.COMPLETED_BAR_CONFIRMATION}
)


def max_starter_risk_usd(
    full_setup_risk_budget_usd: float, config: StarterConfigV1
) -> float:
    if (
        not math.isfinite(full_setup_risk_budget_usd)
        or full_setup_risk_budget_usd <= 0
    ):
        raise ValueError("full setup risk budget must be finite and positive")
    return (
        full_setup_risk_budget_usd
        * config.max_risk_fraction_of_full_setup
    )


def calculate_proximity(
    *,
    current_price: float,
    local_resistance: float | None,
    local_support: float | None,
    atr14: float | None,
    config: StarterConfigV1,
) -> ProximitySummary:
    resistance_pct = (
        None
        if local_resistance is None
        else abs(local_resistance - current_price) / current_price * 100
    )
    invalidation_pct = (
        None
        if local_support is None
        else abs(current_price - local_support) / current_price * 100
    )
    if atr14 is None or atr14 <= 0 or local_resistance is None:
        quality = EntryProximity.UNKNOWN
        resistance_atr = None
    else:
        resistance_atr = abs(local_resistance - current_price) / atr14
        if resistance_atr >= config.proximity.high_atr:
            quality = EntryProximity.HIGH
        elif resistance_atr >= config.proximity.medium_atr:
            quality = EntryProximity.MEDIUM
        else:
            quality = EntryProximity.LOW
    invalidation_atr = (
        None
        if atr14 is None or atr14 <= 0 or local_support is None
        else abs(current_price - local_support) / atr14
    )
    return ProximitySummary(
        quality=quality,
        resistance_distance_atr=resistance_atr,
        resistance_distance_pct=resistance_pct,
        invalidation_distance_atr=invalidation_atr,
        invalidation_distance_pct=invalidation_pct,
    )


def entry_proximity(
    current_price: float,
    local_resistance: float | None,
    atr14: float | StarterConfigV1 | None,
    config: StarterConfigV1 | None = None,
) -> tuple[EntryProximity, float | None]:
    """Compatibility helper returning quality and resistance distance percent."""

    if isinstance(atr14, StarterConfigV1):
        config = atr14
        atr14 = None
    if config is None:
        raise ValueError("config is required")
    result = calculate_proximity(
        current_price=current_price,
        local_resistance=local_resistance,
        local_support=None,
        atr14=atr14,
        config=config,
    )
    return result.quality, result.resistance_distance_pct


def _requirement_statuses(
    source: StarterPolicyInput,
) -> dict[CallRequirementCode, RequirementStatus]:
    return {
        requirement.code: requirement.status
        for requirement in source.equity.readiness.requirements
    }


def _preliminary_readiness(source: StarterPolicyInput) -> bool:
    # V1 shadow research retains its technical 4-of-5 pattern, never execution permission.
    statuses = {
        code: status for code, status in _requirement_statuses(source).items()
        if code in _ALL_REQUIREMENTS
    }
    return (
        frozenset(statuses) == _ALL_REQUIREMENTS
        and frozenset(
            code
            for code, status in statuses.items()
            if status is RequirementStatus.PASS
        )
        == _PRELIMINARY_PASS
        and frozenset(
            code
            for code, status in statuses.items()
            if status is RequirementStatus.FAIL
        )
        == _PRELIMINARY_FAIL
    )


def _full_confirmation(source: StarterPolicyInput) -> bool:
    statuses = _requirement_statuses(source)
    return _ALL_REQUIREMENTS.issubset(statuses) and all(
        status is RequirementStatus.PASS for status in statuses.values()
    )


def _confirmation(source: StarterPolicyInput) -> ConfirmationSummary:
    requirements = [
        item for item in source.equity.readiness.requirements
        if item.code in _ALL_REQUIREMENTS
    ]
    passed = sum(
        requirement.status is RequirementStatus.PASS
        for requirement in requirements
    )
    total = len(requirements)
    if source.equity.lower_low:
        quality = ConfirmationQuality.LOW
    elif passed == 5 and total == 5:
        quality = ConfirmationQuality.HIGH
    elif passed == 4 and total == 5:
        quality = ConfirmationQuality.MEDIUM
    else:
        quality = ConfirmationQuality.LOW
    return ConfirmationSummary(
        quality=quality,
        passed_count=passed,
        total_count=total,
        lower_low=source.equity.lower_low,
    )


def _preliminary_blockers(
    source: StarterPolicyInput, config: StarterConfigV1
) -> tuple[StarterBlockerCode, ...]:
    result: list[StarterBlockerCode] = []
    profile = source.profile
    equity = source.equity
    assessment = source.event_assessment

    if equity.ticker not in config.approved_tickers:
        result.append(StarterBlockerCode.TICKER_NOT_APPROVED)
    if profile.ticker != equity.ticker or (
        assessment is not None and assessment.ticker != equity.ticker
    ):
        result.append(StarterBlockerCode.IDENTITY_MISMATCH)
    if not profile.confirmed:
        result.append(StarterBlockerCode.PROFILE_NOT_CONFIRMED)
    if not (
        profile.enabled
        and profile.asset_class is AssetClass.EQUITY
        and TickerGroup.LEADER_LONG_CALL in profile.groups
    ):
        result.append(StarterBlockerCode.PROFILE_NOT_ENABLED_EQUITY_LEADER)
    if equity.state is not SetupState.RIGHT_SIDE_REPAIR:
        result.append(
            StarterBlockerCode.EQUITY_STATE_NOT_RIGHT_SIDE_REPAIR
        )
    if equity.tech_setup_score < config.min_tech_setup_score:
        result.append(StarterBlockerCode.TECH_SETUP_SCORE_BELOW_MINIMUM)
    if equity.lower_low:
        result.append(StarterBlockerCode.LOWER_LOW_PRESENT)
    if not _preliminary_readiness(source):
        result.append(
            StarterBlockerCode.READINESS_REQUIREMENTS_NOT_EXACT_STARTER
        )

    if assessment is not None:
        if assessment.event_type not in config.allowed_event_types:
            result.append(StarterBlockerCode.EVENT_TYPE_NOT_ALLOWED)
        if not assessment.is_current(source.evaluated_at):
            result.append(StarterBlockerCode.EVENT_ASSESSMENT_EXPIRED)
        if assessment.event_result_quality not in {
            EventResultQuality.POSITIVE,
            EventResultQuality.MIXED_POSITIVE,
        }:
            result.append(StarterBlockerCode.EVENT_RESULT_NOT_SUPPORTIVE)
        if assessment.selloff_driver not in {
            SelloffDriver.EXPECTATION_RESET,
            SelloffDriver.VALUATION_RESET,
        }:
            result.append(StarterBlockerCode.SELLOFF_DRIVER_NOT_SUPPORTIVE)
        if assessment.thesis_impact not in {
            ThesisImpact.IMPROVED,
            ThesisImpact.INTACT,
        }:
            result.append(StarterBlockerCode.THESIS_IMPACT_NOT_SUPPORTIVE)
        if (
            assessment.data_completeness
            < config.min_event_data_completeness
        ):
            result.append(StarterBlockerCode.EVENT_DATA_INCOMPLETE)
        if (
            assessment.evidence_confidence
            < config.min_event_evidence_confidence
        ):
            result.append(
                StarterBlockerCode.EVENT_EVIDENCE_CONFIDENCE_LOW
            )
        if not assessment.blocker_review_complete:
            result.append(StarterBlockerCode.BLOCKER_REVIEW_INCOMPLETE)
        if not assessment.source_references:
            result.append(StarterBlockerCode.SOURCE_REFERENCES_MISSING)
        if assessment.event_blocker_codes:
            result.append(StarterBlockerCode.EVENT_BLOCKERS_PRESENT)

    if source.full_setup_risk is not None and assessment is not None:
        if (
            source.full_setup_risk.risk_plan_id != assessment.risk_plan_id
            or source.full_setup_risk.planned_full_setup_risk_budget_usd
            != assessment.planned_full_setup_risk_budget_usd
        ):
            result.append(StarterBlockerCode.IDENTITY_MISMATCH)
    if equity.local_support is None:
        result.append(StarterBlockerCode.LOCAL_SUPPORT_UNAVAILABLE)
    return tuple(dict.fromkeys(result))


def _options_blockers(
    source: StarterPolicyInput, config: StarterConfigV1
) -> tuple[tuple[StarterBlockerCode, ...], tuple[StarterWarningCode, ...]]:
    summary = source.options_fit
    if summary is None:
        return (), ()
    gates = config.options_gates
    result: list[StarterBlockerCode] = []
    warnings: list[StarterWarningCode] = []
    age = source.evaluated_at - summary.result_at

    if summary.ticker != source.equity.ticker:
        result.append(StarterBlockerCode.IDENTITY_MISMATCH)
    if summary.equity_snapshot_id != source.equity.snapshot_id:
        result.append(
            StarterBlockerCode.OPTIONS_EQUITY_SNAPSHOT_MISMATCH
        )
    if age < timedelta(0) or age > timedelta(
        minutes=gates.max_result_age_minutes
    ):
        result.append(StarterBlockerCode.OPTIONS_RESULT_STALE)
    if (
        gates.require_non_manual_result
        and summary.result_source is OptionsResultSource.MANUAL
    ):
        result.append(StarterBlockerCode.OPTIONS_RESULT_MANUAL)
    if summary.scan_status is not StarterOptionsScanStatus.CANDIDATES_FOUND:
        result.append(
            StarterBlockerCode.OPTIONS_STATUS_NOT_CANDIDATES_FOUND
        )
    candidate = summary.candidate
    if candidate is None:
        result.append(StarterBlockerCode.OPTIONS_CANDIDATE_UNAVAILABLE)
        return tuple(dict.fromkeys(result)), tuple(warnings)
    if candidate.quality_score < gates.min_candidate_quality:
        result.append(StarterBlockerCode.OPTIONS_CANDIDATE_QUALITY_LOW)
    if candidate.confidence < gates.min_candidate_confidence:
        result.append(StarterBlockerCode.OPTIONS_CANDIDATE_CONFIDENCE_LOW)
    if gates.require_relative_iv and candidate.relative_iv_percentile is None:
        result.append(StarterBlockerCode.OPTIONS_RELATIVE_IV_MISSING)
    elif (
        candidate.relative_iv_percentile is not None
        and candidate.relative_iv_percentile
        > gates.max_relative_iv_percentile
    ):
        result.append(StarterBlockerCode.OPTIONS_RELATIVE_IV_HIGH)
    if gates.require_valid_liquidity and not candidate.liquidity_valid:
        result.append(StarterBlockerCode.OPTIONS_LIQUIDITY_INVALID)
    if gates.require_valid_spread and not candidate.spread_valid:
        result.append(StarterBlockerCode.OPTIONS_SPREAD_INVALID)
    if gates.require_no_hard_blockers and candidate.hard_blocker_codes:
        result.append(StarterBlockerCode.OPTIONS_HARD_BLOCKER_PRESENT)
    if summary.feed is StarterOptionsFeed.INDICATIVE:
        warnings.append(StarterWarningCode.INDICATIVE_OPTIONS_FEED)
    return tuple(dict.fromkeys(result)), tuple(warnings)


def evaluate_starter_policy(
    source: StarterPolicyInput, config: StarterConfigV1
) -> StarterPolicyEvaluation:
    if config.mode is not StarterMode.SHADOW:
        raise ValueError("Starter V1 supports SHADOW mode only")

    risk = source.full_setup_risk
    max_risk = (
        None
        if risk is None
        else max_starter_risk_usd(
            risk.planned_full_setup_risk_budget_usd, config
        )
    )
    invalidation = (
        None
        if source.equity.local_support is None
        else StructuredInvalidation(
            source=InvalidationSource.LOCAL_SUPPORT,
            level=source.equity.local_support,
        )
    )
    common = {
        "ticker": source.equity.ticker,
        "created_at": source.evaluated_at,
        "event_assessment_id": (
            None
            if source.event_assessment is None
            else source.event_assessment.assessment_id
        ),
        "equity_snapshot_id": source.equity.snapshot_id,
        "snapshot_at": source.equity.snapshot_at,
        "snapshot_price": source.equity.snapshot_price,
        "policy_version": config.policy_version,
        "profile_version": source.profile.profile_version,
        "readiness_snapshot": source.equity.readiness,
        "confirmation": _confirmation(source),
        "proximity": calculate_proximity(
            current_price=source.equity.snapshot_price,
            local_resistance=source.equity.local_resistance,
            local_support=source.equity.local_support,
            atr14=source.equity.atr14,
            config=config,
        ),
        "max_risk_fraction_of_full_setup": (
            config.max_risk_fraction_of_full_setup
        ),
        "max_starter_risk_usd": max_risk,
        "invalidation": invalidation,
        "confirmation_trigger": (
            source.equity.readiness.next_trigger.model_copy(deep=True)
        ),
        "options_scan_id": (
            None
            if source.options_fit is None
            else source.options_fit.options_scan_id
        ),
        "options_fit_summary": source.options_fit,
    }

    if not config.enabled:
        return StarterPolicyEvaluation(
            status=StarterEvaluationStatus.BLOCKED,
            blocker_codes=(StarterBlockerCode.POLICY_DISABLED,),
            **common,
        )
    unavailable: list[StarterBlockerCode] = []
    if source.event_assessment is None:
        unavailable.append(
            StarterBlockerCode.EVENT_ASSESSMENT_UNAVAILABLE
        )
    if risk is None:
        unavailable.append(
            StarterBlockerCode.FULL_SETUP_RISK_BUDGET_UNAVAILABLE
        )
    if unavailable:
        return StarterPolicyEvaluation(
            status=StarterEvaluationStatus.UNAVAILABLE,
            blocker_codes=tuple(unavailable),
            **common,
        )

    # Qualification is inferred from the exact five shared requirements only.
    if _full_confirmation(source):
        return StarterPolicyEvaluation(
            status=(
                StarterEvaluationStatus.FULL_CONFIRMATION_ALREADY_AVAILABLE
            ),
            evidence=(StarterEvidenceCode.FULL_CONFIRMATION_PRESENT,),
            **common,
        )

    blockers = _preliminary_blockers(source, config)
    if blockers:
        return StarterPolicyEvaluation(
            status=StarterEvaluationStatus.NOT_ELIGIBLE,
            blocker_codes=blockers,
            **common,
        )
    if source.options_fit is None:
        return StarterPolicyEvaluation(
            status=StarterEvaluationStatus.PRELIMINARY_ELIGIBLE,
            evidence=(StarterEvidenceCode.PRELIMINARY_GATE_SATISFIED,),
            **common,
        )

    option_blockers, warnings = _options_blockers(source, config)
    if option_blockers:
        return StarterPolicyEvaluation(
            status=StarterEvaluationStatus.NOT_ELIGIBLE,
            blocker_codes=option_blockers,
            warning_codes=warnings,
            evidence=(StarterEvidenceCode.PRELIMINARY_GATE_SATISFIED,),
            **common,
        )
    return StarterPolicyEvaluation(
        status=StarterEvaluationStatus.SHADOW_ELIGIBLE,
        evidence=(
            StarterEvidenceCode.PRELIMINARY_GATE_SATISFIED,
            StarterEvidenceCode.OPTIONS_FIT_SATISFIED,
        ),
        warning_codes=warnings,
        **common,
    )


evaluate = evaluate_starter_policy
