from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape

from app.config import AppConfig
from app.call_readiness import evaluate_call_readiness
from app.entry_ui import (
    entry_conclusion, entry_markup, readiness_lights,
    readiness_light_script, readiness_light_styles,
)
from app.entry import current_entry
from app.models import ScanSnapshot
from app.options.eligibility import evaluate_options_eligibility
from app.options.models import (
    EligibilityDecision,
    EligibilityStatus,
    OptionCandidateStatus,
    OptionContract,
    OptionsScanResult,
    OptionsScanStatus,
    ScoredOptionCandidate,
)
from app.runtime_universe import RuntimeSymbol
from app.readiness_models import CallReadinessEvaluation, CallRequirementCode
from app.ui import (
    MARKET_HEADERS,
    PRODUCT_NAME,
    format_timestamp_et,
    glossary_script,
    glossary_styles,
    render_glossary,
    render_market_cells,
    render_primary_nav,
    render_ticker_copy,
    shared_page_styles,
)

_STATUS_LABELS = {
    OptionsScanStatus.NOT_ELIGIBLE: "Not Eligible",
    OptionsScanStatus.MANUAL_OVERRIDE: "Manual Override",
    OptionsScanStatus.OPTIONS_DATA_UNAVAILABLE: "Options Data Unavailable",
    OptionsScanStatus.NO_SUITABLE_CONTRACT: "No Suitable Contract",
    OptionsScanStatus.CANDIDATES_FOUND: "Candidates Found",
}

DISCLOSURE_NOTICE = (
    "<div class='notice disclosure'><strong>TOP_CANDIDATE</strong> marks the best "
    "configured contract fit under the scoring rules below — it is not a "
    "recommendation and carries no instruction about any position. This page "
    "reports contract fit only; it never manages orders, trades, or broker "
    "positions. When the displayed feed is <strong>indicative</strong>, quotes "
    "and trades may be modified and delayed up to 15 minutes, so spread and "
    "liquidity figures should be treated cautiously and are not guaranteed to "
    "reflect current tradable prices. OPRA requires a market-data "
    "subscription.</div>"
)

MANUAL_OVERRIDE_WARNING = (
    "Manual Override permits research despite entry, state or score blockers. "
    "It never grants execution qualification. Contract filtering and scoring are unchanged."
)

CURRENT_SETUP_MAX_AGE = timedelta(minutes=30)
NEAR_QUALIFICATION_LIMIT = 5


@dataclass(frozen=True)
class _EquitySetupView:
    snapshot: ScanSnapshot
    eligibility: EligibilityDecision
    readiness: CallReadinessEvaluation


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _setup_views(
    config: AppConfig,
    eligible_tickers: list[str],
    equity_snapshots: list[ScanSnapshot],
    runtime_symbols: Mapping[str, RuntimeSymbol] | None = None,
    as_of: datetime | None = None,
) -> list[_EquitySetupView]:
    snapshots = {item.ticker.upper(): item for item in equity_snapshots}
    views: list[_EquitySetupView] = []
    for ticker in eligible_tickers:
        snapshot = snapshots.get(ticker)
        symbol = (
            runtime_symbols.get(ticker)
            if runtime_symbols is not None
            else config.symbols.get(ticker)
        )
        if snapshot is None or symbol is None:
            continue
        snapshot = snapshot.model_copy(update={
            "entry_plan": current_entry(
                snapshot.entry_plan, now=as_of, policy=config.strategy.entry,
                momentum_rsi=config.strategy.thresholds.momentum_rsi,
            )
        })
        views.append(
            _EquitySetupView(
                snapshot=snapshot,
                eligibility=evaluate_options_eligibility(
                    snapshot,
                    symbol,
                    config.strategy.options,
                    as_of=as_of,
                    entry_policy=config.strategy.entry,
                    momentum_rsi=config.strategy.thresholds.momentum_rsi,
                ),
                readiness=evaluate_call_readiness(
                    snapshot,
                    allow_call_candidate=symbol.allows_call_candidate,
                    as_of=as_of,
                    entry_policy=config.strategy.entry,
                    momentum_rsi=config.strategy.thresholds.momentum_rsi,
                ),
            )
        )
    return views


def _matches_current_equity(
    result: OptionsScanResult,
    setup: _EquitySetupView,
    rendered_at: datetime,
) -> bool:
    scan_age = rendered_at - _as_utc(result.scanned_at)
    return (
        setup.eligibility.execution_qualified
        and result.eligibility.execution_qualified
        and not result.eligibility.manual_override
        and result.equity_state == setup.snapshot.current_state
        and result.equity_snapshot_at is not None
        and _as_utc(result.equity_snapshot_at) == _as_utc(setup.snapshot.scanned_at)
        and abs(result.equity_score - setup.snapshot.score) < 1e-9
        and _as_utc(result.scanned_at) >= _as_utc(setup.snapshot.scanned_at)
        and timedelta(0) <= scan_age <= CURRENT_SETUP_MAX_AGE
    )


def _near_sort_key(view: _EquitySetupView) -> tuple[int, float, str]:
    priority = {
        "RIGHT_SIDE_REPAIR": 0,
        "SELLING_EXHAUSTION": 1,
        "DIP_WATCH": 2,
        "NORMAL": 3,
        "BREAKDOWN": 4,
    }
    return (
        priority.get(view.snapshot.current_state.value, 5),
        -view.snapshot.score,
        view.snapshot.ticker,
    )


def _text(value: object | None, unavailable: str = "—") -> str:
    if value is None:
        return unavailable
    return escape(str(getattr(value, "value", value)))


def _timestamp(value: datetime | None) -> str:
    return escape(format_timestamp_et(value))


def _num(value: float | int | None, fmt: str = "{:.2f}") -> str:
    return _text(fmt.format(value) if value is not None else None)


def _money(value: float | None) -> str:
    return _text(f"${value:,.2f}" if value is not None else None)


def _pct(value: float | None, digits: int = 1) -> str:
    return _text(f"{value:.{digits}%}" if value is not None else None)


def _iv_cell(contract: OptionContract) -> str:
    return _pct(contract.implied_volatility)


def _relative_iv_cell(contract: OptionContract) -> str:
    return _pct(contract.chain_relative_iv_percentile, digits=0)


def _quote_age_cell(
    contract: OptionContract, result: OptionsScanResult, *, now: datetime,
) -> str:
    parts: list[str] = []
    if contract.quote_timestamp is not None:
        age_seconds = (now - _as_utc(contract.quote_timestamp)).total_seconds()
        parts.append(f"{int(age_seconds)}s" if age_seconds >= 0 else "Future timestamp")
    else:
        parts.append("—")
    if result.feed:
        parts.append(escape(result.feed))
    return " · ".join(parts) if parts else "—"


def _list_markup(values: Iterable[object]) -> str:
    items = [escape(str(getattr(value, "value", value))) for value in values]
    if not items:
        return "<span class='muted'>None</span>"
    return "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"


def _signal(label: str, tone: str) -> str:
    return f"<span class='signal signal-{escape(tone)}'>{escape(label)}</span>"


def _explanation(content: str) -> str:
    return "<details class='explanation'><summary>Explanation</summary>" + content + "</details>"


def _entry_signal(view: _EquitySetupView, *, now: datetime) -> str:
    allowed = any(
        item.code is CallRequirementCode.LEADER_WORKFLOW_ENABLED and item.passed
        for item in view.readiness.requirements
    )
    label, tone = entry_conclusion(
        view.snapshot.entry_plan, qualified=view.eligibility.execution_qualified,
        allowed=allowed, now=now,
    )
    return _signal(label, tone)


def _eligibility_signal(decision: EligibilityDecision) -> str:
    if decision.execution_qualified:
        return _signal("Qualified", "qualified")
    if decision.manual_override:
        return _signal("Manual research", "research")
    if decision.research_eligible:
        return _signal("Research only", "research")
    return _signal("Not eligible", "not_ready")


def _scan_signal(result: OptionsScanResult) -> str:
    tone = {
        OptionsScanStatus.CANDIDATES_FOUND: "fit",
        OptionsScanStatus.NO_SUITABLE_CONTRACT: "developing",
        OptionsScanStatus.OPTIONS_DATA_UNAVAILABLE: "blocked",
        OptionsScanStatus.NOT_ELIGIBLE: "not_ready",
        OptionsScanStatus.MANUAL_OVERRIDE: "research",
    }[result.status]
    return _signal(_STATUS_LABELS[result.status], tone)


def _context_signal(
    result: OptionsScanResult, *, setup: _EquitySetupView | None, now: datetime,
    historical: bool = False,
) -> str:
    context = _signal("Historical scan" if historical else "Not current", "not_ready")
    if result.eligibility.manual_override:
        return _signal("Manual research", "research") + context
    if not historical and setup is not None and _matches_current_equity(result, setup, now):
        return _entry_signal(setup, now=now)
    if result.eligibility.status is EligibilityStatus.RESEARCH_ELIGIBLE:
        return _signal("Research only", "research") + context
    return context if historical else _signal("Historical / refresh required", "not_ready")


def _attention_signals(
    result: OptionsScanResult, *, now: datetime, stale_quote_minutes: float | None,
    candidate: ScoredOptionCandidate | None = None,
) -> str:
    if result.status is OptionsScanStatus.OPTIONS_DATA_UNAVAILABLE:
        return _signal("Data unavailable", "blocked")
    candidates = [candidate] if candidate is not None else result.accepted_candidates
    labels: list[tuple[str, str]] = []
    if result.feed and "indicative" in result.feed.lower():
        labels.append(("Delayed feed", "developing"))
    elif not result.feed:
        labels.append(("Feed unavailable", "not_ready"))
    if (
        result.warnings or result.eligibility.warnings
        or any(
            item.warnings or item.confidence_penalties
            or item.contract.warnings or item.contract.data_quality_flags
            for item in candidates
        )
    ):
        labels.append(("Review warnings", "developing"))
    quotes = [item.contract.quote_timestamp for item in candidates]
    if any(quote is None for quote in quotes):
        labels.append(("Quote time missing", "developing"))
    known_quotes = [_as_utc(quote) for quote in quotes if quote is not None]
    if any(quote > now for quote in known_quotes):
        labels.append(("Check quote time", "developing"))
    if stale_quote_minutes is not None:
        if any(now - quote > timedelta(minutes=stale_quote_minutes) for quote in known_quotes):
            labels.append(("Quote stale", "developing"))
    elif known_quotes:
        labels.append(("Quote age unverified", "not_ready"))
    if not labels:
        labels.append(("No recorded warnings", "not_ready"))
    return "".join(_signal(label, tone) for label, tone in labels)


def _equity_details(view: _EquitySetupView, *, now: datetime) -> str:
    checks = "".join(
        f"<li><strong>{item.status.value}: {escape(item.label)}</strong>"
        f" — {escape(item.evidence)}</li>"
        for item in view.readiness.requirements
    )
    return (
        "<h3>Current equity context</h3><dl class='facts'>"
        f"<dt>Equity State</dt><dd>{_text(view.snapshot.current_state)}</dd>"
        f"<dt>Tech Setup Score</dt><dd>{_num(view.snapshot.score, '{:.1f}')}</dd>"
        f"<dt>Call Readiness</dt><dd>{_text(view.readiness.call_readiness)}</dd>"
        f"<dt>Eligibility</dt><dd>{_list_markup(view.eligibility.reasons)}</dd>"
        f"<dt>Blockers</dt><dd>{_list_markup(view.readiness.blockers)}</dd>"
        f"<dt>Next Trigger</dt><dd>{escape(view.readiness.next_trigger.description)}</dd>"
        f"<dt>Equity Refresh</dt><dd>{_timestamp(view.snapshot.scanned_at)}</dd></dl>"
        f"<ul class='readiness-checks'>{checks}</ul>"
        f"{entry_markup(view.snapshot.entry_plan, now=now)}"
    )


def _scan_details(
    result: OptionsScanResult, *, setup: _EquitySetupView | None, now: datetime,
) -> str:
    top = next(
        (item for item in result.accepted_candidates if item.status is OptionCandidateStatus.TOP_CANDIDATE),
        None,
    )
    contract_attention = "".join(
        f"<li><strong>{escape(item.contract.contract_symbol)}</strong>"
        f"<p>Quote Age / Feed: {_quote_age_cell(item.contract, result, now=now)}</p>"
        + _list_markup([
            *item.warnings, *item.contract.warnings,
            *item.confidence_penalties, *item.contract.data_quality_flags,
        ]) + "</li>"
        for item in result.accepted_candidates
    )
    return (
        "<h3>Recorded scan context</h3><dl class='facts'>"
        f"<dt>Equity State</dt><dd>{_text(result.equity_state)}</dd>"
        f"<dt>Tech Setup Score</dt><dd>{_num(result.equity_score, '{:.1f}')}</dd>"
        f"<dt>Options Score</dt><dd>{_num(top.options_quality_score, '{:.1f}') if top else '—'}</dd>"
        f"<dt>Top Combined Score</dt><dd>{_num(top.combined_score, '{:.1f}') if top else '—'}</dd>"
        f"<dt>Scanned At</dt><dd>{_timestamp(result.scanned_at)}</dd>"
        f"<dt>Equity Snapshot</dt><dd>{_timestamp(result.equity_snapshot_at)}</dd>"
        f"<dt>Feed</dt><dd>{_text(result.feed)}</dd>"
        f"<dt>Recorded Eligibility</dt><dd>{_text(result.eligibility.status)}"
        f"{_list_markup(result.eligibility.reasons)}</dd>"
        f"<dt>Warnings</dt><dd>{_list_markup([*result.warnings, *result.eligibility.warnings])}</dd>"
        "</dl>" + _status_note(result)
        + (f"<h3>Contract attention</h3><ul>{contract_attention}</ul>" if contract_attention else "")
        + (_equity_details(setup, now=now) if setup is not None else "")
    )


def _score_details(candidate: ScoredOptionCandidate) -> str:
    breakdown = candidate.breakdown
    component_rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{value:.2f} / 2.00</td></tr>"
        for label, value in (
            ("Delta fit", breakdown.delta_fit),
            ("DTE fit", breakdown.dte_fit),
            ("Liquidity", breakdown.liquidity),
            ("IV quality", breakdown.iv_quality),
            ("Moneyness", breakdown.moneyness),
        )
    )
    component_rows += (
        f"<tr><th>Total</th><td>{breakdown.total:.2f} / 10.00</td></tr>"
    )
    return (
        "<div class='candidate-detail'><h3>Score components, reasons "
        "&amp; warnings</h3>"
        f"<table class='mini'><tbody>{component_rows}</tbody></table>"
        f"<div><strong>Reasons</strong>{_list_markup(candidate.reasons)}</div>"
        f"<div><strong>Warnings</strong>{_list_markup(candidate.warnings)}</div>"
        f"<div><strong>Contract warnings</strong>{_list_markup(candidate.contract.warnings)}</div>"
        "<div><strong>Confidence penalties</strong>"
        f"{_list_markup(candidate.confidence_penalties)}</div>"
        "<div><strong>Data quality flags</strong>"
        f"{_list_markup(candidate.contract.data_quality_flags)}</div>"
        "</div>"
    )


def _candidate_rows(
    result: OptionsScanResult, *, now: datetime, stale_quote_minutes: float | None,
) -> str:
    rows = []
    for candidate in result.accepted_candidates:
        contract = candidate.contract
        is_top = candidate.status is OptionCandidateStatus.TOP_CANDIDATE
        status_label = "Top Candidate (configured fit)" if is_top else "Acceptable"
        facts = (
            "<dl class='facts'>"
            f"<dt>Expiration</dt><dd>{escape(contract.expiration.isoformat())}</dd>"
            f"<dt>Strike</dt><dd>{_money(contract.strike)}</dd>"
            f"<dt>DTE</dt><dd>{_text(contract.dte)}</dd>"
            f"<dt>Delta</dt><dd>{_num(contract.delta, '{:.3f}')}</dd>"
            f"<dt>Bid</dt><dd>{_money(contract.bid)}</dd>"
            f"<dt>Ask</dt><dd>{_money(contract.ask)}</dd>"
            f"<dt>Spread %</dt><dd>{_pct(contract.spread_pct)}</dd>"
            f"<dt>OI</dt><dd>{_text(contract.open_interest)}</dd>"
            f"<dt>Volume</dt><dd>{_text(contract.volume)}</dd>"
            f"<dt>IV</dt><dd>{_iv_cell(contract)}</dd>"
            f"<dt>Chain-Relative IV</dt><dd>{_relative_iv_cell(contract)}</dd>"
            f"<dt>Options Score</dt><dd>{_num(candidate.options_quality_score, '{:.1f}')}</dd>"
            f"<dt>Evidence/Data Confidence</dt><dd>{_pct(candidate.options_score_confidence)}</dd>"
            f"<dt>Combined Score</dt><dd>{_num(candidate.combined_score, '{:.1f}')}</dd>"
            f"<dt>Quote Age / Feed</dt><dd>{_quote_age_cell(contract, result, now=now)}</dd>"
            f"<dt>Quote Timestamp</dt><dd>{_timestamp(contract.quote_timestamp)}</dd>"
            f"<dt>Scan Warnings</dt><dd>{_list_markup([*result.warnings, *result.eligibility.warnings])}</dd>"
            "</dl>"
        )
        rows.append(
            f"<tr data-contract='{escape(contract.contract_symbol)}'>"
            f"<td class='contract-symbol'>{escape(contract.contract_symbol)}</td>"
            f"<td>{_signal(status_label, 'fit')}</td>"
            f"<td>{_attention_signals(result, now=now, stale_quote_minutes=stale_quote_minutes, candidate=candidate)}</td>"
            f"<td>{_explanation(facts + _score_details(candidate))}</td></tr>"
        )
    return "".join(rows)


def _rejected_row(contract: OptionContract) -> str:
    reasons = (
        ", ".join(escape(reason) for reason in contract.rejection_reasons) or "—"
    )
    return (
        "<tr>"
        f"<td>{escape(contract.contract_symbol)}</td>"
        f"<td>{escape(contract.expiration.isoformat())}</td>"
        f"<td>{_money(contract.strike)}</td>"
        f"<td>{_text(contract.filter_status)}</td>"
        f"<td>{reasons}</td>"
        "</tr>"
    )


def _rejected_section(result: OptionsScanResult) -> str:
    if not result.rejected_contracts and not result.stage_counts:
        return ""
    stage_rows = "".join(
        "<tr>"
        f"<td>{escape(stage.stage)}</td><td>{stage.evaluated}</td>"
        f"<td>{stage.passed}</td><td>{stage.rejected}</td></tr>"
        for stage in result.stage_counts
    ) or "<tr><td colspan='4' class='muted'>No stage counts recorded</td></tr>"
    rejected_rows = "".join(
        _rejected_row(contract) for contract in result.rejected_contracts
    ) or "<tr><td colspan='5' class='muted'>No rejected contracts</td></tr>"
    return (
        "<details class='rejected-detail'><summary>Rejected contracts &amp; "
        f"stage counts ({len(result.rejected_contracts)})</summary>"
        "<div class='table-wrap'><table class='mini'><thead><tr><th>Stage</th>"
        "<th>Evaluated</th><th>Passed</th><th>Rejected</th></tr></thead>"
        f"<tbody>{stage_rows}</tbody></table></div>"
        "<div class='table-wrap'><table><thead><tr><th>Contract</th>"
        "<th>Expiration</th><th>Strike</th><th>Filter status</th>"
        "<th>Rejection reasons</th></tr></thead>"
        f"<tbody>{rejected_rows}</tbody></table></div></details>"
    )


def _status_note(result: OptionsScanResult) -> str:
    if result.status is OptionsScanStatus.OPTIONS_DATA_UNAVAILABLE:
        message = result.error_message or (
            "The options data provider was unavailable for this scan."
        )
        return f"<div class='warning'>Options Data Unavailable: {escape(message)}</div>"
    if result.status is OptionsScanStatus.NO_SUITABLE_CONTRACT:
        return (
            "<div class='notice'>No Suitable Contract: no option contract in the chain passed the "
            "configured filters. Contract analysis does not grant equity entry qualification.</div>"
        )
    if result.status is OptionsScanStatus.NOT_ELIGIBLE:
        reasons = (
            ", ".join(escape(reason) for reason in result.eligibility.reasons)
            or "No reasons recorded"
        )
        return f"<div class='notice'>Not Eligible: {reasons}</div>"
    return ""


def _overview_row(
    result: OptionsScanResult, selected_ticker: str | None,
    *, now: datetime, stale_quote_minutes: float | None,
    setup: _EquitySetupView | None = None,
) -> str:
    current = (
        " class='current'"
        if selected_ticker and result.ticker == selected_ticker
        else ""
    )
    market_cells = render_market_cells(setup.snapshot.features) if setup is not None else ""
    return (
        f"<tr{current} data-signal-ticker='{escape(result.ticker)}'><td>{render_ticker_copy(result.ticker)} "
        f"<a class='ticker-view' href='/options?ticker={escape(result.ticker)}'>View</a></td>"
        f"{market_cells}"
        f"<td>{_context_signal(result, setup=setup, now=now, historical=setup is None)}</td>"
        f"<td>{readiness_lights(setup.readiness if setup is not None else None)}</td>"
        f"<td>{_scan_signal(result)}</td>"
        f"<td>{_attention_signals(result, now=now, stale_quote_minutes=stale_quote_minutes)}</td>"
        f"<td>{_explanation(_scan_details(result, setup=setup, now=now))}</td></tr>"
    )


def _near_qualification_row(view: _EquitySetupView, *, now: datetime) -> str:
    snapshot = view.snapshot
    return (
        f"<tr data-signal-ticker='{escape(snapshot.ticker)}'><td>{render_ticker_copy(snapshot.ticker)}</td>"
        f"{render_market_cells(snapshot.features)}"
        f"<td>{_entry_signal(view, now=now)}</td>"
        f"<td>{readiness_lights(view.readiness)}</td>"
        f"<td>{_eligibility_signal(view.eligibility)}</td>"
        f"<td>{_explanation(_equity_details(view, now=now))}</td></tr>"
    )


_CANDIDATE_HEADER = (
    "<tr><th>Contract</th><th>Configured Fit</th><th>Attention</th><th>Explanation</th></tr>"
)

_OVERVIEW_HEADER = (
    "<tr><th>Ticker</th><th>Context</th><th>Checks</th><th>Contract Fit</th>"
    "<th>Attention</th><th>Explanation</th></tr>"
)

_CURRENT_HEADER = (
    f"<tr><th>Ticker</th>{MARKET_HEADERS}<th>Context</th><th>Checks</th><th>Contract Fit</th>"
    "<th>Attention</th><th>Explanation</th></tr>"
)

_SETUP_HEADER = (
    f"<tr><th>Ticker</th>{MARKET_HEADERS}<th>New Entry</th><th>Checks</th>"
    "<th>Eligibility</th><th>Explanation</th></tr>"
)


def _detail_section(
    result: OptionsScanResult, *, setup: _EquitySetupView | None, now: datetime,
    stale_quote_minutes: float | None,
) -> str:
    candidate_rows = _candidate_rows(result, now=now, stale_quote_minutes=stale_quote_minutes)
    table = (
        f"<div class='table-wrap'><table class='candidates'>"
        f"<thead>{_CANDIDATE_HEADER}</thead><tbody>{candidate_rows}</tbody></table>"
        "</div>"
        if candidate_rows
        else "<p class='muted'>No accepted candidates for this scan.</p>"
    )
    return (
        f"<section class='card' id='selected-scan'><h2>{render_ticker_copy(result.ticker)} · Latest Scan</h2>"
        "<div class='signal-line'>"
        f"{_context_signal(result, setup=setup, now=now)}{_scan_signal(result)}"
        f"{_attention_signals(result, now=now, stale_quote_minutes=stale_quote_minutes)}</div>"
        "<div class='scan-checks'><strong>Current equity checks</strong>"
        f"{readiness_lights(setup.readiness if setup is not None else None)}</div>"
        f"{_explanation(_scan_details(result, setup=setup, now=now))}"
        f"{table}{_rejected_section(result)}"
        "</section>"
    )


def render_options_page(
    *,
    config: AppConfig | None,
    runtime_symbols: Mapping[str, RuntimeSymbol] | None = None,
    eligible_tickers: list[str],
    latest_results: list[OptionsScanResult],
    equity_snapshots: list[ScanSnapshot] | None = None,
    selected_history: list[OptionsScanResult] | None = None,
    selected_ticker: str | None = None,
    unavailable_message: str | None = None,
    equity_unavailable_message: str | None = None,
    rendered_at: datetime | None = None,
) -> str:
    now = _as_utc(rendered_at or datetime.now(UTC))
    stale_quote_minutes = config.strategy.options.long_call.stale_quote_minutes if config else None
    normalized_selection = (
        selected_ticker.strip().upper() if selected_ticker else None
    )
    history = selected_history or []
    setup_views = (
        _setup_views(
            config,
            eligible_tickers,
            equity_snapshots or [],
            runtime_symbols,
            as_of=now,
        )
        if config is not None
        else []
    )
    setups_by_ticker = {
        view.snapshot.ticker: view for view in setup_views
    }
    results_by_ticker = {result.ticker: result for result in latest_results}
    selected_result = (
        results_by_ticker.get(normalized_selection) if normalized_selection else None
    )
    ticker_options = "".join(
        "<option value='{ticker}'{selected}>{ticker}</option>".format(
            ticker=escape(ticker),
            selected=" selected" if ticker == normalized_selection else "",
        )
        for ticker in eligible_tickers
    )
    current_results = [
        result
        for result in latest_results
        if result.ticker in setups_by_ticker
        and _matches_current_equity(
            result,
            setups_by_ticker[result.ticker],
            now,
        )
    ]
    current_results.sort(
        key=lambda result: (
            0 if result.status is OptionsScanStatus.CANDIDATES_FOUND else 1,
            -max(
                (
                    candidate.combined_score
                    for candidate in result.accepted_candidates
                ),
                default=-1.0,
            ),
            result.ticker,
        )
    )
    current_rows = "".join(
        _overview_row(
            result, normalized_selection, now=now, stale_quote_minutes=stale_quote_minutes,
            setup=setups_by_ticker[result.ticker],
        )
        for result in current_results
    ) or (
        "<tr><td colspan='10' class='muted'>No fresh contract-fit results match "
        "the latest qualified equity context. Use Refresh Current Setups.</td></tr>"
    )
    research_views = sorted(
        (
            view
            for view in setup_views
            if view.eligibility.status is EligibilityStatus.RESEARCH_ELIGIBLE
        ),
        key=_near_sort_key,
    )
    research_rows = "".join(
        _near_qualification_row(view, now=now) for view in research_views
    ) or (
        "<tr><td colspan='9' class='muted'>No repair setups currently meet "
        "the contract pre-screen research gate.</td></tr>"
    )
    near_views = sorted(
        (view for view in setup_views if not view.eligibility.research_eligible),
        key=_near_sort_key,
    )[:NEAR_QUALIFICATION_LIMIT]
    near_rows = "".join(_near_qualification_row(view, now=now) for view in near_views) or (
        "<tr><td colspan='9' class='muted'>No near-qualification rows are "
        "available until equity snapshots exist.</td></tr>"
    )
    unavailable_parts = [
        message
        for message in (unavailable_message, equity_unavailable_message)
        if message
    ]
    unavailable = "".join(
        f"<div class='warning'>{escape(message)}</div>"
        for message in unavailable_parts
    )
    detail = (
        _detail_section(
            selected_result, setup=setups_by_ticker.get(selected_result.ticker),
            now=now, stale_quote_minutes=stale_quote_minutes,
        )
        if selected_result is not None
        else (
            f"<section class='card'><p class='muted'>No scan yet for "
            f"{escape(normalized_selection)}. Use Analyze Contract Fit above.</p>"
            "</section>"
            if normalized_selection
            else ""
        )
    )
    latest_history_rows = "".join(
        _overview_row(result, normalized_selection, now=now, stale_quote_minutes=stale_quote_minutes)
        for result in sorted(
            latest_results,
            key=lambda item: _as_utc(item.scanned_at),
            reverse=True,
        )
    ) or "<tr><td colspan='6' class='muted'>No scans recorded yet.</td></tr>"
    selected_history_rows = "".join(
        _overview_row(result, None, now=now, stale_quote_minutes=stale_quote_minutes) for result in history
    ) or "<tr><td colspan='6' class='muted'>No history recorded.</td></tr>"
    selected_history_section = (
        "<details class='card history-card'><summary>Selected Ticker History</summary>"
        f"<div class='table-wrap'><table class='signal-table'><thead>{_OVERVIEW_HEADER}</thead>"
        f"<tbody>{selected_history_rows}</tbody></table></div></details>"
        if normalized_selection
        else ""
    )
    update_times = [
        *[result.scanned_at for result in [*latest_results, *history]],
        *[view.snapshot.scanned_at for view in setup_views],
    ]
    latest_update = _timestamp(max(update_times)) if update_times else "—"
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Options Scanner · {PRODUCT_NAME}</title><style>"
        ":root{--blue:#0A66C2;--dark:#004182;--bg:#F3F2EF;--surface:#fff;"
        "--border:#ddd;--muted:#666;--red:#b42318;--green:#057642}"
        "*{box-sizing:border-box}body{margin:0;background:var(--bg);font:14px/1.45 "
        "-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#222}"
        "main{max-width:1360px;margin:auto;padding:24px}header{padding:24px 28px;"
        "border-radius:12px;background:linear-gradient(135deg,var(--blue),var(--dark));"
        "color:#fff}header h1{margin:0 0 5px}header p{margin:0;color:#dcecff}"
        ".header-top{display:flex;justify-content:space-between;gap:20px;align-items:start}"
        ".update-badge{white-space:nowrap;border:1px solid #ffffff55;border-radius:18px;"
        "padding:6px 10px;font-size:11px}"
        ".card,.notice,.warning{background:var(--surface);border-radius:10px;"
        "padding:18px;box-shadow:0 1px 3px #0002;margin:14px 0}"
        ".warning{background:#fff4e5;color:#684500;border-left:4px solid #e8a000;"
        "box-shadow:none}.notice{background:#eef6ff;border-left:4px solid var(--blue);"
        "box-shadow:none}.notice.disclosure{background:#fff8e6;border-left-color:#a06600;"
        "color:#5a4300}"
        ".section-head{display:flex;justify-content:space-between;gap:12px;"
        "align-items:center;flex-wrap:wrap}.section-head h2{margin:0}"
        ".eyebrow{font-size:11px;font-weight:700;text-transform:uppercase;"
        "letter-spacing:.08em;color:var(--blue)}"
        "label span,label select,label input{display:block;width:100%}"
        "input,select,button{font:inherit;padding:8px;border:1px solid #bbb;"
        "border-radius:6px}button{background:var(--blue);color:#fff;border:0;"
        "font-weight:700;cursor:pointer}button.secondary{background:#e8f0fd;"
        "color:var(--dark)}button:disabled{opacity:.45;cursor:not-allowed}"
        ".form-row{display:flex;gap:16px;align-items:end;flex-wrap:wrap;margin-top:14px}"
        ".form-row label{min-width:180px}.manual-toggle{display:flex;flex-direction:row;"
        "align-items:center;gap:8px;min-width:auto}.manual-toggle input{width:auto}"
        ".manual-warning{color:#8a5300;font-size:12px;max-width:320px}"
        ".result{white-space:pre-wrap;background:#172033;color:#e8f0fd;padding:12px;"
        "border-radius:7px;min-height:42px;margin-top:12px}.result.error{background:#5b1717}"
        ".table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%}"
        "th,td{text-align:left;border-bottom:1px solid #eee;padding:8px;"
        "vertical-align:top;white-space:normal}th{color:var(--muted)}"
        "table.candidates,table.signal-table{min-width:650px}table.mini{min-width:auto}"
        "table.signal-table[data-market-prices]{min-width:1150px}"
        ".signal-table>tbody>tr>td:first-child{white-space:nowrap}"
        ".contract-symbol{overflow-wrap:anywhere;max-width:240px}"
        "tr.current{background:#eef6ff}"
        ".signal{display:inline-block;padding:4px 9px;margin:2px 4px 2px 0;"
        "border-radius:999px;font-size:12px;font-weight:700;line-height:1.4}"
        ".signal-qualified{background:#dff5e8;color:#075f38}"
        ".signal-fit{background:#e5f0ff;color:#004182}"
        ".signal-research{background:#efe6fa;color:#69348b}"
        ".signal-developing{background:#fff1d8;color:#805000}"
        ".signal-blocked{background:#fde7e7;color:#a32119}"
        ".signal-not_ready{background:#edf0f4;color:#505966}"
        ".signal-line,.signal-legend{display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin:10px 0}"
        ".signal-legend .muted{margin-left:8px;font-size:12px}"
        ".explanation{min-width:110px}.explanation>summary{white-space:nowrap}"
        ".explanation[open]{min-width:330px;max-width:620px}"
        ".explanation>summary:focus-visible{outline:2px solid var(--blue);outline-offset:3px}"
        ".explanation h3{font-size:13px;margin:14px 0 6px}"
        ".facts{display:grid;grid-template-columns:minmax(120px,1fr) minmax(140px,2fr);"
        "gap:6px 12px;margin:12px 0;font-variant-numeric:tabular-nums}"
        ".facts dt{font-weight:600;color:var(--muted)}.facts dd{margin:0;overflow-wrap:anywhere}"
        ".facts ul,.readiness-checks{padding-left:18px;margin:4px 0}"
        ".readiness-checks li{margin:5px 0}.entry-plan{margin:14px 0}"
        "details summary{cursor:pointer;color:var(--blue);font-weight:700;margin:8px 0}"
        "details.history-card>summary{font-size:18px}.advanced{background:#fafafa;"
        "border:1px solid #e5e5e5;border-radius:8px;padding:8px 12px;max-width:520px}"
        ".advanced .manual-toggle{margin:8px 0}.workflow-copy{max-width:820px}"
        ".muted{color:var(--muted)}.footer{text-align:center;color:#777;margin:18px}"
        f"{glossary_styles()}{shared_page_styles()}{readiness_light_styles()}"
        "@media(max-width:800px){main{padding:12px}.header-top{display:block}"
        ".update-badge{display:inline-block;margin-top:12px}"
        ".form-row{flex-direction:column;align-items:stretch}"
        ".form-row label{min-width:0}}</style></head><body><div class='app-viewport'>"
        "<main class='app-shell'><div class='page-shell'>"
        "<header class='page-hero'><div class='header-top page-hero-top'><div>"
        f"<h1>{PRODUCT_NAME} · Options Scanner</h1>"
        "<p>Technical page. Reports configured contract fit for eligible equities "
        "only; no order, trade, or broker-position actions are available here.</p>"
        "</div><div class='update-badge'>Last update: "
        f"{latest_update}</div></div>{render_primary_nav('options')}</header>"
        f"{unavailable}"
        "<div class='signal-legend' aria-label='Signal color legend'>"
        f"{_signal('Entry qualified', 'qualified')}{_signal('Contract fit', 'fit')}"
        f"{_signal('Wait / caution', 'developing')}{_signal('Research only', 'research')}"
        f"{_signal('Blocked / error', 'blocked')}{_signal('Refresh / unavailable', 'not_ready')}"
        "<span class='muted'>Entry and contract fit are separate. Labels are analysis, not orders.</span></div>"
        "<details class='card options-guide'><summary>How to read these signals</summary>"
        f"{DISCLOSURE_NOTICE}"
        "<p>A current result must use the normal gate, match the latest equity state "
        "and score, have QUALIFIED shared call readiness with zero required blockers, "
        "and be no more than 30 minutes old. Research-only, manual, and stale scans "
        "never appear in Current Qualified Setups.</p>"
        "<p>Checks shows each equity gate as a green check or red cross. Hover, focus "
        "or tap a light for its PASS/FAIL evidence. These checks do not replace the "
        "separate overall qualification and contract-fit conclusions.</p></details>"
        "<section class='card control-plane'><div class='section-head'><div>"
        "<div class='eyebrow'>On-demand workflow · Automation off</div>"
        "<h2>Refresh Current Setups</h2></div>"
        "<button type='button' id='refresh-button'>Refresh Current Setups</button>"
        "</div><p class='workflow-copy'>This first refreshes the configured equity "
        "watchlist, then evaluates the latest leader setups. Option chains are fetched "
        "only for equities that currently pass the normal eligibility gate. Nothing "
        "runs or pushes alerts in the background.</p>"
        "<div id='scan-status' class='result' role='status'>No refresh run yet.</div>"
        "</section>"
        "<section class='card' id='current-setups'><div class='section-head'><h2>Current Qualified Setups</h2>"
        f"<span class='muted'>{len(current_results)} fresh result(s)</span></div>"
        "<p class='muted'>Fresh equity entry qualification; contract fit and warnings remain separate.</p>"
        f"<div class='table-wrap'><table class='signal-table' data-market-prices><thead>{_CURRENT_HEADER}</thead>"
        f"<tbody>{current_rows}</tbody></table></div></section>"
        "<section class='card' id='research-setups'><div class='section-head'>"
        "<h2>Contract Pre-Screen Eligible</h2>"
        f"<span class='muted'>{len(research_views)} research setup(s)</span></div>"
        "<p class='muted'>Strong technical setups without a qualified entry may inspect "
        "contracts for research only. They are not part of Current Qualified Setups.</p>"
        f"<div class='table-wrap'><table class='signal-table' data-market-prices><thead>{_SETUP_HEADER}</thead>"
        f"<tbody>{research_rows}</tbody></table></div></section>"
        "<section class='card' id='near-setups'><div class='section-head'><h2>Near Qualification</h2>"
        f"<span class='muted'>Top {NEAR_QUALIFICATION_LIMIT} by setup proximity</span>"
        "</div><p class='muted'>These leader equities do not currently qualify for an "
        "option-chain fetch. Open Explanation for blockers and the next trigger.</p>"
        f"<div class='table-wrap'><table class='signal-table' data-market-prices><thead>{_SETUP_HEADER}"
        f"</thead><tbody>{near_rows}</tbody></table></div>"
        "</section>"
        "<section class='card'><div class='eyebrow'>Separate research path</div>"
        "<h2>Manual Research</h2><p class='muted'>Choose a configured leader ticker "
        "to inspect contract fit on demand. This does not make it a current qualified "
        "setup, and the page intentionally starts with no ticker selected.</p>"
        "<div class='form-row'>"
        "<label>Ticker<select id='ticker-select'><option value=''>Select a ticker…"
        f"</option>{ticker_options}</select></label>"
        "<button type='button' id='analyze-button' class='secondary'>"
        "Analyze Selected Ticker</button></div>"
        "<details class='advanced'><summary>Advanced: Manual Override</summary>"
        "<label class='manual-toggle'><input type='checkbox' id='manual-override'>"
        "<span>Bypass entry/state/score gates for this research scan only</span></label>"
        f"<div class='manual-warning'>{escape(MANUAL_OVERRIDE_WARNING)}</div></details>"
        "</section>"
        f"{detail}"
        "<details class='card history-card'><summary>Recent Scan History "
        f"({len(latest_results)} ticker(s))</summary>"
        "<p class='muted'>Persisted normal and manual results remain here for audit. "
        "A ticker appearing in history does not mean it currently qualifies.</p>"
        f"<div class='table-wrap'><table class='signal-table'><thead>{_OVERVIEW_HEADER}"
        f"</thead><tbody>{latest_history_rows}</tbody></table>"
        f"</div></details>{selected_history_section}"
        "<p class='footer'>Local analysis only · No orders · No trading · "
        "No broker-position actions</p>"
        f"{render_glossary()}</div></main></div><script>"
        "const analyzeButton=document.getElementById('analyze-button');"
        "const refreshButton=document.getElementById('refresh-button');"
        "const manualOverride=document.getElementById('manual-override');"
        "const tickerSelect=document.getElementById('ticker-select');"
        "const scanStatus=document.getElementById('scan-status');"
        "let scanInFlight=false;"
        "function setBusy(busy){scanInFlight=busy;analyzeButton.disabled=busy;"
        "refreshButton.disabled=busy;}"
        "function showStatus(message,error=false){"
        "scanStatus.className=`result${error?' error':''}`;"
        "scanStatus.textContent=message;}"
        "async function postScan(url,payload){"
        "const options={method:'POST'};"
        "if(payload!==null){options.headers={'Content-Type':'application/json'};"
        "options.body=JSON.stringify(payload);}"
        "const response=await fetch(url,options);"
        "const raw=await response.text();let data=null;"
        "try{data=raw?JSON.parse(raw):null;}catch(parseError){data=null;}"
        "if(!response.ok&&!(data&&data.status==='OPTIONS_DATA_UNAVAILABLE')){"
        "const message=data&&typeof data.detail==='string'?"
        "data.detail:(raw.trim()||`HTTP ${response.status}`);"
        "const error=new Error(message);error.responseStatus=response.status;"
        "error.responseData=data;throw error;}return data;}"
        "if(analyzeButton){analyzeButton.addEventListener('click',async()=>{"
        "if(scanInFlight)return;const ticker=tickerSelect?tickerSelect.value:'';"
        "if(!ticker){showStatus('Select a ticker first.',true);return;}"
        "const override=manualOverride&&manualOverride.checked;"
        "if(override&&!confirm(`Manual Override permits research despite entry, state "
        "or score blockers for ${ticker}. It never grants execution qualification. "
        "Contract filtering and scoring are unchanged. Continue?`)){return;}"
        "setBusy(true);showStatus(`Analyzing ${ticker}…`);"
        "try{const data=await postScan(`/options/scan/${encodeURIComponent(ticker)}`,"
        "{manual_override:override});"
        "showStatus(data&&data.status==='OPTIONS_DATA_UNAVAILABLE'?"
        "'Options data unavailable. Refreshing persisted result…':"
        "'Scan complete. Refreshing…',"
        "Boolean(data&&data.status==='OPTIONS_DATA_UNAVAILABLE'));"
        "window.location.assign(`/options?ticker=${encodeURIComponent(ticker)}`);"
        "}catch(error){showStatus(`Analyze failed: ${error.message}`,true);"
        "setBusy(false);}});}"
        "if(refreshButton){refreshButton.addEventListener('click',async()=>{"
        "if(scanInFlight)return;setBusy(true);"
        "showStatus('Step 1 of 2: refreshing equity snapshots…');"
        "try{const equities=await postScan('/scan',null);"
        "showStatus('Step 2 of 2: evaluating qualified setups and contract fit…');"
        "const options=await postScan('/options/scan/qualified',{});"
        "const equityCount=Array.isArray(equities)?equities.length:0;"
        "const optionResults=Array.isArray(options)?options:[];"
        "const candidateSetups=optionResults.filter(item=>"
        "item.status==='CANDIDATES_FOUND').length;"
        "const candidateContracts=optionResults.reduce((total,item)=>"
        "total+(Array.isArray(item.accepted_candidates)?"
        "item.accepted_candidates.length:0),0);"
        "const summary=`Refreshed ${equityCount} equities · "
        "${optionResults.length} qualified setup(s) analyzed · "
        "${candidateSetups} setup(s) with ${candidateContracts} contract candidate(s).`;"
        "sessionStorage.setItem('nanzone-options-refresh-summary',summary);"
        "showStatus(`${summary} Reloading current view…`);"
        "window.location.assign('/options');"
        "}catch(error){const partial=error.responseData&&"
        "Array.isArray(error.responseData.results)?error.responseData.results:null;"
        "if(error.responseStatus===503&&partial){"
        "const failed=Array.isArray(error.responseData.failed_tickers)?"
        "error.responseData.failed_tickers.length:0;"
        "const summary=`Equities refreshed; ${partial.length} qualified setup(s) "
        "completed and ${failed} ticker(s) had provider errors. Persisted results "
        "will be shown.`;sessionStorage.setItem("
        "'nanzone-options-refresh-summary',summary);"
        "window.location.assign('/options');return;}"
        "showStatus(`Refresh failed: ${error.message}`,true);"
        "setBusy(false);}});}"
        "if(tickerSelect){tickerSelect.addEventListener('change',()=>{"
        "if(tickerSelect.value){window.location.assign("
        "`/options?ticker=${encodeURIComponent(tickerSelect.value)}`);}});}"
        "const savedSummary=sessionStorage.getItem("
        "'nanzone-options-refresh-summary');"
        "if(savedSummary){sessionStorage.removeItem("
        "'nanzone-options-refresh-summary');showStatus(savedSummary);}"
        f"{glossary_script()}"
        f"</script><script>{readiness_light_script()}"
        "</script></body></html>"
    )
