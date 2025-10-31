import logging
from app.database import SessionLocal
from app.models.config import Config

logger = logging.getLogger(__name__)

def init_configs():
    """Initialize default configs"""
    db = SessionLocal()
    
    configs = [
        # TVDB
        ("tvdb_api_key", "", "core", False, "string", "TVDB API Key für Episode-Daten"),
        
        # MediathekViewWeb
        ("mediathekviewweb_enabled", "true", "mediathekviewweb", False, "boolean", "MediathekViewWeb aktivieren"),
        
        # Download
        ("download_path", "/app/downloads", "download", False, "string", "Download-Pfad"),
        ("max_concurrent_downloads", "2", "download", False, "integer", "Max. gleichzeitige Downloads"),
        ("download_retry_count", "3", "download", False, "integer", "Retry-Versuche bei fehlgeschlagenen Downloads"),
        
        # System
        ("log_level", "INFO", "system", False, "string", "Log-Level (DEBUG, INFO, WARNING, ERROR)"),
        ("scheduler_enabled", "true", "system", False, "boolean", "Scheduler aktivieren"),
        ("update_check_interval", "86400", "system", False, "integer", "Update-Check Intervall (Sekunden)"),
        
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
    from app.models.module_state import ModuleState
    
    modules = [
        ("mediathekviewweb", "source", "1.0.0"),
        ("tvdb", "metadata", "1.0.0"),
    ]
    
    for name, mod_type, version in modules:
        existing = db.query(ModuleState).filter_by(module_name=name).first()
        if not existing:
            module_state = ModuleState(
                module_name=name,
                module_type=mod_type,
                version=version,
                enabled=True
            )
            db.add(module_state)
            logger.info(f"✓ Added module: {name}")
    
    # Matcher Configs
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
    
    db.commit()
    db.close()
    logger.info("✅ Base config initialized")
