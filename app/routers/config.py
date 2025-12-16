from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path

from app.database import get_session
from app.models import Connection, EmbyUser, EmbyLibrary, LibraryUserMapping
from app.services.emby import EmbyClient
from app.services.sonarr import SonarrClient
from app.config import settings

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


@router.get("/", response_class=HTMLResponse)
async def config_page(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """Configuration page."""
    # Get current connections
    result = await session.execute(select(Connection))
    connections = {c.service: c for c in result.scalars().all()}
    
    # Get users and libraries
    users_result = await session.execute(select(EmbyUser))
    users = users_result.scalars().all()
    
    libraries_result = await session.execute(select(EmbyLibrary))
    libraries = libraries_result.scalars().all()
    
    # Get mappings
    mappings_result = await session.execute(select(LibraryUserMapping))
    mappings = mappings_result.scalars().all()
    
    # Build mapping lookup
    mapping_lookup = {}
    for m in mappings:
        if m.library_id not in mapping_lookup:
            mapping_lookup[m.library_id] = []
        mapping_lookup[m.library_id].append(m.user_id)
    
    return templates.TemplateResponse(
        "config.html",
        {
            "request": request,
            "emby": connections.get("emby"),
            "sonarr": connections.get("sonarr"),
            "users": users,
            "libraries": libraries,
            "mapping_lookup": mapping_lookup,
            "settings": settings
        }
    )


@router.post("/emby")
async def save_emby_connection(
    url: str = Form(...),
    api_key: str = Form(...),
    session: AsyncSession = Depends(get_session)
):
    """Save and test Emby connection."""
    # Test connection
    client = EmbyClient(url, api_key)
    try:
        info = await client.test_connection()
        verified = True
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {e}")
    
    # Save or update
    result = await session.execute(
        select(Connection).where(Connection.service == "emby")
    )
    conn = result.scalar_one_or_none()
    
    if conn:
        conn.url = url
        conn.api_key = api_key
        conn.verified = verified
    else:
        conn = Connection(
            service="emby",
            url=url,
            api_key=api_key,
            verified=verified
        )
        session.add(conn)
    
    await session.commit()
    return RedirectResponse(url="/config", status_code=303)


@router.post("/sonarr")
async def save_sonarr_connection(
    url: str = Form(...),
    api_key: str = Form(...),
    session: AsyncSession = Depends(get_session)
):
    """Save and test Sonarr connection."""
    client = SonarrClient(url, api_key)
    try:
        info = await client.test_connection()
        verified = True
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Connection failed: {e}")
    
    result = await session.execute(
        select(Connection).where(Connection.service == "sonarr")
    )
    conn = result.scalar_one_or_none()
    
    if conn:
        conn.url = url
        conn.api_key = api_key
        conn.verified = verified
    else:
        conn = Connection(
            service="sonarr",
            url=url,
            api_key=api_key,
            verified=verified
        )
        session.add(conn)
    
    await session.commit()
    return RedirectResponse(url="/config", status_code=303)


@router.post("/sync-emby")
async def sync_emby_data(
    session: AsyncSession = Depends(get_session)
):
    """Sync users and libraries from Emby."""
    from app.models import EmbyLibraryFolder
    
    result = await session.execute(
        select(Connection).where(Connection.service == "emby")
    )
    conn = result.scalar_one_or_none()
    
    if not conn or not conn.verified:
        raise HTTPException(status_code=400, detail="Emby not configured")
    
    client = EmbyClient(conn.url, conn.api_key)
    
    # Sync users
    users = await client.get_users()
    for user in users:
        existing = await session.get(EmbyUser, user["Id"])
        if existing:
            existing.name = user["Name"]
        else:
            session.add(EmbyUser(
                id=user["Id"],
                name=user["Name"],
                is_active=True
            ))
    
    # Sync libraries and their folders
    libraries = await client.get_libraries()
    for lib in libraries:
        lib_id = str(lib.get("ItemId", lib.get("Id", "")))
        lib_guid = lib.get("Guid", "")
        locations = lib.get("Locations", [])
        lib_path = locations[0] if locations else ""
        
        existing = await session.get(EmbyLibrary, lib_id)
        if existing:
            existing.name = lib["Name"]
            existing.path = lib_path
            existing.guid = lib_guid
        else:
            session.add(EmbyLibrary(
                id=lib_id,
                guid=lib_guid,
                name=lib["Name"],
                path=lib_path,
                is_enabled=False
            ))
        
        # Sync folder mappings
        # Pattern: subfolder_id = library_id + 2 + index
        lib_id_int = int(lib_id)
        for i, folder_path in enumerate(locations):
            subfolder_id = lib_id_int + 2 + i
            
            # Check if mapping exists
            result = await session.execute(
                select(EmbyLibraryFolder).where(
                    EmbyLibraryFolder.library_id == lib_id,
                    EmbyLibraryFolder.subfolder_id == subfolder_id
                )
            )
            existing_folder = result.scalar_one_or_none()
            
            if existing_folder:
                existing_folder.path = folder_path
            else:
                session.add(EmbyLibraryFolder(
                    library_id=lib_id,
                    subfolder_id=subfolder_id,
                    path=folder_path
                ))
    
    await session.commit()
    return RedirectResponse(url="/config", status_code=303)

@router.post("/library/{library_id}/toggle")
async def toggle_library(
    library_id: str,
    session: AsyncSession = Depends(get_session)
):
    """Toggle a library's enabled status."""
    library = await session.get(EmbyLibrary, library_id)
    if library:
        library.is_enabled = not library.is_enabled
        await session.commit()
    return {"enabled": library.is_enabled if library else False}


@router.post("/library/{library_id}/users")
async def update_library_users(
    library_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    """Update which users are required for a library."""
    data = await request.json()
    user_ids = data.get("user_ids", [])
    
    # Remove existing mappings
    result = await session.execute(
        select(LibraryUserMapping).where(
            LibraryUserMapping.library_id == library_id
        )
    )
    for mapping in result.scalars().all():
        await session.delete(mapping)
    
    # Add new mappings
    for user_id in user_ids:
        session.add(LibraryUserMapping(
            library_id=library_id,
            user_id=user_id,
            required=True
        ))
    
    await session.commit()
    return {"success": True}


@router.post("/settings")
async def update_settings(
    dry_run: bool = Form(False),
    schedule_hour: int = Form(3),
    schedule_minute: int = Form(0),
    session: AsyncSession = Depends(get_session)
):
    """Update application settings."""
    # Update in-memory settings
    settings.dry_run = dry_run
    settings.schedule_hour = schedule_hour
    settings.schedule_minute = schedule_minute
    
    # Update scheduler
    from app.scheduler import update_schedule
    update_schedule(schedule_hour, schedule_minute)
    
    return RedirectResponse(url="/config", status_code=303)
