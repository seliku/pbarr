from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class ModuleState(Base):
    __tablename__ = "module_states"
    
    id = Column(Integer, primary_key=True)
    module_name = Column(String, unique=True, nullable=False)  # "ard", "auth_basic", "proxy_socks5"
    module_type = Column(String)  # "source", "auth", "proxy", "downloader"
    
    enabled = Column(Boolean, default=True)
    version = Column(String, default="1.0.0")
    
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    error_log = Column(Text, nullable=True)
    
    def __repr__(self):
        return f"<Module {self.module_name} [{'✓' if self.enabled else '✗'}]>"
