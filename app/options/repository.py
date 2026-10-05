from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.options.models import (
    ContractFilterStatus,
    OptionsScanResult,
    ScoredOptionCandidate,
)


class OptionsBase(DeclarativeBase):
    pass


class OptionsScanRecord(OptionsBase):
    __tablename__ = "options_scans"

    scan_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    status: Mapped[str] = mapped_column(String(40), index=True)
    equity_state: Mapped[str] = mapped_column(String(40), index=True)
    equity_score: Mapped[float] = mapped_column(Float, index=True)
    provider: Mapped[str | None] = mapped_column(String(80), index=True)
    feed: Mapped[str | None] = mapped_column(String(32), index=True)
    manual_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, index=True
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class OptionScanContractRecord(OptionsBase):
    __tablename__ = "option_scan_contracts"
    __table_args__ = (
        UniqueConstraint(
            "scan_id",
            "contract_symbol",
            name="uq_option_scan_contracts_scan_symbol",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scan_id: Mapped[str] = mapped_column(String(36), index=True)
    contract_symbol: Mapped[str] = mapped_column(String(40), index=True)
    filter_status: Mapped[str] = mapped_column(String(24), index=True)
    candidate_status: Mapped[str | None] = mapped_column(
        String(24), index=True
    )
    expiration: Mapped[date] = mapped_column(Date, index=True)
    combined_score: Mapped[float | None] = mapped_column(Float, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)


class OptionsScanRepository:
    """Isolated, additive persistence for options analysis results."""

    def __init__(self, database_url: str) -> None:
        if database_url.startswith("sqlite:///") and ":memory:" not in database_url:
            path = Path(database_url.removeprefix("sqlite:///"))
            path.parent.mkdir(parents=True, exist_ok=True)
        connect_args = (
            {"check_same_thread": False}
            if database_url.startswith("sqlite")
            else {}
        )
        self.engine = create_engine(database_url, connect_args=connect_args)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        OptionsBase.metadata.create_all(self.engine)

    def save(self, result: OptionsScanResult) -> None:
        candidates = {
            item.contract.contract_symbol: item
            for item in result.accepted_candidates
        }
        accepted = result.accepted_contracts or [
            item.contract for item in result.accepted_candidates
        ]
        with self.sessions.begin() as session:
            session.add(
                OptionsScanRecord(
                    scan_id=str(result.scan_id),
                    ticker=result.ticker,
                    scanned_at=result.scanned_at.astimezone(UTC),
                    status=result.status.value,
                    equity_state=result.equity_state.value,
                    equity_score=result.equity_score,
                    provider=result.provider_name,
                    feed=result.feed,
                    manual_override=result.eligibility.manual_override,
                    payload=result.model_dump(mode="json"),
                )
            )
            for contract in accepted:
                candidate = candidates.get(contract.contract_symbol)
                session.add(
                    OptionScanContractRecord(
                        scan_id=str(result.scan_id),
                        contract_symbol=contract.contract_symbol,
                        filter_status=ContractFilterStatus.ACCEPTED.value,
                        candidate_status=(
                            candidate.status.value if candidate else None
                        ),
                        expiration=contract.expiration,
                        combined_score=(
                            candidate.combined_score if candidate else None
                        ),
                        payload=(
                            candidate.model_dump(mode="json")
                            if candidate
                            else contract.model_dump(mode="json")
                        ),
                    )
                )
            for contract in result.rejected_contracts:
                session.add(
                    OptionScanContractRecord(
                        scan_id=str(result.scan_id),
                        contract_symbol=contract.contract_symbol,
                        filter_status=ContractFilterStatus.REJECTED.value,
                        candidate_status=None,
                        expiration=contract.expiration,
                        combined_score=None,
                        payload=contract.model_dump(mode="json"),
                    )
                )

    @staticmethod
    def _scan(record: OptionsScanRecord | None) -> OptionsScanResult | None:
        return (
            OptionsScanResult.model_validate(record.payload)
            if record is not None
            else None
        )

    def get_scan(self, scan_id: UUID | str) -> OptionsScanResult | None:
        with self.sessions() as session:
            return self._scan(session.get(OptionsScanRecord, str(scan_id)))

    def get(self, scan_id: UUID | str) -> OptionsScanResult | None:
        return self.get_scan(scan_id)

    def latest(self, ticker: str) -> OptionsScanResult | None:
        with self.sessions() as session:
            record = session.scalar(
                select(OptionsScanRecord)
                .where(OptionsScanRecord.ticker == ticker.strip().upper())
                .order_by(
                    OptionsScanRecord.scanned_at.desc(),
                    OptionsScanRecord.scan_id.desc(),
                )
                .limit(1)
            )
            return self._scan(record)

    latest_for_ticker = latest
    get_latest = latest

    def latest_all(self) -> list[OptionsScanResult]:
        with self.sessions() as session:
            tickers = session.scalars(
                select(OptionsScanRecord.ticker).distinct()
            ).all()
        return [
            result
            for ticker in sorted(tickers)
            if (result := self.latest(ticker)) is not None
        ]

    def candidates(
        self, scan_id: UUID | str
    ) -> list[ScoredOptionCandidate]:
        with self.sessions() as session:
            records = session.scalars(
                select(OptionScanContractRecord)
                .where(
                    OptionScanContractRecord.scan_id == str(scan_id),
                    OptionScanContractRecord.candidate_status.is_not(None),
                )
                .order_by(
                    OptionScanContractRecord.combined_score.desc(),
                    OptionScanContractRecord.contract_symbol,
                )
            ).all()
            return [
                ScoredOptionCandidate.model_validate(record.payload)
                for record in records
            ]

    get_candidates = candidates
    list_candidates = candidates

    def history(
        self, ticker: str, *, limit: int = 100
    ) -> list[OptionsScanResult]:
        if limit < 1:
            raise ValueError("limit must be positive")
        with self.sessions() as session:
            records = session.scalars(
                select(OptionsScanRecord)
                .where(OptionsScanRecord.ticker == ticker.strip().upper())
                .order_by(
                    OptionsScanRecord.scanned_at.desc(),
                    OptionsScanRecord.scan_id.desc(),
                )
                .limit(limit)
            ).all()
            return [
                result
                for record in records
                if (result := self._scan(record)) is not None
            ]

    get_history = history


OptionsRepository = OptionsScanRepository
