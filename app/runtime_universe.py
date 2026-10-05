from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import logging
from types import MappingProxyType
from typing import Mapping, Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.classification.models import RiskTier, TickerProfile
from app.classification.repository import ClassificationRepository
from app.config import (
    AppConfig,
    LongTermAction,
    SymbolConfig,
    UniverseSelectionError,
)
from app.universe import AssetClass, TickerGroup

LOGGER = logging.getLogger(__name__)


class RuntimeUniverseSource(StrEnum):
    CONFIRMED_DB = "CONFIRMED_DB"
    STATIC_CONFIG = "STATIC_CONFIG"
    DEGRADED_YAML = "DEGRADED_YAML"

    @property
    def display_name(self) -> str:
        return {
            RuntimeUniverseSource.CONFIRMED_DB: "Confirmed DB",
            RuntimeUniverseSource.STATIC_CONFIG: "Static config",
            RuntimeUniverseSource.DEGRADED_YAML: "Degraded YAML fallback",
        }[self]


@dataclass(frozen=True)
class RuntimeSymbol:
    ticker: str
    enabled: bool
    groups: frozenset[TickerGroup]
    strategy_tags: frozenset[str]
    risk_tier: RiskTier | None
    benchmark_tags: tuple[str, ...]
    company_quality: float
    asset_class: AssetClass
    company_id: str | None
    exposure_group: str | None
    target_weight: float | None
    max_weight: float | None
    profile_version: int | None
    tier: int | None
    long_term_action: LongTermAction | None
    benchmark: bool = False

    @property
    def scan_eligible(self) -> bool:
        return (
            self.enabled
            and not self.benchmark
            and self.asset_class is AssetClass.EQUITY
        )

    @property
    def allows_call_candidate(self) -> bool:
        return TickerGroup.LEADER_LONG_CALL in self.groups


@dataclass(frozen=True)
class RuntimeUniverse:
    symbols: Mapping[str, RuntimeSymbol]
    source: RuntimeUniverseSource
    degraded_reason: str | None = None

    @property
    def degraded(self) -> bool:
        return self.source is RuntimeUniverseSource.DEGRADED_YAML

    @property
    def warnings(self) -> tuple[str, ...]:
        return (self.degraded_reason,) if self.degraded_reason else ()

    @property
    def source_label(self) -> str:
        return self.source.display_name

    @property
    def enabled_analysis_symbols(self) -> list[str]:
        return [
            ticker for ticker, symbol in self.symbols.items() if symbol.scan_eligible
        ]

    def configured_symbols(
        self, group: str | TickerGroup | None = None
    ) -> list[str]:
        if group is None:
            return list(self.symbols)
        parsed = self._parse_group(group)
        return [
            ticker
            for ticker, symbol in self.symbols.items()
            if parsed in symbol.groups
        ]

    def select_analysis_symbols(
        self,
        *,
        group: str | TickerGroup | None = None,
        ticker: str | None = None,
    ) -> list[str]:
        if group is not None and ticker is not None:
            raise UniverseSelectionError("Choose either a group or a ticker, not both")
        if ticker is not None:
            normalized = ticker.strip().upper()
            symbol = self.symbols.get(normalized)
            if symbol is None:
                raise UniverseSelectionError(
                    f"Unknown or unconfirmed ticker '{normalized}'"
                )
            if not symbol.enabled:
                raise UniverseSelectionError(
                    f"Ticker {normalized} is disabled for scanning"
                )
            if symbol.benchmark:
                raise UniverseSelectionError(
                    f"Ticker {normalized} is benchmark-only"
                )
            if symbol.asset_class is not AssetClass.EQUITY:
                raise UniverseSelectionError(
                    f"Ticker {normalized} uses unsupported asset class "
                    f"{symbol.asset_class.value}; this scanner supports equities only"
                )
            return [normalized]

        selected = self.enabled_analysis_symbols
        if group is None:
            return selected
        parsed = self._parse_group(group)
        return [
            ticker for ticker in selected if parsed in self.symbols[ticker].groups
        ]

    def benchmark_symbols_for(self, analysis_symbols: list[str]) -> list[str]:
        required = {
            benchmark
            for ticker in analysis_symbols
            for benchmark in self.symbols[ticker].benchmark_tags
        }
        return [
            ticker
            for ticker, symbol in self.symbols.items()
            if ticker in required
            and symbol.benchmark
            and symbol.enabled
            and symbol.asset_class is AssetClass.EQUITY
        ]

    @staticmethod
    def _parse_group(group: str | TickerGroup) -> TickerGroup:
        try:
            return group if isinstance(group, TickerGroup) else TickerGroup(group)
        except ValueError as exc:
            valid = ", ".join(item.value for item in TickerGroup)
            raise UniverseSelectionError(
                f"Unknown group '{group}'. Valid groups: {valid}"
            ) from exc


class RuntimeUniverseResolver(Protocol):
    def resolve(self) -> RuntimeUniverse: ...


class StaticRuntimeUniverseResolver:
    def __init__(
        self,
        config: AppConfig,
        *,
        source: RuntimeUniverseSource = RuntimeUniverseSource.STATIC_CONFIG,
        degraded_reason: str | None = None,
    ) -> None:
        self.config = config
        self.source = source
        self.degraded_reason = degraded_reason

    def resolve(self) -> RuntimeUniverse:
        symbols = {
            ticker: _from_static_config(ticker, symbol)
            for ticker, symbol in self.config.symbols.items()
        }
        return RuntimeUniverse(
            symbols=MappingProxyType(symbols),
            source=self.source,
            degraded_reason=self.degraded_reason,
        )


class ConfirmedProfileUniverseResolver:
    def __init__(
        self,
        config: AppConfig,
        repository: ClassificationRepository,
    ) -> None:
        self.config = config
        self.repository = repository

    def resolve(self) -> RuntimeUniverse:
        try:
            profiles = {profile.ticker: profile for profile in self.repository.list_profiles()}
        except (SQLAlchemyError, OSError) as exc:
            LOGGER.warning(
                "Runtime profile query failed; using explicit degraded YAML fallback: %s",
                exc,
            )
            return StaticRuntimeUniverseResolver(
                self.config,
                source=RuntimeUniverseSource.DEGRADED_YAML,
                degraded_reason=type(exc).__name__,
            ).resolve()

        symbols: dict[str, RuntimeSymbol] = {}
        for ticker, static in self.config.symbols.items():
            if static.benchmark:
                symbols[ticker] = _from_static_config(ticker, static)
                continue
            profile = profiles.get(ticker)
            if profile is not None:
                symbols[ticker] = _from_confirmed_profile(ticker, static, profile)
        return RuntimeUniverse(
            symbols=MappingProxyType(symbols),
            source=RuntimeUniverseSource.CONFIRMED_DB,
        )


def _from_static_config(ticker: str, symbol: SymbolConfig) -> RuntimeSymbol:
    confirmed = symbol.confirmed_profile
    return RuntimeSymbol(
        ticker=ticker,
        enabled=symbol.enabled,
        groups=frozenset(symbol.groups),
        strategy_tags=frozenset(symbol.strategy_tags),
        risk_tier=confirmed.risk_tier if confirmed else None,
        benchmark_tags=tuple(symbol.benchmark_tags),
        company_quality=symbol.company_quality,
        asset_class=symbol.asset_class,
        company_id=confirmed.company_id if confirmed else None,
        exposure_group=confirmed.exposure_group if confirmed else None,
        target_weight=confirmed.target_weight if confirmed else None,
        max_weight=confirmed.max_weight if confirmed else None,
        profile_version=None,
        tier=symbol.tier,
        long_term_action=symbol.long_term_action,
        benchmark=symbol.benchmark,
    )


def _from_confirmed_profile(
    ticker: str,
    static: SymbolConfig,
    profile: TickerProfile,
) -> RuntimeSymbol:
    return RuntimeSymbol(
        ticker=ticker,
        enabled=profile.enabled,
        groups=frozenset(profile.groups),
        strategy_tags=frozenset(profile.strategy_tags),
        risk_tier=profile.risk_tier,
        benchmark_tags=tuple(profile.benchmark_tags),
        company_quality=profile.company_quality,
        asset_class=profile.asset_class,
        company_id=profile.company_id,
        exposure_group=profile.exposure_group,
        target_weight=profile.target_weight,
        max_weight=profile.max_weight,
        profile_version=profile.version,
        tier=static.tier,
        long_term_action=static.long_term_action,
        benchmark=False,
    )
