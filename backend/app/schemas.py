"""
Pydantic Schemas for Request/Response validation and WebSocket message framing.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# -------------------------------------------------------------
# 1. Department Schemas
# -------------------------------------------------------------
class DepartmentBase(BaseModel):
    code: str
    name: str
    category: str
    nodal_officer: Optional[str] = None
    contact_email: Optional[str] = None

class DepartmentRead(DepartmentBase):
    id: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

# -------------------------------------------------------------
# 2. Camera Schemas (Model 1 Registry)
# -------------------------------------------------------------
class CameraBase(BaseModel):
    name: str
    camera_type: str = "ANPR"
    lat: float
    lng: float
    location_name: str
    district: str
    city: str
    landmark: Optional[str] = None
    status: str = "online"
    stream_rtsp: Optional[str] = None
    stream_whep: Optional[str] = None
    stream_hls: Optional[str] = None
    codec: str = "H.264"
    resolution: str = "1920x1080"
    fps: float = 25.0
    storage_type: str = "cloud"
    retention_days: int = 15
    vms_vendor: str = "Standard ONVIF"
    amc_status: str = "Active"

class CameraCreate(CameraBase):
    id: str
    dept_code: Optional[str] = "POLICE"

class CameraRead(CameraBase):
    id: str
    dept_id: Optional[str] = None
    last_seen: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class CameraStats(BaseModel):
    total_cameras: int
    online_cameras: int
    offline_cameras: int
    by_department: Dict[str, int]
    by_codec: Dict[str, int]
    by_storage: Dict[str, int]
    by_district: Dict[str, int]

# -------------------------------------------------------------
# 3. Watchlist Schemas
# -------------------------------------------------------------
class WatchlistBase(BaseModel):
    plate_number: str
    person_name: Optional[str] = None
    category: str  # Stolen Vehicle, Wanted Criminal, Missing Person, Blacklisted Vehicle, Suspect
    source_dept: str  # eGujCop, VAHAN, SARTHI, AFIS, NAFIS
    fir_number: Optional[str] = None
    police_station: Optional[str] = None
    vehicle_make_model: Optional[str] = None
    vehicle_color: Optional[str] = None
    severity: str = "CRITICAL"
    notes: Optional[str] = None
    active: bool = True

class WatchlistCreate(WatchlistBase):
    id: Optional[str] = None

class WatchlistRead(WatchlistBase):
    id: str
    normalized_plate: str
    date_added: Optional[datetime] = None

    class Config:
        from_attributes = True

# -------------------------------------------------------------
# 4. Detection & Event Schemas
# -------------------------------------------------------------
class PlateDetectionEvent(BaseModel):
    plate: str
    confidence: float
    camera_id: str
    derived_timestamp: str  # ISO-8601 derived from PTS anchor
    lat: Optional[float] = None
    lng: Optional[float] = None
    location_name: Optional[str] = None
    district: Optional[str] = None
    department: Optional[str] = None
    vehicle_type: Optional[str] = "Car"
    vehicle_color: Optional[str] = None
    bbox: Optional[List[float]] = None  # Pixel [x1, y1, x2, y2]
    frame_width: Optional[int] = 1280
    frame_height: Optional[int] = 720
    snapshot_url: Optional[str] = None
    crop_url: Optional[str] = None

class DetectionRead(BaseModel):
    id: str
    camera_id: str
    plate_number: str
    normalized_plate: str
    confidence: float
    vehicle_type: Optional[str] = None
    vehicle_color: Optional[str] = None
    pts_timestamp: datetime
    wall_clock_time: datetime
    lat: Optional[float] = None
    lng: Optional[float] = None
    snapshot_url: Optional[str] = None
    crop_url: Optional[str] = None

    class Config:
        from_attributes = True

# -------------------------------------------------------------
# 5. Alert Schemas
# -------------------------------------------------------------
class AlertRead(BaseModel):
    id: str
    alert_code: str
    plate_number: str
    watchlist_id: Optional[str] = None
    detection_id: Optional[str] = None
    camera_id: Optional[str] = None
    location_name: str
    district: str
    department: str
    severity: str
    category: str
    event_timestamp: datetime
    snapshot_url: Optional[str] = None
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    escalation_status: str = "NEW"
    created_at: Optional[datetime] = None

    # Enriched context
    suspect_name: Optional[str] = None
    source_database: Optional[str] = None
    fir_reference: Optional[str] = None

    class Config:
        from_attributes = True

class AlertAcknowledgeRequest(BaseModel):
    acknowledged_by: str
    escalation_status: str = "DISPATCHED"  # DISPATCHED, INTERCEPTED, FALSE_POSITIVE

# -------------------------------------------------------------
# 6. Route Trace Schemas (Vehicle Movement History)
# -------------------------------------------------------------
class TracePoint(BaseModel):
    step_number: int
    camera_id: str
    camera_name: str
    department: str
    district: str
    location_name: str
    lat: float
    lng: float
    timestamp: str  # ISO-8601 derived from PTS
    epoch_seconds: float
    time_delta_sec: float
    distance_km_from_prev: float
    estimated_speed_kmh: float
    snapshot_url: Optional[str] = None
    crop_url: Optional[str] = None

class TraceRouteResponse(BaseModel):
    plate_number: str
    total_sightings: int
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    total_distance_km: float
    average_speed_kmh: float
    active_watchlist_match: Optional[WatchlistRead] = None
    trajectory: List[TracePoint]

# -------------------------------------------------------------
# 7. System Health & Diagnostics (/health)
# -------------------------------------------------------------
class ComponentHealth(BaseModel):
    status: str  # healthy, degraded, unreachable
    details: Optional[Dict[str, Any]] = None

class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    uptime_seconds: float
    timestamp: str
    database: ComponentHealth
    redis_event_bus: ComponentHealth
    stream_gateway: ComponentHealth
    anpr_worker_pool: ComponentHealth
    camera_metrics: Dict[str, int]
