from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from app.classification.models import (
    DecisionSource,
    TickerProfile,
    TickerProfileHistory,
)
from app.classification.repository import ClassificationRepository

if TYPE_CHECKING:
    from app.config import AppConfig, SymbolConfig


INITIALIZATION_ACTOR = "SYSTEM_INITIALIZATION"


@dataclass(frozen=True)
class BootstrapResult:
    inserted_tickers: tuple[str, ...]
    existing_tickers: tuple[str, ...]
    skipped_tickers: tuple[str, ...]


def build_bootstrap_profile(
    ticker: str,
    symbol: SymbolConfig,
    *,
    confirmed_at: datetime,
) -> TickerProfile:
    metadata = symbol.confirmed_profile
    if metadata is None:
        raise ValueError(f"{ticker} has no explicit confirmed_profile metadata")
    return TickerProfile(
        ticker=ticker,
        primary_role=metadata.primary_role,
        groups=tuple(sorted(symbol.groups, key=lambda group: group.value)),
        strategy_tags=tuple(sorted(symbol.strategy_tags)),
        risk_tier=metadata.risk_tier,
        benchmark_tags=symbol.benchmark_tags,
        company_quality=symbol.company_quality,
        enabled=symbol.enabled,
        asset_class=symbol.asset_class,
        confirmed_at=confirmed_at,
        confirmed_by=INITIALIZATION_ACTOR,
        version=1,
        company_id=metadata.company_id,
        exposure_group=metadata.exposure_group,
        target_weight=metadata.target_weight,
        max_weight=metadata.max_weight,
    )


def bootstrap_confirmed_profiles(
    config: AppConfig,
    repository: ClassificationRepository,
    *,
    confirmed_at: datetime | None = None,
) -> BootstrapResult:
    timestamp = confirmed_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("confirmed_at must be timezone-aware")

    inserted: list[str] = []
    existing: list[str] = []
    skipped: list[str] = []
    for ticker, symbol in config.symbols.items():
        if not symbol.enabled or symbol.benchmark or symbol.confirmed_profile is None:
            skipped.append(ticker)
            continue
        profile = build_bootstrap_profile(
            ticker,
            symbol,
            confirmed_at=timestamp,
        )
        history = TickerProfileHistory(
            id=uuid5(
                NAMESPACE_URL,
                f"ceg-trader:classification:{ticker}:initialization:v1",
            ),
            ticker=ticker,
            old_profile_snapshot=None,
            new_profile_snapshot=profile,
            effective_from=timestamp,
            confirmed_at=timestamp,
            decision_source=DecisionSource.SYSTEM_INITIALIZATION,
            proposal_id=None,
            reason_codes=(),
            evidence_snapshot=(),
            profile_version=1,
        )
        if repository.initialize_profile(profile, history):
            inserted.append(ticker)
        else:
            existing.append(ticker)
    return BootstrapResult(
        inserted_tickers=tuple(inserted),
        existing_tickers=tuple(existing),
        skipped_tickers=tuple(skipped),
    )
