from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///data/afterwatch.db"
    dry_run: bool = True
    schedule_hour: int = 3
    schedule_minute: int = 0
    
    class Config:
        env_prefix = "AFTERWATCH_"


settings = Settings()


async def load_settings_from_db():
    """Load settings from database on startup."""
    from app.database import async_session
    from app.models import AppSettings
    from sqlalchemy import select
    
    async with async_session() as session:
        result = await session.execute(select(AppSettings))
        app_settings = result.scalar_one_or_none()
        
        if app_settings:
            settings.dry_run = app_settings.dry_run


async def save_dry_run(value: bool):
    """Save dry_run setting to database."""
    from app.database import async_session
    from app.models import AppSettings
    from sqlalchemy import select
    
    async with async_session() as session:
        result = await session.execute(select(AppSettings))
        app_settings = result.scalar_one_or_none()
        
        if app_settings:
            app_settings.dry_run = value
        else:
            app_settings = AppSettings(dry_run=value)
            session.add(app_settings)
        
        await session.commit()
    
    settings.dry_run = value
