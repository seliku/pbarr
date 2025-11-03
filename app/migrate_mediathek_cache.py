#!/usr/bin/env python3
"""
Migration script to add new columns to the mediathek_cache table for improved matching.
Run this script once to update your database schema.
"""

import os
from sqlalchemy import create_engine, text

def migrate_mediathek_cache_table():
    """Add new columns to mediathek_cache table"""

    # Get database URL from environment
    DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pbuser:pbpass@postgres:5432/pbarr")

    # Create engine
    if "sqlite" in DATABASE_URL:
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)

    # SQL to add new columns
    alter_statements = [
        "ALTER TABLE mediathek_cache ADD COLUMN IF NOT EXISTS match_confidence INTEGER;",
        "ALTER TABLE mediathek_cache ADD COLUMN IF NOT EXISTS match_type VARCHAR(50);",
    ]

    try:
        with engine.connect() as conn:
            print("Starting database migration for mediathek_cache table...")

            for statement in alter_statements:
                print(f"Executing: {statement}")
                conn.execute(text(statement))
                conn.commit()

            print("✅ Migration completed successfully!")
            print("New columns added to mediathek_cache table:")
            print("  - match_confidence (INTEGER)")
            print("  - match_type (VARCHAR(50))")

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False

    return True

if __name__ == "__main__":
    print("PBArr MediathekCache Table Migration")
    print("=" * 40)

    # Run migration
    success = migrate_mediathek_cache_table()

    if success:
        print("\n🎉 Migration completed! You can now use the improved matching features.")
        print("Restart your PBArr application to ensure all changes take effect.")
    else:
        print("\n💥 Migration failed! Please check the error messages above.")
        import sys
        sys.exit(1)
