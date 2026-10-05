from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.exc import SQLAlchemyError

from app.classification.models import (
    ClassificationDecisionResult,
    ClassificationEvaluation,
    EvidenceCategory,
    EvidenceDataQuality,
    EvidenceSource,
    PortfolioRole,
    ProposalStatus,
    ReviewMode,
    RiskTier,
    RoleEvidence,
    TickerProfile,
    TickerProfileHistory,
)
from app.classification.repository import ClassificationRepository
from app.classification.reviewer import (
    ClassificationReviewError,
    ClassificationReviewer,
    ProfileNotFoundError,
)
from app.classification.scoring import reason_codes_for_score
from app.classification.service import (
    ClassificationService,
    InvalidDecisionError,
)
from app.universe import AssetClass, TickerGroup

logger = logging.getLogger(__name__)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManualEvidenceInput(ApiModel):
    category: EvidenceCategory
    score: float | None = Field(default=None, ge=0, le=10)
    confidence: float = Field(default=0.8, ge=0, le=1)
    data_quality: EvidenceDataQuality | None = None

    @model_validator(mode="after")
    def normalize_availability(self) -> ManualEvidenceInput:
        quality = self.data_quality
        if self.score is None:
            object.__setattr__(
                self, "data_quality", EvidenceDataQuality.UNAVAILABLE
            )
        elif quality is None:
            object.__setattr__(
                self, "data_quality", EvidenceDataQuality.AVAILABLE
            )
        elif quality is EvidenceDataQuality.UNAVAILABLE:
            raise ValueError(
                "UNAVAILABLE manual evidence cannot contain a score"
            )
        return self


class ManualReviewRequest(ApiModel):
    review_mode: ReviewMode = ReviewMode.MANUAL
    evidence: tuple[ManualEvidenceInput, ...] = ()

    @model_validator(mode="after")
    def validate_unique_categories(self) -> ManualReviewRequest:
        categories = [item.category for item in self.evidence]
        if len(categories) != len(set(categories)):
            raise ValueError("manual evidence categories must be unique")
        return self


class DecisionRequest(ApiModel):
    actor: str = Field(min_length=1)
    reason: str | None = None


class SnoozeRequest(ApiModel):
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    snooze_until: datetime


class ManualProfileEditRequest(ApiModel):
    actor: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    expected_version: int = Field(ge=1)
    primary_role: PortfolioRole | None = None
    groups: tuple[TickerGroup, ...] | None = None
    strategy_tags: tuple[str, ...] | None = None
    risk_tier: RiskTier | None = None
    benchmark_tags: tuple[str, ...] | None = None
    company_quality: float | None = Field(default=None, ge=0, le=2)
    enabled: bool | None = None
    asset_class: AssetClass | None = None
    company_id: str | None = None
    exposure_group: str | None = None
    target_weight: float | None = Field(default=None, ge=0, le=1)
    max_weight: float | None = Field(default=None, ge=0, le=1)


class HistoryResponse(ApiModel):
    history: tuple[TickerProfileHistory, ...]
    audit: tuple[dict, ...]


def _manual_evidence(
    ticker: str,
    request: ManualReviewRequest,
    now: datetime,
) -> tuple[RoleEvidence, ...]:
    return tuple(
        RoleEvidence(
            ticker=ticker,
            category=item.category,
            score=item.score,
            confidence=item.confidence,
            reason_codes=reason_codes_for_score(item.category, item.score),
            source_timestamp=now,
            data_quality=item.data_quality
            or EvidenceDataQuality.UNAVAILABLE,
            source=EvidenceSource.MANUAL_USER_ENTRY,
        )
        for item in request.evidence
    )


def create_classification_router(
    repository: ClassificationRepository | None,
    service: ClassificationService | None,
    snapshot_repository=None,
) -> APIRouter:
    router = APIRouter()

    def require_repository() -> ClassificationRepository:
        if repository is None:
            raise HTTPException(
                status_code=503,
                detail="Classification storage is unavailable",
            )
        return repository

    def require_service() -> ClassificationService:
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Classification service is unavailable",
            )
        return service

    def translate_mutation(call):
        try:
            return call()
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, RuntimeError, InvalidDecisionError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503,
                detail="Classification storage operation failed",
            ) from exc

    @router.get("/classification", response_class=HTMLResponse)
    def classification_page() -> HTMLResponse:
        from app.classification.ui import render_classification_page

        if repository is None:
            return HTMLResponse(
                render_classification_page(
                    profiles=[],
                    proposals=[],
                    history=[],
                    audit=[],
                    snapshots=snapshot_repository,
                    unavailable_message="Classification storage is unavailable. "
                    "The equity dashboard remains operational.",
                )
            )
        try:
            profiles = repository.list_profiles()
            proposals = repository.list_proposals()
            history = [
                item
                for profile in profiles
                for item in repository.list_history(profile.ticker)
            ]
            audit = repository.list_audit_events()
        except SQLAlchemyError as exc:
            logger.warning("Classification page query failed: %s", exc)
            return HTMLResponse(
                render_classification_page(
                    profiles=[],
                    proposals=[],
                    history=[],
                    audit=[],
                    snapshots=snapshot_repository,
                    unavailable_message="Classification data could not be loaded. "
                    "No equity or options data was affected.",
                )
            )
        return HTMLResponse(
            render_classification_page(
                profiles=profiles,
                proposals=proposals,
                history=history,
                audit=audit,
                snapshots=snapshot_repository,
            )
        )

    @router.get("/classification/proposals")
    def list_proposals(
        status: ProposalStatus | None = None,
        ticker: str | None = None,
    ) -> list:
        repo = require_repository()
        try:
            return repo.list_proposals(status=status, ticker=ticker)
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503, detail="Classification storage unavailable"
            ) from exc

    @router.get("/classification/proposals/{proposal_id}")
    def get_proposal(proposal_id: str):
        proposal = require_repository().get_proposal(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Proposal not found")
        return proposal

    @router.post(
        "/classification/review/{ticker}",
        response_model=ClassificationEvaluation,
    )
    def review_ticker(
        ticker: str, request: ManualReviewRequest
    ) -> ClassificationEvaluation:
        classification = require_service()
        now = datetime.now(UTC)
        try:
            return classification.reviewer.review(
                ticker,
                _manual_evidence(ticker.strip().upper(), request, now),
                review_mode=request.review_mode,
                created_at=now,
            )
        except ProfileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ClassificationReviewError, SQLAlchemyError) as exc:
            raise HTTPException(
                status_code=503, detail="Classification review failed"
            ) from exc

    @router.post(
        "/classification/review-all",
        response_model=list[ClassificationEvaluation],
    )
    def review_all() -> list[ClassificationEvaluation]:
        classification = require_service()
        now = datetime.now(UTC)
        results: list[ClassificationEvaluation] = []
        try:
            for profile in require_repository().list_profiles():
                results.append(
                    classification.reviewer.review_stored_evidence(
                        profile.ticker,
                        review_mode=ReviewMode.WEEKLY,
                        created_at=now,
                    )
                )
            return results
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503, detail="Classification review failed"
            ) from exc

    @router.post(
        "/classification/proposals/{proposal_id}/accept",
        response_model=ClassificationDecisionResult,
    )
    def accept_proposal(
        proposal_id: str, request: DecisionRequest
    ) -> ClassificationDecisionResult:
        return translate_mutation(
            lambda: require_service().accept(
                proposal_id, actor=request.actor
            )
        )

    @router.post(
        "/classification/proposals/{proposal_id}/reject",
        response_model=ClassificationDecisionResult,
    )
    def reject_proposal(
        proposal_id: str, request: DecisionRequest
    ) -> ClassificationDecisionResult:
        if request.reason is None:
            raise HTTPException(status_code=422, detail="reason is required")
        return translate_mutation(
            lambda: require_service().reject(
                proposal_id,
                actor=request.actor,
                reason=request.reason or "",
            )
        )

    @router.post(
        "/classification/proposals/{proposal_id}/snooze",
        response_model=ClassificationDecisionResult,
    )
    def snooze_proposal(
        proposal_id: str, request: SnoozeRequest
    ) -> ClassificationDecisionResult:
        return translate_mutation(
            lambda: require_service().snooze(
                proposal_id,
                actor=request.actor,
                reason=request.reason,
                snooze_until=request.snooze_until,
            )
        )

    @router.get("/classification/history/{ticker}")
    def classification_history(ticker: str) -> dict:
        repo = require_repository()
        return {
            "history": repo.list_history(ticker),
            "audit": repo.list_audit_events(ticker),
        }

    @router.get(
        "/classification/evaluations/{ticker}",
        response_model=list[ClassificationEvaluation],
    )
    def classification_evaluations(
        ticker: str,
    ) -> list[ClassificationEvaluation]:
        return require_repository().list_review_cycles(ticker)

    @router.get("/profiles", response_model=list[TickerProfile])
    def list_profiles() -> list[TickerProfile]:
        return require_repository().list_profiles()

    @router.get("/profiles/{ticker}", response_model=TickerProfile)
    def get_profile(ticker: str) -> TickerProfile:
        profile = require_repository().get_profile(ticker)
        if profile is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        return profile

    @router.put(
        "/profiles/{ticker}",
        response_model=ClassificationDecisionResult,
    )
    def update_profile(
        ticker: str, request: ManualProfileEditRequest
    ) -> ClassificationDecisionResult:
        excluded = {"actor", "reason", "expected_version"}
        changes = {
            key: value
            for key, value in request.model_dump(exclude=excluded).items()
            if key in request.model_fields_set
        }
        return translate_mutation(
            lambda: require_service().manual_edit(
                ticker,
                changes,
                expected_version=request.expected_version,
                actor=request.actor,
                reason=request.reason,
            )
        )

    return router
