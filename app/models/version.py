from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from datetime import datetime
from app.database import Base

class AppVersion(Base):
    __tablename__ = "app_versions"
    
    id = Column(Integer, primary_key=True)
    version = Column(String, unique=True, nullable=False)
    release_date = Column(DateTime, default=datetime.utcnow)
    changelog = Column(Text, nullable=True)
    is_stable = Column(Boolean, default=True)
    is_installed = Column(Boolean, default=False)
    installed_at = Column(DateTime, nullable=True)
    
    def __repr__(self):
        return f"<Version {self.version}>"

class UpdateCheck(Base):
    __tablename__ = "update_checks"
    
    id = Column(Integer, primary_key=True)
    last_check = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    latest_available = Column(String, nullable=True)
    current_installed = Column(String)
    update_available = Column(Boolean, default=False)
    auto_update_enabled = Column(Boolean, default=False)
    
    def __repr__(self):
        return f"<UpdateCheck {self.current_installed} -> {self.latest_available}>"
