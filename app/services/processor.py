import os
import asyncio
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import logging

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import (
    Connection, EmbyLibrary, EmbyLibraryFolder, EmbyUser, LibraryUserMapping, 
    ProcessLog, ProcessRun, WatchedEpisode
)
from app.services.emby import EmbyClient
from app.services.sonarr import SonarrClient
from app.config import settings
from app.progress import progress

logger = logging.getLogger(__name__)


async def get_clients() -> tuple[Optional[EmbyClient], Optional[SonarrClient]]:
    """Get configured Emby and Sonarr clients."""
    async with async_session() as session:
        result = await session.execute(
            select(Connection).where(Connection.service == "emby")
        )
        emby_conn = result.scalar_one_or_none()
        
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


async def get_excluded_user_ids(session: AsyncSession) -> set[str]:
    """Get set of user IDs that are marked as excluded."""
    result = await session.execute(
        select(EmbyUser).where(EmbyUser.is_excluded == True)
    )
    users = result.scalars().all()
    return {u.id for u in users}


async def get_folder_mappings(
    session: AsyncSession,
    library_id: str
) -> dict[int, str]:
    """Get subfolder_id -> path mapping for a library."""
    result = await session.execute(
        select(EmbyLibraryFolder).where(
            EmbyLibraryFolder.library_id == library_id
        )
    )
    folders = result.scalars().all()
    return {f.subfolder_id: f.path for f in folders}


def get_subfolder_id_for_path(file_path: str, folder_mappings: dict[int, str]) -> Optional[int]:
    """Find which subfolder a file belongs to based on its path."""
    sorted_mappings = sorted(folder_mappings.items(), key=lambda x: len(x[1]), reverse=True)
    
    for subfolder_id, folder_path in sorted_mappings:
        if file_path.startswith(folder_path):
            return subfolder_id
    return None


def user_can_access_file(
    file_path: str,
    user_access: dict,
    library_guid: str,
    folder_mappings: dict[int, str]
) -> bool:
    """Check if a user can access a specific file based on their permissions."""
    if user_access.get('all_access', False):
        return True
    
    if library_guid not in user_access.get('enabled_folders', set()):
        return False
    
    subfolder_id = get_subfolder_id_for_path(file_path, folder_mappings)
    if subfolder_id is None:
        return True
    
    if subfolder_id in user_access.get('excluded_subfolders', set()):
        return False
    
    return True


async def cleanup_stale_watched_records(
    session: AsyncSession,
    emby: EmbyClient,
    libraries: list,
    user_access_map: dict,
    user_names: dict[str, str]
) -> int:
    """Remove WatchedEpisode records for episodes no longer watched by all required users."""
    
    removed_count = 0
    
    for library in libraries:
        required_users = await get_library_required_users(session, library.id)
        if not required_users:
            continue
        
        folder_mappings = await get_folder_mappings(session, library.id)
        folder_paths = list(folder_mappings.values())
        
        if not folder_paths:
            continue
        
        # Build set of file paths watched by each required user
        user_watched_paths = {}
        for user_id in required_users:
            user_watched = await emby.get_watched_episodes(user_id, library.id)
            paths = set()
            for ep in user_watched:
                media_sources = ep.get("MediaSources", [])
                if media_sources:
                    file_path = media_sources[0].get("Path", "")
                    if file_path:
                        paths.add(file_path)
            user_watched_paths[user_id] = paths
        
        # Get WatchedEpisode records that belong to this library
        result = await session.execute(select(WatchedEpisode))
        all_pending = result.scalars().all()
        
        for watched in all_pending:
            # Check if belongs to this library
            belongs = any(watched.file_path.startswith(fp) for fp in folder_paths)
            if not belongs:
                continue
            
            # Check which users can access this file
            accessible_users = [
                user_id for user_id in required_users
                if user_can_access_file(
                    watched.file_path, 
                    user_access_map.get(user_id, {}), 
                    library.guid, 
                    folder_mappings
                )
            ]
            
            if not accessible_users:
                # No required users can access, remove record
                await session.delete(watched)
                removed_count += 1
                logger.info(f"Removed stale record (no accessible users): {watched.series_name} S{watched.season_number:02d}E{watched.episode_number:02d}")
                continue
            
            # Check if all accessible required users have still watched
            all_watched = True
            for user_id in accessible_users:
                if watched.file_path not in user_watched_paths.get(user_id, set()):
                    all_watched = False
                    break
            
            if not all_watched:
                await session.delete(watched)
                removed_count += 1
                user_name_list = [user_names.get(uid, uid) for uid in accessible_users]
                logger.info(f"Removed from pending (no longer watched): {watched.series_name} S{watched.season_number:02d}E{watched.episode_number:02d}")
    
    if removed_count > 0:
        await session.commit()
    
    return removed_count


async def check_or_create_watched_record(
    session: AsyncSession,
    file_path: str,
    series_name: str,
    season_num: int,
    episode_num: int
) -> tuple[bool, Optional[WatchedEpisode]]:
    """
    Check if episode has a watched record and if delay has passed.
    Returns (ready_to_process, watched_record)
    """
    result = await session.execute(
        select(WatchedEpisode).where(WatchedEpisode.file_path == file_path)
    )
    watched = result.scalar_one_or_none()
    
    if not watched:
        watched = WatchedEpisode(
            file_path=file_path,
            series_name=series_name,
            season_number=season_num,
            episode_number=episode_num,
            first_seen_at=datetime.now()
        )
        session.add(watched)
        return False, watched
    
    delay_days = settings.delay_days
    if delay_days == 0:
        return True, watched
    
    cutoff = datetime.now() - timedelta(days=delay_days)
    if watched.first_seen_at <= cutoff:
        return True, watched
    
    return False, watched


async def process_episode(
    emby: EmbyClient,
    sonarr: SonarrClient,
    episode: dict,
    required_users: list[str],
    excluded_user_ids: set[str],
    user_access_map: dict,
    user_names: dict[str, str],
    library_guid: str,
    folder_mappings: dict[int, str],
    test_mode: bool,
    session: AsyncSession,
    run_id: int
) -> Optional[ProcessLog]:
    """Process a single episode - check watched state and replace if needed."""
    
    episode_id = episode.get("Id")
    series_name = episode.get("SeriesName", "Unknown")
    season_num = episode.get("ParentIndexNumber", 0)
    episode_num = episode.get("IndexNumber", 0)
    episode_title = episode.get("Name", "")
    
    media_sources = episode.get("MediaSources", [])
    if not media_sources:
        return None
    
    file_path = media_sources[0].get("Path", "")
    if not file_path:
        return None
    
    if file_path.lower().endswith(".strm"):
        return None
    
    strm_version = str(Path(file_path).with_suffix(".strm"))
    if not os.path.exists(file_path) and os.path.exists(strm_version):
        return None
    
    existing = await session.execute(
        select(ProcessLog).where(
            ProcessLog.original_path == file_path,
            ProcessLog.success == True,
            ProcessLog.test_mode == False
        )
    )
    if existing.scalar_one_or_none():
        return None
    
    folder_name = None
    subfolder_id = get_subfolder_id_for_path(file_path, folder_mappings)
    if subfolder_id:
        folder_path = folder_mappings.get(subfolder_id, "")
        folder_name = Path(folder_path).name if folder_path else None
    
    for user_id in excluded_user_ids:
        user_access = user_access_map.get(user_id, {})
        if user_can_access_file(file_path, user_access, library_guid, folder_mappings):
            return None
    
    accessible_users = [
        user_id for user_id in required_users
        if user_can_access_file(file_path, user_access_map.get(user_id, {}), library_guid, folder_mappings)
    ]
    
    if not accessible_users:
        return None
    
    watched_status = await emby.check_episode_watched(episode_id, accessible_users)
    if not all(watched_status.values()):
        return None
    
    ready_to_process, watched_record = await check_or_create_watched_record(
        session, file_path, series_name, season_num, episode_num
    )
    
    if not ready_to_process:
        days_remaining = settings.delay_days - (datetime.now() - watched_record.first_seen_at).days
        logger.info(f"Delaying: {series_name} S{season_num:02d}E{episode_num:02d} ({days_remaining} days remaining)")
        return None
    
    watched_by_names = [user_names.get(uid, uid) for uid in accessible_users if watched_status.get(uid)]
    watched_by = ", ".join(watched_by_names)
    
    logger.info(f"Processing: {series_name} S{season_num:02d}E{episode_num:02d} ({watched_by})")
    
    try:
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    except OSError:
        file_size = 0
    
    log_entry = ProcessLog(
        series_name=series_name,
        season_number=season_num,
        episode_number=episode_num,
        episode_title=episode_title,
        original_path=file_path,
        original_size_bytes=file_size,
        strm_path=str(Path(file_path).with_suffix(".strm")),
        folder_name=folder_name,
        watched_by=watched_by,
        test_mode=test_mode
    )
    
    if test_mode:
        log_entry.success = True
        session.add(log_entry)
        return log_entry
    
    try:
        sonarr_file = await sonarr.get_episode_file_by_path(file_path)
        if not sonarr_file:
            raise Exception(f"Could not find file in Sonarr: {file_path}")
        
        series = await sonarr.get_series_by_path(file_path)
        if not series:
            raise Exception(f"Could not find series in Sonarr for: {file_path}")
        
        series_id = series["id"]
        
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
        
        await sonarr.set_episode_monitored(sonarr_episode_id, False)
        log_entry.sonarr_unmonitored = True
        logger.info(f"  Unmonitored episode")
        
        if await sonarr.check_season_complete(series_id, season_num):
            await sonarr.set_season_monitored(series_id, season_num, False)
            log_entry.season_unmonitored = True
            logger.info(f"  Unmonitored season {season_num}")
        
        if os.path.exists(file_path):
            os.remove(file_path)
            log_entry.file_deleted = True
            logger.info(f"  Deleted original file")
        
        strm_path = Path(file_path).with_suffix(".strm")
        strm_path.touch()
        log_entry.strm_created = True
        logger.info(f"  Created STRM placeholder")
        
        await sonarr.refresh_series(series_id)
        logger.info(f"  Refreshed series in Sonarr")
        
        await asyncio.sleep(2)
        
        new_file = await sonarr.get_episode_file_by_path(str(strm_path))
        if new_file:
            await sonarr.rename_files(series_id, [new_file["id"]])
            log_entry.sonarr_renamed = True
            logger.info(f"  Triggered rename in Sonarr")
        
        log_entry.success = True
        
        await session.execute(
            delete(WatchedEpisode).where(WatchedEpisode.file_path == file_path)
        )
        
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
    
    test_mode = settings.test_mode
    
    try:
        user_access = await emby.get_all_user_access_details()
        logger.info(f"Loaded access details for {len(user_access)} users")
    except Exception as e:
        logger.error(f"Failed to get user access details: {e}")
        return
    
    try:
        users = await emby.get_users()
        user_names = {u["Id"]: u["Name"] for u in users}
    except Exception as e:
        logger.error(f"Failed to get user names: {e}")
        user_names = {}
    
    async with async_session() as session:
        if test_mode:
            await session.execute(
                delete(ProcessLog).where(ProcessLog.test_mode == True)
            )
            await session.execute(
                delete(ProcessRun).where(ProcessRun.test_mode == True)
            )
            await session.commit()
            logger.info("Cleared previous test mode logs")
        else:
            await session.execute(
                delete(ProcessLog).where(ProcessLog.test_mode == True)
            )
            await session.execute(
                delete(ProcessRun).where(ProcessRun.test_mode == True)
            )
            await session.commit()
            logger.info("Cleared test mode logs before live run")
        
        excluded_user_ids = await get_excluded_user_ids(session)
        if excluded_user_ids:
            excluded_names = [user_names.get(uid, uid) for uid in excluded_user_ids]
            logger.info(f"Excluded users: {', '.join(excluded_names)}")
        
        # Get enabled libraries for cleanup
        result = await session.execute(
            select(EmbyLibrary).where(EmbyLibrary.is_enabled == True)
        )
        libraries = result.scalars().all()
        
        # Cleanup stale watched records (episodes marked as unwatched)
        removed = await cleanup_stale_watched_records(
            session, emby, libraries, user_access, user_names
        )
        if removed > 0:
            logger.info(f"Removed {removed} stale pending records")
        
        total_episodes = 0
        for library in libraries:
            required_users = await get_library_required_users(session, library.id)
            if required_users:
                for user_id in required_users:
                    user_watched = await emby.get_watched_episodes(user_id, library.id)
                    total_episodes += len(user_watched)
                    break
        
        run = ProcessRun(
            trigger=trigger,
            test_mode=test_mode,
            status="running"
        )
        session.add(run)
        await session.commit()
        await session.refresh(run)
        
        progress.start(run.id, total_episodes)
        
        try:
            result = await session.execute(
                select(EmbyLibrary).where(EmbyLibrary.is_enabled == True)
            )
            libraries = result.scalars().all()
            
            total_processed = 0
            total_failed = 0
            total_bytes = 0
            
            for library in libraries:
                logger.info(f"Processing library: {library.name}")
                
                required_users = await get_library_required_users(
                    session, library.id
                )
                
                if not required_users:
                    logger.warning(f"  No required users configured, skipping")
                    continue
                
                folder_mappings = await get_folder_mappings(session, library.id)
                logger.info(f"  Loaded {len(folder_mappings)} folder mappings")
                
                all_watched = {}
                for user_id in required_users:
                    user_watched = await emby.get_watched_episodes(user_id, library.id)
                    for ep in user_watched:
                        ep_id = ep.get("Id")
                        if ep_id not in all_watched:
                            all_watched[ep_id] = ep
                
                watched = list(all_watched.values())
                
                logger.info(f"  Found {len(watched)} watched episodes to check")
                
                for episode in watched:
                    log = await process_episode(
                        emby, sonarr, episode, required_users,
                        excluded_user_ids, user_access, user_names, 
                        library.guid, folder_mappings,
                        test_mode, session, run.id
                    )
                    
                    if log:
                        episode_str = f"S{log.season_number:02d}E{log.episode_number:02d}"
                        progress.update(
                            log.series_name, 
                            episode_str, 
                            log.success, 
                            log.original_size_bytes if log.success else 0
                        )
                        
                        if log.success:
                            total_processed += 1
                            total_bytes += log.original_size_bytes
                        else:
                            total_failed += 1
                
                await session.commit()
            
            run.completed_at = datetime.now()
            run.episodes_processed = total_processed
            run.episodes_failed = total_failed
            run.bytes_reclaimed = total_bytes
            run.status = "completed"
            
            logger.info(
                f"Processing complete: {total_processed} episodes, "
                f"{total_bytes / (1024*1024):.2f} MB reclaimed"
            )
            
        except Exception as e:
            run.completed_at = datetime.now()
            run.status = "failed"
            run.error_message = str(e)
            logger.error(f"Processing failed: {e}")
        
        finally:
            progress.finish()
        
        await session.commit()
