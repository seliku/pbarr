import importlib
import os
import logging
from sqlalchemy.orm import Session
from app.models import ModuleState

logger = logging.getLogger(__name__)

class ModuleManager:
    def __init__(self, db: Session):
        self.db = db
        self.modules = {}
    
    def load_sources(self):
        """Lädt alle Source-Module (ARD, ZDF, etc.)"""
        source_dir = os.path.join(os.path.dirname(__file__), "..", "modules", "sources")
        
        for file in os.listdir(source_dir):
            if file.startswith("_") or file == "base.py" or file == "loader.py":
                continue
            
            module_name = file.replace(".py", "")
            
            try:
                mod = importlib.import_module(f"app.modules.sources.{module_name}")
                self.modules[module_name] = mod
                
                # In DB registrieren
                existing = self.db.query(ModuleState).filter_by(module_name=module_name).first()
                if not existing:
                    state = ModuleState(
                        module_name=module_name,
                        module_type="source",
                        enabled=True,
                        version="1.0.0"
                    )
                    self.db.add(state)
                
                logger.info(f"✓ Loaded source module: {module_name}")
            except Exception as e:
                logger.error(f"✗ Failed to load module {module_name}: {e}")
        
        self.db.commit()
        return self.modules
    
    def get_enabled_sources(self):
        """Gibt nur aktivierte Source-Module zurück"""
        enabled_modules = self.db.query(ModuleState).filter(
            ModuleState.module_type == "source",
            ModuleState.enabled == True
        ).all()
        
        return {m.module_name: self.modules.get(m.module_name) for m in enabled_modules}
