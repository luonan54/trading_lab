from datetime import datetime
from html import escape

from app.entry import current_entry
from app.entry_models import EntryEvaluation, EntryStatus
from app.readiness_models import CallReadinessEvaluation


def readiness_lights(readiness: CallReadinessEvaluation | None) -> str:
    if readiness is None:
        return "<span class='readiness-unavailable'>Checks unavailable</span>"
    lights = []
    for item in readiness.requirements:
        description = f"{item.status.value}: {item.label} — {item.evidence}"
        tone = "pass" if item.passed else "fail"
        mark = "&#x1F7E2;" if item.passed else "&#x1F534;"
        lights.append(
            f"<button type='button' class='readiness-light' "
            f"data-check-code='{item.code.value}' data-check-status='{item.status.value}' "
            f"title='{escape(description)}' aria-label='{escape(description)}'>"
            f"<span class='readiness-lamp readiness-lamp-{tone}' aria-hidden='true'>{mark}</span>"
            "</button>"
        )
    return (
        "<div class='readiness-lights' role='group' "
        "aria-label='Readiness checks; hover, focus or tap each light for evidence'>"
        + "".join(lights) + "</div>"
    )


def readiness_light_styles() -> str:
    return (
        ".readiness-lights{display:flex;align-items:center;gap:2px;width:max-content}"
        ".readiness-lights .readiness-light{display:flex;align-items:center;justify-content:center;"
        "width:24px;height:28px;min-width:24px;padding:0;margin:0;border:0;border-radius:5px;"
        "background:transparent;box-shadow:none;cursor:help}"
        ".readiness-lights .readiness-light:focus-visible{outline:2px solid #0a66c2;outline-offset:1px}"
        ".readiness-lamp{display:block;flex:none;"
        "font:400 17px/1 'Apple Color Emoji','Segoe UI Emoji','Noto Color Emoji',sans-serif}"
        ".readiness-unavailable{font-size:12px;color:#666}"
        ".readiness-tooltip{position:fixed;z-index:10000;max-width:min(360px,calc(100vw - 16px));"
        "max-height:calc(100vh - 16px);overflow-y:auto;"
        "padding:10px 12px;background:#172033;color:#fff;border-radius:8px;"
        "box-shadow:0 4px 18px #0003;font:13px/1.5 -apple-system,BlinkMacSystemFont,sans-serif;"
        "white-space:normal;overflow-wrap:anywhere;text-align:left}"
        ".readiness-tooltip[hidden]{display:none}"
        ".scan-checks{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:10px 0}"
    )


def readiness_light_script() -> str:
    return """
    (()=>{
      const lights=document.querySelectorAll('.readiness-light');
      if(!lights.length)return;
      const tooltip=document.createElement('div');
      tooltip.id='readiness-tooltip';
      tooltip.className='readiness-tooltip';
      tooltip.setAttribute('role','tooltip');
      tooltip.hidden=true;
      document.body.appendChild(tooltip);
      let active=null,timer;
      function hide(){
        clearTimeout(timer);
        tooltip.hidden=true;
        if(active)active.removeAttribute('aria-describedby');
        active=null;
      }
      function show(light){
        hide();
        active=light;
        tooltip.textContent=light.dataset.readinessTooltip;
        tooltip.hidden=false;
        tooltip.style.left='8px';
        tooltip.style.top='8px';
        const anchor=light.getBoundingClientRect();
        const box=tooltip.getBoundingClientRect();
        tooltip.style.left=Math.max(8,Math.min(anchor.left,window.innerWidth-box.width-8))+'px';
        tooltip.style.top=Math.max(8,anchor.bottom+box.height+16<=window.innerHeight
          ?anchor.bottom+8:anchor.top-box.height-8)+'px';
        light.setAttribute('aria-describedby',tooltip.id);
      }
      function deferHide(){
        clearTimeout(timer);
        timer=setTimeout(()=>{
          if(!active||!active.matches(':focus'))hide();
        },150);
      }
      lights.forEach(light=>{
        light.dataset.readinessTooltip=light.title;
        light.removeAttribute('title');
        light.addEventListener('mouseenter',()=>show(light));
        light.addEventListener('mouseleave',deferHide);
        light.addEventListener('focus',()=>show(light));
        light.addEventListener('blur',deferHide);
        light.addEventListener('click',()=>show(light));
      });
      tooltip.addEventListener('mouseenter',()=>clearTimeout(timer));
      tooltip.addEventListener('mouseleave',deferHide);
      document.addEventListener('keydown',event=>{if(event.key==='Escape')hide();});
      document.addEventListener('pointerdown',event=>{
        if(active&&!active.contains(event.target)&&!tooltip.contains(event.target))hide();
      });
      window.addEventListener('resize',hide);
      window.addEventListener('scroll',hide,true);
    })();
    """


def entry_conclusion(
    plan: EntryEvaluation | None, *, qualified: bool, allowed: bool = True,
    now: datetime | None = None,
) -> tuple[str, str]:
    current = current_entry(plan, now=now)
    if not allowed:
        return "Outside call workflow", "not_ready"
    if qualified:
        return "Ready for review", "qualified"
    label = {
        EntryStatus.READY: "Wait for confirmation",
        EntryStatus.WAIT_CONFIRMATION: "Wait for confirmation",
        EntryStatus.WAIT_PULLBACK: "Wait for pullback",
        EntryStatus.INSUFFICIENT_REWARD: "Risk/reward insufficient",
        EntryStatus.INVALIDATED: "Setup invalidated",
        EntryStatus.UNAVAILABLE: "Entry not assessable",
        EntryStatus.STALE: "Refresh required",
    }[current.status]
    tone = "developing"
    if current.status is EntryStatus.INVALIDATED:
        tone = "blocked"
    elif current.status in {EntryStatus.STALE, EntryStatus.UNAVAILABLE}:
        tone = "not_ready"
    return label, tone


def entry_markup(plan: EntryEvaluation | None, *, now: datetime | None = None) -> str:
    current = current_entry(plan, now=now)
    anchor = current.anchor

    def money(value: float | None) -> str:
        return f"${value:.2f}" if value is not None else "Not recorded"

    ratio = f"{current.reward_risk:.2f}R" if current.reward_risk is not None else "Not assessable"
    stop = money(anchor.invalidation_level) if anchor else "Not established"
    target = money(anchor.target_level) if anchor and anchor.target_level is not None else "No confirmed target"
    levels = (
        f"<div>E {money(current.entry_price)} / "
        f"S {stop} / T {target}</div>"
        f"<div><strong>Reward/risk: {ratio}</strong> "
        f"(minimum {current.policy.min_reward_risk:.2f}R)</div>"
    )
    zone = (
        f"<div>Entry zone: {money(current.entry_zone_low)} - {money(current.entry_zone_high)}</div>"
        if current.entry_zone_low is not None else (
            "<div>Entry zone pending a confirmed structure</div>" if anchor is None
            else "<div>No feasible entry zone established</div>"
        )
    )
    structure_note = (
        "<p>Structure not established: stop, target and R cannot be derived yet. "
        "This does not by itself mean market prices are missing.</p>"
        if anchor is None else ""
    )
    time_note = (
        f"Price bar close: {current.price_as_of.isoformat()}"
        if current.price_as_of else "No source price timestamp stored with this entry evaluation."
    )
    source = (
        f"<div>{escape(anchor.setup_type.value)}: {escape(anchor.reference_source)}; "
        f"target: {escape(anchor.target_source)}. "
        f"Anchored {escape(anchor.formed_at.isoformat())}.</div>"
        if anchor else ""
    )
    relative = (
        f"<div>20-session relative strength vs benchmarks: "
        f"{current.relative_strength_pct:+.2f} percentage points</div>"
        if current.relative_strength_pct is not None else ""
    )
    blockers = "".join(f"<li>{escape(text)}</li>" for text in current.blockers)
    return (
        f"<div class='entry-plan' data-entry-status='{current.status.value}'>"
        f"<strong>{current.status.value.replace('_', ' ')}</strong>"
        f"{levels}{zone}{structure_note}<small>{escape(time_note)}</small>"
        f"<ul>{blockers}</ul><details><summary>Entry evidence / limitations</summary>"
        f"{source}{relative}<p>{escape(current.next_trigger)}</p>"
        "<p>2-10 trading-day equity swing; not option DTE. Stock R is not option R "
        "or a probability. Gaps and slippage can exceed the planned loss. "
        "Not a live quote, order or instruction to sell existing holdings.</p>"
        "</details></div>"
    )
