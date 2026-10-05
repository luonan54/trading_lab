from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
import math
from typing import Any
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from app.models import SetupState


class OptionType(StrEnum):
    CALL = "CALL"
    PUT = "PUT"


class EligibilityStatus(StrEnum):
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    ELIGIBLE = "ELIGIBLE"
    RESEARCH_ELIGIBLE = "RESEARCH_ELIGIBLE"
    EXECUTION_QUALIFIED = "EXECUTION_QUALIFIED"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"


class ContractFilterStatus(StrEnum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DeltaRangeStatus(StrEnum):
    PREFERRED = "PREFERRED"
    ACCEPTABLE = "ACCEPTABLE"
    MISSING = "MISSING"
    OUTSIDE = "OUTSIDE"


class MoneynessStatus(StrEnum):
    ATM_OR_ITM = "ATM_OR_ITM"
    ACCEPTABLE_OTM = "ACCEPTABLE_OTM"
    TOO_FAR_OTM = "TOO_FAR_OTM"
    INVALID = "INVALID"


class EventDataStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class DataQualityFlag(StrEnum):
    MISSING_QUOTE = "MISSING_QUOTE"
    MISSING_QUOTE_TIMESTAMP = "MISSING_QUOTE_TIMESTAMP"
    MISSING_GREEKS = "MISSING_GREEKS"
    MISSING_IV = "MISSING_IV"
    MISSING_OPEN_INTEREST = "MISSING_OPEN_INTEREST"
    MISSING_VOLUME = "MISSING_VOLUME"
    STALE_QUOTE = "STALE_QUOTE"
    CROSSED_MARKET = "CROSSED_MARKET"
    ZERO_BID = "ZERO_BID"
    INVALID_BID = "INVALID_BID"
    INVALID_ASK = "INVALID_ASK"
    INVALID_UNDERLYING_PRICE = "INVALID_UNDERLYING_PRICE"
    INVALID_STRIKE = "INVALID_STRIKE"
    INVALID_DTE = "INVALID_DTE"
    INVALID_IV = "INVALID_IV"
    INVALID_OPEN_INTEREST = "INVALID_OPEN_INTEREST"
    INVALID_VOLUME = "INVALID_VOLUME"
    WIDE_SPREAD = "WIDE_SPREAD"
    HIGH_RELATIVE_IV = "HIGH_RELATIVE_IV"
    INSUFFICIENT_RELATIVE_IV_SAMPLE = "INSUFFICIENT_RELATIVE_IV_SAMPLE"
    NEAR_TERM_EARNINGS_RISK = "NEAR_TERM_EARNINGS_RISK"
    EARNINGS_WITHIN_CONTRACT_LIFE = "EARNINGS_WITHIN_CONTRACT_LIFE"
    EARNINGS_DATA_UNAVAILABLE = "EARNINGS_DATA_UNAVAILABLE"


class OptionCandidateStatus(StrEnum):
    TOP_CANDIDATE = "TOP_CANDIDATE"
    ACCEPTABLE = "ACCEPTABLE"


class OptionsScanStatus(StrEnum):
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    OPTIONS_DATA_UNAVAILABLE = "OPTIONS_DATA_UNAVAILABLE"
    NO_SUITABLE_CONTRACT = "NO_SUITABLE_CONTRACT"
    CANDIDATES_FOUND = "CANDIDATES_FOUND"


class ProviderErrorKind(StrEnum):
    CREDENTIALS_MISSING = "CREDENTIALS_MISSING"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    ENTITLEMENT_REQUIRED = "ENTITLEMENT_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    SERVER_ERROR = "SERVER_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    PAGINATION_LIMIT = "PAGINATION_LIMIT"


class ProviderResponseMetadata(BaseModel):
    endpoint: str
    request_id: str | None = None
    status_code: int = Field(ge=100, le=599)
    rate_limit_remaining: int | None = Field(default=None, ge=0)
    rate_limit_reset: str | None = None
    response_time_ms: float = Field(ge=0, allow_inf_nan=False)
    fetched_at: datetime
    cache_hit: bool = False
    source_age_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)

    @field_validator("fetched_at")
    @classmethod
    def validate_fetched_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("provider response timestamps must be timezone-aware")
        return value


class ProviderErrorMetadata(BaseModel):
    kind: ProviderErrorKind
    feed: str
    status_code: int | None = Field(default=None, ge=100, le=599)
    request_id: str | None = None
    retry_after: str | None = None
    rate_limit_remaining: int | None = Field(default=None, ge=0)
    rate_limit_reset: str | None = None
    response_time_ms: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )


class OptionChainMetadata(BaseModel):
    provider_name: str
    feed: str
    responses: list[ProviderResponseMetadata] = Field(default_factory=list)
    request_count: int = Field(default=0, ge=0)
    cache_hits: int = Field(default=0, ge=0)
    cache_misses: int = Field(default=0, ge=0)
    malformed_items: int = Field(default=0, ge=0)
    malformed_item_messages: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_age_seconds: float = Field(default=0, ge=0, allow_inf_nan=False)


class OptionChainResult(BaseModel):
    contracts: list["OptionContract"] = Field(default_factory=list)
    metadata: OptionChainMetadata


class OptionContract(BaseModel):
    ticker: str
    contract_symbol: str
    option_type: OptionType
    expiration: date
    dte: int
    strike: float
    underlying_price: float

    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    last: float | None = None
    spread_abs: float | None = None
    spread_pct: float | None = None

    volume: int | None = None
    open_interest: int | None = None

    implied_volatility: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None

    moneyness_pct: float | None = Field(
        default=None,
        description=(
            "Signed call convention: (underlying - strike) / underlying; "
            "positive is in the money and negative is out of the money."
        ),
    )
    intrinsic_value: float | None = None
    extrinsic_value: float | None = None
    breakeven_at_expiration: float | None = None

    quote_timestamp: datetime | None = None
    trade_timestamp: datetime | None = None
    data_provider: str
    earnings_date: date | None = None
    event_data_status: EventDataStatus = EventDataStatus.UNAVAILABLE
    chain_relative_iv_percentile: float | None = None
    delta_range_status: DeltaRangeStatus | None = None
    moneyness_status: MoneynessStatus | None = None

    filter_status: ContractFilterStatus = ContractFilterStatus.PENDING
    data_quality_flags: list[DataQualityFlag] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    rejection_reasons: list[str] = Field(default_factory=list)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("ticker must not be empty")
        return normalized

    @field_validator("contract_symbol")
    @classmethod
    def validate_contract_symbol(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("contract_symbol must not be empty")
        return normalized

    @field_validator("data_provider")
    @classmethod
    def validate_data_provider(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("data_provider must not be empty")
        return normalized

    @field_validator("quote_timestamp", "trade_timestamp")
    @classmethod
    def validate_market_timestamp(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("market timestamps must be timezone-aware")
        return value

    @field_validator(
        "strike",
        "underlying_price",
        "bid",
        "ask",
        "mid",
        "last",
        "spread_abs",
        "spread_pct",
        "implied_volatility",
        "delta",
        "gamma",
        "theta",
        "vega",
        "moneyness_pct",
        "intrinsic_value",
        "extrinsic_value",
        "breakeven_at_expiration",
        "chain_relative_iv_percentile",
    )
    @classmethod
    def validate_finite_numeric(
        cls, value: float | None
    ) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("option contract numeric values must be finite")
        return value


class EligibilityDecision(BaseModel):
    ticker: str
    status: EligibilityStatus
    eligible: bool
    manual_override: bool
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def research_eligible(self) -> bool:
        return self.eligible

    @computed_field
    @property
    def execution_qualified(self) -> bool:
        return self.status is EligibilityStatus.EXECUTION_QUALIFIED


class FilterStageCount(BaseModel):
    stage: str
    evaluated: int = Field(ge=0)
    passed: int = Field(ge=0)
    rejected: int = Field(ge=0)


class OptionFilterResult(BaseModel):
    total: int = Field(ge=0)
    accepted: list[OptionContract]
    rejected: list[OptionContract]
    stage_counts: list[FilterStageCount]


class OptionsScoreBreakdown(BaseModel):
    delta_fit: float = Field(ge=0, le=2, allow_inf_nan=False)
    dte_fit: float = Field(ge=0, le=2, allow_inf_nan=False)
    liquidity: float = Field(ge=0, le=2, allow_inf_nan=False)
    iv_quality: float = Field(ge=0, le=2, allow_inf_nan=False)
    moneyness: float = Field(ge=0, le=2, allow_inf_nan=False)
    total: float = Field(ge=0, le=10, allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def compute_total(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        result = dict(value)
        components = (
            "delta_fit",
            "dte_fit",
            "liquidity",
            "iv_quality",
            "moneyness",
        )
        if "total" not in result and all(name in result for name in components):
            result["total"] = round(
                sum(float(result[name]) for name in components), 4
            )
        return result

    @model_validator(mode="after")
    def validate_total(self) -> "OptionsScoreBreakdown":
        expected = round(
            self.delta_fit
            + self.dte_fit
            + self.liquidity
            + self.iv_quality
            + self.moneyness,
            4,
        )
        if abs(self.total - expected) > 1e-4:
            raise ValueError("score breakdown total must equal its five components")
        return self


class ScoredOptionCandidate(BaseModel):
    contract: OptionContract
    breakdown: OptionsScoreBreakdown
    options_quality_score: float = Field(ge=0, le=10, allow_inf_nan=False)
    options_score_confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    combined_score: float = Field(ge=0, le=10, allow_inf_nan=False)
    status: OptionCandidateStatus = OptionCandidateStatus.ACCEPTABLE
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    confidence_penalties: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_score_consistency(self) -> "ScoredOptionCandidate":
        if abs(self.options_quality_score - self.breakdown.total) > 1e-4:
            raise ValueError(
                "options_quality_score must equal score breakdown total"
            )
        return self


class OptionsScanResult(BaseModel):
    scan_id: UUID = Field(default_factory=uuid4)
    scanned_at: datetime
    provider_timestamp: datetime | None = None
    ticker: str
    equity_snapshot_at: datetime | None = None
    underlying_price: float = Field(gt=0, allow_inf_nan=False)
    equity_state: SetupState
    equity_score: float = Field(ge=0, le=10, allow_inf_nan=False)
    eligibility: EligibilityDecision
    status: OptionsScanStatus
    provider_name: str | None = None
    feed: str | None = None
    data_age_seconds: float | None = Field(
        default=None, ge=0, allow_inf_nan=False
    )
    accepted_candidates: list[ScoredOptionCandidate] = Field(
        default_factory=list
    )
    accepted_contracts: list[OptionContract] = Field(default_factory=list)
    rejected_contracts: list[OptionContract] = Field(default_factory=list)
    stage_counts: list[FilterStageCount] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    request_count: int = Field(default=0, ge=0)
    cache_hits: int = Field(default=0, ge=0)
    cache_misses: int = Field(default=0, ge=0)
    error_status: str | None = None
    error_message: str | None = None
    provider_error: ProviderErrorMetadata | None = None
    provider_metadata: OptionChainMetadata | None = None
    equity_weight: float = Field(default=0.70, ge=0, le=1)
    options_weight: float = Field(default=0.30, ge=0, le=1)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("ticker must not be empty")
        return normalized

    @field_validator("provider_name", "feed")
    @classmethod
    def normalize_optional_metadata(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("provider and feed metadata must not be empty")
        return normalized

    @field_validator("scanned_at", "provider_timestamp", "equity_snapshot_at")
    @classmethod
    def validate_aware_timestamp(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("scan and provider timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_result_consistency(self) -> "OptionsScanResult":
        if abs(self.equity_weight + self.options_weight - 1.0) > 1e-9:
            raise ValueError("scan result score weights must total 1.0")
        if self.eligibility.ticker.strip().upper() != self.ticker:
            raise ValueError("eligibility ticker must match scan ticker")

        all_contracts = [
            *(candidate.contract for candidate in self.accepted_candidates),
            *self.accepted_contracts,
            *self.rejected_contracts,
        ]
        for contract in all_contracts:
            if contract.ticker != self.ticker:
                raise ValueError("every contract ticker must match scan ticker")
            if (
                abs(contract.underlying_price - self.underlying_price)
                > max(1e-6, self.underlying_price * 1e-6)
            ):
                raise ValueError(
                    "every contract underlying price must match the scan"
                )
        for contract in self.rejected_contracts:
            if not contract.rejection_reasons:
                raise ValueError("rejected contracts must include reasons")
        accepted_symbols = {
            contract.contract_symbol for contract in self.accepted_contracts
        }
        if accepted_symbols and any(
            candidate.contract.contract_symbol not in accepted_symbols
            for candidate in self.accepted_candidates
        ):
            raise ValueError("every candidate must be present in accepted_contracts")

        for candidate in self.accepted_candidates:
            expected = round(
                self.equity_weight * self.equity_score
                + self.options_weight * candidate.options_quality_score,
                4,
            )
            if abs(candidate.combined_score - expected) > 1e-4:
                raise ValueError(
                    "candidate combined_score is inconsistent with scan weights"
                )
        if self.accepted_candidates:
            if (
                self.accepted_candidates[0].status
                is not OptionCandidateStatus.TOP_CANDIDATE
            ):
                raise ValueError("first accepted candidate must be TOP_CANDIDATE")
            if any(
                candidate.status is not OptionCandidateStatus.ACCEPTABLE
                for candidate in self.accepted_candidates[1:]
            ):
                raise ValueError(
                    "only the first accepted candidate may be TOP_CANDIDATE"
                )

        if self.status is OptionsScanStatus.CANDIDATES_FOUND:
            if not self.eligibility.eligible or not self.accepted_candidates:
                raise ValueError(
                    "CANDIDATES_FOUND requires eligibility and candidates"
                )
        elif self.status is OptionsScanStatus.NO_SUITABLE_CONTRACT:
            if not self.eligibility.eligible or self.accepted_candidates:
                raise ValueError(
                    "NO_SUITABLE_CONTRACT requires eligibility and no candidates"
                )
        elif self.status is OptionsScanStatus.NOT_ELIGIBLE:
            if self.eligibility.eligible or self.accepted_candidates:
                raise ValueError(
                    "NOT_ELIGIBLE requires an ineligible decision and no candidates"
                )
        elif self.status is OptionsScanStatus.MANUAL_OVERRIDE:
            if not (
                self.eligibility.eligible and self.eligibility.manual_override
            ):
                raise ValueError(
                    "MANUAL_OVERRIDE requires a manual override decision"
                )
        elif self.status is OptionsScanStatus.OPTIONS_DATA_UNAVAILABLE:
            if self.accepted_candidates:
                raise ValueError(
                    "OPTIONS_DATA_UNAVAILABLE cannot include candidates"
                )
            if not self.error_status or not self.error_message:
                raise ValueError(
                    "OPTIONS_DATA_UNAVAILABLE requires error status and message"
                )

        if self.status is not OptionsScanStatus.OPTIONS_DATA_UNAVAILABLE and (
            self.error_status is not None or self.error_message is not None
        ):
            raise ValueError(
                "error status and message are reserved for unavailable data"
            )
        if (
            self.provider_error is not None
            and self.status is not OptionsScanStatus.OPTIONS_DATA_UNAVAILABLE
        ):
            raise ValueError(
                "provider_error metadata is reserved for unavailable data"
            )
        if self.status in {
            OptionsScanStatus.CANDIDATES_FOUND,
            OptionsScanStatus.NO_SUITABLE_CONTRACT,
        } and self.provider_timestamp is None:
            raise ValueError(
                "completed contract analysis requires a provider timestamp"
            )
        if self.status in {
            OptionsScanStatus.CANDIDATES_FOUND,
            OptionsScanStatus.NO_SUITABLE_CONTRACT,
        } and (
            self.provider_name is None
            or self.feed is None
            or self.data_age_seconds is None
        ):
            raise ValueError(
                "completed contract analysis requires provider/feed/data-age metadata"
            )
        return self

    @property
    def candidates(self) -> list[ScoredOptionCandidate]:
        return self.accepted_candidates


class QualifiedOptionAlertPayload(BaseModel):
    scan_id: UUID
    qualified_at: datetime
    ticker: str
    equity_state: SetupState
    equity_score: float = Field(ge=0, le=10, allow_inf_nan=False)
    eligibility: EligibilityDecision
    candidate: ScoredOptionCandidate
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("ticker")
    @classmethod
    def normalize_alert_ticker(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("ticker must not be empty")
        return normalized

    @field_validator("qualified_at")
    @classmethod
    def validate_qualified_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("qualified_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_qualified_contract(self) -> "QualifiedOptionAlertPayload":
        if (
            not self.eligibility.execution_qualified
            or self.eligibility.ticker.strip().upper() != self.ticker
        ):
            raise ValueError(
                "qualified alert payload requires matching execution-qualified equity"
            )
        if self.candidate.contract.ticker != self.ticker:
            raise ValueError("candidate ticker must match alert ticker")
        if self.candidate.status is not OptionCandidateStatus.TOP_CANDIDATE:
            raise ValueError(
                "qualified alert payload requires the top configured-fit candidate"
            )
        return self

    @classmethod
    def from_scan_result(
        cls, result: OptionsScanResult
    ) -> "QualifiedOptionAlertPayload":
        if result.status is not OptionsScanStatus.CANDIDATES_FOUND:
            raise ValueError(
                "qualified alert payload requires CANDIDATES_FOUND"
            )
        return cls(
            scan_id=result.scan_id,
            qualified_at=result.scanned_at,
            ticker=result.ticker,
            equity_state=result.equity_state,
            equity_score=result.equity_score,
            eligibility=result.eligibility,
            candidate=result.accepted_candidates[0],
            reasons=result.eligibility.reasons,
            warnings=result.warnings,
        )


OptionsAlertPayload = QualifiedOptionAlertPayload
CandidateStatus = OptionCandidateStatus
ScanResultStatus = OptionsScanStatus
