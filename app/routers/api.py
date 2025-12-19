from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession
import csv
import io

from app.database import get_session
from app.models import ProcessRun, ProcessLog, WatchedEpisode, Schedule
from app.config import settings, save_settings
from app.progress import progress

router = APIRouter()


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


@router.get("/stats")
async def get_stats(session: AsyncSession = Depends(get_session)):
    """Get dashboard statistics."""
    from sqlalchemy import func
    
    # Get last run status
    result = await session.execute(
        select(ProcessRun).order_by(desc(ProcessRun.started_at)).limit(1)
    )
    last_run = result.scalar_one_or_none()
    
    # Count episodes from actual logs (not runs)
    result = await session.execute(
        select(
            func.count(ProcessLog.id),
            func.coalesce(func.sum(ProcessLog.original_size_bytes), 0)
        ).where(
            ProcessLog.success == True,
            ProcessLog.test_mode == False
        )
    )
    row = result.one()
    total_episodes = row[0] or 0
    total_bytes = row[1] or 0
    
    return {
        "episodes_processed": total_episodes,
        "space_reclaimed": format_size(total_bytes),
        "last_run_status": last_run.status if last_run else "never",
        "test_mode": settings.test_mode
    }


@router.get("/counts")
async def get_counts(session: AsyncSession = Depends(get_session)):
    """Get counts for pending and orphaned files."""
    # Pending count
    pending_result = await session.execute(
        select(func.count(WatchedEpisode.id))
    )
    pending_count = pending_result.scalar() or 0
    
    # Orphaned count
    orphan_result = await session.execute(
        select(func.count(ProcessLog.id)).where(
            ProcessLog.success == False,
            ProcessLog.test_mode == False,
            ProcessLog.error_message.like("%Could not find file in Sonarr%")
        )
    )
    orphan_count = orphan_result.scalar() or 0
    
    return {
        "pending_count": pending_count,
        "orphan_count": orphan_count
    }


@router.get("/schedule-info")
async def get_schedule_info(session: AsyncSession = Depends(get_session)):
    """Get schedule information for dashboard."""
    from app.scheduler import get_next_run_time
    
    result = await session.execute(select(Schedule))
    schedule = result.scalar_one_or_none()
    
    next_run = get_next_run_time()
    
    if not schedule or not schedule.enabled:
        return {
            "enabled": False,
            "schedule_type": "disabled",
            "description": "Disabled",
            "next_run": None
        }
    
    # Build description
    if schedule.schedule_type == "daily":
        desc = f"Daily at {schedule.daily_hour:02d}:{schedule.daily_minute:02d}"
    elif schedule.schedule_type == "hourly":
        if schedule.hour_filter == "odd":
            desc = f"Odd hours at :{schedule.daily_minute:02d}"
        elif schedule.hour_filter == "even":
            desc = f"Even hours at :{schedule.daily_minute:02d}"
        else:
            desc = f"Every hour at :{schedule.daily_minute:02d}"
    elif schedule.schedule_type == "interval":
        desc = f"Every {schedule.interval_hours} hour(s)"
    else:
        desc = "Unknown"
    
    return {
        "enabled": True,
        "schedule_type": schedule.schedule_type,
        "description": desc,
        "next_run": next_run.strftime('%Y-%m-%d %H:%M') if next_run else None
    }


@router.get("/last-run")
async def get_last_run(session: AsyncSession = Depends(get_session)):
    """Get the last processing run."""
    result = await session.execute(
        select(ProcessRun).order_by(desc(ProcessRun.started_at)).limit(1)
    )
    run = result.scalar_one_or_none()
    
    if not run:
        return JSONResponse(None, status_code=204)
    
    return {
        "started_at": run.started_at.strftime('%m/%d/%Y, %I:%M:%S %p'),
        "status": run.status,
        "episodes_processed": run.episodes_processed,
        "test_mode": run.test_mode
    }


@router.post("/process")
async def trigger_process():
    """Trigger a processing run."""
    from app.services.processor import process_watched_episodes
    import asyncio
    
    asyncio.create_task(process_watched_episodes(trigger="manual"))
    
    return {"status": "started"}


@router.post("/toggle-test-mode")
async def toggle_test_mode():
    """Toggle test mode on/off."""
    new_value = not settings.test_mode
    await save_settings(new_value, settings.delay_days)
    return {"test_mode": new_value}


@router.get("/progress")
async def get_progress():
    """Get current processing progress."""
    return JSONResponse(progress.to_dict())


@router.get("/pending")
async def get_pending(session: AsyncSession = Depends(get_session)):
    """Get list of episodes waiting for delay period to pass."""
    from datetime import datetime, timedelta
    
    result = await session.execute(
        select(WatchedEpisode).order_by(WatchedEpisode.first_seen_at)
    )
    watched = result.scalars().all()
    
    pending = []
    for w in watched:
        days_elapsed = (datetime.now() - w.first_seen_at).days
        days_remaining = max(0, settings.delay_days - days_elapsed)
        process_date = w.first_seen_at + timedelta(days=settings.delay_days)
        
        pending.append({
            "id": w.id,
            "series_name": w.series_name,
            "season_number": w.season_number,
            "episode_number": w.episode_number,
            "file_path": w.file_path,
            "first_seen_at": w.first_seen_at.strftime('%Y-%m-%d %H:%M'),
            "days_remaining": days_remaining,
            "process_date": process_date.strftime('%Y-%m-%d')
        })
    
    return {
        "pending": pending,
        "total_count": len(pending),
        "delay_days": settings.delay_days
    }


@router.post("/process-pending")
async def process_pending_episodes(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """Process selected pending episodes immediately, bypassing delay."""
    import os
    import asyncio
    from pathlib import Path
    from app.services.processor import get_clients
    from app.models import ProcessLog
    from sqlalchemy import delete
    
    data = await request.json()
    episode_ids = data.get("ids", [])
    
    if not episode_ids:
        return JSONResponse({"success": False, "error": "No episodes selected"}, status_code=400)
    
    emby, sonarr = await get_clients()
    if not emby or not sonarr:
        return JSONResponse({"success": False, "error": "Emby or Sonarr not configured"}, status_code=400)
    
    # Get the watched episodes
    result = await session.execute(
        select(WatchedEpisode).where(WatchedEpisode.id.in_(episode_ids))
    )
    episodes = result.scalars().all()
    
    processed = 0
    failed = 0
    total_bytes = 0
    errors = []
    
    for ep in episodes:
        file_path = ep.file_path
        
        try:
            # Check file exists
            if not os.path.exists(file_path):
                raise Exception(f"File not found: {file_path}")
            
            file_size = os.path.getsize(file_path)
            
            # Find in Sonarr
            sonarr_file = await sonarr.get_episode_file_by_path(file_path)
            if not sonarr_file:
                raise Exception(f"Could not find file in Sonarr")
            
            series = await sonarr.get_series_by_path(file_path)
            if not series:
                raise Exception(f"Could not find series in Sonarr")
            
            series_id = series["id"]
            
            episodes_list = await sonarr.get_episodes_by_series(series_id)
            sonarr_episode = None
            for e in episodes_list:
                if (e.get("seasonNumber") == ep.season_number and 
                    e.get("episodeNumber") == ep.episode_number):
                    sonarr_episode = e
                    break
            
            if not sonarr_episode:
                raise Exception(f"Could not find episode in Sonarr")
            
            sonarr_episode_id = sonarr_episode["id"]
            
            # Unmonitor
            await sonarr.set_episode_monitored(sonarr_episode_id, False)
            
            # Check season
            if await sonarr.check_season_complete(series_id, ep.season_number):
                await sonarr.set_season_monitored(series_id, ep.season_number, False)
            
            # Delete file
            os.remove(file_path)
            
            # Create STRM
            strm_path = Path(file_path).with_suffix(".strm")
            strm_path.touch()
            
            # Refresh Sonarr
            await sonarr.refresh_series(series_id)
            await asyncio.sleep(2)
            
            # Rename
            new_file = await sonarr.get_episode_file_by_path(str(strm_path))
            if new_file:
                await sonarr.rename_files(series_id, [new_file["id"]])
            
            # Log it
            log_entry = ProcessLog(
                series_name=ep.series_name,
                season_number=ep.season_number,
                episode_number=ep.episode_number,
                episode_title="",
                original_path=file_path,
                original_size_bytes=file_size,
                strm_path=str(strm_path),
                folder_name=Path(file_path).parent.parent.name,
                watched_by="Manual",
                test_mode=False,
                success=True,
                file_deleted=True,
                strm_created=True,
                sonarr_unmonitored=True,
                sonarr_renamed=True
            )
            session.add(log_entry)
            
            # Remove from watched
            await session.execute(
                delete(WatchedEpisode).where(WatchedEpisode.id == ep.id)
            )
            
            processed += 1
            total_bytes += file_size
            
        except Exception as e:
            failed += 1
            errors.append(f"{ep.series_name} S{ep.season_number:02d}E{ep.episode_number:02d}: {str(e)}")
    
    await session.commit()
    
    return {
        "success": True,
        "processed": processed,
        "failed": failed,
        "bytes_reclaimed": total_bytes,
        "size_formatted": format_size(total_bytes),
        "errors": errors
    }


@router.get("/orphans")
async def get_orphans(session: AsyncSession = Depends(get_session)):
    """Get list of orphaned files (in Emby but not in Sonarr)."""
    import os
    
    result = await session.execute(
        select(ProcessLog).where(
            ProcessLog.success == False,
            ProcessLog.test_mode == False,
            ProcessLog.error_message.like("%Could not find file in Sonarr%")
        ).order_by(
            ProcessLog.series_name,
            ProcessLog.season_number,
            ProcessLog.episode_number
        )
    )
    logs = result.scalars().all()
    
    orphans = []
    total_size = 0
    
    for log in logs:
        exists = os.path.exists(log.original_path)
        size = 0
        if exists:
            try:
                size = os.path.getsize(log.original_path)
                total_size += size
            except OSError:
                pass
        
        orphans.append({
            "id": log.id,
            "series_name": log.series_name,
            "season_number": log.season_number,
            "episode_number": log.episode_number,
            "episode_title": log.episode_title,
            "folder_name": log.folder_name,
            "path": log.original_path,
            "size": size,
            "size_formatted": format_size(size),
            "exists": exists
        })
    
    return {
        "orphans": orphans,
        "total_count": len(orphans),
        "total_size": total_size,
        "total_size_formatted": format_size(total_size)
    }


@router.post("/delete-orphans")
async def delete_orphans(session: AsyncSession = Depends(get_session)):
    """Delete all orphaned files."""
    import os
    
    result = await session.execute(
        select(ProcessLog).where(
            ProcessLog.success == False,
            ProcessLog.test_mode == False,
            ProcessLog.error_message.like("%Could not find file in Sonarr%")
        )
    )
    logs = result.scalars().all()
    
    deleted_count = 0
    deleted_bytes = 0
    cleared_count = 0
    errors = []
    
    for log in logs:
        if os.path.exists(log.original_path):
            try:
                size = os.path.getsize(log.original_path)
                os.remove(log.original_path)
                deleted_count += 1
                deleted_bytes += size
            except Exception as e:
                errors.append(f"{log.original_path}: {str(e)}")
                continue
        else:
            cleared_count += 1
        
        log.error_message = "Orphaned file deleted"
        log.success = True
    
    await session.commit()
    
    return {
        "deleted_count": deleted_count,
        "cleared_count": cleared_count,
        "deleted_bytes": deleted_bytes,
        "deleted_size_formatted": format_size(deleted_bytes),
        "errors": errors
    }


@router.get("/export-failures")
async def export_failures(session: AsyncSession = Depends(get_session)):
    """Export failed processing logs as CSV."""
    result = await session.execute(
        select(ProcessLog).where(
            ProcessLog.success == False,
            ProcessLog.test_mode == False
        ).order_by(
            ProcessLog.series_name,
            ProcessLog.season_number,
            ProcessLog.episode_number
        )
    )
    logs = result.scalars().all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow([
        "Series", "Season", "Episode", "Title", "Folder", "Path", "Error"
    ])
    
    for log in logs:
        writer.writerow([
            log.series_name,
            log.season_number,
            log.episode_number,
            log.episode_title,
            log.folder_name,
            log.original_path,
            log.error_message
        ])
    
    output.seek(0)
    
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=afterwatch_failures.csv"}
    )

@router.get("/changelog")
async def get_changelog():
    """Serve the changelog."""
    from fastapi.responses import HTMLResponse
    from app.version import CHANGELOG
    
    # Simple markdown to HTML conversion
    lines = CHANGELOG.strip().split('\n')
    html_lines = []
    in_list = False
    
    for line in lines:
        if line.startswith('# '):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            html_lines.append(f'<h1>{line[2:]}</h1>')
        elif line.startswith('## '):
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            html_lines.append(f'<h2>{line[3:]}</h2>')
        elif line.startswith('- '):
            if not in_list:
                html_lines.append('<ul>')
                in_list = True
            html_lines.append(f'<li>{line[2:]}</li>')
        elif line.strip() == '':
            if in_list:
                html_lines.append('</ul>')
                in_list = False
    
    if in_list:
        html_lines.append('</ul>')
    
    html_content = '\n'.join(html_lines)
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Afterwatch Changelog</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: #1a1a2e;
                color: #e2e8f0;
                max-width: 800px;
                margin: 0 auto;
                padding: 2rem;
                line-height: 1.6;
            }}
            h1 {{
                color: #e63946;
                border-bottom: 1px solid #374151;
                padding-bottom: 0.5rem;
            }}
            h2 {{
                color: #e63946;
                margin-top: 2rem;
            }}
            ul {{
                padding-left: 1.5rem;
            }}
            li {{
                margin-bottom: 0.5rem;
            }}
            .back-link {{
                display: inline-block;
                margin-bottom: 1rem;
                padding: 0.5rem 1rem;
                background: #1f2937;
                border-radius: 6px;
                text-decoration: none;
                color: #e63946;
            }}
            .back-link:hover {{
                background: #374151;
            }}
        </style>
    </head>
    <body>
        <a href="/" class="back-link">← Back to Dashboard</a>
        {html_content}
    </body>
    </html>
    """
    
    return HTMLResponse(html)
