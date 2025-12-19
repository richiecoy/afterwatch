from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///data/afterwatch.db"
    test_mode: bool = True
    delay_days: int = 7
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
            settings.test_mode = app_settings.test_mode
            settings.delay_days = app_settings.delay_days


async def save_settings(test_mode: bool, delay_days: int):
    """Save settings to database."""
    from app.database import async_session
    from app.models import AppSettings
    from sqlalchemy import select
    
    async with async_session() as session:
        result = await session.execute(select(AppSettings))
        app_settings = result.scalar_one_or_none()
        
        if app_settings:
            app_settings.test_mode = test_mode
            app_settings.delay_days = delay_days
        else:
            app_settings = AppSettings(test_mode=test_mode, delay_days=delay_days)
            session.add(app_settings)
        
        await session.commit()
    
    settings.test_mode = test_mode
    settings.delay_days = delay_days
