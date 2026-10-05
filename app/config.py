from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.classification.config import ClassificationConfig
from app.classification.models import ConfirmedProfileBootstrap
from app.models import SetupState
from app.universe import AssetClass, TickerGroup

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LongTermAction(StrEnum):
    ADD = "ADD"
    HOLD = "HOLD"
    PAUSE_ADD = "PAUSE_ADD"
    THESIS_REVIEW = "THESIS_REVIEW"


class UniverseSelectionError(ValueError):
    pass


class SymbolConfig(BaseModel):
    enabled: bool = True
    groups: frozenset[TickerGroup] = Field(default_factory=frozenset)
    tier: int | None = Field(default=None, ge=1)
    company_quality: float = Field(ge=0, le=2)
    strategy_tags: frozenset[str] = Field(default_factory=frozenset)
    benchmark_tags: tuple[str, ...] = ()
    benchmark: bool = False
    asset_class: AssetClass = AssetClass.EQUITY
    long_term_action: LongTermAction | None = None
    confirmed_profile: ConfirmedProfileBootstrap | None = None

    @field_validator("strategy_tags", mode="before")
    @classmethod
    def normalize_strategy_tags(cls, value: object) -> object:
        if value is None:
            return ()
        return tuple(str(tag).strip().lower() for tag in value)

    @field_validator("benchmark_tags", mode="before")
    @classmethod
    def normalize_benchmark_tags(cls, value: object) -> object:
        if value is None:
            return ()
        return tuple(str(tag).strip().upper() for tag in value)

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


class AlpacaConfig(BaseModel):
    feed: str = "iex"
    intraday_lookback_days: int = Field(default=12, ge=2)
    daily_lookback_days: int = Field(default=220, ge=40)


class ThresholdConfig(BaseModel):
    oversold_rsi: float = 35.0
    momentum_rsi: float = Field(default=50.0, ge=0, le=100, allow_inf_nan=False)
    dip_drawdown_pct: float = -5.0
    breakdown_buffer_pct: float = 0.5
    benchmark_min_daily_return_pct: float = -0.75
    structure_tolerance_pct: float = 0.2


class StructureConfig(BaseModel):
    swing_window: int = Field(default=3, ge=2)
    support_resistance_window: int = Field(default=20, ge=5)
    local_structure_window: int = Field(default=20, ge=7)
    local_pivot_span: int = Field(default=2, ge=1, le=5)


class PolicyAction(StrEnum):
    WARN = "warn"
    REJECT = "reject"


class OptionsFeed(StrEnum):
    INDICATIVE = "indicative"
    OPRA = "opra"


class OptionsProviderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feed: OptionsFeed = OptionsFeed.INDICATIVE
    data_base_url: str = "https://data.alpaca.markets"
    trading_base_url: str = "https://paper-api.alpaca.markets"
    request_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    snapshot_page_size: int = Field(default=100, ge=1, le=1000)
    contracts_page_size: int = Field(default=100, ge=1, le=1000)
    max_snapshot_pages: int = Field(default=20, ge=1, le=100)
    max_contract_pages: int = Field(default=20, ge=1, le=100)
    max_chain_contracts: int = Field(default=2000, ge=1, le=10000)

    @field_validator("data_base_url")
    @classmethod
    def validate_official_data_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        if normalized != "https://data.alpaca.markets":
            raise ValueError("options data_base_url must use the official Alpaca host")
        return normalized

    @field_validator("trading_base_url")
    @classmethod
    def validate_trading_url(cls, value: str) -> str:
        normalized = value.rstrip("/")
        parsed = urlparse(normalized)
        allowed_hosts = {
            "api.alpaca.markets",
            "paper-api.alpaca.markets",
        }
        if (
            parsed.scheme != "https"
            or parsed.hostname not in allowed_hosts
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError(
                "trading_base_url must use an official Alpaca paper/live API host"
            )
        return normalized


class OptionsCacheConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chain_ttl_seconds: int = Field(default=300, ge=1, le=3600)
    contract_metadata_ttl_seconds: int = Field(default=900, ge=1, le=86400)
    max_entries: int = Field(default=256, ge=2, le=10000)


class OptionsEligibilityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_equity_score: float = Field(default=8.0, ge=0, le=10)
    allowed_states: frozenset[SetupState] = Field(
        default_factory=lambda: frozenset(
            {SetupState.CALL_CANDIDATE, SetupState.RIGHT_SIDE_REPAIR}
        )
    )

    @model_validator(mode="after")
    def validate_allowed_states(self) -> "OptionsEligibilityConfig":
        safe_states = {
            SetupState.CALL_CANDIDATE,
            SetupState.RIGHT_SIDE_REPAIR,
        }
        unsupported = self.allowed_states - safe_states
        if unsupported:
            values = ", ".join(sorted(state.value for state in unsupported))
            raise ValueError(f"Unsupported options eligibility states: {values}")
        missing = safe_states - self.allowed_states
        if missing:
            values = ", ".join(sorted(state.value for state in missing))
            raise ValueError(f"Required options eligibility states are missing: {values}")
        return self


class LongCallConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_dte: int = Field(default=60, ge=0)
    max_dte: int = Field(default=120, ge=0)
    preferred_dte_min: int = Field(default=75, ge=0)
    preferred_dte_max: int = Field(default=100, ge=0)
    preferred_delta_min: float = Field(default=0.55, ge=0, le=1)
    preferred_delta_max: float = Field(default=0.70, ge=0, le=1)
    absolute_delta_min: float = Field(default=0.45, ge=0, le=1)
    absolute_delta_max: float = Field(default=0.75, ge=0, le=1)
    max_otm_pct: float = Field(default=0.03, ge=0, le=1)
    min_open_interest: int = Field(default=500, ge=0)
    min_volume: int = Field(default=50, ge=0)
    max_spread_pct: float = Field(default=0.05, ge=0, le=1)
    max_candidates_per_ticker: int = Field(default=5, ge=1)
    prefer_atm_or_itm: bool = True
    missing_delta_policy: PolicyAction = PolicyAction.WARN
    missing_volume_policy: PolicyAction = PolicyAction.WARN
    missing_open_interest_policy: PolicyAction = PolicyAction.REJECT
    low_volume_policy: PolicyAction = PolicyAction.REJECT
    stale_quote_minutes: int = Field(default=15, ge=1)
    high_relative_iv_percentile: float = Field(default=0.80, ge=0, le=1)
    relative_iv_min_sample_size: int = Field(default=5, ge=2)

    @model_validator(mode="after")
    def validate_ranges(self) -> "LongCallConfig":
        if self.min_dte > self.max_dte:
            raise ValueError("min_dte must be less than or equal to max_dte")
        if self.preferred_dte_min > self.preferred_dte_max:
            raise ValueError(
                "preferred_dte_min must be less than or equal to preferred_dte_max"
            )
        if not (
            self.min_dte
            <= self.preferred_dte_min
            <= self.preferred_dte_max
            <= self.max_dte
        ):
            raise ValueError(
                "preferred DTE range must be within the filtered DTE range"
            )
        if self.absolute_delta_min > self.absolute_delta_max:
            raise ValueError(
                "absolute_delta_min must be less than or equal to "
                "absolute_delta_max"
            )
        if self.preferred_delta_min > self.preferred_delta_max:
            raise ValueError(
                "preferred_delta_min must be less than or equal to "
                "preferred_delta_max"
            )
        if not (
            self.absolute_delta_min
            <= self.preferred_delta_min
            <= self.preferred_delta_max
            <= self.absolute_delta_max
        ):
            raise ValueError(
                "preferred delta range must be within the absolute delta range"
            )
        return self


class CombinedScoreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    equity_weight: float = Field(default=0.70, ge=0)
    options_weight: float = Field(default=0.30, ge=0)

    @model_validator(mode="after")
    def validate_weights(self) -> "CombinedScoreConfig":
        if abs(self.equity_weight + self.options_weight - 1.0) > 1e-9:
            raise ValueError("combined score weights must total 1.0")
        return self


class OptionsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    provider: OptionsProviderConfig = Field(default_factory=OptionsProviderConfig)
    cache: OptionsCacheConfig = Field(default_factory=OptionsCacheConfig)
    eligibility: OptionsEligibilityConfig = Field(
        default_factory=OptionsEligibilityConfig
    )
    long_call: LongCallConfig = Field(default_factory=LongCallConfig)
    combined_score: CombinedScoreConfig = Field(
        default_factory=CombinedScoreConfig
    )


from app.entry_models import EntryPolicy


class StrategyConfig(BaseModel):
    alpaca: AlpacaConfig
    thresholds: ThresholdConfig
    structure: StructureConfig
    options: OptionsConfig = Field(default_factory=OptionsConfig)
    entry: EntryPolicy = Field(default_factory=EntryPolicy)


from app.starter.config import StarterConfigV1, load_starter_config


class AppConfig(BaseModel):
    symbols: dict[str, SymbolConfig]
    strategy: StrategyConfig
    database_url: str
    alpaca_api_key: str | None
    alpaca_api_secret: str | None
    classification: ClassificationConfig = Field(
        default_factory=ClassificationConfig
    )
    starter: StarterConfigV1 = Field(default_factory=StarterConfigV1)

    @model_validator(mode="after")
    def validate_universe(self) -> "AppConfig":
        for ticker, symbol in self.symbols.items():
            if ticker != ticker.upper():
                raise ValueError(f"Ticker keys must be uppercase: {ticker}")
            for benchmark_ticker in symbol.benchmark_tags:
                benchmark = self.symbols.get(benchmark_ticker)
                if benchmark is None:
                    raise ValueError(
                        f"{ticker} references unknown benchmark {benchmark_ticker}"
                    )
                if (
                    not benchmark.benchmark
                    or not benchmark.enabled
                    or benchmark.asset_class is not AssetClass.EQUITY
                ):
                    raise ValueError(
                        f"{ticker} benchmark {benchmark_ticker} must be an enabled "
                        "equity benchmark"
                    )
        return self

    @property
    def group_names(self) -> tuple[str, ...]:
        return tuple(group.value for group in TickerGroup)

    @property
    def benchmarks(self) -> list[str]:
        return [
            symbol
            for symbol, item in self.symbols.items()
            if item.benchmark and item.enabled and item.asset_class is AssetClass.EQUITY
        ]

    @property
    def enabled_analysis_symbols(self) -> list[str]:
        return [
            ticker for ticker, symbol in self.symbols.items() if symbol.scan_eligible
        ]

    @property
    def credentials_configured(self) -> bool:
        return bool(self.alpaca_api_key and self.alpaca_api_secret)

    def parse_group(self, group: str | TickerGroup) -> TickerGroup:
        try:
            return group if isinstance(group, TickerGroup) else TickerGroup(group)
        except ValueError as exc:
            valid = ", ".join(self.group_names)
            raise UniverseSelectionError(
                f"Unknown group '{group}'. Valid groups: {valid}"
            ) from exc

    def configured_symbols(
        self, group: str | TickerGroup | None = None
    ) -> list[str]:
        if group is None:
            return list(self.symbols)
        parsed_group = self.parse_group(group)
        return [
            ticker
            for ticker, symbol in self.symbols.items()
            if parsed_group in symbol.groups
        ]

    def select_analysis_symbols(
        self,
        *,
        group: str | TickerGroup | None = None,
        ticker: str | None = None,
    ) -> list[str]:
        if group is not None and ticker is not None:
            raise UniverseSelectionError(
                "Choose either a group or a ticker, not both"
            )
        if ticker is not None:
            normalized = ticker.strip().upper()
            symbol = self.symbols.get(normalized)
            if symbol is None:
                raise UniverseSelectionError(
                    f"Unknown ticker '{normalized}'"
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
        if group is not None:
            parsed_group = self.parse_group(group)
            selected = [
                ticker
                for ticker in selected
                if parsed_group in self.symbols[ticker].groups
            ]
        if not selected:
            label = f"group {group}" if group is not None else "the universe"
            raise UniverseSelectionError(
                f"No enabled equity analysis symbols are configured for {label}"
            )
        return selected

    def benchmark_symbols_for(self, tickers: list[str]) -> list[str]:
        required = {
            benchmark
            for ticker in tickers
            for benchmark in self.symbols[ticker].benchmark_tags
        }
        return [ticker for ticker in self.benchmarks if ticker in required]


def _read_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_config(
    *,
    database_url: str | None = None,
    watchlist_path: Path | None = None,
    strategy_path: Path | None = None,
    classification_path: Path | None = None,
    starter_path: Path | None = None,
    load_environment: bool = True,
) -> AppConfig:
    if load_environment:
        load_dotenv(PROJECT_ROOT / ".env")
    watchlist = _read_yaml(watchlist_path or PROJECT_ROOT / "config/watchlist.yaml")
    strategy = _read_yaml(strategy_path or PROJECT_ROOT / "config/strategy.yaml")
    classification = _read_yaml(
        classification_path or PROJECT_ROOT / "config/classification.yaml"
    )
    feed_override = os.getenv("ALPACA_DATA_FEED") if load_environment else None
    if feed_override:
        strategy["alpaca"]["feed"] = feed_override
    if load_environment:
        options = strategy.setdefault("options", {})
        provider = options.setdefault("provider", {})
        options_feed_override = os.getenv("ALPACA_OPTIONS_FEED")
        trading_url_override = os.getenv("ALPACA_TRADING_BASE_URL")
        if options_feed_override:
            provider["feed"] = options_feed_override
        if trading_url_override:
            provider["trading_base_url"] = trading_url_override

    return AppConfig(
        symbols=watchlist["symbols"],
        strategy=StrategyConfig.model_validate(strategy),
        classification=ClassificationConfig.model_validate(classification),
        starter=load_starter_config(
            starter_path or PROJECT_ROOT / "config/starter.yaml"
        ),
        database_url=database_url
        or (
            os.getenv("DATABASE_URL", "sqlite:///data/ceg_trader.db")
            if load_environment
            else "sqlite:///data/ceg_trader.db"
        ),
        alpaca_api_key=(os.getenv("ALPACA_API_KEY") or None)
        if load_environment
        else None,
        alpaca_api_secret=(os.getenv("ALPACA_API_SECRET") or None)
        if load_environment
        else None,
    )
