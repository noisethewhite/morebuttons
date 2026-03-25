#!/usr/bin/env python3
"""Heroku release phase: ensure PostgreSQL schema exists before migrations / app tables."""
import os
import sqlalchemy as sqla


def main() -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set")
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    engine = sqla.create_engine(url)
    with engine.connect() as conn:
        conn.execute(sqla.text('CREATE SCHEMA IF NOT EXISTS "00_secrets"'))
        conn.commit()


if __name__ == "__main__":
    main()
