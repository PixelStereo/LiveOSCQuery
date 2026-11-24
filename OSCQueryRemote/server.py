"""OSCQuery server: HTTP (JSON), WebSocket (LISTEN/IGNORE) and UDP OSC, all polled from one thread.

Live's API may only be touched from its main thread, so there is no thread here: poll() is called from the
control surface's update_display() tick, with sockets in non-blocking mode.
"""
import base64
import hashlib
import json
import select
import socket
import struct
from urllib.parse import unquote

from . import osc
from .tree import describe, attribute

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
EXTENSIONS = {"ACCESS": True, "VALUE": True, "RANGE": True, "DESCRIPTION": True, "LISTEN": True,
              "PATH_ADDED": True, "PATH_REMOVED": True}


class _Conn(object):
    def __init__(self, sock, addr):
        self.sock, self.addr = sock, addr
        self.rbuf = b""
        self.wbuf = b""
        self.ws = False
        self.close_after = False
        self.listen = set()   # paths
        self.last = {}        # path -> last value sent


def _bind(kind, host, port):
    s = socket.socket(socket.AF_INET, kind)
    if kind == socket.SOCK_STREAM:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind((host, port))
    except OSError:
        s.bind((host, 0))  # busy: let the system choose, HOST_INFO tells the clients
    s.setblocking(False)
    return s


class Server(object):
    def __init__(self, tree, name, osc_port=9100, http_port=9101, log=None):
        self.tree = tree
        self.name = name
        self.log = log or (lambda m: None)
        self.udp = _bind(socket.SOCK_DGRAM, "0.0.0.0", osc_port)
        self.http = _bind(socket.SOCK_STREAM, "0.0.0.0", http_port)
        self.http.listen(16)
        self.osc_port = self.udp.getsockname()[1]
        self.http_port = self.http.getsockname()[1]
        self.conns = []

    # -- tree ------------------------------------------------------------------------------------------------
    def set_tree(self, tree):
        """Swaps the tree and tells the WebSocket clients which paths came and went."""
        old = self.tree.paths()
        self.tree = tree
        new = tree.paths()
        for kind, paths in (("PATH_REMOVED", old - new), ("PATH_ADDED", new - old)):
            # only the topmost path of each changed branch
            for p in sorted(paths):
                parent = p.rsplit("/", 1)[0]
                if parent in paths:
                    continue
                self._broadcast_text({"COMMAND": kind, "DATA": p})
        for c in self.conns:
            c.listen = set(p for p in c.listen if tree.find(p) is not None)
            c.last = dict((p, v) for p, v in c.last.items() if p in c.listen)

    def host_info(self):
        return {"NAME": self.name, "OSC_PORT": self.osc_port, "OSC_TRANSPORT": "UDP",
                "WS_PORT": self.http_port, "EXTENSIONS": EXTENSIONS}

    # -- main loop -------------------------------------------------------------------------------------------
    def poll(self):
        socks = [self.udp, self.http] + [c.sock for c in self.conns]
        try:
            readable = select.select(socks, [], [], 0)[0]
        except (OSError, ValueError):
            readable = []
        by_sock = dict((c.sock, c) for c in self.conns)
        for s in readable:
            if s is self.udp:
                self._read_udp()
            elif s is self.http:
                self._accept()
            elif s in by_sock:
                self._read_conn(by_sock[s])
        self._push_changes()
        self._flush()

    def close(self):
        for c in list(self.conns):
            self._drop(c)
        for s in (self.udp, self.http):
            try:
                s.close()
            except OSError:
                pass

    # -- UDP -------------------------------------------------------------------------------------------------
    def _read_udp(self):
        for _ in range(512):
            try:
                data, _addr = self.udp.recvfrom(65535)
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                return
            self._dispatch_osc(data)

    def _dispatch_osc(self, data):
        for address, args in osc.decode(data):
            node = self.tree.find(address)
            if node is None or node.type is None:
                continue
            try:
                node.write(args)
            except Exception as e:  # a failing Live call must not stop the loop
                self.log("write %s failed: %r" % (address, e))

    # -- TCP -------------------------------------------------------------------------------------------------
    def _accept(self):
        for _ in range(16):
            try:
                s, addr = self.http.accept()
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                return
            s.setblocking(False)
            self.conns.append(_Conn(s, addr))

    def _drop(self, c):
        if c in self.conns:
            self.conns.remove(c)
        try:
            c.sock.close()
        except OSError:
            pass

    def _read_conn(self, c):
        try:
            data = c.sock.recv(65536)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            self._drop(c)
            return
        if not data:
            self._drop(c)
            return
        c.rbuf += data
        if not c.ws:
            i = c.rbuf.find(b"\r\n\r\n")
            if i < 0:
                if len(c.rbuf) > 65536:
                    self._drop(c)
                return
            head, c.rbuf = c.rbuf[:i].decode("latin-1"), c.rbuf[i + 4:]
            self._http_request(c, head)
        if c.ws:
            self._read_frames(c)

    def _respond(self, c, status, body=b"", ctype="application/json", extra=""):
        reasons = {200: "OK", 204: "No Content", 400: "Bad Request", 403: "Forbidden", 404: "Not Found",
                   405: "Method Not Allowed"}
        head = ("HTTP/1.1 %d %s\r\nContent-Type: %s; charset=utf-8\r\nContent-Length: %d\r\n"
                "Access-Control-Allow-Origin: *\r\nAccess-Control-Allow-Methods: GET, OPTIONS\r\n"
                "Connection: close\r\n%s\r\n") % (status, reasons.get(status, ""), ctype, len(body), extra)
        c.wbuf += head.encode("latin-1") + body
        c.close_after = True

    def _http_request(self, c, head):
        lines = head.split("\r\n")
        parts = lines[0].split(" ")
        headers = {}
        for ln in lines[1:]:
            if ":" in ln:
                k, v = ln.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        if len(parts) < 2:
            return self._respond(c, 400)
        method, target = parts[0].upper(), parts[1]
        if method == "OPTIONS":
            return self._respond(c, 204)
        if method not in ("GET", "HEAD"):
            return self._respond(c, 405)
        if headers.get("upgrade", "").lower() == "websocket":
            return self._handshake(c, headers)
        target = target.split("#", 1)[0]
        path, _, query = target.partition("?")
        path, query = unquote(path) or "/", unquote(query).upper()
        if path == "/" and query == "HOST_INFO":
            return self._json(c, self.host_info())
        node = self.tree.find(path)
        if node is None:
            return self._respond(c, 404)
        if query:
            a = attribute(node, query)
            return self._json(c, a) if a is not None else self._respond(c, 204)
        self._json(c, describe(node))

    def _json(self, c, obj):
        self._respond(c, 200, json.dumps(obj, separators=(",", ":")).encode("utf-8"))

    # -- WebSocket -------------------------------------------------------------------------------------------
    def _origin_ok(self, headers):
        origin = headers.get("origin")
        if not origin:
            return True  # a native client
        rest = origin.split("://", 1)[-1].split("/", 1)[0]
        host = rest.rsplit(":", 1)[0] if not rest.startswith("[") else rest.split("]")[0][1:]
        own = headers.get("host", "").rsplit(":", 1)[0]
        return host in ("localhost", "::1") or host.startswith("127.") or (own and host == own)

    def _handshake(self, c, headers):
        key = headers.get("sec-websocket-key")
        if not key or not self._origin_ok(headers):
            return self._respond(c, 403)
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest()).decode("ascii")
        c.wbuf += ("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   "Sec-WebSocket-Accept: %s\r\n\r\n" % accept).encode("ascii")
        c.ws = True

    @staticmethod
    def _frame(opcode, payload):
        n = len(payload)
        if n < 126:
            head = struct.pack(">BB", 0x80 | opcode, n)
        elif n < 65536:
            head = struct.pack(">BBH", 0x80 | opcode, 126, n)
        else:
            head = struct.pack(">BBQ", 0x80 | opcode, 127, n)
        return head + payload

    def _read_frames(self, c):
        while True:
            b = c.rbuf
            if len(b) < 2:
                return
            opcode, n = b[0] & 0x0F, b[1] & 0x7F
            masked = bool(b[1] & 0x80)
            i = 2
            if n == 126:
                if len(b) < 4:
                    return
                n, i = struct.unpack(">H", b[2:4])[0], 4
            elif n == 127:
                if len(b) < 10:
                    return
                n, i = struct.unpack(">Q", b[2:10])[0], 10
            if n > 1 << 20:
                return self._drop(c)
            need = i + (4 if masked else 0) + n
            if len(b) < need:
                return
            if masked:
                key = b[i:i + 4]
                payload = bytes(x ^ key[k % 4] for k, x in enumerate(b[i + 4:need]))
            else:
                payload = b[i:need]
            c.rbuf = b[need:]
            if opcode == 0x8:
                c.wbuf += self._frame(0x8, b"")
                c.close_after = True
                return
            elif opcode == 0x9:
                c.wbuf += self._frame(0xA, payload)
            elif opcode == 0x1:
                self._command(c, payload)
            elif opcode == 0x2:
                self._dispatch_osc(payload)

    def _command(self, c, payload):
        try:
            o = json.loads(payload.decode("utf-8"))
            cmd, data = o.get("COMMAND"), o.get("DATA")
        except (ValueError, AttributeError):
            return
        if not isinstance(data, str):
            return
        node = self.tree.find(data)
        if node is None:
            return
        if cmd == "LISTEN":
            c.listen.add(node.path() if node.path() != "/" else "/")
            for n in node.walk():
                if n.type and n.type != "I" and (n.access & 1):
                    c.last[n.path()] = n.value()
        elif cmd == "IGNORE":
            c.listen.discard(node.path())

    def _broadcast_text(self, obj):
        data = self._frame(0x1, json.dumps(obj).encode("utf-8"))
        for c in self.conns:
            if c.ws:
                c.wbuf += data

    def _push_changes(self):
        for c in self.conns:
            if not (c.ws and c.listen):
                continue
            for root in list(c.listen):
                node = self.tree.find(root)
                if node is None:
                    continue
                for n in node.walk():
                    if not n.type or n.type == "I" or not (n.access & 1):
                        continue
                    p = n.path()
                    v = n.value()
                    if v is None or c.last.get(p, None) == v and p in c.last:
                        continue
                    c.last[p] = v
                    c.wbuf += self._frame(0x2, osc.encode_message(p, [_osc_arg(n.type, v)]))

    def _flush(self):
        for c in list(self.conns):
            if c.wbuf:
                try:
                    sent = c.sock.send(c.wbuf)
                    c.wbuf = c.wbuf[sent:]
                except (BlockingIOError, InterruptedError):
                    continue
                except OSError:
                    self._drop(c)
                    continue
            if not c.wbuf and c.close_after:
                self._drop(c)


def _osc_arg(t, v):
    if t == "T":
        return bool(v)
    if t == "i":
        return int(v)
    if t == "f":
        return float(v)
    return str(v)
