#!/usr/bin/env python3
"""
Migration script to add search title filter columns to the watch_list table.
Run this script once to update your database schema.
"""

import os
from sqlalchemy import create_engine, text

def migrate_search_title_filters():
    """Add search title filter columns to watch_list table"""

    # Get database URL from environment
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise RuntimeError("❌ DATABASE_URL environment variable not set!")

    # Create engine
    if "sqlite" in DATABASE_URL:
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)

    # SQL to add new columns
    alter_statements = [
        "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS search_title_filter BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE watch_list ADD COLUMN IF NOT EXISTS custom_search_title VARCHAR(500);",
    ]

    # Update existing records to have default values (FALSE for boolean, NULL for text)
    update_statements = [
        "UPDATE watch_list SET search_title_filter = FALSE WHERE search_title_filter IS NULL;",
        # custom_search_title remains NULL by default (no update needed)
    ]

    try:
        with engine.connect() as conn:
            print("Starting database migration for search title filters...")

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
            print("  - search_title_filter (BOOLEAN) - Enables automatic stopword filtering")
            print("  - custom_search_title (VARCHAR(500)) - Custom search title override")

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False

    return True

if __name__ == "__main__":
    print("PBArr Search Title Filters Migration")
    print("=" * 45)

    # Run migration
    success = migrate_search_title_filters()

    if success:
        print("\n🎉 Migration completed! You can now use the search title filtering features.")
        print("This will help improve search results by removing common stopwords from series titles.")
        print("Restart your PBArr application to ensure all changes take effect.")
    else:
        print("\n💥 Migration failed! Please check the error messages above.")
        import sys
        sys.exit(1)
