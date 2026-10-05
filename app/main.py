from __future__ import annotations

import logging
from html import escape
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.exc import SQLAlchemyError

from app.action_guidance import (
    NextStepGuidance,
    StrategyContext,
    derive_next_step,
)
from app.call_readiness import evaluate_call_readiness
from app.alpaca import MarketDataError
from app.config import (
    AppConfig,
    TickerGroup,
    UniverseSelectionError,
    load_config,
)
from app.db import SnapshotRepository
from app.entry import current_entry
from app.entry_ui import (
    entry_conclusion, entry_markup, readiness_lights,
    readiness_light_script, readiness_light_styles,
)
from app.features import create_features_router
from app.models import HealthResponse, ScanSnapshot
from app.move_guidance import (
    MOVE_LANE_LABELS,
    MOVE_LANE_PRIORITY,
    MoveGuidance,
    MoveLane,
    derive_move_guidance,
)
from app.options.api import OptionsContext, create_options_router
from app.options.repository import OptionsScanRepository
from app.options.service import OptionsScanService
from app.runtime_universe import (
    ConfirmedProfileUniverseResolver,
    RuntimeSymbol,
    RuntimeUniverse,
    RuntimeUniverseSource,
    StaticRuntimeUniverseResolver,
)
from app.service import ACTION_ORDER, ScanService, refresh_snapshot, sort_snapshots
from app.ui import (
    MARKET_HEADERS,
    PRODUCT_NAME,
    glossary_script,
    glossary_styles,
    render_glossary,
    render_market_cells,
    render_market_price,
    render_primary_nav,
    render_ticker_copy,
    shared_page_styles,
)

logger = logging.getLogger(__name__)

STATE_STYLE = {
    "CALL_CANDIDATE": "incoming",
    "RIGHT_SIDE_REPAIR": "incoming",
    "SELLING_EXHAUSTION": "split",
    "DIP_WATCH": "covered",
    "BREAKDOWN": "leaving",
    "NORMAL": "unassigned",
}

ACTION_STYLE = {
    "ADD": "staying",
    "HOLD": "incoming",
    "PAUSE_ADD": "split",
    "THESIS_REVIEW": "covered",
    "UNSET": "unassigned",
}

TECH_CONTEXT = {
    "NORMAL": "Normal",
    "DIP_WATCH": "Pullback",
    "SELLING_EXHAUSTION": "Stabilizing",
    "RIGHT_SIDE_REPAIR": "Repairing",
    "CALL_CANDIDATE": "Trend Confirmed (entry separate)",
    "BREAKDOWN": "Breakdown",
}


def _pill(value: str, style: str) -> str:
    return f"<span class='pill pill-{style}'>{escape(value)}</span>"


def _state_pill(snapshot: ScanSnapshot) -> str:
    value = snapshot.current_state.value
    label = "TREND CONFIRMED" if value == "CALL_CANDIDATE" else value
    return _pill(label, STATE_STYLE[value])


def _code_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _code_label(value: Any) -> str:
    code = _code_value(value)
    label = code.replace("_", " ").title()
    return f"{escape(label)} <code>{escape(code)}</code>"


def _code_list(values: list[Any], empty_text: str = "None") -> str:
    if not values:
        return f"<span class='muted'>{escape(empty_text)}</span>"
    items = "".join(f"<li>{_code_label(value)}</li>" for value in values)
    return f"<ul class='explain-list'>{items}</ul>"


def _condition_markup(condition: Any) -> str:
    if condition is None:
        return "<span class='muted'>None / not applicable</span>"
    if condition.level is None:
        level = "<span class='muted'>No reliable numeric level</span>"
    else:
        source = escape(_code_value(condition.source))
        level = f"<strong>${condition.level:,.2f}</strong> <code>{source}</code>"
    return (
        f"<div>{_code_label(condition.type)}</div>"
        f"<div>{escape(condition.description)}</div><div>{level}</div>"
    )


def _next_trigger_markup(snapshot: ScanSnapshot) -> str:
    if snapshot.call_readiness is not None and snapshot.current_state.value != "BREAKDOWN":
        trigger = snapshot.call_readiness.next_trigger
    elif snapshot.explanation is not None:
        trigger = snapshot.explanation.next_trigger
    else:
        return "<span class='legacy-note'>Run a new scan for explanation</span>"
    label = escape(_code_value(trigger.type).replace("_", " ").title())
    level = (
        f"<span class='trigger-level'>${trigger.level:,.2f}</span>"
        if trigger.level is not None
        else "<span class='muted'>No reliable level</span>"
    )
    return (
        f"<strong>{label}</strong><small>{escape(trigger.description)}</small>{level}"
    )


def _next_step_markup(guidance: NextStepGuidance, *, compact: bool = False) -> str:
    tone = escape(guidance.tone.value)
    headline = escape(guidance.headline)
    detail = escape(guidance.detail)
    code = escape(guidance.code.value)
    if compact:
        return (
            f"<div class='next-step next-step-{tone} next-step-compact' "
            f"data-next-step-code='{code}'><strong>{headline}</strong></div>"
        )
    return (
        f"<div class='next-step next-step-{tone}' title='{detail}' "
        f"data-next-step-code='{code}'>"
        f"<span class='next-step-tone'>{tone.title()}</span>"
        f"<strong>{headline}</strong>"
        f"<small>{detail}</small>"
        "</div>"
    )


def _move_markup(guidance: MoveGuidance) -> str:
    lane = escape(guidance.lane.value)
    label = escape(guidance.label)
    headline = escape(guidance.headline)
    detail = escape(guidance.detail)
    source = escape(guidance.source_next_step_code.value)
    return (
        f"<div class='move move-{lane.lower().replace('_', '-')}' "
        f"title='{detail}' data-move-lane='{lane}' "
        f"data-source-next-step-code='{source}'>"
        f"<span class='move-lane'>{label}</span>"
        f"<strong>{headline}</strong><small>{detail}</small></div>"
    )


def _readiness_markup(
    snapshot: ScanSnapshot, *, allow_call_candidate: bool, detailed: bool = False
) -> str:
    readiness = evaluate_call_readiness(
        snapshot,
        allow_call_candidate=allow_call_candidate,
    )
    code = readiness.call_readiness.value
    if not detailed:
        plan = current_entry(snapshot.entry_plan)
        label, style = entry_conclusion(
            plan, qualified=readiness.qualified, allowed=allow_call_candidate,
        )
        return (
            f"<span class='readiness-badge readiness-{style}' "
            f"data-call-readiness='{escape(code)}' "
            f"data-entry-status='{plan.status.value}'>{escape(label)}</span>"
        )
    items = "".join(
        "<li class='{status}'><span>{mark}</span><strong>{label}</strong>"
        "<small>{evidence}</small></li>".format(
            status="pass" if item.passed else "fail",
            mark="✓" if item.passed else "○",
            label=escape(item.label),
            evidence=escape(item.evidence),
        )
        for item in readiness.requirements
    )
    label = escape(code.replace("_", " "))
    return (
        f"<div class='readiness' data-call-readiness='{escape(code)}'>"
        f"<span class='readiness-badge readiness-{escape(code.lower())}'>{label}</span>"
        f"<ul>{items}</ul>{entry_markup(snapshot.entry_plan)}</div>"
    )


def _explanation_details(
    snapshot: ScanSnapshot, *, allow_call_candidate: bool,
    guidance: NextStepGuidance, move: MoveGuidance,
) -> str:
    explanation = snapshot.explanation
    if explanation is None:
        state_details = (
            "<dt>Why This State</dt><dd class='legacy-note'>Run a new scan for "
            "explanation. Legacy snapshot data is preserved without fabrication.</dd>"
        )
    else:
        invalidation = (
            _condition_markup(explanation.invalidation)
            if explanation.invalidation is not None
            else "<span class='muted'>None / not applicable for NORMAL</span>"
        )
        state_details = (
            f"<dt>Why This State</dt><dd>{_code_list(explanation.reasons)}</dd>"
            f"<dt>Missing at Scan</dt><dd>{_code_list(explanation.missing_conditions)}</dd>"
            f"<dt>Next Trigger at Scan</dt><dd>{_condition_markup(explanation.next_trigger)}</dd>"
            f"<dt>Invalidation</dt><dd>{invalidation}</dd>"
            "<dt>Confidence Notes</dt><dd>"
            f"{_code_list(explanation.confidence_notes, 'No additional deterministic confidence notes')}"
            "</dd>"
        )
    transition = ""
    if snapshot.state_changed:
        transition = (
            "<dt>Transition Reasons</dt><dd>"
            f"{_code_list(snapshot.transition_reasons, 'Unavailable for legacy transition')}"
            "</dd>"
        )
    return (
        "<details class='explanation'><summary "
        f"title='Details for {escape(snapshot.ticker)}'>Explanation</summary><dl>"
        f"<dt>Next Step</dt><dd>{_next_step_markup(guidance)}</dd>"
        f"<dt>Move</dt><dd>{_move_markup(move)}</dd>"
        "<dt>Current Entry / Call Readiness</dt><dd>"
        f"{_readiness_markup(snapshot, allow_call_candidate=allow_call_candidate, detailed=True)}</dd>"
        f"<dt>Current Next Trigger</dt><dd class='next-trigger'>{_next_trigger_markup(snapshot)}</dd>"
        f"<dt>Tech Setup Score</dt><dd>{snapshot.ceg_tech_score:.1f} / 10</dd>"
        f"<dt>Tech Context</dt><dd>{escape(TECH_CONTEXT[snapshot.current_state.value])}</dd>"
        f"{state_details}"
        "<dt>Market Levels</dt><dd>"
        f"<div>Local Support: {render_market_price(snapshot.features.local_support)}</div>"
        f"<div>Local Resistance: {render_market_price(snapshot.features.local_resistance)}</div>"
        f"<div>Major Swing Support: {render_market_price(snapshot.features.major_swing_support or snapshot.features.support)}</div>"
        f"<div>Major Swing Resistance: {render_market_price(snapshot.features.major_swing_resistance or snapshot.features.resistance)}</div>"
        "</dd>"
        f"{transition}<dt>Scanned (audit)</dt>"
        f"<dd>{escape(snapshot.displayed_at_et)}</dd></dl></details>"
    )


def _dashboard_row(
    snapshot: ScanSnapshot,
    config: AppConfig,
    *,
    runtime_symbol: RuntimeSymbol,
    strategy_context: StrategyContext,
    guidance: NextStepGuidance,
    move: MoveGuidance,
    original_order: int,
    pending_classification: bool = False,
) -> str:
    long_term_view = strategy_context in {
        StrategyContext.LONG_TERM,
        StrategyContext.HIGH_RISK_GROWTH,
    }
    state = snapshot.current_state.value
    pending = (
        " <a class='classification-pending' href='/classification' "
        "title='Pending classification review' aria-label='Pending classification review'>●</a>"
        if pending_classification
        else ""
    )
    action = (
        runtime_symbol.long_term_action.value
        if runtime_symbol.long_term_action
        else "UNSET"
    )
    row_attributes = " ".join(
        (
            "data-dashboard-row='true'",
            f"data-ticker='{escape(snapshot.ticker)}'",
            f"data-state='{escape(state)}'",
            f"data-state-rank='{ACTION_ORDER[snapshot.current_state]}'",
            f"data-tech-score='{snapshot.ceg_tech_score:.6f}'",
            f"data-next-step-code='{escape(guidance.code.value)}'",
            f"data-move-lane='{escape(move.lane.value)}'",
            f"data-move-rank='{MOVE_LANE_PRIORITY[move.lane]}'",
            f"data-long-term-action='{escape(action)}'",
            f"data-original-order='{original_order}'",
        )
    )
    base = (
        f"<tr class='row-{STATE_STYLE[state]}' {row_attributes}>"
        f"<td>{render_ticker_copy(snapshot.ticker, css_class='ticker')}{pending}</td>"
        f"{render_market_cells(snapshot.features)}"
    )
    next_step = _next_step_markup(guidance, compact=True)
    readiness = _readiness_markup(
        snapshot,
        allow_call_candidate=runtime_symbol.allows_call_candidate,
    )
    common_tail = (
        f"<td>{readiness_lights(evaluate_call_readiness(snapshot, allow_call_candidate=runtime_symbol.allows_call_candidate))}</td>"
        f"<td>{next_step}</td>"
        f"<td>{_explanation_details(snapshot, allow_call_candidate=runtime_symbol.allows_call_candidate, guidance=guidance, move=move)}</td>"
        "</tr>"
    )
    if not long_term_view:
        return (
            base
            + f"<td>{_state_pill(snapshot)}</td>"
            + f"<td>{readiness}</td>"
            + common_tail
        )

    long_term_groups = {
        TickerGroup.LONG_TERM_CORE,
        TickerGroup.LONG_TERM_GROWTH,
        TickerGroup.HIGH_RISK_GROWTH,
    }
    groups = " ".join(
        _pill(group.value, "unassigned")
        for group in sorted(runtime_symbol.groups, key=lambda item: item.value)
        if group in long_term_groups
    )
    return (
        base
        + f"<td>{groups}</td>"
        + f"<td>{_pill(action, ACTION_STYLE[action])}</td>"
        + f"<td>{_state_pill(snapshot)}</td>"
        + f"<td>{readiness}</td>"
        + common_tail
    )


def _symbol_payload(
    ticker: str,
    config: AppConfig,
    item: RuntimeSymbol,
    source: RuntimeUniverseSource,
) -> dict:
    if not item.enabled and item.asset_class.value != "equity":
        scan_status = (
            f"disabled; {item.asset_class.value} is unsupported by the equity scanner"
        )
    elif not item.enabled:
        scan_status = "disabled"
    elif item.benchmark:
        scan_status = "benchmark-only"
    elif item.scan_eligible:
        scan_status = "enabled"
    else:
        scan_status = f"unsupported asset class: {item.asset_class.value}"
    return {
        "ticker": ticker,
        "enabled": item.enabled,
        "groups": sorted(group.value for group in item.groups),
        "tier": item.tier,
        "company_quality": item.company_quality,
        "strategy_tags": sorted(item.strategy_tags),
        "benchmark_tags": list(item.benchmark_tags),
        "benchmark": item.benchmark,
        "asset_class": item.asset_class.value,
        "long_term_action": (
            item.long_term_action.value if item.long_term_action else None
        ),
        "scan_eligible": item.scan_eligible,
        "scan_status": scan_status,
        "risk_tier": item.risk_tier.value if item.risk_tier else None,
        "company_id": item.company_id,
        "exposure_group": item.exposure_group,
        "target_weight": item.target_weight,
        "max_weight": item.max_weight,
        "profile_version": item.profile_version,
        "runtime_authority": source.value,
    }


def _latest_for_group(
    universe: RuntimeUniverse,
    repository: SnapshotRepository,
    group: str | None,
    config: AppConfig,
) -> list[ScanSnapshot]:
    allowed = set(universe.select_analysis_symbols(group=group))
    return sort_snapshots(
        [
            refresh_snapshot(
                snapshot, allow_call_candidate=universe.symbols[snapshot.ticker].allows_call_candidate,
                entry_policy=config.strategy.entry,
                momentum_rsi=config.strategy.thresholds.momentum_rsi,
            )
            for snapshot in repository.latest_all()
            if snapshot.ticker in allowed
        ]
    )


def _dashboard_symbols(universe: RuntimeUniverse, view: str) -> list[str]:
    if view == "all":
        return universe.enabled_analysis_symbols
    if view == "leader":
        return universe.select_analysis_symbols(
            group=TickerGroup.LEADER_LONG_CALL
        )
    if view == "long-term":
        long_term_groups = {
            TickerGroup.LONG_TERM_CORE,
            TickerGroup.LONG_TERM_GROWTH,
        }
        return [
            ticker
            for ticker in universe.enabled_analysis_symbols
            if universe.symbols[ticker].groups & long_term_groups
        ]
    if view == "high-risk":
        return universe.select_analysis_symbols(
            group=TickerGroup.HIGH_RISK_GROWTH
        )
    if view == "short-term":
        return universe.select_analysis_symbols(
            group=TickerGroup.SHORT_TERM_WATCH
        )
    raise UniverseSelectionError(
        "Unknown dashboard view. Valid views: all, leader, long-term, "
        "high-risk, short-term"
    )


def create_app(*, database_url: str | None = None) -> FastAPI:
    config = load_config(database_url=database_url)
    repository = SnapshotRepository(config.database_url)
    app = FastAPI(title=PRODUCT_NAME, version="0.1.0")
    app.state.config = config
    app.state.repository = repository
    classification_repository = None
    classification_service = None
    try:
        from app.classification.api import create_classification_router
        from app.classification.bootstrap import bootstrap_confirmed_profiles
        from app.classification.repository import ClassificationRepository
        from app.classification.service import ClassificationService

        classification_repository = ClassificationRepository(
            config.database_url
        )
        bootstrap_confirmed_profiles(config, classification_repository)
        classification_service = ClassificationService(
            classification_repository, config.classification
        )
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("Classification initialization failed: %s", exc)
        from app.classification.api import create_classification_router
    app.state.classification_repository = classification_repository
    app.state.classification_service = classification_service
    universe_resolver = (
        ConfirmedProfileUniverseResolver(config, classification_repository)
        if classification_repository is not None
        else StaticRuntimeUniverseResolver(
            config,
            source=RuntimeUniverseSource.DEGRADED_YAML,
            degraded_reason=(
                "Confirmed classification profiles are unavailable; "
                "using degraded YAML fallback."
            ),
        )
    )
    service = ScanService(
        config,
        repository,
        universe_resolver=universe_resolver,
    )
    app.state.scan_service = service
    app.state.universe_resolver = universe_resolver
    app.include_router(
        create_classification_router(
            classification_repository,
            classification_service,
            repository,
        )
    )
    options_repository = None
    options_service = None
    try:
        options_repository = OptionsScanRepository(config.database_url)
        options_service = OptionsScanService(
            config,
            repository,
            options_repository,
            universe_resolver=universe_resolver,
        )
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("Options initialization failed: %s", exc)
    app.state.options_context = OptionsContext(
        config=config,
        equity_repository=repository,
        options_repository=options_repository,
        options_service=options_service,
        universe_resolver=universe_resolver,
    )
    app.include_router(create_options_router())
    app.include_router(create_features_router())

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            database="ready",
            alpaca_credentials_configured=config.credentials_configured,
            data_feed=config.strategy.alpaca.feed,
            feed_note=(
                "IEX is a limited exchange feed and is not the full-market SIP feed."
                if config.strategy.alpaca.feed.lower() == "iex"
                else "Configured Alpaca market-data feed."
            ),
        )

    @app.get("/watchlist")
    def watchlist(group: str | None = None) -> dict:
        universe = universe_resolver.resolve()
        try:
            if group is None:
                tickers = sorted(universe.symbols)
            else:
                selected_group = TickerGroup(group.strip().lower())
                tickers = sorted(
                    ticker
                    for ticker, symbol in universe.symbols.items()
                    if selected_group in symbol.groups
                )
        except ValueError as exc:
            valid = ", ".join(item.value for item in TickerGroup)
            message = f"Unknown group '{group}'. Valid groups: {valid}"
            raise HTTPException(status_code=400, detail=message) from exc
        return {
            "profile_source": universe.source.value,
            "degraded": universe.degraded,
            "warnings": list(universe.warnings),
            "symbols": [
                _symbol_payload(
                    ticker,
                    config,
                    universe.symbols[ticker],
                    universe.source,
                )
                for ticker in tickers
            ],
        }

    @app.get("/scan/latest", response_model=list[ScanSnapshot])
    def latest_scan(group: str | None = None) -> list[ScanSnapshot]:
        try:
            return _latest_for_group(universe_resolver.resolve(), repository, group, config)
        except UniverseSelectionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/scan/{ticker}", response_model=ScanSnapshot)
    def ticker_scan(ticker: str) -> ScanSnapshot:
        symbol = universe_resolver.resolve().symbols.get(ticker.upper())
        if symbol is None:
            raise HTTPException(status_code=404, detail="Ticker is not in the watchlist")
        snapshot = repository.latest(ticker.upper())
        if not snapshot:
            raise HTTPException(status_code=404, detail="No scan is available for this ticker")
        return refresh_snapshot(
            snapshot, allow_call_candidate=symbol.allows_call_candidate,
            entry_policy=config.strategy.entry,
            momentum_rsi=config.strategy.thresholds.momentum_rsi,
        )

    @app.post("/scan", response_model=list[ScanSnapshot])
    def run_scan(
        group: str | None = None, ticker: str | None = None
    ) -> list[ScanSnapshot]:
        try:
            return sort_snapshots(service.scan(group=group, ticker=ticker))
        except UniverseSelectionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MarketDataError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/", response_class=HTMLResponse)
    def dashboard(view: str = "all") -> HTMLResponse:
        strategy_context = {
            "all": StrategyContext.ALL,
            "leader": StrategyContext.LEADER_LONG_CALL,
            "long-term": StrategyContext.LONG_TERM,
            "high-risk": StrategyContext.HIGH_RISK_GROWTH,
            "short-term": StrategyContext.SHORT_TERM,
        }.get(view)
        if strategy_context is None:
            raise HTTPException(status_code=400, detail=f"Unknown dashboard view: {view}")
        universe = universe_resolver.resolve()
        profile_source_label = (
            "Confirmed DB"
            if universe.source is RuntimeUniverseSource.CONFIRMED_DB
            else "Degraded YAML fallback"
        )
        profile_source_badge = (
            "<div class='update-badge' data-profile-source='"
            f"{escape(universe.source.value)}'>Profile source: "
            f"{escape(profile_source_label)}</div>"
        )
        try:
            configured_tickers = _dashboard_symbols(universe, view)
        except UniverseSelectionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        allowed = set(configured_tickers)
        snapshots = sort_snapshots(
            [
                refresh_snapshot(
                    snapshot, allow_call_candidate=universe.symbols[snapshot.ticker].allows_call_candidate,
                    entry_policy=config.strategy.entry,
                    momentum_rsi=config.strategy.thresholds.momentum_rsi,
                )
                for snapshot in repository.latest_all()
                if snapshot.ticker in allowed
            ]
        )
        long_term_view = view in {"long-term", "high-risk"}
        row_contexts = []
        for index, item in enumerate(snapshots):
            runtime_symbol = universe.symbols[item.ticker]
            guidance = derive_next_step(
                item,
                runtime_symbol,
                strategy_context,
                config.strategy.options,
            )
            move = derive_move_guidance(
                item,
                runtime_symbol,
                strategy_context,
                config.strategy.options,
                guidance,
            )
            row_contexts.append((item, guidance, move, index))
        pending_classification: set[str] = set()
        if classification_repository is not None:
            try:
                from app.classification.models import ProposalStatus

                pending_classification = {
                    item.ticker
                    for item in classification_repository.list_proposals(
                        status=ProposalStatus.PENDING
                    )
                }
            except SQLAlchemyError as exc:
                logger.warning(
                    "Pending classification query failed; dashboard unaffected: %s",
                    exc,
                )
        if long_term_view:
            rows = "".join(
                _dashboard_row(
                    item,
                    config,
                    runtime_symbol=universe.symbols[item.ticker],
                    strategy_context=strategy_context,
                    guidance=guidance,
                    move=move,
                    original_order=index,
                    pending_classification=item.ticker
                    in pending_classification,
                )
                for item, guidance, move, index in row_contexts
            )
            headers = (
                f"<th>Ticker</th>{MARKET_HEADERS}<th>Long-Term Group</th>"
                "<th>Manual Long-Term Action</th>"
                "<th>Technical Trend</th><th>New Entry / Call Readiness</th>"
                "<th>Checks</th><th>Next Step / 下一步</th><th>Explanation</th>"
            )
            separation_note = (
                "<div class='callout callout-warning'><strong>Role separation</strong>"
                "<span>Long-term group and action are manually configured and "
                "remain primary. Technical State is timing context and does not "
                "automatically change the long-term plan.</span></div>"
            )
        else:
            rows = "".join(
                _dashboard_row(
                    item,
                    config,
                    runtime_symbol=universe.symbols[item.ticker],
                    strategy_context=strategy_context,
                    guidance=guidance,
                    move=move,
                    original_order=index,
                    pending_classification=item.ticker
                    in pending_classification,
                )
                for item, guidance, move, index in row_contexts
            )
            headers = (
                f"<th>Ticker</th>{MARKET_HEADERS}<th>Technical Trend</th>"
                "<th>New Entry / Call Readiness</th>"
                "<th>Checks</th><th>Next Step / 下一步</th><th>Explanation</th>"
            )
            separation_note = (
                "<div class='callout callout-note'><strong>Strong stock != good entry</strong>"
                "<span>Trend and score describe stock quality. New entry requires a fresh "
                "structural stop, a real overhead target and sufficient reward/risk. "
                "Waiting is not an instruction to sell existing holdings.</span></div>"
            )

        controls = " ".join(
            f"<a class='{'active' if view == key else ''}' href='/?view={key}'>{label}</a>"
            for key, label in (
                ("all", "All"),
                ("leader", "Leader Long Call"),
                ("long-term", "Long-Term"),
                ("high-risk", "High-Risk Growth"),
                ("short-term", "Short-Term"),
            )
        )
        next_step_choices: dict[str, str] = {}
        for _, guidance, _, _ in row_contexts:
            next_step_choices.setdefault(guidance.code.value, guidance.headline)
        next_step_options = "".join(
            f"<option value='{escape(code)}'>{escape(headline)}</option>"
            for code, headline in next_step_choices.items()
        )
        action_options = "".join(
            f"<option value='{action}'>{action}</option>"
            for action in ("ADD", "HOLD", "PAUSE_ADD", "THESIS_REVIEW", "UNSET")
        )
        move_options = "".join(
            f"<option value='{lane.value}'>{escape(MOVE_LANE_LABELS[lane])}</option>"
            for lane in MoveLane
        )
        table_toolbar = (
            "<div class='table-toolbar' aria-label='Dashboard table filters and sorting'>"
            "<div class='table-control'><label for='move-filter'>Move</label>"
            "<select id='move-filter'><option value='ALL'>All Moves</option>"
            f"{move_options}</select></div>"
            "<div class='table-control'><label for='next-step-filter'>Next Step</label>"
            "<select id='next-step-filter'><option value='ALL'>All Next Steps</option>"
            f"{next_step_options}</select></div>"
            "<div class='table-control'><label for='long-term-action-filter'>"
            "Manual Long-Term Action</label><select id='long-term-action-filter'>"
            f"<option value='ALL'>All Manual Actions</option>{action_options}"
            "</select></div>"
            "<div class='table-control'><label for='dashboard-sort'>Sort by</label>"
            "<select id='dashboard-sort'>"
            "<option value='default'>Default priority</option>"
            "<option value='move-priority'>Move priority</option>"
            "<option value='ticker-asc'>Ticker A–Z</option>"
            "<option value='ticker-desc'>Ticker Z–A</option>"
            "<option value='state-priority'>Technical State priority</option>"
            "<option value='score-desc'>Tech Setup Score high → low</option>"
            "<option value='score-asc'>Tech Setup Score low → high</option>"
            "</select></div>"
            "<button class='table-reset' id='reset-table-controls' type='button'>"
            "Reset</button><div class='table-toolbar-note'>Move routes review attention "
            "without changing State, eligibility, or the confirmed manual plan. "
            "All filters combine with AND logic.</div></div>"
        )
        empty = (
            "<div class='empty-state'><div class='empty-icon'>◇</div>"
            "<strong>No matching scans yet</strong><span>Run the corresponding "
            "filtered scan or <code>python -m app.scanner</code>.</span></div>"
            if not snapshots
            else ""
        )
        unscanned_count = len(configured_tickers) - len(snapshots)
        unscanned_note = (
            f"<div class='callout callout-note'><strong>Coverage note</strong>"
            f"<span>{unscanned_count} configured symbol(s) in this view have "
            "not been scanned and are omitted.</span></div>"
            if unscanned_count > 0
            else ""
        )
        market_session_note = (
            "<div class='callout callout-note'><strong>Market-session fields</strong>"
            "<span>Today % compares the latest completed 15-minute close with the "
            "previous regular-session close; 15m % compares consecutive completed "
            "15-minute closes. Today Open is the first regular-session 15-minute "
            "bar open and becomes available after that bar completes, normally "
            "09:45 ET. Values come from the already-fetched Alpaca bars.</span></div>"
        )

        watching_count = sum(
            item.current_state.value in {"DIP_WATCH", "SELLING_EXHAUSTION"}
            for item in snapshots
        )
        repairing_count = sum(
            item.current_state.value == "RIGHT_SIDE_REPAIR" for item in snapshots
        )
        call_count = sum(
            evaluate_call_readiness(
                item, allow_call_candidate=universe.symbols[item.ticker].allows_call_candidate
            ).qualified for item in snapshots
        )
        long_term_add_count = sum(
            universe.symbols[item.ticker].long_term_action is not None
            and universe.symbols[item.ticker].long_term_action.value == "ADD"
            for item in snapshots
        )
        latest_refresh = (
            max(snapshots, key=lambda item: item.scanned_at).displayed_at_et
            if snapshots
            else "—"
        )
        view_title = {
            "all": "All Analysis",
            "leader": "Leader Long Call",
            "long-term": "Long-Term",
            "high-risk": "High-Risk Growth",
            "short-term": "Short-Term",
        }[view]
        return HTMLResponse(
            "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{PRODUCT_NAME}</title><style>"
            ":root{--blue:#0A66C2;--blue-dark:#004182;--bg:#F3F2EF;"
            "--surface:#FFFFFF;--text:#1A1A1A;--secondary:#555;--muted:#888;"
            "--green:#057642;--red:#CC1016;--orange:#E16B16;"
            "--purple:#7B2FBE;--blue-tint:#E8F0FD;--border:#E8E6E3;"
            "--shadow:0 1px 3px rgba(0,0,0,.08),0 1px 2px rgba(0,0,0,.04)}"
            "*,*::before,*::after{box-sizing:border-box}body{margin:0;background:"
            "var(--bg);color:var(--text);font-family:'Source Sans 3',-apple-system,"
            "BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;line-height:1.5}"
            ".page{max-width:1440px;margin:0 auto;padding:24px}.hero{background:"
            "linear-gradient(135deg,var(--blue) 0%,var(--blue-dark) 100%);"
            "border-radius:12px;color:#fff;padding:28px 30px 20px;box-shadow:"
            "0 8px 24px rgba(0,65,130,.18)}.hero-top{display:flex;align-items:"
            "flex-start;justify-content:space-between;gap:24px}.eyebrow,.label,"
            "th,.card-title{font-size:10.5px;font-weight:700;text-transform:uppercase;"
            "letter-spacing:.7px}.eyebrow{color:rgba(255,255,255,.58);margin-bottom:"
            "5px}.hero h1{font-size:30px;line-height:1.15;margin:0 0 7px;letter-spacing:"
            "-.4px}.hero p{margin:0;color:rgba(255,255,255,.74);font-size:15px}"
            ".hero-meta{text-align:right}.update-badge{white-space:nowrap;"
            "background:rgba(255,255,255,.15);border:"
            "1px solid rgba(255,255,255,.3);border-radius:20px;padding:6px 11px;"
            "font-size:11px;font-weight:600}.view-nav{display:flex;"
            "flex-wrap:wrap;gap:7px;margin:14px 0}.view-nav a{display:inline-block;padding:"
            "7px 11px;border-radius:7px;color:var(--blue-dark);text-decoration:none;"
            "font-size:12px;font-weight:600;border:1px solid #bfd5eb;background:#f7fbff}"
            ".view-nav a:hover{background:var(--blue-tint)}.view-nav a.active{background:"
            "var(--blue);color:#fff;border-color:var(--blue)}.kpi-grid{display:"
            "grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;"
            "margin:14px 0 18px}.kpi-card,.card{background:var(--surface);border-radius:"
            "10px;box-shadow:var(--shadow)}.kpi-card{padding:16px 18px}.label{color:"
            "var(--muted);margin-bottom:4px}.kpi-value{font-size:24px;line-height:1.2;"
            "font-weight:700;color:var(--blue)}.kpi-meta{font-size:12px;color:#999;"
            "margin-top:2px}.content-card{padding:0;overflow:hidden}.card-head{display:"
            "flex;justify-content:space-between;align-items:center;gap:16px;padding:"
            "17px 20px 12px}.card-title{color:var(--blue);border-bottom:2px solid "
            "var(--blue-tint);padding-bottom:8px;flex:1}.result-count{font-size:12px;"
            "color:var(--muted);white-space:nowrap}.table-wrap{overflow-x:auto}table{"
            "border-collapse:collapse;width:100%;min-width:1180px}"
            ".dashboard-long-term{min-width:1400px}th{background:#F9F9F8;"
            "color:var(--muted);padding:10px 14px;text-align:left;border-bottom:1px "
            "solid var(--border);white-space:nowrap}td{padding:12px 14px;text-align:"
            "left;border-bottom:1px solid #F0EFEC;color:#444;vertical-align:middle}"
            "tbody tr:last-child td{border-bottom:0}tbody tr:hover{filter:brightness("
            ".985)}.row-staying{background:#F7FBF8}.row-leaving{background:#FFFAFA}"
            ".row-incoming{background:#F8FBFF}.row-split{background:#FFFCF7}"
            ".row-covered{background:#FCFAFF}.ticker{font-size:14px;color:var(--text);"
            "letter-spacing:.2px}.classification-pending{color:var(--orange);"
            "text-decoration:none;margin-left:5px}.score{font-size:16px;color:var(--blue)}.number{"
            "font-variant-numeric:tabular-nums}.timestamp{font-size:12px;color:#888;"
            "white-space:nowrap}.muted{color:var(--muted)}.legacy-note{color:#765A18;"
            "font-size:12px}.next-trigger{min-width:210px;max-width:280px}"
            ".next-trigger strong,.next-trigger small,.next-trigger span{display:block}"
            ".next-trigger small{color:var(--secondary);margin:3px 0}"
            ".next-step{min-width:220px;max-width:290px;padding-left:11px;"
            "border-left:3px solid var(--next-step-accent,#9C7AF2)}"
            ".next-step strong,.next-step small{display:block}"
            ".next-step strong{color:var(--shell-heading);margin-top:5px}"
            ".next-step-compact{min-width:170px;max-width:260px}"
            ".next-step-compact strong{margin-top:0}"
            ".next-step small{color:var(--secondary);margin-top:3px;line-height:1.35}"
            ".next-step-tone{display:inline-flex;padding:2px 7px;border-radius:999px;"
            "font-size:10px;font-weight:800;letter-spacing:.05em;text-transform:uppercase;"
            "color:#6546C9;background:#F2EEFF;border:1px solid #DCD2FF}"
            ".next-step-neutral{--next-step-accent:#B5A9CC}"
            ".next-step-watch{--next-step-accent:#9C7AF2}"
            ".next-step-wait{--next-step-accent:#B88A3B}"
            ".next-step-review{--next-step-accent:#7C5CE5}"
            ".next-step-caution{--next-step-accent:#B65775}"
            ".move{min-width:185px;max-width:245px}.move strong,.move small{display:block}"
            ".move strong{margin-top:5px;color:var(--text)}.move small{margin-top:2px;"
            "color:var(--secondary);line-height:1.3}.move-lane{display:inline-flex;"
            "padding:3px 8px;border-radius:999px;font-size:9.5px;font-weight:800;"
            "letter-spacing:.04em;text-transform:uppercase;border:1px solid #D5D0DE}"
            ".move-options-setup .move-lane{background:#E8F0FD;color:var(--blue);"
            "border-color:#B8D2EE}.move-long-term-plan .move-lane{background:#E7F3E8;"
            "color:var(--green);border-color:#B8D8C0}.move-thesis-review .move-lane{"
            "background:#F0E6FF;color:var(--purple);border-color:#D6BDEF}"
            ".move-risk-caution .move-lane{background:#FDECEA;color:var(--red);"
            "border-color:#F2C2C4}.move-wait-monitor .move-lane{background:#F3F2EF;"
            "color:#666;border-color:#D0CFCD}"
            ".readiness{min-width:210px}.readiness-badge{display:inline-flex;padding:3px 8px;"
            "border-radius:999px;background:#F1EDFF;color:#6546C9;font-size:10px;"
            "font-weight:800;letter-spacing:.04em}.readiness-qualified{background:#E7F3E8;"
            "color:var(--green)}.readiness-near_qualification{background:#EEE9FF;"
            "color:#6546C9}.readiness-developing{background:#FFF4E5;color:#8A5B00}"
            ".readiness-not_ready{background:#F3F2EF;color:#777}.readiness ul{list-style:none;"
            "margin:7px 0 0;padding:0}.readiness li{display:grid;grid-template-columns:16px 1fr;"
            "gap:0 4px;margin-top:3px;font-size:11px}.readiness li span{grid-row:1/3}"
            ".readiness li.pass span{color:var(--green)}.readiness li.fail span{color:#9A80D8}"
            ".readiness li strong,.readiness li small{display:block}.readiness li small{"
            "grid-column:2;color:var(--muted);white-space:normal;line-height:1.25}"
            ".readiness-blocked{background:#FDECEA;color:var(--red)}"
            ".dashboard-guide{margin:0 0 14px;color:var(--secondary)}"
            ".dashboard-guide>summary{cursor:pointer;font-size:12px}"
            ".dashboard-guide .callout{margin-top:10px}"
            ".trigger-level{color:var(--blue);font-weight:700}.explanation{min-width:"
            "150px}.explanation summary{color:var(--blue);cursor:pointer;font-weight:700;"
            "white-space:nowrap}.explanation dl{min-width:330px;margin:10px 0 0;padding:"
            "12px;background:#F9F9F8;border:1px solid var(--border);border-radius:7px}"
            ".explanation dt{font-size:10px;font-weight:700;text-transform:uppercase;"
            "letter-spacing:.5px;color:var(--muted);margin-top:10px}.explanation dt:first-"
            "child{margin-top:0}.explanation dd{margin:3px 0;color:var(--secondary)}"
            ".explanation dd>div+div{margin-top:3px}.explain-list{margin:0;padding-left:"
            "18px}.explain-list li+li{margin-top:3px}.explanation code{font-size:10px}"
            ".delta-positive{"
            "color:var(--green);font-weight:600;white-space:nowrap}.delta-negative{"
            "color:var(--red);font-weight:600;white-space:nowrap}.pill{display:inline-"
            "block;font-size:10px;font-weight:700;letter-spacing:.5px;padding:3px 9px;"
            "border-radius:20px;text-transform:uppercase;white-space:nowrap;margin:"
            "1px 2px 1px 0}.pill-staying{background:#E7F3E8;color:var(--green)}"
            ".pill-leaving{background:#FDECEA;color:var(--red)}.pill-incoming{"
            "background:var(--blue-tint);color:var(--blue)}.pill-unassigned{"
            "background:#F3F2EF;color:#666;border:1px solid #D0CFCD}.pill-split{"
            "background:#FFF4E5;color:var(--orange)}.pill-covered{background:#F0E6FF;"
            "color:var(--purple)}.callout{display:flex;gap:12px;align-items:baseline;"
            "margin:0 0 14px;padding:11px 14px;border-radius:0 8px 8px 0}.callout "
            "strong{font-size:11px;text-transform:uppercase;letter-spacing:.5px;"
            "white-space:nowrap}.callout-note{background:#F0F7FF;border-left:3px solid "
            "var(--blue);color:#315A7D}.callout-warning{background:#FFF8E6;border-left:"
            "3px solid #E8A000;color:#5A3E00}.empty-state{text-align:center;padding:"
            "48px 20px;color:#666}.empty-state strong,.empty-state span{display:block}"
            ".empty-state strong{color:var(--text);font-size:16px;margin:8px 0 3px}"
            ".empty-icon{width:42px;height:42px;line-height:39px;margin:0 auto;border-"
            "radius:50%;background:var(--blue-tint);color:var(--blue);font-size:24px}"
            ".scan-toolbar{display:flex;align-items:center;gap:14px;margin-top:18px;"
            "padding:13px 16px;background:var(--surface);border-radius:10px;box-shadow:"
            "var(--shadow)}.scan-button{appearance:none;border:0;border-radius:7px;"
            "background:var(--blue);color:#fff;padding:9px 15px;font:inherit;font-weight:"
            "700;cursor:pointer;white-space:nowrap;transition:background .15s,opacity .15s}"
            ".scan-button:hover:not(:disabled){background:var(--blue-dark)}.scan-button:"
            "disabled{cursor:not-allowed;opacity:.58}.scan-copy{color:var(--secondary);"
            "font-size:12px}.scan-status{margin-left:auto;font-size:12px;font-weight:700;"
            "color:var(--blue);min-width:90px;text-align:right}.scan-status.scan-error{"
            "color:var(--red);max-width:520px}.scan-status:empty{display:none}"
            ".table-toolbar{display:flex;align-items:flex-end;gap:10px;flex-wrap:wrap;"
            "padding:14px 20px;background:#FAF8FF;border-top:1px solid #EEE9FA;"
            "border-bottom:1px solid var(--border)}.table-control{display:grid;gap:4px;"
            "min-width:170px}.table-control label{font-size:10px;font-weight:800;"
            "letter-spacing:.06em;text-transform:uppercase;color:#756894}"
            ".table-control select{appearance:auto;border:1px solid #D9D0EE;"
            "border-radius:7px;background:#fff;color:var(--secondary);font:inherit;"
            "font-size:12px;padding:7px 28px 7px 9px}.table-control select:focus,"
            ".table-reset:focus{outline:2px solid #9274E6;outline-offset:2px}"
            ".table-reset{border:1px solid #CFC3EA;border-radius:7px;background:#F5F1FF;"
            "color:#6546C9;font:inherit;font-size:12px;font-weight:700;padding:7px 12px;"
            "cursor:pointer}.table-reset:hover{background:#ECE5FF}"
            ".table-toolbar-note{flex:1;min-width:240px;color:var(--muted);font-size:11px;"
            "line-height:1.35;padding-bottom:2px}.filtered-empty{padding:30px 20px;"
            "text-align:center;color:var(--secondary);background:#FCFBFF}"
            ".filtered-empty[hidden],[data-dashboard-row][hidden]{display:none}"
            f"{glossary_styles()}{shared_page_styles()}{readiness_light_styles()}"
            "code{font-family:'SF Mono',Consolas,monospace;background:#F3F2EF;padding:"
            "2px 5px;border-radius:4px}.footer-note{text-align:center;color:#999;font-"
            "size:11px;margin:16px 0 0}@media(max-width:700px){.page{padding:12px}"
            ".hero{padding:22px 20px 16px}.hero-top{display:block}.hero-meta{text-align:left;"
            "margin-top:14px}.update-badge{display:inline-block}.hero h1{font-size:26px}.kpi-grid{grid-"
            "template-columns:repeat(2,1fr)}.scan-toolbar{align-items:flex-start;"
            "flex-wrap:wrap}.scan-status{width:100%;margin-left:0;text-align:left}"
            ".table-toolbar{align-items:stretch}.table-control{min-width:100%;}"
            ".table-reset{width:max-content}.table-toolbar-note{min-width:100%}"
            ".callout{display:block}.callout strong{display:block;margin-bottom:3px}}"
            "</style></head><body><div class='app-viewport'>"
            "<main class='page app-shell'><div class='page-shell'>"
            "<header class='hero page-hero'><div class='hero-top page-hero-top'>"
            "<div><div class='eyebrow'>"
            f"Market Analysis Workspace</div><h1>{PRODUCT_NAME}</h1><p>Deterministic "
            "technical context for a focused equity universe.</p></div>"
            "<div class='hero-meta'>"
            f"<div class='update-badge'>Last update: {escape(latest_refresh)}"
            f"</div>{profile_source_badge}</div></div>"
            f"{render_primary_nav('dashboard')}</header>"
            f"<div class='view-nav' aria-label='Dashboard views'>{controls}</div>"
            "<section class='scan-toolbar control-plane' "
            "aria-label='Equity scan controls'>"
            "<button class='scan-button' id='run-equity-scan' type='button'>"
            "Run Equity Scan</button><div class='scan-copy'><strong>Analysis only.</strong> "
            "Scans all enabled equities and never places or prepares orders.</div>"
            "<div class='scan-status' id='scan-status' role='status' "
            "aria-live='polite'></div></section>"
            "<section class='kpi-grid' aria-label='Scan summary'>"
            f"<div class='kpi-card'><div class='label'>Coverage</div><div class='kpi-value'>{len(snapshots)}</div><div class='kpi-meta'>of {len(configured_tickers)} in view</div></div>"
            f"<div class='kpi-card'><div class='label'>Watching</div><div class='kpi-value'>{watching_count}</div><div class='kpi-meta'>dip watch + selling exhaustion</div></div>"
            f"<div class='kpi-card'><div class='label'>Repairing</div><div class='kpi-value'>{repairing_count}</div><div class='kpi-meta'>right-side repair</div></div>"
            f"<div class='kpi-card'><div class='label'>Entry Qualified</div><div class='kpi-value'>{call_count}</div><div class='kpi-meta'>fresh structural entry and readiness gates passed</div></div>"
            f"<div class='kpi-card'><div class='label'>Long-Term Add</div><div class='kpi-value'>{long_term_add_count}</div><div class='kpi-meta'>manual action in displayed rows</div></div>"
            "</section><details class='dashboard-guide'><summary>About these conclusions</summary>"
            f"{separation_note}{market_session_note}</details>{unscanned_note}"
            "<section class='card content-card'><div class='card-head'>"
            f"<div class='card-title'>{escape(view_title)} Setups</div>"
            f"<div class='result-count' id='dashboard-result-count' role='status' "
            f"aria-live='polite'>Showing {len(snapshots)} of {len(snapshots)}</div></div>"
            f"{table_toolbar}{empty}<div class='filtered-empty' "
            "id='dashboard-filter-empty' role='status' hidden>"
            "No displayed rows match these table filters. Reset or change the filters."
            f"</div><div class='table-wrap'><table class='{'dashboard-long-term' if long_term_view else 'dashboard-summary'}'><thead><tr>{headers}"
            f"</tr></thead><tbody id='dashboard-table-body'>{rows}</tbody></table>"
            "</div></section>"
            "<p class='footer-note'>Analysis only · No brokerage connectivity · "
            f"Completed-bar data</p>{render_glossary()}</div></main></div>"
            "<script>"
            "const dashboardRows=Array.from(document.querySelectorAll("
            "\"[data-dashboard-row]\"));"
            "const dashboardBody=document.getElementById('dashboard-table-body');"
            "const moveFilter=document.getElementById('move-filter');"
            "const stepFilter=document.getElementById('next-step-filter');"
            "const actionFilter=document.getElementById('long-term-action-filter');"
            "const dashboardSort=document.getElementById('dashboard-sort');"
            "const resetTableControls=document.getElementById('reset-table-controls');"
            "const dashboardResultCount=document.getElementById('dashboard-result-count');"
            "const dashboardFilterEmpty=document.getElementById('dashboard-filter-empty');"
            "const validValue=(select,value,fallback)=>Array.from(select.options)"
            ".some(option=>option.value===value)?value:fallback;"
            "const tableParams=new URLSearchParams(window.location.search);"
            "moveFilter.value=validValue(moveFilter,tableParams.get('move')||'ALL','ALL');"
            "stepFilter.value=validValue(stepFilter,tableParams.get('step')||'ALL','ALL');"
            "actionFilter.value=validValue(actionFilter,tableParams.get('action')||'ALL','ALL');"
            "dashboardSort.value=validValue(dashboardSort,tableParams.get('sort')||'default','default');"
            "const originalOrder=row=>Number(row.dataset.originalOrder);"
            "const tickerCompare=(left,right)=>left.dataset.ticker.localeCompare("
            "right.dataset.ticker,'en',{sensitivity:'base'});"
            "const stableCompare=(left,right)=>{"
            "let result=0;"
            "if(dashboardSort.value==='ticker-asc')result=tickerCompare(left,right);"
            "else if(dashboardSort.value==='ticker-desc')result=tickerCompare(right,left);"
            "else if(dashboardSort.value==='state-priority')result="
            "Number(left.dataset.stateRank)-Number(right.dataset.stateRank);"
            "else if(dashboardSort.value==='move-priority')result="
            "Number(left.dataset.moveRank)-Number(right.dataset.moveRank);"
            "else if(dashboardSort.value==='score-desc')result="
            "Number(right.dataset.techScore)-Number(left.dataset.techScore);"
            "else if(dashboardSort.value==='score-asc')result="
            "Number(left.dataset.techScore)-Number(right.dataset.techScore);"
            "return result||originalOrder(left)-originalOrder(right);};"
            "const syncTableQuery=()=>{"
            "const url=new URL(window.location.href);"
            "for(const [key,value,defaultValue] of [['move',moveFilter.value,'ALL'],"
            "['step',stepFilter.value,'ALL'],"
            "['action',actionFilter.value,'ALL'],['sort',dashboardSort.value,'default']]){"
            "if(value===defaultValue)url.searchParams.delete(key);"
            "else url.searchParams.set(key,value);}"
            "history.replaceState(null,'',url.pathname+url.search);};"
            "const applyTableControls=(persist=true)=>{"
            "dashboardRows.sort(stableCompare).forEach(row=>dashboardBody.appendChild(row));"
            "let visibleCount=0;"
            "dashboardRows.forEach(row=>{"
            "const moveMatch=moveFilter.value==='ALL'||"
            "row.dataset.moveLane===moveFilter.value;"
            "const stepMatch=stepFilter.value==='ALL'||"
            "row.dataset.nextStepCode===stepFilter.value;"
            "const actionMatch=actionFilter.value==='ALL'||"
            "row.dataset.longTermAction===actionFilter.value;"
            "row.hidden=!(moveMatch&&stepMatch&&actionMatch);"
            "if(!row.hidden)visibleCount+=1;});"
            "dashboardResultCount.textContent=`Showing ${visibleCount} of ${dashboardRows.length}`;"
            "dashboardFilterEmpty.hidden=dashboardRows.length===0||visibleCount>0;"
            "if(persist)syncTableQuery();};"
            "[moveFilter,stepFilter,actionFilter,dashboardSort].forEach(control=>"
            "control.addEventListener('change',()=>applyTableControls()));"
            "resetTableControls.addEventListener('click',()=>{"
            "moveFilter.value='ALL';stepFilter.value='ALL';actionFilter.value='ALL';"
            "dashboardSort.value='default';applyTableControls();});"
            "applyTableControls(true);"
            "const scanButton=document.getElementById('run-equity-scan');"
            "const scanStatus=document.getElementById('scan-status');"
            "let scanInFlight=false;"
            "scanButton.addEventListener('click',async()=>{"
            "if(scanInFlight)return;"
            "scanInFlight=true;scanButton.disabled=true;"
            "scanStatus.className='scan-status';scanStatus.textContent='Scanning...';"
            "try{"
            "const response=await fetch('/scan',{method:'POST',headers:{"
            "'Accept':'application/json'}});"
            "if(!response.ok){"
            "const raw=await response.text();"
            "let message=raw.trim()||`HTTP ${response.status}`;"
            "if((response.headers.get('content-type')||'').includes('application/json')"
            "&&raw){try{const parsed=JSON.parse(raw);"
            "if(parsed&&typeof parsed.detail==='string')message=parsed.detail;"
            "}catch(parseError){message=raw.trim()||`HTTP ${response.status}`;}}"
            "throw new Error(message);}"
            "window.location.assign(window.location.pathname+window.location.search);"
            "}catch(error){"
            "scanStatus.className='scan-status scan-error';"
            "scanStatus.textContent=`Scan failed: ${error instanceof Error?"
            "error.message:'Unknown error'}`;"
            "scanInFlight=false;scanButton.disabled=false;"
            "}});"
            f"{glossary_script()}"
            f"</script><script>{readiness_light_script()}"
            "</script></body></html>"
        )

    return app

app = create_app()
