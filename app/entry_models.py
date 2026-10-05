from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


class EntryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    min_reward_risk: float = Field(default=2.0, gt=0)
    max_extension_atr: float = Field(default=0.3, gt=0)
    max_stop_distance_atr: float = Field(default=1.0, gt=0)
    min_stop_noise_atr: float = Field(default=1.0, gt=0)
    stop_buffer_atr: float = Field(default=0.25, gt=0)
    max_daily_ema_extension_atr: float = Field(default=1.5, gt=0)
    confirmation_bars: int = Field(default=2, ge=2, le=4)
    consolidation_bars: int = Field(default=20, ge=10, le=52)
    max_base_width_atr: float = Field(default=1.0, gt=0)
    max_base_drift_atr: float = Field(default=0.4, ge=0)
    retest_tolerance_atr: float = Field(default=0.1, ge=0)
    max_bar_age_minutes: int = Field(default=30, ge=1, le=60)
    max_setup_age_days: int = Field(default=10, ge=1, le=14)


class EntrySetup(StrEnum):
    BREAKOUT = "BREAKOUT"
    BREAKOUT_RETEST = "BREAKOUT_RETEST"
    SUPPORT_RECLAIM = "SUPPORT_RECLAIM"


class EntryStatus(StrEnum):
    READY = "ENTRY_PLAN_READY"
    WAIT_CONFIRMATION = "WAIT_CONFIRMATION"
    WAIT_PULLBACK = "WAIT_PULLBACK"
    INSUFFICIENT_REWARD = "INSUFFICIENT_REWARD"
    INVALIDATED = "INVALIDATED"
    UNAVAILABLE = "DATA_UNAVAILABLE"
    STALE = "STALE"


class EntryAnchor(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    setup_type: EntrySetup
    formed_at: datetime
    reference_level: float = Field(gt=0)
    invalidation_level: float = Field(gt=0)
    target_level: float | None = Field(default=None, gt=0)
    target_source: str = "Confirmed daily pivot high before setup"
    reference_source: str

    @field_validator("formed_at")
    @classmethod
    def aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("entry timestamps must be timezone-aware")
        return value


class EntryEvaluation(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    status: EntryStatus
    evaluated_at: datetime
    price_as_of: datetime | None = None
    expires_at: datetime | None = None
    invalidated_at: datetime | None = None
    entry_price: float | None = Field(default=None, gt=0)
    anchor: EntryAnchor | None = None
    entry_zone_low: float | None = Field(default=None, gt=0)
    entry_zone_high: float | None = Field(default=None, gt=0)
    risk_per_share: float | None = Field(default=None, gt=0)
    reward_per_share: float | None = Field(default=None, gt=0)
    reward_risk: float | None = Field(default=None, gt=0)
    daily_atr: float | None = Field(default=None, gt=0)
    intraday_atr: float | None = Field(default=None, gt=0)
    extension_atr: float | None = None
    daily_trend_confirmed: bool = False
    bar_confirmation: bool = False
    relative_strength_pct: float | None = None
    momentum_rsi: float = Field(default=50, ge=0, le=100)
    policy: EntryPolicy = Field(default_factory=EntryPolicy)
    blockers: list[str] = Field(default_factory=list)
    next_trigger: str

    @field_validator("evaluated_at", "price_as_of", "expires_at", "invalidated_at")
    @classmethod
    def aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() is None
        ):
            raise ValueError("entry timestamps must be timezone-aware")
        return value

    @computed_field
    @property
    def ready(self) -> bool:
        return (
            self.status is EntryStatus.READY
            and not self.blockers
            and self.anchor is not None
            and self.reward_risk is not None
            and self.reward_risk >= self.policy.min_reward_risk
            and self.daily_trend_confirmed
            and self.bar_confirmation
        )
