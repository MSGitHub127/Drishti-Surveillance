"""
Live Hardware USB Webcam Diagnostic & ANPR Live Preview
Tests USB webcam connectivity, resolution, FPS, and real-time ANPR plate recognition.

Usage:
    python scripts/test_webcam.py
    python scripts/test_webcam.py --index 1
    python scripts/test_webcam.py --no-anpr   (pure video feed test without AI models)
"""

import os
import sys
import time
import argparse
import sqlite3
from pathlib import Path
import cv2

# Windows DirectShow backend for zero-delay hardware access
CAP_BACKEND = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY

def probe_cameras(max_devices: int = 4):
    """Probes video device indices and returns list of accessible cameras."""
    available = []
    print("\nScanning for connected video cameras...")
    for idx in range(max_devices):
        cap = cv2.VideoCapture(idx, CAP_BACKEND)
        if cap is not None and cap.isOpened():
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            available.append((idx, w, h, fps))
            cap.release()
            print(f"  [Camera Index {idx}] DETECTED: {w}x{h} @ ~{int(fps)} FPS")
        else:
            if cap:
                cap.release()
    return available

def load_watchlist_cache():
    """Loads active watchlist plates from local database for instant alert check."""
    repo_root = Path(__file__).resolve().parent.parent
    db_path = repo_root / "data" / "cctv_local.db"
    watchlist = {}
    if db_path.exists():
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("SELECT normalized_plate, severity, category, person_name FROM watchlist WHERE active = 1")
            for row in cur.fetchall():
                watchlist[row[0].upper()] = {
                    "severity": row[1],
                    "category": row[2],
                    "person_name": row[3]
                }
            conn.close()
        except Exception:
            pass
    return watchlist

def main():
    parser = argparse.ArgumentParser(description="USB Webcam Diagnostic & Live ANPR Tester")
    parser.add_argument("--index", type=int, default=None, help="Device index (e.g. 0, 1)")
    parser.add_argument("--no-anpr", action="store_true", help="Skip loading AI models; show raw video feed only")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root / "backend"))

    available_cams = probe_cameras(max_devices=4)
    if not available_cams:
        print("\n[!] No active video cameras detected!")
        print("    1. Please ensure your USB webcam is firmly plugged in.")
        print("    2. Check that Windows Camera privacy settings allow desktop apps to access the camera.")
        return

    # Choose device index
    selected_idx = args.index
    if selected_idx is None:
        # Default: if multiple cameras found and index 1 exists, suggest or default
        if len(available_cams) > 1:
            print(f"\n[i] Multiple cameras detected ({len(available_cams)}).")
            print(f"    Index 0 is often the built-in laptop webcam.")
            print(f"    Index 1 is typically the external USB webcam.")
            selected_idx = available_cams[-1][0]  # External is usually last index
            print(f"    Auto-selecting Camera Index {selected_idx}. (Use --index 0 to change)")
        else:
            selected_idx = available_cams[0][0]

    print(f"\nOpening Camera Index {selected_idx}...")
    cap = cv2.VideoCapture(selected_idx, CAP_BACKEND)
    if not cap.isOpened():
        # Fallback to default backend
        cap = cv2.VideoCapture(selected_idx)

    if not cap.isOpened():
        print(f"[!] Failed to open camera device index {selected_idx}.")
        return

    # Set preferred resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[OK] Camera {selected_idx} opened at {actual_w}x{actual_h}")

    # Watchlist lookup
    watchlist = load_watchlist_cache()
    print(f"[OK] Loaded {len(watchlist)} watchlist targets from database.")

    # Optional ANPR setup
    anpr_engine = None
    if not args.no_anpr:
        print("\nLoading YOLO Plate Detector & OCR Engine for live ANPR preview...")
        try:
            from app.anpr_engine import ANPREngine
            anpr_engine = ANPREngine(num_workers=2)
            anpr_engine.load_models()
            print("[OK] ANPR Models ready! Live detection active.")
        except Exception as e:
            print(f"[!] Could not load ANPR models ({e}). Continuing in raw video mode.")
            anpr_engine = None

    print("\n" + "=" * 65)
    print(f"  LIVE WEBCAM PREVIEW ACTIVE (Camera Index: {selected_idx})")
    print("  - Hold up a vehicle license plate in front of the camera.")
    print("  - Recognized plates will be highlighted in real time.")
    print("  - Watchlist matches will trigger RED tactical alert banners.")
    print("  - Press 'q' or 'ESC' in the video window to exit.")
    print("=" * 65 + "\n")

    frame_count = 0
    fps_calc = 0.0
    t_start = time.time()
    last_detections = []
    alert_banner = None
    alert_banner_expire = 0.0

    window_name = f"Gujarat Smart CCTV - Live Camera [Device {selected_idx}] - Press Q to Exit"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1024, 576)

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue

            frame_count += 1
            if frame_count % 15 == 0:
                dt = time.time() - t_start
                if dt > 0:
                    fps_calc = 15.0 / dt
                t_start = time.time()

            # Run ANPR every 3 frames for high responsiveness
            if anpr_engine and (frame_count % 3 == 0):
                try:
                    events = anpr_engine.process_frame_sync(
                        frame=frame,
                        camera_id=f"webcam-{selected_idx}",
                        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        pts_ms=time.time() * 1000
                    )
                    last_detections = events
                    for ev in events:
                        norm = ev.plate_number.replace(" ", "").upper()
                        if norm in watchlist:
                            match = watchlist[norm]
                            alert_banner = f"ALERT: WATCHLIST MATCH [{norm}] - {match['severity']} ({match['category']})"
                            alert_banner_expire = time.time() + 4.0
                            print(f"\n>>> 🚨 {alert_banner} <<<")
                            if os.name == "nt":
                                try:
                                    import winsound
                                    winsound.Beep(1200, 200)
                                except Exception:
                                    pass
                except Exception:
                    pass

            # Draw detections
            for det in last_detections:
                x1, y1, x2, y2 = det.bbox
                plate = det.plate_number
                norm = plate.replace(" ", "").upper()
                is_hit = norm in watchlist

                box_color = (0, 0, 255) if is_hit else (0, 255, 0)
                cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)

                # Label
                label = f"{plate} ({det.confidence*100:.0f}%)"
                if is_hit:
                    label += f" - {watchlist[norm]['severity']}"
                (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                cv2.rectangle(frame, (x1, max(0, y1 - lh - 10)), (x1 + lw + 8, y1), box_color, -1)
                cv2.putText(frame, label, (x1 + 4, max(lh + 2, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

            # Draw Alert Banner if active
            if alert_banner and time.time() < alert_banner_expire:
                cv2.rectangle(frame, (0, 0), (frame.shape[1], 45), (0, 0, 220), -1)
                cv2.putText(frame, alert_banner, (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255, 255, 255), 2)

            # Draw OSD info bar at bottom
            osd = f"CAM DEV {selected_idx} | {actual_w}x{actual_h} | {fps_calc:.1f} FPS | ANPR: {'ACTIVE' if anpr_engine else 'OFF'} | Press 'q' to exit"
            cv2.rectangle(frame, (0, frame.shape[0] - 30), (frame.shape[1], frame.shape[0]), (20, 20, 20), -1)
            cv2.putText(frame, osd, (15, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 200), 1)

            cv2.imshow(window_name, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), ord('Q'), 27):  # 'q' or ESC
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("\nCamera test finished.")
        print("To run the FULL web platform with this USB webcam attached, run:")
        print(f'  $env:USE_LIVE_WEBCAM="true"')
        print(f'  $env:WEBCAM_INDEX="{selected_idx}"')
        print(f'  python backend/run.py\n')

if __name__ == "__main__":
    main()
