from sqlalchemy import String, Integer, Boolean
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Schedule(Base):
    """Stores scheduling configuration."""
    
    __tablename__ = "schedule"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    
    # Schedule type: "disabled", "daily", "hourly", "interval"
    schedule_type: Mapped[str] = mapped_column(String(50), default="disabled")
    
    # For daily: what time to run
    daily_hour: Mapped[int] = mapped_column(Integer, default=3)
    daily_minute: Mapped[int] = mapped_column(Integer, default=0)
    
    # For interval: how many hours between runs
    interval_hours: Mapped[int] = mapped_column(Integer, default=1)
    
    # For hourly: odd, even, or all hours
    hour_filter: Mapped[str] = mapped_column(String(20), default="all")  # "all", "odd", "even"
    
    # Days to run (comma-separated: "0,1,2,3,4,5,6" where 0=Monday)
    days_enabled: Mapped[str] = mapped_column(String(50), default="0,1,2,3,4,5,6")
    
    # Master enable
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
