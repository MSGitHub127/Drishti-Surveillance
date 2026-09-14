"""
Model 1: Camera Registry & GIS Foundation Service
Manages camera onboarding, catalog synchronization (/api/ingest), PostGIS spatial queries, and health metrics.
"""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
import httpx
from sqlalchemy import select, func, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Camera, Department
from app.schemas import CameraCreate, CameraRead, CameraStats

logger = logging.getLogger("cctv.registry")

class CameraRegistryService:

    @staticmethod
    async def sync_catalog_from_api(session: AsyncSession, catalog_url: str) -> Dict[str, Any]:
        """
        Polls the hackathon camera catalogue (e.g. http://<host>/api/ingest)
        and upserts cameras into PostgreSQL + PostGIS.
        Catalogue is the contract: camera ids and stream URLs can change dynamically.
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(catalog_url)
                if resp.status_code != 200:
                    logger.warning(f"Catalog sync failed with HTTP {resp.status_code} from {catalog_url}")
                    return {"status": "error", "message": f"HTTP {resp.status_code}", "updated": 0}
                
                catalog_data = resp.json()
        except Exception as e:
            logger.error(f"Catalog poll exception from {catalog_url}: {e}")
            return {"status": "error", "message": str(e), "updated": 0}

        # Catalogue may return a list or an object with 'cameras'
        cameras_list = catalog_data if isinstance(catalog_data, list) else catalog_data.get("cameras", [])
        updated_count = 0

        for item in cameras_list:
            cam_id = str(item.get("id"))
            if not cam_id:
                continue

            # Extract URLs
            rtsp_url = item.get("rtsp") or item.get("stream_rtsp") or f"rtsp://localhost:8554/stream/{cam_id}"
            whep_url = item.get("whep") or item.get("stream_whep") or f"http://localhost:8889/stream/{cam_id}/whep"
            hls_url = item.get("hls") or item.get("stream_hls") or f"http://localhost:8888/stream/{cam_id}/index.m3u8"

            codec = item.get("codec", "H.264").upper()
            resolution = item.get("resolution", "1920x1080")
            fps = float(item.get("fps", 25.0))
            is_live = item.get("live", True)
            status = "online" if is_live else "offline"

            # Check if camera exists
            result = await session.execute(select(Camera).where(Camera.id == cam_id))
            existing_cam = result.scalar_one_or_none()

            if existing_cam:
                existing_cam.stream_rtsp = rtsp_url
                existing_cam.stream_whep = whep_url
                existing_cam.stream_hls = hls_url
                existing_cam.codec = codec
                existing_cam.resolution = resolution
                existing_cam.fps = fps
                existing_cam.status = status
                existing_cam.last_seen = datetime.utcnow()
            else:
                new_cam = Camera(
                    id=cam_id,
                    name=item.get("name", f"Catalogue Camera {cam_id}"),
                    dept_id=item.get("dept_id", "dept-police"),
                    camera_type=item.get("camera_type", "ANPR"),
                    lat=float(item.get("lat", 23.0)),
                    lng=float(item.get("lng", 72.5)),
                    location_name=item.get("location", f"Site {cam_id}"),
                    district=item.get("district", "Gujarat"),
                    city=item.get("city", "Gujarat"),
                    landmark=item.get("landmark", "Catalogue feed"),
                    status=status,
                    stream_rtsp=rtsp_url,
                    stream_whep=whep_url,
                    stream_hls=hls_url,
                    codec=codec,
                    resolution=resolution,
                    fps=fps,
                    storage_type=item.get("storage_type", "cloud"),
                    retention_days=int(item.get("retention_days", 15)),
                    last_seen=datetime.utcnow()
                )
                session.add(new_cam)
            updated_count += 1

        await session.commit()
        logger.info(f"Successfully synced {updated_count} cameras from catalogue {catalog_url}")
        return {"status": "success", "synced_cameras": updated_count}

    @staticmethod
    async def get_cameras(
        session: AsyncSession,
        department: Optional[str] = None,
        status: Optional[str] = None,
        district: Optional[str] = None,
        camera_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Camera]:
        """Lists cameras with optional filtering."""
        query = select(Camera)
        if department:
            # Join department code
            query = query.join(Department, Camera.dept_id == Department.id).where(Department.code == department.upper())
        if status:
            query = query.where(Camera.status == status.lower())
        if district:
            query = query.where(Camera.district.ilike(f"%{district}%"))
        if camera_type:
            query = query.where(Camera.camera_type == camera_type)

        query = query.order_by(Camera.name).limit(limit).offset(offset)
        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def get_camera_by_id(session: AsyncSession, camera_id: str) -> Optional[Camera]:
        """Retrieves a single camera by ID."""
        result = await session.execute(select(Camera).where(Camera.id == camera_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_cameras_in_bounding_box(
        session: AsyncSession,
        min_lat: float,
        min_lng: float,
        max_lat: float,
        max_lng: float
    ) -> List[Camera]:
        """
        Executes PostGIS ST_MakeEnvelope spatial query to retrieve all cameras
        strictly within the geographical bounding box.
        """
        try:
            # Native PostGIS spatial query using ST_MakeEnvelope
            sql = text("""
                SELECT id FROM cameras 
                WHERE geom && ST_MakeEnvelope(:min_lng, :min_lat, :max_lng, :max_lat, 4326)
                   OR (lat BETWEEN :min_lat AND :max_lat AND lng BETWEEN :min_lng AND :max_lng)
            """)
            result = await session.execute(sql, {
                "min_lng": min_lng, "min_lat": min_lat,
                "max_lng": max_lng, "max_lat": max_lat
            })
            cam_ids = [row[0] for row in result.fetchall()]
            if not cam_ids:
                return []
            
            cams_result = await session.execute(select(Camera).where(Camera.id.in_(cam_ids)))
            return list(cams_result.scalars().all())
        except Exception as e:
            logger.warning(f"PostGIS spatial query failed, falling back to coordinate bounds: {e}")
            query = select(Camera).where(
                Camera.lat >= min_lat, Camera.lat <= max_lat,
                Camera.lng >= min_lng, Camera.lng <= max_lng
            )
            res = await session.execute(query)
            return list(res.scalars().all())

    @staticmethod
    async def get_statistics(session: AsyncSession) -> CameraStats:
        """Returns statewide camera operational metrics, breakdown by department, codec, and storage."""
        # Total counts
        total_res = await session.execute(select(func.count(Camera.id)))
        total_cameras = total_res.scalar_one() or 0

        online_res = await session.execute(select(func.count(Camera.id)).where(Camera.status == 'online'))
        online_cameras = online_res.scalar_one() or 0
        offline_cameras = total_cameras - online_cameras

        # By Department
        dept_sql = text("""
            SELECT COALESCE(d.code, 'OTHER') as dept_code, COUNT(c.id) 
            FROM cameras c
            LEFT JOIN departments d ON c.dept_id = d.id
            GROUP BY d.code
        """)
        dept_res = await session.execute(dept_sql)
        by_department = {row[0]: row[1] for row in dept_res.fetchall()}

        # By Codec
        codec_sql = text("SELECT codec, COUNT(id) FROM cameras GROUP BY codec")
        codec_res = await session.execute(codec_sql)
        by_codec = {row[0]: row[1] for row in codec_res.fetchall()}

        # By Storage Type
        storage_sql = text("SELECT storage_type, COUNT(id) FROM cameras GROUP BY storage_type")
        storage_res = await session.execute(storage_sql)
        by_storage = {row[0]: row[1] for row in storage_res.fetchall()}

        # By District
        dist_sql = text("SELECT district, COUNT(id) FROM cameras GROUP BY district ORDER BY COUNT(id) DESC LIMIT 10")
        dist_res = await session.execute(dist_sql)
        by_district = {row[0]: row[1] for row in dist_res.fetchall()}

        return CameraStats(
            total_cameras=total_cameras,
            online_cameras=online_cameras,
            offline_cameras=offline_cameras,
            by_department=by_department,
            by_codec=by_codec,
            by_storage=by_storage,
            by_district=by_district
        )

    @staticmethod
    async def update_camera_status(session: AsyncSession, camera_id: str, status: str):
        """Updates camera connectivity status (online / offline / maintenance)."""
        await session.execute(
            update(Camera)
            .where(Camera.id == camera_id)
            .values(status=status, last_seen=datetime.utcnow())
        )
        await session.commit()
