"""
Synthetic Test Fixture Generator (CI & Ground-Truth Verification)
Outputs to: tests/fixtures/synthetic/
ROLE: Internal unit testing, regression testing, and CI ground-truth validation ONLY.
NOT FOR DELIVERABLE #3 DEMO VIDEO (Real footage is used for submission).

Generates deterministic synthetic surveillance clips across 6 cameras matching data/seed_cameras.json:
- Camera 1 (cam-val-001 | Valsad): GJ01AB1234 (Hero Target), GJ05CD5678 (Wanted NDPS)
- Camera 2 (cam-dah-001 | Dahod):  GJ01AB1234 (Hero Target), GJ20KL1122 (Overload Truck)
- Camera 3 (cam-ahm-001 | Ahmedabad): GJ01AB1234 (Hero Target), GJ06XY9999 (Stolen SUV)
- Camera 4 (cam-jam-001 | Jamnagar): GJ01AB1234 (Hero Target), GJ10EF4321 (Coastal Suspect)
- Camera 5 (cam-dwk-001 | Dwarka): GJ01AB1234 (Hero Target - Final Sighting)
- Camera 6 (cam-som-001 | Somnath): NEGATIVE TEST CASE - Non-target vehicles only (GJ11AA9999, GJ11ZZ1111)
  Verifies that trace_engine returns a clean empty result, not an error, when a plate is absent.
"""

import os
import cv2
import numpy as np

def create_surveillance_fixture(
    output_path: str,
    camera_id: str,
    camera_name: str,
    location_str: str,
    lat: float,
    lng: float,
    target_plates: list,
    duration_sec: int = 6,
    fps: int = 25,
    width: int = 1280,
    height: int = 720
):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    total_frames = duration_sec * fps
    print(f"Generating fixture: {output_path} ({total_frames} frames)...")

    # Set up vehicles
    vehicles = []
    for idx, (plate, vtype, color_bgr) in enumerate(target_plates):
        start_frame = idx * int(total_frames / (len(target_plates) + 0.5))
        vehicles.append({
            "plate": plate,
            "type": vtype,
            "color": color_bgr,
            "start_frame": start_frame,
            "duration": int(fps * 2.8),
            "lane_y": 380 + (idx % 3) * 90
        })

    for f in range(total_frames):
        # 1. Background
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[0:280] = (25, 30, 40)
        frame[280:height] = (45, 48, 52)

        # Markings
        cv2.line(frame, (0, 360), (width, 360), (200, 200, 200), 2)
        cv2.line(frame, (0, 470), (width, 470), (200, 200, 200), 2)
        cv2.line(frame, (0, 580), (width, 580), (200, 200, 200), 2)

        # Center divider
        dash_offset = (f * 10) % 60
        for x in range(-dash_offset, width, 60):
            cv2.line(frame, (x, 470), (x + 30, 470), (30, 215, 255), 3)

        # 2. Render Moving Vehicles
        for v in vehicles:
            if v["start_frame"] <= f < (v["start_frame"] + v["duration"]):
                progress = (f - v["start_frame"]) / v["duration"]
                x = int(-200 + progress * (width + 400))
                y = v["lane_y"]

                bw, bh = 220, 85
                cv2.rectangle(frame, (x, y), (x + bw, y + bh), v["color"], -1)
                cv2.rectangle(frame, (x, y), (x + bw, y + bh), (20, 20, 20), 2)
                cv2.rectangle(frame, (x + 130, y + 8), (x + 195, y + bh - 8), (50, 60, 75), -1)

                cv2.circle(frame, (x + 45, y + bh), 16, (15, 15, 15), -1)
                cv2.circle(frame, (x + bw - 45, y + bh), 16, (15, 15, 15), -1)

                pw, ph = 110, 28
                px = x + bw - 15
                py = y + int(bh / 2) - 10

                cv2.rectangle(frame, (px, py), (px + pw, py + ph), (250, 250, 250), -1)
                cv2.rectangle(frame, (px, py), (px + pw, py + ph), (0, 0, 0), 2)
                cv2.rectangle(frame, (px, py), (px + 12, py + ph), (180, 50, 20), -1)
                cv2.putText(frame, v["plate"], (px + 15, py + 19), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 0, 0), 2)

        # 3. OSD Header
        cv2.rectangle(frame, (20, 20), (580, 85), (10, 10, 10), -1)
        cv2.rectangle(frame, (20, 20), (580, 85), (60, 60, 60), 1)

        pts_sec = f / fps
        osd_time = f"2026-09-09 10:14:{pts_sec:06.3f} UTC [PTS: {pts_sec*1000:06.0f}ms]"
        cv2.putText(frame, f"{camera_name} ({camera_id})", (32, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 2)
        cv2.putText(frame, f"{location_str} | GPS: {lat:.4f}, {lng:.4f}", (32, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (180, 180, 180), 1)
        cv2.putText(frame, osd_time, (32, 78), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (50, 220, 50), 1)

        writer.write(frame)

    writer.release()
    print(f"Fixture created: {output_path}")

if __name__ == "__main__":
    # Scoped strictly to tests/fixtures/synthetic/
    fixtures_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fixtures", "synthetic")

    # Cross-checked with data/seed_cameras.json coordinates and IDs
    fixtures = [
        # Camera 1: Valsad Checkpost (NH48)
        ("fixture_cam_val_001.mp4", "cam-val-001", "Valsad RTO Interstate Checkpost", "NH-48 Bhilad Interstate Checkpoint", 20.6128, 72.9289, [
            ("GJ01AB1234", "White Hyundai Creta", (245, 245, 245)),
            ("GJ05CD5678", "Silver Maruti Swift", (190, 190, 190))
        ]),
        # Camera 2: Dahod Border (NH47)
        ("fixture_cam_dah_001.mp4", "cam-dah-001", "Dahod MP-Gujarat Border Checkpoint", "NH-47 Pitol Border Checkpost", 22.8315, 74.2589, [
            ("GJ20KL1122", "Tata Heavy Truck", (40, 90, 160)),
            ("GJ01AB1234", "White Hyundai Creta", (245, 245, 245))
        ]),
        # Camera 3: Ahmedabad SG Highway (ISKCON)
        ("fixture_cam_ahm_001.mp4", "cam-ahm-001", "Ahmedabad SG Highway ISKCON Junction", "SG Highway & ISKCON Cross Road", 23.0298, 72.5074, [
            ("GJ06XY9999", "Black Mahindra Scorpio", (30, 30, 30)),
            ("GJ01AB1234", "White Hyundai Creta", (245, 245, 245))
        ]),
        # Camera 4: Jamnagar Refinery Complex
        ("fixture_cam_jam_001.mp4", "cam-jam-001", "Jamnagar Refinery Ring Road", "Moti Khavdi Industrial Corridor", 22.4215, 69.8512, [
            ("GJ10EF4321", "Grey Toyota Innova", (140, 140, 140)),
            ("GJ01AB1234", "White Hyundai Creta", (245, 245, 245))
        ]),
        # Camera 5: Dwarka Temple Chokdi
        ("fixture_cam_dwk_001.mp4", "cam-dwk-001", "Dwarka Dwarkadhish Temple Approach", "Dwarkadhish Temple North Approach", 22.2394, 68.9678, [
            ("GJ01AB1234", "White Hyundai Creta", (245, 245, 245))
        ]),
        # Camera 6: Somnath Temple Complex (NEGATIVE TEST CASE)
        # None of the tracked plates (GJ01AB1234, GJ05CD5678, GJ06XY9999, etc.) appear here.
        ("fixture_cam_som_001_negative.mp4", "cam-som-001", "Somnath Temple North Gate", "Somnath Temple North Parking Gate", 20.8880, 70.4012, [
            ("GJ11AA9999", "Local Tourist Taxi", (50, 180, 240)),
            ("GJ11ZZ1111", "Auto Rickshaw", (30, 200, 50))
        ])
    ]

    for filename, cam_id, cam_name, loc, lat, lng, targets in fixtures:
        out_file = os.path.join(fixtures_dir, filename)
        create_surveillance_fixture(out_file, cam_id, cam_name, loc, lat, lng, targets, duration_sec=6)

    print(f"\nAll 6 synthetic test fixtures (5 positive + 1 negative) created in {fixtures_dir}")
