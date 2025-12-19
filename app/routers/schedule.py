from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path
from typing import Optional

from app.database import get_session
from app.models import Schedule
from app.version import __version__

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


async def get_or_create_schedule(session: AsyncSession) -> Schedule:
    """Get existing schedule or create default."""
    result = await session.execute(select(Schedule))
    schedule = result.scalar_one_or_none()
    
    if not schedule:
        schedule = Schedule()
        session.add(schedule)
        await session.commit()
        await session.refresh(schedule)
    
    return schedule


@router.get("/", response_class=HTMLResponse)
async def schedule_page(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """Schedule configuration page."""
    schedule = await get_or_create_schedule(session)
    
    # Parse days_enabled into list
    days_list = [int(d) for d in schedule.days_enabled.split(",") if d]
    
    # Get next run time from scheduler
    from app.scheduler import get_next_run_time
    next_run = get_next_run_time()
    
return templates.TemplateResponse(
        "schedule.html",
        {
            "request": request,
            "schedule": schedule,
            "version": __version__
        }
    )

@router.post("/save")
async def save_schedule(
    request: Request,
    schedule_type: str = Form("disabled"),
    daily_hour: int = Form(3),
    daily_minute: int = Form(0),
    interval_hours: int = Form(1),
    hour_filter: str = Form("all"),
    session: AsyncSession = Depends(get_session)
):
    """Save schedule configuration."""
    form_data = await request.form()
    
    # Get days from checkboxes
    days = []
    for i in range(7):
        if form_data.get(f"day_{i}"):
            days.append(str(i))
    days_enabled = ",".join(days) if days else "0,1,2,3,4,5,6"
    
    schedule = await get_or_create_schedule(session)
    
    schedule.schedule_type = schedule_type
    schedule.daily_hour = daily_hour
    schedule.daily_minute = daily_minute
    schedule.interval_hours = interval_hours
    schedule.hour_filter = hour_filter
    schedule.days_enabled = days_enabled
    schedule.enabled = schedule_type != "disabled"
    
    await session.commit()
    
    # Update the scheduler
    from app.scheduler import update_schedule_from_db
    await update_schedule_from_db()
    
    return RedirectResponse(url="/schedule", status_code=303)
