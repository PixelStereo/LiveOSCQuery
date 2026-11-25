# OSCQueryRemote

A Python control script (Remote Script) for Ableton Live that exposes the set over OSC with OSCQuery discovery. An OSCQuery client finds the set automatically, reads the tree as JSON, listens for changes over WebSocket (`LISTEN`), and writes via OSC/UDP.

Working name. Written from Live's object model, with nothing taken from AbletonOSC (uses different ports so both can run together).

## Installation

Copy the `OSCQueryRemote/` folder into `~/Music/Ableton/User Library/Remote Scripts/`, restart Live, and go to **Settings > Link, Tempo & MIDI > Control Surface > `OSCQueryRemote`**. Live's log file (`Log.txt`) reports the ports.

- **OSCQuery HTTP + WebSocket:** TCP 9101 (the OS picks another if busy; `HOST_INFO` reports it)
- **Incoming OSC:** UDP 9100
- **Bonjour announcement** (`_oscjson._tcp`) via `dns-sd` (macOS, Windows with Bonjour) or `avahi-publish-service` (Linux). Without either one, there is no announcement—enter the address manually.

## Tree (index-based paths, name is a value)

| Path | Contents |
|---|---|
| `/transport/` | play, stop, continue, stop_all_clips, record, session_record, overdub, loop, metronome, tempo, position, signature_*, tap_tempo, undo, redo |
| `/tracks/N/` | name, volume, pan, mute, solo, arm (if armable), stop, `sends/K`, `devices/M/parameters/K`, `clips/S/{fire,stop,has_clip,playing,triggered,name,color,looping,length}` |
| `/returns/N/` | name, volume, pan, mute, solo, devices |
| `/master/` | volume, pan, cue_volume, devices |
| `/scenes/S/` | name, color, fire |
| `/view/` | selected_track, selected_scene, `selected_device/parameters/K` (macros of the selected device) |

Types: `f` float, `i` integer, `T` boolean, `s` string, `I` trigger (send the message with no arguments). `RANGE` comes from the parameter's `min`/`max` (volume 0..1, pan -1..1, tempo 20..999). Device parameters use their raw value.

## How It Works

- **Single thread:** Everything is called from `update_display()` (roughly every 100 ms) because Live's API can only be used on its main thread. Command latency is on the order of a tick.
- **No Live listeners:** Values are read on demand and polled every tick for clients using `LISTEN`. No listeners to clean up.
- **Dynamic tree updates:** The tree is rebuilt (roughly every 0.5 s if the signature changes: tracks, scenes, devices, selected device) and clients receive `PATH_ADDED` / `PATH_REMOVED`.
- **Origin check:** WebSocket connections are rejected if the `Origin` header is not local (arbitrary web pages cannot control Live).
- **No authentication:** Use on a trusted network.

## Tests

```bash
python3 -I tests/test_all.py
```

Uses a mock Live (`tests/mock_live.py`) and real sockets: HTTP, attributes, UDP writes, WebSocket `LISTEN`/`IGNORE`, `PATH_REMOVED`, OSC over WebSocket, and `Origin` rejection.

## Not Yet Done / Unverified

- No output meters, no MIDI/automation, and no expandable group tracks.
- **Bonjour announcement:** A pure-Python mDNS responder would be needed for Windows without Bonjour.
- Colors are RGB integers (`i`), not yet `r`.
- **Index shifts:** Deleting a track shifts subsequent paths (the trade-off of index-based paths).
