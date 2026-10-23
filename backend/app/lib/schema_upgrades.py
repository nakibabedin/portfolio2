"""Columns added after the database was created, applied when the app starts.

The production database sits on an RDS instance that is only reachable from
inside the VPC, so a script run from a laptop (the update_schema_*.py files)
can't reach it. Every statement here is idempotent and additive -- nullable, or
with a default -- so running it on each start is safe, and the image that needs
a column is the one that adds it. Append new statements; never edit old ones.
"""

import logging

from sqlalchemy import text

from app.database import engine

logger = logging.getLogger(__name__)

STATEMENTS = [
    "ALTER TABLE posts ADD COLUMN IF NOT EXISTS instagram_hashtags TEXT[] NOT NULL DEFAULT '{}'",
    "ALTER TABLE posts ADD COLUMN IF NOT EXISTS instagram_collaborators TEXT[] NOT NULL DEFAULT '{}'",
    "ALTER TABLE posts ADD COLUMN IF NOT EXISTS instagram_location_id VARCHAR(32)",
    "ALTER TABLE posts ADD COLUMN IF NOT EXISTS instagram_location_name VARCHAR(255)",
]


def apply() -> None:
    """Never raises: a database that's briefly unreachable at boot shouldn't
    stop the app from starting, and the next start will try again."""
    try:
        with engine.begin() as conn:
            for statement in STATEMENTS:
                conn.execute(text(statement))
        logger.info("[schema] %d upgrade statements applied", len(STATEMENTS))
    except Exception:
        logger.exception("[schema] upgrade failed")
