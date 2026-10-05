from __future__ import annotations

from collections.abc import Sequence

from app.config import LongCallConfig, OptionsConfig
from app.options.models import OptionCandidateStatus, ScoredOptionCandidate


def _base_key(candidate: ScoredOptionCandidate) -> tuple[object, ...]:
    spread = candidate.contract.spread_pct
    return (
        -candidate.combined_score,
        -candidate.options_score_confidence,
        spread is None,
        spread if spread is not None else 0.0,
        candidate.contract.contract_symbol,
    )


def _moneyness(candidate: ScoredOptionCandidate) -> float:
    contract = candidate.contract
    if contract.moneyness_pct is not None:
        return contract.moneyness_pct
    return (
        contract.underlying_price - contract.strike
    ) / contract.underlying_price


def _is_strong_atm_or_itm(candidate: ScoredOptionCandidate) -> bool:
    return 0 <= _moneyness(candidate) <= 0.05


def _is_near_duplicate(
    candidate: ScoredOptionCandidate, selected: ScoredOptionCandidate
) -> bool:
    if candidate.contract.expiration != selected.contract.expiration:
        return False
    underlying = selected.contract.underlying_price
    return (
        abs(candidate.contract.strike - selected.contract.strike)
        <= underlying * 0.01
    )


def rank_option_candidates(
    candidates: Sequence[ScoredOptionCandidate],
    config: OptionsConfig | LongCallConfig,
) -> list[ScoredOptionCandidate]:
    """Rank accepted contracts with a bounded, deterministic diversity pass.

    Base order is combined score descending, confidence descending, spread
    ascending (missing last), then contract symbol. The base leader is always
    first. Diversity choices must remain within 1.0 combined-score point and
    1.5 options-score points of that leader. If needed, the pass adds one
    ATM/slightly-ITM contract (0% through +5%), then one expiration at least
    seven days from every selected expiration, then non-near-duplicates. A
    near-duplicate has the same expiration and a strike within 1% of the
    underlying. Remaining capacity is filled in base order. Diversity never
    promotes a materially lower-scoring contract.
    """

    long_call = config.long_call if isinstance(config, OptionsConfig) else config
    if not candidates:
        return []

    base = sorted(candidates, key=_base_key)
    top = base[0]
    selected = [top]
    selected_symbols = {top.contract.contract_symbol}
    diversity_pool = [
        candidate
        for candidate in base[1:]
        if top.combined_score - candidate.combined_score <= 1.0
        and top.options_quality_score - candidate.options_quality_score <= 1.5
    ]

    def add_first(predicate) -> None:
        if len(selected) >= long_call.max_candidates_per_ticker:
            return
        for candidate in diversity_pool:
            symbol = candidate.contract.contract_symbol
            if symbol not in selected_symbols and predicate(candidate):
                selected.append(candidate)
                selected_symbols.add(symbol)
                return

    if not _is_strong_atm_or_itm(top):
        add_first(_is_strong_atm_or_itm)

    add_first(
        lambda candidate: all(
            abs(
                (candidate.contract.expiration - existing.contract.expiration).days
            )
            >= 7
            for existing in selected
        )
    )

    for candidate in diversity_pool:
        if len(selected) >= long_call.max_candidates_per_ticker:
            break
        symbol = candidate.contract.contract_symbol
        if symbol in selected_symbols:
            continue
        if all(
            not _is_near_duplicate(candidate, existing)
            for existing in selected
        ):
            selected.append(candidate)
            selected_symbols.add(symbol)

    for candidate in diversity_pool:
        if len(selected) >= long_call.max_candidates_per_ticker:
            break
        symbol = candidate.contract.contract_symbol
        if symbol not in selected_symbols:
            selected.append(candidate)
            selected_symbols.add(symbol)

    ranked: list[ScoredOptionCandidate] = []
    for index, candidate in enumerate(selected):
        status = (
            OptionCandidateStatus.TOP_CANDIDATE
            if index == 0
            else OptionCandidateStatus.ACCEPTABLE
        )
        status_reason = (
            "Top candidate is the best configured fit."
            if index == 0
            else "Acceptable candidate retained after deterministic ranking."
        )
        ranked.append(
            candidate.model_copy(
                update={
                    "status": status,
                    "reasons": [*candidate.reasons, status_reason],
                }
            )
        )
    return ranked


rank_candidates = rank_option_candidates
