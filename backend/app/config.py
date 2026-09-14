"""
Configuration Module for Team Vayunotics CCTV Integration Platform
Manages environment variables, stream settings, database connections, and tuning parameters.
"""

import os
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Project Info
    PROJECT_NAME: str = "Dhristi Surveillance - CCTV AI Platform"
    PROJECT_VERSION: str = "2.0.0"
    TEAM_NAME: str = "Team Vayunotics (GPH26)"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    # PostgreSQL + PostGIS Configuration
    # Defaults to local PostGIS container or standard PostgreSQL
    DB_USER: str = os.getenv("DB_USER", "cctv_admin")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "cctv_secure_pass_2026")
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: str = os.getenv("DB_PORT", "5432")
    DB_NAME: str = os.getenv("DB_NAME", "cctv_unified_db")

    @property
    def DATABASE_URL(self) -> str:
        env_url = os.getenv("DATABASE_URL")
        if env_url:
            return env_url
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def DB_SYNC_URL(self) -> str:
        env_url = os.getenv("DB_SYNC_URL")
        if env_url:
            return env_url
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    # Redis Event Bus Configuration
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Stream Gateway Settings (Strict Sentinel Protocol Adherence)
    RTSP_TRANSPORT: str = "tcp"  # Strictly enforce RTSP over TCP
    RECONNECT_INITIAL_BACKOFF_SEC: float = 2.0
    RECONNECT_MAX_BACKOFF_SEC: float = 30.0
    RECONNECT_BACKOFF_MULTIPLIER: float = 1.5
    STREAM_IDLE_TIMEOUT_SEC: float = 120.0  # Auto-close idle capture after 2 min
    SCENE_DISCONTINUITY_PTS_GAP_MS: float = 3000.0  # PTS backward jump or >3s gap triggers loop cut recovery

    # Media Relay (MediaMTX / go2rtc)
    MEDIAMTX_HOST: str = os.getenv("MEDIAMTX_HOST", "localhost")
    MEDIAMTX_RTSP_PORT: int = 8554
    MEDIAMTX_HLS_PORT: int = 8888
    MEDIAMTX_WHEP_PORT: int = 8889

    # AI Analytics & ANPR Settings
    ANPR_CONFIDENCE_THRESHOLD: float = 0.70
    ANPR_PLATE_CONFIDENCE_THRESHOLD: float = float(os.getenv("ANPR_PLATE_CONFIDENCE_THRESHOLD", "0.15"))
    ANPR_SAMPLE_FPS: float = 1.5  # Sample ~1-2 frames per sec per camera to control 50-stream load
    ANPR_WORKER_CONCURRENCY: int = int(os.getenv("ANPR_WORKER_CONCURRENCY", "8"))
    ANPR_QUEUE_MAXSIZE: int = 500

    # Alert Settings
    ALERT_DEBOUNCE_COOLDOWN_SEC: float = 60.0  # Cooldown per plate+camera to prevent duplicate flood
    FUZZY_MATCH_MAX_DISTANCE: int = 1  # Levenshtein distance tolerance for OCR errors

    # Security, Evaluation Mode & RBAC
    EVAL_MODE: bool = os.getenv("EVAL_MODE", "true").lower() in ("true", "1", "yes")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "vayunotics-cctv-secret-key-gujarat-2026")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Model Weights Paths & Provenance
    # License plate detector fine-tuned YOLOv8 (Roboflow keremberke benchmark / QoDe-5G)
    LICENSE_PLATE_MODEL_PATH: str = os.getenv("LICENSE_PLATE_MODEL_PATH", "license_plate_detector.pt")
    VEHICLE_MODEL_PATH: str = os.getenv("VEHICLE_MODEL_PATH", "yolov8n.pt")

    # On-Demand Live MJPEG Stream Optimization (Quality & Size Control)
    LIVE_STREAM_WIDTH: int = int(os.getenv("LIVE_STREAM_WIDTH", "640"))
    LIVE_STREAM_HEIGHT: int = int(os.getenv("LIVE_STREAM_HEIGHT", "360"))
    LIVE_STREAM_JPEG_QUALITY: int = int(os.getenv("LIVE_STREAM_JPEG_QUALITY", "65"))

    class Config:
        case_sensitive = True

settings = Settings()

# Security warning if production environment runs on default secret key
if not settings.EVAL_MODE and settings.SECRET_KEY == "vayunotics-cctv-secret-key-gujarat-2026":
    import warnings
    warnings.warn(
        "SECURITY NOTICE: Default SECRET_KEY is active in non-EVAL_MODE! "
        "Set SECRET_KEY environment variable before deploying to production.",
        UserWarning
    )
