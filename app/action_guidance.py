from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.config import LongTermAction, OptionsConfig, SymbolConfig
from app.models import ScanSnapshot, SetupState
from app.options.eligibility import evaluate_options_eligibility
from app.runtime_universe import RuntimeSymbol


class StrategyContext(StrEnum):
    ALL = "ALL"
    LEADER_LONG_CALL = "LEADER_LONG_CALL"
    LONG_TERM = "LONG_TERM"
    HIGH_RISK_GROWTH = "HIGH_RISK_GROWTH"
    SHORT_TERM = "SHORT_TERM"


class NextStepCode(StrEnum):
    NO_ACTIVE_SETUP = "NO_ACTIVE_SETUP"
    MONITOR_STABILIZATION = "MONITOR_STABILIZATION"
    AWAIT_HIGHER_LOW = "AWAIT_HIGHER_LOW"
    AWAIT_BREAKOUT_CONFIRMATION = "AWAIT_BREAKOUT_CONFIRMATION"
    REVIEW_QUALIFIED_SETUP = "REVIEW_QUALIFIED_SETUP"
    AWAIT_RECLAIM = "AWAIT_RECLAIM"
    NO_OPTIONS_WORKFLOW = "NO_OPTIONS_WORKFLOW"
    MONITOR_REPAIR = "MONITOR_REPAIR"
    AWAIT_OPTIONS_CONFIRMATION = "AWAIT_OPTIONS_CONFIRMATION"
    RUN_OPTIONS_FIT_SCAN = "RUN_OPTIONS_FIT_SCAN"
    AWAIT_ELIGIBILITY = "AWAIT_ELIGIBILITY"
    REVIEW_OPTIONS_CANDIDATES = "REVIEW_OPTIONS_CANDIDATES"
    PAUSE_LONG_CALL_WORKFLOW = "PAUSE_LONG_CALL_WORKFLOW"
    COMPLETE_THESIS_REVIEW = "COMPLETE_THESIS_REVIEW"
    KEEP_STAGED_ACTIVITY_PAUSED = "KEEP_STAGED_ACTIVITY_PAUSED"
    MAINTAIN_HOLD_PLAN = "MAINTAIN_HOLD_PLAN"
    REVIEW_STAGED_PLAN = "REVIEW_STAGED_PLAN"
    PREPARE_AWAIT_REPAIR = "PREPARE_AWAIT_REPAIR"
    AWAIT_HIGHER_LOW_REVIEW = "AWAIT_HIGHER_LOW_REVIEW"
    DEFER_NEXT_TRANCHE = "DEFER_NEXT_TRANCHE"
    FOLLOW_STAGED_PLAN = "FOLLOW_STAGED_PLAN"
    DEFINE_LONG_TERM_PLAN = "DEFINE_LONG_TERM_PLAN"
    REVIEW_THESIS_AND_RISK_CAP = "REVIEW_THESIS_AND_RISK_CAP"
    KEEP_NEW_RISK_PAUSED = "KEEP_NEW_RISK_PAUSED"
    DEFER_NEW_RISK = "DEFER_NEW_RISK"
    WATCH_CONFIRMED_REPAIR = "WATCH_CONFIRMED_REPAIR"
    REVIEW_WITHIN_RISK_CAP = "REVIEW_WITHIN_RISK_CAP"
    MONITOR_NO_SETUP = "MONITOR_NO_SETUP"


class NextStepTone(StrEnum):
    NEUTRAL = "neutral"
    WATCH = "watch"
    WAIT = "wait"
    REVIEW = "review"
    CAUTION = "caution"


@dataclass(frozen=True)
class NextStepGuidance:
    code: NextStepCode
    headline: str
    detail: str
    tone: NextStepTone


def _guidance(
    code: NextStepCode,
    headline: str,
    detail: str,
    tone: NextStepTone,
) -> NextStepGuidance:
    return NextStepGuidance(
        code=code,
        headline=headline,
        detail=detail,
        tone=tone,
    )


def _generic_guidance(state: SetupState) -> NextStepGuidance:
    return {
        SetupState.NORMAL: _guidance(
            NextStepCode.NO_ACTIVE_SETUP,
            "No active setup",
            "Continue monitoring completed-bar structure.",
            NextStepTone.NEUTRAL,
        ),
        SetupState.DIP_WATCH: _guidance(
            NextStepCode.MONITOR_STABILIZATION,
            "Watch only",
            "Wait for stabilization, a higher low, and a reclaim.",
            NextStepTone.WATCH,
        ),
        SetupState.SELLING_EXHAUSTION: _guidance(
            NextStepCode.AWAIT_HIGHER_LOW,
            "Wait for higher low",
            "Slowing pressure is not a confirmed repair.",
            NextStepTone.WAIT,
        ),
        SetupState.RIGHT_SIDE_REPAIR: _guidance(
            NextStepCode.AWAIT_BREAKOUT_CONFIRMATION,
            "Wait for breakout confirmation",
            "Use Next Trigger to track the missing market confirmation.",
            NextStepTone.WAIT,
        ),
        SetupState.CALL_CANDIDATE: _guidance(
            NextStepCode.REVIEW_QUALIFIED_SETUP,
            "Review qualified setup",
            "Inspect invalidation and the relevant strategy view; nothing is automatic.",
            NextStepTone.REVIEW,
        ),
        SetupState.BREAKDOWN: _guidance(
            NextStepCode.AWAIT_RECLAIM,
            "Wait for reclaim",
            "Broken support needs a reclaim and higher low before reconsideration.",
            NextStepTone.CAUTION,
        ),
    }[state]


def _leader_guidance(
    snapshot: ScanSnapshot,
    symbol: SymbolConfig | RuntimeSymbol,
    options: OptionsConfig,
) -> NextStepGuidance:
    state = snapshot.current_state
    if state is SetupState.RIGHT_SIDE_REPAIR:
        eligibility = evaluate_options_eligibility(snapshot, symbol, options)
        if eligibility.research_eligible:
            return _guidance(
                NextStepCode.RUN_OPTIONS_FIT_SCAN,
                "Run contract pre-screen",
                "Research eligibility is met; inspect contract fit without treating the setup as qualified.",
                NextStepTone.REVIEW,
            )
        return _guidance(
            NextStepCode.AWAIT_ELIGIBILITY,
            "Wait for stronger confirmation",
            "The repair has not met the configured options eligibility threshold.",
            NextStepTone.WAIT,
        )
    return {
        SetupState.NORMAL: _guidance(
            NextStepCode.NO_OPTIONS_WORKFLOW,
            "No options workflow yet",
            "Continue monitoring the equity setup.",
            NextStepTone.NEUTRAL,
        ),
        SetupState.DIP_WATCH: _guidance(
            NextStepCode.MONITOR_REPAIR,
            "Monitor repair",
            "No options scan yet; wait for stabilization and repair.",
            NextStepTone.WATCH,
        ),
        SetupState.SELLING_EXHAUSTION: _guidance(
            NextStepCode.AWAIT_OPTIONS_CONFIRMATION,
            "Wait for confirmed higher low",
            "No options scan yet; stabilization alone is insufficient.",
            NextStepTone.WAIT,
        ),
        SetupState.CALL_CANDIDATE: _guidance(
            NextStepCode.REVIEW_OPTIONS_CANDIDATES,
            "Review options candidates",
            "Run a fit scan if needed, then inspect contract warnings and equity invalidation.",
            NextStepTone.REVIEW,
        ),
        SetupState.BREAKDOWN: _guidance(
            NextStepCode.PAUSE_LONG_CALL_WORKFLOW,
            "Pause long-call workflow",
            "Wait for a reclaim and higher low before resuming this workflow.",
            NextStepTone.CAUTION,
        ),
    }[state]


def _short_term_guidance(state: SetupState) -> NextStepGuidance:
    return {
        SetupState.NORMAL: _guidance(
            NextStepCode.NO_ACTIVE_SETUP,
            "No active setup",
            "Continue monitoring completed-bar structure.",
            NextStepTone.NEUTRAL,
        ),
        SetupState.DIP_WATCH: _guidance(
            NextStepCode.MONITOR_REPAIR,
            "Monitor only",
            "Wait for stabilization and repair.",
            NextStepTone.WATCH,
        ),
        SetupState.SELLING_EXHAUSTION: _guidance(
            NextStepCode.AWAIT_HIGHER_LOW,
            "Watch for higher low",
            "Treat stabilization as observation, not confirmation.",
            NextStepTone.WATCH,
        ),
        SetupState.RIGHT_SIDE_REPAIR: _guidance(
            NextStepCode.AWAIT_BREAKOUT_CONFIRMATION,
            "Wait for break and acceptance",
            "Use Next Trigger to track the required confirmation.",
            NextStepTone.WAIT,
        ),
        SetupState.CALL_CANDIDATE: _guidance(
            NextStepCode.REVIEW_QUALIFIED_SETUP,
            "Review setup and invalidation",
            "Check the completed-bar evidence and failure condition.",
            NextStepTone.REVIEW,
        ),
        SetupState.BREAKDOWN: _guidance(
            NextStepCode.AWAIT_RECLAIM,
            "Stand aside; wait for reclaim",
            "Reconsider only after support and structure are repaired.",
            NextStepTone.CAUTION,
        ),
    }[state]


def _long_term_guidance(
    state: SetupState,
    action: LongTermAction | None,
) -> NextStepGuidance:
    context_note = (
        f"Technical State is timing context ({state.value}), not a long-term instruction."
    )
    if action is None:
        return _guidance(
            NextStepCode.DEFINE_LONG_TERM_PLAN,
            "Define long-term plan first",
            context_note,
            NextStepTone.REVIEW,
        )
    if action is LongTermAction.THESIS_REVIEW:
        return _guidance(
            NextStepCode.COMPLETE_THESIS_REVIEW,
            "Complete thesis review first",
            f"{context_note} Technical evidence does not resolve the thesis.",
            NextStepTone.CAUTION,
        )
    if action is LongTermAction.PAUSE_ADD:
        return _guidance(
            NextStepCode.KEEP_STAGED_ACTIVITY_PAUSED,
            "Keep planned adds paused",
            f"{context_note} Reconsider only after repair and the configured trigger.",
            NextStepTone.CAUTION,
        )
    if action is LongTermAction.HOLD:
        if state is SetupState.BREAKDOWN:
            return _guidance(
                NextStepCode.MAINTAIN_HOLD_PLAN,
                "Review thesis and risk",
                f"{context_note} This state does not change the confirmed HOLD plan.",
                NextStepTone.CAUTION,
            )
        return _guidance(
            NextStepCode.MAINTAIN_HOLD_PLAN,
            "Maintain HOLD plan; monitor context",
            context_note,
            NextStepTone.NEUTRAL,
        )
    return {
        SetupState.NORMAL: _guidance(
            NextStepCode.FOLLOW_STAGED_PLAN,
            "Follow existing staged plan",
            f"No technical edge is active. {context_note}",
            NextStepTone.NEUTRAL,
        ),
        SetupState.DIP_WATCH: _guidance(
            NextStepCode.PREPARE_AWAIT_REPAIR,
            "Prepare, but wait for repair",
            f"Review the next tranche only after repair. {context_note}",
            NextStepTone.WATCH,
        ),
        SetupState.SELLING_EXHAUSTION: _guidance(
            NextStepCode.AWAIT_HIGHER_LOW_REVIEW,
            "Wait for confirmed higher low",
            f"Defer staged-plan review until structure confirms. {context_note}",
            NextStepTone.WAIT,
        ),
        SetupState.RIGHT_SIDE_REPAIR: _guidance(
            NextStepCode.REVIEW_STAGED_PLAN,
            "Review next staged add against plan",
            context_note,
            NextStepTone.REVIEW,
        ),
        SetupState.CALL_CANDIDATE: _guidance(
            NextStepCode.REVIEW_STAGED_PLAN,
            "Review next staged add against plan",
            context_note,
            NextStepTone.REVIEW,
        ),
        SetupState.BREAKDOWN: _guidance(
            NextStepCode.DEFER_NEXT_TRANCHE,
            "Defer next tranche",
            f"Review thesis and support first. {context_note}",
            NextStepTone.CAUTION,
        ),
    }[state]


def _high_risk_guidance(
    state: SetupState,
    action: LongTermAction | None,
) -> NextStepGuidance:
    cap_note = (
        "Any review remains subject to the confirmed high-risk cap and staged plan."
    )
    if action is LongTermAction.THESIS_REVIEW:
        return _guidance(
            NextStepCode.REVIEW_THESIS_AND_RISK_CAP,
            "Review thesis and risk cap first",
            "Technical repair does not resolve the thesis or upgrade the portfolio role.",
            NextStepTone.CAUTION,
        )
    if action is LongTermAction.PAUSE_ADD:
        return _guidance(
            NextStepCode.KEEP_NEW_RISK_PAUSED,
            "Keep new risk paused",
            cap_note,
            NextStepTone.CAUTION,
        )
    if state is SetupState.BREAKDOWN:
        return _guidance(
            NextStepCode.DEFER_NEW_RISK,
            "Defer new risk",
            "Review thesis, broken support, and maximum exposure first.",
            NextStepTone.CAUTION,
        )
    if state in {SetupState.DIP_WATCH, SetupState.SELLING_EXHAUSTION}:
        return _guidance(
            NextStepCode.WATCH_CONFIRMED_REPAIR,
            "Watch only",
            f"Wait for confirmed repair. {cap_note}",
            NextStepTone.WATCH,
        )
    if state in {SetupState.RIGHT_SIDE_REPAIR, SetupState.CALL_CANDIDATE}:
        return _guidance(
            NextStepCode.REVIEW_WITHIN_RISK_CAP,
            "Review only within risk cap",
            f"Repair does not upgrade the portfolio role. {cap_note}",
            NextStepTone.REVIEW,
        )
    return _guidance(
        NextStepCode.MONITOR_NO_SETUP,
        "Monitor; no active setup",
        cap_note,
        NextStepTone.NEUTRAL,
    )


def derive_next_step(
    snapshot: ScanSnapshot,
    symbol_config: SymbolConfig | RuntimeSymbol,
    strategy_context: StrategyContext,
    options_config: OptionsConfig,
) -> NextStepGuidance:
    if (
        strategy_context in {
            StrategyContext.ALL, StrategyContext.LEADER_LONG_CALL,
            StrategyContext.SHORT_TERM,
        }
        and snapshot.current_state is SetupState.CALL_CANDIDATE
    ):
        from app.call_readiness import evaluate_call_readiness

        readiness = evaluate_call_readiness(
            snapshot, allow_call_candidate=symbol_config.allows_call_candidate
        )
        if not readiness.qualified:
            return _guidance(
                NextStepCode.AWAIT_ELIGIBILITY,
                "Strong structure; wait for entry",
                readiness.next_trigger.description
                + " Existing-position decisions stay separate.",
                NextStepTone.WAIT,
            )
    if strategy_context is StrategyContext.ALL:
        return _generic_guidance(snapshot.current_state)
    if strategy_context is StrategyContext.LEADER_LONG_CALL:
        return _leader_guidance(snapshot, symbol_config, options_config)
    if strategy_context is StrategyContext.LONG_TERM:
        return _long_term_guidance(
            snapshot.current_state,
            symbol_config.long_term_action,
        )
    if strategy_context is StrategyContext.HIGH_RISK_GROWTH:
        return _high_risk_guidance(
            snapshot.current_state,
            symbol_config.long_term_action,
        )
    return _short_term_guidance(snapshot.current_state)
