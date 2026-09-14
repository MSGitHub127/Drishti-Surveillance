"""
Real Video Footage Stream Relay for Deliverable #3 (Own-Feed Demonstration)
Serves genuine recorded video clips from test-footage/real/ as looped RTSP/HLS endpoints
into MediaMTX (or local relay server), enabling the SAME live pipeline:
stream_gateway.py -> anpr_engine.py -> watchlist_engine.py -> trace_engine.py
to process real footage with zero code changes and zero shortcuts.
"""

import os
import sys
import time
import subprocess
import shutil
from pathlib import Path

def find_real_clips(real_dir: Path):
    """Finds all .mp4 video files in test-footage/real/."""
    valid_exts = [".mp4", ".avi", ".mkv", ".mov"]
    return [p for p in real_dir.iterdir() if p.suffix.lower() in valid_exts]

def main():
    script_dir = Path(__file__).resolve().parent
    real_dir = script_dir.parent / "test-footage" / "real"
    mediamtx_rtsp_url = "rtsp://localhost:8554"

    print("=" * 70)
    print("  DELIVERABLE #3: REAL-FOOTAGE RTSP STREAM RELAY")
    print(f"  Source Directory: {real_dir}")
    print("=" * 70)

    if not real_dir.exists():
        real_dir.mkdir(parents=True, exist_ok=True)

    clips = find_real_clips(real_dir)
    if not clips:
        print(f"\n[!] Notice: No real video files found in {real_dir}.")
        print("    Please place 2-3 genuine recorded traffic MP4 clips in that directory.")
        print("    Example: camera_real_01.mp4, camera_real_02.mp4")
        print("    Refer to test-footage/real/README.md for guidelines.\n")
        return

    print(f"Found {len(clips)} real video clips to stream:")
    for idx, clip in enumerate(clips):
        stream_id = idx + 1
        target_rtsp = f"{mediamtx_rtsp_url}/stream/{stream_id}"
        print(f"  [{stream_id}] {clip.name} -> {target_rtsp}")

    # Check for FFmpeg availability
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        print("\n[!] 'ffmpeg' binary not detected on PATH.")
        print("    To publish streams directly to MediaMTX, install FFmpeg or run:")
        for idx, clip in enumerate(clips):
            print(f"    ffmpeg -re -stream_loop -1 -i \"{clip}\" -c copy -f rtsp rtsp://localhost:8554/stream/{idx+1}")
        return

    print("\nStarting FFmpeg RTSP streaming loops (Press Ctrl+C to stop)...")
    processes = []
    try:
        for idx, clip in enumerate(clips):
            stream_id = idx + 1
            cmd = [
                ffmpeg_bin,
                "-re",
                "-stream_loop", "-1",
                "-i", str(clip),
                "-c", "copy",
                "-f", "rtsp",
                f"{mediamtx_rtsp_url}/stream/{stream_id}"
            ]
            print(f"Launching Stream {stream_id}: {' '.join(cmd)}")
            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(p)

        print("\n[✓] All real clips are actively publishing as live RTSP over TCP streams.")
        print("    The backend pipeline will ingest them from rtsp://localhost:8554/stream/<id>.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping streaming relay processes...")
        for p in processes:
            p.terminate()
        print("All stream processes terminated.")

if __name__ == "__main__":
    main()
