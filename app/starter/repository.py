from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Float,
    JSON,
    String,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.starter.models import (
    PostEventAssessment,
    StarterOutcomeObservation,
    StarterPolicyEvaluation,
    StarterPolicyInput,
)


class StarterRepositoryError(RuntimeError):
    pass


class StarterConflictError(StarterRepositoryError):
    pass


class StarterNotFoundError(StarterRepositoryError):
    pass


class StarterBase(DeclarativeBase):
    pass


class StarterEventAssessmentRecord(StarterBase):
    __tablename__ = "starter_event_assessments"

    assessment_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    supersedes_id: Mapped[str | None] = mapped_column(
        String(36), unique=True, index=True
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class StarterEvaluationRecord(StarterBase):
    __tablename__ = "anticipatory_starter_evaluations"

    evaluation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(48), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    assessment_id: Mapped[str | None] = mapped_column(String(36), index=True)
    profile_version: Mapped[int] = mapped_column(index=True)
    options_scan_id: Mapped[str | None] = mapped_column(String(36), index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class StarterOutcomeObservationRecord(StarterBase):
    __tablename__ = "starter_outcome_observations"
    __table_args__ = (
        UniqueConstraint(
            "baseline_for_evaluation",
            name="uq_starter_baseline_for_evaluation",
        ),
    )

    observation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(String(36), index=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    elapsed_days: Mapped[float] = mapped_column(Float, index=True)
    baseline_for_evaluation: Mapped[str | None] = mapped_column(
        String(36), nullable=True
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class StarterRepository:
    """Append-only persistence isolated from equity and options metadata."""

    def __init__(self, database_url: str) -> None:
        if database_url.startswith("sqlite:///") and ":memory:" not in database_url:
            path = Path(database_url.removeprefix("sqlite:///"))
            path.parent.mkdir(parents=True, exist_ok=True)
        connect_args = (
            {"check_same_thread": False}
            if database_url.startswith("sqlite")
            else {}
        )
        self.engine = create_engine(database_url, connect_args=connect_args)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        StarterBase.metadata.create_all(self.engine)

    def save_assessment(self, assessment: PostEventAssessment) -> None:
        with self.sessions() as session:
            if assessment.supersedes is not None:
                prior = session.get(
                    StarterEventAssessmentRecord, str(assessment.supersedes)
                )
                if prior is None:
                    raise StarterNotFoundError(
                        f"superseded assessment not found: {assessment.supersedes}"
                    )
                prior_model = PostEventAssessment.model_validate(prior.payload)
                if (
                    prior_model.ticker != assessment.ticker
                    or prior_model.event_id != assessment.event_id
                ):
                    raise StarterConflictError(
                        "correction must retain ticker and event identity"
                    )
            session.add(
                StarterEventAssessmentRecord(
                    assessment_id=str(assessment.assessment_id),
                    event_id=str(assessment.event_id),
                    ticker=assessment.ticker,
                    event_type=assessment.event_type.value,
                    event_at=assessment.event_at.astimezone(UTC),
                    entered_at=assessment.entered_at.astimezone(UTC),
                    expires_at=assessment.expires_at.astimezone(UTC),
                    supersedes_id=(
                        str(assessment.supersedes)
                        if assessment.supersedes is not None
                        else None
                    ),
                    payload=assessment.model_dump(mode="json"),
                )
            )
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise StarterConflictError(
                    "assessment is duplicate or already superseded"
                ) from exc

    def get_assessment(
        self, assessment_id: UUID | str
    ) -> PostEventAssessment | None:
        with self.sessions() as session:
            record = session.get(
                StarterEventAssessmentRecord, str(assessment_id)
            )
            return (
                PostEventAssessment.model_validate(record.payload)
                if record is not None
                else None
            )

    def list_assessments(
        self, ticker: str | None = None
    ) -> list[PostEventAssessment]:
        statement = select(StarterEventAssessmentRecord).order_by(
            StarterEventAssessmentRecord.entered_at.desc(),
            StarterEventAssessmentRecord.assessment_id.desc(),
        )
        if ticker is not None:
            statement = statement.where(
                StarterEventAssessmentRecord.ticker == ticker.strip().upper()
            )
        with self.sessions() as session:
            records = session.scalars(statement).all()
            return [
                PostEventAssessment.model_validate(record.payload)
                for record in records
            ]

    def latest_active_assessment(
        self, ticker: str, *, at: datetime
    ) -> PostEventAssessment | None:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError("at must be timezone-aware")
        for assessment in self.list_assessments(ticker):
            if assessment.is_current(at):
                return assessment
        return None

    @staticmethod
    def _evaluation_payload(
        evaluation: StarterPolicyEvaluation,
        frozen_input: StarterPolicyInput | None,
    ) -> dict:
        return {
            "evaluation": evaluation.model_dump(mode="json"),
            "frozen_input": (
                frozen_input.model_dump(mode="json")
                if frozen_input is not None
                else None
            ),
        }

    @staticmethod
    def _evaluation(
        record: StarterEvaluationRecord | None,
    ) -> StarterPolicyEvaluation | None:
        if record is None:
            return None
        payload = record.payload.get("evaluation", record.payload)
        return StarterPolicyEvaluation.model_validate(payload)

    @staticmethod
    def _observation(
        record: StarterOutcomeObservationRecord,
    ) -> StarterOutcomeObservation:
        return StarterOutcomeObservation.model_validate(record.payload)

    @staticmethod
    def _add_evaluation(
        session,
        evaluation: StarterPolicyEvaluation,
        frozen_input: StarterPolicyInput | None,
    ) -> None:
        session.add(
            StarterEvaluationRecord(
                evaluation_id=str(evaluation.evaluation_id),
                ticker=evaluation.ticker,
                status=evaluation.status.value,
                created_at=evaluation.created_at.astimezone(UTC),
                assessment_id=(
                    str(evaluation.event_assessment_id)
                    if evaluation.event_assessment_id is not None
                    else None
                ),
                profile_version=evaluation.profile_version,
                options_scan_id=(
                    str(evaluation.options_scan_id)
                    if evaluation.options_scan_id is not None
                    else None
                ),
                payload=StarterRepository._evaluation_payload(
                    evaluation, frozen_input
                ),
            )
        )

    @staticmethod
    def _add_observation(
        session, observation: StarterOutcomeObservation
    ) -> None:
        session.add(
            StarterOutcomeObservationRecord(
                observation_id=str(observation.observation_id),
                evaluation_id=str(observation.evaluation_id),
                observed_at=observation.observed_at.astimezone(UTC),
                elapsed_days=observation.elapsed_days,
                baseline_for_evaluation=(
                    str(observation.evaluation_id)
                    if observation.baseline
                    else None
                ),
                payload=observation.model_dump(mode="json"),
            )
        )

    def save_evaluation(
        self,
        evaluation: StarterPolicyEvaluation,
        *,
        frozen_input: StarterPolicyInput | None = None,
    ) -> None:
        with self.sessions.begin() as session:
            self._add_evaluation(session, evaluation, frozen_input)

    def save_evaluation_with_baseline(
        self,
        evaluation: StarterPolicyEvaluation,
        baseline: StarterOutcomeObservation,
        *,
        frozen_input: StarterPolicyInput,
    ) -> None:
        if baseline.evaluation_id != evaluation.evaluation_id:
            raise StarterConflictError(
                "baseline must reference the evaluation being saved"
            )
        if not baseline.baseline:
            raise StarterConflictError("baseline observation must be marked baseline")
        with self.sessions.begin() as session:
            self._add_evaluation(session, evaluation, frozen_input)
            self._add_observation(session, baseline)

    def get_evaluation(
        self, evaluation_id: UUID | str
    ) -> StarterPolicyEvaluation | None:
        with self.sessions() as session:
            return self._evaluation(
                session.get(StarterEvaluationRecord, str(evaluation_id))
            )

    def get_frozen_input(
        self, evaluation_id: UUID | str
    ) -> StarterPolicyInput | None:
        with self.sessions() as session:
            record = session.get(StarterEvaluationRecord, str(evaluation_id))
            if record is None:
                return None
            payload = record.payload.get("frozen_input")
            return (
                StarterPolicyInput.model_validate(payload)
                if payload is not None
                else None
            )

    def list_evaluations(
        self, ticker: str | None = None
    ) -> list[StarterPolicyEvaluation]:
        statement = select(StarterEvaluationRecord).order_by(
            StarterEvaluationRecord.created_at.desc(),
            StarterEvaluationRecord.evaluation_id.desc(),
        )
        if ticker is not None:
            statement = statement.where(
                StarterEvaluationRecord.ticker == ticker.strip().upper()
            )
        with self.sessions() as session:
            return [
                evaluation
                for record in session.scalars(statement).all()
                if (evaluation := self._evaluation(record)) is not None
            ]

    def latest_evaluation(
        self, ticker: str
    ) -> StarterPolicyEvaluation | None:
        evaluations = self.list_evaluations(ticker)
        return evaluations[0] if evaluations else None

    def append_observation(
        self, observation: StarterOutcomeObservation
    ) -> None:
        with self.sessions() as session:
            evaluation = session.get(
                StarterEvaluationRecord, str(observation.evaluation_id)
            )
            if evaluation is None:
                raise StarterNotFoundError(
                    f"evaluation not found: {observation.evaluation_id}"
                )
            if observation.observed_at < evaluation.created_at.replace(
                tzinfo=UTC
            ):
                raise StarterConflictError(
                    "observation cannot predate the evaluation"
                )
            self._add_observation(session, observation)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise StarterConflictError(
                    "baseline observation already exists"
                ) from exc

    def list_observations(
        self, evaluation_id: UUID | str | None = None
    ) -> list[StarterOutcomeObservation]:
        statement = select(StarterOutcomeObservationRecord).order_by(
            StarterOutcomeObservationRecord.observed_at,
            StarterOutcomeObservationRecord.observation_id,
        )
        if evaluation_id is not None:
            statement = statement.where(
                StarterOutcomeObservationRecord.evaluation_id
                == str(evaluation_id)
            )
        with self.sessions() as session:
            return [
                self._observation(record)
                for record in session.scalars(statement).all()
            ]
