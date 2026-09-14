# Real Video Footage for Deliverable #3 (Participant's Own Feed Demo)

## Purpose & Strict Separation
As mandated by evaluation rules:
- **`tests/fixtures/synthetic/`**: Strictly for internal unit testing, regression testing, and CI ground-truth validation. NEVER used in the submitted demo video.
- **`test-footage/real/`**: Contains **genuine, recorded real-world traffic footage** (dashcam, mobile video, or open ANPR road surveillance dataset) with clear, readable Indian vehicle registration plates.

---

## Instructions for Deliverable #3 Video Recording

1. **Place Real Footage**:
   Place 2 to 3 real MP4 traffic video clips in this folder:
   - `test-footage/real/camera_real_01.mp4`
   - `test-footage/real/camera_real_02.mp4`
   - `test-footage/real/camera_real_03.mp4`

2. **Seed Known Real Plate**:
   Note a clear vehicle registration number visible in your recorded video (for example, `GJ01AB1234` or any plate from your footage), and verify it exists in `data/seed_watchlist.json`.

3. **Start RTSP Streaming Relay**:
   Run the streaming helper script:
   ```bash
   python scripts/stream_real_footage.py
   ```
   This streams your real video files as live looped RTSP endpoints over TCP:
   - `rtsp://localhost:8554/stream/1` &rarr; `camera_real_01.mp4`
   - `rtsp://localhost:8554/stream/2` &rarr; `camera_real_02.mp4`
   - `rtsp://localhost:8554/stream/3` &rarr; `camera_real_03.mp4`

4. **Run Live Unified Platform**:
   ```bash
   python backend/run.py
   ```
   The backend pipeline (`stream_gateway.py` &rarr; `anpr_engine.py` &rarr; `watchlist_engine.py`) connects to these RTSP endpoints using the exact same code path, protocol enforcement (RTSP over TCP, PTS monotonic timing, backoff reconnect), detects the real vehicles, correlates the plate against the active watchlist, fires the real-time alert, and plots the reconstructed movement route on the GIS map.

5. **Screen Record (2–3 minutes)**:
   Capture your screen showing:
   - Live stream onboarding and playback in the Multi-Camera Grid.
   - Real-time YOLO detection and OCR plate extraction.
   - The watchlist alert triggering in the alert console with audio siren and suspect metadata.
   - The interactive route trajectory traced across multiple camera locations on the Gujarat GIS map.
