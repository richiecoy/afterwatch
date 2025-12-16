from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path


class Settings(BaseSettings):
    """Application settings."""
    
    # Database
    data_dir: Path = Field(default=Path("/app/data"))
    database_url: str = Field(default="sqlite+aiosqlite:////app/data/afterwatch.db")
    
    # Server
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8199)
    
    # Scheduler
    schedule_enabled: bool = Field(default=True)
    schedule_hour: int = Field(default=3)  # 3 AM
    schedule_minute: int = Field(default=0)
    
    # Processing
    dry_run: bool = Field(default=True)  # Start in dry-run mode for safety
    
    class Config:
        env_prefix = "AFTERWATCH_"


settings = Settings()

# Ensure data directory exists
settings.data_dir.mkdir(parents=True, exist_ok=True)
