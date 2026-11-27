"""Builds the OSCQuery tree from Live's object model (Live 11 and 12).

Paths are index based (/tracks/0/volume) and carry the name as a value, so a rename never moves a path.
Nothing here keeps a listener on Live: values are read when asked and polled for the clients that LISTEN.
"""
from .osc import RGBA
from .tree import Node, Tree


def _attr(obj, name, default=None):
    def get():
        return getattr(obj, name)
    return get


def _setter(obj, name):
    def set_(v):
        setattr(obj, name, v)
    return set_


def prop(parent, name, obj, attr, type, rng=None, rw=True, desc=None):
    return parent.add(Node(name, type, _attr(obj, attr), _setter(obj, attr) if rw else None, rng, desc))


def trigger(parent, name, fn, desc=None):
    return parent.add(Node(name, "N", None, lambda _v: fn(), None, desc))


def container(parent, name, desc=None):
    return parent.add(Node(name, description=desc))


def param(parent, name, p):
    """A DeviceParameter: its value is the raw one, RANGE says min and max."""
    try:
        lo, hi = float(p.min), float(p.max)
        quantized = bool(p.is_quantized)
    except Exception:
        lo, hi, quantized = 0.0, 1.0, False

    def get():
        return p.value

    def set_(v):
        p.value = float(v)

    def desc():
        try:
            return p.name
        except Exception:
            return ""

    n = parent.add(Node(name, "i" if quantized else "f", get, set_, (int(lo), int(hi)) if quantized else (lo, hi), desc))
    if quantized:
        n.get = lambda: int(round(p.value))
    return n


def _safe(fn, default):
    def get():
        try:
            return fn()
        except Exception:
            return default
    return get


def _device(parent, name, device):
    d = container(parent, name)
    d.add(Node("name", "s", _safe(lambda: device.name, ""), None))
    d.add(Node("class_name", "s", _safe(lambda: device.class_name, ""), None))
    params = container(d, "parameters")
    automation = container(d, "automation_state")
    for i, p in enumerate(device.parameters):
        param(params, str(i), p)
        prop(automation, str(i), p, "automation_state", "i", rw=False)
    return d


def _meter(parent, track):
    audio = getattr(track, "has_audio_output", False)
    if audio or getattr(track, "has_midi_output", False):
        prop(parent, "output_meter", track, "output_meter_level", "f", (0.0, 1.0), rw=False)
    if audio:
        for channel in ("output_meter_left", "output_meter_right"):
            prop(parent, channel, track, channel, "f", (0.0, 1.0), rw=False)


def _rgba(rgb):
    return RGBA((int(rgb) & 0xFFFFFF) << 8 | 0xFF)


def _mixer(parent, track, with_arm=False, with_sends=True):
    _meter(parent, track)
    m = track.mixer_device
    parent.add(Node("name", "s", _safe(lambda: track.name, ""), _setter(track, "name")))
    param(parent, "volume", m.volume)
    param(parent, "pan", m.panning)
    prop(parent, "mute", track, "mute", "T")
    prop(parent, "solo", track, "solo", "T")
    if with_arm and getattr(track, "can_be_armed", False):
        prop(parent, "arm", track, "arm", "T")
    if with_sends:
        sends = container(parent, "sends")
        for i, s in enumerate(m.sends):
            param(sends, str(i), s)
    devs = container(parent, "devices")
    for i, d in enumerate(track.devices):
        _device(devs, str(i), d)


def _slot(parent, name, slot, midi_track):
    s = container(parent, name)
    trigger(s, "fire", slot.fire)
    trigger(s, "stop", slot.stop)
    if midi_track and callable(getattr(slot, "create_clip", None)):
        def create_midi_clip(length):
            if not slot.has_clip and 0 < length < float("inf"):
                slot.create_clip(length)

        s.add(Node("create_midi_clip", "f", set=create_midi_clip, description="Length in beats"))
    s.add(Node("has_clip", "T", _safe(lambda: slot.has_clip, False), None))
    s.add(Node("playing", "T", _safe(lambda: bool(slot.is_playing), False), None))
    s.add(Node("triggered", "T", _safe(lambda: bool(slot.is_triggered), False), None))

    def clip_get(attr, default):
        return _safe(lambda: getattr(slot.clip, attr) if slot.has_clip else default, default)

    def clip_set(attr):
        def set_(v):
            if slot.has_clip:
                setattr(slot.clip, attr, v)
        return set_

    s.add(Node("name", "s", clip_get("name", ""), clip_set("name")))
    rgb = clip_get("color", 0)
    set_rgb = clip_set("color")
    s.add(Node("color", "r", lambda: _rgba(rgb()), lambda value: set_rgb(value >> 8)))
    s.add(Node("color_rgb", "i", rgb, set_rgb, (0, 0xFFFFFF)))
    s.add(Node("is_midi_clip", "T", clip_get("is_midi_clip", False), None))
    s.add(Node("looping", "T", clip_get("looping", False), clip_set("looping")))
    s.add(Node("length", "f", clip_get("length", 0.0), None))


def _index_of(items, obj):
    for i, o in enumerate(items):
        if o == obj:
            return i
    return -1


class TrackIds(object):
    """Allocates session-local IDs without depending on Live proxy hashing."""

    def __init__(self):
        self.entries = []
        self.next_id = 0

    def update(self, tracks):
        entries = []
        for track in tracks:
            previous = next((key for obj, key in self.entries if track == obj), None)
            if previous is None:
                previous = str(self.next_id)
                self.next_id += 1
            entries.append((track, previous))
        self.entries = entries
        return [key for _, key in entries]


def build(song, track_ids=None):
    tree = Tree()
    root = tree.root

    t = container(root, "transport", "Song transport")
    t.add(Node("play", "T", _safe(lambda: song.is_playing, False), lambda v: song.start_playing() if v else song.stop_playing()))
    trigger(t, "stop", song.stop_playing)
    trigger(t, "continue", song.continue_playing)
    trigger(t, "stop_all_clips", song.stop_all_clips)
    prop(t, "record", song, "record_mode", "T")
    prop(t, "session_record", song, "session_record", "T")
    prop(t, "overdub", song, "arrangement_overdub", "T")
    prop(t, "loop", song, "loop", "T")
    prop(t, "metronome", song, "metronome", "T")
    prop(t, "tempo", song, "tempo", "f", (20.0, 999.0))
    prop(t, "position", song, "current_song_time", "f", (0.0, 1e9), desc="Beats")
    prop(t, "signature_numerator", song, "signature_numerator", "i", (1, 99))
    prop(t, "signature_denominator", song, "signature_denominator", "i", (1, 16))
    trigger(t, "tap_tempo", song.tap_tempo)
    trigger(t, "undo", song.undo)
    trigger(t, "redo", song.redo)

    tracks = list(song.tracks)
    returns = list(song.return_tracks)
    scenes = list(song.scenes)

    tr = container(root, "tracks")
    ids = (track_ids if track_ids is not None else TrackIds()).update(tracks)
    stable = container(root, "tracks_by_id", "Track addresses stable during this session")
    for i, track in enumerate(tracks):
        group_index = _index_of(tracks, getattr(track, "group_track", None))
        midi_track = bool(getattr(track, "has_midi_input", False))
        group_id = ids[group_index] if group_index >= 0 else ""
        for branch, key in ((tr, str(i)), (stable, ids[i])):
            n = container(branch, key)
            _mixer(n, track, with_arm=True)
            n.add(Node("id", "s", lambda key=ids[i]: key))
            n.add(Node("group_id", "s", lambda key=group_id: key))
            if getattr(track, "is_foldable", False):
                prop(n, "folded", track, "fold_state", "T")
            trigger(n, "stop", track.stop_all_clips)
            clips = container(n, "clips")
            for j, slot in enumerate(track.clip_slots):
                _slot(clips, str(j), slot, midi_track)

    rt = container(root, "returns")
    for i, track in enumerate(returns):
        _mixer(container(rt, str(i)), track, with_sends=False)

    m = container(root, "master")
    mm = song.master_track
    _meter(m, mm)
    param(m, "volume", mm.mixer_device.volume)
    param(m, "pan", mm.mixer_device.panning)
    try:
        param(m, "cue_volume", mm.mixer_device.cue_volume)
    except Exception:
        pass
    devs = container(m, "devices")
    for i, d in enumerate(mm.devices):
        _device(devs, str(i), d)

    if callable(getattr(song, "re_enable_automation", None)):
        trigger(t, "re_enable_automation", song.re_enable_automation)

    sc = container(root, "scenes")
    for i, scene in enumerate(scenes):
        n = container(sc, str(i))
        n.add(Node("name", "s", _safe(lambda s=scene: s.name, ""), _setter(scene, "name")))
        n.add(Node("color", "r", lambda s=scene: _rgba(s.color)))
        prop(n, "color_rgb", scene, "color", "i", rw=False)
        trigger(n, "fire", scene.fire)

    v = container(root, "view", "What is selected in Live")

    def sel_track_get():
        return _index_of(tracks, song.view.selected_track)

    def sel_track_set(i):
        if 0 <= i < len(tracks):
            song.view.selected_track = tracks[i]

    def sel_scene_get():
        return _index_of(scenes, song.view.selected_scene)

    def sel_scene_set(i):
        if 0 <= i < len(scenes):
            song.view.selected_scene = scenes[i]

    v.add(Node("selected_track", "i", _safe(sel_track_get, -1), sel_track_set, (0, max(0, len(tracks) - 1)), "Index in /tracks, -1 when a return or the master"))
    v.add(Node("selected_scene", "i", _safe(sel_scene_get, -1), sel_scene_set, (0, max(0, len(scenes) - 1))))
    dev = selected_device(song)
    if dev is not None:
        _device(v, "selected_device", dev)
    return tree


def selected_device(song):
    try:
        return song.view.selected_track.view.selected_device
    except Exception:
        return None


def signature(song):
    """Keep Live object references so replacements with the same shape are detected."""
    def devs(track):
        return tuple((d, tuple(d.parameters)) for d in track.devices)

    def track_shape(track):
        return (track, getattr(track, "group_track", None),
                bool(getattr(track, "is_foldable", False)),
                bool(getattr(track, "can_be_armed", False)),
                bool(getattr(track, "has_midi_input", False)),
                bool(getattr(track, "has_audio_output", False)),
                bool(getattr(track, "has_midi_output", False)),
                tuple(track.mixer_device.sends), devs(track))

    return (
        tuple(song.scenes),
        tuple((track_shape(t), tuple(t.clip_slots)) for t in song.tracks),
        tuple(track_shape(t) for t in song.return_tracks),
        track_shape(song.master_track),
    )
