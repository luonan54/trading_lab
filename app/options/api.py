from __future__ import annotations

from dataclasses import dataclass
import logging
from uuid import UUID

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.exc import SQLAlchemyError

from app.config import AppConfig
from app.options.models import OptionsScanResult, OptionsScanStatus, ScoredOptionCandidate
from app.options.repository import OptionsScanRepository
from app.options.service import (
    EquitySnapshotRepository,
    OptionsScanService,
    QualifiedScanError,
)
from app.runtime_universe import RuntimeUniverseResolver

logger = logging.getLogger(__name__)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScanRequest(ApiModel):
    """Explicit request body for a single-ticker scan.

    ``manual_override`` defaults to ``False`` so an empty POST body performs
    a normal (non-override) scan; callers opt in to bypassing equity
    eligibility explicitly.
    """

    manual_override: bool = False


@dataclass
class OptionsContext:
    """Request-time lookup object stored on ``app.state.options_context``.

    Reading dependencies from this object inside each route handler (rather
    than capturing them as closures at router-construction time) lets tests
    override ``options_service``/``options_repository`` with synthetic
    fakes after ``create_app()`` has already run, guaranteeing no live
    provider or credential access during tests.
    """

    config: AppConfig
    equity_repository: EquitySnapshotRepository | None
    options_repository: OptionsScanRepository | None
    options_service: OptionsScanService | None
    universe_resolver: RuntimeUniverseResolver | None = None


def _context(request: Request) -> OptionsContext:
    context = getattr(request.app.state, "options_context", None)
    if context is None:
        raise HTTPException(
            status_code=503, detail="Options subsystem is unavailable"
        )
    return context


def _normalize_ticker(ticker: str, config: AppConfig) -> str:
    normalized = ticker.strip().upper()
    if normalized not in config.symbols:
        raise HTTPException(
            status_code=400, detail=f"Unknown configured ticker: {normalized}"
        )
    return normalized


def _require_repository(context: OptionsContext) -> OptionsScanRepository:
    if context.options_repository is None:
        raise HTTPException(
            status_code=503, detail="Options storage is unavailable"
        )
    return context.options_repository


def _require_service(context: OptionsContext) -> OptionsScanService:
    if context.options_service is None:
        raise HTTPException(
            status_code=503, detail="Options scan service is unavailable"
        )
    return context.options_service


def create_options_router() -> APIRouter:
    router = APIRouter()

    @router.get("/options/latest", response_model=list[OptionsScanResult])
    def latest_scans(request: Request) -> list[OptionsScanResult]:
        repository = _require_repository(_context(request))
        try:
            return repository.latest_all()
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503, detail="Options storage operation failed"
            ) from exc

    @router.get("/options/scans/{scan_id}", response_model=OptionsScanResult)
    def get_scan(scan_id: UUID, request: Request) -> OptionsScanResult:
        repository = _require_repository(_context(request))
        try:
            result = repository.get_scan(scan_id)
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503, detail="Options storage operation failed"
            ) from exc
        if result is None:
            raise HTTPException(
                status_code=404, detail=f"No scan found for id {scan_id}"
            )
        return result

    @router.get(
        "/options/{ticker}/candidates",
        response_model=list[ScoredOptionCandidate],
    )
    def get_candidates(
        ticker: str, request: Request
    ) -> list[ScoredOptionCandidate]:
        context = _context(request)
        normalized = _normalize_ticker(ticker, context.config)
        repository = _require_repository(context)
        try:
            result = repository.latest(normalized)
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503, detail="Options storage operation failed"
            ) from exc
        if result is None:
            raise HTTPException(
                status_code=404, detail=f"No scan result for {normalized}"
            )
        return list(result.accepted_candidates)

    @router.get("/options/{ticker}", response_model=OptionsScanResult)
    def get_latest(ticker: str, request: Request) -> OptionsScanResult:
        context = _context(request)
        normalized = _normalize_ticker(ticker, context.config)
        repository = _require_repository(context)
        try:
            result = repository.latest(normalized)
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503, detail="Options storage operation failed"
            ) from exc
        if result is None:
            raise HTTPException(
                status_code=404, detail=f"No scan result for {normalized}"
            )
        return result

    @router.post(
        "/options/scan/qualified", response_model=list[OptionsScanResult]
    )
    def scan_qualified(
        request: Request,
    ) -> list[OptionsScanResult] | JSONResponse:
        service = _require_service(_context(request))
        try:
            return service.scan_qualified()
        except QualifiedScanError as exc:
            return JSONResponse(
                status_code=503,
                content={
                    "detail": str(exc),
                    "failed_tickers": [
                        {"ticker": ticker, "error_type": error_type}
                        for ticker, error_type in exc.failures
                    ],
                    "results": jsonable_encoder(exc.partial_results),
                },
            )
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503, detail="Options scan operation failed"
            ) from exc

    @router.post("/options/scan/{ticker}", response_model=OptionsScanResult)
    def scan_ticker(
        ticker: str,
        request: Request,
        body: ScanRequest = Body(default_factory=ScanRequest),
    ) -> OptionsScanResult | JSONResponse:
        context = _context(request)
        normalized = _normalize_ticker(ticker, context.config)
        service = _require_service(context)
        if context.equity_repository is None:
            raise HTTPException(
                status_code=503,
                detail="Equity snapshot storage is unavailable",
            )
        try:
            snapshot = context.equity_repository.latest(normalized)
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503,
                detail="Equity snapshot storage operation failed",
            ) from exc
        if snapshot is None:
            raise HTTPException(
                status_code=409,
                detail=f"No equity scan snapshot is available for {normalized}",
            )
        try:
            result = service.scan(
                normalized, manual_override=body.manual_override
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except SQLAlchemyError as exc:
            raise HTTPException(
                status_code=503, detail="Options scan operation failed"
            ) from exc
        if result.status is OptionsScanStatus.OPTIONS_DATA_UNAVAILABLE:
            # The scan is still persisted with an honest result; report the
            # provider outage via HTTP status while returning that same
            # body rather than substituting a generic error payload.
            return JSONResponse(
                status_code=503, content=jsonable_encoder(result)
            )
        return result

    @router.get("/options", response_class=HTMLResponse)
    def options_page(
        request: Request, ticker: str | None = None
    ) -> HTMLResponse:
        from app.options.ui import render_options_page

        context = getattr(request.app.state, "options_context", None)
        if context is None:
            return HTMLResponse(
                render_options_page(
                    config=getattr(request.app.state, "config", None),
                    eligible_tickers=[],
                    latest_results=[],
                    selected_ticker=ticker,
                    unavailable_message=(
                        "Options storage is unavailable. The equity "
                        "dashboard remains operational."
                    ),
                )
            )
        universe = (
            context.universe_resolver.resolve()
            if context.universe_resolver is not None
            else None
        )
        runtime_symbols = (
            universe.symbols if universe is not None else context.config.symbols
        )
        eligible_tickers = sorted(
            symbol_ticker
            for symbol_ticker, symbol in runtime_symbols.items()
            if symbol.scan_eligible and symbol.allows_call_candidate
        )
        latest_results: list[OptionsScanResult] = []
        selected_history: list[OptionsScanResult] = []
        unavailable_message: str | None = None
        if context.options_repository is None:
            unavailable_message = (
                "Options storage is unavailable. The equity dashboard "
                "remains operational."
            )
        else:
            try:
                latest_results = context.options_repository.latest_all()
                normalized_selection = ticker.strip().upper() if ticker else None
                selected_history = (
                    context.options_repository.history(
                        normalized_selection, limit=20
                    )
                    if normalized_selection in eligible_tickers
                    else []
                )
            except SQLAlchemyError as exc:
                logger.warning("Options page query failed: %s", exc)
                unavailable_message = (
                    "Options data could not be loaded. No equity or "
                    "classification data was affected."
                )

        equity_snapshots = []
        equity_unavailable_message: str | None = None
        if context.equity_repository is None:
            equity_unavailable_message = (
                "Equity snapshot storage is unavailable, so current "
                "qualification cannot be evaluated."
            )
        else:
            try:
                equity_snapshots = context.equity_repository.latest_all()
            except SQLAlchemyError as exc:
                logger.warning("Options page equity query failed: %s", exc)
                equity_unavailable_message = (
                    "Equity snapshots could not be loaded, so current "
                    "qualification cannot be evaluated."
                )
        return HTMLResponse(
            render_options_page(
                config=context.config,
                runtime_symbols=runtime_symbols,
                eligible_tickers=eligible_tickers,
                latest_results=latest_results,
                equity_snapshots=equity_snapshots,
                selected_history=selected_history,
                selected_ticker=ticker,
                unavailable_message=unavailable_message,
                equity_unavailable_message=equity_unavailable_message,
            )
        )

    return router
