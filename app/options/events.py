from __future__ import annotations

from datetime import datetime

from app.options.models import (
    DataQualityFlag,
    EventDataStatus,
    OptionContract,
)
from app.options.quality import ordered_unique


def attach_event_risk(
    contract: OptionContract, *, as_of: datetime
) -> OptionContract:
    """Attach date-only earnings metadata without inferring an event time."""

    flags = list(contract.data_quality_flags)
    warnings = list(contract.warnings)
    if contract.earnings_date is None:
        flags = ordered_unique(
            flags, DataQualityFlag.EARNINGS_DATA_UNAVAILABLE
        )
        warnings = ordered_unique(warnings, "Earnings date is unavailable")
        return contract.model_copy(
            update={
                "event_data_status": EventDataStatus.UNAVAILABLE,
                "data_quality_flags": flags,
                "warnings": warnings,
            }
        )

    days_until_earnings = (contract.earnings_date - as_of.date()).days
    if 0 <= days_until_earnings <= 2:
        flags = ordered_unique(
            flags, DataQualityFlag.NEAR_TERM_EARNINGS_RISK
        )
        warnings = ordered_unique(
            warnings,
            "Earnings are within two calendar days; event time is unavailable",
        )
    if as_of.date() <= contract.earnings_date <= contract.expiration:
        flags = ordered_unique(
            flags, DataQualityFlag.EARNINGS_WITHIN_CONTRACT_LIFE
        )
        warnings = ordered_unique(
            warnings, "Earnings occur within the contract lifetime"
        )
    return contract.model_copy(
        update={
            "event_data_status": EventDataStatus.AVAILABLE,
            "data_quality_flags": flags,
            "warnings": warnings,
        }
    )
