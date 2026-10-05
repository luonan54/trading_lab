from __future__ import annotations

from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.features_content import (
    ARCHITECTURE_STEPS,
    CADENCE,
    FEATURE_CARDS,
    LIMITATIONS,
    PITCH,
    PRINCIPLES,
    SOURCE_NOTE,
    TIMELINE,
)
from app.ui import (
    PRODUCT_NAME,
    glossary_script,
    glossary_styles,
    render_glossary,
    render_primary_nav,
    shared_page_styles,
)

GOOGLE_MIRROR_URL = ""


def _cards() -> str:
    return "".join(
        "<article class='feature-card'>"
        f"<span class='status status-{item.status.lower()}'>{escape(item.status)}</span>"
        f"<h3>{escape(item.title)}</h3><p>{escape(item.description)}</p></article>"
        for item in FEATURE_CARDS
    )


def _labeled_rows(items: tuple[tuple[str, str], ...]) -> str:
    return "".join(
        f"<article><h3>{escape(title)}</h3><p>{escape(body)}</p></article>"
        for title, body in items
    )


def render_features_page() -> str:
    architecture = "".join(
        f"<li><span>{index}</span>{escape(step)}</li>"
        for index, step in enumerate(ARCHITECTURE_STEPS, start=1)
    )
    limitations = "".join(f"<li>{escape(item)}</li>" for item in LIMITATIONS)
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>Features · {PRODUCT_NAME}</title><style>"
        ":root{--blue:#0A66C2;--dark:#004182;--bg:#F3F2EF;--surface:#fff;"
        "--border:#E5E3DF;--muted:#666;--green:#057642;--orange:#9a5b00}"
        "*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#222;"
        "font:14px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}"
        "main{max-width:1240px;margin:auto;padding:24px}.hero{padding:28px 30px 22px;"
        "border-radius:12px;background:linear-gradient(135deg,var(--blue),var(--dark));"
        "color:#fff;box-shadow:0 8px 24px #0041822f}.eyebrow{font-size:11px;"
        "font-weight:800;letter-spacing:.8px;text-transform:uppercase;color:#ffffff99}"
        ".hero h1{font-size:32px;margin:4px 0}.hero>p{max-width:800px;margin:0;color:#dcecff;"
        "font-size:16px}.section{margin-top:18px;padding:22px;background:var(--surface);"
        "border-radius:10px;box-shadow:0 1px 3px #0002}.section h2{margin:0 0 13px;"
        "color:var(--dark)}.principles,.features,.two-col{display:grid;gap:12px}"
        ".principles{grid-template-columns:repeat(4,1fr)}.principles article,.two-col article{"
        "padding:14px;border:1px solid var(--border);border-radius:8px}.principles h3,"
        ".two-col h3{margin:0 0 5px;font-size:14px}.principles p,.two-col p,"
        ".feature-card p{margin:0;color:var(--muted)}.features{grid-template-columns:"
        "repeat(3,1fr)}.feature-card{position:relative;padding:18px;border:1px solid "
        "var(--border);border-radius:9px}.feature-card h3{margin:25px 0 6px}.status{"
        "position:absolute;top:13px;right:13px;padding:3px 8px;border-radius:12px;"
        "font-size:10px;font-weight:800;text-transform:uppercase}.status-complete{"
        "background:#dff5e8;color:var(--green)}.status-planned{background:#e8f0fd;"
        "color:var(--blue)}.status-deferred{background:#fff1dc;color:var(--orange)}"
        ".status-dormant{background:#ecebea;color:#666}"
        ".architecture{counter-reset:none;display:grid;grid-template-columns:repeat(4,1fr);"
        "gap:10px;list-style:none;padding:0}.architecture li{padding:14px;border-radius:8px;"
        "background:#f4f8fd}.architecture span{display:block;width:24px;height:24px;"
        "margin-bottom:7px;border-radius:50%;background:var(--blue);color:#fff;text-align:"
        "center;line-height:24px;font-weight:800}.two-col{grid-template-columns:1fr 1fr}"
        ".limitations li+li{margin-top:7px}.links{display:flex;gap:9px;flex-wrap:wrap}"
        ".links a{padding:8px 11px;border-radius:7px;background:#e8f0fd;color:var(--dark);"
        "font-weight:700;text-decoration:none}.source-note{color:var(--muted);font-size:12px}"
        f"{glossary_styles()}{shared_page_styles()}"
        "@media(max-width:900px){.principles,.features,.architecture{grid-template-columns:"
        "repeat(2,1fr)}}@media(max-width:620px){main{padding:12px}.principles,.features,"
        ".architecture,.two-col{grid-template-columns:1fr}}</style></head><body>"
        "<div class='app-viewport'><main class='app-shell'><div class='page-shell'>"
        "<header class='hero page-hero'><div class='eyebrow'>Product guide</div>"
        f"<h1>{PRODUCT_NAME} Features</h1><p>{escape(PITCH)}</p>"
        f"{render_primary_nav('features')}</header>"
        "<section class='section'><h2>Operating principles</h2><div class='principles'>"
        f"{_labeled_rows(PRINCIPLES)}</div></section>"
        f"<section class='section'><h2>Feature status</h2><div class='features'>{_cards()}</div></section>"
        "<section class='section control-plane architecture-panel'>"
        "<h2>High-level architecture</h2>"
        f"<ol class='architecture'>{architecture}</ol></section>"
        "<section class='section'><h2>Manual operating cadence</h2><div class='two-col'>"
        f"{_labeled_rows(CADENCE)}</div></section>"
        "<section class='section'><h2>Development timeline</h2><div class='two-col'>"
        f"{_labeled_rows(TIMELINE)}</div></section>"
        f"<section class='section'><h2>Limitations and disclosures</h2><ul class='limitations'>{limitations}</ul></section>"
        "<section class='section'><h2>Sources and maintenance</h2>"
        f"<p class='source-note'>{escape(SOURCE_NOTE)}</p><p><code>README.md</code> "
        "describes this sharing copy.</p><div class='links'>"
        "<a href='/'>Dashboard</a><a href='/options'>Options</a>"
        "<a href='/classification'>Classification</a>"
        "</div></section>"
        f"{render_glossary()}</div></main></div>"
        f"<script>{glossary_script()}</script></body></html>"
    )


def create_features_router() -> APIRouter:
    router = APIRouter()

    @router.get("/features", response_class=HTMLResponse)
    def features_page() -> HTMLResponse:
        return HTMLResponse(render_features_page())

    return router
