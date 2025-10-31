from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from datetime import datetime
from app.database import Base

class Config(Base):
    __tablename__ = "config"
    
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(Text)
    module = Column(String, default="core")
    secret = Column(Boolean, default=False)
    data_type = Column(String, default="string")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    description = Column(String, nullable=True)
    
    def __repr__(self):
        return f"<Config {self.key}={self.value[:20] if self.value else 'None'}...>"
