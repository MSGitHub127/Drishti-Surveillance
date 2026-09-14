"""
SQLAlchemy ORM Models for Team Vayunotics CCTV Platform
Maps PostgreSQL + PostGIS schema entities.
"""

from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base

class Department(Base):
    __tablename__ = "departments"

    id = Column(String(64), primary_key=True)
    code = Column(String(32), unique=True, nullable=False)
    name = Column(String(255), nullable=False)
    category = Column(String(64), nullable=False)
    nodal_officer = Column(String(128), nullable=True)
    contact_email = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    cameras = relationship("Camera", back_populates="department")

class Camera(Base):
    __tablename__ = "cameras"

    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    dept_id = Column(String(64), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True)
    camera_type = Column(String(64), default="ANPR")
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    location_name = Column(String(255), nullable=False)
    district = Column(String(128), nullable=False)
    city = Column(String(128), nullable=False)
    landmark = Column(String(255), nullable=True)
    status = Column(String(32), default="online")  # online, offline, maintenance
    stream_rtsp = Column(String(512), nullable=True)
    stream_whep = Column(String(512), nullable=True)
    stream_hls = Column(String(512), nullable=True)
    codec = Column(String(32), default="H.264")
    resolution = Column(String(32), default="1920x1080")
    fps = Column(Float, default=25.0)
    storage_type = Column(String(32), default="cloud")  # cloud, local, hybrid
    retention_days = Column(Integer, default=15)
    vms_vendor = Column(String(64), default="Standard ONVIF")
    amc_status = Column(String(64), default="Active")
    last_seen = Column(DateTime(timezone=True), default=datetime.utcnow)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    department = relationship("Department", back_populates="cameras")
    detections = relationship("Detection", back_populates="camera")
    alerts = relationship("Alert", back_populates="camera")

class Watchlist(Base):
    __tablename__ = "watchlist"

    id = Column(String(64), primary_key=True)
    plate_number = Column(String(32), nullable=False, index=True)
    normalized_plate = Column(String(32), nullable=False, index=True)
    person_name = Column(String(128), nullable=True)
    category = Column(String(64), nullable=False)  # Stolen Vehicle, Wanted Criminal, Missing Person, Blacklisted Vehicle, Suspect
    source_dept = Column(String(64), nullable=False)  # eGujCop, VAHAN, SARTHI, AFIS, NAFIS
    fir_number = Column(String(128), nullable=True)
    police_station = Column(String(128), nullable=True)
    vehicle_make_model = Column(String(128), nullable=True)
    vehicle_color = Column(String(64), nullable=True)
    severity = Column(String(32), default="CRITICAL")  # CRITICAL, HIGH, MEDIUM, LOW
    notes = Column(Text, nullable=True)
    active = Column(Boolean, default=True)
    date_added = Column(DateTime(timezone=True), default=datetime.utcnow)

    alerts = relationship("Alert", back_populates="watchlist_item")

class Detection(Base):
    __tablename__ = "detections"

    id = Column(String(64), primary_key=True)
    camera_id = Column(String(64), ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False)
    plate_number = Column(String(32), nullable=False)
    normalized_plate = Column(String(32), nullable=False, index=True)
    confidence = Column(Float, nullable=False)
    vehicle_type = Column(String(64), default="Car")
    vehicle_color = Column(String(64), nullable=True)
    pts_timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    wall_clock_time = Column(DateTime(timezone=True), default=datetime.utcnow)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    snapshot_url = Column(Text, nullable=True)
    crop_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    camera = relationship("Camera", back_populates="detections")
    alerts = relationship("Alert", back_populates="detection")

class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String(64), primary_key=True)
    alert_code = Column(String(32), unique=True, nullable=False)
    plate_number = Column(String(32), nullable=False, index=True)
    watchlist_id = Column(String(64), ForeignKey("watchlist.id", ondelete="SET NULL"), nullable=True)
    detection_id = Column(String(64), ForeignKey("detections.id", ondelete="SET NULL"), nullable=True)
    camera_id = Column(String(64), ForeignKey("cameras.id", ondelete="SET NULL"), nullable=True)
    location_name = Column(String(255), nullable=False)
    district = Column(String(128), nullable=False)
    department = Column(String(64), nullable=False)
    severity = Column(String(32), nullable=False)  # CRITICAL, HIGH, MEDIUM, LOW
    category = Column(String(64), nullable=False)
    event_timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    snapshot_url = Column(Text, nullable=True)
    acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(String(128), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    escalation_status = Column(String(64), default="NEW")  # NEW, DISPATCHED, INTERCEPTED, FALSE_POSITIVE
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    watchlist_item = relationship("Watchlist", back_populates="alerts")
    detection = relationship("Detection", back_populates="alerts")
    camera = relationship("Camera", back_populates="alerts")

class User(Base):
    __tablename__ = "users"

    id = Column(String(64), primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(128), nullable=False)
    role = Column(String(64), nullable=False)  # SUPER_ADMIN, POLICE_OFFICER, RTO_OFFICER, FCS_OFFICER
    department = Column(String(64), nullable=False)
    badge_number = Column(String(64), nullable=True)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
