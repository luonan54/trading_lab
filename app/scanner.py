from __future__ import annotations

import argparse
import logging
import sys

from app.alpaca import MarketDataError
from app.config import TickerGroup, UniverseSelectionError, load_config
from app.db import SnapshotRepository
from app.classification.bootstrap import bootstrap_confirmed_profiles
from app.classification.repository import ClassificationRepository
from app.runtime_universe import ConfirmedProfileUniverseResolver
from app.models import ScanSnapshot
from app.call_readiness import evaluate_call_readiness
from app.entry import current_entry
from app.service import ScanService, sort_snapshots


def _percent(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}%"


def _price(value: float | None) -> str:
    return "—" if value is None else f"${value:.2f}"


def render_scan_table(results: list[ScanSnapshot]) -> str:
    lines = [
        f"{'TICKER':<7} {'STATE':<21} {'READINESS':<18} {'SETUP':>5} {'PRICE':>10} "
        f"{'TODAY %':>9} {'15M %':>8} {'TODAY OPEN':>12}"
    ]
    for item in results:
        changed = "*" if item.state_changed else ""
        readiness = evaluate_call_readiness(item).call_readiness.value
        lines.append(
            f"{item.ticker:<7} {(item.current_state.value + changed):<21} "
            f"{readiness:<18} {item.ceg_tech_score:>5.1f} "
            f"{item.features.current_price:>10.2f} "
            f"{_percent(item.features.today_return_pct):>9} "
            f"{_percent(item.features.return_15m_pct):>8} "
            f"{_price(item.features.session_open):>12}"
        )
        if item.state_changed:
            lines.append(f"  changed: {'; '.join(item.reasons)}")
        plan = current_entry(item.entry_plan)
        anchor = plan.anchor
        ratio = f"{plan.reward_risk:.2f}R" if plan.reward_risk is not None else "Unavailable"
        lines.append(
            f"  NEW ENTRY: {plan.status.value}; E={_price(plan.entry_price)} "
            f"S={_price(anchor.invalidation_level if anchor else None)} "
            f"T={_price(anchor.target_level if anchor else None)} R={ratio}"
        )
        lines.extend(f"  blocker: {reason}" for reason in plan.blockers)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local Local Stock Lab equity analysis scanner"
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--group",
        choices=[group.value for group in TickerGroup],
        help="Scan one configured ticker group",
    )
    selection.add_argument(
        "--ticker",
        help="Scan one enabled equity analysis ticker",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = load_config()
    classification_repository = ClassificationRepository(config.database_url)
    bootstrap_confirmed_profiles(config, classification_repository)
    service = ScanService(
        config,
        SnapshotRepository(config.database_url),
        universe_resolver=ConfirmedProfileUniverseResolver(
            config, classification_repository
        ),
    )
    try:
        results = sort_snapshots(
            service.scan(group=args.group, ticker=args.ticker)
        )
    except (MarketDataError, UniverseSelectionError, ValueError) as exc:
        print(f"Scan failed: {exc}", file=sys.stderr)
        return 2

    print(render_scan_table(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
