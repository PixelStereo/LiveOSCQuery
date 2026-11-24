"""The OSCQuery tree: nodes, lookup, and the JSON description (attribute names as pxs-core writes them)."""

# OSC type -> how a written value is coerced
def _coerce(t, v):
    if t == "f":
        return float(v)
    if t == "i":
        return int(round(float(v)))
    if t == "T":
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "t", "yes", "on")
        return bool(v)
    if t == "s":
        return str(v)
    return v


class Node(object):
    """A container (type None) or a parameter.

    type: 'f' float, 'i' int, 's' string, 'T' boolean, 'I' trigger (no value).
    get(): the current value, or None. set(value): applies a coerced value (set(None) for a trigger).
    description may be a string or a callable returning one.
    """

    def __init__(self, name, type=None, get=None, set=None, range=None, description=None):
        self.name = name
        self.parent = None
        self.children = {}
        self.order = []
        self.type = type
        self.get = get
        self.set = set
        self.range = range
        self.description = description

    @property
    def access(self):
        if self.type is None:
            return 0
        if self.type == "I":
            return 2
        return (1 if self.get else 0) | (2 if self.set else 0)

    def add(self, node):
        node.parent = self
        if node.name not in self.children:
            self.order.append(node.name)
        self.children[node.name] = node
        return node

    def path(self):
        parts = []
        n = self
        while n is not None and n.parent is not None:
            parts.append(n.name)
            n = n.parent
        return "/" + "/".join(reversed(parts))

    def value(self):
        if not self.get:
            return None
        try:
            return self.get()
        except Exception:
            return None

    def write(self, args):
        """Applies an incoming OSC message. Returns True when something was done."""
        if self.set is None:
            return False
        if self.type == "I":
            self.set(None)
            return True
        if not args:
            return False
        v = _coerce(self.type, args[0])
        if self.range and self.type in "fi":
            v = max(self.range[0], min(self.range[1], v))
            if self.type == "i":
                v = int(v)
        self.set(v)
        return True

    def walk(self):
        yield self
        for n in self.order:
            for d in self.children[n].walk():
                yield d


class Tree(object):
    def __init__(self):
        self.root = Node("")

    def find(self, path):
        node = self.root
        for part in [p for p in path.split("/") if p]:
            node = node.children.get(part)
            if node is None:
                return None
        return node

    def paths(self):
        return set(n.path() for n in self.root.walk() if n is not self.root)


def _json_value(t, v):
    if t == "T":
        return bool(v)
    if t == "i":
        return int(v)
    if t == "f":
        v = float(v)
        return v if v == v and abs(v) != float("inf") else 0.0
    return "" if v is None else str(v)


def describe(node, contents=True):
    o = {"FULL_PATH": node.path(), "ACCESS": node.access}
    d = node.description() if callable(node.description) else node.description
    if d:
        o["DESCRIPTION"] = str(d)
    if node.type:
        o["TYPE"] = node.type
        if node.type != "I" and (node.access & 1):
            v = node.value()
            if v is not None:
                o["VALUE"] = [_json_value(node.type, v)]
        if node.range is not None and node.type in "fi":
            o["RANGE"] = [{"MIN": node.range[0], "MAX": node.range[1]}]
    elif contents:
        o["CONTENTS"] = dict((n, describe(node.children[n], True)) for n in node.order)
    return o


def attribute(node, name):
    """The one-attribute answer ({"VALUE": [...]}), or None when the node has no such attribute."""
    name = name.upper()
    o = describe(node, name == "CONTENTS")
    if name in o:
        return {name: o[name]}
    return None
