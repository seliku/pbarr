#!/usr/bin/env python3
"""Startup script - runs before FastAPI starts"""
import logging
from app.database import SessionLocal, init_db
from app.models.config import Config
from app.models.module_state import ModuleState
from app.models.matcher_config import MatcherConfig
from app.services.pattern_matcher import MatcherTemplates

logger = logging.getLogger(__name__)

def init_configs():
    """Initialize base configs if they don't exist"""
    init_db()
    db = SessionLocal()
    
    try:
        # Basis Configs
        configs = [
            # API Keys
            Config(
                key="tvdb_api_key",
                value="",
                module="tvdb",
                secret=True,
                data_type="string",
                description="TVDB API Key für Show/Episode Matching (https://www.thetvdb.com/api-information)"
            ),
            Config(
                key="ard_mediathek_enabled",
                value="true",
                module="ard",
                secret=False,
                data_type="bool",
                description="ARD Mediathek Scraping aktivieren"
            ),
            # Download Settings
            Config(
                key="download_path",
                value="/app/downloads",
                module="core",
                secret=False,
                data_type="string",
                description="Pfad wo Downloads gespeichert werden"
            ),
            Config(
                key="max_concurrent_downloads",
                value="2",
                module="downloader",
                secret=False,
                data_type="int",
                description="Maximale gleichzeitige Downloads"
            ),
            Config(
                key="download_retry_count",
                value="3",
                module="downloader",
                secret=False,
                data_type="int",
                description="Anzahl der Wiederholungen bei fehlgeschlagenen Downloads"
            ),
            # Scheduler Settings
            Config(
                key="log_level",
                value="INFO",
                module="core",
                secret=False,
                data_type="string",
                description="Logging Level (DEBUG, INFO, WARNING, ERROR)"
            ),
            Config(
                key="scheduler_enabled",
                value="true",
                module="core",
                secret=False,
                data_type="bool",
                description="Scheduler für regelmäßige Updates aktivieren"
            ),
            Config(
                key="update_check_interval",
                value="3",
                module="core",
                secret=False,
                data_type="int",
                description="Stunde (0-23) für tägliche Update-Checks"
            ),
            # Optional Proxy
            Config(
                key="socks5_proxy",
                value="",
                module="proxy",
                secret=False,
                data_type="string",
                description="Optional: SOCKS5 Proxy (socks5://host:port)"
            ),
        ]
        
        for config in configs:
            existing = db.query(Config).filter_by(key=config.key).first()
            if not existing:
                db.add(config)
                logger.info(f"✓ Added config: {config.key}")
        
        # Module States
        modules = [
            ModuleState(
                module_name="ard",
                module_type="source",
                enabled=True,
                version="0.1.0"
            ),
            ModuleState(
                module_name="tvdb",
                module_type="matcher",
                enabled=True,
                version="1.0.0"
            ),
        ]
        
        for module in modules:
            existing = db.query(ModuleState).filter_by(module_name=module.module_name).first()
            if not existing:
                db.add(module)
                logger.info(f"✓ Added module: {module.module_name}")
        
        # Default Matcher Configs
        default_matchers = [
            MatcherConfig(
                name="ard_default",
                source="ard",
                **MatcherTemplates.ARD_SIMPLE
            ),
            MatcherConfig(
                name="zdf_default",
                source="zdf",
                **MatcherTemplates.ZDF_STANDARD
            ),
        ]
        
        for matcher in default_matchers:
            existing = db.query(MatcherConfig).filter_by(name=matcher.name).first()
            if not existing:
                db.add(matcher)
                logger.info(f"✓ Added matcher: {matcher.name}")
        
        db.commit()
        logger.info("✅ Base config initialized")
    
    except Exception as e:
        logger.error(f"✗ Config init failed: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    init_configs()
