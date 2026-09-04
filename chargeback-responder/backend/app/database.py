import os
import logging
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base

logger = logging.getLogger("chargeback_responder")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@db:5432/disputes_db")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_dev_auto_migrations():
    """
    Hackathon-timeline stopgap, NOT a substitute for real migrations
    (Alembic) before this goes anywhere near production. Base.metadata.
    create_all() only creates tables that don't exist yet - it never ALTERs
    an existing table when a model gains a new column. That's exactly what
    caused 'column disputes.source does not exist': the model picked up
    Dispute.source in a later session, but the dev DB volume from an earlier
    session still has the old shape.

    This walks every model's columns after create_all() and ADD COLUMNs
    whatever's missing from the live table, so a schema change made between
    hackathon sessions doesn't require dropping the dev DB (and losing all
    seeded demo data) every time. New columns are always added nullable,
    even if the model marks them non-nullable - a NOT NULL ADD COLUMN would
    fail outright against a table that already has rows, and "nullable in
    the DB, defaulted in the app" is a fine trade-off for a dev-only helper.
    """
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue  # create_all() already handled brand-new tables
        existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in existing_columns:
                continue
            col_type = column.type.compile(dialect=engine.dialect)
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                logger.info(f"[dev-auto-migrate] Added missing column {table.name}.{column.name}")
            except Exception as exc:
                logger.warning(f"[dev-auto-migrate] Could not add {table.name}.{column.name}: {exc}")
