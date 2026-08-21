import logging
import os
import subprocess
import sys
from pathlib import Path
from app.database import SessionLocal
from app.models.config import Config


logger = logging.getLogger(__name__)

# Hardcoded download path in container (maps to completed directory on host)
PBARR_DOWNLOAD_PATH = Path("/app/downloads/completed")


def init_config():
    """Initialize default configs"""
    db = SessionLocal()
    
    configs = [
        # TVDB
        ("tvdb_api_key", "", "core", False, "string", "TVDB API Key für Episode-Daten"),

        # MediathekViewWeb
        ("mediathekviewweb_enabled", "true", "mediathekviewweb", False, "boolean", "MediathekViewWeb aktivieren"),

        # Download (path is now hardcoded to /app/downloads)
        ("max_concurrent_downloads", "2", "download", False, "integer", "Gleichzeitige Downloads"),
        ("download_retry_count", "3", "download", False, "integer", "Download Versuche"),

        # System
        ("log_level", "INFO", "system", False, "string", "Log-Level (DEBUG, INFO, WARNING, ERROR)"),
        ("scheduler_enabled", "true", "system", False, "boolean", "Hintergrund-Scheduler für automatische Aufgaben aktivieren (Cache-Sync, Cleanup, etc.)"),
        ("update_check_interval", "86400", "system", False, "integer", "Automatischer Update-Check Intervall für PBArr-Versionen (Sekunden)"),

        # Sonarr Integration
        ("sonarr_url", "", "sonarr", False, "string", "Sonarr URL (z.B. http://localhost:8989)"),
        ("sonarr_api_key", "", "sonarr", True, "string", "Sonarr API Key"),
    ]
    
    for key, value, module, secret, data_type, description in configs:
        existing = db.query(Config).filter_by(key=key).first()
        if not existing:
            config = Config(
                key=key,
                value=value,
                module=module,
                secret=secret,
                data_type=data_type,
                description=description
            )
            db.add(config)
            logger.info(f"✓ Added config: {key}")
    
    # Module States
    try:
        from app.models.module_state import ModuleState
        
        from app.modules.sources.registry import discover_sources

        # Hier stand frueher eine feste Liste mit "mediathekviewweb" und "tvdb".
        # Sie legte "tvdb" auch dann wieder an, wenn das Modul laengst geloescht
        # war - die Oberflaeche zeigte dann ein aktives Modul samt Eingabefeld
        # fuer einen Dienst, den es nicht mehr gibt. Wer eine Quelle hinzufuegt
        # oder entfernt, soll an dieser Stelle nichts nachpflegen muessen.
        gefunden = discover_sources(refresh=True)

        for name, quelle in gefunden.items():
            existing = db.query(ModuleState).filter_by(module_name=name).first()
            if existing:
                existing.version = quelle.version
            else:
                db.add(ModuleState(
                    module_name=name,
                    module_type="source",
                    version=quelle.version,
                    enabled=True,
                ))
                logger.info(f"✓ Neue Quelle eingetragen: {name}")

        # Zeilen von Quellen, die es nicht mehr gibt, verschwinden mit.
        for zeile in db.query(ModuleState).all():
            if zeile.module_name not in gefunden:
                logger.info(f"✗ Verwaiste Quelle entfernt: {zeile.module_name}")
                db.delete(zeile)
    except Exception as e:
        logger.warning(f"ModuleState table might not exist yet: {e}")
    
    # Matcher Configs
    try:
        from app.models.matcher_config import MatcherConfig
        
        existing = db.query(MatcherConfig).filter_by(name="mediathekviewweb_default").first()
        if not existing:
            matcher = MatcherConfig(
                name="mediathekviewweb_default",
                source="mediathekviewweb",
                strategy="regex",
                enabled=True
            )
            db.add(matcher)
            logger.info(f"✓ Added matcher: mediathekviewweb_default")
    except Exception as e:
        logger.warning(f"MatcherConfig table might not exist yet: {e}")
    
    # Remove deprecated configs
    deprecated_keys = ["sonarr_download_path", "download_path", "sonarr_download_path_host"]
    for key in deprecated_keys:
        try:
            deprecated_config = db.query(Config).filter_by(key=key).first()
            if deprecated_config:
                db.delete(deprecated_config)
                logger.info(f"✓ Removed deprecated config: {key}")
        except Exception as e:
            logger.warning(f"Could not remove deprecated config {key}: {e}")

    db.commit()
    db.close()
    logger.info("✅ Base config initialized")


def load_enabled_modules():
    """Load enabled modules (placeholder for future implementation)"""
    logger.info("✓ Modules loaded")


def init_download_directory():
    """Initialize the download directory"""
    try:
        if not PBARR_DOWNLOAD_PATH.exists():
            PBARR_DOWNLOAD_PATH.mkdir(parents=True, exist_ok=True)
            logger.info(f"📂 Created download directory: {PBARR_DOWNLOAD_PATH}")
        else:
            logger.info(f"📂 Download directory exists: {PBARR_DOWNLOAD_PATH}")

        # Log the path info for user clarity
        logger.info(f"✅ PBArr will download to: {PBARR_DOWNLOAD_PATH}")
        logger.info("ℹ️  Configure host mapping in docker-compose.yml to control where downloads go on your system")

    except Exception as e:
        logger.error(f"❌ Failed to initialize download directory: {e}")
        raise


def run_migrations():
    """Run all pending database migrations automatically"""
    try:
        logger.info("🔄 Checking for pending database migrations...")

        # Find all migration scripts in the app directory (where this file is located)
        app_dir = Path(__file__).parent
        migration_files = []

        # Look for files starting with 'migrate_'
        for file_path in app_dir.glob("migrate_*.py"):
            migration_files.append(file_path)

        if not migration_files:
            logger.info("✅ No migration scripts found")
            return

        logger.info(f"📋 Found {len(migration_files)} migration script(s)")

        # Run each migration script
        for migration_file in sorted(migration_files):
            script_name = migration_file.name
            logger.info(f"🚀 Running migration: {script_name}")

            try:
                # Run the migration script as a subprocess
                result = subprocess.run([
                    sys.executable, str(migration_file)
                ], capture_output=True, text=True, cwd=app_dir)

                if result.returncode == 0:
                    logger.info(f"✅ Migration {script_name} completed successfully")
                    if result.stdout.strip():
                        logger.debug(f"Migration output: {result.stdout.strip()}")
                else:
                    logger.error(f"❌ Migration {script_name} failed with exit code {result.returncode}")
                    if result.stderr:
                        logger.error(f"Migration error: {result.stderr.strip()}")
                    # Continue with other migrations even if one fails
                    continue

            except Exception as e:
                logger.error(f"❌ Failed to run migration {script_name}: {e}")
                continue

        logger.info("✅ Database migration check completed")

    except Exception as e:
        logger.error(f"❌ Database migration check failed: {e}")
        # Don't raise exception - allow app to continue even if migrations fail
