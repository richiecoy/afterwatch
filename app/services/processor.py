import os
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import (
    Connection, EmbyLibrary, LibraryUserMapping, 
    ProcessLog, ProcessRun
)
from app.services.emby import EmbyClient
from app.services.sonarr import SonarrClient
from app.config import settings

logger = logging.getLogger(__name__)


async def get_clients() -> tuple[Optional[EmbyClient], Optional[SonarrClient]]:
    """Get configured Emby and Sonarr clients."""
    async with async_session() as session:
        # Get Emby connection
        result = await session.execute(
            select(Connection).where(Connection.service == "emby")
        )
        emby_conn = result.scalar_one_or_none()
        
        # Get Sonarr connection
        result = await session.execute(
            select(Connection).where(Connection.service == "sonarr")
        )
        sonarr_conn = result.scalar_one_or_none()
        
        emby_client = None
        sonarr_client = None
        
        if emby_conn and emby_conn.verified:
            emby_client = EmbyClient(emby_conn.url, emby_conn.api_key)
        
        if sonarr_conn and sonarr_conn.verified:
            sonarr_client = SonarrClient(sonarr_conn.url, sonarr_conn.api_key)
        
        return emby_client, sonarr_client


async def get_library_required_users(
    session: AsyncSession, 
    library_id: str
) -> list[str]:
    """Get list of user IDs that must have watched for a library."""
    result = await session.execute(
        select(LibraryUserMapping).where(
            LibraryUserMapping.library_id == library_id,
            LibraryUserMapping.required == True
        )
    )
    mappings = result.scalars().all()
    return [m.user_id for m in mappings]


async def process_episode(
    emby: EmbyClient,
    sonarr: SonarrClient,
    episode: dict,
    required_users: list[str],
    dry_run: bool,
    session: AsyncSession,
    run_id: int
) -> Optional[ProcessLog]:
    """Process a single episode - check watched state and replace if needed."""
    
    episode_id = episode.get("Id")
    series_name = episode.get("SeriesName", "Unknown")
    season_num = episode.get("ParentIndexNumber", 0)
    episode_num = episode.get("IndexNumber", 0)
    episode_title = episode.get("Name", "")
    
    # Get file path from episode
    media_sources = episode.get("MediaSources", [])
    if not media_sources:
        logger.warning(f"No media source for {series_name} S{season_num:02d}E{episode_num:02d}")
        return None
    
    file_path = media_sources[0].get("Path", "")
    if not file_path:
        return None
    
    # Skip if already a STRM file
    if file_path.lower().endswith(".strm"):
        return None
    
    # Check if all required users have watched
    watched_status = await emby.check_episode_watched(episode_id, required_users)
    if not all(watched_status.values()):
        # Not all users have watched
        return None
    
    logger.info(f"Processing: {series_name} S{season_num:02d}E{episode_num:02d}")
    
    # Get file size before deletion
    try:
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    except OSError:
        file_size = 0
    
    # Create log entry
    log_entry = ProcessLog(
        series_name=series_name,
        season_number=season_num,
        episode_number=episode_num,
        episode_title=episode_title,
        original_path=file_path,
        original_size_bytes=file_size,
        strm_path=str(Path(file_path).with_suffix(".strm")),
        dry_run=dry_run
    )
    
    if dry_run:
        log_entry.success = True
        session.add(log_entry)
        logger.info(f"  [DRY RUN] Would process {file_path}")
        return log_entry
    
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
            if (ep.get("seasonNumber") == season_num and 
                ep.get("episodeNumber") == episode_num):
                sonarr_episode = ep
                break
        
        if not sonarr_episode:
            raise Exception(f"Could not find episode in Sonarr")
        
        sonarr_episode_id = sonarr_episode["id"]
        
        # Step 2: Unmonitor the episode FIRST (before deletion)
        await sonarr.set_episode_monitored(sonarr_episode_id, False)
        log_entry.sonarr_unmonitored = True
        logger.info(f"  Unmonitored episode")
        
        # Step 3: Check if this was the last monitored episode in the season
        if await sonarr.check_season_complete(series_id, season_num):
            await sonarr.set_season_monitored(series_id, season_num, False)
            log_entry.season_unmonitored = True
            logger.info(f"  Unmonitored season {season_num}")
        
        # Step 4: Delete the original file
        if os.path.exists(file_path):
            os.remove(file_path)
            log_entry.file_deleted = True
            logger.info(f"  Deleted original file")
        
        # Step 5: Create STRM placeholder
        strm_path = Path(file_path).with_suffix(".strm")
        strm_path.touch()  # Creates empty file
        log_entry.strm_created = True
        logger.info(f"  Created STRM placeholder")
        
        # Step 6: Refresh Sonarr series to detect the new file
        await sonarr.refresh_series(series_id)
        logger.info(f"  Refreshed series in Sonarr")
        
        # Wait a moment for Sonarr to process
        await asyncio.sleep(2)
        
        # Step 7: Trigger rename in Sonarr
        # Need to get the new file ID after refresh
        new_file = await sonarr.get_episode_file_by_path(str(strm_path))
        if new_file:
            await sonarr.rename_files(series_id, [new_file["id"]])
            log_entry.sonarr_renamed = True
            logger.info(f"  Triggered rename in Sonarr")
        
        log_entry.success = True
        
    except Exception as e:
        log_entry.success = False
        log_entry.error_message = str(e)
        logger.error(f"  Error: {e}")
    
    session.add(log_entry)
    return log_entry


async def process_watched_episodes(trigger: str = "manual"):
    """Main processing function - finds and processes all watched episodes."""
    
    emby, sonarr = await get_clients()
    
    if not emby or not sonarr:
        logger.error("Emby or Sonarr not configured")
        return
    
    dry_run = settings.dry_run
    
    # Get user library access once at the start
    try:
        user_access = await emby.get_all_user_library_access()
        logger.info(f"Loaded library access for {len(user_access)} users")
    except Exception as e:
        logger.error(f"Failed to get user library access: {e}")
        return
    
    async with async_session() as session:
        # Create run record
        run = ProcessRun(
            trigger=trigger,
            dry_run=dry_run,
            status="running"
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        
        try:
            # Get enabled libraries
            result = await session.execute(
                select(EmbyLibrary).where(EmbyLibrary.is_enabled == True)
            )
            libraries = result.scalars().all()
            
            total_processed = 0
            total_failed = 0
            total_bytes = 0
            
            for library in libraries:
                logger.info(f"Processing library: {library.name}")
                
                # Get required users for this library
                required_users = await get_library_required_users(
                    session, library.id
                )
                
                if not required_users:
                    logger.warning(f"  No required users configured, skipping")
                    continue
                
                # Filter to only users who have access to this library
                accessible_users = []
                for user_id in required_users:
                    user_libs = user_access.get(user_id)
                    # None means all access, or check if library is in their list
                    if user_libs is None or library.id in user_libs:
                        accessible_users.append(user_id)
                
                if not accessible_users:
                    logger.warning(f"  No required users have access to this library, skipping")
                    continue
                
                logger.info(f"  Required users with access: {len(accessible_users)}/{len(required_users)}")
                
                # Get watched episodes (from perspective of first accessible user)
                watched = await emby.get_watched_episodes(
                    accessible_users[0], 
                    library.id
                )
                
                logger.info(f"  Found {len(watched)} watched episodes")
                
                for episode in watched:
                    log = await process_episode(
                        emby, sonarr, episode, accessible_users,
                        dry_run, session, run.id
                    )
                    
                    if log:
                        if log.success:
                            total_processed += 1
                            total_bytes += log.original_size_bytes
                        else:
                            total_failed += 1
                
                await session.commit()
            
            # Update run record
            run.completed_at = datetime.utcnow()
            run.episodes_processed = total_processed
            run.episodes_failed = total_failed
            run.bytes_reclaimed = total_bytes
            run.status = "completed"
            
            logger.info(
                f"Processing complete: {total_processed} episodes, "
                f"{total_bytes / (1024*1024):.2f} MB reclaimed"
            )
            
        except Exception as e:
            run.completed_at = datetime.utcnow()
            run.status = "failed"
            run.error_message = str(e)
            logger.error(f"Processing failed: {e}")
        
        await session.commit()
