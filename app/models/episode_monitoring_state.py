from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime
from app.database import Base

class EpisodeMonitoringState(Base):
    """Tracks which episodes are monitored in Sonarr for change detection"""
    __tablename__ = "episode_monitoring_state"

    id = Column(Integer, primary_key=True)
    sonarr_series_id = Column(Integer, nullable=False)
    season = Column(Integer, nullable=False)
    episode = Column(Integer, nullable=False)
    monitored = Column(Boolean, default=False)
    checked_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<EpisodeMonitoringState S{self.season}E{self.episode} monitored={self.monitored}>"
