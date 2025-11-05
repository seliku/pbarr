#!/usr/bin/env python3
"""
Migration script to create episode_monitoring_state table for smart monitoring detection.
Run this script once to add the new table to your database.
"""

import os
from sqlalchemy import create_engine, text

def migrate_episode_monitoring_table():
    """Create episode_monitoring_state table"""

    # Get database URL from environment
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise RuntimeError("❌ DATABASE_URL environment variable not set!")

    # Create engine
    if "sqlite" in DATABASE_URL:
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)

    # SQL to create new table
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS episode_monitoring_state (
        id SERIAL PRIMARY KEY,
        sonarr_series_id INTEGER NOT NULL,
        season INTEGER NOT NULL,
        episode INTEGER NOT NULL,
        monitored BOOLEAN DEFAULT FALSE,
        checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(sonarr_series_id, season, episode)
    );
    """

    try:
        with engine.connect() as conn:
            print("Starting database migration for episode_monitoring_state table...")

            print(f"Executing: {create_table_sql.strip()}")
            conn.execute(text(create_table_sql))
            conn.commit()

            print("✅ Migration completed successfully!")
            print("New table created: episode_monitoring_state")
            print("Columns:")
            print("  - id (SERIAL PRIMARY KEY)")
            print("  - sonarr_series_id (INTEGER NOT NULL)")
            print("  - season (INTEGER NOT NULL)")
            print("  - episode (INTEGER NOT NULL)")
            print("  - monitored (BOOLEAN DEFAULT FALSE)")
            print("  - checked_at (TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            print("  - UNIQUE(sonarr_series_id, season, episode)")

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False

    return True

if __name__ == "__main__":
    print("PBArr Episode Monitoring State Table Migration")
    print("=" * 50)

    # Run migration
    success = migrate_episode_monitoring_table()

    if success:
        print("\n🎉 Migration completed! You can now use smart episode monitoring detection.")
        print("Restart your PBArr application to ensure all changes take effect.")
    else:
        print("\n💥 Migration failed! Please check the error messages above.")
        import sys
        sys.exit(1)
