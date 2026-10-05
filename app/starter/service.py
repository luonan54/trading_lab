from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from app.call_readiness import evaluate_call_readiness
from app.config import AppConfig
from app.db import SnapshotRepository
from app.models import ScanSnapshot
from app.options.models import OptionsScanResult
from app.options.repository import OptionsScanRepository
from app.runtime_universe import (
    RuntimeUniverseResolver,
    RuntimeUniverseSource,
)
from app.starter.models import (
    EquitySnapshot,
    FullSetupRiskSnapshot,
    OptionCandidateFitSummary,
    OptionsFitSummary,
    OptionsResultSource,
    PostEventAssessment,
    PostEventAssessmentInput,
    ProfileSnapshot,
    ReadinessSnapshot,
    StarterOptionsScanStatus,
    StarterOptionsFeed,
    StarterOutcomeObservation,
    StarterPolicyEvaluation,
    StarterPolicyInput,
)
from app.starter.policy import evaluate_starter_policy
from app.starter.repository import (
    StarterConflictError,
    StarterNotFoundError,
    StarterRepository,
)


class StarterServiceUnavailable(RuntimeError):
    pass


def equity_snapshot_id(snapshot: ScanSnapshot) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"nanzone-equity:{snapshot.ticker}:{snapshot.scanned_at.isoformat()}",
    )


def _candidate_spread_valid(result) -> bool:
    contract = result.contract
    return (
        contract.bid is not None
        and contract.ask is not None
        and contract.bid > 0
        and contract.ask >= contract.bid
    )


class StarterService:
    def __init__(
        self,
        config: AppConfig,
        repository: StarterRepository,
        equity_repository: SnapshotRepository,
        options_repository: OptionsScanRepository | None,
        universe_resolver: RuntimeUniverseResolver,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        readiness_evaluator: Callable = evaluate_call_readiness,
    ) -> None:
        self.config = config
        self.repository = repository
        self.equity_repository = equity_repository
        self.options_repository = options_repository
        self.universe_resolver = universe_resolver
        self._clock = clock
        self._readiness_evaluator = readiness_evaluator

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("service clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    def create_assessment(
        self,
        raw: PostEventAssessmentInput,
        *,
        supersedes: UUID | None = None,
    ) -> PostEventAssessment:
        now = self._now()
        if raw.entered_at > now + timedelta(minutes=1):
            raise ValueError("entered_at cannot be in the future")
        if raw.ticker not in self.config.starter.approved_tickers:
            raise ValueError("ticker is not approved for Starter V1")
        if raw.event_type not in self.config.starter.allowed_event_types:
            raise ValueError("event type is not allowed for Starter V1")
        if supersedes is None:
            assessment = PostEventAssessment.create(
                raw,
                assessment_valid_hours=self.config.starter.assessment_valid_hours,
            )
        else:
            previous = self.repository.get_assessment(supersedes)
            if previous is None:
                raise StarterNotFoundError(
                    f"assessment not found: {supersedes}"
                )
            assessment = previous.correct(
                raw,
                assessment_valid_hours=self.config.starter.assessment_valid_hours,
            )
        self.repository.save_assessment(assessment)
        return assessment

    def _options_fit(
        self,
        result: OptionsScanResult | None,
        *,
        snapshot: ScanSnapshot,
    ) -> OptionsFitSummary | None:
        if result is None:
            return None
        linked_at = result.equity_snapshot_at
        linked_id = (
            uuid5(
                NAMESPACE_URL,
                f"nanzone-equity:{result.ticker}:{linked_at.isoformat()}",
            )
            if linked_at is not None
            else uuid5(NAMESPACE_URL, f"unlinked-options:{result.scan_id}")
        )
        common = {
            "options_scan_id": result.scan_id,
            "ticker": result.ticker,
            "equity_snapshot_id": linked_id,
            "result_at": result.scanned_at,
            "result_source": (
                OptionsResultSource.MANUAL
                if result.eligibility.manual_override
                else OptionsResultSource.NORMAL
            ),
            "scan_status": StarterOptionsScanStatus(result.status.value),
            "feed": StarterOptionsFeed(
                result.feed or self.config.strategy.options.provider.feed
            ),
        }
        if not result.accepted_candidates:
            return OptionsFitSummary(**common, candidate=None)
        gates = self.config.starter.options

        def passes(candidate) -> bool:
            relative_iv = candidate.contract.chain_relative_iv_percentile
            return (
                candidate.options_quality_score >= gates.min_candidate_quality
                and candidate.options_score_confidence
                >= gates.min_candidate_confidence
                and (
                    not gates.require_relative_iv
                    or (
                        relative_iv is not None
                        and relative_iv <= gates.max_relative_iv_percentile
                    )
                )
                and _candidate_spread_valid(candidate)
            )

        candidate = next(
            (
                item
                for item in sorted(
                    result.accepted_candidates,
                    key=lambda item: item.combined_score,
                    reverse=True,
                )
                if passes(item)
            ),
            max(
                result.accepted_candidates,
                key=lambda item: item.combined_score,
            ),
        )
        hard_blockers = tuple(
            value
            for value in (result.error_status, result.error_message)
            if value
        )
        return OptionsFitSummary(
            **common,
            candidate=OptionCandidateFitSummary(
                contract_symbol=candidate.contract.contract_symbol,
                mid=(
                    (candidate.contract.bid + candidate.contract.ask) / 2
                    if candidate.contract.bid is not None
                    and candidate.contract.ask is not None
                    else None
                ),
                quality_score=candidate.options_quality_score,
                confidence=candidate.options_score_confidence,
                relative_iv_percentile=(
                    candidate.contract.chain_relative_iv_percentile
                ),
                liquidity_valid=True,
                spread_valid=_candidate_spread_valid(candidate),
                hard_blocker_codes=hard_blockers,
            ),
        )

    def evaluate(self, ticker: str) -> StarterPolicyEvaluation:
        normalized = ticker.strip().upper()
        now = self._now()
        universe = self.universe_resolver.resolve()
        if universe.source is not RuntimeUniverseSource.CONFIRMED_DB:
            raise StarterServiceUnavailable(
                "confirmed profile authority is unavailable"
            )
        symbol = universe.symbols.get(normalized)
        if symbol is None or symbol.profile_version is None:
            raise StarterNotFoundError(
                f"confirmed profile not found: {normalized}"
            )
        snapshot = self.equity_repository.latest(normalized)
        if snapshot is None:
            raise StarterNotFoundError(
                f"equity snapshot not found: {normalized}"
            )

        readiness = self._readiness_evaluator(
            snapshot,
            allow_call_candidate=symbol.allows_call_candidate,
            as_of=now,
            entry_policy=self.config.strategy.entry,
            momentum_rsi=self.config.strategy.thresholds.momentum_rsi,
        )
        assessment = self.repository.latest_active_assessment(
            normalized, at=now
        )
        risk = (
            None
            if assessment is None
            else FullSetupRiskSnapshot(
                risk_plan_id=assessment.risk_plan_id,
                planned_full_setup_risk_budget_usd=(
                    assessment.planned_full_setup_risk_budget_usd
                ),
            )
        )
        options_result = (
            self.options_repository.latest(normalized)
            if self.options_repository is not None
            else None
        )
        frozen_input = StarterPolicyInput(
            evaluated_at=now,
            profile=ProfileSnapshot(
                ticker=normalized,
                profile_version=symbol.profile_version,
                confirmed=True,
                enabled=symbol.enabled,
                asset_class=symbol.asset_class,
                groups=symbol.groups,
            ),
            equity=EquitySnapshot(
                snapshot_id=equity_snapshot_id(snapshot),
                ticker=normalized,
                snapshot_at=snapshot.scanned_at,
                snapshot_price=snapshot.features.current_price,
                state=snapshot.current_state,
                tech_setup_score=snapshot.ceg_tech_score,
                lower_low=snapshot.features.lower_low,
                atr14=snapshot.features.atr14,
                local_support=snapshot.features.local_support,
                local_resistance=snapshot.features.local_resistance,
                rsi14=snapshot.features.rsi14,
                readiness=ReadinessSnapshot.from_evaluation(readiness),
            ),
            event_assessment=assessment,
            full_setup_risk=risk,
            options_fit=self._options_fit(
                options_result,
                snapshot=snapshot,
            ),
        )
        evaluation = evaluate_starter_policy(
            frozen_input, self.config.starter
        )
        if evaluation.shadow_eligible:
            candidate = (
                evaluation.options_fit_summary.candidate
                if evaluation.options_fit_summary is not None
                else None
            )
            baseline = StarterOutcomeObservation(
                evaluation_id=evaluation.evaluation_id,
                observed_at=now,
                elapsed_days=0,
                underlying_price=snapshot.features.current_price,
                option_symbol=(
                    candidate.contract_symbol if candidate is not None else None
                ),
                option_mid=candidate.mid if candidate is not None else None,
                strict_readiness=readiness.call_readiness,
                invalidation_observed=(
                    evaluation.invalidation is not None
                    and snapshot.features.current_price
                    <= evaluation.invalidation.level
                ),
                equity_snapshot_id=frozen_input.equity.snapshot_id,
                options_scan_id=evaluation.options_scan_id,
                baseline=True,
            )
            self.repository.save_evaluation_with_baseline(
                evaluation,
                baseline,
                frozen_input=frozen_input,
            )
        else:
            self.repository.save_evaluation(
                evaluation, frozen_input=frozen_input
            )
        return evaluation
