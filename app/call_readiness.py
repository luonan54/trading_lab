from __future__ import annotations

from datetime import datetime

from app.entry import current_entry
from app.entry_models import EntryEvaluation, EntryPolicy, EntryStatus

from app.explainability.models import (
    LevelSource,
    MissingConditionCode,
    NextTrigger,
    TriggerType,
)
from app.models import ScanSnapshot, TechnicalFeatures
from app.readiness_models import (
    CallReadiness,
    CallReadinessEvaluation,
    CallReadinessRequirement,
    CallRequirementCode,
    RequirementStatus,
)
from app.states import SetupState

REPAIR_CONTEXT_STATES = {
    SetupState.RIGHT_SIDE_REPAIR,
    SetupState.SELLING_EXHAUSTION,
}


def _requirement(
    code: CallRequirementCode,
    label: str,
    passed: bool,
    evidence: str,
    *,
    blocker: str,
    missing_condition: MissingConditionCode,
) -> CallReadinessRequirement:
    return CallReadinessRequirement(
        code=code,
        label=label,
        status=RequirementStatus.PASS if passed else RequirementStatus.FAIL,
        evidence=evidence,
        blocker=None if passed else blocker,
        missing_condition=None if passed else missing_condition,
    )


def _next_trigger(
    requirements: list[CallReadinessRequirement],
    features: TechnicalFeatures,
) -> NextTrigger:
    failed = {item.code for item in requirements if not item.passed}
    if CallRequirementCode.LEADER_WORKFLOW_ENABLED in failed:
        return NextTrigger(
            type=TriggerType.LEADER_WORKFLOW_REQUIRED,
            description="This ticker is not enabled for the leader long-call workflow.",
        )
    if CallRequirementCode.ENTRY_PLAN in failed:
        requirement = next(item for item in requirements if item.code is CallRequirementCode.ENTRY_PLAN)
        return NextTrigger(type=TriggerType.REVIEW_ENTRY_PLAN, description=requirement.evidence)
    if CallRequirementCode.MOMENTUM_CONFIRMATION in failed:
        return NextTrigger(
            type=TriggerType.MOMENTUM_CONFIRMATION,
            description="Wait for RSI to meet the configured momentum threshold.",
        )
    if CallRequirementCode.PRIOR_REPAIR_CONTEXT in failed:
        return NextTrigger(
            type=TriggerType.ESTABLISH_REPAIR_CONTEXT,
            description=(
                "Establish a completed-bar repair context before call qualification."
            ),
        )
    if CallRequirementCode.HIGHER_LOW in failed:
        return NextTrigger(
            type=TriggerType.CONFIRMED_HIGHER_LOW,
            description="Confirm a higher low in completed daily structure.",
        )
    if CallRequirementCode.COMPLETED_BAR_CONFIRMATION in failed:
        level = features.local_resistance
        return NextTrigger(
            type=TriggerType.LOCAL_ACCEPTANCE_OR_RECLAIM,
            level=level,
            source=LevelSource.LOCAL_15M_PIVOT_HIGH if level is not None else None,
            description=(
                "Confirm two completed 15-minute closes above local resistance "
                "or a completed-bar reclaim of local support."
            ),
        )
    if CallRequirementCode.BENCHMARK_CONFIRMATION in failed:
        return NextTrigger(
            type=TriggerType.BENCHMARK_CONFIRMATION,
            description="Wait for the configured benchmark confirmation.",
        )
    return NextTrigger(
        type=TriggerType.MAINTAIN_REPAIR_STRUCTURE,
        description="Maintain confirmed repair structure and benchmark confirmation.",
    )


def evaluate_call_readiness(
    source: ScanSnapshot | TechnicalFeatures,
    *,
    previous_state: SetupState | None = None,
    benchmark_confirmed: bool | None = None,
    allow_call_candidate: bool | None = None,
    entry_plan: EntryEvaluation | None = None,
    as_of: datetime | None = None,
    require_entry: bool = True,
    momentum_rsi: float | None = None,
    entry_policy: EntryPolicy | None = None,
) -> CallReadinessEvaluation:
    """Evaluate every call-state requirement from one deterministic rule set."""

    if isinstance(source, ScanSnapshot):
        features = source.features
        previous_state = source.previous_state
        benchmark_confirmed = source.benchmark_confirmed
        entry_plan = source.entry_plan
        if allow_call_candidate is None and source.call_readiness is not None:
            allow_call_candidate = any(
                item.code is CallRequirementCode.LEADER_WORKFLOW_ENABLED and item.passed
                for item in source.call_readiness.requirements
            )
    else:
        features = source
        if benchmark_confirmed is None:
            raise ValueError(
                "benchmark_confirmed is required when evaluating TechnicalFeatures"
            )
    if allow_call_candidate is None:
        allow_call_candidate = True

    plan = current_entry(
        entry_plan, now=as_of, policy=entry_policy, momentum_rsi=momentum_rsi,
    )
    structured_setup = (
        entry_plan is not None
        and entry_plan.anchor is not None
        and entry_plan.daily_trend_confirmed
        and entry_plan.bar_confirmation
        and entry_plan.status is not EntryStatus.INVALIDATED
    )
    threshold = momentum_rsi if momentum_rsi is not None else plan.momentum_rsi
    prior_context = structured_setup or previous_state in REPAIR_CONTEXT_STATES
    completed_bar_confirmation = (
        structured_setup or features.two_bar_acceptance or features.two_bar_reclaim
    )
    requirements = [
        _requirement(
            CallRequirementCode.LEADER_WORKFLOW_ENABLED,
            "Leader workflow enabled",
            allow_call_candidate,
            (
                "Ticker is enabled for leader long-call analysis."
                if allow_call_candidate
                else "Ticker is outside the leader long-call analysis group."
            ),
            blocker="Leader long-call workflow permission is required.",
            missing_condition=MissingConditionCode.LEADER_WORKFLOW_PERMISSION_MISSING,
        ),
        _requirement(
            CallRequirementCode.PRIOR_REPAIR_CONTEXT,
            "Repair context or structural breakout",
            prior_context,
            (
                "A completed-bar structural setup is confirmed independently of scan history."
                if structured_setup else (
                    f"Previous state was {previous_state.value}."
                    if prior_context and previous_state is not None
                    else "No qualifying repair context or structural breakout."
                )
            ),
            blocker="A prior repair context has not been established.",
            missing_condition=MissingConditionCode.PRIOR_REPAIR_CONTEXT_MISSING,
        ),
        _requirement(
            CallRequirementCode.HIGHER_LOW,
            "Higher low or daily-trend breakout",
            features.higher_low or structured_setup,
            (
                "Daily trend and a structural breakout/reclaim are confirmed."
                if structured_setup else (
                    "Completed daily structure confirms a higher low."
                    if features.higher_low
                    else "Completed daily structure does not yet confirm a higher low."
                )
            ),
            blocker="A completed daily higher low is still required.",
            missing_condition=MissingConditionCode.HIGHER_LOW_NOT_CONFIRMED,
        ),
        _requirement(
            CallRequirementCode.COMPLETED_BAR_CONFIRMATION,
            "Completed-bar confirmation",
            completed_bar_confirmation,
            (
                "Distinct completed bars confirmed the anchored structural setup."
                if structured_setup else "Two completed bars accepted above local resistance."
                if features.two_bar_acceptance
                else (
                    "Two completed bars reclaimed local support."
                    if features.two_bar_reclaim
                    else "Neither local acceptance nor local support reclaim is confirmed."
                )
            ),
            blocker=(
                "Two completed bars must confirm local resistance acceptance "
                "or local support reclaim."
            ),
            missing_condition=MissingConditionCode.TWO_BAR_CONFIRMATION_MISSING,
        ),
        _requirement(
            CallRequirementCode.BENCHMARK_CONFIRMATION,
            "Benchmark confirmation",
            bool(benchmark_confirmed),
            (
                "Configured benchmark confirmation passed."
                if benchmark_confirmed
                else "Configured benchmark confirmation is not present."
            ),
            blocker="Configured benchmark confirmation is still required.",
            missing_condition=MissingConditionCode.BENCHMARK_CONFIRMATION_MISSING,
        ),
        _requirement(
            CallRequirementCode.MOMENTUM_CONFIRMATION,
            "Momentum RSI",
            features.rsi14 >= threshold,
            f"RSI {features.rsi14:.1f}; required minimum {threshold:.1f}.",
            blocker=f"RSI must reach {threshold:.1f} before call qualification.",
            missing_condition=MissingConditionCode.MOMENTUM_NOT_CONFIRMED,
        ),
    ]
    if require_entry:
        requirements.append(_requirement(
            CallRequirementCode.ENTRY_PLAN,
            "Current structural entry / reward-risk",
            plan.ready,
            plan.next_trigger if plan.ready else (
                plan.blockers[0] if plan.blockers else "Entry plan is incomplete."
            ),
            blocker=plan.blockers[0] if plan.blockers else "Entry plan is not qualified.",
            missing_condition=MissingConditionCode.ENTRY_PLAN_NOT_QUALIFIED,
        ))
    blockers = [item.blocker for item in requirements if item.blocker is not None]
    missing = [
        item.missing_condition
        for item in requirements
        if item.missing_condition is not None
    ]
    evidence = [item.evidence for item in requirements if item.passed]

    if not allow_call_candidate:
        readiness = CallReadiness.NOT_READY
    elif not blockers:
        readiness = CallReadiness.QUALIFIED
    elif prior_context and features.higher_low:
        readiness = CallReadiness.NEAR_QUALIFICATION
    elif prior_context or features.higher_low or completed_bar_confirmation:
        readiness = CallReadiness.DEVELOPING
    else:
        readiness = CallReadiness.NOT_READY

    return CallReadinessEvaluation(
        call_readiness=readiness,
        requirements=requirements,
        supporting_evidence=evidence,
        blockers=blockers,
        missing_conditions=missing,
        next_trigger=_next_trigger(requirements, features),
    )
