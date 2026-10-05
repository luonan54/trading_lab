from __future__ import annotations

from app.config import ThresholdConfig
from app.models import Classification, SetupState, TechnicalFeatures
from app.call_readiness import evaluate_call_readiness
from app.readiness_models import CallReadinessEvaluation

REPAIR_CONTEXT_STATES = {
    SetupState.RIGHT_SIDE_REPAIR,
    SetupState.SELLING_EXHAUSTION,
}


def classify_setup(
    features: TechnicalFeatures,
    *,
    previous_state: SetupState | None,
    benchmark_confirmed: bool,
    thresholds: ThresholdConfig,
    allow_call_candidate: bool = True,
    readiness: CallReadinessEvaluation | None = None,
) -> Classification:
    below_support = features.current_price < features.support * (
        1 - thresholds.breakdown_buffer_pct / 100
    )
    if below_support and features.lower_low:
        return Classification(
            state=SetupState.BREAKDOWN,
            confidence=0.9,
            reasons=["Price broke support with a confirmed lower-low structure"],
            invalidation_conditions=[
                "Two completed 15-minute closes reclaim prior support",
                "Daily structure forms a higher low",
            ],
        )

    readiness = readiness or evaluate_call_readiness(
        features,
        previous_state=previous_state,
        benchmark_confirmed=benchmark_confirmed,
        allow_call_candidate=allow_call_candidate,
        require_entry=False,
        momentum_rsi=thresholds.momentum_rsi,
    )
    market_conditions_met = all(
        item.passed
        for item in readiness.requirements
        if item.code.value != "LEADER_WORKFLOW_ENABLED"
    )
    if readiness.qualified:
        return Classification(
            state=SetupState.CALL_CANDIDATE,
            confidence=0.85,
            reasons=[
                "Repair or initial structural breakout confirmed",
                "Completed-bar confirmation; technical state alone is not entry permission",
                "Configured benchmark confirmation passed",
            ],
            invalidation_conditions=[
                "A completed bar closes back below the reclaimed level",
                "Higher-low structure fails",
                "Benchmark confirmation turns negative",
            ],
        )

    if market_conditions_met:
        return Classification(
            state=SetupState.RIGHT_SIDE_REPAIR,
            confidence=0.78,
            reasons=[
                "Technical repair is confirmed",
                "CALL_CANDIDATE is limited to the leader-long-call strategy",
            ],
            invalidation_conditions=[
                "A completed bar closes back below the reclaimed level",
                "Higher-low structure fails",
                "Benchmark confirmation turns negative",
            ],
        )

    if (
        features.current_price > features.ema9
        and features.ema9 >= features.ema20
        and features.higher_low
    ):
        reasons = ["Price is above rising short-term averages with a higher low"]
        if not benchmark_confirmed:
            reasons.append("Benchmark confirmation is not yet present")
        if not (features.two_bar_acceptance or features.two_bar_reclaim):
            reasons.append("Two completed confirming bars are still required")
        return Classification(
            state=SetupState.RIGHT_SIDE_REPAIR,
            confidence=0.72,
            reasons=reasons,
            invalidation_conditions=[
                "Price loses EMA20",
                "Daily structure prints a lower low",
            ],
        )

    if features.rsi14 <= thresholds.oversold_rsi and (
        features.return_15m_pct > 0 or features.current_price >= features.vwap
    ):
        return Classification(
            state=SetupState.SELLING_EXHAUSTION,
            confidence=0.65,
            reasons=["Oversold momentum is stabilizing intraday"],
            invalidation_conditions=[
                "Price makes a fresh lower low below support",
                "Intraday stabilization fails",
            ],
        )

    if (
        features.drawdown_pct <= thresholds.dip_drawdown_pct
        and features.current_price >= features.support
    ):
        return Classification(
            state=SetupState.DIP_WATCH,
            confidence=0.6,
            reasons=["Meaningful pullback remains above recent support"],
            invalidation_conditions=["Price closes below recent support"],
        )

    return Classification(
        state=SetupState.NORMAL,
        confidence=0.5,
        reasons=["No actionable repair, exhaustion, or breakdown pattern is confirmed"],
        invalidation_conditions=["Re-evaluate after the next completed 15-minute bar"],
    )


def calculate_underlying_score(
    features: TechnicalFeatures,
    *,
    company_quality: float,
    benchmark_confirmed: bool,
) -> float:
    if not 0 <= company_quality <= 2:
        raise ValueError("company_quality must be between 0 and 2")
    score = company_quality
    score += 1.5 if features.current_price >= features.ema20 else 0.3
    score += 1.0 if features.ema9 >= features.ema20 else 0.2
    score += 1.5 if features.higher_low else (0.1 if features.lower_low else 0.7)
    score += 1.0 if features.macd >= features.macd_signal else 0.3
    score += 1.0 if 40 <= features.rsi14 <= 70 else 0.3
    score += 1.0 if features.current_price >= features.vwap else 0.2
    score += 1.0 if benchmark_confirmed else 0.1
    return round(min(10.0, max(0.0, score)), 1)
