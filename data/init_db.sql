-- PostgreSQL 16 + PostGIS 3.4 Schema for Unified State CCTV Integration Platform
-- Team Vayunotics - GPH26

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";

-- -------------------------------------------------------------
-- 1. Departments Table
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS departments (
    id VARCHAR(64) PRIMARY KEY,
    code VARCHAR(32) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    category VARCHAR(64) NOT NULL, -- Law Enforcement, Transport, Civil Supplies, Urban Local Bodies, Private Entity
    nodal_officer VARCHAR(128),
    contact_email VARCHAR(128),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- -------------------------------------------------------------
-- 2. Cameras Table (Model 1 Registry & GIS Foundation)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cameras (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    dept_id VARCHAR(64) REFERENCES departments(id) ON DELETE SET NULL,
    camera_type VARCHAR(64) DEFAULT 'ANPR', -- ANPR, Bullet, PTZ, Dome, Thermal
    lat DOUBLE PRECISION NOT NULL,
    lng DOUBLE PRECISION NOT NULL,
    geom GEOMETRY(Point, 4326),
    location_name VARCHAR(255) NOT NULL,
    district VARCHAR(128) NOT NULL,
    city VARCHAR(128) NOT NULL,
    landmark VARCHAR(255),
    status VARCHAR(32) DEFAULT 'online', -- online, offline, maintenance
    stream_rtsp VARCHAR(512),
    stream_whep VARCHAR(512),
    stream_hls VARCHAR(512),
    codec VARCHAR(32) DEFAULT 'H.264', -- H.264, H.265
    resolution VARCHAR(32) DEFAULT '1920x1080',
    fps DOUBLE PRECISION DEFAULT 25.0,
    storage_type VARCHAR(32) DEFAULT 'cloud', -- cloud, local, hybrid
    retention_days INT DEFAULT 15, -- 7 to 15+ days
    vms_vendor VARCHAR(64) DEFAULT 'Standard ONVIF',
    amc_status VARCHAR(64) DEFAULT 'Active',
    last_seen TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cameras_geom ON cameras USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_cameras_dept ON cameras (dept_id);
CREATE INDEX IF NOT EXISTS idx_cameras_status ON cameras (status);
CREATE INDEX IF NOT EXISTS idx_cameras_district ON cameras (district);

-- -------------------------------------------------------------
-- 3. Watchlist Table (VAHAN, SARTHI, eGujCop, AFIS, NAFIS)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS watchlist (
    id VARCHAR(64) PRIMARY KEY,
    plate_number VARCHAR(32) NOT NULL,
    normalized_plate VARCHAR(32) NOT NULL,
    person_name VARCHAR(128),
    category VARCHAR(64) NOT NULL, -- Stolen Vehicle, Wanted Criminal, Missing Person, Blacklisted Vehicle, Suspect
    source_dept VARCHAR(64) NOT NULL, -- eGujCop, VAHAN, SARTHI, AFIS, NAFIS, State Crime Records
    fir_number VARCHAR(128),
    police_station VARCHAR(128),
    vehicle_make_model VARCHAR(128),
    vehicle_color VARCHAR(64),
    severity VARCHAR(32) DEFAULT 'CRITICAL', -- CRITICAL, HIGH, MEDIUM, LOW
    notes TEXT,
    active BOOLEAN DEFAULT TRUE,
    date_added TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_watchlist_plate ON watchlist (plate_number);
CREATE INDEX IF NOT EXISTS idx_watchlist_norm_plate ON watchlist (normalized_plate);
CREATE INDEX IF NOT EXISTS idx_watchlist_category ON watchlist (category);
CREATE INDEX IF NOT EXISTS idx_watchlist_source ON watchlist (source_dept);

-- -------------------------------------------------------------
-- 4. Detections Table (Spatial & Temporal Detections)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS detections (
    id VARCHAR(64) PRIMARY KEY,
    camera_id VARCHAR(64) REFERENCES cameras(id) ON DELETE CASCADE,
    plate_number VARCHAR(32) NOT NULL,
    normalized_plate VARCHAR(32) NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    vehicle_type VARCHAR(64) DEFAULT 'Car', -- Car, SUV, Truck, Bus, Motorcycle, Auto-Rickshaw
    vehicle_color VARCHAR(64),
    pts_timestamp TIMESTAMPTZ NOT NULL,
    wall_clock_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    geom GEOMETRY(Point, 4326),
    snapshot_url TEXT,
    crop_url TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_detections_geom ON detections USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_detections_plate ON detections (normalized_plate);
CREATE INDEX IF NOT EXISTS idx_detections_pts ON detections (pts_timestamp);
CREATE INDEX IF NOT EXISTS idx_detections_cam_pts ON detections (camera_id, pts_timestamp);

-- -------------------------------------------------------------
-- 5. Alerts Table (Real-Time Watchlist Matches & Cooldown)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id VARCHAR(64) PRIMARY KEY,
    alert_code VARCHAR(32) UNIQUE NOT NULL,
    plate_number VARCHAR(32) NOT NULL,
    watchlist_id VARCHAR(64) REFERENCES watchlist(id) ON DELETE SET NULL,
    detection_id VARCHAR(64) REFERENCES detections(id) ON DELETE SET NULL,
    camera_id VARCHAR(64) REFERENCES cameras(id) ON DELETE SET NULL,
    location_name VARCHAR(255) NOT NULL,
    district VARCHAR(128) NOT NULL,
    department VARCHAR(64) NOT NULL,
    severity VARCHAR(32) NOT NULL,
    category VARCHAR(64) NOT NULL,
    event_timestamp TIMESTAMPTZ NOT NULL,
    snapshot_url TEXT,
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_by VARCHAR(128),
    acknowledged_at TIMESTAMPTZ,
    escalation_status VARCHAR(64) DEFAULT 'NEW', -- NEW, DISPATCHED, INTERCEPTED, FALSE_POSITIVE
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_alerts_plate ON alerts (plate_number);
CREATE INDEX IF NOT EXISTS idx_alerts_timestamp ON alerts (event_timestamp);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts (severity);
CREATE INDEX IF NOT EXISTS idx_alerts_ack ON alerts (acknowledged);

-- -------------------------------------------------------------
-- 6. Users & RBAC
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(128) NOT NULL,
    role VARCHAR(64) NOT NULL, -- SUPER_ADMIN, POLICE_OFFICER, RTO_OFFICER, FCS_OFFICER
    department VARCHAR(64) NOT NULL,
    badge_number VARCHAR(64),
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Trigger function to automatically maintain geom from lat/lng
CREATE OR REPLACE FUNCTION update_camera_geom()
RETURNS TRIGGER AS $$
BEGIN
    NEW.geom = ST_SetSRID(ST_MakePoint(NEW.lng, NEW.lat), 4326);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_camera_geom ON cameras;
CREATE TRIGGER trg_camera_geom
BEFORE INSERT OR UPDATE OF lat, lng ON cameras
FOR EACH ROW EXECUTE FUNCTION update_camera_geom();

CREATE OR REPLACE FUNCTION update_detection_geom()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.lng IS NOT NULL AND NEW.lat IS NOT NULL THEN
        NEW.geom = ST_SetSRID(ST_MakePoint(NEW.lng, NEW.lat), 4326);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_detection_geom ON detections;
CREATE TRIGGER trg_detection_geom
BEFORE INSERT OR UPDATE OF lat, lng ON detections
FOR EACH ROW EXECUTE FUNCTION update_detection_geom();
