import os
import signal
import socket
import subprocess
import sys
import time
import webbrowser


def is_port_available(port: int, host: str = "localhost") -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
        return True
    except OSError:
        return False


def choose_available_port(preferred_port: int, host: str = "localhost", max_retries: int = 50) -> int:
    for offset in range(max_retries + 1):
        candidate = preferred_port + offset
        if is_port_available(candidate, host):
            return candidate
    raise RuntimeError(
        f"Could not find an available port in range {preferred_port}-{preferred_port + max_retries}"
    )


def main() -> int:
    requested_http_port = int(os.getenv("PORT", "8000"))
    port = choose_available_port(requested_http_port)
    if port != requested_http_port:
        print(f"HTTP port {requested_http_port} is busy; using {port}.")

    requested_ws_port = int(os.getenv("WS_PORT", os.getenv("AUDIO_WS_PORT", "8765")))
    ws_port = choose_available_port(requested_ws_port)
    if ws_port != requested_ws_port:
        print(f"WebSocket port {requested_ws_port} is busy; using {ws_port}.")

    backend = os.getenv("BACKEND", os.getenv("AUDIO_BACKEND", "auto"))
    default_device = "BlackHole 2ch" if sys.platform == "darwin" else "default"
    device = os.getenv("DEVICE", os.getenv("AUDIO_DEVICE", default_device))
    rate = os.getenv("AUDIO_RATE")
    channels = os.getenv("AUDIO_CHANNELS")

    print(
        f"Starting audio WebSocket server on {ws_port} "
        f"(backend: {backend}, device: {device})..."
    )
    cmd = [
        sys.executable,
        "visualizer.py",
        "--backend",
        backend,
        "--device",
        device,
        "--port",
        str(ws_port),
    ]
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
        webbrowser.open(f"http://localhost:{port}/index.html?wsPort={ws_port}")
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
