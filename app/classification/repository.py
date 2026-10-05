from __future__ import annotations

from datetime import datetime
from typing import TypeVar
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.classification.migrations import (
    create_classification_engine,
    initialize_classification_schema,
)
from app.classification.models import (
    ClassificationAuditEvent,
    ClassificationDecisionResult,
    ClassificationEvaluation,
    ClassificationProposal,
    ClassificationReasonCode,
    DecisionSource,
    EvaluationStatus,
    PortfolioRole,
    ProposalStatus,
    ProposalType,
    RoleEvidence,
    TickerProfile,
    TickerProfileHistory,
)


class ClassificationBase(DeclarativeBase):
    pass


class TickerProfileRecord(ClassificationBase):
    __tablename__ = "ticker_profiles"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_ticker_profiles_version"),
    )

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    primary_role: Mapped[str] = mapped_column(String(32), index=True)
    risk_tier: Mapped[str] = mapped_column(String(20), index=True)
    version: Mapped[int] = mapped_column(Integer)
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    confirmed_by: Mapped[str] = mapped_column(String(120))
    payload: Mapped[dict] = mapped_column(JSON)


class RoleEvidenceRecord(ClassificationBase):
    __tablename__ = "role_evidence"
    __table_args__ = (
        Index(
            "ix_role_evidence_ticker_category_source",
            "ticker",
            "category",
            "source_timestamp",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    category: Mapped[str] = mapped_column(String(40), index=True)
    source_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    payload: Mapped[dict] = mapped_column(JSON)


class ClassificationProposalRecord(ClassificationBase):
    __tablename__ = "classification_proposals"
    __table_args__ = (
        Index(
            "ix_classification_proposals_ticker_status_created",
            "ticker",
            "status",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    proposal_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    payload: Mapped[dict] = mapped_column(JSON)


class TickerProfileHistoryRecord(ClassificationBase):
    __tablename__ = "ticker_profile_history"
    __table_args__ = (
        CheckConstraint(
            "profile_version >= 1",
            name="ck_ticker_profile_history_version",
        ),
        UniqueConstraint(
            "ticker",
            "profile_version",
            name="uq_ticker_profile_history_ticker_version",
        ),
        Index(
            "ix_ticker_profile_history_ticker_effective",
            "ticker",
            "effective_from",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    profile_version: Mapped[int] = mapped_column(Integer, index=True)
    decision_source: Mapped[str] = mapped_column(String(40), index=True)
    proposal_id: Mapped[str | None] = mapped_column(String(36), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class ClassificationReviewCycleRecord(ClassificationBase):
    __tablename__ = "classification_review_cycles"
    __table_args__ = (
        Index(
            "ix_classification_review_cycles_ticker_created",
            "ticker",
            "created_at",
        ),
        Index(
            "ix_classification_review_cycles_candidate_status",
            "candidate_role",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    profile_version: Mapped[int] = mapped_column(Integer, index=True)
    candidate_role: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class ClassificationAuditLogRecord(ClassificationBase):
    __tablename__ = "classification_audit_log"
    __table_args__ = (
        Index(
            "ix_classification_audit_log_ticker_occurred",
            "ticker",
            "occurred_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    decision_source: Mapped[str] = mapped_column(String(40), index=True)
    actor: Mapped[str] = mapped_column(String(120), index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    proposal_id: Mapped[str | None] = mapped_column(String(36), index=True)
    payload: Mapped[dict] = mapped_column(JSON)


ModelT = TypeVar(
    "ModelT",
    TickerProfile,
    RoleEvidence,
    ClassificationProposal,
    TickerProfileHistory,
    ClassificationEvaluation,
    ClassificationAuditEvent,
)


def _payload(model: ModelT) -> dict:
    return model.model_dump(mode="json")


class ClassificationRepository:
    def __init__(self, database_url: str, *, initialize_schema: bool = True) -> None:
        self.engine = create_classification_engine(database_url)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        if initialize_schema:
            initialize_classification_schema(self.engine)

    def get_profile(self, ticker: str) -> TickerProfile | None:
        with self.sessions() as session:
            record = session.get(TickerProfileRecord, ticker.strip().upper())
            return TickerProfile.model_validate(record.payload) if record else None

    def list_profiles(self) -> list[TickerProfile]:
        with self.sessions() as session:
            records = session.scalars(
                select(TickerProfileRecord).order_by(TickerProfileRecord.ticker)
            ).all()
            return [TickerProfile.model_validate(record.payload) for record in records]

    def insert_profile_if_absent(self, profile: TickerProfile) -> bool:
        if self.engine.dialect.name == "sqlite":
            with self.sessions.begin() as session:
                result = session.execute(
                    sqlite_insert(TickerProfileRecord)
                    .values(**self._profile_values(profile))
                    .on_conflict_do_nothing(index_elements=["ticker"])
                )
                return result.rowcount == 1
        with self.sessions() as session:
            if session.get(TickerProfileRecord, profile.ticker) is not None:
                return False
            session.add(self._profile_record(profile))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if session.get(TickerProfileRecord, profile.ticker) is not None:
                    return False
                raise
            return True

    def initialize_profile(
        self,
        profile: TickerProfile,
        history: TickerProfileHistory,
    ) -> bool:
        if history.old_profile_snapshot is not None:
            raise ValueError("initialization history must not have an old profile")
        if history.new_profile_snapshot != profile:
            raise ValueError("initialization history must contain the inserted profile")
        if self.engine.dialect.name == "sqlite":
            with self.sessions.begin() as session:
                result = session.execute(
                    sqlite_insert(TickerProfileRecord)
                    .values(**self._profile_values(profile))
                    .on_conflict_do_nothing(index_elements=["ticker"])
                )
                if result.rowcount != 1:
                    return False
                session.add(self._history_record(history))
                return True
        with self.sessions() as session:
            if session.get(TickerProfileRecord, profile.ticker) is not None:
                return False
            session.add(self._profile_record(profile))
            session.add(self._history_record(history))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if session.get(TickerProfileRecord, profile.ticker) is not None:
                    return False
                raise
            return True

    def append_evidence(self, evidence: RoleEvidence) -> str:
        record_id = str(uuid4())
        with self.sessions.begin() as session:
            session.add(
                RoleEvidenceRecord(
                    id=record_id,
                    ticker=evidence.ticker,
                    category=evidence.category.value,
                    source_timestamp=evidence.source_timestamp,
                    payload=_payload(evidence),
                )
            )
        return record_id

    def list_evidence(self, ticker: str) -> list[RoleEvidence]:
        with self.sessions() as session:
            records = session.scalars(
                select(RoleEvidenceRecord)
                .where(RoleEvidenceRecord.ticker == ticker.strip().upper())
                .order_by(
                    RoleEvidenceRecord.source_timestamp,
                    RoleEvidenceRecord.id,
                )
            ).all()
            return [RoleEvidence.model_validate(record.payload) for record in records]

    def latest_evidence(self, ticker: str) -> list[RoleEvidence]:
        from app.classification.scoring import latest_evidence_by_category

        return list(latest_evidence_by_category(self.list_evidence(ticker)))

    def save_proposal(self, proposal: ClassificationProposal) -> None:
        with self.sessions.begin() as session:
            session.add(
                ClassificationProposalRecord(
                    id=str(proposal.id),
                    ticker=proposal.ticker,
                    proposal_type=proposal.proposal_type.value,
                    status=proposal.review_status.value,
                    created_at=proposal.created_at,
                    expires_at=proposal.expires_at,
                    payload=_payload(proposal),
                )
            )

    def get_proposal(self, proposal_id: str) -> ClassificationProposal | None:
        with self.sessions() as session:
            record = session.get(
                ClassificationProposalRecord, str(proposal_id)
            )
            return (
                ClassificationProposal.model_validate(record.payload)
                if record
                else None
            )

    def list_proposals(
        self,
        *,
        ticker: str | None = None,
        status: ProposalStatus | None = None,
    ) -> list[ClassificationProposal]:
        statement = select(ClassificationProposalRecord)
        if ticker is not None:
            statement = statement.where(
                ClassificationProposalRecord.ticker == ticker.strip().upper()
            )
        if status is not None:
            statement = statement.where(
                ClassificationProposalRecord.status == status.value
            )
        statement = statement.order_by(
            ClassificationProposalRecord.created_at.desc(),
            ClassificationProposalRecord.id.desc(),
        )
        with self.sessions() as session:
            records = session.scalars(statement).all()
            return [
                ClassificationProposal.model_validate(record.payload)
                for record in records
            ]

    def update_proposal(self, proposal: ClassificationProposal) -> None:
        with self.sessions.begin() as session:
            record = session.get(
                ClassificationProposalRecord, str(proposal.id)
            )
            if record is None:
                raise LookupError(f"proposal not found: {proposal.id}")
            record.ticker = proposal.ticker
            record.proposal_type = proposal.proposal_type.value
            record.status = proposal.review_status.value
            record.created_at = proposal.created_at
            record.expires_at = proposal.expires_at
            record.payload = _payload(proposal)

    def expire_stale_proposals(self, now: datetime) -> int:
        expired = 0
        for proposal in self.list_proposals(status=ProposalStatus.PENDING):
            if proposal.expires_at is None or proposal.expires_at > now:
                continue
            updated = ClassificationProposal.model_validate(
                {
                    **proposal.model_dump(),
                    "review_status": ProposalStatus.EXPIRED,
                }
            )
            self.update_proposal(updated)
            expired += 1
        return expired

    def find_equivalent_proposals(
        self,
        *,
        ticker: str,
        profile_version: int,
        candidate_role: PortfolioRole,
    ) -> list[ClassificationProposal]:
        return [
            proposal
            for proposal in self.list_proposals(ticker=ticker)
            if proposal.current_profile_snapshot.version == profile_version
            and proposal.suggested_role is candidate_role
        ]

    def append_review_cycle(
        self, evaluation: ClassificationEvaluation
    ) -> str:
        record_id = str(uuid4())
        with self.sessions.begin() as session:
            session.add(
                ClassificationReviewCycleRecord(
                    id=record_id,
                    ticker=evaluation.ticker,
                    created_at=evaluation.created_at,
                    profile_version=evaluation.profile_version,
                    candidate_role=(
                        evaluation.winning_candidate.value
                        if evaluation.winning_candidate is not None
                        else None
                    ),
                    status=evaluation.status.value,
                    payload=_payload(evaluation),
                )
            )
        return record_id

    def list_review_cycles(
        self, ticker: str, *, newest_first: bool = False
    ) -> list[ClassificationEvaluation]:
        order = (
            ClassificationReviewCycleRecord.created_at.desc()
            if newest_first
            else ClassificationReviewCycleRecord.created_at
        )
        with self.sessions() as session:
            records = session.scalars(
                select(ClassificationReviewCycleRecord)
                .where(
                    ClassificationReviewCycleRecord.ticker
                    == ticker.strip().upper()
                )
                .order_by(order, ClassificationReviewCycleRecord.id)
            ).all()
            return [
                ClassificationEvaluation.model_validate(record.payload)
                for record in records
            ]

    def list_audit_events(
        self, ticker: str | None = None
    ) -> list[ClassificationAuditEvent]:
        statement = select(ClassificationAuditLogRecord)
        if ticker is not None:
            statement = statement.where(
                ClassificationAuditLogRecord.ticker
                == ticker.strip().upper()
            )
        statement = statement.order_by(
            ClassificationAuditLogRecord.occurred_at,
            ClassificationAuditLogRecord.id,
        )
        with self.sessions() as session:
            records = session.scalars(statement).all()
            return [
                ClassificationAuditEvent.model_validate(record.payload)
                for record in records
            ]

    def accept_proposal(
        self,
        proposal_id: str,
        *,
        actor: str,
        occurred_at: datetime,
    ) -> ClassificationDecisionResult:
        terminal_error: RuntimeError | None = None
        result: ClassificationDecisionResult | None = None
        with self.sessions.begin() as session:
            record = session.get(ClassificationProposalRecord, proposal_id)
            if record is None:
                raise LookupError(f"proposal not found: {proposal_id}")
            proposal = ClassificationProposal.model_validate(record.payload)
            if proposal.review_status is not ProposalStatus.PENDING:
                raise ValueError(
                    f"proposal is not actionable: {proposal.review_status.value}"
                )
            if (
                proposal.expires_at is not None
                and proposal.expires_at <= occurred_at
            ):
                expired = self._updated_proposal(
                    proposal, review_status=ProposalStatus.EXPIRED
                )
                self._write_proposal_record(record, expired)
                terminal_error = ValueError("proposal has expired")
            else:
                profile_record = session.get(
                    TickerProfileRecord, proposal.ticker
                )
                if profile_record is None:
                    raise LookupError(
                        f"profile not found: {proposal.ticker}"
                    )
                current = TickerProfile.model_validate(
                    profile_record.payload
                )
                if current != proposal.current_profile_snapshot:
                    superseded = self._updated_proposal(
                        proposal, review_status=ProposalStatus.SUPERSEDED
                    )
                    self._write_proposal_record(record, superseded)
                    terminal_error = RuntimeError(
                        "confirmed profile changed after proposal creation"
                    )
                else:
                    next_profile = self._accepted_profile(
                        current,
                        proposal,
                        actor=actor,
                        occurred_at=occurred_at,
                    )
                    updated = session.execute(
                        update(TickerProfileRecord)
                        .where(
                            TickerProfileRecord.ticker == current.ticker,
                            TickerProfileRecord.version == current.version,
                        )
                        .values(**self._profile_values(next_profile))
                    )
                    if updated.rowcount != 1:
                        raise RuntimeError(
                            "profile version conflict during acceptance"
                        )
                    history = TickerProfileHistory(
                        id=uuid4(),
                        ticker=current.ticker,
                        old_profile_snapshot=current,
                        new_profile_snapshot=next_profile,
                        effective_from=occurred_at,
                        confirmed_at=occurred_at,
                        decision_source=DecisionSource.USER_ACCEPTED_PROPOSAL,
                        proposal_id=proposal.id,
                        reason_codes=proposal.reason_codes,
                        evidence_snapshot=proposal.evidence_summary,
                        profile_version=next_profile.version,
                    )
                    accepted = self._updated_proposal(
                        proposal,
                        review_status=ProposalStatus.ACCEPTED,
                        reviewed_at=occurred_at,
                        reviewed_by=actor,
                        decision_reason="Accepted proposed classification change",
                    )
                    audit = ClassificationAuditEvent(
                        id=uuid4(),
                        ticker=current.ticker,
                        decision_source=DecisionSource.USER_ACCEPTED_PROPOSAL,
                        actor=actor,
                        reason="Accepted proposed classification change",
                        occurred_at=occurred_at,
                        proposal_id=proposal.id,
                        old_profile_snapshot=current,
                        new_profile_snapshot=next_profile,
                    )
                    session.add(self._history_record(history))
                    session.add(self._audit_record(audit))
                    self._write_proposal_record(record, accepted)
                    result = ClassificationDecisionResult(
                        profile=next_profile,
                        proposal=accepted,
                        audit_event=audit,
                    )
        if terminal_error is not None:
            raise terminal_error
        assert result is not None
        return result

    def reject_proposal(
        self,
        proposal_id: str,
        *,
        actor: str,
        reason: str,
        occurred_at: datetime,
        cooldown_until: datetime,
    ) -> ClassificationDecisionResult:
        return self._close_proposal_without_profile_change(
            proposal_id,
            actor=actor,
            reason=reason,
            occurred_at=occurred_at,
            status=ProposalStatus.REJECTED,
            decision_source=DecisionSource.USER_REJECTED_PROPOSAL,
            cooldown_until=cooldown_until,
        )

    def snooze_proposal(
        self,
        proposal_id: str,
        *,
        actor: str,
        reason: str,
        occurred_at: datetime,
        snooze_until: datetime,
    ) -> ClassificationDecisionResult:
        return self._close_proposal_without_profile_change(
            proposal_id,
            actor=actor,
            reason=reason,
            occurred_at=occurred_at,
            status=ProposalStatus.SNOOZED,
            decision_source=DecisionSource.USER_SNOOZED_PROPOSAL,
            snooze_until=snooze_until,
        )

    def manual_edit_profile(
        self,
        proposed_profile: TickerProfile,
        *,
        expected_version: int,
        actor: str,
        reason: str,
        occurred_at: datetime,
    ) -> ClassificationDecisionResult:
        with self.sessions.begin() as session:
            record = session.get(
                TickerProfileRecord, proposed_profile.ticker
            )
            if record is None:
                raise LookupError(
                    f"profile not found: {proposed_profile.ticker}"
                )
            current = TickerProfile.model_validate(record.payload)
            if current.version != expected_version:
                raise RuntimeError(
                    f"profile version conflict: expected {expected_version}, "
                    f"found {current.version}"
                )
            next_profile = TickerProfile.model_validate(
                {
                    **proposed_profile.model_dump(),
                    "ticker": current.ticker,
                    "version": current.version + 1,
                    "confirmed_at": occurred_at,
                    "confirmed_by": actor,
                }
            )
            updated = session.execute(
                update(TickerProfileRecord)
                .where(
                    TickerProfileRecord.ticker == current.ticker,
                    TickerProfileRecord.version == expected_version,
                )
                .values(**self._profile_values(next_profile))
            )
            if updated.rowcount != 1:
                raise RuntimeError(
                    "profile version conflict during manual edit"
                )
            history = TickerProfileHistory(
                id=uuid4(),
                ticker=current.ticker,
                old_profile_snapshot=current,
                new_profile_snapshot=next_profile,
                effective_from=occurred_at,
                confirmed_at=occurred_at,
                decision_source=DecisionSource.MANUAL_USER_EDIT,
                reason_codes=(),
                evidence_snapshot=(),
                profile_version=next_profile.version,
            )
            audit = ClassificationAuditEvent(
                id=uuid4(),
                ticker=current.ticker,
                decision_source=DecisionSource.MANUAL_USER_EDIT,
                actor=actor,
                reason=reason,
                occurred_at=occurred_at,
                old_profile_snapshot=current,
                new_profile_snapshot=next_profile,
            )
            session.add(self._history_record(history))
            session.add(self._audit_record(audit))
        return ClassificationDecisionResult(
            profile=next_profile,
            audit_event=audit,
        )

    def _close_proposal_without_profile_change(
        self,
        proposal_id: str,
        *,
        actor: str,
        reason: str,
        occurred_at: datetime,
        status: ProposalStatus,
        decision_source: DecisionSource,
        cooldown_until: datetime | None = None,
        snooze_until: datetime | None = None,
    ) -> ClassificationDecisionResult:
        terminal_error: RuntimeError | None = None
        result: ClassificationDecisionResult | None = None
        with self.sessions.begin() as session:
            record = session.get(ClassificationProposalRecord, proposal_id)
            if record is None:
                raise LookupError(f"proposal not found: {proposal_id}")
            proposal = ClassificationProposal.model_validate(record.payload)
            if proposal.review_status is not ProposalStatus.PENDING:
                raise ValueError(
                    f"proposal is not actionable: {proposal.review_status.value}"
                )
            if (
                proposal.expires_at is not None
                and proposal.expires_at <= occurred_at
            ):
                expired = self._updated_proposal(
                    proposal, review_status=ProposalStatus.EXPIRED
                )
                self._write_proposal_record(record, expired)
                terminal_error = ValueError("proposal has expired")
            else:
                profile_record = session.get(
                    TickerProfileRecord, proposal.ticker
                )
                if profile_record is None:
                    raise LookupError(
                        f"profile not found: {proposal.ticker}"
                    )
                current = TickerProfile.model_validate(
                    profile_record.payload
                )
                closed = self._updated_proposal(
                    proposal,
                    review_status=status,
                    reviewed_at=occurred_at,
                    reviewed_by=actor,
                    decision_reason=reason,
                    cooldown_until=cooldown_until,
                    snooze_until=snooze_until,
                )
                audit = ClassificationAuditEvent(
                    id=uuid4(),
                    ticker=current.ticker,
                    decision_source=decision_source,
                    actor=actor,
                    reason=reason,
                    occurred_at=occurred_at,
                    proposal_id=proposal.id,
                    old_profile_snapshot=current,
                    new_profile_snapshot=current,
                )
                self._write_proposal_record(record, closed)
                session.add(self._audit_record(audit))
                result = ClassificationDecisionResult(
                    profile=current,
                    proposal=closed,
                    audit_event=audit,
                )
        if terminal_error is not None:
            raise terminal_error
        assert result is not None
        return result

    def append_history(self, history: TickerProfileHistory) -> None:
        with self.sessions.begin() as session:
            session.add(self._history_record(history))

    def list_history(self, ticker: str) -> list[TickerProfileHistory]:
        with self.sessions() as session:
            records = session.scalars(
                select(TickerProfileHistoryRecord)
                .where(
                    TickerProfileHistoryRecord.ticker
                    == ticker.strip().upper()
                )
                .order_by(
                    TickerProfileHistoryRecord.profile_version,
                    TickerProfileHistoryRecord.effective_from,
                )
            ).all()
            return [
                TickerProfileHistory.model_validate(record.payload)
                for record in records
            ]

    @staticmethod
    def _profile_values(profile: TickerProfile) -> dict:
        return {
            "ticker": profile.ticker,
            "primary_role": profile.primary_role.value,
            "risk_tier": profile.risk_tier.value,
            "version": profile.version,
            "confirmed_at": profile.confirmed_at,
            "confirmed_by": profile.confirmed_by,
            "payload": _payload(profile),
        }

    @classmethod
    def _profile_record(cls, profile: TickerProfile) -> TickerProfileRecord:
        return TickerProfileRecord(
            **cls._profile_values(profile)
        )

    @staticmethod
    def _history_record(
        history: TickerProfileHistory,
    ) -> TickerProfileHistoryRecord:
        return TickerProfileHistoryRecord(
            id=str(history.id),
            ticker=history.ticker,
            effective_from=history.effective_from,
            profile_version=history.profile_version,
            decision_source=history.decision_source.value,
            proposal_id=(
                str(history.proposal_id)
                if history.proposal_id is not None
                else None
            ),
            payload=_payload(history),
        )

    @staticmethod
    def _audit_record(
        event: ClassificationAuditEvent,
    ) -> ClassificationAuditLogRecord:
        return ClassificationAuditLogRecord(
            id=str(event.id),
            ticker=event.ticker,
            decision_source=event.decision_source.value,
            actor=event.actor,
            occurred_at=event.occurred_at,
            proposal_id=(
                str(event.proposal_id)
                if event.proposal_id is not None
                else None
            ),
            payload=_payload(event),
        )

    @staticmethod
    def _updated_proposal(
        proposal: ClassificationProposal, **updates: object
    ) -> ClassificationProposal:
        return ClassificationProposal.model_validate(
            {**proposal.model_dump(), **updates}
        )

    @staticmethod
    def _write_proposal_record(
        record: ClassificationProposalRecord,
        proposal: ClassificationProposal,
    ) -> None:
        record.ticker = proposal.ticker
        record.proposal_type = proposal.proposal_type.value
        record.status = proposal.review_status.value
        record.created_at = proposal.created_at
        record.expires_at = proposal.expires_at
        record.payload = _payload(proposal)

    @staticmethod
    def _accepted_profile(
        current: TickerProfile,
        proposal: ClassificationProposal,
        *,
        actor: str,
        occurred_at: datetime,
    ) -> TickerProfile:
        suggested = proposal.suggested_profile_snapshot
        allowed_fields = {
            ProposalType.ROLE_CHANGE: ("primary_role",),
            ProposalType.GROUP_ADD: ("groups",),
            ProposalType.GROUP_REMOVE: ("groups",),
            ProposalType.RISK_TIER_CHANGE: ("risk_tier",),
            ProposalType.STRATEGY_TAG_ADD: ("strategy_tags",),
            ProposalType.STRATEGY_TAG_REMOVE: ("strategy_tags",),
            ProposalType.BENCHMARK_TAG_CHANGE: ("benchmark_tags",),
            ProposalType.COMPANY_QUALITY_CHANGE: ("company_quality",),
        }[proposal.proposal_type]
        values = current.model_dump()
        for field_name in allowed_fields:
            values[field_name] = getattr(suggested, field_name)
        values.update(
            version=current.version + 1,
            confirmed_at=occurred_at,
            confirmed_by=actor,
        )
        return TickerProfile.model_validate(values)
