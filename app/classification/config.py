from __future__ import annotations

from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.classification.models import ClassificationAxis, PortfolioRole


def _expected_transitions() -> dict[PortfolioRole, tuple[PortfolioRole, ...]]:
    return {
        PortfolioRole.CORE: (PortfolioRole.CORE_GROWTH,),
        PortfolioRole.CORE_GROWTH: (
            PortfolioRole.CORE,
            PortfolioRole.GROWTH,
        ),
        PortfolioRole.GROWTH: (
            PortfolioRole.CORE_GROWTH,
            PortfolioRole.HIGH_RISK_GROWTH,
        ),
        PortfolioRole.HIGH_RISK_GROWTH: (
            PortfolioRole.GROWTH,
            PortfolioRole.TACTICAL,
        ),
        PortfolioRole.TACTICAL: (PortfolioRole.HIGH_RISK_GROWTH,),
        PortfolioRole.CYCLICAL: (),
        PortfolioRole.HEDGE: (),
    }


class ClassificationWeights(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    business_quality: float = Field(default=0.30, ge=0, allow_inf_nan=False)
    financial_stability: float = Field(default=0.25, ge=0, allow_inf_nan=False)
    revenue_visibility: float = Field(default=0.20, ge=0, allow_inf_nan=False)
    volatility_risk: float = Field(default=0.15, ge=0, allow_inf_nan=False)
    concentration_event_risk: float = Field(
        default=0.10, ge=0, allow_inf_nan=False
    )

    @model_validator(mode="after")
    def validate_total(self) -> ClassificationWeights:
        if abs(sum(self.model_dump().values()) - 1.0) > 1e-9:
            raise ValueError("classification weights must total 1.0")
        return self


class RoleTransitionRule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    current: PortfolioRole
    candidates: tuple[PortfolioRole, ...] = ()


class RoleArchetype(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: PortfolioRole
    business_quality: float = Field(ge=0, le=10, allow_inf_nan=False)
    financial_stability: float = Field(ge=0, le=10, allow_inf_nan=False)
    revenue_visibility: float = Field(ge=0, le=10, allow_inf_nan=False)
    volatility_risk: float = Field(ge=0, le=10, allow_inf_nan=False)
    concentration_event_risk: float = Field(
        ge=0, le=10, allow_inf_nan=False
    )

    def target_for(self, axis: ClassificationAxis) -> float:
        return getattr(self, axis.value)


def _default_archetypes() -> tuple[RoleArchetype, ...]:
    return (
        RoleArchetype(
            role=PortfolioRole.CORE,
            business_quality=9.5,
            financial_stability=9.5,
            revenue_visibility=9.5,
            volatility_risk=9.5,
            concentration_event_risk=9.5,
        ),
        RoleArchetype(
            role=PortfolioRole.CORE_GROWTH,
            business_quality=7.5,
            financial_stability=7.5,
            revenue_visibility=7.5,
            volatility_risk=7.5,
            concentration_event_risk=7.5,
        ),
        RoleArchetype(
            role=PortfolioRole.GROWTH,
            business_quality=5.5,
            financial_stability=5.5,
            revenue_visibility=5.5,
            volatility_risk=5.5,
            concentration_event_risk=5.5,
        ),
        RoleArchetype(
            role=PortfolioRole.HIGH_RISK_GROWTH,
            business_quality=3.5,
            financial_stability=3.5,
            revenue_visibility=3.5,
            volatility_risk=3.5,
            concentration_event_risk=3.5,
        ),
        RoleArchetype(
            role=PortfolioRole.TACTICAL,
            business_quality=1.5,
            financial_stability=1.5,
            revenue_visibility=1.5,
            volatility_risk=1.5,
            concentration_event_risk=1.5,
        ),
    )


def _default_transition_rules() -> tuple[RoleTransitionRule, ...]:
    return tuple(
        RoleTransitionRule(current=current, candidates=candidates)
        for current, candidates in _expected_transitions().items()
    )


class ClassificationConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed_role_transitions: tuple[RoleTransitionRule, ...] = Field(
        default_factory=_default_transition_rules
    )
    role_archetypes: tuple[RoleArchetype, ...] = Field(
        default_factory=_default_archetypes
    )
    weights: ClassificationWeights = Field(default_factory=ClassificationWeights)
    min_score_delta: float = Field(default=1.5, ge=0, allow_inf_nan=False)
    required_confirmation_cycles: int = Field(default=2, ge=1)
    min_data_completeness: float = Field(
        default=0.70, ge=0, le=1, allow_inf_nan=False
    )
    min_evidence_confidence: float = Field(
        default=0.65, ge=0, le=1, allow_inf_nan=False
    )
    proposal_cooldown_days: int = Field(default=30, ge=0)
    proposal_expiration_days: int = Field(default=30, ge=1)
    material_score_change: float = Field(
        default=1.0, ge=0, allow_inf_nan=False
    )

    @field_validator("allowed_role_transitions", mode="before")
    @classmethod
    def normalize_transition_mapping(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return tuple(
                {"current": current, "candidates": candidates}
                for current, candidates in value.items()
            )
        return value

    @field_validator("role_archetypes", mode="before")
    @classmethod
    def normalize_archetype_mapping(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return tuple(
                {"role": role, **targets} for role, targets in value.items()
            )
        return value

    @model_validator(mode="after")
    def validate_transitions(self) -> ClassificationConfig:
        expected = _expected_transitions()
        current_roles = [rule.current for rule in self.allowed_role_transitions]
        if len(current_roles) != len(set(current_roles)):
            raise ValueError("allowed_role_transitions contains duplicate role keys")
        if set(current_roles) != set(PortfolioRole):
            raise ValueError("allowed_role_transitions must define every portfolio role")
        normalized: dict[PortfolioRole, tuple[PortfolioRole, ...]] = {}
        for rule in self.allowed_role_transitions:
            current = rule.current
            candidates = rule.candidates
            if current in candidates:
                raise ValueError(f"self transition is not allowed for {current.value}")
            if len(candidates) != len(set(candidates)):
                raise ValueError(
                    f"duplicate role transition configured for {current.value}"
                )
            normalized[current] = tuple(candidates)
        if normalized != expected:
            raise ValueError(
                "allowed_role_transitions must match the configured adjacent ladder; "
                "CYCLICAL and HEDGE are isolated"
            )
        archetype_roles = [item.role for item in self.role_archetypes]
        expected_archetypes = {
            PortfolioRole.CORE,
            PortfolioRole.CORE_GROWTH,
            PortfolioRole.GROWTH,
            PortfolioRole.HIGH_RISK_GROWTH,
            PortfolioRole.TACTICAL,
        }
        if (
            len(archetype_roles) != len(set(archetype_roles))
            or set(archetype_roles) != expected_archetypes
        ):
            raise ValueError(
                "role_archetypes must define the five adjacent-ladder roles "
                "exactly once"
            )
        return self

    def candidates_for(self, current: PortfolioRole) -> tuple[PortfolioRole, ...]:
        return next(
            rule.candidates
            for rule in self.allowed_role_transitions
            if rule.current is current
        )

    def archetype_for(self, role: PortfolioRole) -> RoleArchetype | None:
        return next(
            (item for item in self.role_archetypes if item.role is role),
            None,
        )
