from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.classification.config import ClassificationConfig
from app.classification.models import (
    AxisScore,
    ClassificationAxis,
    ClassificationEvaluation,
    ClassificationReasonCode,
    EvaluationStatus,
    EvidenceCategory,
    EvidenceDataQuality,
    PortfolioRole,
    ReviewMode,
    RoleEvidence,
    RoleFitScore,
    TickerProfile,
)


# Every scored category uses the same favorable direction:
# 0 = unfavorable/high risk; 10 = resilient/favorable/low risk.
AXIS_CATEGORIES: dict[ClassificationAxis, tuple[EvidenceCategory, ...]] = {
    ClassificationAxis.BUSINESS_QUALITY: (
        EvidenceCategory.BUSINESS_QUALITY,
        EvidenceCategory.BUSINESS_MATURITY,
        EvidenceCategory.THESIS_STABILITY,
    ),
    ClassificationAxis.FINANCIAL_STABILITY: (
        EvidenceCategory.FINANCIAL_STABILITY,
        EvidenceCategory.FINANCING_RISK,
        EvidenceCategory.DILUTION_RISK,
    ),
    ClassificationAxis.REVENUE_VISIBILITY: (
        EvidenceCategory.REVENUE_VISIBILITY,
    ),
    ClassificationAxis.VOLATILITY_RISK: (
        EvidenceCategory.VOLATILITY_REGIME,
    ),
    ClassificationAxis.CONCENTRATION_EVENT_RISK: (
        EvidenceCategory.CUSTOMER_CONCENTRATION,
        EvidenceCategory.EVENT_DEPENDENCE,
    ),
}

QUALITY_FACTORS = {
    EvidenceDataQuality.AVAILABLE: 1.0,
    EvidenceDataQuality.PARTIAL: 0.5,
    EvidenceDataQuality.UNAVAILABLE: 0.0,
}


@dataclass(frozen=True)
class ScoringComponents:
    axis_scores: tuple[AxisScore, ...]
    role_scores: tuple[RoleFitScore, ...]
    data_completeness: float
    evidence_confidence: float


def _axis_weight(
    config: ClassificationConfig, axis: ClassificationAxis
) -> float:
    return float(getattr(config.weights, axis.value))


def score_components(
    evidence: tuple[RoleEvidence, ...] | list[RoleEvidence],
    config: ClassificationConfig,
) -> ScoringComponents:
    axis_scores: list[AxisScore] = []
    confidence_numerator = 0.0
    confidence_denominator = 0

    for axis, categories in AXIS_CATEGORIES.items():
        contributors = [
            item
            for item in evidence
            if item.category in categories
            and item.score is not None
            and QUALITY_FACTORS[item.data_quality] > 0
        ]
        weighted_total = sum(
            float(item.score)
            * item.confidence
            * QUALITY_FACTORS[item.data_quality]
            for item in contributors
        )
        contribution_weight = sum(
            item.confidence * QUALITY_FACTORS[item.data_quality]
            for item in contributors
        )
        axis_value = (
            weighted_total / contribution_weight
            if contribution_weight > 0
            else None
        )
        axis_scores.append(
            AxisScore(
                axis=axis,
                score=axis_value,
                configured_weight=_axis_weight(config, axis),
                contributing_categories=tuple(
                    item.category for item in contributors
                ),
            )
        )
        confidence_numerator += sum(
            item.confidence * QUALITY_FACTORS[item.data_quality]
            for item in contributors
        )
        confidence_denominator += len(contributors)

    covered_weight = sum(
        item.configured_weight
        for item in axis_scores
        if item.score is not None
    )
    evidence_confidence = (
        confidence_numerator / confidence_denominator
        if confidence_denominator
        else 0.0
    )

    role_scores: list[RoleFitScore] = []
    for role in PortfolioRole:
        archetype = config.archetype_for(role)
        if archetype is None or covered_weight <= 0:
            role_scores.append(RoleFitScore(role=role, score=None))
            continue
        distance = sum(
            item.configured_weight
            * abs(float(item.score) - archetype.target_for(item.axis))
            for item in axis_scores
            if item.score is not None
        ) / covered_weight
        role_scores.append(
            RoleFitScore(role=role, score=max(0.0, min(10.0, 10 - distance)))
        )

    return ScoringComponents(
        axis_scores=tuple(axis_scores),
        role_scores=tuple(role_scores),
        data_completeness=max(0.0, min(1.0, covered_weight)),
        evidence_confidence=max(0.0, min(1.0, evidence_confidence)),
    )


def evaluate_profile(
    profile: TickerProfile,
    evidence: tuple[RoleEvidence, ...] | list[RoleEvidence],
    config: ClassificationConfig,
    *,
    review_mode: ReviewMode,
    created_at: datetime,
) -> ClassificationEvaluation:
    evidence_tuple = tuple(evidence)
    components = score_components(evidence_tuple, config)
    score_by_role = {item.role: item.score for item in components.role_scores}
    current_score = score_by_role[profile.primary_role]
    allowed_candidates = set(config.candidates_for(profile.primary_role))
    scored_alternatives = [
        item
        for item in components.role_scores
        if item.role in allowed_candidates and item.score is not None
    ]
    winner = (
        max(scored_alternatives, key=lambda item: float(item.score)).role
        if scored_alternatives
        else None
    )
    winner_score = score_by_role.get(winner) if winner is not None else None
    score_delta = (
        float(winner_score) - float(current_score)
        if winner_score is not None and current_score is not None
        else 0.0
    )

    if (
        components.data_completeness < config.min_data_completeness
        or components.evidence_confidence < config.min_evidence_confidence
    ):
        status = EvaluationStatus.INSUFFICIENT_EVIDENCE
    elif current_score is None or not allowed_candidates:
        status = EvaluationStatus.DISALLOWED_TRANSITION
    elif winner is None:
        status = EvaluationStatus.NO_CHANGE
    elif score_delta < config.min_score_delta:
        status = EvaluationStatus.NO_CHANGE
    else:
        status = EvaluationStatus.AWAITING_CONFIRMATION

    reason_codes = tuple(
        dict.fromkeys(
            code
            for item in evidence_tuple
            for code in item.reason_codes
        )
    )
    return ClassificationEvaluation(
        ticker=profile.ticker,
        review_mode=review_mode,
        profile_version=profile.version,
        current_role=profile.primary_role,
        current_role_score=current_score,
        axis_scores=components.axis_scores,
        role_scores=components.role_scores,
        winning_candidate=winner,
        score_delta=score_delta,
        data_completeness=components.data_completeness,
        evidence_confidence=components.evidence_confidence,
        evidence_snapshot=evidence_tuple,
        status=status,
        reason_codes=reason_codes,
        created_at=created_at,
    )


def latest_evidence_by_category(
    evidence: tuple[RoleEvidence, ...] | list[RoleEvidence],
) -> tuple[RoleEvidence, ...]:
    latest: dict[EvidenceCategory, RoleEvidence] = {}
    for item in evidence:
        previous = latest.get(item.category)
        if previous is None or item.source_timestamp >= previous.source_timestamp:
            latest[item.category] = item
    return tuple(latest[category] for category in EvidenceCategory if category in latest)


def reason_codes_for_score(
    category: EvidenceCategory, score: float | None
) -> tuple[ClassificationReasonCode, ...]:
    if score is None or 4 < score < 7:
        return ()
    positive = score >= 7
    pairs = {
        EvidenceCategory.BUSINESS_QUALITY: (
            ClassificationReasonCode.BUSINESS_QUALITY_STRONG,
            ClassificationReasonCode.BUSINESS_QUALITY_WEAK,
        ),
        EvidenceCategory.FINANCIAL_STABILITY: (
            ClassificationReasonCode.FINANCIAL_STABILITY_STRONG,
            ClassificationReasonCode.FINANCIAL_STABILITY_WEAK,
        ),
        EvidenceCategory.REVENUE_VISIBILITY: (
            ClassificationReasonCode.REVENUE_VISIBILITY_STRONG,
            ClassificationReasonCode.REVENUE_VISIBILITY_WEAK,
        ),
        EvidenceCategory.CUSTOMER_CONCENTRATION: (
            ClassificationReasonCode.CUSTOMER_DIVERSIFICATION_STRONG,
            ClassificationReasonCode.CUSTOMER_CONCENTRATION_HIGH,
        ),
        EvidenceCategory.FINANCING_RISK: (
            ClassificationReasonCode.FINANCING_RISK_LOW,
            ClassificationReasonCode.FINANCING_RISK_HIGH,
        ),
        EvidenceCategory.DILUTION_RISK: (
            ClassificationReasonCode.DILUTION_RISK_LOW,
            ClassificationReasonCode.DILUTION_RISK_HIGH,
        ),
        EvidenceCategory.BUSINESS_MATURITY: (
            ClassificationReasonCode.BUSINESS_MATURITY_ESTABLISHED,
            ClassificationReasonCode.BUSINESS_MATURITY_EMERGING,
        ),
        EvidenceCategory.VOLATILITY_REGIME: (
            ClassificationReasonCode.VOLATILITY_NORMALIZED,
            ClassificationReasonCode.VOLATILITY_ELEVATED,
        ),
        EvidenceCategory.THESIS_STABILITY: (
            ClassificationReasonCode.THESIS_STABILITY_STRONG,
            ClassificationReasonCode.THESIS_STABILITY_WEAK,
        ),
        EvidenceCategory.EVENT_DEPENDENCE: (
            ClassificationReasonCode.EVENT_DEPENDENCE_LOW,
            ClassificationReasonCode.EVENT_DEPENDENCE_HIGH,
        ),
    }
    pair = pairs.get(category)
    return (pair[0] if positive else pair[1],) if pair else ()
