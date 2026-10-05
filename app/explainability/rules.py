from __future__ import annotations

import math

from app.config import ThresholdConfig
from app.entry_models import EntryEvaluation
from app.explainability.models import (
    ConfidenceNoteCode,
    Invalidation,
    InvalidationType,
    LevelSource,
    MissingConditionCode,
    NextTrigger,
    ReasonCode,
    SetupExplanation,
    TriggerType,
)
from app.models import TechnicalFeatures
from app.call_readiness import evaluate_call_readiness
from app.readiness_models import CallReadinessEvaluation
from app.states import SetupState

REPAIR_CONTEXT_STATES = {
    SetupState.RIGHT_SIDE_REPAIR,
    SetupState.SELLING_EXHAUSTION,
}


def _reliable_level(
    value: float, source: LevelSource
) -> tuple[float | None, LevelSource | None]:
    if math.isfinite(value) and value > 0:
        return value, source
    return None, None


def _trigger(
    trigger_type: TriggerType,
    description: str,
    *,
    value: float | None = None,
    source: LevelSource | None = None,
) -> NextTrigger:
    level, level_source = (
        _reliable_level(value, source)
        if value is not None and source is not None
        else (None, None)
    )
    return NextTrigger(
        type=trigger_type,
        level=level,
        source=level_source,
        description=description,
    )


def _invalidation(
    invalidation_type: InvalidationType,
    description: str,
    *,
    value: float | None = None,
    source: LevelSource | None = None,
) -> Invalidation:
    level, level_source = (
        _reliable_level(value, source)
        if value is not None and source is not None
        else (None, None)
    )
    return Invalidation(
        type=invalidation_type,
        level=level,
        source=level_source,
        description=description,
    )


def _structure_missing(
    features: TechnicalFeatures,
) -> list[MissingConditionCode]:
    missing: list[MissingConditionCode] = []
    if not features.higher_low:
        missing.append(MissingConditionCode.HIGHER_LOW_NOT_CONFIRMED)
    if not (features.two_bar_reclaim or features.two_bar_acceptance):
        missing.append(MissingConditionCode.TWO_BAR_CONFIRMATION_MISSING)
    return missing


def _confidence_notes(
    features: TechnicalFeatures, benchmark_confirmed: bool
) -> list[ConfidenceNoteCode]:
    structure_confirmed = features.higher_low and (
        features.two_bar_acceptance or features.two_bar_reclaim
    )
    return [
        (
            ConfidenceNoteCode.FULL_STRUCTURE_CONFIRMATION
            if structure_confirmed
            else ConfidenceNoteCode.PARTIAL_STRUCTURE_CONFIRMATION
        ),
        (
            ConfidenceNoteCode.BENCHMARK_CONFIRMATION_PRESENT
            if benchmark_confirmed
            else ConfidenceNoteCode.BENCHMARK_CONFIRMATION_MISSING
        ),
    ]


def build_setup_explanation(
    *,
    ticker: str,
    state: SetupState,
    features: TechnicalFeatures,
    benchmark_confirmed: bool,
    previous_state: SetupState | None,
    thresholds: ThresholdConfig,
    readiness: CallReadinessEvaluation | None = None,
    entry_plan: EntryEvaluation | None = None,
) -> SetupExplanation:
    """Build a truthful explanation from the classifier's current inputs."""

    confidence_notes = _confidence_notes(features, benchmark_confirmed)
    readiness = readiness or evaluate_call_readiness(
        features,
        previous_state=previous_state,
        benchmark_confirmed=benchmark_confirmed,
        entry_plan=entry_plan,
        momentum_rsi=thresholds.momentum_rsi,
    )

    if state is SetupState.NORMAL:
        return SetupExplanation(
            ticker=ticker,
            state=state,
            reasons=[ReasonCode.NO_ACTIVE_DIP_OR_BREAKOUT_SETUP],
            next_trigger=_trigger(
                TriggerType.WAIT_FOR_MEANINGFUL_DIP_OR_BREAKOUT_SETUP,
                "Wait for a meaningful dip or confirmed repair setup.",
            ),
            invalidation=None,
            missing_conditions=_structure_missing(features),
            confidence_notes=confidence_notes,
        )

    if state is SetupState.DIP_WATCH:
        reasons = [
            ReasonCode.DRAWDOWN_THRESHOLD_REACHED,
            ReasonCode.PRICE_AT_OR_ABOVE_SUPPORT,
        ]
        if features.current_price < features.vwap:
            reasons.append(ReasonCode.BELOW_VWAP)
        return SetupExplanation(
            ticker=ticker,
            state=state,
            reasons=reasons,
            next_trigger=_trigger(
                TriggerType.HIGHER_LOW_AND_RECLAIM,
                "Confirm a higher low and reclaim VWAP.",
                value=features.vwap,
                source=LevelSource.VWAP,
            ),
            invalidation=_invalidation(
                InvalidationType.BREAKDOWN_CONTINUATION,
                "A completed bar loses rolling support.",
                value=features.support,
                source=LevelSource.RECENT_SWING_LOW,
            ),
            missing_conditions=_structure_missing(features),
            confidence_notes=confidence_notes,
        )

    if state is SetupState.SELLING_EXHAUSTION:
        reasons = [
            ReasonCode.OVERSOLD_MOMENTUM,
            ReasonCode.INTRADAY_STABILIZATION,
        ]
        if features.return_15m_pct > 0:
            reasons.append(ReasonCode.POSITIVE_FIFTEEN_MINUTE_RETURN)
        if features.current_price >= features.vwap:
            reasons.append(ReasonCode.PRICE_AT_OR_ABOVE_VWAP)
        return SetupExplanation(
            ticker=ticker,
            state=state,
            reasons=reasons,
            next_trigger=_trigger(
                TriggerType.CONFIRMED_HIGHER_LOW,
                "Confirm a higher low before treating stabilization as repair.",
            ),
            invalidation=_invalidation(
                InvalidationType.FRESH_EXPANSION_LOW,
                "A fresh low below rolling support invalidates stabilization.",
                value=features.support,
                source=LevelSource.RECENT_SWING_LOW,
            ),
            missing_conditions=_structure_missing(features),
            confidence_notes=confidence_notes,
        )

    if state is SetupState.RIGHT_SIDE_REPAIR:
        reasons: list[ReasonCode] = []
        if features.current_price > features.ema9:
            reasons.append(ReasonCode.PRICE_ABOVE_EMA9)
        if features.ema9 >= features.ema20:
            reasons.append(ReasonCode.EMA9_AT_OR_ABOVE_EMA20)
        if features.higher_low:
            reasons.append(ReasonCode.HIGHER_LOW_CONFIRMED)
        if features.two_bar_reclaim:
            reasons.extend(
                [ReasonCode.SUPPORT_RECLAIMED, ReasonCode.ACCEPTANCE_CONFIRMED]
            )
        if features.two_bar_acceptance:
            reasons.extend(
                [
                    ReasonCode.RESISTANCE_RECLAIMED,
                    ReasonCode.ACCEPTANCE_CONFIRMED,
                ]
            )
        if features.higher_low and (
            features.two_bar_reclaim or features.two_bar_acceptance
        ):
            reasons.append(ReasonCode.RIGHT_SIDE_REPAIR_CONFIRMED)
        if benchmark_confirmed:
            reasons.append(ReasonCode.MARKET_CONFIRMATION)
        return SetupExplanation(
            ticker=ticker,
            state=state,
            reasons=reasons or [ReasonCode.RIGHT_SIDE_REPAIR_CONFIRMED],
            next_trigger=readiness.next_trigger,
            invalidation=_invalidation(
                InvalidationType.REPAIR_STRUCTURE_FAILED,
                "Losing EMA20 or printing a fresh lower low invalidates repair.",
                value=features.ema20,
                source=LevelSource.EMA20,
            ),
            missing_conditions=readiness.missing_conditions,
            confidence_notes=confidence_notes,
        )

    if state is SetupState.CALL_CANDIDATE:
        reasons = [ReasonCode.ACCEPTANCE_CONFIRMED, ReasonCode.MARKET_CONFIRMATION]
        if previous_state in REPAIR_CONTEXT_STATES:
            reasons.append(ReasonCode.PRIOR_REPAIR_CONTEXT)
        if features.higher_low:
            reasons.append(ReasonCode.HIGHER_LOW_CONFIRMED)
        if entry_plan is not None and entry_plan.anchor is not None:
            reasons.append(ReasonCode.STRUCTURAL_SETUP_CONFIRMED)
            invalidation_level = entry_plan.anchor.invalidation_level
            invalidation_source = LevelSource.ENTRY_STRUCTURAL_STOP
        elif features.two_bar_acceptance:
            reasons.append(ReasonCode.RESISTANCE_RECLAIMED)
            invalidation_level = features.resistance
            invalidation_source = LevelSource.RECLAIMED_RESISTANCE
        else:
            reasons.append(ReasonCode.SUPPORT_RECLAIMED)
            invalidation_level = features.support
            invalidation_source = LevelSource.RECLAIMED_SUPPORT
        return SetupExplanation(
            ticker=ticker,
            state=state,
            reasons=reasons,
            next_trigger=readiness.next_trigger,
            invalidation=_invalidation(
                InvalidationType.REPAIR_STRUCTURE_FAILED,
                "Losing structural support invalidates the setup; current entry eligibility is separate.",
                value=invalidation_level,
                source=invalidation_source,
            ),
            missing_conditions=readiness.missing_conditions,
            confidence_notes=confidence_notes,
        )

    return SetupExplanation(
        ticker=ticker,
        state=state,
        reasons=[ReasonCode.SUPPORT_LOST, ReasonCode.FRESH_LOWER_LOW],
        next_trigger=_trigger(
            TriggerType.RECLAIM_SUPPORT_AND_HIGHER_LOW,
            "Reclaim broken support and then form a higher low.",
            value=features.support,
            source=LevelSource.BROKEN_SUPPORT,
        ),
        invalidation=_invalidation(
            InvalidationType.RECLAIM_SUPPORT_AND_HIGHER_LOW,
            "Reclaiming broken support and forming a higher low cancels breakdown.",
            value=features.support,
            source=LevelSource.BROKEN_SUPPORT,
        ),
        missing_conditions=[
            MissingConditionCode.RECLAIM_ABSENT,
            MissingConditionCode.HIGHER_LOW_ABSENT,
        ],
        confidence_notes=confidence_notes,
    )
