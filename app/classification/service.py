from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.classification.config import ClassificationConfig
from app.classification.models import (
    ClassificationDecisionResult,
    PortfolioRole,
    RiskTier,
    TickerProfile,
)
from app.classification.repository import ClassificationRepository
from app.classification.reviewer import ClassificationReviewer


class ClassificationDecisionError(RuntimeError):
    pass


class InvalidDecisionError(ClassificationDecisionError):
    pass


def _required_text(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise InvalidDecisionError(f"{field_name} is required")
    return normalized


def _aware_now(value: datetime | None) -> datetime:
    result = value or datetime.now(UTC)
    if result.tzinfo is None or result.utcoffset() is None:
        raise InvalidDecisionError("decision time must be timezone-aware")
    return result.astimezone(UTC)


class ClassificationService:
    EDITABLE_PROFILE_FIELDS = frozenset(
        {
            "primary_role",
            "groups",
            "strategy_tags",
            "risk_tier",
            "benchmark_tags",
            "company_quality",
            "enabled",
            "asset_class",
            "company_id",
            "exposure_group",
            "target_weight",
            "max_weight",
        }
    )

    def __init__(
        self,
        repository: ClassificationRepository,
        config: ClassificationConfig,
    ) -> None:
        self.repository = repository
        self.config = config
        self.reviewer = ClassificationReviewer(repository, config)

    def accept(
        self,
        proposal_id: str,
        *,
        actor: str,
        occurred_at: datetime | None = None,
    ) -> ClassificationDecisionResult:
        return self.repository.accept_proposal(
            proposal_id,
            actor=_required_text(actor, "actor"),
            occurred_at=_aware_now(occurred_at),
        )

    def reject(
        self,
        proposal_id: str,
        *,
        actor: str,
        reason: str,
        occurred_at: datetime | None = None,
    ) -> ClassificationDecisionResult:
        now = _aware_now(occurred_at)
        return self.repository.reject_proposal(
            proposal_id,
            actor=_required_text(actor, "actor"),
            reason=_required_text(reason, "reason"),
            occurred_at=now,
            cooldown_until=now
            + timedelta(days=self.config.proposal_cooldown_days),
        )

    def snooze(
        self,
        proposal_id: str,
        *,
        actor: str,
        reason: str,
        snooze_until: datetime,
        occurred_at: datetime | None = None,
    ) -> ClassificationDecisionResult:
        now = _aware_now(occurred_at)
        until = _aware_now(snooze_until)
        if until <= now:
            raise InvalidDecisionError("snooze_until must be in the future")
        return self.repository.snooze_proposal(
            proposal_id,
            actor=_required_text(actor, "actor"),
            reason=_required_text(reason, "reason"),
            occurred_at=now,
            snooze_until=until,
        )

    def manual_edit(
        self,
        ticker: str,
        changes: dict[str, Any],
        *,
        expected_version: int,
        actor: str,
        reason: str,
        occurred_at: datetime | None = None,
    ) -> ClassificationDecisionResult:
        normalized = ticker.strip().upper()
        current = self.repository.get_profile(normalized)
        if current is None:
            raise LookupError(f"profile not found: {normalized}")
        unsupported = set(changes) - self.EDITABLE_PROFILE_FIELDS
        if unsupported:
            raise InvalidDecisionError(
                f"unsupported profile fields: {', '.join(sorted(unsupported))}"
            )
        proposed = TickerProfile.model_validate(
            {**current.model_dump(), **changes}
        )
        return self.repository.manual_edit_profile(
            proposed,
            expected_version=expected_version,
            actor=_required_text(actor, "actor"),
            reason=_required_text(reason, "reason"),
            occurred_at=_aware_now(occurred_at),
        )
