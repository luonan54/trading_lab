from __future__ import annotations

from sqlalchemy import Engine, inspect

from app.starter.repository import StarterBase

STARTER_TABLES = (
    "starter_event_assessments",
    "anticipatory_starter_evaluations",
    "starter_outcome_observations",
)


def apply_starter_migrations(engine: Engine) -> None:
    """Apply the V1 additive schema without touching existing metadata."""

    StarterBase.metadata.create_all(engine)


def starter_schema_status(engine: Engine) -> dict[str, bool]:
    existing = set(inspect(engine).get_table_names())
    return {table: table in existing for table in STARTER_TABLES}
