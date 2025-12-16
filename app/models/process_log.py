from sqlalchemy import String, Integer, DateTime, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from app.database import Base


class ProcessLog(Base):
    """Logs each episode processing action."""
    
    __tablename__ = "process_logs"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Episode info
    series_name: Mapped[str] = mapped_column(String(500))
    season_number: Mapped[int] = mapped_column(Integer)
    episode_number: Mapped[int] = mapped_column(Integer)
    episode_title: Mapped[str] = mapped_column(String(500), nullable=True)
    
    # File info
    original_path: Mapped[str] = mapped_column(String(1000))
    original_size_bytes: Mapped[int] = mapped_column(Integer)
    strm_path: Mapped[str] = mapped_column(String(1000))
    
    # Status
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    
    # Actions taken
    file_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    strm_created: Mapped[bool] = mapped_column(Boolean, default=False)
    sonarr_renamed: Mapped[bool] = mapped_column(Boolean, default=False)
    sonarr_unmonitored: Mapped[bool] = mapped_column(Boolean, default=False)
    season_unmonitored: Mapped[bool] = mapped_column(Boolean, default=False)


class ProcessRun(Base):
    """Logs each processing run (scheduled or manual)."""
    
    __tablename__ = "process_runs"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    
    trigger: Mapped[str] = mapped_column(String(50))  # 'scheduled', 'manual'
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    
    episodes_processed: Mapped[int] = mapped_column(Integer, default=0)
    episodes_failed: Mapped[int] = mapped_column(Integer, default=0)
    bytes_reclaimed: Mapped[int] = mapped_column(Integer, default=0)
    
    status: Mapped[str] = mapped_column(String(50), default="running")  # running, completed, failed
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
