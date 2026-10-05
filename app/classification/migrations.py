from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine


def create_classification_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite:///") and ":memory:" not in database_url:
        database_path = Path(database_url.removeprefix("sqlite:///"))
        database_path.parent.mkdir(parents=True, exist_ok=True)
    connect_args = (
        {"check_same_thread": False, "timeout": 30}
        if database_url.startswith("sqlite")
        else {}
    )
    return create_engine(database_url, connect_args=connect_args)


def initialize_classification_schema(engine: Engine) -> None:
    from app.classification.repository import ClassificationBase

    ClassificationBase.metadata.create_all(engine)
