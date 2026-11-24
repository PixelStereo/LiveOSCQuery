"""Announces the OSCQuery service (_oscjson._tcp) so clients find it by themselves.

Live's Python has no zeroconf, so this lets the system's own responder do it: dns-sd on macOS (and Windows
with Bonjour installed), avahi on Linux. When none is there the script still works: type the address by hand.
"""
import shutil
import subprocess
import sys


class Advertiser(object):
    def __init__(self, name, port, log=None):
        self.name, self.port = name, port
        self.log = log or (lambda m: None)
        self.proc = None

    def start(self):
        if sys.platform == "darwin" or sys.platform.startswith("win"):
            exe = shutil.which("dns-sd")
            cmd = [exe, "-R", self.name, "_oscjson._tcp", ".", str(self.port)] if exe else None
        else:
            exe = shutil.which("avahi-publish-service")
            cmd = [exe, self.name, "_oscjson._tcp", str(self.port)] if exe else None
        if not cmd:
            self.log("no Bonjour/avahi tool found: not advertised, connect by address")
            return False
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            return True
        except Exception as e:
            self.log("advertising failed: %r" % (e,))
            return False

    def stop(self):
        p, self.proc = self.proc, None
        if p is not None:
            try:
                p.terminate()
                p.wait(timeout=2)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
