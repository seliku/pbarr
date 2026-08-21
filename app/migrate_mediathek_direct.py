#!/usr/bin/env python3
"""
Migration for the direct Mediathek path (alpha).

Adds what is needed to fetch straight from MediathekViewWeb, without Sonarr
and without TVDB:

  watch_list.quality            preferred stream quality (hd | normal | low)
  watch_list.search_topic       the topic as it is called in the Mediathek;
                                empty means "use show_name"
  mediathek_downloads           one row per fetched item, keyed by its source
                                URL - the only identity that stays stable

Season/episode numbers are deliberately not used any more. Two independent
TVDB consumers (pbarr and Sonarr) produced conflicting numbering, so nothing
ever matched. Files are named by broadcast date instead, which Plex handles
natively for date-based shows.
"""

import os
from sqlalchemy import create_engine, text


STATEMENTS = [
    ("watch_list.quality",
     "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS quality VARCHAR(20) DEFAULT 'hd'"),

    ("watch_list.search_topic",
     "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS search_topic VARCHAR(255) DEFAULT ''"),

    ("mediathek_downloads", """
     CREATE TABLE IF NOT EXISTS mediathek_downloads (
         id SERIAL PRIMARY KEY,
         watch_key VARCHAR(50) NOT NULL,
         show_name VARCHAR(255) NOT NULL,
         source_url TEXT NOT NULL,
         channel VARCHAR(100),
         topic VARCHAR(255),
         title VARCHAR(500),
         aired TIMESTAMP,
         duration_seconds INTEGER,
         quality VARCHAR(20),
         file_path TEXT,
         file_size BIGINT,
         downloaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
         UNIQUE (watch_key, source_url)
     )"""),

    ("mediathek_downloads.season/episode",
     "ALTER TABLE mediathek_downloads "
     "ADD COLUMN IF NOT EXISTS season INTEGER, "
     "ADD COLUMN IF NOT EXISTS episode INTEGER"),

    ("Index mediathek_downloads.watch_key",
     "CREATE INDEX IF NOT EXISTS ix_mediathek_downloads_watch_key "
     "ON mediathek_downloads (watch_key)"),
]


def migrate():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("❌ DATABASE_URL environment variable not set!")

    if "sqlite" in database_url:
        engine = create_engine(database_url, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(database_url, pool_pre_ping=True, pool_recycle=3600)

    print("Starting migration for the direct Mediathek path...")

    with engine.connect() as conn:
        for label, sql in STATEMENTS:
            conn.execute(text(sql))
            print(f"  ✅ {label}")
        conn.commit()

    print("✅ Migration completed")


if __name__ == "__main__":
    migrate()
