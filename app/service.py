from __future__ import annotations

from datetime import UTC, datetime
from collections.abc import Callable
import logging
import math
from zoneinfo import ZoneInfo

from app.alpaca import AlpacaMarketDataClient
from app.call_readiness import evaluate_call_readiness
from app.config import AppConfig
from app.db import SESSION_OPEN_SOURCE, SnapshotRepository
from app.entry import build_entry_plan, completed_price_time, current_entry, price_expiry
from app.entry_models import EntryPolicy
from app.explainability.rules import build_setup_explanation
from app.explainability.transitions import derive_transition_reasons
from app.indicators import calculate_features
from app.models import ScanSnapshot, SetupState, TechnicalFeatures
from app.runtime_universe import (
    RuntimeUniverseResolver,
    StaticRuntimeUniverseResolver,
)
from app.strategy import calculate_underlying_score, classify_setup

ET = ZoneInfo("America/New_York")
LOGGER = logging.getLogger(__name__)


class ScanService:
    def __init__(
        self,
        config: AppConfig,
        repository: SnapshotRepository,
        market_data: AlpacaMarketDataClient | None = None,
        universe_resolver: RuntimeUniverseResolver | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.config = config
        self._clock = clock
        self.repository = repository
        self.universe_resolver = universe_resolver or StaticRuntimeUniverseResolver(
            config
        )
        self.market_data = market_data or AlpacaMarketDataClient(
            config.alpaca_api_key,
            config.alpaca_api_secret,
            feed=config.strategy.alpaca.feed,
        )

    def _benchmark_confirmed(
        self,
        features_by_symbol: dict[str, TechnicalFeatures],
        benchmark_tickers: tuple[str, ...],
    ) -> bool:
        threshold = self.config.strategy.thresholds.benchmark_min_daily_return_pct
        available = [
            features_by_symbol[symbol]
            for symbol in benchmark_tickers
            if symbol in features_by_symbol
        ]
        return len(available) == len(benchmark_tickers) and bool(available) and all(
            item.today_return_pct is not None
            and item.today_return_pct >= threshold
            and item.current_price >= item.ema20
            for item in available
        )

    def _canonicalize_session_open(
        self,
        symbol: str,
        features: TechnicalFeatures,
        *,
        recorded_at: datetime,
    ) -> TechnicalFeatures:
        if features.session_date is None or features.session_open is None:
            return features
        canonical = self.repository.record_market_session_open(
            symbol,
            features.session_date,
            features.session_open,
            source=SESSION_OPEN_SOURCE,
            recorded_at=recorded_at,
        )
        if not math.isclose(
            canonical.open_price,
            features.session_open,
            rel_tol=0,
            abs_tol=1e-9,
        ):
            LOGGER.warning(
                "Computed session open differs from canonical value for %s on %s; "
                "retained the first recorded value",
                symbol,
                features.session_date,
            )
        return features.model_copy(
            update={"session_open": canonical.open_price}
        )

    def scan(
        self, *, group: str | None = None, ticker: str | None = None
    ) -> list[ScanSnapshot]:
        universe = self.universe_resolver.resolve()
        analysis_symbols = universe.select_analysis_symbols(
            group=group, ticker=ticker
        )
        benchmark_symbols = universe.benchmark_symbols_for(analysis_symbols)
        fetch_symbols = analysis_symbols + benchmark_symbols
        alpaca = self.config.strategy.alpaca
        intraday, daily = self.market_data.fetch_analysis_bars(
            fetch_symbols,
            intraday_lookback_days=alpaca.intraday_lookback_days,
            daily_lookback_days=alpaca.daily_lookback_days,
        )
        features_by_symbol = {
            symbol: calculate_features(
                intraday[symbol],
                daily[symbol],
                swing_window=self.config.strategy.structure.swing_window,
                support_resistance_window=(
                    self.config.strategy.structure.support_resistance_window
                ),
                local_structure_window=(
                    self.config.strategy.structure.local_structure_window
                ),
                local_pivot_span=self.config.strategy.structure.local_pivot_span,
                structure_tolerance_pct=(
                    self.config.strategy.thresholds.structure_tolerance_pct
                ),
            )
            for symbol in fetch_symbols
        }
        scanned_at = self._clock()
        if scanned_at.utcoffset() is None:
            raise ValueError("scan service requires a timezone-aware clock")
        for symbol in analysis_symbols:
            features_by_symbol[symbol] = self._canonicalize_session_open(
                symbol,
                features_by_symbol[symbol],
                recorded_at=scanned_at,
            )
        results: list[ScanSnapshot] = []

        for symbol in analysis_symbols:
            symbol_config = universe.symbols[symbol]
            benchmark_confirmed = self._benchmark_confirmed(
                features_by_symbol, symbol_config.benchmark_tags
            )
            previous = self.repository.latest(symbol)
            previous_state = previous.current_state if previous else None
            features = features_by_symbol[symbol]
            entry_plan = build_entry_plan(
                intraday[symbol], daily[symbol],
                policy=self.config.strategy.entry,
                now=scanned_at,
                previous=previous.entry_plan if previous else None,
                benchmarks=[daily[ticker] for ticker in symbol_config.benchmark_tags],
                momentum_rsi=self.config.strategy.thresholds.momentum_rsi,
            )
            for benchmark in symbol_config.benchmark_tags:
                benchmark_at = completed_price_time(intraday[benchmark], scanned_at)
                if benchmark_at is None:
                    benchmark_confirmed = False
                    continue
                expires_at = price_expiry(benchmark_at, self.config.strategy.entry)
                if scanned_at > expires_at:
                    benchmark_confirmed = False
                if entry_plan.expires_at is not None:
                    entry_plan = entry_plan.model_copy(update={
                        "expires_at": min(entry_plan.expires_at, expires_at)
                    })
            entry_plan = current_entry(entry_plan, now=scanned_at)
            readiness = evaluate_call_readiness(
                features,
                previous_state=previous_state,
                benchmark_confirmed=benchmark_confirmed,
                allow_call_candidate=symbol_config.allows_call_candidate,
                entry_plan=entry_plan,
                as_of=scanned_at,
            )
            technical_readiness = evaluate_call_readiness(
                features,
                previous_state=previous_state,
                benchmark_confirmed=benchmark_confirmed,
                allow_call_candidate=symbol_config.allows_call_candidate,
                entry_plan=entry_plan,
                as_of=scanned_at,
                require_entry=False,
            )
            classification = classify_setup(
                features,
                previous_state=previous_state,
                benchmark_confirmed=benchmark_confirmed,
                thresholds=self.config.strategy.thresholds,
                allow_call_candidate=symbol_config.allows_call_candidate,
                readiness=technical_readiness,
            )
            quality = symbol_config.company_quality
            score = calculate_underlying_score(
                features,
                company_quality=quality,
                benchmark_confirmed=benchmark_confirmed,
            )
            explanation = build_setup_explanation(
                ticker=symbol,
                state=classification.state,
                features=features,
                benchmark_confirmed=benchmark_confirmed,
                previous_state=previous_state,
                thresholds=self.config.strategy.thresholds,
                readiness=readiness,
                entry_plan=entry_plan,
            )
            state_changed = bool(
                previous and previous.current_state != classification.state
            )
            transition_reasons = derive_transition_reasons(
                state_changed=state_changed,
                previous_explanation=previous.explanation if previous else None,
                current_explanation=explanation,
            )
            snapshot = ScanSnapshot(
                ticker=symbol,
                scanned_at=scanned_at,
                displayed_at_et=scanned_at.astimezone(ET).strftime("%Y-%m-%d %I:%M %p ET"),
                previous_state=previous_state,
                current_state=classification.state,
                state_changed=state_changed,
                score=score,
                score_change=round(score - previous.score, 1) if previous else None,
                company_quality=quality,
                options_quality=None,
                benchmark_confirmed=benchmark_confirmed,
                confidence=classification.confidence,
                reasons=classification.reasons,
                invalidation_conditions=classification.invalidation_conditions,
                features=features,
                explanation=explanation,
                call_readiness=readiness,
                entry_plan=entry_plan,
                transition_reasons=transition_reasons,
            )
            self.repository.save(snapshot)
            results.append(snapshot)
        return results


ACTION_ORDER = {
    SetupState.CALL_CANDIDATE: 0,
    SetupState.RIGHT_SIDE_REPAIR: 1,
    SetupState.SELLING_EXHAUSTION: 2,
    SetupState.DIP_WATCH: 3,
    SetupState.BREAKDOWN: 4,
    SetupState.NORMAL: 5,
}


def refresh_snapshot(
    snapshot: ScanSnapshot, *, allow_call_candidate: bool = True,
    entry_policy: EntryPolicy | None = None, momentum_rsi: float | None = None,
) -> ScanSnapshot:
    now = datetime.now(UTC)
    plan = current_entry(
        snapshot.entry_plan, now=now, policy=entry_policy, momentum_rsi=momentum_rsi,
    )
    return snapshot.model_copy(update={
        "entry_plan": plan,
        "call_readiness": evaluate_call_readiness(
            snapshot, allow_call_candidate=allow_call_candidate, as_of=now,
            entry_policy=entry_policy, momentum_rsi=momentum_rsi,
        ),
    })


def sort_snapshots(snapshots: list[ScanSnapshot]) -> list[ScanSnapshot]:
    return sorted(
        snapshots,
        key=lambda item: (
            not evaluate_call_readiness(item).qualified,
            ACTION_ORDER[item.current_state], -item.score, item.ticker,
        ),
    )
