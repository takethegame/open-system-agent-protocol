# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Real local transports for the two framing bindings (standard.md §7.9, §7.10).

The transport layer sits below `Bus`:

- `UnixStreamServer` / `UnixStreamClient` use an `AF_UNIX` stream socket and
  the mandatory 4-byte big-endian length prefix. Every accepted connection owns
  an independent `Bus`, so handshake state never leaks between peers;
- `UnixMessagePair` uses a connected `AF_UNIX` datagram socket pair. One
  datagram is exactly one message, so no length prefix is added.

Both bindings authenticate the peer before any protocol message is exchanged.
Linux exposes `SO_PEERCRED` (pid, uid, gid) and `/proc/<pid>/exe`; macOS and
BSD expose `getpeereid` plus `LOCAL_PEERPID` and `proc_pidpath`. A `PeerPolicy`
fails closed: a field the policy requires but the platform cannot provide is a
denial, not a pass.
"""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import select
import selectors
import socket
import stat
import struct
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from . import framing
from .bus import Bus
from .errors import OsapError
from .flowcontrol import Admission, AdmissionController

_UCRED_BYTES = struct.calcsize("3i")

#: macOS `LOCAL_PEERPID` socket option (`sys/un.h`, `SOL_LOCAL` is 0).
_MACOS_LOCAL_PEERPID = 0x002


@dataclass(frozen=True)
class PeerCredentials:
    """What the local kernel tells us about the other end of a socket."""

    uid: int | None = None
    gid: int | None = None
    pid: int | None = None
    executable: str | None = None
    source: str = "unavailable"

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "gid": self.gid,
            "pid": self.pid,
            "executable": self.executable,
            "source": self.source,
        }


def connection_identity(peer: PeerCredentials) -> str:
    """A stable admission key for a kernel-attested peer.

    Before the OSAP handshake there is no Agent URI, so the listener keys
    connection quotas by what the kernel can attest: the executable path when
    available, then the pid, then the uid. An unidentifiable peer shares the
    `unknown` bucket instead of bypassing the quota.
    """

    if peer.executable:
        return f"exe:{os.path.realpath(peer.executable)}"
    if peer.pid is not None:
        return f"pid:{peer.pid}"
    if peer.uid is not None:
        return f"uid:{peer.uid}"
    return "unknown"


def _getpeereid(fd: int) -> tuple[int | None, int | None]:
    """Read uid/gid via the BSD `getpeereid(2)` libc call."""

    try:
        libc = ctypes.CDLL(None, use_errno=True)
        uid = ctypes.c_uint32()
        gid = ctypes.c_uint32()
        if libc.getpeereid(fd, ctypes.byref(uid), ctypes.byref(gid)) == 0:
            return uid.value, gid.value
    except (AttributeError, OSError):
        pass
    return None, None


def _macos_peer_pid(sock: socket.socket) -> int | None:
    try:
        raw = sock.getsockopt(0, _MACOS_LOCAL_PEERPID, 4)
        return struct.unpack("i", raw)[0]
    except OSError:
        return None


def _executable_of(pid: int | None) -> str | None:
    """Resolve the executable path for `pid` where the platform allows it."""

    if pid is None:
        return None
    if sys.platform.startswith("linux"):
        try:
            return os.readlink(f"/proc/{pid}/exe")
        except OSError:
            return None
    if sys.platform == "darwin":
        try:
            libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
            buffer = ctypes.create_string_buffer(4096)
            length = libproc.proc_pidpath(pid, buffer, len(buffer))
            if length > 0:
                return buffer.value.decode("utf-8", "replace")
        except (AttributeError, OSError):
            return None
    return None


def _ids_from_pid(pid: int | None) -> tuple[int | None, int | None]:
    """Resolve uid/gid for `pid` when the socket option omits them."""

    if pid is None:
        return None, None
    if sys.platform == "darwin":
        try:
            libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
            buffer = ctypes.create_string_buffer(256)
            # PROC_PIDTBSDINFO = 3; pbi_uid/pbi_gid sit at offsets 20 and 24.
            length = libproc.proc_pidinfo(pid, 3, 0, buffer, len(buffer))
            if length >= 28:
                raw = buffer.raw
                uid = struct.unpack_from("I", raw, 20)[0]
                gid = struct.unpack_from("I", raw, 24)[0]
                return uid, gid
        except (AttributeError, OSError):
            return None, None
    if sys.platform.startswith("linux"):
        try:
            status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
        except OSError:
            return None, None
        values = {}
        for line in status.splitlines():
            if line.startswith(("Uid:", "Gid:")):
                key, _, rest = line.partition(":")
                values[key] = int(rest.split()[0])
        return values.get("Uid"), values.get("Gid")
    return None, None


def peer_credentials(sock: socket.socket) -> PeerCredentials:
    """Return the kernel-attested identity of the socket peer, or empty fields."""

    if sys.platform.startswith("linux") and hasattr(socket, "SO_PEERCRED"):
        try:
            raw = sock.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, _UCRED_BYTES
            )
            pid, uid, gid = struct.unpack("3i", raw)
            return PeerCredentials(
                uid=uid,
                gid=gid,
                pid=pid,
                executable=_executable_of(pid),
                source="SO_PEERCRED",
            )
        except OSError:
            pass

    uid, gid = _getpeereid(sock.fileno())
    if sys.platform == "darwin":
        pid = _macos_peer_pid(sock)
        source = "getpeereid+LOCAL_PEERPID" if pid is not None else "getpeereid"
        if uid is None or gid is None:
            fallback_uid, fallback_gid = _ids_from_pid(pid)
            uid = uid if uid is not None else fallback_uid
            gid = gid if gid is not None else fallback_gid
        return PeerCredentials(
            uid=uid,
            gid=gid,
            pid=pid,
            executable=_executable_of(pid),
            source=source,
        )
    return PeerCredentials(
        uid=uid,
        gid=gid,
        source="getpeereid" if uid is not None else "unavailable",
    )


@dataclass(frozen=True)
class PeerPolicy:
    """An allow-list for kernel-attested peer attributes.

    Unset fields are not checked. A set field that the platform cannot attest
    is denied, because absence of evidence is not evidence of a trusted peer.
    """

    uid: int | None = None
    gid: int | None = None
    pid: int | None = None
    executable: str | None = None

    def check(self, peer: PeerCredentials) -> PeerCredentials:
        for field, expected, actual in (
            ("uid", self.uid, peer.uid),
            ("gid", self.gid, peer.gid),
            ("pid", self.pid, peer.pid),
        ):
            if expected is None:
                continue
            if actual is None:
                raise OsapError(
                    "AUTH_DENIED",
                    f"peer {field} is unavailable",
                    details={"reason": "peer_field_unavailable", "field": field},
                )
            if actual != expected:
                raise OsapError(
                    "AUTH_DENIED",
                    f"peer {field} does not match the policy",
                    details={
                        "reason": "peer_mismatch",
                        "field": field,
                        "expected": expected,
                        "actual": actual,
                    },
                )

        if self.executable is not None:
            if peer.executable is None:
                raise OsapError(
                    "AUTH_DENIED",
                    "peer executable is unavailable",
                    details={
                        "reason": "peer_field_unavailable",
                        "field": "executable",
                    },
                )
            expected = os.path.realpath(self.executable)
            actual = os.path.realpath(peer.executable)
            if actual != expected:
                raise OsapError(
                    "AUTH_DENIED",
                    "peer executable does not match the policy",
                    details={
                        "reason": "peer_mismatch",
                        "field": "executable",
                        "expected": expected,
                        "actual": actual,
                    },
                )
        return peer


class UnixSession:
    """One authenticated connection or datagram pair with its own Bus."""

    def __init__(
        self,
        sock: socket.socket,
        *,
        binding: framing.Binding,
        bus: Bus | None = None,
        peer_policy: PeerPolicy | None = None,
    ) -> None:
        self.sock = sock
        self.binding = binding
        self.bus = bus or Bus(binding=binding)
        self.peer = peer_credentials(sock)
        if peer_policy is not None:
            peer_policy.check(self.peer)
        self.admission_lease: Admission | None = None
        self.closed = False

    # --- wire -------------------------------------------------------------

    def send(self, message: object) -> None:
        if self.binding == framing.Binding.STREAM:
            self.sock.sendall(framing.encode_stream(message))
            return
        payload = json.dumps(
            message, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        framing.check_size(len(payload))
        self.sock.send(payload)

    def _recv_exact(self, count: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < count:
            chunk = self.sock.recv(count - len(chunks))
            if not chunk:
                raise ConnectionError("peer closed the transport")
            chunks.extend(chunk)
        return bytes(chunks)

    def _recv_payload(self) -> bytes:
        if self.binding == framing.Binding.STREAM:
            header = self._recv_exact(framing.HEADER_BYTES)
            (length,) = struct.unpack(">I", header)
            framing.check_size(length)
            return self._recv_exact(length)
        payload = self.sock.recv(framing.MAX_FRAME_BYTES + 1)
        if not payload:
            raise ConnectionError("peer closed the transport")
        framing.check_size(len(payload))
        return payload

    def receive(self) -> dict:
        payload = self._recv_payload()
        try:
            message = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OsapError(
                "SCHEMA_INVALID", f"transport payload is not UTF-8 JSON: {exc}"
            ) from exc
        if not isinstance(message, dict):
            raise OsapError("SCHEMA_INVALID", "transport payload must be an object")
        return message

    # --- Bus integration --------------------------------------------------

    def serve(self) -> dict:
        """Receive one message, dispatch it, and send the reply or error."""

        request = None
        try:
            request = self.receive()
            reply = self.bus.receive(request)
        except OsapError as error:
            reply = self.bus.error_envelope(request or {}, error)
        self.send(reply)
        return reply

    def call(self, message: dict) -> dict:
        """Send one message and return the next reply."""

        self.send(message)
        return self.receive()

    def serve_forever(self, *, max_messages: int | None = None) -> int:
        """Serve until the peer closes or `max_messages` replies were sent."""

        served = 0
        while max_messages is None or served < max_messages:
            try:
                self.serve()
            except (ConnectionError, OSError):
                break
            served += 1
        return served

    # --- lifecycle --------------------------------------------------------

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            try:
                self.sock.close()
            except AttributeError:
                # An asyncio transport owns this socket; its close() already
                # closed the underlying fd.
                pass
            if self.admission_lease is not None:
                self.admission_lease.release()
                self.admission_lease = None

    def __enter__(self) -> "UnixSession":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


class _AsyncioStreamProtocol(asyncio.Protocol):
    """Buffered stream framing for the asyncio serving mode (§7.9).

    `data_received` appends bytes and peels complete frames from the buffer,
    so a peer that stalls mid-frame holds only its own connection. Dispatch
    reuses the per-connection `Bus`; errors answer with the standard error
    envelope, and a connection quota rejection is sent before closing, the
    same way the blocking `accept()` path does it.
    """

    def __init__(self, outer: "UnixStreamServer", state: dict) -> None:
        self._outer = outer
        self._state = state
        self.transport = None
        self.session = None
        self.buffer = bytearray()

    def connection_made(self, transport) -> None:
        self.transport = transport
        outer = self._outer
        sock = transport.get_extra_info("socket")
        bus = outer._bus_factory()
        try:
            session = UnixSession(
                sock,
                binding=framing.Binding.STREAM,
                bus=bus,
                peer_policy=outer.peer_policy,
            )
            session.admission_lease = outer.admission.open_connection(
                connection_identity(session.peer)
            )
        except OsapError as error:
            # Tell the peer why it was dropped; a silent close looks like a
            # network fault and invites an immediate retry storm.
            try:
                transport.write(framing.encode_stream(bus.error_envelope({}, error)))
            except (OSError, OsapError):
                pass
            transport.close()
            return
        except Exception:
            transport.close()
            return
        self.session = session
        self._state["sessions"].add(self)

    def data_received(self, data: bytes) -> None:
        self.buffer.extend(data)
        while True:
            if len(self.buffer) < framing.HEADER_BYTES:
                return
            (length,) = struct.unpack(
                ">I", bytes(self.buffer[: framing.HEADER_BYTES])
            )
            try:
                framing.check_size(length)
            except OsapError as error:
                self._reject(error)
                return
            end = framing.HEADER_BYTES + length
            if len(self.buffer) < end:
                return
            payload = bytes(self.buffer[framing.HEADER_BYTES : end])
            del self.buffer[:end]
            if not self._dispatch(payload):
                return

    def _dispatch(self, payload: bytes) -> bool:
        """Handle one framed payload; False when the connection must close."""

        message = None
        try:
            try:
                message = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise OsapError(
                    "SCHEMA_INVALID",
                    f"transport payload is not UTF-8 JSON: {exc}",
                ) from exc
            if not isinstance(message, dict):
                raise OsapError("SCHEMA_INVALID", "transport payload must be an object")
            reply = self.session.bus.receive(message)
        except OsapError as error:
            self._send(self.session.bus.error_envelope(message or {}, error))
            return True
        except (ConnectionError, OSError, NotImplementedError, ValueError):
            self.transport.close()
            return False
        self._send(reply)
        return True

    def _send(self, reply: dict) -> None:
        self.transport.write(framing.encode_stream(reply))
        self._state["served"] += 1
        limit = self._state["max_messages"]
        if limit is not None and self._state["served"] >= limit:
            self._state["finish"]()

    def _reject(self, error: OsapError) -> None:
        self._send(self.session.bus.error_envelope({}, error))
        self.transport.close()

    def connection_lost(self, exc) -> None:
        self._state["sessions"].discard(self)
        if self.session is not None:
            self.session.close()
        self.transport = None


class UnixStreamServer:
    """`AF_UNIX` stream listener whose accepted connections use length framing."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        bus_factory: Callable[[], Bus] | None = None,
        peer_policy: PeerPolicy | None = None,
        admission: AdmissionController | None = None,
        admission_wait: float = 0.0,
        backlog: int = 8,
    ) -> None:
        self.path = Path(path)
        self._remove_stale_socket()
        self.peer_policy = peer_policy
        self.admission = admission or AdmissionController()
        self.admission_wait = admission_wait
        self._bus_factory = bus_factory or (
            lambda: Bus(
                binding=framing.Binding.STREAM,
                admission=self.admission,
                admission_wait=self.admission_wait,
            )
        )
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.sock.bind(str(self.path))
        except OSError:
            self.sock.close()
            raise
        os.chmod(self.path, 0o600)
        self.sock.listen(backlog)
        self.closed = False
        self._asyncio_stop = None

    def _remove_stale_socket(self) -> None:
        """Drop a leftover socket, but never clobber an unrelated file."""

        try:
            mode = self.path.lstat().st_mode
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(mode):
            raise FileExistsError(
                f"{self.path} exists and is not a socket; refusing to replace it"
            )
        self.path.unlink()

    def accept(self) -> UnixSession:
        connection, _ = self.sock.accept()
        try:
            session = UnixSession(
                connection,
                binding=framing.Binding.STREAM,
                bus=self._bus_factory(),
                peer_policy=self.peer_policy,
            )
            try:
                session.admission_lease = self.admission.open_connection(
                    connection_identity(session.peer)
                )
            except OsapError as error:
                # Tell the peer why it was dropped; a silent close looks like a
                # network fault and invites an immediate retry storm.
                try:
                    session.send(session.bus.error_envelope({}, error))
                except (OSError, OsapError):
                    pass
                session.close()
                raise
            return session
        except Exception:
            connection.close()
            raise

    def serve_once(self) -> dict:
        with self.accept() as session:
            return session.serve()

    def serve_forever(
        self,
        *,
        max_messages: int | None = None,
        concurrency: int = 1,
        mode: str = "threads",
    ) -> int:
        """Serve connections until closed or `max_messages` replies were sent.

        `concurrency=1` keeps the original serial behavior. A higher value
        accepts and serves that many connections in parallel, so an idle or
        slow peer cannot block another peer's handshake. Every session still
        owns its own `Bus`; per-Agent quotas and wait queues are shared through
        the server's `AdmissionController`.

        `mode="selector"` runs a single-threaded event loop over
        `selectors.DefaultSelector` instead of a thread pool: the loop serves
        every ready connection in turn, so many idle peers cost one thread,
        not one thread per connection. A peer that stalls halfway through a
        frame can still block the loop until the frame times out at the
        client; full duplex buffering would need a native async binding.

        `mode="asyncio"` runs the listener and every session on an asyncio
        event loop with a buffered framing protocol. Because bytes are
        buffered per connection, a peer that stalls mid-frame no longer
        blocks anyone else; a slow dispatch still serializes the loop, which
        is what a native OS binding would parallelize.

        With concurrency above 1, in selector mode, or in asyncio mode,
        `max_messages` is a best-effort stop condition: no new reply is
        started once the count is reached, but replies already in flight may
        finish.
        """

        if mode not in ("threads", "selector", "asyncio"):
            raise ValueError("mode must be 'threads', 'selector', or 'asyncio'")
        if isinstance(concurrency, bool) or not isinstance(concurrency, int):
            raise ValueError("concurrency must be a positive int")
        if concurrency < 1:
            raise ValueError("concurrency must be a positive int")
        if mode != "threads" and concurrency != 1:
            raise ValueError(f"{mode} mode does not take a concurrency")
        if mode == "selector":
            return self._serve_selector(max_messages)
        if mode == "asyncio":
            return self._serve_asyncio(max_messages)
        if concurrency == 1:
            return self._serve_serial(max_messages)
        return self._serve_concurrent(max_messages, concurrency)

    def _serve_serial(self, max_messages: int | None) -> int:
        served = 0
        while not self.closed and (max_messages is None or served < max_messages):
            try:
                session = self.accept()
            except OsapError:
                continue
            except OSError:
                break
            try:
                while max_messages is None or served < max_messages:
                    session.serve()
                    served += 1
            except (ConnectionError, OSError):
                pass
            finally:
                session.close()
        return served

    def _serve_selector(self, max_messages: int | None) -> int:
        """Serve every ready connection in one thread (§7.11 no starvation).

        The listener and all live sessions share one `DefaultSelector`. A
        readable listener is accepted; a readable session serves one message.
        A peer that disconnects, sends garbage, or hits an error envelope is
        dropped without stopping the loop, so one broken client cannot take
        the Bus down.
        """

        served = 0
        session_of: dict = {}
        with selectors.DefaultSelector() as selector:
            selector.register(self.sock, selectors.EVENT_READ, None)
            try:
                while not self.closed and (
                    max_messages is None or served < max_messages
                ):
                    for key, _ in selector.select(timeout=0.05):
                        if key.data is None:
                            try:
                                session = self.accept()
                            except OsapError:
                                continue
                            except OSError:
                                return served
                            try:
                                selector.register(
                                    session.sock, selectors.EVENT_READ, session
                                )
                            except (OSError, ValueError):
                                session.close()
                                continue
                            session_of[session.sock] = session
                            continue
                        if max_messages is not None and served >= max_messages:
                            return served
                        session = key.data
                        try:
                            session.serve()
                        except (
                            ConnectionError,
                            OSError,
                            OsapError,
                            NotImplementedError,
                            ValueError,
                        ):
                            # Nothing was delivered, so `max_messages` still
                            # counts only replies that actually went out.
                            self._drop_session(selector, session_of, session)
                            continue
                        served += 1
            finally:
                for session in list(session_of.values()):
                    try:
                        selector.unregister(session.sock)
                    except (KeyError, OSError, ValueError):
                        pass
                    session.close()
        return served

    def _serve_asyncio(self, max_messages: int | None) -> int:
        """Run the listener and every session on one asyncio event loop.

        Bytes are buffered per connection (`_AsyncioStreamProtocol`), so a
        peer that sends half a frame and stalls does not block anyone else —
        the guarantee the selector loop cannot give. Dispatch itself is
        synchronous, so a slow handler still serializes the loop.
        """

        try:
            return asyncio.run(self._asyncio_main(max_messages))
        except (OSError, ValueError):
            # The listener was closed underneath us; deliver what we counted.
            return 0

    async def _asyncio_main(self, max_messages: int | None) -> int:
        loop = asyncio.get_running_loop()
        state: dict = {
            "served": 0,
            "max_messages": max_messages,
            "sessions": set(),
            "server": None,
        }

        def finish() -> None:
            if state["done"].done():
                return
            if state["server"] is not None:
                state["server"].close()
            for session in list(state["sessions"]):
                if session.transport is not None:
                    session.transport.close()
            state["done"].set_result(True)

        state["finish"] = finish
        state["done"] = loop.create_future()
        self._asyncio_stop = (loop, finish)

        async def monitor() -> None:
            while not state["done"].done():
                await asyncio.sleep(0.05)
                if self.closed or (
                    max_messages is not None and state["served"] >= max_messages
                ):
                    finish()

        monitor_task = loop.create_task(monitor())
        try:
            state["server"] = await loop.create_server(
                lambda: _AsyncioStreamProtocol(self, state),
                sock=self.sock,
            )
            await state["done"]
        finally:
            monitor_task.cancel()
            self._asyncio_stop = None
            # The loop thread owns the socket in this mode; close it here so
            # an external close() never has to touch the kqueue-selected fd.
            try:
                self.sock.close()
            except OSError:
                pass
        return state["served"]

    def _drop_session(self, selector, session_of: dict, session) -> None:
        session_of.pop(session.sock, None)
        try:
            selector.unregister(session.sock)
        except (KeyError, OSError, ValueError):
            pass
        session.close()

    def _serve_concurrent(self, max_messages: int | None, concurrency: int) -> int:
        served = 0
        lock = threading.Lock()
        stop = threading.Event()
        sessions: set[UnixSession] = set()

        def worker(session: UnixSession) -> None:
            nonlocal served
            try:
                while not stop.is_set():
                    try:
                        readable, _, _ = select.select(
                            [session.sock], [], [], 0.05
                        )
                    except (OSError, ValueError):
                        break
                    if not readable:
                        continue
                    with lock:
                        if max_messages is not None and served >= max_messages:
                            break
                        if max_messages is not None:
                            served += 1
                    try:
                        session.serve()
                    except (ConnectionError, OSError, OsapError, NotImplementedError):
                        # The claim above was for a reply that was never sent;
                        # return it so the budget still reflects delivered
                        # replies.
                        with lock:
                            if max_messages is not None:
                                served -= 1
                        break
                    with lock:
                        if max_messages is not None and served >= max_messages:
                            stop.set()
            finally:
                with lock:
                    sessions.discard(session)
                session.close()

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            try:
                while not self.closed and not stop.is_set():
                    try:
                        readable, _, _ = select.select([self.sock], [], [], 0.05)
                    except (OSError, ValueError):
                        break
                    if not readable:
                        continue
                    try:
                        session = self.accept()
                    except OsapError:
                        continue
                    except OSError:
                        break
                    with lock:
                        if stop.is_set() or (
                            max_messages is not None and served >= max_messages
                        ):
                            session.close()
                            break
                        sessions.add(session)
                    pool.submit(worker, session)
            finally:
                stop.set()
                with lock:
                    pending = list(sessions)
                for session in pending:
                    try:
                        session.sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
        return served

    def close(self) -> None:
        if not self.closed:
            self.closed = True
            stopper = self._asyncio_stop
            if stopper is not None:
                # An asyncio loop owns the socket right now. Never close a
                # kqueue-selected fd from another thread — on macOS that can
                # hang the loop's kevent() forever — signal it instead; the
                # serving thread closes the socket in its own finally.
                loop, finish = stopper
                loop.call_soon_threadsafe(finish)
            else:
                self.sock.close()
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def __enter__(self) -> "UnixStreamServer":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


class UnixStreamClient:
    """Connect to a `UnixStreamServer` and return an authenticated session."""

    @staticmethod
    def connect(
        path: str | os.PathLike[str],
        *,
        bus: Bus | None = None,
        peer_policy: PeerPolicy | None = None,
        timeout: float | None = None,
    ) -> UnixSession:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            if timeout is not None:
                sock.settimeout(timeout)
            sock.connect(str(path))
            return UnixSession(
                sock,
                binding=framing.Binding.STREAM,
                bus=bus,
                peer_policy=peer_policy,
            )
        except Exception:
            sock.close()
            raise


class UnixMessagePair:
    """A connected datagram pair; one datagram is exactly one message."""

    @staticmethod
    def pair(
        *,
        server_bus: Bus | None = None,
        client_bus: Bus | None = None,
        peer_policy: PeerPolicy | None = None,
        timeout: float | None = None,
    ) -> tuple[UnixSession, UnixSession]:
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        if timeout is not None:
            left.settimeout(timeout)
            right.settimeout(timeout)
        try:
            server = UnixSession(
                left,
                binding=framing.Binding.MESSAGE,
                bus=server_bus,
                peer_policy=peer_policy,
            )
            client = UnixSession(
                right,
                binding=framing.Binding.MESSAGE,
                bus=client_bus,
                peer_policy=peer_policy,
            )
        except Exception:
            left.close()
            right.close()
            raise
        return server, client
