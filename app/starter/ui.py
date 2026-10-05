from __future__ import annotations

from html import escape

from app.starter.config import StarterConfigV1
from app.starter.models import (
    PostEventAssessment,
    StarterEvaluationStatus,
    StarterOutcomeObservation,
    StarterPolicyEvaluation,
)
from app.ui import (
    PRODUCT_NAME,
    glossary_script,
    glossary_styles,
    render_glossary,
    render_primary_nav,
    shared_page_styles,
)


def _assessment_rows(values: list[PostEventAssessment]) -> str:
    if not values:
        return "<tr><td colspan='6'>No manual assessments recorded.</td></tr>"
    return "".join(
        "<tr>"
        f"<td>{escape(item.entered_at.isoformat())}</td>"
        f"<td>{escape(item.event_result_quality.value)}</td>"
        f"<td>{escape(item.selloff_driver.value)}</td>"
        f"<td>{escape(item.thesis_impact.value)}</td>"
        f"<td>{item.data_completeness:.0%}</td>"
        f"<td>{escape(item.expires_at.isoformat())}</td>"
        "</tr>"
        for item in values
    )


def _evaluation_rows(values: list[StarterPolicyEvaluation]) -> str:
    if not values:
        return "<tr><td colspan='7'>No shadow evaluations recorded.</td></tr>"
    return "".join(
        "<tr>"
        f"<td>{escape(item.created_at.isoformat())}</td>"
        f"<td>{escape(item.status.value)}</td>"
        f"<td>{item.confirmation.passed_count}/{item.confirmation.total_count}</td>"
        f"<td>{escape(item.confirmation.quality.value)}</td>"
        f"<td>{escape(item.proximity.quality.value)}</td>"
        f"<td>{item.max_starter_risk_usd if item.max_starter_risk_usd is not None else '—'}</td>"
        f"<td>{escape(', '.join(code.value for code in item.blocker_codes) or '—')}</td>"
        "</tr>"
        for item in values
    )


def _outcome_rows(
    values: list[StarterOutcomeObservation],
    evaluation_ids: set,
) -> str:
    selected = [
        item for item in values if item.evaluation_id in evaluation_ids
    ]
    if not selected:
        return "<tr><td colspan='6'>No forward observations recorded.</td></tr>"
    return "".join(
        "<tr>"
        f"<td>{escape(item.observed_at.isoformat())}</td>"
        f"<td>{item.elapsed_days:.2f}</td>"
        f"<td>{item.underlying_price if item.underlying_price is not None else '—'}</td>"
        f"<td>{escape(item.option_symbol or '—')}</td>"
        f"<td>{item.option_mid if item.option_mid is not None else '—'}</td>"
        f"<td>{escape(item.strict_readiness.value)}</td>"
        "</tr>"
        for item in selected
    )


def render_starter_page(
    *,
    config: StarterConfigV1,
    selected_ticker: str,
    assessments: list[PostEventAssessment],
    evaluations: list[StarterPolicyEvaluation],
    observations: list[StarterOutcomeObservation],
    error: str | None = None,
) -> str:
    selected = selected_ticker.strip().upper()
    ticker_options = "".join(
        f"<option value='{escape(ticker)}'"
        f"{' selected' if ticker == selected else ''}>{escape(ticker)}</option>"
        for ticker in sorted(config.approved_tickers)
    )
    latest = evaluations[0] if evaluations else None
    result = (
        "<div class='result-card'>"
        f"<h2>{escape(latest.status.value)}</h2>"
        f"<p>Technical confirmation: {escape(latest.confirmation.quality.value)} "
        f"({latest.confirmation.passed_count}/{latest.confirmation.total_count} "
        "shared requirements passed)</p>"
        f"<p>Entry proximity: {escape(latest.proximity.quality.value)} — price "
        "distance to confirmation only, not expected value.</p>"
        f"<p>Risk cap: {latest.max_risk_fraction_of_full_setup:.0%} of the "
        f"manually frozen full-setup risk budget"
        f"{f' (${latest.max_starter_risk_usd:,.2f})' if latest.max_starter_risk_usd else ''}.</p>"
        f"<p>Blockers: {escape(', '.join(code.value for code in latest.blocker_codes) or 'None')}</p>"
        f"<p>Warnings: {escape(', '.join(code.value for code in latest.warning_codes) or 'None')}</p>"
        "<p>Full-confirmation review uses the existing Call Readiness next trigger "
        "and requires a future QUALIFIED result while event evidence remains fresh "
        "and local-support invalidation has not occurred.</p>"
        "</div>"
        if latest is not None
        else "<div class='result-card'><h2>No evaluation yet</h2>"
        "<p>Record a complete post-earnings assessment, then evaluate.</p></div>"
    )
    prescreen = (
        "<button id='run-options-prescreen' type='button'>Run existing Options "
        "contract pre-screen</button>"
        if latest is not None
        and latest.status is StarterEvaluationStatus.PRELIMINARY_ELIGIBLE
        else ""
    )
    error_markup = (
        f"<div class='notice error'>{escape(error)}</div>" if error else ""
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Starter Lab · {PRODUCT_NAME}</title><style>"
        "body{margin:0;font-family:Inter,system-ui,sans-serif}.page{max-width:1180px;"
        "margin:auto;padding:24px}.shadow-banner{padding:16px;border-radius:12px;"
        "background:#3f286f;color:white;font-weight:800}.grid{display:grid;"
        "grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.card{padding:20px;"
        "margin-top:16px;border:1px solid #ded6ef;border-radius:14px;background:#fff}"
        "form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}"
        "label{display:grid;gap:5px;font-size:13px;font-weight:700}input,select,textarea,"
        "button{font:inherit;padding:9px;border:1px solid #cfc3ea;border-radius:8px}"
        "textarea{min-height:70px}.wide{grid-column:1/-1}.checks{font-weight:500}"
        "table{border-collapse:collapse;width:100%;font-size:12px}th,td{padding:8px;"
        "border-bottom:1px solid #eee;text-align:left}.result-card{padding:16px;"
        "border-radius:10px;background:#f5f1ff}.error{color:#a11}.status{min-height:24px}"
        "@media(max-width:700px){.grid,form{grid-template-columns:1fr}.wide{grid-column:auto}}"
        f"{glossary_styles()}{shared_page_styles()}</style></head><body>"
        "<div class='app-viewport'><main class='page app-shell'>"
        "<header class='page-hero'><div class='eyebrow'>Research workspace</div>"
        "<h1>Anticipatory Starter Shadow Lab</h1>"
        "<p>Post-earnings evidence and deterministic pre-confirmation review.</p>"
        f"{render_primary_nav('starter')}</header>"
        "<div class='shadow-banner'>SHADOW MODE — hypothetical research only. "
        "No execution qualification, no order, and no automatic averaging.</div>"
        f"{error_markup}<div class='grid'><section class='card'><h2>Manual Post-Earnings "
        "Assessment</h2><p>Expiry is computed by the system. Values are manually "
        "attested and are not externally verified.</p><form id='assessment-form'>"
        f"<label>Ticker<select id='ticker'>{ticker_options}</select></label>"
        "<label>Event time (timezone required)<input id='event-at' "
        "placeholder='2026-09-01T20:00:00Z' required></label>"
        "<label>Event result<select id='event-result'><option>UNKNOWN</option>"
        "<option>POSITIVE</option><option>MIXED_POSITIVE</option>"
        "<option>NEGATIVE</option></select></label>"
        "<label>Selloff driver<select id='selloff-driver'><option>UNKNOWN</option>"
        "<option>EXPECTATION_RESET</option><option>VALUATION_RESET</option>"
        "<option>THESIS_IMPAIRMENT</option></select></label>"
        "<label>Thesis impact<select id='thesis-impact'><option>UNCERTAIN</option>"
        "<option>IMPROVED</option><option>INTACT</option>"
        "<option>IMPAIRED</option></select></label>"
        "<label>Entered by<input id='entered-by' required></label>"
        "<label class='wide'>Positive reason codes (comma-separated)"
        "<input id='positive-reasons'></label>"
        "<label class='wide'>Negative reason codes (comma-separated)"
        "<input id='negative-reasons'></label>"
        "<label class='wide'>Source references (one per line)"
        "<textarea id='source-references' required></textarea></label>"
        "<label>Evidence confidence (trust/completeness, not probability)"
        "<input id='confidence' type='number' min='0' max='1' step='.05' "
        "required></label><label>Risk plan UUID<input id='risk-plan-id' required>"
        "</label><label>Full-setup risk budget (USD loss budget)"
        "<input id='risk-budget' type='number' min='.01' step='.01' required></label>"
        "<label class='checks'><input id='blocker-review' type='checkbox'>"
        "Explicit blocker review complete</label>"
        "<fieldset class='wide'><legend>Hard blockers reviewed</legend>"
        + "".join(
            f"<label class='checks'><input type='checkbox' name='blocker' "
            f"value='{escape(code)}'>{escape(code)}</label>"
            for code in (
                "GUIDANCE_COLLAPSE",
                "ACCOUNTING_OR_REGULATORY_SHOCK",
                "THESIS_IMPAIRMENT",
                "UNRESOLVED_BINARY_CATALYST",
                "EVENT_ATTRIBUTION_UNKNOWN",
            )
        )
        + "</fieldset><button id='save-assessment' type='submit'>Save immutable "
        "assessment</button><button id='evaluate' type='button'>Evaluate shadow "
        f"eligibility</button>{prescreen}<div class='status wide' id='starter-status' "
        "role='status'></div></form></section><section class='card'><h2>Latest result"
        f"</h2>{result}</section></div>"
        "<section class='card'><h2>Assessment history</h2><table><thead><tr>"
        "<th>Entered</th><th>Result</th><th>Driver</th><th>Thesis</th>"
        "<th>Completeness</th><th>Expires</th></tr></thead><tbody>"
        f"{_assessment_rows(assessments)}</tbody></table></section>"
        "<section class='card'><h2>Evaluation history</h2><table><thead><tr>"
        "<th>Created</th><th>Status</th><th>Requirements</th><th>Confirmation</th>"
        "<th>Proximity</th><th>Risk cap USD</th><th>Blockers</th></tr></thead><tbody>"
        f"{_evaluation_rows(evaluations)}</tbody></table></section>"
        "<section class='card'><h2>Forward observations</h2><p>Only actual persisted "
        "point-in-time values are recorded. No outcome or expectancy claim is made.</p>"
        "<table><thead><tr><th>Observed</th><th>Elapsed days</th><th>Underlying</th>"
        "<th>Option</th><th>Mid</th><th>Strict readiness</th></tr></thead><tbody>"
        f"{_outcome_rows(observations, {item.evaluation_id for item in evaluations})}"
        "</tbody></table></section>"
        f"{render_glossary()}<script>"
        "const form=document.getElementById('assessment-form');"
        "const statusEl=document.getElementById('starter-status');"
        "let busy=false;const csv=id=>document.getElementById(id).value.split(',')"
        ".map(v=>v.trim()).filter(Boolean);"
        "const lines=id=>document.getElementById(id).value.split(/\\n+/)"
        ".map(v=>v.trim()).filter(Boolean);"
        "async function request(url,options){const r=await fetch(url,options);"
        "const raw=await r.text();let body;try{body=raw?JSON.parse(raw):null;}"
        "catch(_){body={detail:raw||`HTTP ${r.status}`};}if(!r.ok)"
        "throw new Error(body&&body.detail?body.detail:`HTTP ${r.status}`);return body;}"
        "form.addEventListener('submit',async event=>{event.preventDefault();if(busy)return;"
        "busy=true;const button=document.getElementById('save-assessment');button.disabled=true;"
        "statusEl.textContent='Saving…';try{const ticker=document.getElementById('ticker').value;"
        "const payload={event_id:crypto.randomUUID(),ticker,event_type:'EARNINGS',"
        "event_at:document.getElementById('event-at').value,entered_at:new Date().toISOString(),"
        "entered_by:document.getElementById('entered-by').value,event_result_quality:"
        "document.getElementById('event-result').value,selloff_driver:"
        "document.getElementById('selloff-driver').value,thesis_impact:"
        "document.getElementById('thesis-impact').value,positive_reason_codes:"
        "csv('positive-reasons'),negative_reason_codes:csv('negative-reasons'),"
        "event_blocker_codes:[...document.querySelectorAll(\"input[name='blocker']:checked\")]"
        ".map(item=>item.value),blocker_review_complete:document.getElementById("
        "'blocker-review').checked,source:'MANUAL_USER_ENTRY',source_references:"
        "lines('source-references'),evidence_confidence:Number(document.getElementById("
        "'confidence').value),risk_plan_id:document.getElementById('risk-plan-id').value,"
        "planned_full_setup_risk_budget_usd:Number(document.getElementById('risk-budget').value)};"
        "await request(`/starter/events/${encodeURIComponent(ticker)}`,{method:'POST',"
        "headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});"
        "window.location.assign(`/starter?ticker=${encodeURIComponent(ticker)}`);}"
        "catch(error){statusEl.textContent=`Save failed: ${error.message}`;busy=false;"
        "button.disabled=false;}});"
        "document.getElementById('evaluate').addEventListener('click',async()=>{if(busy)return;"
        "busy=true;statusEl.textContent='Evaluating…';try{const ticker=document.getElementById("
        "'ticker').value;await request(`/starter/evaluate/${encodeURIComponent(ticker)}`,"
        "{method:'POST'});window.location.assign(`/starter?ticker=${encodeURIComponent(ticker)}`);}"
        "catch(error){statusEl.textContent=`Evaluation failed: ${error.message}`;busy=false;}});"
        "const prescreen=document.getElementById('run-options-prescreen');if(prescreen)"
        "prescreen.addEventListener('click',async()=>{if(busy)return;busy=true;"
        "statusEl.textContent='Running existing Options pre-screen…';try{const ticker="
        "document.getElementById('ticker').value;await request(`/options/scan/${encodeURIComponent("
        "ticker)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});"
        "await request(`/starter/evaluate/${encodeURIComponent(ticker)}`,{method:'POST'});"
        "window.location.assign(`/starter?ticker=${encodeURIComponent(ticker)}`);}"
        "catch(error){statusEl.textContent=`Pre-screen failed: ${error.message}`;busy=false;}});"
        f"{glossary_script()}</script></main></div></body></html>"
    )
