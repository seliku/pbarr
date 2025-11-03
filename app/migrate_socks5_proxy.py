#!/usr/bin/env python3
"""
Migration script to add SOCKS5 proxy configuration to the config table.
Run this script once to add the SOCKS5 proxy setting.
"""

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import sys
from pathlib import Path

# Add the app directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from app.database import engine
from app.models.config import Config

def migrate_socks5_proxy_setting():
    """Add SOCKS5 proxy setting to config table"""

    # Create session
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    try:
        print("Starting SOCKS5 proxy configuration migration...")

        # Check if SOCKS5 proxy setting already exists
        existing = db.query(Config).filter_by(key="socks5_proxy").first()

        if existing:
            print("✅ SOCKS5 proxy setting already exists, skipping migration")
            return True

        # Create SOCKS5 proxy config entry
        socks5_config = Config(
            key="socks5_proxy",
            value="",  # Empty by default (no proxy)
            module="network",
            secret=False,
            data_type="string",
            description="SOCKS5 Proxy URL (format: socks5://user:pass@host:port or socks5://host:port). Leave empty to disable proxy."
        )

        db.add(socks5_config)
        db.commit()
        db.refresh(socks5_config)

        print("✅ SOCKS5 proxy configuration added successfully!")
        print("Setting details:")
        print(f"  - Key: {socks5_config.key}")
        print(f"  - Module: {socks5_config.module}")
        print(f"  - Description: {socks5_config.description}")
        print(f"  - Default value: (empty - no proxy)")

        return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        db.rollback()
        return False
    finally:
        db.close()

if __name__ == "__main__":
    print("PBArr SOCKS5 Proxy Configuration Migration")
    print("=" * 50)

    # Run migration
    success = migrate_socks5_proxy_setting()

    if success:
        print("\n🎉 Migration completed! SOCKS5 proxy support is now available.")
        print("You can configure the SOCKS5 proxy in the Admin Panel under Configuration.")
        print("Format: socks5://user:pass@host:port or socks5://host:port")
        print("Leave empty to disable proxy (default).")
    else:
        print("\n💥 Migration failed! Please check the error messages above.")
        import sys
        sys.exit(1)
