from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.classification.config import ClassificationConfig
from app.classification.models import (
    ClassificationEvaluation,
    ClassificationProposal,
    EvaluationStatus,
    PortfolioRole,
    ProposalStatus,
    ProposalType,
    ReviewMode,
    RoleEvidence,
    TickerProfile,
)
from app.classification.repository import ClassificationRepository
from app.classification.scoring import evaluate_profile


class ClassificationReviewError(RuntimeError):
    pass


class ProfileNotFoundError(ClassificationReviewError):
    pass


QUALIFYING_STATUSES = {
    EvaluationStatus.AWAITING_CONFIRMATION,
    EvaluationStatus.PROPOSAL_CREATED,
    EvaluationStatus.DUPLICATE_PENDING,
    EvaluationStatus.COOLDOWN_BLOCKED,
    EvaluationStatus.SNOOZE_BLOCKED,
}


def _updated_evaluation(
    evaluation: ClassificationEvaluation, **updates: object
) -> ClassificationEvaluation:
    return ClassificationEvaluation.model_validate(
        {**evaluation.model_dump(), **updates}
    )


class ClassificationReviewer:
    def __init__(
        self,
        repository: ClassificationRepository,
        config: ClassificationConfig,
    ) -> None:
        self.repository = repository
        self.config = config

    def review(
        self,
        ticker: str,
        evidence: tuple[RoleEvidence, ...] | list[RoleEvidence],
        *,
        review_mode: ReviewMode = ReviewMode.MANUAL,
        created_at: datetime | None = None,
        persist_evidence: bool = True,
    ) -> ClassificationEvaluation:
        now = created_at or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        now = now.astimezone(UTC)
        normalized = ticker.strip().upper()
        profile = self.repository.get_profile(normalized)
        if profile is None:
            raise ProfileNotFoundError(f"profile not found: {normalized}")
        evidence_tuple = tuple(evidence)
        if any(item.ticker != normalized for item in evidence_tuple):
            raise ValueError("all evidence must match the reviewed ticker")
        if persist_evidence:
            for item in evidence_tuple:
                self.repository.append_evidence(item)

        evaluation = evaluate_profile(
            profile,
            evidence_tuple,
            self.config,
            review_mode=review_mode,
            created_at=now,
        )
        if evaluation.status is not EvaluationStatus.AWAITING_CONFIRMATION:
            self.repository.append_review_cycle(evaluation)
            return evaluation

        streak = 1 + self._prior_qualifying_streak(evaluation)
        evaluation = _updated_evaluation(
            evaluation, consecutive_win_count=streak
        )
        if streak < self.config.required_confirmation_cycles:
            self.repository.append_review_cycle(evaluation)
            return evaluation

        self.repository.expire_stale_proposals(now)
        assert evaluation.winning_candidate is not None
        equivalents = self.repository.find_equivalent_proposals(
            ticker=normalized,
            profile_version=profile.version,
            candidate_role=evaluation.winning_candidate,
        )
        pending = next(
            (
                proposal
                for proposal in equivalents
                if proposal.review_status is ProposalStatus.PENDING
            ),
            None,
        )
        if pending is not None:
            result = _updated_evaluation(
                evaluation,
                status=EvaluationStatus.DUPLICATE_PENDING,
                proposal_id=pending.id,
            )
            self.repository.append_review_cycle(result)
            return result

        active_snooze = next(
            (
                proposal
                for proposal in equivalents
                if proposal.review_status is ProposalStatus.SNOOZED
                and proposal.snooze_until is not None
                and proposal.snooze_until > now
            ),
            None,
        )
        if active_snooze is not None:
            result = _updated_evaluation(
                evaluation,
                status=EvaluationStatus.SNOOZE_BLOCKED,
                proposal_id=active_snooze.id,
            )
            self.repository.append_review_cycle(result)
            return result

        active_rejection = next(
            (
                proposal
                for proposal in equivalents
                if proposal.review_status is ProposalStatus.REJECTED
                and proposal.cooldown_until is not None
                and proposal.cooldown_until > now
                and abs(proposal.score_delta - evaluation.score_delta)
                < self.config.material_score_change
            ),
            None,
        )
        if active_rejection is not None:
            result = _updated_evaluation(
                evaluation,
                status=EvaluationStatus.COOLDOWN_BLOCKED,
                proposal_id=active_rejection.id,
            )
            self.repository.append_review_cycle(result)
            return result

        proposal = self._create_role_change_proposal(
            profile, evaluation, now
        )
        self.repository.save_proposal(proposal)
        result = _updated_evaluation(
            evaluation,
            status=EvaluationStatus.PROPOSAL_CREATED,
            proposal_id=proposal.id,
        )
        self.repository.append_review_cycle(result)
        return result

    def review_stored_evidence(
        self,
        ticker: str,
        *,
        review_mode: ReviewMode = ReviewMode.WEEKLY,
        created_at: datetime | None = None,
    ) -> ClassificationEvaluation:
        evidence = self.repository.latest_evidence(ticker)
        return self.review(
            ticker,
            evidence,
            review_mode=review_mode,
            created_at=created_at,
            persist_evidence=False,
        )

    def _prior_qualifying_streak(
        self, evaluation: ClassificationEvaluation
    ) -> int:
        count = 0
        for previous in self.repository.list_review_cycles(
            evaluation.ticker, newest_first=True
        ):
            if (
                previous.profile_version != evaluation.profile_version
                or previous.winning_candidate
                is not evaluation.winning_candidate
                or previous.status not in QUALIFYING_STATUSES
            ):
                break
            count += 1
        return count

    def _create_role_change_proposal(
        self,
        profile: TickerProfile,
        evaluation: ClassificationEvaluation,
        now: datetime,
    ) -> ClassificationProposal:
        candidate = evaluation.winning_candidate
        if candidate is None:
            raise ClassificationReviewError(
                "cannot create a proposal without a candidate"
            )
        suggested = TickerProfile.model_validate(
            {**profile.model_dump(), "primary_role": candidate}
        )
        return ClassificationProposal(
            id=uuid4(),
            ticker=profile.ticker,
            proposal_type=ProposalType.ROLE_CHANGE,
            current_profile_snapshot=profile,
            suggested_profile_snapshot=suggested,
            confidence=evaluation.evidence_confidence,
            score_delta=evaluation.score_delta,
            evidence_summary=evaluation.evidence_snapshot,
            reason_codes=evaluation.reason_codes,
            created_at=now,
            expires_at=now
            + timedelta(days=self.config.proposal_expiration_days),
            data_completeness=evaluation.data_completeness,
            current_role_score=evaluation.current_role_score,
            candidate_role_scores=evaluation.role_scores,
        )
