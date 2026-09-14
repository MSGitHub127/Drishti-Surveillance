"""
Bootstrap server script for Team Vayunotics CCTV Integration Platform.
Runs FastAPI with Uvicorn on port 8000.
"""

import os
import sys
import signal
import uvicorn

# Ensure the backend directory is on sys.path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

def fast_exit(sig=None, frame=None):
    """Instantly kills process and releases port 8000 on Ctrl+C without waiting for long-lived streams."""
    print("\n[INFO] Shutdown signal (Ctrl+C) received. Terminating immediately...")
    os._exit(0)

def free_port_if_stale(port: int = 8000):
    """Detects and frees port 8000 from orphaned background processes before startup."""
    try:
        import psutil
        import time
        current_pid = os.getpid()
        for conn in psutil.net_connections(kind="inet"):
            if conn.laddr and conn.laddr.port == port and conn.status == "LISTEN":
                if conn.pid and conn.pid != current_pid:
                    print(f"[INFO] Freeing port {port} (terminating stale process PID {conn.pid})...")
                    try:
                        p = psutil.Process(conn.pid)
                        p.kill()
                        p.wait(timeout=2)
                        time.sleep(0.5)
                    except Exception:
                        pass
    except Exception:
        pass

if __name__ == "__main__":
    # Ensure port 8000 is clear before binding
    free_port_if_stale(8000)

    # Register fast signal handlers for Windows console
    signal.signal(signal.SIGINT, fast_exit)
    signal.signal(signal.SIGTERM, fast_exit)

    print("=" * 70)
    print("  DHRISTI SURVEILLANCE • COMMAND & CONTROL PLATFORM")
    print("  Team Vayunotics - GPH26")
    print("  Serving Command Center at: http://localhost:8000")
    print("  Health Status endpoint:    http://localhost:8000/health")
    print("  API Documentation:         http://localhost:8000/docs")
    print("=" * 70)

    try:
        config = uvicorn.Config(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=False,
            log_level="info",
            timeout_graceful_shutdown=0
        )
        server = uvicorn.Server(config)
        server.run()
    except (KeyboardInterrupt, SystemExit):
        fast_exit()
    except Exception as e:
        print(f"[ERROR] Server error: {e}")
        fast_exit()
