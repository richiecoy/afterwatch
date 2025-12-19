from sqlalchemy import String, Integer, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from app.database import Base


class WatchedEpisode(Base):
    """Tracks when episodes were first seen as watched by all required users."""
    
    __tablename__ = "watched_episodes"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    file_path: Mapped[str] = mapped_column(String(1000), unique=True, index=True)
    series_name: Mapped[str] = mapped_column(String(500))
    season_number: Mapped[int] = mapped_column(Integer)
    episode_number: Mapped[int] = mapped_column(Integer)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
