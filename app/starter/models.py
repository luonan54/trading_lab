from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.explainability.models import (
    MissingConditionCode,
    NextTrigger,
)
from app.readiness_models import (
    CallReadiness,
    CallReadinessEvaluation,
    CallRequirementCode,
    RequirementStatus,
)
from app.states import SetupState
from app.universe import AssetClass, TickerGroup


class StarterModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EventType(StrEnum):
    EARNINGS = "EARNINGS"


class EventResultQuality(StrEnum):
    POSITIVE = "POSITIVE"
    MIXED_POSITIVE = "MIXED_POSITIVE"
    NEGATIVE = "NEGATIVE"
    UNKNOWN = "UNKNOWN"


class SelloffDriver(StrEnum):
    EXPECTATION_RESET = "EXPECTATION_RESET"
    VALUATION_RESET = "VALUATION_RESET"
    THESIS_IMPAIRMENT = "THESIS_IMPAIRMENT"
    UNKNOWN = "UNKNOWN"


class ThesisImpact(StrEnum):
    IMPROVED = "IMPROVED"
    INTACT = "INTACT"
    UNCERTAIN = "UNCERTAIN"
    IMPAIRED = "IMPAIRED"


class AssessmentSource(StrEnum):
    MANUAL_USER_ENTRY = "MANUAL_USER_ENTRY"


class EventBlockerCode(StrEnum):
    GUIDANCE_COLLAPSE = "GUIDANCE_COLLAPSE"
    ACCOUNTING_OR_REGULATORY_SHOCK = "ACCOUNTING_OR_REGULATORY_SHOCK"
    THESIS_IMPAIRMENT = "THESIS_IMPAIRMENT"
    UNRESOLVED_BINARY_CATALYST = "UNRESOLVED_BINARY_CATALYST"
    EVENT_ATTRIBUTION_UNKNOWN = "EVENT_ATTRIBUTION_UNKNOWN"
    GUIDANCE_REDUCTION = "GUIDANCE_REDUCTION"
    MATERIAL_DEMAND_WEAKNESS = "MATERIAL_DEMAND_WEAKNESS"
    MATERIAL_MARGIN_DETERIORATION = "MATERIAL_MARGIN_DETERIORATION"
    ACCOUNTING_OR_DISCLOSURE_CONCERN = "ACCOUNTING_OR_DISCLOSURE_CONCERN"
    LIQUIDITY_OR_FINANCING_CONCERN = "LIQUIDITY_OR_FINANCING_CONCERN"


class StarterEvidenceCode(StrEnum):
    PRELIMINARY_GATE_SATISFIED = "starter.evidence.preliminary_gate_satisfied"
    OPTIONS_FIT_SATISFIED = "starter.evidence.options_fit_satisfied"
    FULL_CONFIRMATION_PRESENT = "starter.evidence.full_confirmation_present"


class StarterBlockerCode(StrEnum):
    POLICY_DISABLED = "starter.blocker.policy_disabled"
    TICKER_NOT_APPROVED = "starter.blocker.ticker_not_approved"
    PROFILE_NOT_CONFIRMED = "starter.blocker.profile_not_confirmed"
    PROFILE_NOT_ENABLED_EQUITY_LEADER = (
        "starter.blocker.profile_not_enabled_equity_leader"
    )
    IDENTITY_MISMATCH = "starter.blocker.identity_mismatch"
    EQUITY_STATE_NOT_RIGHT_SIDE_REPAIR = (
        "starter.blocker.equity_state_not_right_side_repair"
    )
    TECH_SETUP_SCORE_BELOW_MINIMUM = (
        "starter.blocker.tech_setup_score_below_minimum"
    )
    LOWER_LOW_PRESENT = "starter.blocker.lower_low_present"
    READINESS_REQUIREMENTS_NOT_EXACT_STARTER = (
        "starter.blocker.readiness_requirements_not_exact_starter"
    )
    EVENT_ASSESSMENT_UNAVAILABLE = "starter.blocker.event_assessment_unavailable"
    EVENT_ASSESSMENT_EXPIRED = "starter.blocker.event_assessment_expired"
    EVENT_TYPE_NOT_ALLOWED = "starter.blocker.event_type_not_allowed"
    EVENT_RESULT_NOT_SUPPORTIVE = "starter.blocker.event_result_not_supportive"
    SELLOFF_DRIVER_NOT_SUPPORTIVE = "starter.blocker.selloff_driver_not_supportive"
    THESIS_IMPACT_NOT_SUPPORTIVE = "starter.blocker.thesis_impact_not_supportive"
    EVENT_DATA_INCOMPLETE = "starter.blocker.event_data_incomplete"
    EVENT_EVIDENCE_CONFIDENCE_LOW = (
        "starter.blocker.event_evidence_confidence_low"
    )
    BLOCKER_REVIEW_INCOMPLETE = "starter.blocker.blocker_review_incomplete"
    SOURCE_REFERENCES_MISSING = "starter.blocker.source_references_missing"
    EVENT_BLOCKERS_PRESENT = "starter.blocker.event_blockers_present"
    FULL_SETUP_RISK_BUDGET_UNAVAILABLE = (
        "starter.blocker.full_setup_risk_budget_unavailable"
    )
    LOCAL_SUPPORT_UNAVAILABLE = "starter.blocker.local_support_unavailable"
    LOCAL_RESISTANCE_UNAVAILABLE = "starter.blocker.local_resistance_unavailable"
    ATR_UNAVAILABLE = "starter.blocker.atr_unavailable"
    OPTIONS_RESULT_STALE = "starter.blocker.options_result_stale"
    OPTIONS_RESULT_MANUAL = "starter.blocker.options_result_manual"
    OPTIONS_STATUS_NOT_CANDIDATES_FOUND = (
        "starter.blocker.options_status_not_candidates_found"
    )
    OPTIONS_CANDIDATE_UNAVAILABLE = "starter.blocker.options_candidate_unavailable"
    OPTIONS_EQUITY_SNAPSHOT_MISMATCH = (
        "starter.blocker.options_equity_snapshot_mismatch"
    )
    OPTIONS_CANDIDATE_QUALITY_LOW = (
        "starter.blocker.options_candidate_quality_low"
    )
    OPTIONS_CANDIDATE_CONFIDENCE_LOW = (
        "starter.blocker.options_candidate_confidence_low"
    )
    OPTIONS_RELATIVE_IV_MISSING = "starter.blocker.options_relative_iv_missing"
    OPTIONS_RELATIVE_IV_HIGH = "starter.blocker.options_relative_iv_high"
    OPTIONS_LIQUIDITY_INVALID = "starter.blocker.options_liquidity_invalid"
    OPTIONS_SPREAD_INVALID = "starter.blocker.options_spread_invalid"
    OPTIONS_HARD_BLOCKER_PRESENT = "starter.blocker.options_hard_blocker_present"


class StarterWarningCode(StrEnum):
    INDICATIVE_OPTIONS_FEED = "starter.warning.indicative_options_feed"


class StarterEvaluationStatus(StrEnum):
    UNAVAILABLE = "UNAVAILABLE"
    BLOCKED = "BLOCKED"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    PRELIMINARY_ELIGIBLE = "PRELIMINARY_ELIGIBLE"
    SHADOW_ELIGIBLE = "SHADOW_ELIGIBLE"
    FULL_CONFIRMATION_ALREADY_AVAILABLE = "FULL_CONFIRMATION_ALREADY_AVAILABLE"


class ConfirmationQuality(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class EntryProximity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class OptionsResultSource(StrEnum):
    NORMAL = "NORMAL"
    MANUAL = "MANUAL"


class StarterOptionsFeed(StrEnum):
    INDICATIVE = "indicative"
    OPRA = "opra"


class StarterOptionsScanStatus(StrEnum):
    CANDIDATES_FOUND = "CANDIDATES_FOUND"
    NO_SUITABLE_CONTRACT = "NO_SUITABLE_CONTRACT"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    OPTIONS_DATA_UNAVAILABLE = "OPTIONS_DATA_UNAVAILABLE"


class InvalidationSource(StrEnum):
    LOCAL_SUPPORT = "LOCAL_SUPPORT"


def _ticker(value: Any) -> Any:
    return value.strip().upper() if isinstance(value, str) else value


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def _nonblank_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    result = tuple(
        dict.fromkeys(str(item).strip() for item in value if str(item).strip())
    )
    return result


class PostEventAssessmentInput(StarterModel):
    event_id: UUID
    ticker: str
    event_type: EventType
    event_at: datetime
    entered_at: datetime
    entered_by: str = Field(min_length=1, max_length=120)
    event_result_quality: EventResultQuality
    selloff_driver: SelloffDriver
    thesis_impact: ThesisImpact
    positive_reason_codes: tuple[str, ...] = ()
    negative_reason_codes: tuple[str, ...] = ()
    event_blocker_codes: tuple[EventBlockerCode, ...] = ()
    blocker_review_complete: bool
    source: Literal[AssessmentSource.MANUAL_USER_ENTRY] = (
        AssessmentSource.MANUAL_USER_ENTRY
    )
    source_references: tuple[str, ...] = Field(min_length=1)
    evidence_confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    risk_plan_id: UUID
    planned_full_setup_risk_budget_usd: float = Field(
        gt=0, allow_inf_nan=False
    )

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: Any) -> Any:
        return _ticker(value)

    @field_validator("ticker", "entered_by")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized

    @field_validator("event_at", "entered_at")
    @classmethod
    def validate_times(cls, value: datetime) -> datetime:
        return _aware(value, "assessment timestamp")

    @field_validator(
        "positive_reason_codes",
        "negative_reason_codes",
        "source_references",
        mode="before",
    )
    @classmethod
    def normalize_codes_and_references(cls, value: Any) -> tuple[str, ...]:
        return _nonblank_tuple(value)

    @field_validator("event_blocker_codes")
    @classmethod
    def deduplicate_blockers(
        cls, value: tuple[EventBlockerCode, ...]
    ) -> tuple[EventBlockerCode, ...]:
        return tuple(dict.fromkeys(value))

    @model_validator(mode="after")
    def validate_manual_entry(self) -> PostEventAssessmentInput:
        if self.event_at > self.entered_at:
            raise ValueError("event_at cannot be after entered_at")
        return self


class PostEventAssessment(PostEventAssessmentInput):
    assessment_id: UUID = Field(default_factory=uuid4)
    expires_at: datetime
    data_completeness: float = Field(ge=0, le=1, allow_inf_nan=False)
    supersedes: UUID | None = None

    @field_validator("expires_at")
    @classmethod
    def validate_expiry(cls, value: datetime) -> datetime:
        return _aware(value, "expires_at")

    @model_validator(mode="after")
    def validate_persisted_values(self) -> PostEventAssessment:
        if self.expires_at <= self.entered_at:
            raise ValueError("expires_at must be after entered_at")
        if self.assessment_id == self.supersedes:
            raise ValueError("an assessment cannot supersede itself")
        expected = self.compute_data_completeness(self)
        if abs(self.data_completeness - expected) > 1e-9:
            raise ValueError("data_completeness must be system-computed")
        return self

    @staticmethod
    def compute_data_completeness(raw: PostEventAssessmentInput) -> float:
        required_fields_complete = bool(
            raw.entered_by
            and raw.event_result_quality
            and raw.selloff_driver
            and raw.thesis_impact
            and (raw.positive_reason_codes or raw.negative_reason_codes)
        )
        checks = (
            required_fields_complete,
            bool(raw.source_references),
            raw.blocker_review_complete,
            bool(raw.risk_plan_id)
            and raw.planned_full_setup_risk_budget_usd > 0,
        )
        return sum(checks) / len(checks)

    @classmethod
    def create(
        cls,
        raw: PostEventAssessmentInput,
        *,
        assessment_valid_hours: float,
        assessment_id: UUID | None = None,
        supersedes: UUID | None = None,
    ) -> PostEventAssessment:
        if assessment_valid_hours <= 0:
            raise ValueError("assessment_valid_hours must be positive")
        return cls(
            **raw.model_dump(),
            assessment_id=assessment_id or uuid4(),
            expires_at=raw.entered_at + timedelta(hours=assessment_valid_hours),
            data_completeness=cls.compute_data_completeness(raw),
            supersedes=supersedes,
        )

    def correct(
        self,
        replacement: PostEventAssessmentInput,
        *,
        assessment_valid_hours: float,
        assessment_id: UUID | None = None,
    ) -> PostEventAssessment:
        if replacement.event_id != self.event_id:
            raise ValueError("a correction must retain the event_id")
        return self.create(
            replacement,
            assessment_valid_hours=assessment_valid_hours,
            assessment_id=assessment_id,
            supersedes=self.assessment_id,
        )

    def is_current(self, at: datetime) -> bool:
        _aware(at, "assessment comparison time")
        return self.entered_at <= at < self.expires_at


class ReadinessRequirementSnapshot(StarterModel):
    code: CallRequirementCode
    label: str
    status: RequirementStatus
    evidence: str
    blocker: str | None = None
    missing_condition: MissingConditionCode | None = None


class ReadinessSnapshot(StarterModel):
    call_readiness: CallReadiness
    requirements: tuple[ReadinessRequirementSnapshot, ...]
    supporting_evidence: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    missing_conditions: tuple[MissingConditionCode, ...] = ()
    next_trigger: NextTrigger

    @field_validator("requirements")
    @classmethod
    def unique_requirements(
        cls, value: tuple[ReadinessRequirementSnapshot, ...]
    ) -> tuple[ReadinessRequirementSnapshot, ...]:
        if len({item.code for item in value}) != len(value):
            raise ValueError("readiness requirement codes must be unique")
        return value

    @classmethod
    def from_evaluation(cls, value: CallReadinessEvaluation) -> ReadinessSnapshot:
        return cls(
            call_readiness=value.call_readiness,
            requirements=tuple(
                ReadinessRequirementSnapshot(
                    code=item.code,
                    label=item.label,
                    status=item.status,
                    evidence=item.evidence,
                    blocker=item.blocker,
                    missing_condition=item.missing_condition,
                )
                for item in value.requirements
            ),
            supporting_evidence=tuple(value.supporting_evidence),
            blockers=tuple(value.blockers),
            missing_conditions=tuple(value.missing_conditions),
            next_trigger=value.next_trigger.model_copy(deep=True),
        )


class ProfileSnapshot(StarterModel):
    ticker: str
    profile_version: int = Field(ge=1)
    confirmed: bool
    enabled: bool
    asset_class: AssetClass
    groups: frozenset[TickerGroup]

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: Any) -> Any:
        return _ticker(value)


class EquitySnapshot(StarterModel):
    snapshot_id: UUID
    ticker: str
    snapshot_at: datetime
    snapshot_price: float = Field(gt=0, allow_inf_nan=False)
    state: SetupState
    tech_setup_score: float = Field(ge=0, le=10, allow_inf_nan=False)
    lower_low: bool
    atr14: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    local_support: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    local_resistance: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    rsi14: float | None = Field(default=None, allow_inf_nan=False)
    readiness: ReadinessSnapshot

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: Any) -> Any:
        return _ticker(value)

    @field_validator("snapshot_at")
    @classmethod
    def validate_snapshot_at(cls, value: datetime) -> datetime:
        return _aware(value, "snapshot_at")


class FullSetupRiskSnapshot(StarterModel):
    risk_plan_id: UUID
    planned_full_setup_risk_budget_usd: float = Field(
        gt=0, allow_inf_nan=False
    )


class OptionCandidateFitSummary(StarterModel):
    contract_symbol: str | None = None
    mid: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    quality_score: float = Field(ge=0, le=10, allow_inf_nan=False)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    relative_iv_percentile: float | None = Field(
        default=None, ge=0, le=1, allow_inf_nan=False
    )
    liquidity_valid: bool
    spread_valid: bool
    hard_blocker_codes: tuple[str, ...] = ()

    @field_validator("hard_blocker_codes", mode="before")
    @classmethod
    def normalize_hard_blockers(cls, value: Any) -> tuple[str, ...]:
        return _nonblank_tuple(value)

    @field_validator("contract_symbol")
    @classmethod
    def normalize_contract_symbol(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("contract_symbol cannot be blank")
        return normalized


class OptionsFitSummary(StarterModel):
    options_scan_id: UUID
    ticker: str
    equity_snapshot_id: UUID
    result_at: datetime
    result_source: OptionsResultSource
    scan_status: StarterOptionsScanStatus
    feed: StarterOptionsFeed
    candidate: OptionCandidateFitSummary | None = None

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: Any) -> Any:
        return _ticker(value)

    @field_validator("result_at")
    @classmethod
    def validate_result_at(cls, value: datetime) -> datetime:
        return _aware(value, "result_at")


class StarterPolicyInput(StarterModel):
    evaluated_at: datetime
    profile: ProfileSnapshot
    equity: EquitySnapshot
    event_assessment: PostEventAssessment | None
    full_setup_risk: FullSetupRiskSnapshot | None
    options_fit: OptionsFitSummary | None = None

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, value: datetime) -> datetime:
        return _aware(value, "evaluated_at")


class ConfirmationSummary(StarterModel):
    quality: ConfirmationQuality
    passed_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    lower_low: bool


class ProximitySummary(StarterModel):
    quality: EntryProximity
    resistance_distance_atr: float | None = Field(
        default=None, allow_inf_nan=False
    )
    resistance_distance_pct: float | None = Field(
        default=None, allow_inf_nan=False
    )
    invalidation_distance_atr: float | None = Field(
        default=None, allow_inf_nan=False
    )
    invalidation_distance_pct: float | None = Field(
        default=None, allow_inf_nan=False
    )


class StructuredInvalidation(StarterModel):
    source: Literal[InvalidationSource.LOCAL_SUPPORT] = (
        InvalidationSource.LOCAL_SUPPORT
    )
    level: float = Field(gt=0, allow_inf_nan=False)


class StarterPolicyEvaluation(StarterModel):
    evaluation_id: UUID = Field(default_factory=uuid4)
    status: StarterEvaluationStatus
    ticker: str
    created_at: datetime
    event_assessment_id: UUID | None
    equity_snapshot_id: UUID
    snapshot_at: datetime
    snapshot_price: float
    policy_version: str
    profile_version: int
    readiness_snapshot: ReadinessSnapshot
    evidence: tuple[StarterEvidenceCode, ...] = ()
    blocker_codes: tuple[StarterBlockerCode, ...] = ()
    warning_codes: tuple[StarterWarningCode, ...] = ()
    confirmation: ConfirmationSummary
    proximity: ProximitySummary
    max_risk_fraction_of_full_setup: float = Field(gt=0, le=1)
    max_starter_risk_usd: float | None = Field(
        default=None, gt=0, allow_inf_nan=False
    )
    invalidation: StructuredInvalidation | None
    confirmation_trigger: NextTrigger
    options_scan_id: UUID | None = None
    options_fit_summary: OptionsFitSummary | None = None
    full_execution_qualified: Literal[False] = False

    @property
    def shadow_eligible(self) -> bool:
        return self.status is StarterEvaluationStatus.SHADOW_ELIGIBLE

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: Any) -> Any:
        return _ticker(value)


class StarterOutcomeObservation(StarterModel):
    observation_id: UUID = Field(default_factory=uuid4)
    evaluation_id: UUID
    observed_at: datetime
    elapsed_days: float = Field(ge=0, allow_inf_nan=False)
    underlying_price: float | None = Field(
        default=None, gt=0, allow_inf_nan=False
    )
    option_symbol: str | None = None
    option_mid: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    strict_readiness: CallReadiness
    invalidation_observed: bool | None = None
    equity_snapshot_id: UUID | None = None
    options_scan_id: UUID | None = None
    baseline: bool = False

    @field_validator("observed_at")
    @classmethod
    def validate_observed_at(cls, value: datetime) -> datetime:
        return _aware(value, "observed_at")

    @field_validator("option_symbol")
    @classmethod
    def normalize_option_symbol(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("option_symbol cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_option_mark(self) -> StarterOutcomeObservation:
        if self.option_mid is not None and self.option_symbol is None:
            raise ValueError("option_mid requires option_symbol")
        if self.baseline and self.elapsed_days != 0:
            raise ValueError("baseline observation must use elapsed_days=0")
        return self


# Stable aliases for integration callers.
EventResult = EventResultQuality
EventBlocker = EventBlockerCode
StarterBlocker = StarterBlockerCode
StarterWarning = StarterWarningCode
StarterReason = StarterEvidenceCode
StarterReadinessInput = ReadinessSnapshot
StarterReadinessRequirement = ReadinessRequirementSnapshot
StarterProfileInput = ProfileSnapshot
StarterEquityInput = EquitySnapshot
FrozenFullSetupRiskInput = FullSetupRiskSnapshot
StarterOptionsInput = OptionsFitSummary
StarterOptionCandidateFit = OptionCandidateFitSummary
StarterEvaluationInput = StarterPolicyInput
StarterEvaluation = StarterPolicyEvaluation
