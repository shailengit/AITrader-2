"""One-shot DDL for the Trading Brain tables.

Run once to create the 2 tables in the sp1500_1d database.
Safe to re-run: uses CREATE TABLE IF NOT EXISTS. Idempotent.

Usage:
  cd backend && ./venv/bin/python scripts/create_brain_tables.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.database import engine
from sqlalchemy import text

DDL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS strategy_brain (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_name       TEXT NOT NULL UNIQUE,
  strategy_class_path TEXT,
  n_runs              INT NOT NULL DEFAULT 0,
  n_trades            INT NOT NULL DEFAULT 0,
  first_run_date      DATE,
  last_run_date       DATE,
  best_run            JSONB,
  worst_run           JSONB,
  accumulated_insights JSONB,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE strategy_experiments ADD COLUMN IF NOT EXISTS strategy_class_path TEXT;

CREATE TABLE IF NOT EXISTS brain_chat_messages (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_name TEXT,
  role          TEXT NOT NULL,
  content       TEXT NOT NULL,
  context       JSONB,
  model_id      TEXT NOT NULL DEFAULT '',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_brain_chat_strategy ON brain_chat_messages(strategy_name);
"""


def main():
    with engine.begin() as conn:
        for stmt in [s.strip() for s in DDL.split(";") if s.strip()]:
            conn.execute(text(stmt))
    print("✅ Created 2 Trading Brain tables (idempotent).")


if __name__ == "__main__":
    main()
