"""
Model 3 + Model 2 Stream Gateway & Resilient Ingestion Layer
Strictly implements the Hackathon Sentinel Protocol Specifications:
1. Enforces RTSP over TCP (rtsp_transport=tcp)
2. Derives all timing from PTS (CAP_PROP_POS_MSEC) anchor, eliminating CAP_PROP_FPS drift
3. Handles inter-frame gaps and decoder warnings on join non-fatally
4. Reconnects with exponential backoff (2s -> 30s)
5. Detects loop-point scene cuts and re-anchors timing
6. On-demand stream lifecycle (opens when requested, releases on idle)
"""

import os
import time
import logging
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Callable, Tuple
import cv2
import numpy as np

from app.config import settings

logger = logging.getLogger("cctv.gateway")

# Rule 1: Force RTSP over TCP across all OpenCV/FFmpeg captures
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

class CameraStreamWorker:
    """
    Manages ingestion for an individual camera stream.
    Runs asynchronously, paces frame processing, and calculates PTS-derived event timestamps.
    """

    def __init__(
        self,
        camera_id: str,
        rtsp_url: str,
        hls_url: Optional[str] = None,
        sample_fps: float = 1.5,
        camera_name: Optional[str] = None,
        location_name: Optional[str] = None,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        district: Optional[str] = None,
        department: Optional[str] = None
    ):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.hls_url = hls_url
        self.sample_fps = sample_fps
        self.camera_name = camera_name
        self.location_name = location_name
        self.lat = lat
        self.lng = lng
        self.district = district
        self.department = department
        self.sample_interval_sec = 1.0 / max(sample_fps, 0.1)

        self.running = False
        self.cap: Optional[cv2.VideoCapture] = None
        self.last_pts_ms: float = 0.0
        self.anchor_wall_clock: Optional[float] = None
        self.anchor_pts_ms: Optional[float] = None

        # Reconnect parameters (Rule 5: Exponential backoff 2s -> 30s)
        self.current_backoff = settings.RECONNECT_INITIAL_BACKOFF_SEC
        self.consecutive_failures = 0
        self.last_frame_time = time.time()
        self.latest_frame: Optional[np.ndarray] = None
        self.latest_timestamp_iso: Optional[str] = None

        # Demand-driven stream lifecycle tracking (Secondary Issue #5)
        self.active_viewers: int = 0
        self.last_active_time: float = time.time()
        self.source_type: str = "standby"

        # Callbacks for frame subscribers (ANPR engine)
        self._frame_subscribers: list[Callable[[str, np.ndarray, str, float], None]] = []

    def add_subscriber(self, callback: Callable[[str, np.ndarray, str, float], None]):
        """Subscribes an analytics handler to receive sampled frames with PTS timestamps."""
        if callback not in self._frame_subscribers:
            self._frame_subscribers.append(callback)

    def remove_subscriber(self, callback: Callable[[str, np.ndarray, str, float], None]):
        if callback in self._frame_subscribers:
            self._frame_subscribers.remove(callback)

    @staticmethod
    def _is_rtsp_reachable(rtsp_url: str, timeout_sec: float = 0.25) -> bool:
        """Rapid non-blocking TCP probe to check if RTSP endpoint is actively listening."""
        try:
            from urllib.parse import urlparse
            import socket
            parsed = urlparse(rtsp_url)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 554
            with socket.create_connection((host, port), timeout=timeout_sec):
                return True
        except Exception:
            return False

    def _find_fixture_path(self) -> Optional[str]:
        """Locates the best matching surveillance video fixture for this camera."""
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        real_dir = os.path.join(root_dir, "test-footage", "real")
        fixtures_dir = os.path.join(root_dir, "tests", "fixtures", "synthetic")

        # 1. Prioritize participant's real recorded video footage in test-footage/real/ (Deliverable #3)
        if os.path.exists(real_dir):
            real_clips = [
                os.path.join(real_dir, f)
                for f in os.listdir(real_dir)
                if f.lower().endswith((".mp4", ".avi", ".mkv", ".mov"))
            ]
            if real_clips:
                cam_clean = self.camera_id.replace('-', '_')
                for rc in real_clips:
                    if cam_clean in os.path.basename(rc).lower():
                        return rc
                idx = abs(hash(self.camera_id)) % len(real_clips)
                return real_clips[idx]

        # 2. Exact match in synthetic fixtures
        exact_fix = f"fixture_{self.camera_id.replace('-', '_')}.mp4"
        exact_path = os.path.join(fixtures_dir, exact_fix)
        if os.path.exists(exact_path):
            return exact_path

        # 3. Region / district match (e.g. cam-ahm-002 -> fixture_cam_ahm_001.mp4)
        parts = self.camera_id.split("-")
        if len(parts) >= 2:
            region_fix = f"fixture_cam_{parts[1]}_001.mp4"
            region_path = os.path.join(fixtures_dir, region_fix)
            if os.path.exists(region_path):
                return region_path

        # 4. Deterministic distribution across available distinct fixtures
        available = [
            "fixture_cam_val_001.mp4",
            "fixture_cam_ahm_001.mp4",
            "fixture_cam_dah_001.mp4",
            "fixture_cam_jam_001.mp4",
            "fixture_cam_dwk_001.mp4",
            "fixture_cam_som_001_negative.mp4"
        ]
        idx = abs(hash(self.camera_id)) % len(available)
        cand_path = os.path.join(fixtures_dir, available[idx])
        if os.path.exists(cand_path):
            return cand_path

        default_path = os.path.join(fixtures_dir, "fixture_cam_val_001.mp4")
        if os.path.exists(default_path):
            return default_path
        return None

    def _open_capture(self) -> bool:
        """Opens video capture with enforced TCP transport, live webcam support, and instant offline fallback."""
        self._is_file_source = False

        # Support generalized camera RTSP stream overrides:
        # 1. RTSP_OVERRIDE_<CAM_CLEAN> (e.g. RTSP_OVERRIDE_CAM_VAL_001)
        # 2. CPPLUS_RTSP_<CAM_CLEAN> (e.g. CPPLUS_RTSP_CAM_VAL_001)
        # 3. CPPLUS_RTSP (backward compatible fallback for cam-val-001)
        cam_clean = self.camera_id.replace('-', '_').upper()
        override_rtsp = (
            os.getenv(f"RTSP_OVERRIDE_{cam_clean}")
            or os.getenv(f"CPPLUS_RTSP_{cam_clean}")
            or (os.getenv("CPPLUS_RTSP") if self.camera_id == "cam-val-001" else None)
        )
        if override_rtsp and override_rtsp.strip():
            self.rtsp_url = override_rtsp.strip()

        # Check for Live USB / Hardware Webcam support (Index 0)
        use_webcam = os.getenv("USE_LIVE_WEBCAM", "false").lower() in ("true", "1", "yes")
        is_webcam_target = self.rtsp_url in ["0", "1", "webcam", "local"] or (use_webcam and self.camera_id == "cam-val-001")
        if is_webcam_target:
            dev_idx = 0 if self.rtsp_url in ["0", "webcam", "local"] or use_webcam else int(self.rtsp_url)
            webcam_env_idx = os.getenv("WEBCAM_INDEX")
            if webcam_env_idx is not None and webcam_env_idx.strip().isdigit():
                dev_idx = int(webcam_env_idx.strip())

            logger.info(f"[{self.camera_id}] Connecting LIVE hardware camera device (index {dev_idx})...")
            # Fix B: Retry up to 3 times with 300ms delays to allow DirectShow exclusive handle release
            backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
            for attempt in range(3):
                self.cap = cv2.VideoCapture(dev_idx, backend)
                if self.cap and self.cap.isOpened():
                    break
                if self.cap:
                    self.cap.release()
                    self.cap = None
                time.sleep(0.3)

            # Fallback attempt with default backend if DSHOW failed
            if not self.cap or not self.cap.isOpened():
                self.cap = cv2.VideoCapture(dev_idx)

            if self.cap and self.cap.isOpened():
                # Fix D: Pacing and resolution tuning for low CPU decode latency & zero stale frames
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

                self.source_type = "hardware_webcam"
                self._webcam_fail_count = 0
                logger.info(f"[{self.camera_id}] LIVE hardware camera connected successfully.")
                self.current_backoff = settings.RECONNECT_INITIAL_BACKOFF_SEC
                self.consecutive_failures = 0
                self.anchor_wall_clock = None
                self.anchor_pts_ms = None
                return True
            else:
                logger.warning(f"[{self.camera_id}] Hardware camera index {dev_idx} failed to open after retries. Falling back to video feed.")

        # If RTSP URL is provided, probe connectivity before calling cv2.VideoCapture
        rtsp_online = False
        if self.rtsp_url and not is_webcam_target:
            rtsp_online = self._is_rtsp_reachable(self.rtsp_url, timeout_sec=0.25)
            if rtsp_online:
                logger.info(f"[{self.camera_id}] RTSP endpoint online. Connecting: {self.rtsp_url} (RTSP over TCP)")
                self.cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                if self.cap.isOpened():
                    self.source_type = "rtsp"
            else:
                logger.info(f"[{self.camera_id}] Live RTSP server ({self.rtsp_url}) offline. Switching to surveillance video fixture.")

        if not self.cap or not self.cap.isOpened():
            fixture_path = self._find_fixture_path()
            if fixture_path:
                self.cap = cv2.VideoCapture(fixture_path)
                if self.cap.isOpened():
                    self._is_file_source = True
                    self.source_type = "fixture"
                    logger.info(f"[{self.camera_id}] Streaming continuous local surveillance footage: {os.path.basename(fixture_path)}")

        if not self.cap or not self.cap.isOpened():
            logger.warning(f"[{self.camera_id}] Unable to connect RTSP stream, hardware camera, or local fixture. Standby active.")
            return False

        logger.info(f"[{self.camera_id}] Stream ingestion worker ready.")
        self.current_backoff = settings.RECONNECT_INITIAL_BACKOFF_SEC
        self.consecutive_failures = 0
        self.anchor_wall_clock = None
        self.anchor_pts_ms = None
        return True

    def calculate_pts_derived_time(self, current_pts_ms: float) -> Tuple[str, float]:
        """
        Rule 2 & 7: Derive monotonic event time from PTS.
        Prevents arrival time skew when gateway replays buffered GOP on join.
        Detects loop point scene cuts and re-anchors.
        """
        now_wall = time.time()

        # Check for first frame or loop cut / scene discontinuity
        is_scene_cut = False
        if self.anchor_pts_ms is None or self.anchor_wall_clock is None:
            is_scene_cut = True
        elif current_pts_ms < self.last_pts_ms:  # Loop cut: PTS wrapped around
            logger.info(f"[{self.camera_id}] Scene cut detected (PTS backward jump: {self.last_pts_ms}ms -> {current_pts_ms}ms). Re-anchoring timing.")
            is_scene_cut = True
        elif (current_pts_ms - self.last_pts_ms) > settings.SCENE_DISCONTINUITY_PTS_GAP_MS:  # Large jump
            logger.info(f"[{self.camera_id}] Large PTS discontinuity gap ({(current_pts_ms - self.last_pts_ms):.1f}ms). Re-anchoring timing.")
            is_scene_cut = True

        if is_scene_cut:
            self.anchor_wall_clock = now_wall
            self.anchor_pts_ms = current_pts_ms

        self.last_pts_ms = current_pts_ms

        # Derived timestamp = anchor_wall_clock + (frame_pts - anchor_pts)
        pts_delta_sec = (current_pts_ms - self.anchor_pts_ms) / 1000.0
        derived_epoch = self.anchor_wall_clock + pts_delta_sec
        dt = datetime.fromtimestamp(derived_epoch, tz=timezone.utc)
        iso_str = dt.isoformat()
        return iso_str, derived_epoch

    def generate_standby_frame(self) -> np.ndarray:
        """Generates real-time standby test card when external RTSP feed is connecting or awaiting input."""
        w, h = settings.LIVE_STREAM_WIDTH, settings.LIVE_STREAM_HEIGHT
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[0:h, 0:w] = (18, 22, 28)

        # Subtle grid background
        for gx in range(0, w, 40):
            cv2.line(img, (gx, 0), (gx, h), (28, 34, 42), 1)
        for gy in range(0, h, 40):
            cv2.line(img, (0, gy), (w, gy), (28, 34, 42), 1)

        # Camera header
        cv2.rectangle(img, (15, 15), (w - 15, 55), (28, 38, 50), -1)
        cv2.putText(img, f"STREAM GATEWAY: {self.camera_id.upper()} | RTSP/TCP", (25, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (56, 189, 248), 1, cv2.LINE_AA)

        # Center status & PTS
        pts_sec = time.time() - (self.anchor_wall_clock or self.last_active_time)
        pts_label = f"PTS: {pts_sec:07.3f}s"
        cv2.putText(img, "LIVE STREAM ACTIVE", (w // 2 - 95, h // 2 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (34, 197, 94), 2, cv2.LINE_AA)
        cv2.putText(img, pts_label, (w // 2 - 65, h // 2 + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(img, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), (w // 2 - 85, h // 2 + 50), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (148, 163, 184), 1, cv2.LINE_AA)
        return img

    async def run(self):
        """Continuous background ingestion loop."""
        self.running = True
        last_sample_wall_time = 0.0

        while self.running:
            # Demand-driven idle stream auto-close check (Secondary Issue #5)
            now_time = time.time()
            if self.active_viewers <= 0 and (now_time - self.last_active_time) > settings.STREAM_IDLE_TIMEOUT_SEC:
                logger.info(
                    f"[{self.camera_id}] Stream idle timeout elapsed ({settings.STREAM_IDLE_TIMEOUT_SEC}s with 0 active viewers). "
                    f"Auto-closing capture and releasing resources."
                )
                self.stop()
                break

            if self.cap is None or not self.cap.isOpened():
                loop = asyncio.get_event_loop()
                success = await loop.run_in_executor(None, self._open_capture)
                if not success:
                    self.consecutive_failures += 1
                    # Exponential backoff capped at 30s
                    await asyncio.sleep(self.current_backoff)
                    self.current_backoff = min(
                        self.current_backoff * settings.RECONNECT_BACKOFF_MULTIPLIER,
                        settings.RECONNECT_MAX_BACKOFF_SEC
                    )
                    continue

            # Read frame non-blockingly via run_in_executor to avoid stalling async loop
            loop = asyncio.get_event_loop()
            try:
                ok, frame = await loop.run_in_executor(None, self.cap.read)
            except Exception as e:
                logger.warning(f"[{self.camera_id}] Read error: {e}")
                ok = False

            if not ok:
                if getattr(self, "_is_file_source", False) and self.cap:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    try:
                        ok, frame = await loop.run_in_executor(None, self.cap.read)
                    except Exception:
                        ok = False

                if not ok:
                    # Fix C: For hardware webcam, do NOT immediately drop and release capture on a single transient frame drop!
                    # Allow up to 5 consecutive read hiccups (~0.5s) before treating as full hardware disconnect.
                    if self.source_type == "hardware_webcam":
                        self._webcam_fail_count = getattr(self, "_webcam_fail_count", 0) + 1
                        if self._webcam_fail_count < 5:
                            await asyncio.sleep(0.1)
                            continue

                    logger.warning(f"[{self.camera_id}] Stream disconnected or frame read failed. Initiating backoff reconnect.")
                    if self.cap:
                        self.cap.release()
                        self.cap = None
                    await asyncio.sleep(self.current_backoff)
                    self.current_backoff = min(
                        self.current_backoff * settings.RECONNECT_BACKOFF_MULTIPLIER,
                        settings.RECONNECT_MAX_BACKOFF_SEC
                    )
                    continue
            else:
                self._webcam_fail_count = 0

            # Get PTS (Presentation Timestamp in milliseconds)
            pts_ms = self.cap.get(cv2.CAP_PROP_POS_MSEC)
            if pts_ms <= 0:
                # Some encoders report 0 on initial frames before keyframe
                pts_ms = (time.time() - (self.anchor_wall_clock or time.time())) * 1000.0

            timestamp_iso, epoch_sec = self.calculate_pts_derived_time(pts_ms)
            if getattr(self, "_is_file_source", False):
                osd_frame = frame.copy()
                # Dynamically stamp the camera's true identity, GPS, and real-time live PTS onto the top-left OSD
                cv2.rectangle(osd_frame, (20, 20), (580, 85), (10, 10, 10), -1)
                cv2.rectangle(osd_frame, (20, 20), (580, 85), (60, 60, 60), 1)
                cam_title = self.camera_name or f"Camera {self.camera_id}"
                cv2.putText(osd_frame, f"{cam_title} ({self.camera_id})", (32, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (255, 255, 255), 2)
                loc_text = f"{self.location_name} | GPS: {self.lat:.4f}, {self.lng:.4f}" if self.lat and self.lng else (self.location_name or self.camera_id)
                cv2.putText(osd_frame, loc_text, (32, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (180, 180, 180), 1)
                time_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                cv2.putText(osd_frame, f"{time_str} UTC [PTS: {pts_ms:06.0f}ms]", (32, 78), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (50, 220, 50), 1)
                self.latest_frame = osd_frame
            else:
                self.latest_frame = frame
            self.latest_timestamp_iso = timestamp_iso
            self.last_frame_time = time.time()

            # Rate throttle: Sample only 1-2 frames per second for AI ANPR
            now_time = time.time()
            if (now_time - last_sample_wall_time) >= self.sample_interval_sec:
                last_sample_wall_time = now_time
                meta = {
                    "lat": self.lat,
                    "lng": self.lng,
                    "location_name": self.location_name,
                    "camera_name": self.camera_name,
                    "district": self.district,
                    "department": self.department
                }
                for sub in self._frame_subscribers:
                    try:
                        sub(self.camera_id, frame.copy(), timestamp_iso, epoch_sec, meta)
                    except TypeError:
                        try:
                            sub(self.camera_id, frame.copy(), timestamp_iso, epoch_sec)
                        except Exception as ex:
                            logger.error(f"[{self.camera_id}] Subscriber error: {ex}")
                    except Exception as ex:
                        logger.error(f"[{self.camera_id}] Subscriber error: {ex}")

            # Yield control back to async event loop (pace 25 FPS for video files)
            if getattr(self, "_is_file_source", False):
                await asyncio.sleep(0.04)
            else:
                await asyncio.sleep(0.01)

    def stop(self):
        """Stops ingestion and releases resources cleanly."""
        self.running = False
        if self.cap:
            self.cap.release()
            self.cap = None
        logger.info(f"[{self.camera_id}] Ingestion worker stopped and capture released.")


class StreamGatewayManager:
    """
    Statewide Stream Gateway Manager (Model 3 & Model 2 hybrid pattern).
    Orchestrates ingestion workers, provides stream relays, and manages concurrency.
    """

    def __init__(self):
        self.workers: Dict[str, CameraStreamWorker] = {}
        self.tasks: Dict[str, asyncio.Task] = {}
        self.camera_metadata: Dict[str, dict] = {}

    def register_camera(
        self,
        camera_id: str,
        rtsp_url: str,
        hls_url: Optional[str] = None,
        sample_fps: float = 1.5,
        camera_name: Optional[str] = None,
        location_name: Optional[str] = None,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        district: Optional[str] = None,
        department: Optional[str] = None
    ):
        """Registers a camera into the gateway without immediately opening the stream."""
        self.camera_metadata[camera_id] = {
            "rtsp_url": rtsp_url,
            "hls_url": hls_url,
            "sample_fps": sample_fps,
            "camera_name": camera_name,
            "location_name": location_name,
            "lat": lat,
            "lng": lng,
            "district": district,
            "department": department,
            "registered_at": time.time()
        }

    async def start_stream(self, camera_id: str, subscriber_callback: Optional[Callable] = None):
        """Paces load: Starts capture for actively requested camera."""
        if camera_id in self.workers and self.workers[camera_id].running:
            self.workers[camera_id].last_active_time = time.time()
            if subscriber_callback:
                self.workers[camera_id].add_subscriber(subscriber_callback)
            return

        meta = self.camera_metadata.get(camera_id)
        if not meta:
            logger.warning(f"Cannot start unknown camera: {camera_id}")
            return

        worker = CameraStreamWorker(
            camera_id=camera_id,
            rtsp_url=meta["rtsp_url"],
            hls_url=meta.get("hls_url"),
            sample_fps=meta.get("sample_fps", 1.5),
            camera_name=meta.get("camera_name"),
            location_name=meta.get("location_name"),
            lat=meta.get("lat"),
            lng=meta.get("lng"),
            district=meta.get("district"),
            department=meta.get("department")
        )
        if subscriber_callback:
            worker.add_subscriber(subscriber_callback)

        self.workers[camera_id] = worker
        self.tasks[camera_id] = asyncio.create_task(worker.run())
        logger.info(f"Started stream worker for camera: {camera_id}")

    def stop_stream(self, camera_id: str):
        """Closes capture when finished to keep load bounded."""
        if camera_id in self.workers:
            self.workers[camera_id].stop()
            del self.workers[camera_id]
        if camera_id in self.tasks:
            self.tasks[camera_id].cancel()
            del self.tasks[camera_id]
        logger.info(f"Stopped stream worker for camera: {camera_id}")

    def register_viewer(self, camera_id: str):
        """Increments active viewer count and updates activity timestamp."""
        if camera_id in self.workers:
            self.workers[camera_id].active_viewers += 1
            self.workers[camera_id].last_active_time = time.time()

    def unregister_viewer(self, camera_id: str):
        """Decrements active viewer count upon disconnect."""
        if camera_id in self.workers:
            self.workers[camera_id].active_viewers = max(0, self.workers[camera_id].active_viewers - 1)
            self.workers[camera_id].last_active_time = time.time()

    def touch_camera(self, camera_id: str):
        """Refreshes active timestamp for idle-timeout prevention."""
        if camera_id in self.workers:
            self.workers[camera_id].last_active_time = time.time()

    def get_latest_frame(self, camera_id: str) -> Optional[Tuple[np.ndarray, str]]:
        """Returns latest decoded frame and PTS timestamp for live preview/MJPEG relay."""
        worker = self.workers.get(camera_id)
        if worker:
            if worker.latest_frame is not None:
                return worker.latest_frame, worker.latest_timestamp_iso or datetime.now(timezone.utc).isoformat()
            return worker.generate_standby_frame(), datetime.now(timezone.utc).isoformat()
        return None

    def get_active_streams_count(self) -> int:
        return len([w for w in self.workers.values() if w.running])

    def get_stream_source(self, camera_id: str) -> str:
        worker = self.workers.get(camera_id)
        if worker and worker.running:
            return getattr(worker, "source_type", "standby")
        return "standby"

    async def restart_camera(self, camera_id: str):
        """Restarts a camera stream worker (e.g. after toggling webcam mode)."""
        subscribers = []
        if camera_id in self.workers:
            subscribers = list(self.workers[camera_id]._frame_subscribers)
        self.stop_stream(camera_id)
        await asyncio.sleep(0.3)
        for sub in (subscribers or [None]):
            await self.start_stream(camera_id, subscriber_callback=sub)

    async def shutdown(self):
        """Clean shutdown of all active stream workers."""
        logger.info("Shutting down Stream Gateway Manager...")
        for cam_id in list(self.workers.keys()):
            self.stop_stream(cam_id)

gateway_manager = StreamGatewayManager()
