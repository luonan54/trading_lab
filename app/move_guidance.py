from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.action_guidance import (
    NextStepCode,
    NextStepGuidance,
    NextStepTone,
    StrategyContext,
)
from app.config import LongTermAction, OptionsConfig, SymbolConfig
from app.models import ScanSnapshot, SetupState
from app.options.eligibility import evaluate_options_eligibility
from app.options.models import EligibilityStatus
from app.runtime_universe import RuntimeSymbol


class MoveLane(StrEnum):
    OPTIONS_SETUP = "OPTIONS_SETUP"
    LONG_TERM_PLAN = "LONG_TERM_PLAN"
    THESIS_REVIEW = "THESIS_REVIEW"
    RISK_CAUTION = "RISK_CAUTION"
    WAIT_MONITOR = "WAIT_MONITOR"


MOVE_LANE_PRIORITY = {
    MoveLane.RISK_CAUTION: 0,
    MoveLane.THESIS_REVIEW: 1,
    MoveLane.OPTIONS_SETUP: 2,
    MoveLane.LONG_TERM_PLAN: 3,
    MoveLane.WAIT_MONITOR: 4,
}


@dataclass(frozen=True)
class MoveGuidance:
    lane: MoveLane
    label: str
    headline: str
    detail: str
    tone: NextStepTone
    source_next_step_code: NextStepCode


MOVE_LANE_LABELS = {
    MoveLane.OPTIONS_SETUP: "Options Setup / 期权准备",
    MoveLane.LONG_TERM_PLAN: "Long-Term Plan / 长期计划",
    MoveLane.THESIS_REVIEW: "Thesis Review / 逻辑复核",
    MoveLane.RISK_CAUTION: "Risk Caution / 风险优先",
    MoveLane.WAIT_MONITOR: "Wait / Monitor / 等待观察",
}


def _move(
    lane: MoveLane,
    headline: str,
    detail: str,
    tone: NextStepTone,
    next_step: NextStepGuidance,
) -> MoveGuidance:
    return MoveGuidance(
        lane=lane,
        label=MOVE_LANE_LABELS[lane],
        headline=headline,
        detail=detail,
        tone=tone,
        source_next_step_code=next_step.code,
    )


def _wait(
    headline: str,
    detail: str,
    next_step: NextStepGuidance,
) -> MoveGuidance:
    return _move(
        MoveLane.WAIT_MONITOR,
        headline,
        detail,
        NextStepTone.WAIT,
        next_step,
    )


def _risk(
    headline: str,
    detail: str,
    next_step: NextStepGuidance,
) -> MoveGuidance:
    return _move(
        MoveLane.RISK_CAUTION,
        headline,
        detail,
        NextStepTone.CAUTION,
        next_step,
    )


def _options_move(
    snapshot: ScanSnapshot,
    symbol: SymbolConfig | RuntimeSymbol,
    options_config: OptionsConfig,
    next_step: NextStepGuidance,
) -> MoveGuidance | None:
    eligibility = evaluate_options_eligibility(
        snapshot,
        symbol,
        options_config,
    )
    if eligibility.status is EligibilityStatus.EXECUTION_QUALIFIED:
        return _move(
            MoveLane.OPTIONS_SETUP,
            "Review options setup",
            "Review the qualified equity context and contract-fit evidence.",
            NextStepTone.REVIEW,
            next_step,
        )
    if eligibility.status is EligibilityStatus.RESEARCH_ELIGIBLE:
        return _move(
            MoveLane.OPTIONS_SETUP,
            "Run options pre-screen",
            "Use the existing read-only contract-fit workflow; qualification is not implied.",
            NextStepTone.REVIEW,
            next_step,
        )
    return None


def _long_term_move(
    snapshot: ScanSnapshot,
    action: LongTermAction | None,
    next_step: NextStepGuidance,
) -> MoveGuidance:
    state = snapshot.current_state
    if action is LongTermAction.THESIS_REVIEW:
        return _move(
            MoveLane.THESIS_REVIEW,
            "Complete thesis review",
            "Resolve the confirmed manual thesis review before staged-plan review.",
            NextStepTone.CAUTION,
            next_step,
        )
    if action is None:
        return _move(
            MoveLane.THESIS_REVIEW,
            "Define plan first",
            "Set a confirmed long-term plan before using technical timing context.",
            NextStepTone.REVIEW,
            next_step,
        )
    if action is LongTermAction.PAUSE_ADD:
        return _risk(
            "Keep planned increase paused",
            "The confirmed manual pause remains primary.",
            next_step,
        )
    if state is SetupState.BREAKDOWN:
        detail = (
            "Review broken structure and risk; this does not change the confirmed HOLD plan."
            if action is LongTermAction.HOLD
            else "Review broken structure and the manual plan before another staged-plan review."
        )
        return _risk("Review thesis and risk", detail, next_step)
    if action is LongTermAction.ADD and state in {
        SetupState.RIGHT_SIDE_REPAIR,
        SetupState.CALL_CANDIDATE,
    }:
        return _move(
            MoveLane.LONG_TERM_PLAN,
            "Review next staged increase",
            "Compare the repaired structure with the confirmed staged plan.",
            NextStepTone.REVIEW,
            next_step,
        )
    if action is LongTermAction.ADD:
        return _wait(
            "Wait before staged increase review",
            "The manual plan remains intact, but technical timing is not ready for review.",
            next_step,
        )
    return _wait(
        "Maintain HOLD plan; monitor",
        "Technical context does not change the confirmed HOLD plan.",
        next_step,
    )


def _high_risk_move(
    snapshot: ScanSnapshot,
    action: LongTermAction | None,
    next_step: NextStepGuidance,
) -> MoveGuidance:
    state = snapshot.current_state
    if action is LongTermAction.THESIS_REVIEW:
        return _move(
            MoveLane.THESIS_REVIEW,
            "Complete thesis review",
            "Resolve thesis and maximum exposure before any setup review.",
            NextStepTone.CAUTION,
            next_step,
        )
    if action is LongTermAction.PAUSE_ADD or state is SetupState.BREAKDOWN:
        return _risk(
            "Keep new risk paused",
            "Review the confirmed risk cap and broken or paused context first.",
            next_step,
        )
    if action is None:
        return _move(
            MoveLane.THESIS_REVIEW,
            "Define plan first",
            "Set a confirmed high-risk plan and cap before technical setup review.",
            NextStepTone.CAUTION,
            next_step,
        )
    if state in {
        SetupState.RIGHT_SIDE_REPAIR,
        SetupState.CALL_CANDIDATE,
    }:
        return _risk(
            "Review within risk cap",
            "Repair does not upgrade the high-risk role or its confirmed exposure cap.",
            next_step,
        )
    return _wait(
        "Wait / monitor",
        "Keep the confirmed high-risk plan primary while structure develops.",
        next_step,
    )


def derive_move_guidance(
    snapshot: ScanSnapshot,
    symbol_config: SymbolConfig | RuntimeSymbol,
    strategy_context: StrategyContext,
    options_config: OptionsConfig,
    next_step_guidance: NextStepGuidance,
) -> MoveGuidance:
    """Route human review attention without changing any underlying decision."""

    state = snapshot.current_state
    if strategy_context is StrategyContext.LONG_TERM:
        return _long_term_move(
            snapshot,
            symbol_config.long_term_action,
            next_step_guidance,
        )
    if strategy_context is StrategyContext.HIGH_RISK_GROWTH:
        return _high_risk_move(
            snapshot,
            symbol_config.long_term_action,
            next_step_guidance,
        )
    if state is SetupState.BREAKDOWN:
        return _risk(
            "Review risk and broken structure",
            "Wait for structural repair before setup review.",
            next_step_guidance,
        )

    options_move = _options_move(
        snapshot,
        symbol_config,
        options_config,
        next_step_guidance,
    )
    if strategy_context is StrategyContext.LEADER_LONG_CALL:
        if options_move is not None:
            return options_move
        return _wait(
            "Wait for options readiness",
            "Continue the existing leader workflow until its current gate is met.",
            next_step_guidance,
        )
    if (
        state is SetupState.CALL_CANDIDATE
        and options_move is not None
        and options_move.lane is MoveLane.OPTIONS_SETUP
    ):
        return options_move
    if state is SetupState.CALL_CANDIDATE:
        return _wait(
            "Review technical setup",
            "The confirmed runtime profile does not permit the leader options workflow.",
            next_step_guidance,
        )
    return _wait(
        "Wait / monitor",
        "Use the existing Next Step and Next Trigger for the current technical context.",
        next_step_guidance,
    )
