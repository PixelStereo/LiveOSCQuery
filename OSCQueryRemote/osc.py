"""OSC 1.0 encoding and decoding (stdlib only, Python 3.7 compatible)."""
import struct


class RGBA(int):
    """Unsigned packed OSC color (0xRRGGBBAA)."""


def _pad(b):
    return b + b"\0" * (-len(b) % 4)


def _string(s):
    return _pad(s.encode("utf-8") + b"\0")


def encode_message(address, args=()):
    tags = ","
    data = b""
    for a in args:
        if isinstance(a, bool):
            tags += "T" if a else "F"
        elif isinstance(a, RGBA):
            tags += "r"
            data += struct.pack(">I", a)
        elif isinstance(a, int):
            tags += "i"
            data += struct.pack(">i", max(-2 ** 31, min(2 ** 31 - 1, a)))
        elif isinstance(a, float):
            tags += "f"
            data += struct.pack(">f", a)
        elif isinstance(a, str):
            tags += "s"
            data += _string(a)
        elif isinstance(a, (bytes, bytearray)):
            tags += "b"
            data += struct.pack(">i", len(a)) + _pad(bytes(a))
        elif a is None:
            tags += "N"
        else:
            raise TypeError("unsupported OSC argument %r" % (a,))
    return _string(address) + _string(tags) + data


def _read_string(data, i):
    end = data.index(b"\0", i)
    s = data[i:end].decode("utf-8", "replace")
    return s, (end + 4) // 4 * 4


def decode(data):
    """Returns a flat list of (address, [args]) for a message or a (nested) bundle."""
    out = []
    try:
        _decode(bytes(data), out)
    except (ValueError, struct.error, IndexError):
        pass
    return out


def _decode(data, out):
    if data.startswith(b"#bundle\0"):
        i = 16
        while i + 4 <= len(data):
            (n,) = struct.unpack_from(">i", data, i)
            i += 4
            if n < 0 or i + n > len(data):
                return
            _decode(data[i:i + n], out)
            i += n
        return
    if not data.startswith(b"/"):
        return
    address, i = _read_string(data, 0)
    args = []
    if i < len(data):
        tags, i = _read_string(data, i)
        for t in tags[1:]:
            if t == "i":
                args.append(struct.unpack_from(">i", data, i)[0]); i += 4
            elif t == "f":
                args.append(struct.unpack_from(">f", data, i)[0]); i += 4
            elif t == "h":
                args.append(struct.unpack_from(">q", data, i)[0]); i += 8
            elif t == "d":
                args.append(struct.unpack_from(">d", data, i)[0]); i += 8
            elif t in "sS":
                s, i = _read_string(data, i); args.append(s)
            elif t == "b":
                (n,) = struct.unpack_from(">i", data, i)
                args.append(data[i + 4:i + 4 + n]); i += 4 + (n + 3) // 4 * 4
            elif t == "T":
                args.append(True)
            elif t == "F":
                args.append(False)
            elif t == "N":
                args.append(None)
            elif t == "I":
                args.append(True)
            elif t == "c":
                args.append(chr(struct.unpack_from(">i", data, i)[0])); i += 4
            elif t == "r":
                args.append(RGBA(struct.unpack_from(">I", data, i)[0])); i += 4
            elif t == "t":
                i += 8
            elif t == "m":
                i += 4
            elif t in "[]":
                pass
            else:
                break
    out.append((address, args))
