from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
import logging
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.config import AppConfig, TickerGroup
from app.models import ScanSnapshot
from app.options.eligibility import evaluate_options_eligibility
from app.options.filters import filter_long_call_contracts
from app.options.models import (
    OptionChainMetadata,
    OptionContract,
    OptionsScanResult,
    OptionsScanStatus,
    ProviderErrorMetadata,
)
from app.options.provider import (
    AlpacaOptionsDataProvider,
    OptionsDataProvider,
    OptionsProviderError,
)
from app.options.ranking import rank_option_candidates
from app.options.repository import OptionsScanRepository
from app.options.scoring import score_option_candidate
from app.runtime_universe import (
    RuntimeUniverseResolver,
    StaticRuntimeUniverseResolver,
)

LOGGER = logging.getLogger(__name__)


class QualifiedScanError(RuntimeError):
    """Report isolated qualified-scan failures after all tickers are attempted."""

    def __init__(
        self,
        partial_results: list[OptionsScanResult],
        failures: list[tuple[str, str]],
    ) -> None:
        self.partial_results = partial_results
        self.failures = failures
        tickers = ", ".join(ticker for ticker, _ in failures)
        super().__init__(f"Qualified scan failed for: {tickers}")


class EquitySnapshotRepository(Protocol):
    def latest(self, ticker: str) -> ScanSnapshot | None: ...

    def latest_all(self) -> list[ScanSnapshot]: ...


class OptionsScanService:
    def __init__(
        self,
        config: AppConfig,
        equity_repository: EquitySnapshotRepository,
        options_repository: OptionsScanRepository,
        provider: OptionsDataProvider | None = None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        universe_resolver: RuntimeUniverseResolver | None = None,
    ) -> None:
        self.config = config
        self.equity_repository = equity_repository
        self.options_repository = options_repository
        self.universe_resolver = universe_resolver or StaticRuntimeUniverseResolver(
            config
        )
        options = config.strategy.options
        self.provider = provider or AlpacaOptionsDataProvider(
            config.alpaca_api_key,
            config.alpaca_api_secret,
            config=options.provider,
            cache_config=options.cache,
        )
        self._clock = clock

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("service clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    @staticmethod
    def _provider_timestamp(
        contracts: Sequence[OptionContract],
        metadata: OptionChainMetadata,
    ) -> datetime:
        timestamps = [
            timestamp
            for contract in contracts
            for timestamp in (
                contract.quote_timestamp,
                contract.trade_timestamp,
            )
            if timestamp is not None
        ]
        if timestamps:
            return max(timestamps)
        if metadata.responses:
            return max(item.fetched_at for item in metadata.responses)
        raise ValueError("successful provider result has no timestamp metadata")

    def scan(
        self, ticker: str, *, manual_override: bool = False
    ) -> OptionsScanResult:
        normalized = ticker.strip().upper()
        universe = self.universe_resolver.resolve()
        symbol = universe.symbols.get(normalized)
        if symbol is None:
            raise ValueError(f"Unknown configured ticker: {normalized}")
        snapshot = self.equity_repository.latest(normalized)
        if snapshot is None:
            raise ValueError(
                f"No persisted equity scan snapshot is available for {normalized}"
            )
        scanned_at = self._now()
        options = self.config.strategy.options
        eligibility = evaluate_options_eligibility(
            snapshot,
            symbol,
            options,
            manual_override=manual_override,
            as_of=scanned_at,
            entry_policy=self.config.strategy.entry,
            momentum_rsi=self.config.strategy.thresholds.momentum_rsi,
        )
        base = {
            "scanned_at": scanned_at,
            "ticker": normalized,
            "equity_snapshot_at": snapshot.scanned_at,
            "underlying_price": snapshot.features.current_price,
            "equity_state": snapshot.current_state,
            "equity_score": snapshot.score,
            "eligibility": eligibility,
            "equity_weight": options.combined_score.equity_weight,
            "options_weight": options.combined_score.options_weight,
            "warnings": list(eligibility.warnings),
        }
        if not eligibility.eligible:
            result = OptionsScanResult(
                **base,
                status=OptionsScanStatus.NOT_ELIGIBLE,
            )
            self.options_repository.save(result)
            self._log_result(result, total_contracts=0)
            return result

        try:
            chain = self.provider.get_option_chain(
                normalized,
                as_of=scanned_at,
                underlying_price=snapshot.features.current_price,
                max_otm_pct=options.long_call.max_otm_pct,
                min_dte=options.long_call.min_dte,
                max_dte=options.long_call.max_dte,
            )
        except OptionsProviderError as exc:
            result = OptionsScanResult(
                **base,
                status=OptionsScanStatus.OPTIONS_DATA_UNAVAILABLE,
                provider_name=self.provider.name,
                feed=getattr(self.provider, "feed", options.provider.feed.value),
                request_count=exc.request_count,
                cache_hits=exc.cache_hits,
                cache_misses=exc.cache_misses,
                error_status=exc.kind.value,
                error_message=str(exc),
                provider_error=ProviderErrorMetadata(
                    kind=exc.kind,
                    feed=(
                        exc.feed
                        or getattr(
                            self.provider,
                            "feed",
                            options.provider.feed.value,
                        )
                    ),
                    status_code=exc.status_code,
                    request_id=exc.request_id,
                    retry_after=exc.retry_after,
                    rate_limit_remaining=exc.rate_limit_remaining,
                    rate_limit_reset=exc.rate_limit_reset,
                    response_time_ms=exc.response_time_ms,
                ),
            )
            self.options_repository.save(result)
            self._log_result(result, total_contracts=0)
            return result

        filtered = filter_long_call_contracts(
            chain.contracts,
            options.long_call,
            as_of=scanned_at,
        )
        scored = [
            score_option_candidate(contract, snapshot.score, options)
            for contract in filtered.accepted
        ]
        candidates = rank_option_candidates(scored, options)
        provider_timestamp = self._provider_timestamp(
            chain.contracts, chain.metadata
        )
        data_age = max(
            chain.metadata.source_age_seconds,
            max(0.0, (scanned_at - provider_timestamp).total_seconds()),
        )
        warnings = [
            *eligibility.warnings,
            *chain.metadata.warnings,
        ]
        if chain.metadata.malformed_items:
            warnings.append(
                f"Provider skipped {chain.metadata.malformed_items} malformed "
                "contract item(s)"
            )
            warnings.extend(chain.metadata.malformed_item_messages)
        status = (
            OptionsScanStatus.CANDIDATES_FOUND
            if candidates
            else OptionsScanStatus.NO_SUITABLE_CONTRACT
        )
        result = OptionsScanResult(
            **(base | {"warnings": warnings}),
            provider_timestamp=provider_timestamp,
            status=status,
            provider_name=chain.metadata.provider_name,
            feed=chain.metadata.feed,
            data_age_seconds=data_age,
            accepted_candidates=candidates,
            accepted_contracts=filtered.accepted,
            rejected_contracts=filtered.rejected,
            stage_counts=filtered.stage_counts,
            request_count=chain.metadata.request_count,
            cache_hits=chain.metadata.cache_hits,
            cache_misses=chain.metadata.cache_misses,
            provider_metadata=chain.metadata,
        )
        self.options_repository.save(result)
        self._log_result(result, total_contracts=filtered.total)
        return result

    def scan_qualified(self) -> list[OptionsScanResult]:
        results: list[OptionsScanResult] = []
        failures: list[tuple[str, str]] = []
        options = self.config.strategy.options
        snapshots = {
            snapshot.ticker: snapshot
            for snapshot in self.equity_repository.latest_all()
        }
        universe = self.universe_resolver.resolve()
        for ticker, symbol in universe.symbols.items():
            if TickerGroup.LEADER_LONG_CALL not in symbol.groups:
                continue
            snapshot = snapshots.get(ticker)
            if snapshot is None:
                continue
            decision = evaluate_options_eligibility(
                snapshot, symbol, options, manual_override=False, as_of=self._now(),
                entry_policy=self.config.strategy.entry,
                momentum_rsi=self.config.strategy.thresholds.momentum_rsi,
            )
            if not decision.execution_qualified:
                continue
            try:
                results.append(self.scan(snapshot.ticker))
            except (RuntimeError, ValueError, SQLAlchemyError) as exc:
                failures.append((snapshot.ticker, type(exc).__name__))
                LOGGER.error(
                    "options_scan status=ISOLATED_FAILURE ticker=%s error_type=%s",
                    snapshot.ticker,
                    type(exc).__name__,
                )
        if failures:
            raise QualifiedScanError(results, failures)
        return results

    @staticmethod
    def _log_result(
        result: OptionsScanResult, *, total_contracts: int
    ) -> None:
        request_id = (
            result.provider_error.request_id
            if result.provider_error is not None
            else next(
                (
                    response.request_id
                    for response in reversed(
                        result.provider_metadata.responses
                        if result.provider_metadata is not None
                        else []
                    )
                    if response.request_id
                ),
                None,
            )
        )
        stage_counts = ",".join(
            f"{item.stage}:{item.passed}/{item.evaluated}"
            for item in result.stage_counts
        ) or "none"
        LOGGER.info(
            "options_scan status=%s eligibility=%s ticker=%s provider=%s feed=%s "
            "contracts=%d candidates=%d "
            "rejected=%d requests=%d cache_hits=%d cache_misses=%d "
            "manual_override=%s request_id=%s stages=%s",
            result.status.value,
            result.eligibility.status.value,
            result.ticker,
            result.provider_name or "none",
            result.feed or "none",
            total_contracts,
            len(result.accepted_candidates),
            len(result.rejected_contracts),
            result.request_count,
            result.cache_hits,
            result.cache_misses,
            result.eligibility.manual_override,
            request_id or "none",
            stage_counts,
        )
