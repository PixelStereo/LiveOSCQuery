"""A small stand-in for Live's object model, enough to build the tree."""


class Param(object):
    def __init__(self, name, value=0.5, lo=0.0, hi=1.0, quantized=False):
        self.name, self.value, self.min, self.max, self.is_quantized = name, value, lo, hi, quantized


class Device(object):
    def __init__(self, name, n=4):
        self.name, self.class_name = name, name
        self.parameters = [Param("Device On", 1.0, 0, 1, True)] + [Param("P%d" % i) for i in range(n)]


class Mixer(object):
    def __init__(self, sends=2):
        self.volume, self.panning, self.cue_volume = Param("Volume", 0.85), Param("Pan", 0.0, -1, 1), Param("Cue", 0.85)
        self.sends = [Param("Send %d" % i, 0.0) for i in range(sends)]


class Clip(object):
    def __init__(self):
        self.name, self.color, self.looping, self.length = "clip", 0xFF0000, True, 4.0


class Slot(object):
    def __init__(self, clip=False):
        self.clip = Clip() if clip else None
        self.is_playing = self.is_triggered = False
        self.fired = 0

    @property
    def has_clip(self):
        return self.clip is not None

    def fire(self):
        self.fired += 1
        self.is_playing = True

    def stop(self):
        self.is_playing = False


class View(object):
    def __init__(self):
        self.selected_device = None


class Track(object):
    def __init__(self, name, scenes=3, sends=2, arm=True):
        self.name, self.mute, self.solo, self.arm, self.can_be_armed = name, False, False, False, arm
        self.mixer_device = Mixer(sends)
        self.devices = [Device("EQ")]
        self.clip_slots = [Slot(i % 2 == 0) for i in range(scenes)]
        self.view = View()
        self.stopped = 0

    def stop_all_clips(self):
        self.stopped += 1


class Scene(object):
    def __init__(self, name):
        self.name, self.color, self.fired = name, 0, 0

    def fire(self):
        self.fired += 1


class SongView(object):
    pass


class Song(object):
    def __init__(self, tracks=3, scenes=3):
        self.is_playing = False
        self.record_mode = self.session_record = self.arrangement_overdub = self.loop = self.metronome = False
        self.tempo, self.current_song_time = 120.0, 0.0
        self.signature_numerator, self.signature_denominator = 4, 4
        self.tracks = [Track("T%d" % i, scenes) for i in range(tracks)]
        self.return_tracks = [Track("R0", scenes, sends=0, arm=False)]
        self.master_track = Track("Master", 0, 0, False)
        self.scenes = [Scene("S%d" % i) for i in range(scenes)]
        self.view = SongView()
        self.view.selected_track = self.tracks[0]
        self.view.selected_scene = self.scenes[0]
        self.tracks[0].view.selected_device = self.tracks[0].devices[0]
        self.calls = []

    def start_playing(self): self.is_playing = True
    def stop_playing(self): self.is_playing = False
    def continue_playing(self): self.calls.append("continue")
    def stop_all_clips(self): self.calls.append("stop_all")
    def tap_tempo(self): self.calls.append("tap")
    def undo(self): self.calls.append("undo")
    def redo(self): self.calls.append("redo")
