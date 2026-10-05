from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from app.explainability.models import ReasonCode, SetupExplanation
from app.entry_models import EntryEvaluation
from app.readiness_models import CallReadinessEvaluation
from app.states import SetupState


class TechnicalFeatures(BaseModel):
    current_price: float
    daily_return_pct: float
    return_15m_pct: float
    previous_close: float | None = Field(
        default=None, gt=0, allow_inf_nan=False
    )
    session_open: float | None = Field(
        default=None, gt=0, allow_inf_nan=False
    )
    session_date: date | None = None
    today_return_pct: float | None = Field(
        default=None, allow_inf_nan=False
    )
    vwap: float
    ema9: float
    ema20: float
    rsi14: float
    macd: float
    macd_signal: float
    atr14: float
    support: float
    resistance: float
    local_support: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    local_resistance: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    major_swing_support: float | None = Field(
        default=None, gt=0, allow_inf_nan=False
    )
    major_swing_resistance: float | None = Field(
        default=None, gt=0, allow_inf_nan=False
    )
    drawdown_pct: float
    higher_low: bool
    lower_low: bool
    two_bar_acceptance: bool
    two_bar_reclaim: bool


class Classification(BaseModel):
    state: SetupState
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]
    invalidation_conditions: list[str]


class ScanSnapshot(BaseModel):
    ticker: str
    scanned_at: datetime
    displayed_at_et: str
    previous_state: SetupState | None
    current_state: SetupState
    state_changed: bool
    score: float = Field(ge=0, le=10)
    score_change: float | None
    company_quality: float = Field(ge=0, le=10)
    options_quality: None = None
    benchmark_confirmed: bool
    confidence: float = Field(ge=0, le=1)
    reasons: list[str]
    invalidation_conditions: list[str]
    features: TechnicalFeatures
    explanation: SetupExplanation | None = None
    call_readiness: CallReadinessEvaluation | None = None
    entry_plan: EntryEvaluation | None = None
    transition_reasons: list[ReasonCode] = Field(default_factory=list)

    @field_validator("transition_reasons")
    @classmethod
    def ordered_deduplicate_transition_reasons(
        cls, values: list[ReasonCode]
    ) -> list[ReasonCode]:
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_explanation_identity(self) -> "ScanSnapshot":
        if self.explanation is not None and (
            self.explanation.ticker != self.ticker.upper()
            or self.explanation.state is not self.current_state
        ):
            raise ValueError(
                "explanation ticker and state must match the scan snapshot"
            )
        return self

    @computed_field
    @property
    def ceg_tech_score(self) -> float:
        return self.score


class HealthResponse(BaseModel):
    status: str
    database: str
    alpaca_credentials_configured: bool
    data_feed: str
    feed_note: str
