from enum import StrEnum


class TickerGroup(StrEnum):
    LEADER_LONG_CALL = "leader_long_call"
    LONG_TERM_CORE = "long_term_core"
    LONG_TERM_GROWTH = "long_term_growth"
    HIGH_RISK_GROWTH = "high_risk_growth"
    SHORT_TERM_WATCH = "short_term_watch"


class AssetClass(StrEnum):
    EQUITY = "equity"
    CRYPTO = "crypto"
