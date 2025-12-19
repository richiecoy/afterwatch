from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path
from typing import Optional

from app.database import get_session
from app.models import Schedule
from app.scheduler import update_schedule_from_db
from app.version import __version__

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/", response_class=HTMLResponse)
async def schedule_page(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """Schedule configuration page."""
    result = await session.execute(select(Schedule))
    schedule = result.scalar_one_or_none()
    
    return templates.TemplateResponse(
        "schedule.html",
        {
            "request": request,
            "schedule": schedule,
            "version": __version__
        }
    )


@router.post("/")
async def save_schedule(
    request: Request,
    enabled: bool = Form(False),
    schedule_type: str = Form("daily"),
    daily_hour: int = Form(3),
    daily_minute: int = Form(0),
    interval_hours: int = Form(6),
    hour_filter: Optional[str] = Form(None),
    session: AsyncSession = Depends(get_session)
):
    """Save schedule configuration."""
    result = await session.execute(select(Schedule))
    schedule = result.scalar_one_or_none()
    
    if schedule:
        schedule.enabled = enabled
        schedule.schedule_type = schedule_type
        schedule.daily_hour = daily_hour
        schedule.daily_minute = daily_minute
        schedule.interval_hours = interval_hours
        schedule.hour_filter = hour_filter
    else:
        schedule = Schedule(
            enabled=enabled,
            schedule_type=schedule_type,
            daily_hour=daily_hour,
            daily_minute=daily_minute,
            interval_hours=interval_hours,
            hour_filter=hour_filter
        )
        session.add(schedule)
    
    await session.commit()
    
    # Update the scheduler
    await update_schedule_from_db()
    
    return RedirectResponse(url="/schedule", status_code=303)
