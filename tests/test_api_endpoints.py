"""
FastAPI REST & Diagnostic Integration Tests
Validates:
1. GET /health (Uptime, database status, stream gateway, ANPR pool)
2. GET /api/registry/cameras (50 cameras loaded)
3. GET /api/watchlist (Seed records loaded)
4. GET /api/trace?plate=GJ01AB1234 (Trajectory reconstruction)
5. GET /api/report (Evaluation report export)
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_api_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "OPERATIONAL"
        assert "anpr_worker_pool" in data
        assert "stream_gateway" in data

@pytest.mark.asyncio
async def test_api_registry_cameras():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/registry/cameras")
        assert resp.status_code == 200
        cams = resp.json()
        assert len(cams) >= 50

@pytest.mark.asyncio
async def test_api_watchlist():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/watchlist")
        assert resp.status_code == 200
        wl = resp.json()
        assert len(wl) >= 10
        assert any(w["plate_number"] == "GJ01AB1234" for w in wl)

@pytest.mark.asyncio
async def test_api_route_trace():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Happy path: search for target plate
        resp = await ac.get("/api/trace?plate=GJ01AB1234")
        assert resp.status_code == 200
        data = resp.json()
        assert data["plate_number"] == "GJ01AB1234"

        # Negative path: search for unknown plate
        resp_neg = await ac.get("/api/trace?plate=UNKNOWN999")
        assert resp_neg.status_code == 200
        data_neg = resp_neg.json()
        assert data_neg["total_sightings"] == 0
        assert len(data_neg["trajectory"]) == 0

@pytest.mark.asyncio
async def test_api_evaluation_report_export():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp_md = await ac.get("/api/report?format=markdown")
        assert resp_md.status_code == 200
        assert "Technical Evaluation Report" in resp_md.text

        resp_json = await ac.get("/api/report?format=json")
        assert resp_json.status_code == 200
        assert "team_name" in resp_json.json()

@pytest.mark.asyncio
async def test_api_auth_token_and_rbac_fail_closed():
    """Verify RBAC tokens and fail-closed security (Secondary Issue #3)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # 1. Issue admin token
        token_resp = await ac.post("/api/auth/token?username=admin")
        assert token_resp.status_code == 200
        admin_token = token_resp.json()["access_token"]

        # 2. Issue RTO token
        rto_resp = await ac.post("/api/auth/token?username=rto")
        assert rto_resp.status_code == 200
        rto_token = rto_resp.json()["access_token"]

        # 3. Fail closed: Bad / forged token MUST return 401 Unauthorized
        bad_headers = {"Authorization": "Bearer forged.tampered.token"}
        bad_resp = await ac.post("/api/registry/sync", headers=bad_headers)
        assert bad_resp.status_code == 401
        assert "Invalid or expired" in bad_resp.json()["detail"]

        # 4. Role enforcement: RTO officer accessing SuperAdmin sync endpoint MUST return 403 Forbidden
        rto_headers = {"Authorization": f"Bearer {rto_token}"}
        forbidden_resp = await ac.post("/api/registry/sync", headers=rto_headers)
        assert forbidden_resp.status_code == 403
        assert "Access denied" in forbidden_resp.json()["detail"]

@pytest.mark.asyncio
async def test_api_stream_heartbeat():
    """Verify stream heartbeat endpoint refreshes activity timestamp."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/api/stream/cam-val-001/heartbeat")
        assert resp.status_code == 200
        assert resp.json()["status"] == "alive"

@pytest.mark.asyncio
async def test_on_anpr_detection_persists_and_traces():
    """
    Verify that on_anpr_detection in main.py persists detections with uuid-based IDs
    and allows /api/trace to immediately reconstruct sightings.
    """
    from app.main import on_anpr_detection
    from app.schemas import PlateDetectionEvent

    event = PlateDetectionEvent(
        plate="GJ01AB1234",
        confidence=0.98,
        camera_id="cam-val-001",
        derived_timestamp="2026-09-11T12:00:00Z",
        vehicle_type="Car",
        lat=20.3892,
        lng=72.9106
    )

    # Must succeed without NameError on uuid
    await on_anpr_detection(event)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/api/trace?plate=GJ01AB1234")
        assert resp.status_code == 200
        data = resp.json()
        assert data["plate_number"] == "GJ01AB1234"
        assert data["total_sightings"] >= 1
        assert any(pt["camera_id"] == "cam-val-001" for pt in data["trajectory"])

@pytest.mark.asyncio
async def test_webcam_status_does_not_probe_when_streaming():
    """
    Verify /api/webcam/status does not attempt cv2.VideoCapture(0) when
    cam-val-001 is actively streaming hardware_webcam.
    """
    from unittest.mock import patch
    from app.stream_gateway import gateway_manager

    with patch.object(gateway_manager, "get_stream_source", return_value="hardware_webcam"):
        with patch("cv2.VideoCapture") as mock_cap:
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get("/api/webcam/status")
                assert resp.status_code == 200
                data = resp.json()
                assert data["is_streaming_webcam"] is True
                assert data["active_stream_source"] == "hardware_webcam"
                # VideoCapture must NOT have been called while streaming!
                mock_cap.assert_not_called()

@pytest.mark.asyncio
async def test_api_cctv_inspect_endpoint():
    """
    Verify POST /api/cctv/inspect accepts image files, runs ANPR pipeline,
    and returns annotated image along with detected plates and latency metrics.
    """
    import cv2
    import numpy as np

    # Generate a dummy test image
    dummy_img = np.zeros((200, 300, 3), dtype=np.uint8)
    _, encoded = cv2.imencode(".jpg", dummy_img)
    img_bytes = encoded.tobytes()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        files = {"file": ("test_snapshot.jpg", img_bytes, "image/jpeg")}
        resp = await ac.post("/api/anpr/inspect-image", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert "detections" in data
        assert "annotated_image" in data
        assert "latency_ms" in data
        assert isinstance(data["detections"], list)

@pytest.mark.asyncio
async def test_api_cctv_inspect_video_endpoint():
    """
    Verify POST /api/anpr/inspect-video accepts video clips (MP4/AVI/MKV),
    samples keyframes, tracks unique vehicles, extracts timeline, and correlates Watchlist.
    """
    import os

    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "synthetic", "fixture_cam_val_001.mp4")
    assert os.path.exists(fixture_path), f"Fixture missing: {fixture_path}"

    with open(fixture_path, "rb") as vf:
        video_bytes = vf.read()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        files = {"file": ("test_surveillance_clip.mp4", video_bytes, "video/mp4")}
        resp = await ac.post("/api/anpr/inspect-video?sample_fps=2.5&max_seconds=10", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "video_metadata" in data
        assert data["video_metadata"]["duration_sec"] > 0
        assert data["video_metadata"]["sampled_frames"] > 0
        assert "unique_plates" in data
        assert "timeline" in data
        assert len(data["unique_plates"]) >= 1
        # Check that target plate GJ01AB1234 was identified
        assert any("GJ01AB1234" in up["plate"] for up in data["unique_plates"])
        # Check that watchlist alert was flagged for GJ01AB1234
        assert data["watchlist_alert"] is True


