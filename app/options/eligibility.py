from __future__ import annotations
from datetime import datetime

from app.config import AssetClass, OptionsConfig, SymbolConfig
from app.call_readiness import evaluate_call_readiness
from app.models import ScanSnapshot, SetupState
from app.entry_models import EntryPolicy
from app.options.models import EligibilityDecision, EligibilityStatus
from app.readiness_models import CallRequirementCode
from app.runtime_universe import RuntimeSymbol


def evaluate_options_eligibility(
    snapshot: ScanSnapshot,
    symbol: SymbolConfig | RuntimeSymbol,
    options: OptionsConfig,
    *,
    manual_override: bool = False,
    as_of: datetime | None = None,
    entry_policy: EntryPolicy | None = None,
    momentum_rsi: float | None = None,
) -> EligibilityDecision:
    """Determine whether an equity setup qualifies for contract analysis."""

    if not options.enabled:
        return EligibilityDecision(
            ticker=snapshot.ticker,
            status=EligibilityStatus.NOT_ELIGIBLE,
            eligible=False,
            manual_override=False,
            reasons=["Options contract analysis is disabled by configuration"],
        )

    is_enabled_equity = (
        symbol.enabled
        and symbol.asset_class is AssetClass.EQUITY
        and not symbol.benchmark
    )
    if not is_enabled_equity:
        return EligibilityDecision(
            ticker=snapshot.ticker,
            status=EligibilityStatus.NOT_ELIGIBLE,
            eligible=False,
            manual_override=False,
            reasons=[
                "Ticker must be an enabled, non-benchmark equity before "
                "contract analysis"
            ],
        )
    readiness = evaluate_call_readiness(
        snapshot,
        allow_call_candidate=symbol.allows_call_candidate,
        as_of=as_of,
        entry_policy=entry_policy,
        momentum_rsi=momentum_rsi,
    )
    leader_requirement = next(
        requirement
        for requirement in readiness.requirements
        if requirement.code is CallRequirementCode.LEADER_WORKFLOW_ENABLED
    )
    if not leader_requirement.passed:
        return EligibilityDecision(
            ticker=snapshot.ticker,
            status=EligibilityStatus.NOT_ELIGIBLE,
            eligible=False,
            manual_override=False,
            reasons=[
                leader_requirement.blocker
                or "Leader long-call workflow permission is required"
            ],
        )

    if manual_override:
        return EligibilityDecision(
            ticker=snapshot.ticker,
            status=EligibilityStatus.MANUAL_OVERRIDE,
            eligible=True,
            manual_override=True,
            reasons=["Research only: manual override bypassed entry, state and score checks"],
            warnings=[
                "MANUAL OVERRIDE: eligibility does not imply setup quality or "
                "a trading recommendation"
            ],
        )

    eligibility = options.eligibility
    if (
        snapshot.current_state is SetupState.CALL_CANDIDATE
        and SetupState.CALL_CANDIDATE in eligibility.allowed_states
        and readiness.qualified
    ):
        return EligibilityDecision(
            ticker=snapshot.ticker,
            status=EligibilityStatus.EXECUTION_QUALIFIED,
            eligible=True,
            manual_override=False,
            reasons=[
                "Equity state is CALL_CANDIDATE",
                "Shared call readiness is QUALIFIED with zero required blockers",
            ],
        )

    if (
        snapshot.current_state in {SetupState.RIGHT_SIDE_REPAIR, SetupState.CALL_CANDIDATE}
        and snapshot.current_state in eligibility.allowed_states
        and snapshot.score >= eligibility.min_equity_score
    ):
        return EligibilityDecision(
            ticker=snapshot.ticker,
            status=EligibilityStatus.RESEARCH_ELIGIBLE,
            eligible=True,
            manual_override=False,
            reasons=[
                f"Equity state is {snapshot.current_state.value}",
                f"Equity score meets the {eligibility.min_equity_score:.1f} minimum",
                "Contract pre-screen research is available; the setup is not qualified",
                *readiness.blockers,
            ],
        )

    reasons = [
        "Equity setup does not meet the configured contract-analysis gate"
    ]
    if snapshot.current_state is SetupState.RIGHT_SIDE_REPAIR:
        reasons.append(
            f"Equity score {snapshot.score:.1f} is below the "
            f"{eligibility.min_equity_score:.1f} minimum"
        )
    if snapshot.current_state is SetupState.CALL_CANDIDATE:
        reasons.extend(readiness.blockers)
    return EligibilityDecision(
        ticker=snapshot.ticker,
        status=EligibilityStatus.NOT_ELIGIBLE,
        eligible=False,
        manual_override=False,
        reasons=reasons,
    )
