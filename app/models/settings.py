from sqlalchemy import String, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class AppSettings(Base):
    """Stores application settings."""
    
    __tablename__ = "app_settings"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    delay_days: Mapped[int] = mapped_column(Integer, default=7)
