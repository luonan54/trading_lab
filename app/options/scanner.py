"""Local Stock Lab options contract-fit scanner command line entry point.

This CLI reports the configured contract-fit outcome for one ticker or for
every currently qualified ticker. It never issues trading, order, or broker
instructions and never uses action words such as BUY/SELL/ENTER/EXECUTE.
``TOP_CANDIDATE`` describes the best configured contract fit only, not a
recommendation.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.exc import SQLAlchemyError

from app.config import load_config
from app.db import SnapshotRepository
from app.options.models import (
    OptionsScanResult,
    OptionsScanStatus,
    ScoredOptionCandidate,
)
from app.options.repository import OptionsScanRepository
from app.options.service import OptionsScanService, QualifiedScanError
from app.classification.bootstrap import bootstrap_confirmed_profiles
from app.classification.repository import ClassificationRepository
from app.runtime_universe import ConfirmedProfileUniverseResolver

PRODUCT_NAME = "Local Stock Lab"

# Exit codes: only an actual scan failure (no honest result could be
# produced) is treated as an error. NOT_ELIGIBLE and NO_SUITABLE_CONTRACT
# are valid, informative outcomes and exit cleanly.
_FAILURE_STATUSES = frozenset({OptionsScanStatus.OPTIONS_DATA_UNAVAILABLE})


def _dash(value: object, fmt: str | None = None) -> str:
    if value is None:
        return "—"
    if fmt is not None:
        return format(value, fmt)
    return str(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.options.scanner",
        description=(
            f"{PRODUCT_NAME} options contract-fit scanner. Reports the "
            "configured contract fit for a ticker or for every currently "
            "qualified ticker. This tool does not place, suggest, or "
            "execute trades."
        ),
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--ticker",
        help="Scan one configured ticker for contract fit",
    )
    scope.add_argument(
        "--qualified",
        action="store_true",
        help="Scan every currently qualified (leader_long_call) ticker",
    )
    parser.add_argument(
        "--manual",
        action="store_true",
        help=(
            "Bypass only the equity state/score eligibility gate for the "
            "single --ticker scan. Has no effect with --qualified."
        ),
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override the configured database URL",
    )
    return parser


def _validate_args(args: argparse.Namespace) -> str | None:
    if args.manual and args.qualified:
        return "--manual is only valid together with --ticker"
    return None


def render_candidate_table(candidates: list[ScoredOptionCandidate]) -> str:
    if not candidates:
        return "  (no candidate contracts)"
    header = (
        f"  {'CONTRACT':<22} {'STATUS':<13} {'EXP':<11} {'STRIKE':>8} "
        f"{'DTE':>4} {'DELTA':>6} {'BID':>7} {'ASK':>7} {'SPRD%':>7} "
        f"{'OI':>7} {'VOL':>7} {'IV':>6} {'OPT':>6} {'CONF':>6} {'COMB':>6}"
    )
    lines = [header]
    for candidate in candidates:
        contract = candidate.contract
        lines.append(
            f"  {contract.contract_symbol:<22} {candidate.status.value:<13} "
            f"{contract.expiration.isoformat():<11} "
            f"{contract.strike:>8.2f} {contract.dte:>4} "
            f"{_dash(contract.delta, '.2f'):>6} "
            f"{_dash(contract.bid, '.2f'):>7} {_dash(contract.ask, '.2f'):>7} "
            f"{_dash(contract.spread_pct, '.1%'):>7} "
            f"{_dash(contract.open_interest):>7} {_dash(contract.volume):>7} "
            f"{_dash(contract.implied_volatility, '.1%'):>6} "
            f"{candidate.options_quality_score:>6.2f} "
            f"{candidate.options_score_confidence:>6.0%} "
            f"{candidate.combined_score:>6.2f}"
        )
    return "\n".join(lines)


def render_result(result: OptionsScanResult) -> str:
    lines = [
        f"{result.ticker} {result.status.value}",
        f"  equity_state={result.equity_state.value} "
        f"equity_score={result.equity_score:.2f}",
        f"  manual_override={result.eligibility.manual_override}",
    ]
    if result.eligibility.reasons:
        lines.append(f"  reasons: {'; '.join(result.eligibility.reasons)}")
    if result.warnings:
        lines.append(f"  warnings: {'; '.join(result.warnings)}")
    if result.status is OptionsScanStatus.OPTIONS_DATA_UNAVAILABLE:
        lines.append(f"  provider_error: {_dash(result.error_message)}")
        return "\n".join(lines)
    if result.status in (
        OptionsScanStatus.CANDIDATES_FOUND,
        OptionsScanStatus.MANUAL_OVERRIDE,
    ):
        lines.append(
            "  contract fit is the current configured best match, not a "
            "recommendation"
        )
        lines.append(render_candidate_table(list(result.accepted_candidates)))
        if result.rejected_contracts:
            lines.append(
                f"  rejected contracts: {len(result.rejected_contracts)}"
            )
    return "\n".join(lines)


def _exit_code_for_results(results: list[OptionsScanResult]) -> int:
    if any(result.status in _FAILURE_STATUSES for result in results):
        return 1
    return 0


def main(
    argv: list[str] | None = None,
    *,
    service: OptionsScanService | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    usage_error = _validate_args(args)
    if usage_error is not None:
        print(usage_error, file=sys.stderr)
        return 2

    if service is None:
        config = load_config(database_url=args.database_url)
        equity_repository = SnapshotRepository(config.database_url)
        options_repository = OptionsScanRepository(config.database_url)
        classification_repository = ClassificationRepository(config.database_url)
        bootstrap_confirmed_profiles(config, classification_repository)
        service = OptionsScanService(
            config,
            equity_repository,
            options_repository,
            universe_resolver=ConfirmedProfileUniverseResolver(
                config, classification_repository
            ),
        )

    try:
        if args.qualified:
            results = service.scan_qualified()
            if not results:
                print("No qualified tickers were eligible for scanning.")
                return 0
            for result in results:
                print(render_result(result))
                print()
        else:
            ticker = args.ticker.strip().upper()
            result = service.scan(ticker, manual_override=args.manual)
            results = [result]
            print(render_result(result))
    except QualifiedScanError as exc:
        for result in exc.partial_results:
            print(render_result(result))
            print()
        failures = ", ".join(
            f"{ticker} ({error_type})"
            for ticker, error_type in exc.failures
        )
        print(f"Qualified scan failed for: {failures}", file=sys.stderr)
        return 1
    except (RuntimeError, ValueError, SQLAlchemyError) as exc:
        print(f"Scan failed: {exc}", file=sys.stderr)
        return 1

    return _exit_code_for_results(results)


if __name__ == "__main__":
    raise SystemExit(main())
