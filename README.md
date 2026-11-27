# OSCQueryRemote

A Python control script (Remote Script) for Ableton Live that exposes the set over OSC with OSCQuery discovery. An OSCQuery client finds the set automatically, reads the tree as JSON, listens for changes over WebSocket (`LISTEN`), and writes via OSC/UDP.

Working name. Written from Live's object model, with nothing taken from AbletonOSC (uses different ports so both can run together).

## Installation

Copy the `OSCQueryRemote/` folder into `~/Music/Ableton/User Library/Remote Scripts/`, restart Live, and go to **Settings > Link, Tempo & MIDI > Control Surface > `OSCQueryRemote`**. Live's log file (`Log.txt`) reports the ports.

- **OSCQuery HTTP + WebSocket:** TCP 9101 (the OS picks another if busy; `HOST_INFO` reports it)
- **Incoming OSC:** UDP 9100
- **Bonjour announcement** (`_oscjson._tcp`) via `dns-sd` (macOS, Windows with Bonjour) or `avahi-publish-service` (Linux). If the command is missing or exits, the script tries `zeroconf` if it is importable in Live’s Python environment and the hostname resolves to a LAN IPv4 address. When discovery is unavailable, enter the address manually.

## Tree

| Path | Contents |
|---|---|
| `/transport/` | play, stop, continue, stop_all_clips, record, session_record, overdub, loop, metronome, tempo, position, signature_*, tap_tempo, undo, redo |
| `/tracks/N/` | name, volume, pan, mute, solo, arm (if armable), stop, `sends/K`, `devices/M/parameters/K`, `clips/S/{fire,stop,has_clip,playing,triggered,name,color,looping,length}` |
| `/tracks_by_id/ID/` | Same controls as `/tracks/N/`, addressed by a session-local track ID |
| `/returns/N/` | name, volume, pan, mute, solo, devices |
| `/master/` | volume, pan, cue_volume, devices |
| `/scenes/S/` | name, color, fire |
| `/view/` | selected_track, selected_scene, `selected_device/parameters/K` (macros of the selected device) |

Types: `f` float, `i` integer, `T` boolean, `s` string, `r` RGBA color, `N` momentary action (the server accepts a message with zero arguments, `N` or `I`). `RANGE` comes from the parameter's `min`/`max` (volume 0..1, pan -1..1, tempo 20..999). Device parameters use their raw value.

- Audio outputs expose `output_meter_left` and `output_meter_right`. Compatible tracks, returns and the master also expose `output_meter`, a peak held for one second.
- Group tracks expose a writable `folded` switch. Each child track reports its parent's session-local ID in `group_id`.
- In `/tracks_by_id/`, tracks keep their IDs until the Remote Script is restarted. Their paths survive renames, moves and deletion of other tracks. The `/tracks/` namespace and scene, clip and device indices follow their order in Live.
- `color` is advertised as OSC `r` and represented in JSON as `#RRGGBBAA`. Live stores RGB, so reads return alpha `FF` and writes apply only RGB. The `color_rgb` node exposes the RGB integer.
- On MIDI tracks, write a positive length in beats to an empty slot's `create_midi_clip` node. `is_midi_clip` identifies MIDI clips.
- `devices/M/automation_state/K` reports the automation state of parameter K (0 absent, 1 active, 2 overridden). Where Live exposes it, `/transport/re_enable_automation` re-enables automation.

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

With the pxs-core checkout beside this repository, the shared wire-format and OSCQuery compatibility tests run with Python alone.

```sh
python3 -I tests/test_compatibility.py ../pxs-core/test/golden/vectors.tsv
```

## Remaining validation

- Verify the new controls in Live 11 and Live 12 and mDNS discovery on Windows without Bonjour.
- MIDI note editing, raw MIDI and automation envelope editing remain to be implemented.
