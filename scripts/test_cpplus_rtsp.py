"""
CP Plus RTSP Stream Connector & ANPR Diagnostic Utility
Tests live video connectivity from CP Plus / EzyKam IP cameras over Wi-Fi.

Usage:
    python scripts/test_cpplus_rtsp.py --ip 192.168.0.xxx --password <SAFETY_CODE_OR_PASSWORD>
"""

import sys
import time
import argparse
import cv2
from pathlib import Path

def test_stream_urls(ip: str, password: str = "", username: str = "admin"):
    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root / "backend"))

    # Common CP Plus / Dahua RTSP URL patterns
    auth = f"{username}:{password}@" if password else f"{username}@"
    candidates = [
        f"rtsp://{auth}{ip}:554/cam/realmonitor?channel=1&subtype=0",  # Main HD Stream
        f"rtsp://{auth}{ip}:554/cam/realmonitor?channel=1&subtype=1",  # Substream (Fast/Low Latency)
        f"rtsp://{auth}{ip}:554/live/ch0",                             # ONVIF Generic
        f"rtsp://{auth}{ip}:554/onvif1",                               # ONVIF Channel 1
        f"rtsp://{ip}:554/cam/realmonitor?channel=1&subtype=1",        # No auth substream
    ]

    print("=" * 70)
    print(f"  CP PLUS CAMERA STREAM DIAGNOSTIC")
    print(f"  Target IP: {ip} | Port: 554 | User: {username}")
    print("=" * 70)

    working_cap = None
    working_url = None

    for url in candidates:
        masked = url.replace(f":{password}@", ":******@") if password else url
        print(f"\nProbing RTSP: {masked} ...")
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        # 3-second timeout probe
        t_start = time.time()
        connected = False
        while time.time() - t_start < 3.5:
            if cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    connected = True
                    break
            time.sleep(0.1)

        if connected:
            print(f"  [SUCCESS] Connected to CP Plus RTSP stream!")
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            print(f"  Resolution: {w}x{h} @ ~{int(fps)} FPS")
            working_cap = cap
            working_url = url
            break
        else:
            print("  [-] Not responding on this endpoint.")
            cap.release()

    if not working_cap:
        print("\n[!] Could not open RTSP stream on any candidate path.")
        print("    Troubleshooting Checklist:")
        print("    1. Verify PC View / ONVIF is enabled in the ezykam app.")
        print("    2. Verify the password (check the 6-character Safety Code on camera sticker).")
        print("    3. Ensure camera and laptop are on the same 2.4GHz Wi-Fi network.")
        return

    print("\nStarting live AI surveillance preview from your CP Plus camera...")
    print("Press 'q' or 'ESC' to close preview window.")

    # Load YOLO detector
    anpr_engine = None
    try:
        from app.anpr_engine import ANPREngine
        anpr_engine = ANPREngine(num_workers=2)
        anpr_engine.load_models()
        print("[OK] ANPR AI engine active.")
    except Exception as e:
        print(f"[!] Continuing in raw video mode ({e})")

    win_name = f"CP Plus Camera [{ip}] - Live Surveillance Stream (Press Q to exit)"
    cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win_name, 1024, 576)

    try:
        while True:
            ret, frame = working_cap.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue

            # Run ANPR
            if anpr_engine:
                try:
                    events = anpr_engine.process_frame_sync(
                        frame=frame,
                        camera_id="cam-cpplus-live",
                        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        pts_ms=time.time() * 1000
                    )
                    for det in events:
                        x1, y1, x2, y2 = det.bbox
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(frame, f"{det.plate} ({det.confidence*100:.0f}%)", (x1, y1 - 8),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                except Exception:
                    pass

            cv2.imshow(win_name, frame)
            if cv2.waitKey(1) & 0xFF in (ord('q'), ord('Q'), 27):
                break
    finally:
        working_cap.release()
        cv2.destroyAllWindows()

    print("\n" + "=" * 70)
    print("TO USE THIS CP PLUS CAMERA AS CAMERA 1 IN THE WEB DASHBOARD:")
    print(f'  $env:CPPLUS_RTSP="{working_url}"')
    print('  python backend/run.py')
    print("=" * 70)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test CP Plus RTSP Stream")
    parser.add_argument("--ip", type=str, required=True, help="Camera IP address (e.g. 192.168.0.120)")
    parser.add_argument("--password", type=str, default="", help="Camera password or safety code on sticker")
    parser.add_argument("--username", type=str, default="admin", help="RTSP username (default: admin)")
    args = parser.parse_args()

    test_stream_urls(ip=args.ip, password=args.password, username=args.username)
