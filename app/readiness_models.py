from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, computed_field

from app.explainability.models import MissingConditionCode, NextTrigger


class CallReadiness(StrEnum):
    NOT_READY = "NOT_READY"
    DEVELOPING = "DEVELOPING"
    NEAR_QUALIFICATION = "NEAR_QUALIFICATION"
    QUALIFIED = "QUALIFIED"


class RequirementStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class CallRequirementCode(StrEnum):
    LEADER_WORKFLOW_ENABLED = "LEADER_WORKFLOW_ENABLED"
    PRIOR_REPAIR_CONTEXT = "PRIOR_REPAIR_CONTEXT"
    HIGHER_LOW = "HIGHER_LOW"
    COMPLETED_BAR_CONFIRMATION = "COMPLETED_BAR_CONFIRMATION"
    BENCHMARK_CONFIRMATION = "BENCHMARK_CONFIRMATION"
    MOMENTUM_CONFIRMATION = "MOMENTUM_CONFIRMATION"
    ENTRY_PLAN = "ENTRY_PLAN"


class CallReadinessRequirement(BaseModel):
    code: CallRequirementCode
    label: str = Field(min_length=1, max_length=80)
    status: RequirementStatus
    evidence: str = Field(min_length=1, max_length=240)
    blocker: str | None = Field(default=None, min_length=1, max_length=240)
    missing_condition: MissingConditionCode | None = None

    @computed_field
    @property
    def passed(self) -> bool:
        return self.status is RequirementStatus.PASS


class CallReadinessEvaluation(BaseModel):
    call_readiness: CallReadiness
    requirements: list[CallReadinessRequirement] = Field(min_length=1)
    supporting_evidence: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    missing_conditions: list[MissingConditionCode] = Field(default_factory=list)
    next_trigger: NextTrigger

    @computed_field
    @property
    def qualified(self) -> bool:
        return (
            self.call_readiness is CallReadiness.QUALIFIED
            and not self.blockers
            and all(item.passed for item in self.requirements)
        )
