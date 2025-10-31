#!/usr/bin/env python3
import sys
sys.path.insert(0, '/root/pbarr')

from app.database import SessionLocal, init_db
from app.models.config import Config
from app.models.module_state import ModuleState

# Initialisiere DB
init_db()

db = SessionLocal()

# Basis Configs
configs = [
    Config(
        key="tvdb_api_key",
        value="",  # User muss eingeben
        module="tvdb",
        secret=True,
        data_type="string",
        description="TVDB API Key für Show/Episode Matching"
    ),
    Config(
        key="download_path",
        value="/data/downloads",
        module="core",
        secret=False,
        data_type="string",
        description="Pfad wo Downloads gespeichert werden"
    ),
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
        value="3",  # 3 Uhr nachts
        module="core",
        secret=False,
        data_type="int",
        description="Stunde (0-23) für tägliche Update-Checks"
    ),
]

for config in configs:
    existing = db.query(Config).filter_by(key=config.key).first()
    if not existing:
        db.add(config)
        print(f"✓ Added config: {config.key}")
    else:
        print(f"→ Config already exists: {config.key}")

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
        print(f"✓ Added module: {module.module_name}")
    else:
        print(f"→ Module already exists: {module.module_name}")

db.commit()
db.close()

print("\n✅ Database initialized with base config!")