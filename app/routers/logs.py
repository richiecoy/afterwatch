from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path
from typing import Optional

from app.database import get_session
from app.models import ProcessLog, ProcessRun

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/", response_class=HTMLResponse)
async def logs_page(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=100),
    series: Optional[str] = Query(None),
    success_only: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_session)
):
    """View processing logs."""
    # Convert success_only string to bool
    success_filter = None
    if success_only == "true":
        success_filter = True
    elif success_only == "false":
        success_filter = False
    
    # Build query
    query = select(ProcessLog).order_by(desc(ProcessLog.timestamp))
    
    if series:
        query = query.where(ProcessLog.series_name.ilike(f"%{series}%"))
    
    if success_filter is not None:
        query = query.where(ProcessLog.success == success_filter)
    
    # Paginate
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)
    
    result = await session.execute(query)
    logs = result.scalars().all()
    
    # Get recent runs
    runs_result = await session.execute(
        select(ProcessRun).order_by(desc(ProcessRun.started_at)).limit(10)
    )
    runs = runs_result.scalars().all()
    
    return templates.TemplateResponse(
        "logs.html",
        {
            "request": request,
            "logs": logs,
            "runs": runs,
            "page": page,
            "per_page": per_page,
            "series_filter": series,
            "success_filter": success_filter
        }
    )


@router.get("/run/{run_id}", response_class=HTMLResponse)
async def run_details(
    request: Request,
    run_id: int,
    session: AsyncSession = Depends(get_session)
):
    """View details of a specific processing run."""
    run = await session.get(ProcessRun, run_id)
    
    if not run:
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "message": "Run not found"},
            status_code=404
        )
    
    # Get logs for this run
    # Note: We'd need to add run_id to ProcessLog to properly link these
    # For now, get logs around the run time
    result = await session.execute(
        select(ProcessLog).where(
            ProcessLog.timestamp >= run.started_at,
            ProcessLog.timestamp <= (run.completed_at or run.started_at)
        ).order_by(ProcessLog.timestamp)
    )
    logs = result.scalars().all()
    
    return templates.TemplateResponse(
        "run_details.html",
        {
            "request": request,
            "run": run,
            "logs": logs
        }
    )
