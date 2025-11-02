#!/usr/bin/env python3
"""
Migration script to add new columns to the watch_list table for Sonarr integration.
Run this script once to update your database schema.
"""

import os
from sqlalchemy import create_engine, text

def migrate_watchlist_table():
    """Add new columns to watch_list table"""

    # Get database URL from environment
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pbuser:pbpass@postgres:5432/pbarr")

    # Create engine
    if "sqlite" in DATABASE_URL:
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)

    # SQL to add new columns
    alter_statements = [
        "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS tagged_in_sonarr BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS tagged_at TIMESTAMP;",
        "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS pbarr_tag_id INTEGER;",
        "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS sonarr_series_id INTEGER;",
        "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS import_source VARCHAR(50) DEFAULT 'manual';",
        "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS episodes_found INTEGER DEFAULT 0;",
        "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS mediathek_episodes_count INTEGER DEFAULT 0;",
        # Filter fields for episode matching with defaults
        "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS min_duration INTEGER DEFAULT 0;",
        "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS max_duration INTEGER DEFAULT 360;",
        "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS exclude_keywords VARCHAR(1000) DEFAULT 'klare Sprache,Audiodeskription,Gebärdensprache';",
        "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS include_senders VARCHAR(1000) DEFAULT '';",
    ]

    # Update existing records to have default values
    update_statements = [
        "UPDATE watch_list SET min_duration = 0 WHERE min_duration IS NULL;",
        "UPDATE watch_list SET max_duration = 360 WHERE max_duration IS NULL;",
        "UPDATE watch_list SET exclude_keywords = 'klare Sprache,Audiodeskription,Gebärdensprache' WHERE exclude_keywords IS NULL;",
        "UPDATE watch_list SET include_senders = '' WHERE include_senders IS NULL;",
    ]

    try:
        with engine.connect() as conn:
            print("Starting database migration for watch_list table...")

            for statement in alter_statements:
                print(f"Executing: {statement}")
                conn.execute(text(statement))
                conn.commit()

            # Update existing records with default values
            print("Setting default values for existing records...")
            for statement in update_statements:
                print(f"Executing: {statement}")
                conn.execute(text(statement))
                conn.commit()

            print("✅ Migration completed successfully!")
            print("New columns added to watch_list table:")
            print("  - tagged_in_sonarr (BOOLEAN)")
            print("  - tagged_at (TIMESTAMP)")
            print("  - pbarr_tag_id (INTEGER)")
            print("  - sonarr_series_id (INTEGER)")
            print("  - import_source (VARCHAR(50))")
            print("  - episodes_found (INTEGER)")
            print("  - mediathek_episodes_count (INTEGER)")
            print("  - min_duration (INTEGER)")
            print("  - max_duration (INTEGER)")
            print("  - exclude_keywords (VARCHAR(1000))")
            print("  - include_senders (VARCHAR(1000))")

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False

    return True

if __name__ == "__main__":
    print("PBArr WatchList Table Migration")
    print("=" * 40)

    # Run migration
    success = migrate_watchlist_table()

    if success:
        print("\n🎉 Migration completed! You can now use the new Sonarr integration features.")
        print("Restart your PBArr application to ensure all changes take effect.")
    else:
        print("\n💥 Migration failed! Please check the error messages above.")
        import sys
        sys.exit(1)
