from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.starter.models import (
    StarterEvaluationStatus,
    StarterOutcomeObservation,
    StarterPolicyEvaluation,
)

FORWARD_HORIZONS_DAYS = (1, 3, 5, 10)


def build_forward_shadow_export(
    evaluations: Iterable[StarterPolicyEvaluation],
    observations: Iterable[StarterOutcomeObservation],
) -> dict[str, Any]:
    """Build a deterministic, claim-free export for future leakage-safe analysis."""
    evaluation_rows = sorted(
        evaluations,
        key=lambda item: (item.created_at, str(item.evaluation_id)),
    )
    observations_by_evaluation: dict[str, list[StarterOutcomeObservation]] = {}
    for observation in observations:
        observations_by_evaluation.setdefault(
            str(observation.evaluation_id), []
        ).append(observation)

    rows: list[dict[str, Any]] = []
    pending_horizons = {str(day): 0 for day in FORWARD_HORIZONS_DAYS}
    for evaluation in evaluation_rows:
        linked = sorted(
            observations_by_evaluation.get(str(evaluation.evaluation_id), []),
            key=lambda item: (item.observed_at, str(item.observation_id)),
        )
        captured_horizons: list[int] = []
        for horizon in FORWARD_HORIZONS_DAYS:
            if any(item.elapsed_days >= horizon for item in linked):
                captured_horizons.append(horizon)
            elif evaluation.status is StarterEvaluationStatus.SHADOW_ELIGIBLE:
                pending_horizons[str(horizon)] += 1
        rows.append(
            {
                "evaluation_id": str(evaluation.evaluation_id),
                "ticker": evaluation.ticker,
                "status": evaluation.status.value,
                "created_at": evaluation.created_at.isoformat(),
                "observation_count": len(linked),
                "captured_horizons_days": captured_horizons,
                "baseline_present": any(item.baseline for item in linked),
            }
        )

    shadow_count = sum(
        item.status is StarterEvaluationStatus.SHADOW_ELIGIBLE
        for item in evaluation_rows
    )
    return {
        "evaluation_count": len(evaluation_rows),
        "shadow_eligible_sample_count": shadow_count,
        "pending_horizons": pending_horizons,
        "outcome_claim_available": False,
        "rows": rows,
        "future_metrics": [
            "invalidation_first",
            "later_strict_qualification",
            "time_and_price_to_qualification",
            "underlying_and_option_marks_at_1_3_5_10_days",
            "mfe_mae",
            "iv_change",
            "spread_slippage",
            "expectancy_per_unit_risk",
            "tail_loss",
        ],
    }
