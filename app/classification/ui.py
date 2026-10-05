from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape

from app.classification.models import (
    ClassificationAuditEvent,
    ClassificationProposal,
    EvidenceCategory,
    PortfolioRole,
    ProposalStatus,
    RiskTier,
    TickerProfile,
    TickerProfileHistory,
)
from app.ui import (
    PRODUCT_NAME,
    format_timestamp_et,
    glossary_script,
    glossary_styles,
    render_glossary,
    render_primary_nav,
    render_ticker_copy,
    shared_page_styles,
)


SCORING_CATEGORIES = tuple(
    category
    for category in EvidenceCategory
    if category is not EvidenceCategory.TECHNICAL_CONTEXT
)

NEGATIVE_CODES = {
    "REVENUE_VISIBILITY_WEAK",
    "CUSTOMER_CONCENTRATION_HIGH",
    "FINANCING_RISK_HIGH",
    "VOLATILITY_ELEVATED",
    "BUSINESS_MATURITY_EMERGING",
    "DILUTION_RISK_HIGH",
    "CASH_BURN_HIGH",
    "GUIDANCE_VISIBILITY_LOW",
    "EVENT_DEPENDENCE_HIGH",
    "BUSINESS_QUALITY_WEAK",
    "FINANCIAL_STABILITY_WEAK",
    "THESIS_STABILITY_WEAK",
}


def _text(value: object | None, unavailable: str = "—") -> str:
    if value is None:
        return unavailable
    return escape(str(getattr(value, "value", value)))


def _timestamp(value: datetime | None) -> str:
    return escape(format_timestamp_et(value))


def _profile_value(profile: TickerProfile, field: str) -> str:
    value = getattr(profile, field)
    if isinstance(value, tuple):
        return ", ".join(str(getattr(item, "value", item)) for item in value) or "None"
    return str(getattr(value, "value", value))


def _impact_rows(proposal: ClassificationProposal) -> str:
    fields = (
        ("Primary role", "primary_role"),
        ("Risk tier", "risk_tier"),
        ("Groups", "groups"),
        ("Strategy tags", "strategy_tags"),
        ("Benchmark tags", "benchmark_tags"),
        ("Company quality", "company_quality"),
    )
    rows = []
    for label, field in fields:
        before = _profile_value(proposal.current_profile_snapshot, field)
        after = _profile_value(proposal.suggested_profile_snapshot, field)
        change = (
            f"{escape(before)} → {escape(after)}"
            if before != after
            else f"{escape(before)} <span class='unchanged'>(unchanged)</span>"
        )
        rows.append(f"<tr><th>{escape(label)}</th><td>{change}</td></tr>")
    return "".join(rows)


def _evidence_rows(proposal: ClassificationProposal) -> str:
    evidence = {item.category: item for item in proposal.evidence_summary}
    rows = []
    for category in SCORING_CATEGORIES:
        item = evidence.get(category)
        score = _text(f"{item.score:.1f}" if item and item.score is not None else None)
        quality = _text(item.data_quality if item else None, "UNAVAILABLE")
        confidence = (
            f"{item.confidence:.0%}" if item and item.score is not None else "—"
        )
        source = _text(item.source if item else None, "No evidence supplied")
        rows.append(
            "<tr>"
            f"<td><code>{escape(category.value)}</code></td>"
            f"<td>{score}</td><td>{quality}</td>"
            f"<td>{escape(confidence)}</td><td>{source}</td></tr>"
        )
    return "".join(rows)


def _reason_lists(proposal: ClassificationProposal) -> str:
    positive: list[str] = []
    negative: list[str] = []
    for code in proposal.reason_codes:
        target = negative if code.value in NEGATIVE_CODES else positive
        target.append(code.value)
    render = lambda values: (
        "".join(f"<li><code>{escape(value)}</code></li>" for value in values)
        or "<li class='muted'>None supplied</li>"
    )
    return (
        "<div><strong>Positive reason codes</strong><ul>"
        f"{render(positive)}</ul></div>"
        "<div><strong>Negative reason codes</strong><ul>"
        f"{render(negative)}</ul></div>"
    )


def _technical_context(proposal: ClassificationProposal, snapshots) -> str:
    if snapshots is None:
        return "Unavailable"
    snapshot = snapshots.latest(proposal.ticker)
    if snapshot is None:
        return "No saved technical snapshot"
    return (
        f"{escape(snapshot.current_state.value)} · "
        f"Tech Setup Score {snapshot.ceg_tech_score:.1f} · "
        f"{escape(snapshot.displayed_at_et)}"
    )


def _proposal_card(
    proposal: ClassificationProposal, snapshots, now: datetime
) -> str:
    actionable = (
        proposal.review_status is ProposalStatus.PENDING
        and (proposal.expires_at is None or proposal.expires_at > now)
    )
    disabled = "" if actionable else " disabled"
    scores = "".join(
        f"<li>{escape(item.role.value)}: "
        f"{'—' if item.score is None else f'{item.score:.2f}'}</li>"
        for item in proposal.candidate_role_scores
    )
    dates = (
        f"Expires: {_timestamp(proposal.expires_at)} · "
        f"Cooldown: {_timestamp(proposal.cooldown_until)} · "
        f"Snooze: {_timestamp(proposal.snooze_until)}"
    )
    return (
        f"<article class='proposal' id='proposal-{proposal.id}'>"
        "<div class='proposal-head'><div>"
        f"<h3>{render_ticker_copy(proposal.ticker)} · "
        f"{escape(proposal.proposal_type.value)}</h3>"
        f"<span class='status status-{proposal.review_status.value.lower()}'>"
        f"{escape(proposal.review_status.value)}</span></div>"
        f"<div class='metric'><strong>{proposal.confidence:.0%}</strong>"
        "<span>Evidence Confidence</span></div>"
        f"<div class='metric'><strong>{_text(f'{proposal.data_completeness:.0%}' if proposal.data_completeness is not None else None)}</strong>"
        "<span>Data Completeness</span></div></div>"
        "<div class='proposal-grid'><section><h4>Score comparison</h4>"
        f"<p>Score delta: <strong>{proposal.score_delta:.2f}</strong> · "
        f"Current score: {_text(f'{proposal.current_role_score:.2f}' if proposal.current_role_score is not None else None)}</p>"
        f"<ul>{scores or '<li class=\"muted\">No role scores stored</li>'}</ul>"
        "</section><section><h4>Exact impact preview</h4>"
        f"<table class='impact'>{_impact_rows(proposal)}</table></section></div>"
        "<details><summary>Evidence and reason codes</summary>"
        f"<div class='reason-grid'>{_reason_lists(proposal)}</div>"
        "<div class='table-wrap'><table><thead><tr><th>Category</th><th>Score</th>"
        "<th>Quality</th><th>Confidence</th><th>Source</th></tr></thead>"
        f"<tbody>{_evidence_rows(proposal)}</tbody></table></div></details>"
        "<div class='technical'><strong>Short-Term Technical Context — informational only</strong>"
        f"<span>{_technical_context(proposal, snapshots)}</span>"
        "<small>Excluded from role scoring and proposal evaluation.</small></div>"
        f"<p class='dates'>{dates}</p>"
        f"<div class='actions' data-proposal='{proposal.id}'>"
        f"<button data-action='accept'{disabled}>ACCEPT</button>"
        f"<button data-action='reject' class='secondary'{disabled}>KEEP CURRENT</button>"
        f"<button data-action='snooze7' class='secondary'{disabled}>SNOOZE 7 DAYS</button>"
        f"<button data-action='snooze30' class='secondary'{disabled}>SNOOZE 30 DAYS</button>"
        f"<button data-action='snoozeManual' class='secondary'{disabled}>SNOOZE TO DATE</button>"
        "</div></article>"
    )


def _profile_row(profile: TickerProfile) -> str:
    options = "".join(
        f"<option value='{role.value}'"
        f"{' selected' if role is profile.primary_role else ''}>{role.value}</option>"
        for role in PortfolioRole
    )
    risk_options = "".join(
        f"<option value='{risk.value}'"
        f"{' selected' if risk is profile.risk_tier else ''}>{risk.value}</option>"
        for risk in RiskTier
    )
    groups = ",".join(item.value for item in profile.groups)
    tags = ",".join(profile.strategy_tags)
    benchmarks = ",".join(profile.benchmark_tags)
    target_weight = "" if profile.target_weight is None else str(profile.target_weight)
    max_weight = "" if profile.max_weight is None else str(profile.max_weight)
    return (
        f"<tr><td>{render_ticker_copy(profile.ticker)}<br>"
        f"<small>{_text(profile.company_id)} / {_text(profile.exposure_group)}</small></td>"
        f"<td>{escape(profile.primary_role.value)}</td><td>{escape(profile.risk_tier.value)}</td>"
        f"<td>{escape(groups or 'None')}</td><td>{profile.version}</td>"
        f"<td>{escape(profile.confirmed_by)}<br><small>{_timestamp(profile.confirmed_at)}</small></td>"
        "<td><details><summary>Manual edit</summary>"
        f"<form class='profile-form' data-ticker='{escape(profile.ticker)}' data-version='{profile.version}'>"
        f"<label>Role<select name='primary_role'>{options}</select></label>"
        f"<label>Risk<select name='risk_tier'>{risk_options}</select></label>"
        f"<label>Groups CSV<input name='groups' value='{escape(groups, quote=True)}'></label>"
        f"<label>Strategy tags CSV<input name='strategy_tags' value='{escape(tags, quote=True)}'></label>"
        f"<label>Benchmark tags CSV<input name='benchmark_tags' value='{escape(benchmarks, quote=True)}'></label>"
        f"<label>Company quality<input type='number' min='0' max='2' step='.1' name='company_quality' value='{profile.company_quality}'></label>"
        f"<label>Company ID<input name='company_id' value='{escape(profile.company_id or '', quote=True)}'></label>"
        f"<label>Exposure group<input name='exposure_group' value='{escape(profile.exposure_group or '', quote=True)}'></label>"
        f"<label>Target weight<input type='number' min='0' max='1' step='.01' name='target_weight' value='{escape(target_weight, quote=True)}'></label>"
        f"<label>Max weight<input type='number' min='0' max='1' step='.01' name='max_weight' value='{escape(max_weight, quote=True)}'></label>"
        "<label>Actor<input name='actor' required></label>"
        "<label>Decision reason<input name='reason' required></label>"
        "<button type='submit'>Save confirmed profile</button>"
        "<small>Changes the confirmed DB profile used by the next dashboard, "
        "equity scan, and options evaluation.</small>"
        "</form></details></td></tr>"
    )


def _history_markup(
    history: list[TickerProfileHistory],
    audit: list[ClassificationAuditEvent],
) -> str:
    history_items = "".join(
        "<li>"
        f"{render_ticker_copy(item.ticker)} v{item.profile_version} · "
        f"{escape(item.decision_source.value)} · {_timestamp(item.effective_from)}"
        "</li>"
        for item in reversed(history[-30:])
    )
    audit_items = "".join(
        "<li>"
        f"{render_ticker_copy(item.ticker)} · "
        f"{escape(item.decision_source.value)} · {escape(item.actor)} · "
        f"{escape(item.reason)} · {_timestamp(item.occurred_at)}"
        "</li>"
        for item in reversed(audit[-30:])
    )
    return (
        "<div class='history-grid'><section><h3>Confirmed profile history</h3><ul>"
        f"{history_items or '<li class=\"muted\">No profile history</li>'}</ul></section>"
        "<section><h3>Decision audit</h3><ul>"
        f"{audit_items or '<li class=\"muted\">No decisions recorded</li>'}</ul></section></div>"
    )


def render_classification_page(
    *,
    profiles: list[TickerProfile],
    proposals: list[ClassificationProposal],
    history: list[TickerProfileHistory],
    audit: list[ClassificationAuditEvent],
    snapshots=None,
    unavailable_message: str | None = None,
) -> str:
    now = datetime.now(UTC)
    recent = now - timedelta(days=30)
    counts = {
        "Pending Reviews": sum(
            item.review_status is ProposalStatus.PENDING for item in proposals
        ),
        "Accepted Recently": sum(
            item.review_status is ProposalStatus.ACCEPTED
            and item.reviewed_at is not None
            and item.reviewed_at >= recent
            for item in proposals
        ),
        "Rejected Recently": sum(
            item.review_status is ProposalStatus.REJECTED
            and item.reviewed_at is not None
            and item.reviewed_at >= recent
            for item in proposals
        ),
        "Snoozed": sum(
            item.review_status is ProposalStatus.SNOOZED for item in proposals
        ),
        "Profiles": len(profiles),
    }
    summary = "".join(
        f"<div class='summary'><strong>{value}</strong><span>{escape(label)}</span></div>"
        for label, value in counts.items()
    )
    ticker_options = "".join(
        f"<option value='{escape(profile.ticker)}'>{escape(profile.ticker)} · "
        f"{escape(profile.primary_role.value)}</option>"
        for profile in profiles
    )
    evidence_inputs = "".join(
        "<label>"
        f"<span>{escape(label)}</span><small>{escape(help_text)}</small>"
        f"<input type='number' min='0' max='10' step='.1' data-category='{category.value}' placeholder='blank = unavailable'>"
        "</label>"
        for category, label, help_text in (
            (EvidenceCategory.BUSINESS_QUALITY, "Business Quality", "10 = durable, favorable"),
            (EvidenceCategory.FINANCIAL_STABILITY, "Financial Stability", "10 = stable, resilient"),
            (EvidenceCategory.REVENUE_VISIBILITY, "Revenue Visibility", "10 = highly visible"),
            (EvidenceCategory.VOLATILITY_REGIME, "Volatility Regime", "10 = stable / low volatility"),
            (EvidenceCategory.CUSTOMER_CONCENTRATION, "Customer Concentration", "10 = diversified / low concentration"),
            (EvidenceCategory.EVENT_DEPENDENCE, "Event Dependence", "10 = low dependence"),
        )
    )
    proposal_cards = "".join(
        _proposal_card(item, snapshots, now) for item in proposals
    )
    profile_rows = "".join(_profile_row(item) for item in profiles)
    unavailable = (
        f"<div class='warning'>{escape(unavailable_message)}</div>"
        if unavailable_message
        else ""
    )
    update_times = (
        [item.confirmed_at for item in profiles]
        + [item.reviewed_at or item.created_at for item in proposals]
        + [item.effective_from for item in history]
        + [item.occurred_at for item in audit]
    )
    latest_update = _timestamp(max(update_times)) if update_times else "—"
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Classification Review · {PRODUCT_NAME}</title><style>"
        ":root{--blue:#0A66C2;--dark:#004182;--bg:#F3F2EF;--surface:#fff;"
        "--border:#ddd;--muted:#666;--red:#b42318;--green:#057642}"
        "*{box-sizing:border-box}body{margin:0;background:var(--bg);font:14px/1.45 "
        "-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#222}"
        "main{max-width:1360px;margin:auto;padding:24px}header{padding:24px 28px;"
        "border-radius:12px;background:linear-gradient(135deg,var(--blue),var(--dark));"
        "color:#fff}header h1{margin:0 0 5px}header p{margin:0;color:#dcecff}"
        ".header-top{display:flex;justify-content:space-between;gap:20px;align-items:start}"
        ".update-badge{white-space:nowrap;border:1px solid #ffffff55;border-radius:18px;"
        "padding:6px 10px;font-size:11px}.summary-grid,.evidence-grid,.proposal-grid,.history-grid{"
        "display:grid;gap:12px}.summary-grid{grid-template-columns:repeat(5,1fr);margin:16px 0}"
        ".summary,.card,.proposal{background:var(--surface);border-radius:10px;padding:18px;"
        "box-shadow:0 1px 3px #0002}.summary strong,.summary span{display:block}"
        ".summary strong{font-size:26px;color:var(--blue)}.summary span{color:var(--muted)}"
        ".card,.proposal{margin:14px 0}.warning{background:#fff4e5;color:#684500;"
        "border-left:4px solid #e8a000;padding:12px;margin-top:14px}.notice{background:#eef6ff;"
        "border-left:4px solid var(--blue);padding:12px;margin:12px 0}.evidence-grid{"
        "grid-template-columns:repeat(3,1fr)}label span,label small,label input,label select{"
        "display:block;width:100%}label small{color:var(--muted);min-height:20px}"
        "input,select,button{font:inherit;padding:8px;border:1px solid #bbb;border-radius:6px}"
        "button{background:var(--blue);color:#fff;border:0;font-weight:700;cursor:pointer}"
        "button.secondary{background:#e8f0fd;color:var(--dark)}button:disabled{opacity:.45;"
        "cursor:not-allowed}.form-row,.actions,.proposal-head{display:flex;gap:10px;"
        "align-items:end;flex-wrap:wrap}.form-row{margin-top:14px}.form-row label{min-width:170px}"
        ".result{white-space:pre-wrap;background:#172033;color:#e8f0fd;padding:12px;"
        "border-radius:7px;min-height:42px;margin-top:12px}.result.error{background:#5b1717}"
        ".proposal-head{justify-content:space-between;align-items:start}.proposal h3{margin:0}"
        ".metric{text-align:right}.metric strong,.metric span{display:block}.metric strong{"
        "font-size:20px;color:var(--blue)}.metric span{font-size:11px;color:var(--muted)}"
        ".status{display:inline-block;margin-top:5px;padding:3px 8px;border-radius:12px;"
        "background:#eee;font-size:11px;font-weight:700}.status-pending{background:#fff4cf}"
        ".status-accepted{background:#dff5e8;color:var(--green)}.status-rejected{"
        "background:#fee4e2;color:var(--red)}.proposal-grid,.history-grid{"
        "grid-template-columns:1fr 1fr}.proposal section{border:1px solid #eee;"
        "border-radius:8px;padding:12px}.proposal h4{margin:0 0 8px}.reason-grid{"
        "display:grid;grid-template-columns:1fr 1fr}.technical{background:#f7f9fb;"
        "padding:10px;margin:12px 0}.technical span,.technical small{display:block}"
        ".technical small,.dates,.muted,.unchanged{color:var(--muted)}.table-wrap{"
        "overflow-x:auto}table{border-collapse:collapse;width:100%}th,td{text-align:left;"
        "border-bottom:1px solid #eee;padding:8px;vertical-align:top}th{color:var(--muted)}"
        ".impact th{width:150px}.profile-form{min-width:320px;display:grid;gap:8px;padding:10px}"
        ".profiles{min-width:1100px}details summary{cursor:pointer;color:var(--blue);font-weight:700}"
        "code{font-size:11px}.footer{text-align:center;color:#777;margin:18px}"
        f"{glossary_styles()}{shared_page_styles()}"
        "@media(max-width:800px){.summary-grid{grid-template-columns:repeat(2,1fr)}"
        ".evidence-grid,.proposal-grid,.history-grid{grid-template-columns:1fr}main{padding:12px}"
        ".header-top{display:block}.update-badge{display:inline-block;margin-top:12px}}</style>"
        "</head><body><div class='app-viewport'><main class='app-shell'>"
        "<div class='page-shell'><header class='page-hero'>"
        "<div class='header-top page-hero-top'><div>"
        f"<h1>{PRODUCT_NAME} · Classification Review Center</h1><p>Explicit evidence, "
        "deterministic proposals, and user-controlled confirmed profiles.</p></div>"
        f"<div class='update-badge'>Last update: {latest_update}</div></div>"
        f"{render_primary_nav('classification')}</header>"
        f"{unavailable}<section class='summary-grid'>{summary}</section>"
        "<div class='notice'><strong>Evidence semantics:</strong> every score uses "
        "0 = unfavorable / high risk and 10 = favorable / resilient / low risk. "
        "<strong>Evidence Confidence</strong> is evidence quality, not probability. "
        "Manual values are user-supplied and are not verified external data. Technical "
        "state is informational only and never affects classification. No change is automatic.</div>"
        "<section class='card control-plane'><h2>Manual Evidence Review</h2>"
        "<p>Blank scores are stored as UNAVAILABLE, never zero. Submit two consistent "
        "qualifying cycles to satisfy hysteresis.</p><form id='review-form'>"
        f"<div class='evidence-grid'>{evidence_inputs}</div><div class='form-row'>"
        f"<label>Ticker<select id='review-ticker'>{ticker_options}</select></label>"
        "<label>Evidence confidence<input id='review-confidence' type='number' min='0' "
        "max='1' step='.05' value='.8'></label><label>Data quality<select id='review-quality'>"
        "<option>AVAILABLE</option><option>PARTIAL</option></select></label>"
        "<button type='submit'>Run Manual Review</button></div></form>"
        "<div id='review-result' class='result' role='status'>No review submitted.</div></section>"
        "<section><h2>Review Proposals</h2>"
        f"{proposal_cards or '<div class=\"card muted\">No proposals. Use the manual evidence form; confirmed profiles remain unchanged.</div>'}"
        "</section><section class='card'><h2>Confirmed Profiles</h2>"
        "<div class='notice'>DB profiles are the classification source of truth. Manual "
        "edits and accepted proposals update the confirmed profile used by the "
        "next dashboard, equity scan, and options evaluation.</div>"
        "<div class='table-wrap'><table class='profiles'><thead><tr><th>Ticker / exposure</th>"
        "<th>Role</th><th>Risk</th><th>Groups</th><th>Version</th><th>Confirmed</th>"
        f"<th>Edit</th></tr></thead><tbody>{profile_rows}</tbody></table></div></section>"
        f"<section class='card'><h2>History and Audit</h2>{_history_markup(history, audit)}</section>"
        "<p class='footer'>Local analysis only · No trading · No automatic classification changes</p>"
        f"{render_glossary()}</div></main></div><script>"
        "const result=document.getElementById('review-result');"
        "async function api(url,options){const response=await fetch(url,options);"
        "const raw=await response.text();let data=null;try{data=raw?JSON.parse(raw):null;}catch(e){}"
        "if(!response.ok){throw new Error(data&&data.detail?String(data.detail):(raw.trim()||`HTTP ${response.status}`));}"
        "return data;}"
        "function show(message,error=false){result.className=`result${error?' error':''}`;"
        "result.textContent=typeof message==='string'?message:JSON.stringify(message,null,2);}"
        "document.getElementById('review-form').addEventListener('submit',async event=>{"
        "event.preventDefault();const ticker=document.getElementById('review-ticker').value;"
        "const confidence=Number(document.getElementById('review-confidence').value);"
        "const quality=document.getElementById('review-quality').value;"
        "const evidence=[...event.target.querySelectorAll('[data-category]')].map(input=>({"
        "category:input.dataset.category,score:input.value===''?null:Number(input.value),"
        "confidence,data_quality:input.value===''?'UNAVAILABLE':quality}));"
        "try{const data=await api(`/classification/review/${encodeURIComponent(ticker)}`,{"
        "method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({"
        "review_mode:'MANUAL',evidence})});show({status:data.status,"
        "candidate_scores:data.role_scores,data_completeness:data.data_completeness,"
        "evidence_confidence:data.evidence_confidence,"
        "consecutive_cycle_count:data.consecutive_win_count,proposal_id:data.proposal_id});"
        "}catch(error){show(`Review failed: ${error.message}`,true);}});"
        "document.querySelectorAll('.actions button').forEach(button=>button.addEventListener('click',async()=>{"
        "const box=button.closest('.actions');const id=box.dataset.proposal;"
        "const action=button.dataset.action;const actor=prompt('Actor / reviewed by (required)');"
        "if(!actor||!actor.trim())return;let endpoint=action;let payload={actor:actor.trim()};"
        "if(action==='accept'){if(!confirm('ACCEPT will update only the exact confirmed DB profile fields shown in the impact preview, create one new version, and affect the next dashboard, equity scan, and options evaluation. Continue?'))return;"
        "}else if(action==='reject'){endpoint='reject';payload.reason=prompt('Optional reason','Keep current classification')||'Keep current classification';"
        "}else{endpoint='snooze';payload.reason='User snoozed classification review';let until;"
        "if(action==='snooze7'||action==='snooze30'){until=new Date(Date.now()+Number(action==='snooze7'?7:30)*86400000);}"
        "else{const entered=prompt('Snooze until date (YYYY-MM-DD). Earnings dates are unavailable.');"
        "if(!entered)return;until=new Date(`${entered}T23:59:59Z`);}if(Number.isNaN(until.getTime())){show('Invalid snooze date',true);return;}"
        "payload.snooze_until=until.toISOString();}"
        "try{await api(`/classification/proposals/${id}/${endpoint}`,{method:'POST',headers:{"
        "'Content-Type':'application/json'},body:JSON.stringify(payload)});"
        "show('Decision saved. Refreshing…');window.location.reload();"
        "}catch(error){show(`Decision failed: ${error.message}`,true);}}));"
        "document.querySelectorAll('.profile-form').forEach(form=>form.addEventListener('submit',async event=>{"
        "event.preventDefault();const data=new FormData(form);const csv=name=>String(data.get(name)||'')"
        ".split(',').map(value=>value.trim()).filter(Boolean);const nullableNumber=name=>"
        "String(data.get(name)||'').trim()===''?null:Number(data.get(name));"
        "const nullableText=name=>String(data.get(name)||'').trim()||null;"
        "const payload={actor:String(data.get('actor')||''),"
        "reason:String(data.get('reason')||''),expected_version:Number(form.dataset.version),"
        "primary_role:data.get('primary_role'),risk_tier:data.get('risk_tier'),groups:csv('groups'),"
        "strategy_tags:csv('strategy_tags'),benchmark_tags:csv('benchmark_tags'),"
        "company_quality:Number(data.get('company_quality')),company_id:nullableText('company_id'),"
        "exposure_group:nullableText('exposure_group'),target_weight:nullableNumber('target_weight'),"
        "max_weight:nullableNumber('max_weight')};"
        "if(!confirm('This changes the confirmed DB profile, creates an audited version, and affects the next dashboard, equity scan, and options evaluation. Continue?'))return;"
        "try{await api(`/profiles/${encodeURIComponent(form.dataset.ticker)}`,{method:'PUT',"
        "headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});"
        "show('Profile updated. Refreshing…');window.location.reload();"
        "}catch(error){show(`Profile update failed: ${error.message}`,true);}}));"
        f"{glossary_script()}"
        "</script></body></html>"
    )
