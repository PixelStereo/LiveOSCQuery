"""Announces the OSCQuery service (_oscjson._tcp) so clients find it by themselves.

Prefer the system responder. If the command is unavailable, use python-zeroconf
when it is installed in Live’s Python environment.
"""
import ipaddress
import re
import shutil
import socket
import subprocess
import sys


class Advertiser(object):
    def __init__(self, name, port, log=None):
        self.name, self.port = name, port
        self.log = log or (lambda m: None)
        self.proc = None
        self.zeroconf = None

    def start(self):
        if sys.platform == "darwin" or sys.platform.startswith("win"):
            exe = shutil.which("dns-sd")
            cmd = [exe, "-R", self.name, "_oscjson._tcp", ".", str(self.port)] if exe else None
        else:
            exe = shutil.which("avahi-publish-service")
            cmd = [exe, self.name, "_oscjson._tcp", str(self.port)] if exe else None
        if cmd:
            try:
                self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
                return True
            except OSError as e:
                self.log("system advertising failed: %r" % (e,))
        return self._start_zeroconf()

    def _start_zeroconf(self):
        try:
            from zeroconf import ServiceInfo, Zeroconf

            service_type = "_oscjson._tcp.local."
            addresses = set()
            hostname = socket.gethostname()
            for _, _, _, _, address in socket.getaddrinfo(hostname, None, socket.AF_INET):
                ip = ipaddress.IPv4Address(address[0])
                if not (ip.is_loopback or ip.is_unspecified or ip.is_multicast):
                    addresses.add(ip.packed)
            if not addresses:
                raise OSError("no LAN IPv4 address found")
            label = re.sub(r"[^a-zA-Z0-9-]", "-", hostname.split(".")[0])[:63].strip("-") or "live"
            service = ServiceInfo(service_type, "%s.%s" % (self.name, service_type),
                                  addresses=sorted(addresses), port=self.port, server=label + ".local.")
            self.zeroconf = Zeroconf()
            self.zeroconf.register_service(service, allow_name_change=True)
            return True
        except Exception as e:
            self.stop()
            self.log("mDNS unavailable (%r): connect by address" % (e,))
            return False

    def poll(self):
        if self.proc is not None and self.proc.poll() is not None:
            self.proc = None
            self._start_zeroconf()

    def stop(self):
        if self.zeroconf is not None:
            responder, self.zeroconf = self.zeroconf, None
            try:
                responder.close()
            except Exception as e:
                self.log("mDNS cleanup failed: %r" % (e,))
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
