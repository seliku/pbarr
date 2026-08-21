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

    # Wohin diese Sendung abgelegt wird. Leer heisst: aus dem Namen ableiten
    # bzw. einen vorhandenen Ordner der Bibliothek benutzen.
    ("watch_list.library_folder",
     "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS library_folder VARCHAR(255) DEFAULT ''"),

    # 'flat' legt alles unmittelbar in den Serienordner, 'seasons' in
    # Staffel-Unterordner. Flach ist die Vorgabe, weil es die Ablage ist, die
    # in bestehenden Bibliotheken am haeufigsten schon vorliegt.
    ("watch_list.season_layout",
     "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS season_layout VARCHAR(20) DEFAULT 'flat'"),

    # Wieviele der neuesten Folgen behalten werden. 0 heisst: alle behalten.
    ("watch_list.keep_latest",
     "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS keep_latest INTEGER DEFAULT 0"),

    # Wann eine Folge im Zuge der Rotation entfernt wurde. Die Zeile bleibt
    # bestehen, damit dieselbe Folge nicht beim naechsten Abgleich erneut
    # geholt wird - sonst entstuende eine Endlosschleife aus Laden und Loeschen.
    ("mediathek_downloads.rotated_at",
     "ALTER TABLE mediathek_downloads ADD COLUMN IF NOT EXISTS rotated_at TIMESTAMP"),

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

    ("mediathek_downloads.failed_attempts/last_error",
     "ALTER TABLE mediathek_downloads "
     "ADD COLUMN IF NOT EXISTS failed_attempts INTEGER DEFAULT 0, "
     "ADD COLUMN IF NOT EXISTS last_error TEXT, "
     "ADD COLUMN IF NOT EXISTS last_attempt TIMESTAMP"),

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
