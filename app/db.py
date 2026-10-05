from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import math
from pathlib import Path

from sqlalchemy import (
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.models import ScanSnapshot

SESSION_OPEN_SOURCE = "ALPACA_15M_REGULAR_SESSION"


class Base(DeclarativeBase):
    pass


class ScanSnapshotRecord(Base):
    __tablename__ = "scan_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    state: Mapped[str] = mapped_column(String(40), index=True)
    score: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict] = mapped_column(JSON)


class MarketSessionOpenRecord(Base):
    __tablename__ = "market_session_opens"
    __table_args__ = (
        UniqueConstraint(
            "ticker",
            "session_date",
            name="uq_market_session_opens_ticker_date",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(10), index=True)
    session_date: Mapped[date] = mapped_column(Date, index=True)
    open_price: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(50))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


@dataclass(frozen=True)
class CanonicalSessionOpen:
    ticker: str
    session_date: date
    open_price: float
    source: str
    recorded_at: datetime


def _canonical_open(record: MarketSessionOpenRecord) -> CanonicalSessionOpen:
    recorded_at = record.recorded_at
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=UTC)
    else:
        recorded_at = recorded_at.astimezone(UTC)
    return CanonicalSessionOpen(
        ticker=record.ticker,
        session_date=record.session_date,
        open_price=record.open_price,
        source=record.source,
        recorded_at=recorded_at,
    )


class SnapshotRepository:
    def __init__(self, database_url: str) -> None:
        if database_url.startswith("sqlite:///") and ":memory:" not in database_url:
            database_path = Path(database_url.removeprefix("sqlite:///"))
            database_path.parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine = create_engine(database_url, connect_args=connect_args)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        Base.metadata.create_all(self.engine)

    def save(self, snapshot: ScanSnapshot) -> None:
        with self.sessions.begin() as session:
            session.add(
                ScanSnapshotRecord(
                    ticker=snapshot.ticker,
                    scanned_at=snapshot.scanned_at.astimezone(UTC),
                    state=snapshot.current_state.value,
                    score=snapshot.score,
                    payload=snapshot.model_dump(mode="json"),
                )
            )

    def latest(self, ticker: str) -> ScanSnapshot | None:
        with self.sessions() as session:
            record = session.scalar(
                select(ScanSnapshotRecord)
                .where(ScanSnapshotRecord.ticker == ticker.upper())
                .order_by(ScanSnapshotRecord.scanned_at.desc(), ScanSnapshotRecord.id.desc())
                .limit(1)
            )
            return ScanSnapshot.model_validate(record.payload) if record else None

    def latest_all(self) -> list[ScanSnapshot]:
        with self.sessions() as session:
            tickers = session.scalars(
                select(ScanSnapshotRecord.ticker).distinct()
            ).all()
        return [
            snapshot
            for ticker in tickers
            if (snapshot := self.latest(ticker)) is not None
        ]

    def get_market_session_open(
        self,
        ticker: str,
        session_date: date,
    ) -> CanonicalSessionOpen | None:
        with self.sessions() as session:
            record = session.scalar(
                select(MarketSessionOpenRecord).where(
                    MarketSessionOpenRecord.ticker == ticker.upper(),
                    MarketSessionOpenRecord.session_date == session_date,
                )
            )
            return _canonical_open(record) if record else None

    def record_market_session_open(
        self,
        ticker: str,
        session_date: date,
        open_price: float,
        *,
        source: str = SESSION_OPEN_SOURCE,
        recorded_at: datetime | None = None,
    ) -> CanonicalSessionOpen:
        ticker = ticker.strip().upper()
        if not ticker:
            raise ValueError("ticker cannot be blank")
        if not math.isfinite(open_price) or open_price <= 0:
            raise ValueError("open_price must be finite and positive")
        if not source.strip():
            raise ValueError("source cannot be blank")

        with self.sessions() as session:
            existing = session.scalar(
                select(MarketSessionOpenRecord).where(
                    MarketSessionOpenRecord.ticker == ticker,
                    MarketSessionOpenRecord.session_date == session_date,
                )
            )
            if existing is not None:
                return _canonical_open(existing)

            record = MarketSessionOpenRecord(
                ticker=ticker,
                session_date=session_date,
                open_price=open_price,
                source=source,
                recorded_at=(recorded_at or datetime.now(UTC)).astimezone(UTC),
            )
            session.add(record)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.scalar(
                    select(MarketSessionOpenRecord).where(
                        MarketSessionOpenRecord.ticker == ticker,
                        MarketSessionOpenRecord.session_date == session_date,
                    )
                )
                if existing is None:
                    raise
                return _canonical_open(existing)
            return _canonical_open(record)
