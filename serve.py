import os
import signal
import subprocess
import sys
import time
import webbrowser


def main() -> int:
    port = int(os.getenv("PORT", "8000"))
    backend = os.getenv("BACKEND", os.getenv("AUDIO_BACKEND", "auto"))
    default_device = "BlackHole 2ch" if sys.platform == "darwin" else "default"
    device = os.getenv("DEVICE", os.getenv("AUDIO_DEVICE", default_device))
    rate = os.getenv("AUDIO_RATE")
    channels = os.getenv("AUDIO_CHANNELS")

    print(f"Starting audio WebSocket server (backend: {backend}, device: {device})...")
    cmd = [sys.executable, "visualizer.py", "--backend", backend, "--device", device]
    if rate:
        cmd += ["--rate", rate]
    if channels:
        cmd += ["--channels", channels]
    ws = subprocess.Popen(
        cmd,
    )

    print(f"Starting HTTP server on port {port}...")
    http = subprocess.Popen([sys.executable, "-m", "http.server", str(port)])

    def cleanup(*_args):
        for p in (http, ws):
            try:
                p.terminate()
            except Exception:
                pass
        # Give processes a moment to exit cleanly
        time.sleep(0.3)
        for p in (http, ws):
            if p.poll() is None:
                try:
                    p.kill()
                except Exception:
                    pass

    # Ensure children are cleaned up on exit signals
    signal.signal(signal.SIGINT, lambda *_: cleanup())
    signal.signal(signal.SIGTERM, lambda *_: cleanup())

    # Open the browser shortly after startup
    time.sleep(0.6)
    try:
        webbrowser.open(f"http://localhost:{port}/index.html")
    except Exception:
        pass

    print("Press Ctrl-C to stop both servers.")
    try:
        # Block on the HTTP server; if it exits, clean up the WS server too
        code = http.wait()
        return code or 0
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
