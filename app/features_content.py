from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeatureCard:
    title: str
    status: str
    description: str


PITCH = (
    "Explainable equity and options analysis that keeps portfolio role, "
    "technical state, contract quality, and position sizing separate."
)

PRINCIPLES = (
    ("Deterministic first", "Rules, thresholds, components, and missing data remain inspectable."),
    ("Separate decision layers", "Portfolio role ≠ technical state ≠ options quality ≠ position size."),
    ("Human confirmation", "Classification changes require an explicit, attributed user decision."),
    ("Unavailable stays unavailable", "Provider gaps reduce confidence; they never become fabricated values."),
)

FEATURE_CARDS = (
    FeatureCard(
        "Multi-role universe",
        "Complete",
        "Overlapping leader, long-term, high-risk, short-term, and benchmark groups without duplicate ticker records.",
    ),
    FeatureCard(
        "Six-state technical engine",
        "Complete",
        "NORMAL, DIP_WATCH, SELLING_EXHAUSTION, RIGHT_SIDE_REPAIR, CALL_CANDIDATE, and BREAKDOWN.",
    ),
    FeatureCard(
        "Tech Setup Score",
        "Complete",
        "Normalized 0–10 underlying setup score with no points reserved for unavailable options data.",
    ),
    FeatureCard(
        "Shared call readiness",
        "Complete",
        "NOT_READY, DEVELOPING, NEAR_QUALIFICATION, and QUALIFIED are derived from one requirement evaluator shared by classification, explanations, and options eligibility.",
    ),
    FeatureCard(
        "Tactical and major levels",
        "Complete",
        "Completed 15-minute pivots drive local confirmation while completed daily swings remain visible as major support and resistance.",
    ),
    FeatureCard(
        "Explainability",
        "Complete",
        "WHY, MISSING, NEXT, INVALIDATION, confidence notes, and transition reasons are persisted per scan.",
    ),
    FeatureCard(
        "Strategy-aware workflow guidance",
        "Complete",
        "Next Step is derived per dashboard view from Technical State, confirmed manual context, and existing options eligibility without mutating stored data.",
    ),
    FeatureCard(
        "Move / 下一步动作",
        "Complete",
        "Five deterministic attention lanes make options, long-term, thesis, risk, and monitoring review immediately scannable without adding a decision or execution layer.",
    ),
    FeatureCard(
        "Dashboard table controls",
        "Complete",
        "Client-side Next Step and manual-plan filters plus stable ticker, state-priority, and Tech Setup Score sorting preserve the authoritative server view and current URL.",
    ),
    FeatureCard(
        "Session metrics and history",
        "Complete",
        "Canonical Today Open, Today %, 15m %, UTC storage, ET display, and immutable snapshot history.",
    ),
    FeatureCard(
        "Long/short horizon separation",
        "Complete",
        "Manual long-term role/action context remains independent of short-term technical state.",
    ),
    FeatureCard(
        "Leader workflow",
        "Complete",
        "Configured leaders can use contract pre-screen research during high-quality repair; only fully qualified call readiness enters Current Qualified Setups.",
    ),
    FeatureCard(
        "Classification review and audit",
        "Complete",
        "Confirmed profiles, evidence scoring, hysteresis, proposals, explicit decisions, versions, and audit history.",
    ),
    FeatureCard(
        "Options scoring and ranking",
        "Complete",
        "Five transparent contract-fit components, evidence confidence, combined score, stable ranking, and diversity controls.",
    ),
    FeatureCard(
        "Read-only options data and review UI",
        "Complete",
        "Documented Alpaca GET endpoints, bounded cache, additive history, typed API/CLI, and a local inspection page.",
    ),
    FeatureCard(
        "Classification-driven dashboard membership",
        "Complete",
        "Confirmed database profiles drive dashboard tabs, equity scan selection, Call Candidate permission, watchlist metadata, and Options leader eligibility; failures are visibly labeled as degraded YAML fallback.",
    ),
    FeatureCard(
        "Anticipatory Starter Shadow Lab",
        "Dormant",
        "UI and API are disabled. The isolated code, configuration, migrations, tables, and retained research data remain available for future research.",
    ),
    FeatureCard(
        "Observation and historical evaluation",
        "Planned",
        "Outcome tracking and leakage-safe backtesting require frozen definitions and sufficient forward history.",
    ),
    FeatureCard(
        "Scheduling and alerts",
        "Deferred",
        "The current product is manually triggered; no scheduler or notification provider is enabled.",
    ),
    FeatureCard(
        "TREND_CONTINUATION / EXTENDED_MOMENTUM",
        "Deferred",
        "Aspirational playbook states are not implemented and are not silently mapped to the six-state engine.",
    ),
)

ARCHITECTURE_STEPS = (
    "YAML market plumbing plus confirmed database runtime profiles",
    "Completed Alpaca bars",
    "Deterministic local/major levels, technical state, and setup score",
    "Shared call-readiness requirements, blockers, and next trigger",
    "Immutable equity snapshot",
    "Contextual, non-binding Next Step workflow guidance",
    "Deterministic Move attention routing plus client-side filtering and stable sorting",
    "Research or fully qualified options eligibility for configured leaders",
    "Read-only options chain and contract metadata",
    "Transparent filters, score, confidence, ranking, and history",
    "Human review in Dashboard, Options, or Classification",
)

CADENCE = (
    ("Before the session", "Review configured universe, roles, event flags, and data availability."),
    ("During the session", "Run manual equity scans after completed bars; use Move for review priority, State for structure, Next Trigger for the missing market condition, and Next Step for detailed workflow context."),
    ("During repair", "Use Contract Pre-Screen for research when the configured score gate passes; this does not place the setup in Current Qualified Setups."),
    ("When qualified", "Review Current Qualified Setups only after CALL_CANDIDATE, QUALIFIED readiness, and zero required blockers."),
    ("After review", "Record explicit classification decisions and retain immutable scan history."),
)

TIMELINE = (
    ("Initial MVP", "Completed-bar market data, indicators, six-state classifier, score, SQLite, API, CLI, and dashboard."),
    ("Explainability and sessions", "Added structured rationale, universe views, transitions, Today %, 15m %, and canonical open."),
    ("Options Phase 1", "Established normalized contracts, eligibility, quality derivation, event flags, and filters."),
    ("Classification Phases 1–4", "Added profile authority, evidence evaluation, hysteresis, proposals, decisions, UI, and audit."),
    ("Options Phases 2–4", "Added deterministic ranking, official read-only provider, cache, persistence, API, CLI, and UI."),
    ("Local Stock Lab product layer", "Added a visible product name, shared navigation, bilingual glossary, refresh clarity, and this feature guide."),
    ("Contextual workflow guidance", "Added deterministic Next Step guidance across All, Leader, Long-Term, High-Risk, and Short-Term dashboard views."),
    ("Shared call readiness", "Unified call requirements across classification, explanations, and options eligibility; split tactical 15-minute levels from major daily swings and separated contract pre-screen from fully qualified setups."),
    ("Dashboard table controls", "Added strategy-aware Next Step and independent manual-plan filters plus stable ticker, state-priority, and Tech Setup Score sorting with URL persistence."),
    ("Classification Phase 5", "Made confirmed database profiles the runtime authority for analysis membership and metadata, with an explicit degraded YAML fallback."),
    ("Starter Shadow Mode", "Added the post-earnings Shadow Lab, exact 4-of-5 readiness gate, current options-fit gate, risk cap, immutable evidence, and forward observation foundation."),
    ("Daily workflow simplification", "Disabled the Starter UI/API while retaining code and data; added deterministic Move lanes, Dashboard filtering, and safety-first priority sorting."),
)

LIMITATIONS = (
    "Analysis and decision support only; no order model, endpoint, submission, or broker-position integration.",
    "IEX equity data is not full-market SIP. The Basic options indicative feed contains modified quotes and trades that can be delayed up to 15 minutes.",
    "TOP_CANDIDATE means best configured contract fit, not a recommendation or probability of success.",
    "RESEARCH_ELIGIBLE permits contract pre-screen only; EXECUTION_QUALIFIED is a rules tier for Current Qualified Setups and still does not place or prepare an order.",
    "Next Step is contextual and non-binding workflow guidance; it never changes positions, profiles, long-term actions, or eligibility.",
    "Move is an aggregation of existing workflow context; it never executes, mutates, overrides manual plans, or creates a new score or eligibility rule.",
    "Dashboard table filters only hide or reorder rows already selected by the server-side strategy view; they do not scan, fetch, or persist data.",
    "Confirmed database profiles are authoritative at runtime; degraded YAML fallback is visibly labeled.",
    "Earnings and live fundamental evidence are unavailable until explicit external providers are added.",
    "Starter is dormant: its UI/API are disabled while its code and tables remain retained for future research.",
    "Historical backtesting, enabled scheduler, alerts, and LLM narrative remain absent.",
)

SOURCE_NOTE = "Feature descriptions are inherited from the source snapshot; see README.md for sharing-copy changes and setup."
