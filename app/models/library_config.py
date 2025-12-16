from sqlalchemy import String, Boolean, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class EmbyUser(Base):
    """Stores Emby users synced from the server."""
    
    __tablename__ = "emby_users"
    
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class EmbyLibrary(Base):
    """Stores Emby libraries synced from the server."""
    
    __tablename__ = "emby_libraries"
    
    id: Mapped[str] = mapped_column(String(100), primary_key=True)  # Emby ItemId
    guid: Mapped[str] = mapped_column(String(100), nullable=True)   # Emby Guid
    name: Mapped[str] = mapped_column(String(200))
    path: Mapped[str] = mapped_column(String(1000))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class EmbyLibraryFolder(Base):
    """Stores folder paths within each library with their subfolder IDs."""
    
    __tablename__ = "emby_library_folders"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[str] = mapped_column(String(100), ForeignKey("emby_libraries.id"))
    subfolder_id: Mapped[int] = mapped_column(Integer)  # The ID used in ExcludedSubFolders
    path: Mapped[str] = mapped_column(String(1000))


class LibraryUserMapping(Base):
    """Maps which users must have watched for each library."""
    
    __tablename__ = "library_user_mappings"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    library_id: Mapped[str] = mapped_column(String(100), ForeignKey("emby_libraries.id"))
    user_id: Mapped[str] = mapped_column(String(100), ForeignKey("emby_users.id"))
    required: Mapped[bool] = mapped_column(Boolean, default=True)
