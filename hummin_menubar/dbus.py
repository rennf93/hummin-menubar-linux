"""Minimal pure-stdlib D-Bus wire client.

Just enough of the protocol to serve a StatusNotifierItem and a dbusmenu tree
on the session bus, plus a handful of blocking calls at startup: little-endian
marshaling, EXTERNAL auth, one reader thread, method-return correlation and
signal dispatch. All variants are represented as (signature, value) tuples.
"""
import os
import socket
import struct
import threading
from itertools import count
from queue import Queue

METHOD_CALL, METHOD_RETURN, ERROR, SIGNAL = 1, 2, 3, 4
NO_REPLY_EXPECTED = 1

FIELD_PATH, FIELD_INTERFACE, FIELD_MEMBER, FIELD_ERROR_NAME = 1, 2, 3, 4
FIELD_REPLY_SERIAL, FIELD_DESTINATION, FIELD_SENDER, FIELD_SIGNATURE = 5, 6, 7, 8

ERR_UNKNOWN_METHOD = "org.freedesktop.DBus.Error.UnknownMethod"
ERR_UNKNOWN_PROP = "org.freedesktop.DBus.Error.UnknownProperty"
ERR_FAILED = "org.freedesktop.DBus.Error.Failed"


class DBusError(Exception):
    def __init__(self, name, text=""):
        super().__init__(f"{name}: {text}" if text else name)
        self.name = name
        self.text = text


# ---- signatures ---------------------------------------------------------------

_SIMPLE_ALIGN = {"y": 1, "b": 4, "n": 2, "q": 2, "u": 4, "i": 4, "x": 8,
                 "t": 8, "d": 8, "s": 4, "o": 4, "g": 1, "v": 1}
_sig_cache = {}


def parse_signature(sig):
    """Parse a complete signature into a list of type nodes."""
    tree = _sig_cache.get(sig)
    if tree is not None:
        return tree
    out, i = [], 0

    def one(i):
        try:
            c = sig[i]
        except IndexError:
            raise ValueError(f"truncated signature {sig!r}")
        if c in _SIMPLE_ALIGN:
            return (c,), i + 1
        if c == "a":
            child, i = one(i + 1)
            return ("a", child), i
        if c == "(":
            i += 1
            children = []
            while i < len(sig) and sig[i] != ")":
                node, i = one(i)
                children.append(node)
            if i >= len(sig):
                raise ValueError(f"unbalanced struct in {sig!r}")
            return ("(", children), i + 1
        if c == "{":
            key, i = one(i + 1)
            val, i = one(i)
            if i >= len(sig) or sig[i] != "}":
                raise ValueError(f"unbalanced dict-entry in {sig!r}")
            return ("{", [key, val]), i + 1
        raise ValueError(f"bad type code {c!r} in {sig!r}")

    while i < len(sig):
        node, i = one(i)
        out.append(node)
    _sig_cache[sig] = out
    return out


def alignof(node):
    t = node[0]
    if t == "a":
        return alignof(node[1])
    if t in ("(", "{"):
        return 8
    return _SIMPLE_ALIGN[t]


# ---- body writer ---------------------------------------------------------------

class BodyWriter:
    def __init__(self):
        self.buf = bytearray()

    def align(self, n):
        self.buf += b"\0" * ((-len(self.buf)) % n)

    def put(self, node, value):
        t = node[0]
        if t == "y":
            self.buf.append(value & 0xFF)
        elif t == "b":
            self.align(4)
            self.buf += struct.pack("<I", 1 if value else 0)
        elif t == "u":
            self.align(4)
            self.buf += struct.pack("<I", value)
        elif t == "i":
            self.align(4)
            self.buf += struct.pack("<i", value)
        elif t in ("x", "t"):
            self.align(8)
            self.buf += struct.pack("<q" if t == "x" else "<Q", value)
        elif t in ("s", "o"):
            raw = value.encode()
            self.align(4)
            self.buf += struct.pack("<I", len(raw))
            self.buf += raw + b"\0"
        elif t == "g":
            raw = value.encode()
            self.buf.append(len(raw))
            self.buf += raw + b"\0"
        elif t == "a":
            # Wire format (as implemented by libdbus/systemd and enforced by
            # dbus-broker): the u32 length counts element bytes only, but the
            # padding that aligns the first element is ALWAYS present after
            # the length field — even for empty arrays — and not counted.
            self.align(4)
            len_pos = len(self.buf)
            self.buf += struct.pack("<I", 0)
            child = node[1]
            self.align(alignof(child))
            start = len(self.buf)
            if isinstance(value, dict):
                k, v = child[1]
                for key, val in value.items():
                    self.align(8)
                    self.put(k, key)
                    self.put(v, val)
            elif child[0] == "y":
                self.buf += bytes(value)
            else:
                for item in value:
                    self.put(child, item)
            self.buf[len_pos:len_pos + 4] = struct.pack("<I", len(self.buf) - start)
        elif t in ("(", "{"):
            self.align(8)
            children = node[1]
            if t == "{":
                self.put(children[0], value[0])
                self.put(children[1], value[1])
            else:
                for child, item in zip(children, value):
                    self.put(child, item)
        elif t == "v":
            sig, inner = value
            self.put(("g",), sig)
            self.put(parse_signature(sig)[0], inner)
        else:  # pragma: no cover
            raise ValueError(f"cannot marshal type {t!r}")


# ---- body reader ---------------------------------------------------------------

class BodyReader:
    def __init__(self, data, pos=0):
        self.d = data
        self.pos = pos

    def align(self, n):
        self.pos += ((-self.pos) % n)

    def take(self, n):
        raw = self.d[self.pos:self.pos + n]
        if len(raw) != n:
            raise ValueError("truncated message body")
        self.pos += n
        return raw

    def get(self, node):
        t = node[0]
        if t == "y":
            return self.take(1)[0]
        if t == "b":
            self.align(4)
            return struct.unpack("<I", self.take(4))[0] != 0
        if t == "u":
            self.align(4)
            return struct.unpack("<I", self.take(4))[0]
        if t == "i":
            self.align(4)
            return struct.unpack("<i", self.take(4))[0]
        if t == "x":
            self.align(8)
            return struct.unpack("<q", self.take(8))[0]
        if t == "t":
            self.align(8)
            return struct.unpack("<Q", self.take(8))[0]
        if t in ("s", "o"):
            self.align(4)
            n = struct.unpack("<I", self.take(4))[0]
            raw = self.take(n)
            self.take(1)
            return raw.decode()
        if t == "g":
            n = self.take(1)[0]
            raw = self.take(n)
            self.take(1)
            return raw.decode()
        if t == "a":
            self.align(4)
            length = struct.unpack("<I", self.take(4))[0]
            child = node[1]
            self.align(alignof(child))
            end = self.pos + length
            if child[0] == "y":
                return bytes(self.take(end - self.pos))
            if child[0] == "{":
                out = {}
                while self.pos < end:
                    self.align(8)
                    k = self.get(child[1][0])
                    v = self.get(child[1][1])
                    out[k] = v
                return out
            out = []
            while self.pos < end:
                out.append(self.get(child))
            return out
        if t == "(":
            self.align(8)
            return tuple(self.get(c) for c in node[1])
        if t == "v":
            sig = self.get(("g",))
            return (sig, self.get(parse_signature(sig)[0]))
        raise ValueError(f"cannot unmarshal type {t!r}")  # pragma: no cover


# ---- messages ---------------------------------------------------------------

class Message:
    __slots__ = ("type", "flags", "serial", "path", "interface", "member",
                 "error_name", "reply_serial", "destination", "sender",
                 "signature", "body")

    def __init__(self, mtype):
        self.type = mtype
        self.flags = 0
        self.serial = 0
        self.path = None
        self.interface = None
        self.member = None
        self.error_name = None
        self.reply_serial = None
        self.destination = None
        self.sender = None
        self.signature = ""
        self.body = None

    def marshal(self, serial):
        w = BodyWriter()
        if self.body:
            for node, val in zip(parse_signature(self.signature), self.body):
                w.put(node, val)
        body = bytes(w.buf)

        # Fields are built on a 12-byte dummy prefix so that struct alignment
        # (8) lines up with absolute message offsets.
        f = bytearray(12)
        entries = [
            (FIELD_PATH, "o", self.path),
            (FIELD_INTERFACE, "s", self.interface),
            (FIELD_MEMBER, "s", self.member),
            (FIELD_ERROR_NAME, "s", self.error_name),
            (FIELD_REPLY_SERIAL, "u", self.reply_serial),
            (FIELD_DESTINATION, "s", self.destination),
            (FIELD_SIGNATURE, "g", self.signature if self.body else None),
        ]
        fw = BodyWriter()
        for code, sig, value in entries:
            if value is None:
                continue
            fw.align(8)
            fw.put(("y",), code)
            fw.put(("v",), (sig, value))
        f += struct.pack("<I", len(fw.buf))
        f += fw.buf
        fields = bytes(f[12:])

        head = struct.pack("<ccccII", b"l", bytes([self.type]),
                           bytes([self.flags]), b"\x01", len(body), serial)
        head += fields  # u32 array length + entries (see dummy-prefix above)
        head += b"\0" * ((-len(head)) % 8)
        return head + body


def parse_message(buf):
    """Parse a full wire message; returns (Message, body_values)."""
    endian, mtype, flags, version = buf[0], buf[1], buf[2], buf[3]
    if endian != ord("l"):
        raise ValueError("non-little-endian message")
    body_len, serial = struct.unpack_from("<II", buf, 4)
    fields_len = struct.unpack_from("<I", buf, 12)[0]
    fields_end = 16 + fields_len
    body_start = (fields_end + 7) & ~7

    msg = Message(mtype)
    msg.flags = flags
    msg.serial = serial
    r = BodyReader(buf, 12)
    length = r.get(("u",))
    r.align(8)
    end = r.pos + length
    while r.pos < end:
        r.align(8)
        code = r.get(("y",))
        sig, value = r.get(("v",))
        if code == FIELD_PATH:
            msg.path = value
        elif code == FIELD_INTERFACE:
            msg.interface = value
        elif code == FIELD_MEMBER:
            msg.member = value
        elif code == FIELD_ERROR_NAME:
            msg.error_name = value
        elif code == FIELD_REPLY_SERIAL:
            msg.reply_serial = value
        elif code == FIELD_DESTINATION:
            msg.destination = value
        elif code == FIELD_SENDER:
            msg.sender = value
        elif code == FIELD_SIGNATURE:
            msg.signature = value

    values = []
    msg.body = buf[body_start:body_start + body_len] or None
    if msg.signature and body_len:
        r = BodyReader(buf, body_start)
        for node in parse_signature(msg.signature):
            values.append(r.get(node))
    return msg, values


# ---- connection ---------------------------------------------------------------

class Connection:
    def __init__(self):
        self.unique_name = None
        self.on_disconnect = None
        self._sock = None
        self._rfile = None
        self._serial = count(1)
        self._send_lock = threading.Lock()
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._methods = {}   # (path, interface, member) -> fn(msg, *args)
        self._signals = []   # (interface, member, arg0, fn)
        self._closed = False

    # lifecycle

    def start(self):
        self._connect()
        self._auth()
        reader = threading.Thread(target=self._read_loop, daemon=True)
        reader.start()
        self.unique_name = self.call_blocking(
            "org.freedesktop.DBus", "/org/freedesktop/DBus",
            "org.freedesktop.DBus", "Hello", "", [], "s", timeout=10)[0]
        return self.unique_name

    def close(self):
        self._closed = True
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._sock.close()

    def _connect(self):
        addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
        if not addr:
            addr = f"unix:path=/run/user/{os.getuid()}/bus"
        for entry in addr.split(";"):
            if entry.startswith("unix:path="):
                self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self._sock.connect(entry[len("unix:path="):])
                break
            if entry.startswith("unix:abstract="):
                self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self._sock.connect("\0" + entry[len("unix:abstract="):])
                break
        if self._sock is None:
            raise RuntimeError(f"unsupported bus address {addr!r}")
        self._rfile = self._sock.makefile("rb")

    def _auth(self):
        uid_hex = "".join(f"{b:02x}" for b in str(os.getuid()).encode()).encode()
        self._sock.sendall(b"\0AUTH EXTERNAL " + uid_hex + b"\r\n")
        line = self._rfile.readline()
        if not line.startswith(b"OK"):
            raise RuntimeError(f"D-Bus auth failed: {line!r}")
        self._sock.sendall(b"BEGIN\r\n")

    # outgoing

    def send(self, msg):
        with self._send_lock:
            msg.serial = next(self._serial)
            self._sock.sendall(msg.marshal(msg.serial))
        return msg.serial

    def call_blocking(self, destination, path, interface, member,
                      signature, args, reply_signature="", timeout=25.0):
        msg = Message(METHOD_CALL)
        msg.destination = destination
        msg.path = path
        msg.interface = interface
        msg.member = member
        msg.signature = signature
        msg.body = args or None
        q = Queue()
        with self._pending_lock:
            msg.serial = self.send(msg)
            self._pending[msg.serial] = (q, reply_signature)
        kind, *payload = q.get(timeout=timeout)
        if kind == "error":
            raise DBusError(payload[0], payload[1])
        return payload[0]

    def send_signal(self, path, interface, member, signature, values):
        msg = Message(SIGNAL)
        msg.flags = NO_REPLY_EXPECTED
        msg.path = path
        msg.interface = interface
        msg.member = member
        msg.signature = signature
        msg.body = values or None
        self.send(msg)

    # handler registration

    def add_method(self, path, interface, member, fn):
        self._methods[(path, interface, member)] = fn

    def add_signal(self, interface, member, arg0, fn):
        self._signals.append((interface, member, arg0, fn))

    # reader

    def _read_exact(self, n):
        chunks = []
        remaining = n
        while remaining:
            chunk = self._rfile.read(remaining)
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _read_loop(self):
        try:
            while True:
                head = self._read_exact(16)
                if head is None:
                    break
                body_len, _serial = struct.unpack_from("<II", head, 4)
                fields_len = struct.unpack_from("<I", head, 12)[0]
                fields_end = 16 + fields_len
                body_start = (fields_end + 7) & ~7
                rest = self._read_exact(body_start + body_len - 16)
                if rest is None:
                    break
                msg, values = parse_message(head + rest)
                self._dispatch(msg, values)
        except (OSError, ValueError) as exc:
            if not self._closed:
                self._on_disconnect(f"session bus connection lost: {exc}")
                return
        self._on_disconnect("session bus connection closed")

    def _on_disconnect(self, reason):
        self._closed = True
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for q, _sig in pending:
            q.put(("error", ERR_FAILED, reason))
        if self.on_disconnect is not None:
            self.on_disconnect(reason)

    def _dispatch(self, msg, values):
        if msg.type in (METHOD_RETURN, ERROR):
            with self._pending_lock:
                entry = self._pending.pop(msg.reply_serial, None)
            if entry is None:
                return
            q, reply_sig = entry
            if msg.type == ERROR:
                text = values[0] if values else ""
                q.put(("error", msg.error_name, text))
            else:
                try:
                    reader = BodyReader(msg.body, 0)
                    parsed = [reader.get(n) for n in parse_signature(reply_sig)] \
                        if reply_sig and msg.body else []
                    q.put(("ok", parsed))
                except (ValueError, struct.error) as exc:
                    q.put(("error", ERR_FAILED, f"bad reply: {exc}"))
            return

        if msg.type == SIGNAL:
            for iface, member, arg0, fn in self._signals:
                if iface == msg.interface and member == msg.member:
                    if arg0 is not None and (not values or values[0] != arg0):
                        continue
                    fn(*values)
            return

        if msg.type == METHOD_CALL:
            fn = self._methods.get((msg.path, msg.interface, msg.member))
            try:
                if fn is None:
                    raise DBusError(ERR_UNKNOWN_METHOD,
                                    f"{msg.interface}.{msg.member}")
                result = fn(msg, *values)
                if msg.flags & NO_REPLY_EXPECTED:
                    return
                reply = Message(METHOD_RETURN)
                reply.reply_serial = msg.serial
                reply.destination = msg.sender
                if result is not None:
                    reply.signature, reply.body = result
                self.send(reply)
            except DBusError as exc:
                self._send_error(msg, exc.name, exc.text)
            except Exception as exc:  # surface bugs as D-Bus errors, never a hang
                self._send_error(msg, ERR_FAILED, str(exc))

    def _send_error(self, msg, name, text):
        if msg.flags & NO_REPLY_EXPECTED:
            return
        reply = Message(ERROR)
        reply.error_name = name
        reply.reply_serial = msg.serial
        reply.destination = msg.sender
        reply.signature = "s"
        reply.body = [text]
        self.send(reply)
