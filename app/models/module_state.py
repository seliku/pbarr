from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from datetime import datetime
from app.database import Base

class ModuleState(Base):
    __tablename__ = "module_states"
    
    id = Column(Integer, primary_key=True)
    module_name = Column(String, unique=True, nullable=False)
    module_type = Column(String)
    
    enabled = Column(Boolean, default=True)
    version = Column(String, default="1.0.0")
    
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    error_log = Column(Text, nullable=True)
    
    def __repr__(self):
        return f"<Module {self.module_name} [{'✓' if self.enabled else '✗'}]>"
