from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, field_validator, model_validator

from app.starter.models import EventType, StarterModel


class StarterMode(StrEnum):
    SHADOW = "SHADOW"


APPROVED_TICKERS: frozenset[str] = frozenset()


class StarterOptionsGates(StarterModel):
    require_relative_iv: bool = True
    require_non_manual_result: bool = True
    max_result_age_minutes: float = Field(
        default=30.0, gt=0, allow_inf_nan=False
    )
    min_candidate_quality: float = Field(
        default=7.0, ge=0, le=10, allow_inf_nan=False
    )
    min_candidate_confidence: float = Field(
        default=0.8, ge=0, le=1, allow_inf_nan=False
    )
    max_relative_iv_percentile: float = Field(
        default=0.8, ge=0, le=1, allow_inf_nan=False
    )
    require_valid_liquidity: bool = True
    require_valid_spread: bool = True
    require_no_hard_blockers: bool = True


class StarterProximityThresholds(StarterModel):
    medium_atr: float = Field(default=0.25, ge=0, allow_inf_nan=False)
    high_atr: float = Field(default=0.75, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_order(self) -> StarterProximityThresholds:
        if self.medium_atr >= self.high_atr:
            raise ValueError("medium_atr must be less than high_atr")
        return self


class StarterConfigV1(StarterModel):
    policy_version: Literal["starter-shadow-v1"] = "starter-shadow-v1"
    mode: Literal[StarterMode.SHADOW] = StarterMode.SHADOW
    enabled: bool = False
    approved_tickers: frozenset[str] = APPROVED_TICKERS
    allowed_event_types: frozenset[EventType] = frozenset({EventType.EARNINGS})
    assessment_valid_hours: float = Field(
        default=168.0, gt=0, allow_inf_nan=False
    )
    min_tech_setup_score: float = Field(
        default=8.0, ge=0, le=10, allow_inf_nan=False
    )
    min_event_data_completeness: float = Field(
        default=0.8, ge=0, le=1, allow_inf_nan=False
    )
    min_event_evidence_confidence: float = Field(
        default=0.75, ge=0, le=1, allow_inf_nan=False
    )
    max_risk_fraction_of_full_setup: float = Field(
        default=0.25, gt=0, le=1, allow_inf_nan=False
    )
    proximity: StarterProximityThresholds = Field(
        default_factory=StarterProximityThresholds
    )
    options: StarterOptionsGates = Field(
        default_factory=StarterOptionsGates
    )

    @property
    def options_gates(self) -> StarterOptionsGates:
        return self.options

    @field_validator("approved_tickers", mode="before")
    @classmethod
    def normalize_tickers(cls, value: object) -> object:
        if value is None:
            return frozenset()
        return frozenset(
            str(item).strip().upper() for item in value if str(item).strip()
        )

    @model_validator(mode="after")
    def validate_v1_contract(self) -> StarterConfigV1:
        if self.allowed_event_types != {EventType.EARNINGS}:
            raise ValueError("Starter V1 allows EARNINGS only")
        return self


DEFAULT_STARTER_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "starter.yaml"
)


def load_starter_config(
    path: str | Path = DEFAULT_STARTER_CONFIG_PATH,
) -> StarterConfigV1:
    with Path(path).open(encoding="utf-8") as stream:
        payload = yaml.safe_load(stream) or {}
    if not isinstance(payload, dict):
        raise ValueError("starter config root must be a mapping")
    return StarterConfigV1.model_validate(payload)


StarterConfig = StarterConfigV1
StarterOptionsConfig = StarterOptionsGates
StarterProximityConfig = StarterProximityThresholds
