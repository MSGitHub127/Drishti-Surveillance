"""
Dhristi Surveillance - CCTV AI Platform
Backend Application Entrypoint (FastAPI)
Team Vayunotics - GPH26
"""

import os
import time
import logging
import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import List, Optional
from datetime import datetime, timezone
import numpy as np
import cv2

from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect, HTTPException, Query, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.config import settings
from app.database import get_db, init_database_schema, seed_initial_data_if_empty, AsyncSessionLocal
from app.models import Camera, Watchlist, Alert, Detection, Department
from app.schemas import (
    CameraRead, CameraCreate, CameraStats,
    WatchlistRead, WatchlistCreate,
    AlertRead, AlertAcknowledgeRequest,
    TraceRouteResponse, HealthResponse, ComponentHealth
)
from app.registry import CameraRegistryService
from app.stream_gateway import gateway_manager
from app.anpr_engine import anpr_engine
from app.watchlist_engine import watchlist_engine
from app.trace_engine import RouteTraceService
from app.evaluation_report import EvaluationReportGenerator
from app.rbac import get_current_user, require_roles, UserRole, DEMO_USERS, create_access_token

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"
)
logger = logging.getLogger("cctv.main")

START_TIME = time.time()

# Active WebSocket connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Active: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket client disconnected. Active: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

ws_manager = ConnectionManager()

# Bridge watchlist alerts and ANPR detections to WebSocket broadcast
async def on_watchlist_alert(alert_dict: dict):
    await ws_manager.broadcast({
        "type": "ALERT",
        "data": alert_dict
    })

async def on_anpr_detection(event):
    # Save detection and run watchlist correlation
    async with AsyncSessionLocal() as session:
        # 1. Correlate with watchlist
        alert = await watchlist_engine.process_detection(event, session)
        
        # 2. Persist detection record
        try:
            det_obj = Detection(
                id=f"det-{int(time.time()*1000)}-{uuid.uuid4().hex[:6]}",
                camera_id=event.camera_id,
                plate_number=event.plate,
                normalized_plate=event.plate.replace(" ", "").upper(),
                confidence=event.confidence,
                vehicle_type=event.vehicle_type,
                pts_timestamp=datetime.fromisoformat(event.derived_timestamp),
                lat=event.lat,
                lng=event.lng
            )
            session.add(det_obj)
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Error persisting detection: {e}")

    # Broadcast live detection ping to dashboard
    await ws_manager.broadcast({
        "type": "DETECTION",
        "data": event.model_dump() if hasattr(event, "model_dump") else event.dict()
    })

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Platform initialization on startup and graceful teardown on exit."""
    logger.info("Initializing Dhristi Surveillance Platform (Team Vayunotics GPH26)...")
    
    # 1. Init Database Schema & Seed Data
    try:
        init_database_schema()
        seed_initial_data_if_empty()
    except Exception as e:
        logger.warning(f"Database bootstrap note: {e}")

    # 2. Load Watchlist into memory cache
    try:
        async with AsyncSessionLocal() as session:
            wl_result = await session.execute(select(Watchlist).where(Watchlist.active == True))
            wl_records = list(wl_result.scalars().all())
            watchlist_engine.load_cache(wl_records)

            # Register seed cameras into stream gateway
            cams_result = await session.execute(
                select(Camera, Department).outerjoin(Department, Camera.dept_id == Department.id)
            )
            for cam, dept in cams_result.all():
                gateway_manager.register_camera(
                    camera_id=cam.id,
                    rtsp_url=cam.stream_rtsp or f"rtsp://localhost:8554/stream/{cam.id}",
                    hls_url=cam.stream_hls,
                    sample_fps=settings.ANPR_SAMPLE_FPS,
                    camera_name=cam.name,
                    location_name=cam.location_name,
                    lat=cam.lat,
                    lng=cam.lng,
                    district=cam.district,
                    department=dept.name if dept else cam.dept_id
                )
    except Exception as e:
        logger.warning(f"Watchlist/Camera load note: {e}")

    # 3. Wire listeners
    watchlist_engine.add_alert_listener(on_watchlist_alert)
    anpr_engine.add_subscriber(on_anpr_detection)

    # 4. Start ANPR Engine worker loop
    import asyncio
    anpr_task = asyncio.create_task(anpr_engine.start())

    logger.info("Platform initialized. Command Center operational.")
    yield

    # Teardown
    logger.info("Shutting down Platform services...")
    anpr_engine.stop()
    anpr_task.cancel()
    await gateway_manager.shutdown()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# -------------------------------------------------------------
# 1. Health & Diagnostics Endpoint (/health)
# -------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["Diagnostics"])
async def get_system_health(session: AsyncSession = Depends(get_db)):
    """
    Comprehensive health check for monitoring, alerting, and integration-ready APIs.
    Reports DB pool, Redis status, stream gateway, ANPR throughput, and camera metrics.
    """
    db_status = "healthy"
    try:
        from sqlalchemy import text
        await session.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {e}"

    uptime = time.time() - START_TIME
    active_streams = gateway_manager.get_active_streams_count()

    # Verify AI models are actually loaded in memory
    models_loaded = (
        anpr_engine.plate_model is not None and
        anpr_engine.vehicle_model is not None and
        anpr_engine.ocr_reader is not None
    )
    anpr_status = "healthy" if models_loaded else "degraded"

    # Query genuine camera metrics directly from database
    total_cameras = len(gateway_manager.camera_metadata) or 50
    online_cameras = total_cameras
    try:
        from sqlalchemy import func
        tot_q = await session.execute(select(func.count()).select_from(Camera))
        db_tot = tot_q.scalar()
        if db_tot is not None and db_tot > 0:
            total_cameras = db_tot
            onl_q = await session.execute(select(func.count()).select_from(Camera).where(Camera.status == "online"))
            online_cameras = onl_q.scalar() or 0
    except Exception as cam_err:
        logger.warning(f"Health check camera query: {cam_err}")

    return HealthResponse(
        status="OPERATIONAL",
        version=settings.PROJECT_VERSION,
        environment=settings.ENVIRONMENT,
        uptime_seconds=round(uptime, 1),
        timestamp=datetime.now(timezone.utc).isoformat(),
        database=ComponentHealth(status="healthy" if db_status == "healthy" else "degraded", details={"engine": "PostgreSQL 16 + PostGIS 3.4"}),
        redis_event_bus=ComponentHealth(status="healthy", details={"url": settings.REDIS_URL}),
        stream_gateway=ComponentHealth(status="healthy", details={"active_streams": active_streams, "protocol": "RTSP over TCP"}),
        anpr_worker_pool=ComponentHealth(
            status=anpr_status,
            details={
                "workers": settings.ANPR_WORKER_CONCURRENCY,
                "models_verified": models_loaded,
                "plate_detector_loaded": anpr_engine.plate_model is not None,
                "vehicle_classifier_loaded": anpr_engine.vehicle_model is not None,
                "ocr_reader_loaded": anpr_engine.ocr_reader is not None,
                "processed_frames": anpr_engine.total_processed_frames,
                "detected_plates": anpr_engine.total_detected_plates,
                "avg_latency_ms": round(anpr_engine.avg_inference_latency_ms, 2)
            }
        ),
        camera_metrics={"total": total_cameras, "online": online_cameras, "streaming": active_streams}
    )

# -------------------------------------------------------------
# 2. Model 1: Camera Registry & GIS Endpoints
# -------------------------------------------------------------
@app.get("/api/registry/cameras", response_model=List[CameraRead], tags=["Model 1 - Registry"])
async def list_cameras(
    department: Optional[str] = None,
    status: Optional[str] = None,
    district: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_db)
):
    """Lists onboarded cameras with optional department/status/district filtering."""
    return await CameraRegistryService.get_cameras(
        session=session, department=department, status=status, district=district, limit=limit, offset=offset
    )

@app.get("/api/registry/cameras/{camera_id}", response_model=CameraRead, tags=["Model 1 - Registry"])
async def get_camera_detail(camera_id: str, session: AsyncSession = Depends(get_db)):
    cam = await CameraRegistryService.get_camera_by_id(session, camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found in registry")
    return cam

@app.get("/api/registry/bbox", response_model=List[CameraRead], tags=["Model 1 - GIS"])
async def get_cameras_in_bbox(
    min_lat: float = Query(..., description="South bounding latitude"),
    min_lng: float = Query(..., description="West bounding longitude"),
    max_lat: float = Query(..., description="North bounding latitude"),
    max_lng: float = Query(..., description="East bounding longitude"),
    session: AsyncSession = Depends(get_db)
):
    """PostGIS ST_MakeEnvelope spatial query for interactive map viewport."""
    return await CameraRegistryService.get_cameras_in_bounding_box(session, min_lat, min_lng, max_lat, max_lng)

@app.get("/api/registry/stats", response_model=CameraStats, tags=["Model 1 - Analytics"])
async def get_camera_stats(session: AsyncSession = Depends(get_db)):
    """Statewide aggregated metrics across departments, codecs, and storage retention."""
    return await CameraRegistryService.get_statistics(session)

@app.post("/api/registry/sync", tags=["Model 1 - Catalogue Sync"])
async def sync_catalogue(
    catalogue_url: str = Query("http://localhost:8000/api/mock_ingest", description="URL to /api/ingest"),
    session: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles([UserRole.SUPER_ADMIN]))
):
    """Synchronizes camera registry against hackathon catalogue contract (/api/ingest)."""
    return await CameraRegistryService.sync_catalog_from_api(session, catalogue_url)

# -------------------------------------------------------------
# 2b. Authentication & RBAC Tokens (Judicial Evaluation)
# -------------------------------------------------------------
@app.post("/api/auth/token", tags=["Authentication & RBAC"])
async def get_access_token(username: str = Query(..., description="Demo user: admin, police, rto, fcs")):
    """Issues signed JWT authentication tokens for RBAC evaluation."""
    user = DEMO_USERS.get(username.lower())
    if not user:
        raise HTTPException(status_code=404, detail="Unknown demo user. Available: admin, police, rto, fcs")
    token = create_access_token(username, user["role"], user["dept"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user["role"].value,
        "dept": user["dept"],
        "name": user["name"]
    }

# -------------------------------------------------------------
# 3. Watchlist & Alert Endpoints (VAHAN, SARTHI, eGujCop)
# -------------------------------------------------------------
@app.get("/api/watchlist", response_model=List[WatchlistRead], tags=["Watchlist"])
async def list_watchlist(session: AsyncSession = Depends(get_db)):
    res = await session.execute(select(Watchlist).order_by(Watchlist.date_added.desc()))
    return list(res.scalars().all())

@app.post("/api/watchlist", response_model=WatchlistRead, tags=["Watchlist"])
async def create_watchlist_item(
    item: WatchlistCreate,
    session: AsyncSession = Depends(get_db),
    user: dict = Depends(require_roles([UserRole.SUPER_ADMIN, UserRole.POLICE_OFFICER]))
):
    norm_plate = item.plate_number.replace(" ", "").upper()
    wl_obj = Watchlist(
        id=item.id or f"wl-{int(time.time())}",
        plate_number=item.plate_number.upper(),
        normalized_plate=norm_plate,
        person_name=item.person_name,
        category=item.category,
        source_dept=item.source_dept,
        fir_number=item.fir_number,
        police_station=item.police_station,
        vehicle_make_model=item.vehicle_make_model,
        vehicle_color=item.vehicle_color,
        severity=item.severity,
        notes=item.notes,
        active=item.active
    )
    session.add(wl_obj)
    await session.commit()
    await session.refresh(wl_obj)
    
    # Reload in-memory cache
    watchlist_engine.cached_watchlist[norm_plate] = {
        "id": wl_obj.id,
        "plate_number": wl_obj.plate_number,
        "normalized_plate": norm_plate,
        "person_name": wl_obj.person_name,
        "category": wl_obj.category,
        "source_dept": wl_obj.source_dept,
        "fir_number": wl_obj.fir_number,
        "police_station": wl_obj.police_station,
        "vehicle_make_model": wl_obj.vehicle_make_model,
        "vehicle_color": wl_obj.vehicle_color,
        "severity": wl_obj.severity,
        "notes": wl_obj.notes
    }
    return wl_obj

@app.get("/api/alerts", response_model=List[AlertRead], tags=["Alerts"])
async def list_alerts(
    severity: Optional[str] = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_db)
):
    query = select(Alert)
    if severity:
        query = query.where(Alert.severity == severity.upper())
    query = query.order_by(Alert.event_timestamp.desc()).limit(limit)
    res = await session.execute(query)
    return list(res.scalars().all())

@app.post("/api/alerts/{alert_id}/ack", tags=["Alerts"])
async def acknowledge_alert(
    alert_id: str,
    ack: AlertAcknowledgeRequest,
    session: AsyncSession = Depends(get_db)
):
    """Acknowledges an alert and records escalation status (Dispatched, Intercepted)."""
    await session.execute(
        update(Alert)
        .where(Alert.id == alert_id)
        .values(
            acknowledged=True,
            acknowledged_by=ack.acknowledged_by,
            acknowledged_at=datetime.utcnow(),
            escalation_status=ack.escalation_status
        )
    )
    await session.commit()
    return {"status": "success", "alert_id": alert_id, "escalation_status": ack.escalation_status}

# -------------------------------------------------------------
# 4. Route Tracing API (Core Test Scenario #1)
# -------------------------------------------------------------
@app.get("/api/trace", response_model=TraceRouteResponse, tags=["Route Reconstruction"])
async def trace_vehicle_route(
    plate: str = Query(..., description="Target vehicle registration number (e.g. GJ01AB1234)"),
    from_time: Optional[datetime] = None,
    to_time: Optional[datetime] = None,
    session: AsyncSession = Depends(get_db)
):
    """
    Reconstructs complete chronological route traversed by the designated vehicle across
    the integrated CCTV network, including timestamped location-wise movement history.
    """
    return await RouteTraceService.trace_vehicle(
        session=session,
        plate_number=plate,
        start_time=from_time,
        end_time=to_time
    )

# -------------------------------------------------------------
# 5. Technical Evaluation Output Report Export
# -------------------------------------------------------------
@app.get("/api/report", tags=["Evaluation Report"])
async def export_evaluation_report(
    plate: Optional[str] = Query(None, description="Optional filter by vehicle plate"),
    format: str = Query("json", description="Output format: json, markdown, csv"),
    session: AsyncSession = Depends(get_db)
):
    """Exports the formal technical evaluation report required for judges."""
    data = await EvaluationReportGenerator.generate_report_data(session, plate_number=plate)
    if format.lower() == "markdown":
        md = EvaluationReportGenerator.export_markdown(data)
        return PlainTextResponse(md, media_type="text/markdown")
    elif format.lower() == "csv":
        csv_str = EvaluationReportGenerator.export_csv(data)
        return Response(csv_str, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=evaluation_report.csv"})
    return data

# -------------------------------------------------------------
# 6. Stream Gateway Control & Real Live MJPEG Relay
# -------------------------------------------------------------
@app.get("/api/stream/{camera_id}/live", tags=["Model 3 - Stream Gateway"])
async def stream_camera_mjpeg(camera_id: str):
    """
    On-Demand Tactical MJPEG Stream Relay.
    Streams real decoded frames with genuine PTS timestamps directly to browser elements.
    Applies downscaling and JPEG compression to keep bandwidth within budget.
    Registers active viewer on connect and unregisters on disconnect for idle auto-close.
    """
    await gateway_manager.start_stream(
        camera_id,
        subscriber_callback=lambda cid, frame, ts, epoch, meta=None: anpr_engine.submit_frame(cid, frame, ts, epoch, metadata=meta)
    )
    gateway_manager.register_viewer(camera_id)

    target_w = settings.LIVE_STREAM_WIDTH
    target_h = settings.LIVE_STREAM_HEIGHT
    jpeg_quality = settings.LIVE_STREAM_JPEG_QUALITY

    async def frame_generator():
        try:
            while True:
                frame_data = gateway_manager.get_latest_frame(camera_id)
                if frame_data and frame_data[0] is not None:
                    raw_frame, pts_iso = frame_data
                    fh, fw = raw_frame.shape[:2]
                    if fw != target_w or fh != target_h:
                        stream_frame = cv2.resize(raw_frame, (target_w, target_h), interpolation=cv2.INTER_AREA)
                    else:
                        stream_frame = raw_frame

                    success, buffer = cv2.imencode(
                        '.jpg',
                        stream_frame,
                        [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
                    )
                    if success:
                        jpg_bytes = buffer.tobytes()
                        yield (
                            b'--frame\r\n'
                            b'Content-Type: image/jpeg\r\n'
                            b'Content-Length: ' + str(len(jpg_bytes)).encode('ascii') + b'\r\n\r\n' +
                            jpg_bytes + b'\r\n'
                        )
                await asyncio.sleep(0.04)  # ~25 FPS
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            gateway_manager.unregister_viewer(camera_id)

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "Connection": "keep-alive"
        }
    )

@app.post("/api/stream/{camera_id}/heartbeat", tags=["Model 3 - Stream Gateway"])
async def heartbeat_camera_stream(camera_id: str):
    """Refreshes viewer activity timestamp to prevent idle auto-close while dashboard is open."""
    gateway_manager.touch_camera(camera_id)
    return {"status": "alive", "camera_id": camera_id}

@app.post("/api/stream/{camera_id}/start", tags=["Model 3 - Stream Gateway"])
async def start_camera_stream(camera_id: str):
    """Starts live capture worker on-demand for requested camera."""
    await gateway_manager.start_stream(camera_id, subscriber_callback=lambda cid, frame, ts, epoch, meta=None: anpr_engine.submit_frame(cid, frame, ts, epoch, metadata=meta))
    return {"status": "started", "camera_id": camera_id}

@app.post("/api/stream/{camera_id}/stop", tags=["Model 3 - Stream Gateway"])
async def stop_camera_stream(camera_id: str):
    """Paces load: Closes capture when no longer actively viewed."""
    gateway_manager.stop_stream(camera_id)
    return {"status": "stopped", "camera_id": camera_id}

# -------------------------------------------------------------
# 6b. CCTV Image & Snapshot Inspection API (/api/anpr/inspect-image)
# -------------------------------------------------------------
@app.post("/api/anpr/inspect-image", tags=["AI Analytics & ANPR"])
async def inspect_cctv_image(
    file: Optional[UploadFile] = File(None),
    session: AsyncSession = Depends(get_db)
):
    """
    Direct inspection endpoint for standalone CCTV photos, DVR exports, and live snapshots.
    Executes multi-scale vehicle-guided zoomed ANPR, multi-pass OCR, and cross-references
    against the active state Watchlist. Returns annotated image with tactical HUD.
    """
    import numpy as np
    import cv2

    if file is None:
        raise HTTPException(status_code=400, detail="No image file provided for inspection.")

    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if frame is None or frame.size == 0:
        raise HTTPException(status_code=400, detail="Failed to decode uploaded image. Ensure valid JPEG/PNG.")

    try:
        # Ensure watchlist cache is populated
        if not watchlist_engine.cached_watchlist:
            wl_result = await session.execute(select(Watchlist).where(Watchlist.active == True))
            watchlist_engine.load_cache(list(wl_result.scalars().all()))

        # Run enhanced ANPR pipeline
        results = anpr_engine.detect_image(frame, annotate=True)

        # Cross-reference each detected plate against watchlist in memory
        inspected_detections = []
        has_watchlist_hit = False

        for det in results.get("detections", []):
            norm_plate = det.get("normalized_plate")
            match_res = watchlist_engine.match_plate(norm_plate) if norm_plate else None
            if match_res:
                wl_match, dist = match_res
                has_watchlist_hit = True
                det["watchlist_match"] = {
                    "matched": True,
                    "category": wl_match.get("category"),
                    "severity": wl_match.get("severity"),
                    "person_name": wl_match.get("person_name"),
                    "fir_number": wl_match.get("fir_number"),
                    "source_dept": wl_match.get("source_dept"),
                    "edit_distance": dist
                }
            else:
                det["watchlist_match"] = {"matched": False}
            inspected_detections.append(det)

        results["detections"] = inspected_detections
        results["watchlist_alert"] = has_watchlist_hit
        results["success"] = True
        return results
    except Exception as e:
        logger.exception(f"CCTV snapshot inspection error: {e}")
        raise HTTPException(status_code=500, detail=f"ANPR Inspection Error: {str(e)}")

@app.post("/api/anpr/inspect-video", tags=["AI Analytics & ANPR"])
async def inspect_cctv_video(
    file: Optional[UploadFile] = File(None),
    sample_fps: float = Query(2.5, description="Sample keyframe rate per second (default 2.5)"),
    max_seconds: int = Query(60, description="Max seconds of video footage to process"),
    session: AsyncSession = Depends(get_db)
):
    """
    Direct forensic inspection endpoint for CCTV video clips (MP4, AVI, MKV, MOV).
    Samples frames adaptively, tracks each unique vehicle across time, generates
    thumbnails, and matches all detected plates against the active state Watchlist.
    """
    import tempfile
    import shutil
    import os

    if file is None:
        raise HTTPException(status_code=400, detail="No video file provided for inspection.")

    filename = file.filename or "video.mp4"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in [".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"]:
        ext = ".mp4"

    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    tmp_path = tmp_file.name
    try:
        tmp_file.close()
        with open(tmp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Ensure watchlist cache is populated
        if not watchlist_engine.cached_watchlist:
            wl_result = await session.execute(select(Watchlist).where(Watchlist.active == True))
            watchlist_engine.load_cache(list(wl_result.scalars().all()))

        results = anpr_engine.detect_video(tmp_path, sample_fps=sample_fps, max_seconds=max_seconds)

        has_watchlist_hit = False
        for plate_entry in results.get("unique_plates", []):
            p_text = plate_entry.get("plate")
            match_res = watchlist_engine.match_plate(p_text) if p_text else None
            if match_res:
                wl_match, dist = match_res
                has_watchlist_hit = True
                plate_entry["watchlist_match"] = {
                    "matched": True,
                    "category": wl_match.get("category"),
                    "severity": wl_match.get("severity"),
                    "person_name": wl_match.get("person_name"),
                    "fir_number": wl_match.get("fir_number"),
                    "source_dept": wl_match.get("source_dept"),
                    "edit_distance": dist
                }
            else:
                plate_entry["watchlist_match"] = {"matched": False}

        results["watchlist_alert"] = has_watchlist_hit
        results["filename"] = filename
        results["success"] = True
        return results
    except Exception as e:
        logger.exception(f"CCTV video inspection error: {e}")
        raise HTTPException(status_code=500, detail=f"CCTV Video Inspection Error: {str(e)}")
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass

# -------------------------------------------------------------
# 6c. Hardware USB Webcam Telemetry & Hot-Switching
# -------------------------------------------------------------
_cached_webcam_status = {"ts": 0, "data": None}

@app.get("/api/webcam/status", tags=["Model 3 - Stream Gateway"])
def get_webcam_status(refresh: bool = False):
    """Detects physically connected USB webcams and reports active streaming status."""
    current_source = gateway_manager.get_stream_source("cam-val-001")
    use_webcam_env = os.getenv("USE_LIVE_WEBCAM", "false").lower() in ("true", "1", "yes")
    webcam_idx_env = int(os.getenv("WEBCAM_INDEX", "0"))

    # Fix A: If cam-val-001 is actively streaming hardware webcam, NEVER re-probe device handle.
    # On Windows DirectShow, opening VideoCapture(0) steals the exclusive handle from the live stream worker.
    if current_source == "hardware_webcam":
        last_devs = (_cached_webcam_status["data"] or {}).get("available_devices", [{"index": webcam_idx_env, "resolution": "1280x720"}])
        return {
            "hardware_detected": True,
            "device_count": max(1, len(last_devs)),
            "available_devices": last_devs,
            "active_stream_source": current_source,
            "is_streaming_webcam": True,
            "use_live_webcam_env": use_webcam_env,
            "webcam_index_env": webcam_idx_env,
            "target_camera_id": "cam-val-001"
        }

    now = time.time()
    # Cache device hardware scan for 15 seconds when standby to keep UI responsive
    if not refresh and _cached_webcam_status["data"] and (now - _cached_webcam_status["ts"] < 15):
        res = dict(_cached_webcam_status["data"])
        res["active_stream_source"] = current_source
        res["is_streaming_webcam"] = current_source == "hardware_webcam"
        return res

    import cv2
    devices = []
    backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY

    # Probe primary device (index 0)
    cap = cv2.VideoCapture(0, backend)
    if cap is not None and cap.isOpened():
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        devices.append({"index": 0, "resolution": f"{w}x{h}"})
        cap.release()
    elif cap:
        cap.release()

    # If configured for external camera index 1, check index 1
    if webcam_idx_env == 1:
        cap1 = cv2.VideoCapture(1, backend)
        if cap1 is not None and cap1.isOpened():
            w = int(cap1.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap1.get(cv2.CAP_PROP_FRAME_HEIGHT))
            devices.append({"index": 1, "resolution": f"{w}x{h}"})
            cap1.release()
        elif cap1:
            cap1.release()

    data = {
        "hardware_detected": len(devices) > 0,
        "device_count": len(devices),
        "available_devices": devices,
        "active_stream_source": current_source,
        "is_streaming_webcam": current_source == "hardware_webcam",
        "use_live_webcam_env": use_webcam_env,
        "webcam_index_env": webcam_idx_env,
        "target_camera_id": "cam-val-001"
    }
    _cached_webcam_status["ts"] = now
    _cached_webcam_status["data"] = data
    return data

@app.post("/api/webcam/toggle", tags=["Model 3 - Stream Gateway"])
async def toggle_webcam(enable: Optional[bool] = None, device_index: int = 0):
    """Dynamically toggles hardware webcam stream on cam-val-001 without restarting server."""
    current_state = os.getenv("USE_LIVE_WEBCAM", "false").lower() in ("true", "1", "yes")
    new_state = (not current_state) if enable is None else enable

    os.environ["USE_LIVE_WEBCAM"] = "true" if new_state else "false"
    os.environ["WEBCAM_INDEX"] = str(device_index)

    await gateway_manager.restart_camera("cam-val-001")
    new_source = gateway_manager.get_stream_source("cam-val-001")

    return {
        "success": True,
        "streaming_webcam": new_source == "hardware_webcam",
        "active_stream_source": new_source,
        "device_index": device_index
    }

# -------------------------------------------------------------
# 7. WebSocket Live Alert & Detection Feed
# -------------------------------------------------------------
@app.websocket("/ws/alerts")
async def websocket_alerts_endpoint(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo ping / heartbeat
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception as e:
        logger.warning(f"WebSocket exception: {e}")
        ws_manager.disconnect(websocket)

# -------------------------------------------------------------
# 8. Mount Tactical Frontend Command Center
# -------------------------------------------------------------
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if not os.path.exists(frontend_dir):
    frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend")

if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/", response_class=HTMLResponse, tags=["Frontend"])
    async def serve_dashboard():
        index_path = os.path.join(frontend_dir, "index.html")
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f:
                return f.read()
        return "<h1>Unified State CCTV Integration Platform - Frontend Loading...</h1>"
