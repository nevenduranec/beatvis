# Audio Levels (System Audio Visualizer)

Browser-based audio spectrum visualizer driven by a small Python WebSocket server.

This project visualizes **system audio output** (not microphone input). Capturing system output requires a loopback setup that varies by OS.

## Requirements

- Python 3.9+
- `ffmpeg` in your `PATH`
- Python deps: `numpy`, `websockets` (`pip install -r requirements.txt`)

### OS-specific requirements (system audio output capture)

Because this visualizes **system output** (not mic input), you need an OS-appropriate loopback source:

- **macOS (`avfoundation`)**: a loopback audio driver such as BlackHole (or similar) and routing system audio through it.
  - If device listing shows an I/O error, macOS may require **Microphone permission** for Terminal/Python to enumerate/capture audio devices.
- **Linux (`pulse`)**: PulseAudio or PipeWire with the PulseAudio compatibility layer, plus `pactl`.
  - You’ll typically capture from a sink monitor source ending in `.monitor`.
- **Windows (`dshow`)**: a loopback capture device such as **Stereo Mix** (if your driver provides it) or a virtual cable (VB-CABLE/Voicemeeter, etc.).
  - Without a loopback capture device, FFmpeg/DirectShow can’t capture “system output”.

## Quick start (macOS/Linux)

```sh
make venv
make devices
make start
```

The UI opens at `http://localhost:8000/index.html` and connects to `ws://localhost:8765`.

## Quick start (Windows)

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
python visualizer.py --backend dshow --list-devices
python serve.py
```

## Choosing a capture backend/device

The server supports three capture backends:

- `avfoundation` (macOS): capture from a loopback input device (e.g. BlackHole)
- `pulse` (Linux): capture from a PulseAudio/PipeWire monitor source (`*.monitor`)
- `dshow` (Windows): capture from a loopback capture device (Stereo Mix / VB-CABLE / similar)

List devices for the selected backend:

```sh
python3 visualizer.py --backend auto --list-devices
```

Start with explicit backend/device:

```sh
python3 serve.py
# or:
python3 visualizer.py --backend pulse --device "<source>" --rate 48000 --channels 2
```

### macOS (system audio)

Install a loopback device such as BlackHole, then route system output through it.
Use `make devices` to find the BlackHole input name and start with:

```sh
BACKEND=avfoundation DEVICE="BlackHole 2ch" make start
```

If you want to both **hear audio normally** and capture it, you may need to route audio to both your speakers/headphones and the loopback device (e.g. via an Aggregate/Multi-Output setup or app-specific output routing).

### Linux (system audio)

The default is the monitor source for your default sink (via `pactl`).

```sh
BACKEND=pulse DEVICE=default make start
```

If auto-detection fails, run `make devices BACKEND=pulse` and pick a `*.monitor` source.

### Windows (system audio)

FFmpeg cannot directly capture system audio output on Windows without a loopback capture device.

Options:
- Enable **Stereo Mix** (if your audio driver provides it), or
- Install a virtual cable (e.g. VB-CABLE / Voicemeeter) and capture its output endpoint.

Then list devices and start with the one that represents loopback/system audio:

```bat
python visualizer.py --backend dshow --list-devices
python serve.py
```

You can set environment variables before running:

- `AUDIO_BACKEND` / `BACKEND` (e.g. `dshow`, `pulse`, `avfoundation`)
- `AUDIO_DEVICE` / `DEVICE` (device/source name)
- `AUDIO_RATE` (e.g. `48000`)
- `AUDIO_CHANNELS` (e.g. `2`)

## License

MIT. See `LICENSE`.
