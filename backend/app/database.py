"""
Database Module for Team Vayunotics CCTV Integration Platform
Target: PostgreSQL 16 + PostGIS 3.4 (Production / Docker Compose)
Provides zero-friction local fallback to SQLite if PostgreSQL daemon is not active.
"""

import os
import json
import logging
import socket
from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

logger = logging.getLogger("cctv.database")

Base = declarative_base()

def is_postgres_reachable(host: str = "localhost", port: int = 5432) -> bool:
    """Checks if PostgreSQL service port is accepting TCP connections."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False

# Determine primary vs fallback database URL
USE_POSTGRES = is_postgres_reachable(settings.DB_HOST, int(settings.DB_PORT))

if USE_POSTGRES:
    logger.info(f"Connected to PostgreSQL 16 + PostGIS 3.4 on {settings.DB_HOST}:{settings.DB_PORT}")
    ACTIVE_DATABASE_URL = settings.DATABASE_URL
    ACTIVE_DB_SYNC_URL = settings.DB_SYNC_URL
else:
    local_db_path = Path(__file__).resolve().parent.parent.parent / "data" / "cctv_local.db"
    logger.warning(
        f"PostgreSQL port {settings.DB_PORT} not reachable on {settings.DB_HOST}. "
        f"Using zero-friction local SQLite database at: {local_db_path}. "
        f"(Start Docker container 'postgis' to switch to PostgreSQL + PostGIS 3.4 automatically)."
    )
    ACTIVE_DATABASE_URL = f"sqlite+aiosqlite:///{local_db_path.as_posix()}"
    ACTIVE_DB_SYNC_URL = f"sqlite:///{local_db_path.as_posix()}"

# Async Engine for API endpoints
async_engine = create_async_engine(
    ACTIVE_DATABASE_URL,
    echo=False
)

# Async Session Factory
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# Synchronous Engine for initial DDL and seeding
sync_engine = create_engine(
    ACTIVE_DB_SYNC_URL,
    echo=False
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that yields an async database session for FastAPI endpoints."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as ex:
            await session.rollback()
            raise ex
        finally:
            await session.close()

def init_database_schema():
    """Initializes tables using init_db.sql on Postgres or SQLAlchemy metadata on local fallback."""
    if USE_POSTGRES:
        sql_path = Path(__file__).resolve().parent.parent.parent / "data" / "init_db.sql"
        if sql_path.exists():
            try:
                with sync_engine.connect() as conn:
                    with open(sql_path, "r", encoding="utf-8") as f:
                        sql_content = f.read()
                    conn.execute(text(sql_content))
                    conn.commit()
                    logger.info("PostgreSQL + PostGIS schema applied from init_db.sql")
            except Exception as e:
                logger.error(f"Error applying init_db.sql: {e}")
    else:
        # Create all tables via SQLAlchemy metadata on fallback
        from app.models import Department, Camera, Watchlist, Detection, Alert, User
        Base.metadata.create_all(bind=sync_engine)
        logger.info("Local database tables initialized via SQLAlchemy schema.")

def seed_initial_data_if_empty():
    """Seeds departments, 50 cameras, and watchlist records if the tables are empty."""
    from app.models import Department, Camera, Watchlist

    data_dir = Path(__file__).resolve().parent.parent.parent / "data"
    cameras_file = data_dir / "seed_cameras.json"
    watchlist_file = data_dir / "seed_watchlist.json"

    try:
        with SyncSessionLocal() as session:
            # 1. Seed departments
            dept_count = session.query(Department).count()
            if dept_count == 0:
                departments = [
                    Department(id="dept-police", code="POLICE", name="Gujarat Police / Home Department", category="Law Enforcement", nodal_officer="Shri V. P. Solanki (IPS)", contact_email="control.cctv@gujaratpolice.gov.in"),
                    Department(id="dept-rto", code="RTO", name="Gujarat Transport Department (RTO)", category="Transport", nodal_officer="Shri K. M. Patel", contact_email="rto.enforcement@gujarat.gov.in"),
                    Department(id="dept-fcs", code="FCS", name="Food, Civil Supplies & Consumer Affairs", category="Civil Supplies", nodal_officer="Smt. A. N. Joshi", contact_email="pds.surveillance@gscsc.gov.in"),
                    Department(id="dept-ports", code="PORTS", name="Gujarat Maritime Board / Ports Authority", category="Maritime & Ports", nodal_officer="Capt. R. K. Vaghela", contact_email="security@gmbports.gov.in"),
                    Department(id="dept-forest", code="FOREST", name="Gujarat Forest & Environment Department", category="Forestry & Wildlife", nodal_officer="Shri D. S. Meena (IFS)", contact_email="wildlife.vigilance@gujarat.gov.in"),
                    Department(id="dept-private", code="PRIVATE", name="Permitted Public-Facing Private Establishments", category="Commercial & Residential", nodal_officer="State Surveillance Cell", contact_email="private.cctv@surveillance.gov.in")
                ]
                session.add_all(departments)
                session.commit()
                logger.info(f"Seeded {len(departments)} core departments.")

            # 2. Seed 50 cameras
            cam_count = session.query(Camera).count()
            if cam_count == 0 and cameras_file.exists():
                with open(cameras_file, "r", encoding="utf-8") as f:
                    cams_data = json.load(f)
                
                dept_map = {d.code: d.id for d in session.query(Department).all()}
                cameras_to_add = []
                for c in cams_data:
                    dept_id = dept_map.get(c.get("dept_code", "POLICE"), "dept-police")
                    cam = Camera(
                        id=c["id"],
                        name=c["name"],
                        dept_id=dept_id,
                        camera_type=c.get("camera_type", "ANPR"),
                        lat=c["lat"],
                        lng=c["lng"],
                        location_name=c.get("location_name", ""),
                        district=c.get("district", ""),
                        city=c.get("city", ""),
                        landmark=c.get("landmark", ""),
                        status=c.get("status", "online"),
                        stream_rtsp=c.get("stream_rtsp", ""),
                        stream_whep=c.get("stream_whep", ""),
                        stream_hls=c.get("stream_hls", ""),
                        codec=c.get("codec", "H.264"),
                        resolution=c.get("resolution", "1920x1080"),
                        fps=c.get("fps", 25.0),
                        storage_type=c.get("storage_type", "cloud"),
                        retention_days=c.get("retention_days", 15),
                        vms_vendor=c.get("vms_vendor", "Standard ONVIF"),
                        amc_status=c.get("amc_status", "Active")
                    )
                    cameras_to_add.append(cam)
                session.add_all(cameras_to_add)
                session.commit()
                logger.info(f"Seeded {len(cameras_to_add)} geographically dispersed cameras.")

            # 3. Seed representative watchlist
            wl_count = session.query(Watchlist).count()
            if wl_count == 0 and watchlist_file.exists():
                with open(watchlist_file, "r", encoding="utf-8") as f:
                    wl_data = json.load(f)
                
                watchlist_items = []
                for w in wl_data:
                    item = Watchlist(
                        id=w["id"],
                        plate_number=w["plate_number"],
                        normalized_plate=w.get("normalized_plate", w["plate_number"].replace(" ", "").upper()),
                        person_name=w.get("person_name", ""),
                        category=w.get("category", "Stolen Vehicle"),
                        source_dept=w.get("source_dept", "eGujCop"),
                        fir_number=w.get("fir_number", ""),
                        police_station=w.get("police_station", ""),
                        vehicle_make_model=w.get("vehicle_make_model", ""),
                        vehicle_color=w.get("vehicle_color", ""),
                        severity=w.get("severity", "CRITICAL"),
                        notes=w.get("notes", ""),
                        active=w.get("active", True)
                    )
                    watchlist_items.append(item)
                session.add_all(watchlist_items)
                session.commit()
                logger.info(f"Seeded {len(watchlist_items)} representative watchlist records.")
    except Exception as e:
        logger.error(f"Error seeding database: {e}")
