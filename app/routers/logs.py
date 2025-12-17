from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path
from typing import Optional

from app.database import get_session
from app.models import ProcessLog, ProcessRun

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


def format_size(bytes_val: int) -> str:
    """Format bytes to human readable size."""
    if bytes_val >= 1024 ** 4:
        return f"{bytes_val / (1024 ** 4):.2f} TB"
    elif bytes_val >= 1024 ** 3:
        return f"{bytes_val / (1024 ** 3):.2f} GB"
    elif bytes_val >= 1024 ** 2:
        return f"{bytes_val / (1024 ** 2):.2f} MB"
    elif bytes_val >= 1024:
        return f"{bytes_val / 1024:.2f} KB"
    else:
        return f"{bytes_val} B"


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
    
    # Build query - sort by most recent first
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
            "success_filter": success_filter,
            "format_size": format_size
        }
    )


@router.post("/process-single/{log_id}")
async def process_single_episode(
    log_id: int,
    session: AsyncSession = Depends(get_session)
):
    """Process a single episode from a dry run log entry."""
    from app.services.processor import get_clients, get_folder_mappings, get_excluded_user_ids
    from app.services.emby import EmbyClient
    from app.models import EmbyLibrary, EmbyLibraryFolder
    import os
    import asyncio
    
    # Get the log entry
    log_entry = await session.get(ProcessLog, log_id)
    if not log_entry:
        return JSONResponse({"success": False, "error": "Log entry not found"}, status_code=404)
    
    if not log_entry.dry_run:
        return JSONResponse({"success": False, "error": "Entry already processed"}, status_code=400)
    
    emby, sonarr = await get_clients()
    if not emby or not sonarr:
        return JSONResponse({"success": False, "error": "Emby or Sonarr not configured"}, status_code=400)
    
    file_path = log_entry.original_path
    
    try:
        # Step 1: Find the episode in Sonarr
        sonarr_file = await sonarr.get_episode_file_by_path(file_path)
        if not sonarr_file:
            raise Exception(f"Could not find file in Sonarr: {file_path}")
        
        series = await sonarr.get_series_by_path(file_path)
        if not series:
            raise Exception(f"Could not find series in Sonarr for: {file_path}")
        
        series_id = series["id"]
        
        # Get the episode ID from Sonarr
        episodes = await sonarr.get_episodes_by_series(series_id)
        sonarr_episode = None
        for ep in episodes:
            if (ep.get("seasonNumber") == log_entry.season_number and 
                ep.get("episodeNumber") == log_entry.episode_number):
                sonarr_episode = ep
                break
        
        if not sonarr_episode:
            raise Exception(f"Could not find episode in Sonarr")
        
        sonarr_episode_id = sonarr_episode["id"]
        
        # Step 2: Unmonitor the episode FIRST
        await sonarr.set_episode_monitored(sonarr_episode_id, False)
        log_entry.sonarr_unmonitored = True
        
        # Step 3: Check if this was the last monitored episode in the season
        if await sonarr.check_season_complete(series_id, log_entry.season_number):
            await sonarr.set_season_monitored(series_id, log_entry.season_number, False)
            log_entry.season_unmonitored = True
        
        # Step 4: Delete the original file
        if os.path.exists(file_path):
            os.remove(file_path)
            log_entry.file_deleted = True
        
        # Step 5: Create STRM placeholder
        from pathlib import Path as PathLib
        strm_path = PathLib(file_path).with_suffix(".strm")
        strm_path.touch()
        log_entry.strm_created = True
        
        # Step 6: Refresh Sonarr series
        await sonarr.refresh_series(series_id)
        
        # Wait for Sonarr to process
        await asyncio.sleep(2)
        
        # Step 7: Trigger rename in Sonarr
        new_file = await sonarr.get_episode_file_by_path(str(strm_path))
        if new_file:
            await sonarr.rename_files(series_id, [new_file["id"]])
            log_entry.sonarr_renamed = True
        
        # Mark as no longer a dry run
        log_entry.dry_run = False
        log_entry.success = True
        log_entry.error_message = None
        
        await session.commit()
        
        return JSONResponse({
            "success": True, 
            "message": f"Processed {log_entry.series_name} S{log_entry.season_number:02d}E{log_entry.episode_number:02d}"
        })
        
    except Exception as e:
        log_entry.success = False
        log_entry.error_message = str(e)
        await session.commit()
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


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
    
    result = await session.execute(
        select(ProcessLog).where(
            ProcessLog.timestamp >= run.started_at,
            ProcessLog.timestamp <= (run.completed_at or run.started_at)
        ).order_by(
            ProcessLog.series_name,
            ProcessLog.season_number,
            ProcessLog.episode_number
        )
    )
    logs = result.scalars().all()
    
    return templates.TemplateResponse(
        "run_details.html",
        {
            "request": request,
            "run": run,
            "logs": logs,
            "format_size": format_size
        }
    )
