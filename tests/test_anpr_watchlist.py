"""
Unit Tests for AI ANPR Engine & Watchlist Correlation
Validates:
1. Indian registration plate syntax normalization
2. Positional OCR error correction (O -> 0, B -> 8)
3. Levenshtein fuzzy matching (distance <= 1)
4. Alert-level deduplication cooldown window (60s suppression)
"""

import time
import pytest
from app.anpr_engine import anpr_engine
from app.watchlist_engine import WatchlistCorrelationEngine, levenshtein_distance
from app.schemas import PlateDetectionEvent

def test_indian_plate_normalization():
    """Verify raw plate strings are cleaned and converted into standard Indian format."""
    # Standard clean plate
    assert anpr_engine.normalize_indian_plate("GJ01AB1234") == "GJ01AB1234"
    # Spaces, dashes, and lowercase
    assert anpr_engine.normalize_indian_plate("gj 01 ab 1234") == "GJ01AB1234"
    assert anpr_engine.normalize_indian_plate("GJ-05-CD-5678") == "GJ05CD5678"

def test_indian_plate_hsrp_ind_stripping():
    """Verify Indian High Security Registration Plate (HSRP) 'IND' country prefix is cleanly stripped."""
    assert anpr_engine.normalize_indian_plate("INDGJ01AB1234") == "GJ01AB1234"
    assert anpr_engine.normalize_indian_plate("IND GJ 01 AB 1234") == "GJ01AB1234"
    assert anpr_engine.normalize_indian_plate("IND-GJ-05-CD-5678") == "GJ05CD5678"
    assert anpr_engine.normalize_indian_plate("INDGJ20KL1122") == "GJ20KL1122"

def test_positional_ocr_error_correction():
    """Verify common OCR character confusions are resolved by position."""
    # 'O' letter in district number slot (01) -> should become digit 0
    assert anpr_engine.normalize_indian_plate("GJO1AB1234") == "GJ01AB1234"
    # 'B' letter in last 4 digit slot (1284) -> should become digit 8
    assert anpr_engine.normalize_indian_plate("GJ01AB12B4") == "GJ01AB1284"

def test_levenshtein_distance_calculation():
    """Verify edit distance computation."""
    assert levenshtein_distance("GJ01AB1234", "GJ01AB1234") == 0  # Exact
    assert levenshtein_distance("GJ01AB1234", "GJ01AB1235") == 1  # 1 substitution
    assert levenshtein_distance("GJ01AB1234", "GJ01AB123") == 1   # 1 deletion
    assert levenshtein_distance("GJ01AB1234", "MH01AB1234") == 2  # 2 substitutions

def test_watchlist_exact_and_fuzzy_matching():
    """Verify watchlist matching catches exact hits and fuzzy OCR variants."""
    engine = WatchlistCorrelationEngine()
    engine.cached_watchlist = {
        "GJ01AB1234": {
            "id": "wl-001",
            "plate_number": "GJ01AB1234",
            "category": "Stolen Vehicle",
            "source_dept": "eGujCop",
            "severity": "CRITICAL",
            "person_name": "Target Suspect",
            "fir_number": "FIR-01",
            "police_station": "Vastrapur",
            "vehicle_make_model": "White Creta",
            "vehicle_color": "White",
            "notes": "Target"
        }
    }

    # 1. Exact Match (distance 0)
    match, dist = engine.match_plate("GJ01AB1234")
    assert match is not None
    assert match["plate_number"] == "GJ01AB1234"
    assert dist == 0

    # 2. Fuzzy Match with distance 1 (e.g. OCR read 'B' as '8' or '4' as '9')
    match_fuzzy, dist_fuzzy = engine.match_plate("GJ01AB1239")
    assert match_fuzzy is not None
    assert match_fuzzy["plate_number"] == "GJ01AB1234"
    assert dist_fuzzy == 1

    # 3. Non-Match (distance > 1)
    match_none = engine.match_plate("MH12DE9999")
    assert match_none is None

@pytest.mark.asyncio
async def test_alert_deduplication_cooldown():
    """Verify 60-second cooldown suppresses repeated alerts at the same camera."""
    engine = WatchlistCorrelationEngine()
    engine.cached_watchlist = {
        "GJ01AB1234": {
            "id": "wl-001",
            "plate_number": "GJ01AB1234",
            "category": "Stolen Vehicle",
            "source_dept": "eGujCop",
            "severity": "CRITICAL",
            "person_name": "Target Suspect",
            "fir_number": "FIR-01",
            "police_station": "Vastrapur",
            "vehicle_make_model": "White Creta",
            "vehicle_color": "White",
            "notes": "Target"
        }
    }

    event = PlateDetectionEvent(
        plate="GJ01AB1234",
        confidence=0.95,
        camera_id="cam-val-001",
        derived_timestamp="2026-09-09T10:00:00Z"
    )

    # First event should trigger alert
    alert1 = await engine.process_detection(event)
    assert alert1 is not None
    assert alert1["plate_number"] == "GJ01AB1234"

    # Immediate second event at same camera (stationary at signal) -> MUST BE SUPPRESSED
    alert2 = await engine.process_detection(event)
    assert alert2 is None
    assert engine.total_deduplicated_suppressions >= 1

    # Event at a DIFFERENT camera (moved down highway) -> MUST TRIGGER
    event_new_cam = PlateDetectionEvent(
        plate="GJ01AB1234",
        confidence=0.95,
        camera_id="cam-sur-001",
        derived_timestamp="2026-09-09T10:05:00Z"
    )
    alert3 = await engine.process_detection(event_new_cam)
    assert alert3 is not None
    assert alert3["camera_id"] == "cam-sur-001"

@pytest.mark.asyncio
async def test_watchlist_async_alert_listener():
    """Verify async alert listener callback executes properly without NameError on asyncio."""
    engine = WatchlistCorrelationEngine()
    engine.cached_watchlist = {
        "GJ01AB1234": {
            "id": "wl-001",
            "plate_number": "GJ01AB1234",
            "category": "Wanted Criminal",
            "source_dept": "eGujCop",
            "severity": "CRITICAL",
            "person_name": "Target Suspect",
            "fir_number": "FIR-01",
            "police_station": "Vastrapur",
            "vehicle_make_model": "White Creta",
            "vehicle_color": "White",
            "notes": "Target"
        }
    }

    received_alerts = []
    async def async_listener(alert_dict):
        received_alerts.append(alert_dict)

    engine.add_alert_listener(async_listener)

    event = PlateDetectionEvent(
        plate="GJ01AB1234",
        confidence=0.92,
        camera_id="cam-listener-001",
        derived_timestamp="2026-09-09T10:10:00Z"
    )

    alert = await engine.process_detection(event)
    assert alert is not None
    assert len(received_alerts) == 1
    assert received_alerts[0]["plate_number"] == "GJ01AB1234"

def test_anpr_pipeline_end_to_end():
    """
    End-to-End Pixel-to-Plate ANPR Pipeline Test (Critical #1 Fix).
    Feeds real video frames into the two-stage pipeline:
    Frame -> YOLO Plate Detector -> Crop -> EasyOCR -> Positional Normalization -> Plate String.
    """
    import cv2
    import os

    fixture_path = "tests/fixtures/synthetic/fixture_cam_val_001.mp4"
    assert os.path.exists(fixture_path), f"Fixture not found at {fixture_path}"

    cap = cv2.VideoCapture(fixture_path)
    # Read frame 30 where the vehicle is clearly visible in the surveillance lane
    for _ in range(30):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    assert ret is True and frame is not None, "Failed to extract frame from surveillance clip"

    # Initialize two-stage pipeline models
    anpr_engine._init_model()
    detections = anpr_engine._sync_inference(frame)

    assert len(detections) > 0, "ANPR pipeline failed to detect license plate in surveillance clip"
    det = detections[0]
    assert det["class"] == "license_plate"
    assert det["normalized_plate"] == "GJ01AB1234", f"Expected GJ01AB1234, got {det.get('normalized_plate')}"
    assert len(det["bbox"]) == 4
    assert det["bbox"][2] > det["bbox"][0] and det["bbox"][3] > det["bbox"][1]

def test_clahe_contrast_enhancement_fallback():
    """Verify CLAHE adaptive histogram fallback activates when raw crop yields empty OCR tokens."""
    import numpy as np
    from unittest.mock import MagicMock

    # Create synthetic test frame
    test_frame = np.full((200, 400, 3), 180, dtype=np.uint8)

    # Mock plate detector returning 1 valid plate box [x1, y1, x2, y2]
    mock_box = MagicMock()
    mock_box.conf = [MagicMock(item=lambda: 0.92)]
    mock_xyxy_row = MagicMock()
    mock_xyxy_row.tolist.return_value = [30, 30, 200, 90]
    mock_box.xyxy = [mock_xyxy_row]
    mock_det = MagicMock()
    mock_det.boxes = [mock_box]

    mock_plate_model = MagicMock(return_value=[mock_det])

    # Mock OCR reader: returns empty on raw color crop, returns valid detection on CLAHE grayscale
    mock_ocr = MagicMock()
    def fake_readtext(img):
        # Grayscale image (2 dimensions) corresponds to CLAHE enhanced fallback
        if len(img.shape) == 2:
            return [([[0, 0], [50, 0], [50, 20], [0, 20]], "GJ01AB1234", 0.95)]
        return []
    mock_ocr.readtext.side_effect = fake_readtext

    orig_plate_model = anpr_engine.plate_model
    orig_ocr = anpr_engine.ocr_reader
    try:
        anpr_engine.plate_model = mock_plate_model
        anpr_engine.ocr_reader = mock_ocr
        results = anpr_engine._sync_inference(test_frame)
        assert len(results) == 1
        assert results[0]["normalized_plate"] == "GJ01AB1234"
        # Verify readtext was called twice: once for raw crop, once for CLAHE fallback
        assert mock_ocr.readtext.call_count == 2
    finally:
        anpr_engine.plate_model = orig_plate_model
        anpr_engine.ocr_reader = orig_ocr


def test_positional_alphanumeric_correction():
    """Verify positional character correction and HSRP prefix removal for Indian number plates."""
    # Prefix removal (IND, INDIA, HSRP)
    assert anpr_engine.normalize_indian_plate("IND GJ 01 AB 1234") == "GJ01AB1234"
    assert anpr_engine.normalize_indian_plate("INDIA MH12CD5678") == "MH12CD5678"
    assert anpr_engine.normalize_indian_plate("HSRP DL04EF9012") == "DL04EF9012"

    # Positional letter correction in middle series (e.g. '4' -> 'A', '8' -> 'B')
    assert anpr_engine.normalize_indian_plate("GJ01481234") == "GJ01AB1234"

    # Positional digit correction in last 4 digits (e.g. 'I' -> '1', 'O' -> '0')
    assert anpr_engine.normalize_indian_plate("GJ01ABIO23") == "GJ01AB1023"


def test_cctv_image_inspection_endpoint():
    """Verify POST /api/anpr/inspect-image accepts CCTV snapshots and returns base64 annotations."""
    from fastapi.testclient import TestClient
    from unittest.mock import patch
    from app.main import app
    import numpy as np
    import cv2
    import io

    client = TestClient(app)
    # Generate synthetic surveillance frame in PNG format
    frame = np.full((360, 640, 3), 40, dtype=np.uint8)
    _, buf = cv2.imencode(".png", frame)
    file_bytes = io.BytesIO(buf.tobytes())

    # Mock detection result with a clean vehicle plate (not on watchlist)
    mock_detection_result = {
        "total_detected": 1,
        "detections": [{
            "class": "license_plate",
            "confidence": 0.94,
            "bbox": [50, 60, 200, 110],
            "plate_text": "GJ01ZZ9999",
            "normalized_plate": "GJ01ZZ9999",
            "vehicle_type": "Car"
        }],
        "latency_ms": 14.5,
        "annotated_image": "data:image/jpeg;base64,/9j/fakeBase64"
    }

    with patch.object(anpr_engine, "detect_image", return_value=mock_detection_result):
        response = client.post(
            "/api/anpr/inspect-image",
            files={"file": ("cctv_sample.png", file_bytes, "image/png")}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["total_detected"] == 1
        assert data["watchlist_alert"] is False
        assert len(data["detections"]) == 1
        assert data["detections"][0]["watchlist_match"]["matched"] is False
        assert data["annotated_image"].startswith("data:image/jpeg;base64,")
        assert "latency_ms" in data


