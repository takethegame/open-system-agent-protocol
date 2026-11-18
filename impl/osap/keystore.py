# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Where the PCS private consent key lives (§10.4).

`ConsentFlow` needs one long-lived Ed25519 key so receipts stay verifiable
across restarts. That key must not be shipped to verifiers and should not
sit in the same plain JSON file as receipts. This module separates the two
concerns: a `KeyStore` answers only `load()` and `save()` for a single signer
record, and the caller decides which backend holds it.

Three backends ship with the reference implementation:

* `JsonKeyStore` wraps a `JsonStore` section, which preserves the 0600 file
  layout used before this module existed.
* `MemoryKeyStore` keeps the record in process memory, for tests and for
  short-lived verifiers that must not persist anything.
* `KeyringKeyStore` uses the OS keyring through `security` (macOS) or
  `secret-tool` (Linux). Both tools are optional; a missing tool fails at
  construction instead of silently falling back to a file.

`signer_of` validates a stored record in one place, so every backend rejects
the same corrupt input with the same `ValueError`.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys

from .pcs import ConsentSigner

#: Section a JSON-backed key store writes.
SIGNING_KEY_SECTION = "consent.pcs_key"


def record_of(signer: ConsentSigner) -> dict:
    """Serialize one signer for a key store; never send this over a Bus."""

    return {
        "kid": signer.kid,
        "private_key": signer.export_private(),
        "public_key": signer.public_key,
    }


def signer_of(record, *, what: str = SIGNING_KEY_SECTION) -> ConsentSigner:
    """Rebuild a signer from a stored record, rejecting corrupt input.

    `public_key` is optional for records written before it was persisted, but
    when present it must match the key derived from `private_key`, so a
    half-rewritten or swapped record cannot impersonate another `kid`.
    """

    if not isinstance(record, dict):
        raise ValueError(f"{what!r} must be a JSON object")
    private = record.get("private_key")
    kid = record.get("kid")
    if not isinstance(private, str) or not isinstance(kid, str) or not kid:
        raise ValueError(f"{what!r} needs a private_key and a kid")
    try:
        signer = ConsentSigner(private, kid=kid)
    except (ValueError, TypeError) as error:
        raise ValueError(f"{what!r} has an invalid private_key") from error
    if record.get("public_key") not in (None, signer.public_key):
        raise ValueError(f"{what!r} public_key does not match")
    return signer


class KeyStore:
    """Minimal storage contract for one PCS signer record.

    Subclasses must implement `load` and `save`; `delete` is optional and
    defaults to "not supported" so a read-only backend stays honest instead
    of pretending a removal succeeded.
    """

    def load(self) -> dict | None:
        raise NotImplementedError

    def save(self, record: dict) -> None:
        raise NotImplementedError

    def delete(self) -> bool:
        raise NotImplementedError("this key store cannot delete records")


class JsonKeyStore(KeyStore):
    """Keep the signer record in one `JsonStore` section."""

    def __init__(self, store, *, section: str = SIGNING_KEY_SECTION) -> None:
        self._store = store
        self._section = section

    def load(self) -> dict | None:
        return self._store.get(self._section)

    def save(self, record: dict) -> None:
        if not isinstance(record, dict):
            raise ValueError("a key record must be a JSON object")
        self._store.put(self._section, record)

    def delete(self) -> bool:
        existed = self._store.get(self._section) is not None
        self._store.delete(self._section)
        return existed


class MemoryKeyStore(KeyStore):
    """Keep the signer record in memory only; nothing survives the process."""

    def __init__(self, record: dict | None = None) -> None:
        self._record: dict | None = None
        if record is not None:
            self.save(record)

    def load(self) -> dict | None:
        return None if self._record is None else copy.deepcopy(self._record)

    def save(self, record: dict) -> None:
        if not isinstance(record, dict):
            raise ValueError("a key record must be a JSON object")
        self._record = copy.deepcopy(record)

    def delete(self) -> bool:
        existed = self._record is not None
        self._record = None
        return existed


def _run(command: list[str], secret: str | None):
    return subprocess.run(
        command,
        input=secret,
        capture_output=True,
        text=True,
        check=False,
    )


class KeyringKeyStore(KeyStore):
    """Keep the signer record in the OS keyring through a platform CLI.

    `platform` and `runner` are injectable so the adapter can be tested
    without touching the real keyring. A `runner` takes `(command, secret)`
    and returns an object with `returncode`, `stdout`, and `stderr`, which
    is what `subprocess.run` returns.

    The macOS backend has to pass the secret on the command line because
    `security add-generic-password` has no stdin form, so it is visible to
    same-user process listings; the Linux `secret-tool` backend sends it on
    stdin. Treat the macOS path as a development convenience, not a hardened
    boundary, and prefer a native keyring binding in production.
    """

    def __init__(
        self,
        *,
        service: str = "osap-consent",
        account: str = "pcs",
        platform: str | None = None,
        runner=None,
    ) -> None:
        self.service = service
        self.account = account
        self.platform = platform or sys.platform
        self._runner = runner or _run
        self._backend = self.backend_for(self.platform)
        if self._backend is None:
            raise ValueError(f"no OS keyring backend for platform {self.platform!r}")
        if runner is None and shutil.which(self._backend) is None:
            raise RuntimeError(f"{self._backend} is not installed")

    @staticmethod
    def backend_for(platform: str | None = None) -> str | None:
        """Return the CLI that backs `platform`, or None when unsupported."""

        platform = platform or sys.platform
        if platform == "darwin":
            return "security"
        if platform.startswith("linux"):
            return "secret-tool"
        return None

    @classmethod
    def available(cls, *, platform: str | None = None) -> bool:
        """True when this machine has a supported keyring CLI installed."""

        backend = cls.backend_for(platform)
        return backend is not None and shutil.which(backend) is not None

    def _lookup_command(self) -> list[str]:
        if self._backend == "security":
            return [
                "security",
                "find-generic-password",
                "-s",
                self.service,
                "-a",
                self.account,
                "-w",
            ]
        return ["secret-tool", "lookup", "service", self.service, "account", self.account]

    def load(self) -> dict | None:
        result = self._runner(self._lookup_command(), None)
        missing = 44 if self._backend == "security" else 1
        if result.returncode == missing and not result.stdout.strip():
            return None
        if result.returncode != 0:
            raise RuntimeError(
                f"{self._backend} lookup failed: {result.stderr.strip()}"
            )
        text = result.stdout.strip()
        if not text:
            return None
        try:
            record = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError("keyring entry is not valid JSON") from error
        if not isinstance(record, dict):
            raise ValueError("keyring entry must be a JSON object")
        return record

    def save(self, record: dict) -> None:
        if not isinstance(record, dict):
            raise ValueError("a key record must be a JSON object")
        payload = json.dumps(record, sort_keys=True)
        if self._backend == "security":
            command = [
                "security",
                "add-generic-password",
                "-U",
                "-s",
                self.service,
                "-a",
                self.account,
                "-w",
                payload,
            ]
            result = self._runner(command, None)
        else:
            command = [
                "secret-tool",
                "store",
                f"--label={self.service}",
                "service",
                self.service,
                "account",
                self.account,
            ]
            result = self._runner(command, payload)
        if result.returncode != 0:
            raise RuntimeError(
                f"{self._backend} store failed: {result.stderr.strip()}"
            )

    def delete(self) -> bool:
        if self._backend == "security":
            command = [
                "security",
                "delete-generic-password",
                "-s",
                self.service,
                "-a",
                self.account,
            ]
        else:
            command = [
                "secret-tool",
                "clear",
                "service",
                self.service,
                "account",
                self.account,
            ]
        result = self._runner(command, None)
        return result.returncode == 0


def as_key_store(value) -> KeyStore | None:
    """Accept a `KeyStore`, a bare `JsonStore`, or None.

    A `JsonStore` is wrapped in `JsonKeyStore`, which keeps the pre-existing
    `key_store=JsonStore(...)` call sites working unchanged.
    """

    if value is None:
        return None
    if isinstance(value, KeyStore):
        return value
    if hasattr(value, "get") and hasattr(value, "put"):
        return JsonKeyStore(value)
    raise TypeError("key_store must be a KeyStore or a JsonStore")
