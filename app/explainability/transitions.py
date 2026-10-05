from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator, model_validator

from app.explainability.models import (
    Invalidation,
    NextTrigger,
    ReasonCode,
    SetupExplanation,
)
from app.states import SetupState

if TYPE_CHECKING:
    from app.models import ScanSnapshot


def derive_transition_reasons(
    *,
    state_changed: bool,
    previous_explanation: SetupExplanation | None,
    current_explanation: SetupExplanation,
) -> list[ReasonCode]:
    if not state_changed:
        return []
    if previous_explanation is None:
        return list(current_explanation.reasons)
    prior_reasons = set(previous_explanation.reasons)
    newly_present = [
        reason
        for reason in current_explanation.reasons
        if reason not in prior_reasons
    ]
    return newly_present or list(current_explanation.reasons)


class SetupTransitionPayload(BaseModel):
    ticker: str
    previous_state: SetupState
    current_state: SetupState
    ceg_tech_score: float = Field(ge=0, le=10)
    transition_reasons: list[ReasonCode] = Field(min_length=1)
    next_trigger: NextTrigger
    invalidation: Invalidation | None
    timestamp: datetime

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("ticker")
    @classmethod
    def validate_ticker(cls, value: str) -> str:
        if not value:
            raise ValueError("ticker cannot be blank")
        return value

    @field_validator("transition_reasons")
    @classmethod
    def ordered_deduplicate_reasons(
        cls, values: list[ReasonCode]
    ) -> list[ReasonCode]:
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_state_change(self) -> "SetupTransitionPayload":
        if self.previous_state is self.current_state:
            raise ValueError("transition payload requires an actual state change")
        return self


def build_transition_payload(
    snapshot: ScanSnapshot,
) -> SetupTransitionPayload | None:
    if (
        not snapshot.state_changed
        or snapshot.previous_state is None
        or snapshot.explanation is None
        or not snapshot.transition_reasons
    ):
        return None
    return SetupTransitionPayload(
        ticker=snapshot.ticker,
        previous_state=snapshot.previous_state,
        current_state=snapshot.current_state,
        ceg_tech_score=snapshot.ceg_tech_score,
        transition_reasons=snapshot.transition_reasons,
        next_trigger=snapshot.explanation.next_trigger,
        invalidation=snapshot.explanation.invalidation,
        timestamp=snapshot.scanned_at,
    )
