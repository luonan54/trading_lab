from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.exc import SQLAlchemyError

from app.config import AppConfig
from app.starter.models import (
    PostEventAssessment,
    PostEventAssessmentInput,
    StarterOutcomeObservation,
    StarterPolicyEvaluation,
)
from app.starter.repository import (
    StarterConflictError,
    StarterNotFoundError,
    StarterRepository,
)
from app.starter.service import StarterService, StarterServiceUnavailable
from app.starter.ui import render_starter_page


@dataclass
class StarterContext:
    config: AppConfig
    repository: StarterRepository | None
    service: StarterService | None
    initialization_error: str | None = None


def _context(request: Request) -> StarterContext:
    return request.app.state.starter_context


def _repository(context: StarterContext) -> StarterRepository:
    if context.repository is None:
        raise HTTPException(
            status_code=503,
            detail="Starter persistence is unavailable",
        )
    return context.repository


def _service(context: StarterContext) -> StarterService:
    if context.service is None:
        raise HTTPException(
            status_code=503,
            detail="Starter evaluation is unavailable",
        )
    return context.service


def create_starter_router() -> APIRouter:
    router = APIRouter(tags=["starter"])

    @router.get("/starter", response_class=HTMLResponse)
    def starter_page(request: Request, ticker: str = "") -> HTMLResponse:
        context = _context(request)
        assessments: list[PostEventAssessment] = []
        evaluations: list[StarterPolicyEvaluation] = []
        observations: list[StarterOutcomeObservation] = []
        error = context.initialization_error
        if context.repository is not None:
            try:
                assessments = context.repository.list_assessments(ticker)
                evaluations = context.repository.list_evaluations(ticker)
                observations = context.repository.list_observations()
            except SQLAlchemyError:
                error = "Starter history is temporarily unavailable."
        return HTMLResponse(
            render_starter_page(
                config=context.config.starter,
                selected_ticker=ticker,
                assessments=assessments,
                evaluations=evaluations,
                observations=observations,
                error=error,
            )
        )

    @router.get("/starter/config")
    def starter_config(request: Request) -> dict:
        return _context(request).config.starter.model_dump(mode="json")

    @router.get(
        "/starter/events/{ticker}",
        response_model=list[PostEventAssessment],
    )
    def list_events(
        ticker: str, request: Request
    ) -> list[PostEventAssessment]:
        try:
            return _repository(_context(request)).list_assessments(ticker)
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503,
                detail="Starter event history is unavailable",
            ) from exc

    @router.post(
        "/starter/events/{ticker}",
        response_model=PostEventAssessment,
        status_code=201,
    )
    def create_event(
        ticker: str,
        body: PostEventAssessmentInput,
        request: Request,
        supersedes: UUID | None = Query(default=None),
    ) -> PostEventAssessment:
        if ticker.strip().upper() != body.ticker:
            raise HTTPException(
                status_code=400,
                detail="path ticker must match assessment ticker",
            )
        try:
            return _service(_context(request)).create_assessment(
                body, supersedes=supersedes
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except StarterNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StarterConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503,
                detail="Starter event persistence is unavailable",
            ) from exc

    @router.post(
        "/starter/evaluate/{ticker}",
        response_model=StarterPolicyEvaluation,
    )
    def evaluate(ticker: str, request: Request) -> StarterPolicyEvaluation:
        try:
            return _service(_context(request)).evaluate(ticker)
        except StarterNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except StarterConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except StarterServiceUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503,
                detail="Starter evaluation persistence is unavailable",
            ) from exc

    @router.get(
        "/starter/evaluations",
        response_model=list[StarterPolicyEvaluation],
    )
    def list_evaluations(
        request: Request, ticker: str | None = None
    ) -> list[StarterPolicyEvaluation]:
        try:
            return _repository(_context(request)).list_evaluations(ticker)
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503,
                detail="Starter evaluation history is unavailable",
            ) from exc

    @router.get(
        "/starter/evaluations/{ticker}",
        response_model=list[StarterPolicyEvaluation],
    )
    def ticker_evaluations(
        ticker: str, request: Request
    ) -> list[StarterPolicyEvaluation]:
        try:
            return _repository(_context(request)).list_evaluations(ticker)
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503,
                detail="Starter evaluation history is unavailable",
            ) from exc

    @router.get(
        "/starter/outcomes",
        response_model=list[StarterOutcomeObservation],
    )
    def list_outcomes(
        request: Request,
    ) -> list[StarterOutcomeObservation]:
        try:
            return _repository(_context(request)).list_observations()
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503,
                detail="Starter outcomes are unavailable",
            ) from exc

    @router.get(
        "/starter/outcomes/{evaluation_id}",
        response_model=list[StarterOutcomeObservation],
    )
    def evaluation_outcomes(
        evaluation_id: UUID, request: Request
    ) -> list[StarterOutcomeObservation]:
        repository = _repository(_context(request))
        try:
            if repository.get_evaluation(evaluation_id) is None:
                raise HTTPException(
                    status_code=404,
                    detail="Starter evaluation not found",
                )
            return repository.list_observations(evaluation_id)
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503,
                detail="Starter outcomes are unavailable",
            ) from exc

    return router
