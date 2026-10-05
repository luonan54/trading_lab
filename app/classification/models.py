from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.universe import AssetClass, TickerGroup


class PortfolioRole(StrEnum):
    CORE = "CORE"
    CORE_GROWTH = "CORE_GROWTH"
    GROWTH = "GROWTH"
    HIGH_RISK_GROWTH = "HIGH_RISK_GROWTH"
    TACTICAL = "TACTICAL"
    CYCLICAL = "CYCLICAL"
    HEDGE = "HEDGE"


class RiskTier(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    MEDIUM_HIGH = "MEDIUM_HIGH"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class ProposalType(StrEnum):
    ROLE_CHANGE = "ROLE_CHANGE"
    GROUP_ADD = "GROUP_ADD"
    GROUP_REMOVE = "GROUP_REMOVE"
    RISK_TIER_CHANGE = "RISK_TIER_CHANGE"
    STRATEGY_TAG_ADD = "STRATEGY_TAG_ADD"
    STRATEGY_TAG_REMOVE = "STRATEGY_TAG_REMOVE"
    BENCHMARK_TAG_CHANGE = "BENCHMARK_TAG_CHANGE"
    COMPANY_QUALITY_CHANGE = "COMPANY_QUALITY_CHANGE"


class ProposalStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SNOOZED = "SNOOZED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class EvidenceCategory(StrEnum):
    BUSINESS_QUALITY = "BUSINESS_QUALITY"
    FINANCIAL_STABILITY = "FINANCIAL_STABILITY"
    REVENUE_VISIBILITY = "REVENUE_VISIBILITY"
    CUSTOMER_CONCENTRATION = "CUSTOMER_CONCENTRATION"
    FINANCING_RISK = "FINANCING_RISK"
    DILUTION_RISK = "DILUTION_RISK"
    BUSINESS_MATURITY = "BUSINESS_MATURITY"
    VOLATILITY_REGIME = "VOLATILITY_REGIME"
    THESIS_STABILITY = "THESIS_STABILITY"
    EVENT_DEPENDENCE = "EVENT_DEPENDENCE"
    TECHNICAL_CONTEXT = "TECHNICAL_CONTEXT"


class EvidenceDataQuality(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


class EvidenceSource(StrEnum):
    MANUAL_USER_ENTRY = "MANUAL_USER_ENTRY"


class ReviewMode(StrEnum):
    WEEKLY = "WEEKLY"
    EVENT = "EVENT"
    MANUAL = "MANUAL"


class EvaluationStatus(StrEnum):
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NO_CHANGE = "NO_CHANGE"
    DISALLOWED_TRANSITION = "DISALLOWED_TRANSITION"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    PROPOSAL_CREATED = "PROPOSAL_CREATED"
    DUPLICATE_PENDING = "DUPLICATE_PENDING"
    COOLDOWN_BLOCKED = "COOLDOWN_BLOCKED"
    SNOOZE_BLOCKED = "SNOOZE_BLOCKED"


class ClassificationAxis(StrEnum):
    BUSINESS_QUALITY = "business_quality"
    FINANCIAL_STABILITY = "financial_stability"
    REVENUE_VISIBILITY = "revenue_visibility"
    VOLATILITY_RISK = "volatility_risk"
    CONCENTRATION_EVENT_RISK = "concentration_event_risk"


class DecisionSource(StrEnum):
    USER_ACCEPTED_PROPOSAL = "USER_ACCEPTED_PROPOSAL"
    USER_REJECTED_PROPOSAL = "USER_REJECTED_PROPOSAL"
    USER_SNOOZED_PROPOSAL = "USER_SNOOZED_PROPOSAL"
    MANUAL_USER_EDIT = "MANUAL_USER_EDIT"
    SYSTEM_INITIALIZATION = "SYSTEM_INITIALIZATION"


class ClassificationReasonCode(StrEnum):
    REVENUE_VISIBILITY_STRONG = "REVENUE_VISIBILITY_STRONG"
    REVENUE_VISIBILITY_WEAK = "REVENUE_VISIBILITY_WEAK"
    CUSTOMER_DIVERSIFICATION_STRONG = "CUSTOMER_DIVERSIFICATION_STRONG"
    CUSTOMER_CONCENTRATION_HIGH = "CUSTOMER_CONCENTRATION_HIGH"
    FINANCING_RISK_LOW = "FINANCING_RISK_LOW"
    FINANCING_RISK_HIGH = "FINANCING_RISK_HIGH"
    VOLATILITY_NORMALIZED = "VOLATILITY_NORMALIZED"
    VOLATILITY_ELEVATED = "VOLATILITY_ELEVATED"
    BUSINESS_MATURITY_ESTABLISHED = "BUSINESS_MATURITY_ESTABLISHED"
    BUSINESS_MATURITY_EMERGING = "BUSINESS_MATURITY_EMERGING"
    DILUTION_RISK_LOW = "DILUTION_RISK_LOW"
    DILUTION_RISK_HIGH = "DILUTION_RISK_HIGH"
    CASH_BURN_CONTROLLED = "CASH_BURN_CONTROLLED"
    CASH_BURN_HIGH = "CASH_BURN_HIGH"
    GUIDANCE_VISIBILITY_HIGH = "GUIDANCE_VISIBILITY_HIGH"
    GUIDANCE_VISIBILITY_LOW = "GUIDANCE_VISIBILITY_LOW"
    EVENT_DEPENDENCE_LOW = "EVENT_DEPENDENCE_LOW"
    EVENT_DEPENDENCE_HIGH = "EVENT_DEPENDENCE_HIGH"
    BUSINESS_QUALITY_STRONG = "BUSINESS_QUALITY_STRONG"
    BUSINESS_QUALITY_WEAK = "BUSINESS_QUALITY_WEAK"
    FINANCIAL_STABILITY_STRONG = "FINANCIAL_STABILITY_STRONG"
    FINANCIAL_STABILITY_WEAK = "FINANCIAL_STABILITY_WEAK"
    THESIS_STABILITY_STRONG = "THESIS_STABILITY_STRONG"
    THESIS_STABILITY_WEAK = "THESIS_STABILITY_WEAK"


def _ordered_unique[T](values: list[T] | tuple[T, ...] | set[T] | frozenset[T]) -> tuple[T, ...]:
    return tuple(dict.fromkeys(values))


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _normalized_nonblank(value: Any, *, uppercase: bool = False) -> Any:
    if not isinstance(value, str):
        return value
    normalized = value.strip()
    return normalized.upper() if uppercase else normalized


def _normalized_optional_identifier(value: Any) -> Any:
    if value is None:
        return None
    normalized = _normalized_nonblank(value, uppercase=True)
    if not normalized:
        raise ValueError("identifier cannot be blank")
    return normalized


class ClassificationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ConfirmedProfileBootstrap(ClassificationModel):
    primary_role: PortfolioRole
    risk_tier: RiskTier
    company_id: str | None = None
    exposure_group: str | None = None
    target_weight: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    max_weight: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )

    @field_validator("company_id", "exposure_group", mode="before")
    @classmethod
    def normalize_optional_identifiers(cls, value: Any) -> Any:
        return _normalized_optional_identifier(value)

    @model_validator(mode="after")
    def validate_weights(self) -> ConfirmedProfileBootstrap:
        if (
            self.target_weight is not None
            and self.max_weight is not None
            and self.target_weight > self.max_weight
        ):
            raise ValueError("target_weight cannot exceed max_weight")
        return self


class TickerProfile(ClassificationModel):
    ticker: str
    primary_role: PortfolioRole
    groups: tuple[TickerGroup, ...] = ()
    strategy_tags: tuple[str, ...] = ()
    risk_tier: RiskTier
    benchmark_tags: tuple[str, ...] = ()
    company_quality: float = Field(ge=0, le=2, allow_inf_nan=False)
    enabled: bool = True
    asset_class: AssetClass = AssetClass.EQUITY
    confirmed_at: datetime
    confirmed_by: str
    version: int = Field(ge=1)
    company_id: str | None = None
    exposure_group: str | None = None
    target_weight: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    max_weight: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: Any) -> Any:
        return _normalized_nonblank(value, uppercase=True)

    @field_validator("ticker", "confirmed_by")
    @classmethod
    def validate_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value cannot be blank")
        return value.strip()

    @field_validator("groups", "strategy_tags", "benchmark_tags", mode="after")
    @classmethod
    def deduplicate_tuple[T](cls, value: tuple[T, ...]) -> tuple[T, ...]:
        return _ordered_unique(value)

    @field_validator("strategy_tags", mode="before")
    @classmethod
    def normalize_strategy_tags(cls, value: Any) -> Any:
        if value is None:
            return ()
        return tuple(str(item).strip().lower() for item in value if str(item).strip())

    @field_validator("benchmark_tags", mode="before")
    @classmethod
    def normalize_benchmark_tags(cls, value: Any) -> Any:
        if value is None:
            return ()
        return tuple(str(item).strip().upper() for item in value if str(item).strip())

    @field_validator("company_id", "exposure_group", mode="before")
    @classmethod
    def normalize_optional_identifiers(cls, value: Any) -> Any:
        return _normalized_optional_identifier(value)

    @field_validator("confirmed_at")
    @classmethod
    def validate_confirmed_at(cls, value: datetime) -> datetime:
        return _aware(value, "confirmed_at")

    @model_validator(mode="after")
    def validate_weights(self) -> TickerProfile:
        if (
            self.target_weight is not None
            and self.max_weight is not None
            and self.target_weight > self.max_weight
        ):
            raise ValueError("target_weight cannot exceed max_weight")
        return self


class RoleEvidence(ClassificationModel):
    ticker: str
    category: EvidenceCategory
    score: float | None = Field(
        default=None, ge=0, le=10, allow_inf_nan=False
    )
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    reason_codes: tuple[ClassificationReasonCode, ...] = ()
    source_timestamp: datetime
    data_quality: EvidenceDataQuality
    source: EvidenceSource = EvidenceSource.MANUAL_USER_ENTRY

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: Any) -> Any:
        return _normalized_nonblank(value, uppercase=True)

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value: str) -> str:
        if not value:
            raise ValueError("ticker cannot be blank")
        return value

    @field_validator("reason_codes", mode="after")
    @classmethod
    def deduplicate_reason_codes(
        cls, value: tuple[ClassificationReasonCode, ...]
    ) -> tuple[ClassificationReasonCode, ...]:
        return _ordered_unique(value)

    @field_validator("source_timestamp")
    @classmethod
    def validate_source_timestamp(cls, value: datetime) -> datetime:
        return _aware(value, "source_timestamp")

    @model_validator(mode="after")
    def validate_score_quality(self) -> RoleEvidence:
        if self.data_quality is EvidenceDataQuality.UNAVAILABLE and self.score is not None:
            raise ValueError("UNAVAILABLE evidence must not have a score")
        if self.data_quality is EvidenceDataQuality.AVAILABLE and self.score is None:
            raise ValueError("AVAILABLE evidence requires a score")
        return self


class AxisScore(ClassificationModel):
    axis: ClassificationAxis
    score: float | None = Field(
        default=None, ge=0, le=10, allow_inf_nan=False
    )
    configured_weight: float = Field(ge=0, le=1, allow_inf_nan=False)
    contributing_categories: tuple[EvidenceCategory, ...] = ()

    @field_validator("contributing_categories", mode="after")
    @classmethod
    def deduplicate_categories(
        cls, value: tuple[EvidenceCategory, ...]
    ) -> tuple[EvidenceCategory, ...]:
        return _ordered_unique(value)


class RoleFitScore(ClassificationModel):
    role: PortfolioRole
    score: float | None = Field(
        default=None, ge=0, le=10, allow_inf_nan=False
    )


class ClassificationEvaluation(ClassificationModel):
    ticker: str
    review_mode: ReviewMode
    profile_version: int = Field(ge=1)
    current_role: PortfolioRole
    current_role_score: float | None = Field(
        default=None, ge=0, le=10, allow_inf_nan=False
    )
    axis_scores: tuple[AxisScore, ...]
    role_scores: tuple[RoleFitScore, ...]
    winning_candidate: PortfolioRole | None = None
    score_delta: float = Field(allow_inf_nan=False)
    data_completeness: float = Field(ge=0, le=1, allow_inf_nan=False)
    evidence_confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    evidence_snapshot: tuple[RoleEvidence, ...] = ()
    status: EvaluationStatus
    reason_codes: tuple[ClassificationReasonCode, ...] = ()
    created_at: datetime
    consecutive_win_count: int = Field(default=0, ge=0)
    proposal_id: UUID | None = None

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: Any) -> Any:
        return _normalized_nonblank(value, uppercase=True)

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value: str) -> str:
        if not value:
            raise ValueError("ticker cannot be blank")
        return value

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        return _aware(value, "created_at")

    @field_validator("reason_codes", mode="after")
    @classmethod
    def deduplicate_reason_codes(
        cls, value: tuple[ClassificationReasonCode, ...]
    ) -> tuple[ClassificationReasonCode, ...]:
        return _ordered_unique(value)

    @model_validator(mode="after")
    def validate_consistency(self) -> ClassificationEvaluation:
        if any(item.ticker != self.ticker for item in self.evidence_snapshot):
            raise ValueError("evidence ticker must match evaluation ticker")
        role_scores = {item.role: item.score for item in self.role_scores}
        if self.current_role not in role_scores:
            raise ValueError("role_scores must include the current role")
        if (
            role_scores[self.current_role] is None
            or self.current_role_score is None
        ):
            if role_scores[self.current_role] is not self.current_role_score:
                raise ValueError("current_role_score must match role_scores")
        elif abs(role_scores[self.current_role] - self.current_role_score) > 1e-9:
            raise ValueError("current_role_score must match role_scores")
        if (
            self.winning_candidate is not None
            and self.winning_candidate not in role_scores
        ):
            raise ValueError("winning_candidate must be present in role_scores")
        if (
            self.status is EvaluationStatus.PROPOSAL_CREATED
            and self.proposal_id is None
        ):
            raise ValueError("PROPOSAL_CREATED requires proposal_id")
        return self


class ClassificationProposal(ClassificationModel):
    id: UUID
    ticker: str
    proposal_type: ProposalType
    current_profile_snapshot: TickerProfile
    suggested_profile_snapshot: TickerProfile
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    score_delta: float = Field(allow_inf_nan=False)
    evidence_summary: tuple[RoleEvidence, ...] = ()
    reason_codes: tuple[ClassificationReasonCode, ...] = ()
    created_at: datetime
    review_status: ProposalStatus = ProposalStatus.PENDING
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    decision_reason: str | None = None
    snooze_until: datetime | None = None
    cooldown_until: datetime | None = None
    expires_at: datetime | None = None
    data_completeness: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    current_role_score: float | None = Field(
        default=None, ge=0, le=10, allow_inf_nan=False
    )
    candidate_role_scores: tuple[RoleFitScore, ...] = ()

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: Any) -> Any:
        return _normalized_nonblank(value, uppercase=True)

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value: str) -> str:
        if not value:
            raise ValueError("ticker cannot be blank")
        return value

    @field_validator("reviewed_by", "decision_reason", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> Any:
        if value is None:
            return None
        normalized = _normalized_nonblank(value)
        return normalized or None

    @field_validator("reason_codes", mode="after")
    @classmethod
    def deduplicate_reason_codes(
        cls, value: tuple[ClassificationReasonCode, ...]
    ) -> tuple[ClassificationReasonCode, ...]:
        return _ordered_unique(value)

    @field_validator(
        "created_at",
        "reviewed_at",
        "snooze_until",
        "cooldown_until",
        "expires_at",
    )
    @classmethod
    def validate_timestamps(cls, value: datetime | None, info: Any) -> datetime | None:
        return None if value is None else _aware(value, info.field_name)

    @model_validator(mode="after")
    def validate_consistency(self) -> ClassificationProposal:
        if self.current_profile_snapshot.ticker != self.ticker:
            raise ValueError("current profile ticker must match proposal ticker")
        if self.suggested_profile_snapshot.ticker != self.ticker:
            raise ValueError("suggested profile ticker must match proposal ticker")
        if any(item.ticker != self.ticker for item in self.evidence_summary):
            raise ValueError("evidence ticker must match proposal ticker")
        for field_name in (
            "reviewed_at",
            "snooze_until",
            "cooldown_until",
            "expires_at",
        ):
            value = getattr(self, field_name)
            if value is not None and value < self.created_at:
                raise ValueError(f"{field_name} cannot precede created_at")
        reviewed_statuses = {
            ProposalStatus.ACCEPTED,
            ProposalStatus.REJECTED,
            ProposalStatus.SNOOZED,
        }
        if self.review_status in reviewed_statuses and (
            self.reviewed_at is None or self.reviewed_by is None
        ):
            raise ValueError("reviewed proposals require reviewed_at and reviewed_by")
        if self.review_status is ProposalStatus.SNOOZED and self.snooze_until is None:
            raise ValueError("SNOOZED proposals require snooze_until")
        if self.review_status is ProposalStatus.PENDING and (
            self.reviewed_at is not None
            or self.reviewed_by is not None
            or self.decision_reason is not None
            or self.snooze_until is not None
        ):
            raise ValueError("PENDING proposals cannot contain review decision fields")
        return self

    @property
    def current_role(self) -> PortfolioRole:
        return self.current_profile_snapshot.primary_role

    @property
    def suggested_role(self) -> PortfolioRole:
        return self.suggested_profile_snapshot.primary_role

    @property
    def current_groups(self) -> tuple[TickerGroup, ...]:
        return self.current_profile_snapshot.groups

    @property
    def suggested_groups(self) -> tuple[TickerGroup, ...]:
        return self.suggested_profile_snapshot.groups

    @property
    def current_risk_tier(self) -> RiskTier:
        return self.current_profile_snapshot.risk_tier

    @property
    def suggested_risk_tier(self) -> RiskTier:
        return self.suggested_profile_snapshot.risk_tier


class ClassificationAuditEvent(ClassificationModel):
    id: UUID
    ticker: str
    decision_source: DecisionSource
    actor: str
    reason: str
    occurred_at: datetime
    proposal_id: UUID | None = None
    old_profile_snapshot: TickerProfile | None = None
    new_profile_snapshot: TickerProfile | None = None

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: Any) -> Any:
        return _normalized_nonblank(value, uppercase=True)

    @field_validator("ticker", "actor", "reason")
    @classmethod
    def validate_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value cannot be blank")
        return value.strip()

    @field_validator("occurred_at")
    @classmethod
    def validate_occurred_at(cls, value: datetime) -> datetime:
        return _aware(value, "occurred_at")

    @model_validator(mode="after")
    def validate_profile_tickers(self) -> ClassificationAuditEvent:
        for profile in (self.old_profile_snapshot, self.new_profile_snapshot):
            if profile is not None and profile.ticker != self.ticker:
                raise ValueError("audit profile ticker must match event ticker")
        return self


class ClassificationDecisionResult(ClassificationModel):
    profile: TickerProfile
    proposal: ClassificationProposal | None = None
    audit_event: ClassificationAuditEvent


class TickerProfileHistory(ClassificationModel):
    id: UUID
    ticker: str
    old_profile_snapshot: TickerProfile | None = None
    new_profile_snapshot: TickerProfile
    effective_from: datetime
    confirmed_at: datetime
    decision_source: DecisionSource
    proposal_id: UUID | None = None
    reason_codes: tuple[ClassificationReasonCode, ...] = ()
    evidence_snapshot: tuple[RoleEvidence, ...] = ()
    profile_version: int = Field(ge=1)

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: Any) -> Any:
        return _normalized_nonblank(value, uppercase=True)

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value: str) -> str:
        if not value:
            raise ValueError("ticker cannot be blank")
        return value

    @field_validator("reason_codes", mode="after")
    @classmethod
    def deduplicate_reason_codes(
        cls, value: tuple[ClassificationReasonCode, ...]
    ) -> tuple[ClassificationReasonCode, ...]:
        return _ordered_unique(value)

    @field_validator("effective_from", "confirmed_at")
    @classmethod
    def validate_timestamps(cls, value: datetime, info: Any) -> datetime:
        return _aware(value, info.field_name)

    @model_validator(mode="after")
    def validate_consistency(self) -> TickerProfileHistory:
        if self.new_profile_snapshot.ticker != self.ticker:
            raise ValueError("new profile ticker must match history ticker")
        if (
            self.old_profile_snapshot is not None
            and self.old_profile_snapshot.ticker != self.ticker
        ):
            raise ValueError("old profile ticker must match history ticker")
        if self.profile_version != self.new_profile_snapshot.version:
            raise ValueError("profile_version must match new profile version")
        if any(item.ticker != self.ticker for item in self.evidence_snapshot):
            raise ValueError("evidence ticker must match history ticker")
        if self.decision_source is DecisionSource.SYSTEM_INITIALIZATION:
            if self.old_profile_snapshot is not None:
                raise ValueError("initialization history cannot have an old profile")
            if self.proposal_id is not None:
                raise ValueError("initialization history cannot reference a proposal")
        elif self.old_profile_snapshot is None:
            raise ValueError("non-initialization history requires an old profile")
        return self

    @property
    def old_role(self) -> PortfolioRole | None:
        return (
            None
            if self.old_profile_snapshot is None
            else self.old_profile_snapshot.primary_role
        )

    @property
    def new_role(self) -> PortfolioRole:
        return self.new_profile_snapshot.primary_role

    @property
    def old_groups(self) -> tuple[TickerGroup, ...] | None:
        return (
            None
            if self.old_profile_snapshot is None
            else self.old_profile_snapshot.groups
        )

    @property
    def new_groups(self) -> tuple[TickerGroup, ...]:
        return self.new_profile_snapshot.groups

    @property
    def old_risk_tier(self) -> RiskTier | None:
        return (
            None
            if self.old_profile_snapshot is None
            else self.old_profile_snapshot.risk_tier
        )

    @property
    def new_risk_tier(self) -> RiskTier:
        return self.new_profile_snapshot.risk_tier
