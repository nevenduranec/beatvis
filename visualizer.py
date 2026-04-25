
import asyncio
import subprocess
import json
import shutil
import os
import sys
import argparse
import re
import errno
from typing import Optional

CHUNK_FRAMES = 1024
DEFAULT_RATE = 48000
DEFAULT_CHANNELS = 2

BACKEND_AUTO = "auto"
BACKEND_AVFOUNDATION = "avfoundation"  # macOS (needs loopback device like BlackHole)
BACKEND_PULSE = "pulse"  # Linux (PulseAudio/PipeWire-Pulse monitor source)
BACKEND_DSHOW = "dshow"  # Windows (needs Stereo Mix / VB-CABLE / similar loopback device)
SUPPORTED_BACKENDS = (BACKEND_AUTO, BACKEND_AVFOUNDATION, BACKEND_PULSE, BACKEND_DSHOW)


def default_backend_for_platform() -> str:
    if sys.platform == "darwin":
        return BACKEND_AVFOUNDATION
    if sys.platform.startswith("win"):
        return BACKEND_DSHOW
    return BACKEND_PULSE


def resolve_backend(backend: Optional[str]) -> str:
    backend = (backend or os.getenv("AUDIO_BACKEND") or os.getenv("BACKEND") or BACKEND_AUTO).strip()
    if not backend or backend == BACKEND_AUTO:
        return default_backend_for_platform()
    if backend not in SUPPORTED_BACKENDS:
        return default_backend_for_platform()
    return backend


def is_address_in_use_error(exc: OSError) -> bool:
    if exc.errno == errno.EADDRINUSE:
        return True
    if exc.errno == 10048:
        return True
    message = str(exc).lower()
    return "address already in use" in message


def list_avfoundation_audio_devices() -> list[tuple[str, str]]:
    """Returns a list of (index, name) audio devices reported by ffmpeg avfoundation."""
    if not shutil.which("ffmpeg"):
        return []

    try:
        proc = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-f",
                "avfoundation",
                "-list_devices",
                "true",
                "-i",
                "",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except Exception:
        return []

    text = (proc.stderr or b"").decode("utf-8", errors="replace")
    devices: list[tuple[str, str]] = []
    in_audio = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if "AVFoundation audio devices:" in line:
            in_audio = True
            continue
        if "AVFoundation video devices:" in line:
            in_audio = False
            continue
        if not in_audio:
            continue

        # Example: [AVFoundation indev @ 0x...] [1] BlackHole 2ch
        if "] [" in line and "]" in line:
            try:
                left = line.rsplit("] [", 1)[-1]
                idx, name = left.split("] ", 1)
                idx = idx.strip()
                name = name.strip()
                if idx.isdigit() and name:
                    devices.append((idx, name))
            except Exception:
                continue

    return devices


def avfoundation_list_devices_output() -> str:
    """Raw ffmpeg output for avfoundation device listing (macOS)."""
    if not shutil.which("ffmpeg"):
        return ""
    return _run_text(
        [
            "ffmpeg",
            "-hide_banner",
            "-f",
            "avfoundation",
            "-list_devices",
            "true",
            "-i",
            "",
        ]
    )


def resolve_avfoundation_audio_device(device: Optional[str]) -> str:
    """Resolves an avfoundation audio device spec (index/name) to an index when possible."""
    device = (device or os.getenv("AUDIO_DEVICE") or os.getenv("DEVICE") or "").strip()
    if not device:
        return "0"
    if device.isdigit():
        return device

    devices = list_avfoundation_audio_devices()
    if not devices:
        return device

    target = device.casefold()
    # Exact match first (case-insensitive)
    for idx, name in devices:
        if name.casefold() == target:
            return idx

    # Substring match next (helps when ffmpeg appends suffixes)
    for idx, name in devices:
        if target in name.casefold():
            return idx

    # If the user passed a Multi-Output/Aggregate device name (output-only),
    # fall back to BlackHole if available since that's the loopback capture device.
    if "multi" in target or "aggregate" in target:
        for idx, name in devices:
            if "blackhole" in name.casefold():
                return idx

    return device


def resolve_avfoundation_audio_device_strict(device: Optional[str]) -> Optional[str]:
    """Resolves to an index or returns None if it can't be resolved."""
    device = (device or "").strip()
    if not device or device.lower() == "default":
        device = "BlackHole 2ch"
    if device.isdigit():
        return device

    devices = list_avfoundation_audio_devices()
    if not devices:
        return None

    target = device.casefold()
    for idx, name in devices:
        if name.casefold() == target:
            return idx
    for idx, name in devices:
        if target in name.casefold():
            return idx
    if "multi" in target or "aggregate" in target:
        for idx, name in devices:
            if "blackhole" in name.casefold():
                return idx
    return None


def _run_text(args: list[str]) -> str:
    try:
        proc = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except Exception:
        return ""
    # ffmpeg device listing often goes to stderr
    return ((proc.stderr or b"") + (proc.stdout or b"")).decode("utf-8", errors="replace")


def list_dshow_audio_devices() -> list[str]:
    """Returns a list of DirectShow audio device names (Windows)."""
    if not shutil.which("ffmpeg"):
        return []

    text = _run_text(
        [
            "ffmpeg",
            "-hide_banner",
            "-f",
            "dshow",
            "-list_devices",
            "true",
            "-i",
            "dummy",
        ]
    )
    if not text:
        return []

    devices: list[str] = []
    in_audio = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if "DirectShow audio devices" in line:
            in_audio = True
            continue
        if "DirectShow video devices" in line:
            in_audio = False
            continue
        if not in_audio:
            continue

        # Example:
        # [dshow @ ...]  "Stereo Mix (Realtek(R) Audio)"
        m = re.search(r"\"([^\"]+)\"", line)
        if m:
            name = m.group(1).strip()
            if name and name not in devices:
                devices.append(name)
    return devices


def _pactl_text(args: list[str]) -> str:
    if not shutil.which("pactl"):
        return ""
    return _run_text(["pactl", *args])


def list_pulse_sources() -> list[str]:
    """Returns a list of PulseAudio source names (Linux). Monitor sources end with '.monitor'."""
    text = _pactl_text(["list", "short", "sources"])
    if not text:
        return []
    sources: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # index \t name \t driver \t ...
        parts = line.split("\t")
        if len(parts) >= 2:
            name = parts[1].strip()
            if name:
                sources.append(name)
    return sources


def get_default_pulse_monitor_source() -> Optional[str]:
    """Best-effort default monitor source for system audio capture on Linux."""
    info = _pactl_text(["info"])
    sources = list_pulse_sources()
    if not sources:
        return None

    default_sink = ""
    for raw_line in info.splitlines():
        line = raw_line.strip()
        if line.lower().startswith("default sink:"):
            default_sink = line.split(":", 1)[-1].strip()
            break

    if default_sink:
        candidate = f"{default_sink}.monitor"
        if candidate in sources:
            return candidate

    # Fall back to first monitor source if present
    for name in sources:
        if name.endswith(".monitor"):
            return name
    return None


def resolve_system_audio_device(backend: str, device: Optional[str]) -> Optional[str]:
    device = (device or os.getenv("AUDIO_DEVICE") or os.getenv("DEVICE") or "").strip()
    if backend == BACKEND_AVFOUNDATION:
        # Loopback device like BlackHole shows up as an input; we map its name to an index.
        return resolve_avfoundation_audio_device_strict(device)

    if backend == BACKEND_PULSE:
        if not device or device.lower() == "default":
            return get_default_pulse_monitor_source() or None
        return device

    if backend == BACKEND_DSHOW:
        # Windows: requires a loopback capture device such as "Stereo Mix" or VB-CABLE.
        if device and device.lower() != "default":
            return device

        devices = list_dshow_audio_devices()
        if not devices:
            return None

        keywords = (
            "stereo mix",
            "what u hear",
            "wave out mix",
            "cable output",
            "vb-audio",
            "virtual cable",
            "virtual audio",
            "loopback",
        )
        for name in devices:
            lowered = name.casefold()
            if any(k in lowered for k in keywords):
                return name
        return None

    return device or None


def build_ffmpeg_command(
    backend: str, device: Optional[str], *, rate: int = DEFAULT_RATE, channels: int = DEFAULT_CHANNELS
):
    """Builds an ffmpeg command for system-audio capture (loopback).

    backend:
      - avfoundation (macOS): capture from a loopback input (e.g. BlackHole)
      - pulse (Linux): capture from a sink monitor source (*.monitor)
      - dshow (Windows): capture from a loopback capture device (Stereo Mix / VB-CABLE)
    """
    if backend == BACKEND_AVFOUNDATION:
        if not device:
            raise ValueError("Missing avfoundation audio device index")
        # avfoundation expects ":<audio>" when capturing audio-only
        ffmpeg_input = f":{device}"
        input_args = ["-f", "avfoundation", "-i", ffmpeg_input]
    elif backend == BACKEND_PULSE:
        ffmpeg_input = device or "default"
        input_args = ["-f", "pulse", "-i", ffmpeg_input]
    elif backend == BACKEND_DSHOW:
        if not device:
            # Use a placeholder; caller will surface a helpful error before launching.
            ffmpeg_input = "audio="
        elif device.startswith("audio="):
            ffmpeg_input = device
        else:
            ffmpeg_input = f"audio={device}"
        input_args = ["-f", "dshow", "-i", ffmpeg_input]
    else:
        raise ValueError(f"Unsupported backend: {backend}")

    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        *input_args,
        "-ac",
        str(channels),
        "-f",
        "s16le",
        "-ar",
        str(rate),
        "-acodec",
        "pcm_s16le",
        "-",
    ]

async def audio_processor(
    websocket,
    *,
    device: Optional[str] = None,
    backend: Optional[str] = None,
    rate: int = DEFAULT_RATE,
    channels: int = DEFAULT_CHANNELS,
):
    """Processes audio from ffmpeg and sends frequency data to WebSocket."""
    try:
        import numpy as np
    except ModuleNotFoundError:
        await websocket.send(
            json.dumps(
                {"error": 'Missing dependency "numpy". Install with: python3 -m pip install -r requirements.txt'}
            )
        )
        return

    if not shutil.which('ffmpeg'):
        await websocket.send(json.dumps({"error": "ffmpeg not found in PATH"}))
        return

    resolved_backend = resolve_backend(backend)
    resolved_device = resolve_system_audio_device(resolved_backend, device)
    if resolved_backend == BACKEND_AVFOUNDATION and not resolved_device:
        await websocket.send(
            json.dumps(
                {
                    "error": (
                        "No macOS loopback input could be resolved. "
                        "Install a loopback driver (e.g. BlackHole) and route system audio through it, "
                        "then run: python3 visualizer.py --backend avfoundation --list-devices "
                        "and pass the device via --device. "
                        "Also ensure Terminal/Python has Microphone permission in System Settings."
                    )
                }
            )
        )
        return
    if resolved_backend == BACKEND_DSHOW and not resolved_device:
        await websocket.send(
            json.dumps(
                {
                    "error": (
                        "No Windows loopback capture device selected/found. "
                        "Enable 'Stereo Mix' or install a virtual cable (e.g. VB-CABLE), "
                        "then run: python3 visualizer.py --backend dshow --list-devices "
                        "and pass one via --device."
                    )
                }
            )
        )
        return

    if resolved_backend == BACKEND_PULSE and not resolved_device:
        await websocket.send(
            json.dumps(
                {
                    "error": (
                        "No PulseAudio/PipeWire monitor source found. "
                        "Ensure 'pactl' is installed and PulseAudio/PipeWire-Pulse is running, "
                        "then run: python3 visualizer.py --backend pulse --list-devices "
                        "and pass a '*.monitor' source via --device."
                    )
                }
            )
        )
        return

    try:
        cmd = build_ffmpeg_command(resolved_backend, resolved_device, rate=rate, channels=channels)
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        await websocket.send(json.dumps({"error": "Unable to launch ffmpeg"}))
        return
    
    # Removed backend smoothing - handled in frontend for EQ-style behavior

    try:
        while True:
            bytes_per_frame = 2 * max(1, channels)  # s16le * channels
            raw_audio = proc.stdout.read(CHUNK_FRAMES * bytes_per_frame)
            if not raw_audio:
                stderr = b""
                try:
                    if proc.stderr is not None:
                        stderr = proc.stderr.read() or b""
                except Exception:
                    stderr = b""

                message = "No raw audio data received from ffmpeg."
                details = stderr.decode("utf-8", errors="replace").strip()
                if details:
                    message = f"{message} ffmpeg: {details}"
                await websocket.send(json.dumps({"error": message}))
                break

            audio_interleaved = np.frombuffer(raw_audio, dtype=np.int16)
            if audio_interleaved.size == 0:
                await asyncio.sleep(0.02)
                continue

            # Convert to mono for analysis
            if channels > 1:
                frames = audio_interleaved.size // channels
                audio_interleaved = audio_interleaved[: frames * channels]
                audio_data = (
                    audio_interleaved.reshape(frames, channels).mean(axis=1).astype(np.float32)
                )
            else:
                audio_data = audio_interleaved.astype(np.float32)

            # Real FFT for real-valued signals (positive freqs only)
            spectrum = np.abs(np.fft.rfft(audio_data))

            # Skip the first few bins to avoid DC and subsonic noise
            min_bin = 3
            if spectrum.size <= min_bin:
                await asyncio.sleep(0.02)
                continue
            spectrum = spectrum[min_bin:]

            # Resample spectrum into fixed number of bands on a logarithmic frequency scale
            num_bands = 64
            freqs = np.fft.rfftfreq(audio_data.size, d=1.0 / rate)[min_bin:]
            if freqs.size == 0:
                await asyncio.sleep(0.02)
                continue

            # Guard against zeros when taking logarithms
            freqs = np.maximum(freqs, 1e-6)
            min_freq = freqs[0]
            max_freq = freqs[-1]
            if min_freq >= max_freq:
                await asyncio.sleep(0.02)
                continue

            log_freqs = np.log(freqs)
            target_freqs = np.logspace(np.log10(min_freq), np.log10(max_freq), num_bands)
            target_log_freqs = np.log(target_freqs)
            bands = np.interp(target_log_freqs, log_freqs, spectrum)

            # Normalize to 0..100, clamp, convert to ints
            # Use a soft max to keep responsiveness
            max_magnitude = 20000.0
            normalized_bands = [int(max(0, min(100, (b / max_magnitude) * 100))) for b in bands]

            await websocket.send(json.dumps(normalized_bands))
            await asyncio.sleep(0.02) # Faster updates for more responsive bars

    except Exception as exc:
        try:
            import websockets

            if isinstance(exc, websockets.exceptions.ConnectionClosed):
                print("Client disconnected.")
                return
        except Exception:
            pass
        raise
    finally:
        try:
            proc.kill()
        except Exception:
            pass

async def main():
    """Starts the WebSocket server."""
    parser = argparse.ArgumentParser(description="Audio spectrum WebSocket server")
    parser.add_argument(
        "--backend",
        default=os.getenv("AUDIO_BACKEND", os.getenv("BACKEND", BACKEND_AUTO)),
        choices=list(SUPPORTED_BACKENDS),
        help="Capture backend (default: auto)",
    )
    parser.add_argument(
        "--device",
        help=(
            "System-audio input device/source. "
            "macOS(avfoundation): loopback input name/index (e.g. 'BlackHole 2ch'); "
            "Linux(pulse): monitor source (e.g. '...monitor' or 'default'); "
            "Windows(dshow): loopback capture device (e.g. 'Stereo Mix', 'CABLE Output')."
        ),
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available devices/sources for the selected backend and exit",
    )
    parser.add_argument(
        "--rate",
        default=int(os.getenv("AUDIO_RATE", str(DEFAULT_RATE))),
        type=int,
        help=f"Sample rate (default: {DEFAULT_RATE})",
    )
    parser.add_argument(
        "--channels",
        default=int(os.getenv("AUDIO_CHANNELS", str(DEFAULT_CHANNELS))),
        type=int,
        help=f"Output channels from ffmpeg (default: {DEFAULT_CHANNELS})",
    )
    parser.add_argument('--host', default='localhost', help='WebSocket host (default: localhost)')
    parser.add_argument('--port', default=8765, type=int, help='WebSocket port (default: 8765)')
    parser.add_argument(
        "--port-retries",
        default=int(os.getenv("AUDIO_PORT_RETRIES", "50")),
        type=int,
        help="Number of fallback ports to try when the selected port is busy (default: 50)",
    )
    args = parser.parse_args()

    if args.list_devices:
        backend = resolve_backend(args.backend)
        print(f"backend: {backend}")
        if backend == BACKEND_AVFOUNDATION:
            devices = list_avfoundation_audio_devices()
            if not devices:
                text = avfoundation_list_devices_output()
                if "Input/output error" in text or "Error opening input" in text:
                    print(
                        "Unable to enumerate avfoundation devices. "
                        "On macOS this often means ffmpeg doesn't have Microphone permission."
                    )
                    print("Fix: System Settings → Privacy & Security → Microphone → enable for Terminal/Python.")
                else:
                    print("No avfoundation audio devices found (is ffmpeg installed with avfoundation support?).")
                return
            print("avfoundation audio devices (pick a loopback input like BlackHole):")
            for idx, name in devices:
                print(f"  [{idx}] {name}")
        elif backend == BACKEND_PULSE:
            sources = list_pulse_sources()
            if not sources:
                print("No PulseAudio sources found (is 'pactl' installed and audio running?).")
                return
            default_monitor = get_default_pulse_monitor_source()
            print("pulse sources (use a '*.monitor' source for system output):")
            for name in sources:
                tag = " (default monitor)" if default_monitor and name == default_monitor else ""
                print(f"  {name}{tag}")
        elif backend == BACKEND_DSHOW:
            devices = list_dshow_audio_devices()
            if not devices:
                print("No DirectShow audio devices found (is ffmpeg installed?).")
                return
            print("DirectShow audio devices (need a loopback capture device for system audio):")
            for name in devices:
                print(f'  {name}')
            print('Tip: look for "Stereo Mix" or install a virtual cable (VB-CABLE) and use its output device.')
        else:
            print(f"Unknown backend: {backend}")
        return

    try:
        import websockets
    except ModuleNotFoundError:
        print('Missing dependency "websockets". Install with: python3 -m pip install -r requirements.txt')
        return

    async def handler(ws):
        await audio_processor(
            ws,
            device=args.device,
            backend=args.backend,
            rate=args.rate,
            channels=args.channels,
        )

    retries = max(args.port_retries, 0)
    bound_port = args.port
    server = None
    for attempt in range(retries + 1):
        candidate_port = args.port + attempt
        try:
            server = await websockets.serve(handler, args.host, candidate_port)
            bound_port = candidate_port
            if attempt > 0:
                print(f"Port {args.port} is busy; using ws://{args.host}:{bound_port} instead.")
            break
        except OSError as exc:
            if not is_address_in_use_error(exc) or attempt >= retries:
                raise

    if server is None:
        return

    try:
        backend = resolve_backend(args.backend)
        resolved = resolve_system_audio_device(
            backend,
            args.device or os.getenv("AUDIO_DEVICE") or os.getenv("DEVICE"),
        )
        print(
            "WebSocket server started at "
            f"ws://{args.host}:{bound_port} "
            f"(backend={backend}, device={args.device or os.getenv('AUDIO_DEVICE') or os.getenv('DEVICE') or 'default'} -> {resolved}, "
            f"rate={args.rate}, channels={args.channels})"
        )
        await asyncio.Future()  # Run forever
    finally:
        server.close()
        await server.wait_closed()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Server stopped.")
