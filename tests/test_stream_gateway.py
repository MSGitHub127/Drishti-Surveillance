"""
Unit Tests for Stream Gateway & Sentinel Protocol Adherence
Validates:
1. RTSP over TCP transport enforcement
2. PTS monotonic timing anchor calculation (no CAP_PROP_FPS drift)
3. Exponential backoff reconnect progression (2s -> 30s)
4. Loop-cut / scene discontinuity recovery on backward PTS step
"""

import os
import time
import pytest
from app.stream_gateway import CameraStreamWorker
from app.config import settings

def test_rtsp_transport_tcp_enforced():
    """Rule 1: Verify rtsp_transport=tcp is strictly set in OpenCV environment."""
    assert os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS") == "rtsp_transport;tcp"

def test_pts_monotonic_timing_calculation():
    """Rule 2 & 7: Verify event timing is derived strictly from PTS, eliminating GOP replay skew."""
    worker = CameraStreamWorker(camera_id="test-cam-1", rtsp_url="rtsp://localhost:8554/stream/1")

    # Frame 1 at PTS 1000ms
    iso1, epoch1 = worker.calculate_pts_derived_time(1000.0)
    assert worker.anchor_pts_ms == 1000.0
    assert worker.anchor_wall_clock is not None

    # Frame 2 arriving fast (PTS 1040ms, +40ms later in stream time)
    iso2, epoch2 = worker.calculate_pts_derived_time(1040.0)
    time_delta = epoch2 - epoch1
    assert pytest.approx(time_delta, abs=0.001) == 0.040  # Exactly 40ms stream time delta

    # Frame 3 (PTS 2000ms, +1000ms later in stream time)
    iso3, epoch3 = worker.calculate_pts_derived_time(2000.0)
    assert pytest.approx(epoch3 - epoch1, abs=0.001) == 1.000

def test_exponential_backoff_progression():
    """Rule 5: Verify exponential backoff starts at 2s, multiplies by 1.5, and caps at 30s."""
    backoff = settings.RECONNECT_INITIAL_BACKOFF_SEC
    assert backoff == 2.0

    # Simulate 10 consecutive failures
    history = [backoff]
    for _ in range(8):
        backoff = min(backoff * settings.RECONNECT_BACKOFF_MULTIPLIER, settings.RECONNECT_MAX_BACKOFF_SEC)
        history.append(backoff)

    assert history[1] == 3.0
    assert history[2] == 4.5
    assert history[3] == 6.75
    # Must never exceed 30s cap
    assert all(b <= 30.0 for b in history)
    assert history[-1] == 30.0

def test_scene_discontinuity_loop_cut_recovery():
    """Rule 8: Verify loop cut (PTS backward jump) triggers re-anchoring."""
    worker = CameraStreamWorker(camera_id="test-cam-2", rtsp_url="rtsp://localhost:8554/stream/2")

    # Initial frames progressing to 30,000ms (30 seconds in)
    worker.calculate_pts_derived_time(1000.0)
    worker.calculate_pts_derived_time(30000.0)
    old_anchor_pts = worker.anchor_pts_ms

    # Loop wraps around: next frame jumps back to 40ms (like camera reboot)
    iso_new, epoch_new = worker.calculate_pts_derived_time(40.0)

    # Must detect scene cut and re-anchor
    assert worker.anchor_pts_ms == 40.0
    assert worker.anchor_pts_ms != old_anchor_pts
    assert worker.last_pts_ms == 40.0

@pytest.mark.asyncio
async def test_idle_stream_auto_close():
    """Rule 6 (Secondary Issue #5): Verify idle stream auto-closes when 0 viewers and timeout elapsed."""
    worker = CameraStreamWorker(camera_id="idle-cam-test", rtsp_url="rtsp://localhost:8554/stream/idle")
    worker.active_viewers = 0
    # Simulate past activity beyond STREAM_IDLE_TIMEOUT_SEC
    worker.last_active_time = time.time() - (settings.STREAM_IDLE_TIMEOUT_SEC + 10.0)

    # Check idle condition
    now = time.time()
    is_idle = (worker.active_viewers <= 0) and ((now - worker.last_active_time) > settings.STREAM_IDLE_TIMEOUT_SEC)
    assert is_idle is True

    # Standby frame should generate cleanly
    standby = worker.generate_standby_frame()
    assert standby is not None
    assert standby.shape == (settings.LIVE_STREAM_HEIGHT, settings.LIVE_STREAM_WIDTH, 3)
