import base64, json, os, socket, struct, sys, time, unittest, urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from OSCQueryRemote import osc, live_model
from OSCQueryRemote.server import Server
import mock_live


class Rig(object):
    def __init__(self):
        self.song = mock_live.Song()
        self.server = Server(live_model.build(self.song), "test", 0, 0)
        self.base = "http://127.0.0.1:%d" % self.server.http_port

    def pump(self, n=20):
        for _ in range(n):
            self.server.poll()
            time.sleep(0.005)

    def get(self, path):
        import threading
        out = {}

        def run():
            try:
                r = urllib.request.urlopen(self.base + path, timeout=5)
                out["status"], out["body"] = r.status, r.read()
            except urllib.error.HTTPError as e:
                out["status"], out["body"] = e.code, b""
        t = threading.Thread(target=run); t.start()
        while t.is_alive():
            self.server.poll(); time.sleep(0.002)
        return out["status"], (json.loads(out["body"]) if out["body"] else None)

    def udp(self, address, *args):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(osc.encode_message(address, args), ("127.0.0.1", self.server.osc_port))
        s.close(); self.pump()


class WS(object):
    def __init__(self, rig):
        self.rig = rig
        self.s = socket.create_connection(("127.0.0.1", rig.server.http_port))
        key = base64.b64encode(b"0123456789abcdef").decode()
        self.s.sendall(("GET / HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % key).encode())
        rig.pump(); self.s.settimeout(0.2)
        self.buf = self.s.recv(4096)
        assert b"101" in self.buf and b"Sec-WebSocket-Accept" in self.buf
        self.buf = self.buf.split(b"\r\n\r\n", 1)[1]

    def send_text(self, obj):
        p = json.dumps(obj).encode(); mask = b"abcd"
        self.s.sendall(struct.pack(">BB", 0x81, 0x80 | len(p)) + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(p)))
        self.rig.pump()

    def frames(self):
        self.rig.pump()
        try:
            self.buf += self.s.recv(65536)
        except socket.timeout:
            pass
        out = []
        while len(self.buf) >= 2:
            op, n = self.buf[0] & 15, self.buf[1] & 127
            if len(self.buf) < 2 + n: break
            out.append((op, self.buf[2:2 + n])); self.buf = self.buf[2 + n:]
        return out


class Tests(unittest.TestCase):
    def setUp(self): self.rig = Rig()
    def tearDown(self): self.rig.server.close()

    def test_host_info(self):
        st, o = self.rig.get("/?HOST_INFO")
        self.assertEqual(st, 200); self.assertEqual(o["OSC_PORT"], self.rig.server.osc_port); self.assertTrue(o["EXTENSIONS"]["LISTEN"])

    def test_tree(self):
        st, o = self.rig.get("/")
        self.assertEqual(o["FULL_PATH"], "/")
        t0 = o["CONTENTS"]["tracks"]["CONTENTS"]["0"]["CONTENTS"]
        self.assertEqual(t0["volume"]["TYPE"], "f"); self.assertEqual(t0["volume"]["VALUE"], [0.85]); self.assertEqual(t0["volume"]["ACCESS"], 3)
        self.assertEqual(t0["pan"]["RANGE"], [{"MIN": -1.0, "MAX": 1.0}])
        self.assertEqual(t0["mute"]["TYPE"], "T"); self.assertEqual(t0["mute"]["VALUE"], [False])
        self.assertEqual(t0["clips"]["CONTENTS"]["0"]["CONTENTS"]["fire"]["ACCESS"], 2)
        self.assertNotIn("arm", o["CONTENTS"]["returns"]["CONTENTS"]["0"]["CONTENTS"])
        self.assertIn("selected_device", o["CONTENTS"]["view"]["CONTENTS"])
        self.assertEqual(self.rig.get("/tracks/0/volume?VALUE")[1], {"VALUE": [0.85]})
        self.assertEqual(self.rig.get("/nope")[0], 404)
        self.assertEqual(self.rig.get("/tracks/0/volume?BOGUS")[0], 204)

    def test_udp_writes(self):
        r = self.rig; s = r.song
        r.udp("/tracks/1/volume", 0.3); self.assertAlmostEqual(s.tracks[1].mixer_device.volume.value, 0.3, 5)
        r.udp("/tracks/1/volume", 7.0); self.assertEqual(s.tracks[1].mixer_device.volume.value, 1.0)  # clamped
        r.udp("/tracks/1/pan", -0.5); self.assertAlmostEqual(s.tracks[1].mixer_device.panning.value, -0.5, 5)
        r.udp("/tracks/1/mute", True); self.assertTrue(s.tracks[1].mute)
        r.udp("/tracks/1/mute", 0); self.assertFalse(s.tracks[1].mute)
        r.udp("/transport/play", True); self.assertTrue(s.is_playing)
        r.udp("/transport/play", False); self.assertFalse(s.is_playing)
        r.udp("/transport/tempo", 140.0); self.assertEqual(s.tempo, 140.0)
        r.udp("/tracks/2/clips/0/fire"); self.assertEqual(s.tracks[2].clip_slots[0].fired, 1)
        r.udp("/scenes/1/fire"); self.assertEqual(s.scenes[1].fired, 1)
        r.udp("/tracks/0/stop"); self.assertEqual(s.tracks[0].stopped, 1)
        r.udp("/view/selected_track", 2); self.assertIs(s.view.selected_track, s.tracks[2])
        r.udp("/tracks/0/devices/0/parameters/1", 0.9); self.assertAlmostEqual(s.tracks[0].devices[0].parameters[1].value, 0.9, 5)
        r.udp("/tracks/0/name", "Bass"); self.assertEqual(s.tracks[0].name, "Bass")
        r.udp("/no/such", 1)  # ignored

    def test_ws_listen_and_notifications(self):
        r = self.rig; ws = WS(r)
        ws.send_text({"COMMAND": "LISTEN", "DATA": "/tracks/0/volume"})
        ws.send_text({"COMMAND": "LISTEN", "DATA": "/transport/play"})
        self.assertEqual(ws.frames(), [])
        r.song.tracks[0].mixer_device.volume.value = 0.4
        r.song.is_playing = True
        got = dict((a, args) for op, p in ws.frames() if op == 2 for a, args in osc.decode(p))
        self.assertAlmostEqual(got["/tracks/0/volume"][0], 0.4, 5); self.assertEqual(got["/transport/play"], [True])
        self.assertEqual(ws.frames(), [])  # no repeat
        ws.send_text({"COMMAND": "IGNORE", "DATA": "/tracks/0/volume"})
        r.song.tracks[0].mixer_device.volume.value = 0.1
        self.assertEqual([f for f in ws.frames() if f[0] == 2], [])
        # structure change: a track goes away
        r.song.tracks.pop()
        self.assertNotEqual(live_model.signature(r.song), None)
        r.server.set_tree(live_model.build(r.song))
        cmds = [json.loads(p) for op, p in ws.frames() if op == 1]
        self.assertIn({"COMMAND": "PATH_REMOVED", "DATA": "/tracks/2"}, cmds)

    def test_ws_osc_write(self):
        ws = WS(self.rig); p = osc.encode_message("/tracks/0/volume", [0.2]); mask = b"wxyz"
        ws.s.sendall(struct.pack(">BB", 0x82, 0x80 | len(p)) + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(p)))
        self.rig.pump(); self.assertAlmostEqual(self.rig.song.tracks[0].mixer_device.volume.value, 0.2, 5)

    def test_origin_refused(self):
        s = socket.create_connection(("127.0.0.1", self.rig.server.http_port))
        s.sendall(b"GET / HTTP/1.1\r\nHost: x\r\nOrigin: http://evil.example\r\nUpgrade: websocket\r\nSec-WebSocket-Key: abc\r\n\r\n")
        self.rig.pump(); s.settimeout(0.5); self.assertIn(b"403", s.recv(100))

    def test_osc_codec(self):
        m = osc.encode_message("/a/b", [1, 2.5, "hi", True])
        self.assertEqual(osc.decode(m), [("/a/b", [1, 2.5, "hi", True])])
        b = b"#bundle\0" + b"\0" * 8 + struct.pack(">i", len(m)) + m
        self.assertEqual(len(osc.decode(b)), 1)
        self.assertEqual(osc.decode(b"garbage"), [])


if __name__ == "__main__":
    unittest.main()
