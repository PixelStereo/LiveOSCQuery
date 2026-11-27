"""OSCQuery remote script: exposes the whole Live set over OSC with OSCQuery discovery.

Install: copy this folder into  <User Library>/Remote Scripts/  and pick it in Live's Link/Tempo/MIDI preferences.
"""
import socket

try:
    from _Framework.ControlSurface import ControlSurface
except ImportError:  # outside Live (tests)
    ControlSurface = None

DEFAULT_OSC_PORT = 9100
DEFAULT_HTTP_PORT = 9101
STRUCTURE_CHECK_EVERY = 5  # ticks (about 0.5 s)

if ControlSurface is not None:
    from . import live_model
    from .mdns import Advertiser
    from .server import Server
    from .tree import Tree

    class OSCQueryRemote(ControlSurface):
        def __init__(self, c_instance):
            ControlSurface.__init__(self, c_instance)
            self._ticks = 0
            self._track_ids = live_model.TrackIds()
            self._signature = None
            self._device = None
            self._server = None
            self._advertiser = None
            with self.component_guard():
                try:
                    host = socket.gethostname().split(".")[0]
                    self._server = Server(Tree(), "Live %s" % host, DEFAULT_OSC_PORT, DEFAULT_HTTP_PORT, self.log_message)
                    self._rebuild()
                    self._advertiser = Advertiser("Live %s" % host, self._server.http_port, self.log_message)
                    self._advertiser.start()
                    self.log_message("OSCQuery: HTTP %d, OSC %d" % (self._server.http_port, self._server.osc_port))
                    self.show_message("OSCQuery: http port %d" % self._server.http_port)
                except Exception as e:
                    self.log_message("OSCQuery failed to start: %r" % (e,))

        def _rebuild(self):
            song = self.song()
            signature = live_model.signature(song)
            device = live_model.selected_device(song)
            self._server.set_tree(live_model.build(song, self._track_ids))
            self._signature = signature
            self._device = device

        def update_display(self):
            ControlSurface.update_display(self)
            if self._server is None:
                return
            try:
                self._ticks += 1
                if self._ticks % STRUCTURE_CHECK_EVERY == 0:
                    if self._advertiser is not None:
                        self._advertiser.poll()
                    song = self.song()
                    if live_model.signature(song) != self._signature or live_model.selected_device(song) != self._device:
                        self._rebuild()
                self._server.poll()
            except Exception as e:
                self.log_message("OSCQuery tick failed: %r" % (e,))

        def disconnect(self):
            if self._advertiser is not None:
                self._advertiser.stop()
            if self._server is not None:
                self._server.close()
            ControlSurface.disconnect(self)

    def create_instance(c_instance):
        return OSCQueryRemote(c_instance)
