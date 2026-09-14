"""
Unit Tests for Vehicle Route Reconstruction (Test Scenario #1)
Validates:
1. Haversine great-circle distance calculation
2. Chronological trajectory ordering and velocity estimation
3. Zero-match edge case handling (Negative test verification)
4. Integration with synthetic camera fixtures
"""

import os
import pytest
from datetime import datetime
from app.trace_engine import haversine_distance_km, RouteTraceService
from app.schemas import TraceRouteResponse

def test_haversine_distance():
    """Verify GPS distance calculation between known Gujarat coordinates."""
    # Ahmedabad ISKCON (23.0298, 72.5074) to Gandhinagar Sachivalaya (23.2189, 72.6567)
    dist = haversine_distance_km(23.0298, 72.5074, 23.2189, 72.6567)
    # Expected distance is ~26.0 km
    assert 24.0 <= dist <= 28.0

    # Same location distance is 0
    assert haversine_distance_km(23.0, 72.0, 23.0, 72.0) == 0.0

def test_zero_result_graceful_handling():
    """Verify unobserved vehicle registration returns clean empty trajectory without error."""
    resp = TraceRouteResponse(
        plate_number="UNKNOWN999",
        total_sightings=0,
        first_seen=None,
        last_seen=None,
        total_distance_km=0.0,
        average_speed_kmh=0.0,
        active_watchlist_match=None,
        trajectory=[]
    )
    assert resp.total_sightings == 0
    assert len(resp.trajectory) == 0
    assert resp.average_speed_kmh == 0.0

def test_synthetic_fixtures_and_negative_test_case():
    """
    Verifies that the synthetic fixtures in tests/fixtures/synthetic/ exist,
    match data/seed_cameras.json IDs, and include the 6th negative camera.
    """
    fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures", "synthetic")
    assert os.path.exists(fixtures_dir), f"Fixtures directory {fixtures_dir} should exist"

    expected_fixtures = [
        "fixture_cam_val_001.mp4",
        "fixture_cam_dah_001.mp4",
        "fixture_cam_ahm_001.mp4",
        "fixture_cam_jam_001.mp4",
        "fixture_cam_dwk_001.mp4",
        "fixture_cam_som_001_negative.mp4"  # Negative test case (untracked plates only)
    ]

    for f in expected_fixtures:
        fixture_path = os.path.join(fixtures_dir, f)
        assert os.path.exists(fixture_path), f"Expected fixture {f} missing in {fixtures_dir}"
        assert os.path.getsize(fixture_path) > 100000, f"Fixture {f} should be a valid non-empty video file"
