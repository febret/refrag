# Refrag - Web-based multi-user Caustic Sound Studio

Refrag is a collaborative, rack-based virtual DAW inspired by Caustic 3.1. Sound
is synthesized on the Python server and streamed to every browser in a shared
room. Machine controls, patterns, transport, mixer state, effects, and
automation are synchronized over WebSockets and persisted as room snapshots.

Refrag includes all 11 Caustic sound-machine families, all 16 insert effects,
a 14-machine rack, two effects slots per channel, mixer, master section,
pattern/song sequencer, automation capture, 70 factory starter presets,
preset storage, and server-side WAV export.

## Quick start

Python 3.11 or newer is recommended.

```sh
python -m pip install -r requirements.txt
./start.sh
```

On Windows:

```bat
python -m pip install -r requirements.txt
start.bat
```

Open `https://localhost:8000`. To choose a collaborative room, use
`https://localhost:8000/?room=your-room`. Share that URL with other musicians.
Set `REFRAG_PORT` before launching to use a port other than 8000.

Refrag always uses HTTPS. On first launch it creates a self-signed certificate
and key under `data/tls/`. Before opening Refrag, trust
`data/tls/refrag-cert.pem` on each computer, phone, or tablet; this is required
for browsers to enable microphone and AudioWorklet features without a security
warning. The public certificate can also be downloaded from
`https://<server-address>:8000/refrag-cert.pem` after initially accepting the
browser warning.

To replace the generated certificate with a trusted or CA-issued certificate,
set its PEM certificate and private-key paths:

```sh
export REFRAG_SSL_CERT=/path/to/cert.pem
export REFRAG_SSL_KEY=/path/to/key.pem
./start.sh
```

On Windows PowerShell:

```powershell
$env:REFRAG_SSL_CERT = "C:\path\to\cert.pem"
$env:REFRAG_SSL_KEY = "C:\path\to\key.pem"
.\start.bat
```

Both variables are required. If the server has additional DNS names or IP
addresses that automatic discovery misses, set a comma-separated
`REFRAG_SSL_HOSTS` value before the first launch, then delete `data/tls/` and
restart to regenerate the self-signed certificate.

## Architecture

- `server/app.py` serves the web app, room API, WebSocket, transport clock, and
  WAV export.
- `server/state.py` owns collaborative room state and JSON persistence.
- `server/synth.py` renders audio for all 11 machine families;
  `server/effects.py` implements the 16 insert effects and
  `server/engine.py` runs the sequencer, mixer and master chain.
- `server/catalog.py` defines the controls exposed by all rack devices.
- `server/samples.py` procedurally generates the factory drum kit,
  instrument samples and vocoder loops.
- `web/` contains the dependency-free browser client.

Room files are written to `data/sessions/` as they change.
See `doc/user-guide.md` for the full manual.

## Tests

```sh
python -m unittest discover -s tests -v
```
