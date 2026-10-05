from __future__ import annotations

import argparse
import sys

from app.classification.bootstrap import bootstrap_confirmed_profiles
from app.classification.models import ReviewMode
from app.classification.repository import ClassificationRepository
from app.classification.reviewer import (
    ClassificationReviewer,
    ProfileNotFoundError,
)
from app.config import load_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Review stored classification evidence without fetching data."
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--ticker")
    scope.add_argument("--all", action="store_true")
    parser.add_argument(
        "--database-url", default="sqlite:///data/ceg_trader.db"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = load_config(
        database_url=args.database_url, load_environment=False
    )
    repository = ClassificationRepository(config.database_url)
    bootstrap_confirmed_profiles(config, repository)
    reviewer = ClassificationReviewer(repository, config.classification)
    tickers = (
        [profile.ticker for profile in repository.list_profiles()]
        if args.all
        else [args.ticker.strip().upper()]
    )
    try:
        for ticker in tickers:
            result = reviewer.review_stored_evidence(
                ticker, review_mode=ReviewMode.MANUAL
            )
            winner = (
                result.winning_candidate.value
                if result.winning_candidate is not None
                else "—"
            )
            print(
                f"{ticker:<8} {result.status.value:<24} "
                f"candidate={winner:<18} delta={result.score_delta:.2f} "
                f"completeness={result.data_completeness:.0%} "
                f"confidence={result.evidence_confidence:.0%} "
                f"streak={result.consecutive_win_count}"
            )
    except ProfileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
