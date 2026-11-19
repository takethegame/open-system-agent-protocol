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
* `KeyringKeyStore` uses the OS keyring through `security` (macOS),
  `secret-tool` (Linux), or Windows PowerShell over the `PasswordVault`
  (Windows Credential Manager). All three tools are optional; a missing tool
  fails at construction with a `KeyringError(reason="backend_missing")`
  instead of silently falling back to a file.

Backend failures raise `KeyringError`, a `RuntimeError` subclass carrying a
`reason` (`backend_missing`, `lookup_failed`, `store_failed`), the backend
name, and the CLI `returncode`/`stderr`, so a
caller can tell "the keyring is locked" from "the tool is absent" without
parsing messages.

`migrate_key_store` moves one validated signer record between backends and
returns a report; the source is deleted only after the target verifiably holds
the same record.

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


class KeyringError(RuntimeError):
    """A keyring backend failure with a diagnosable reason.

    It subclasses `RuntimeError` so existing handlers keep working, while
    `reason` separates "the CLI is absent" (`backend_missing`) from "the CLI
    ran and failed" (`lookup_failed`, `store_failed`), and
    `returncode`/`stderr` keep the raw backend output for diagnostics.
    """

    def __init__(
        self,
        reason: str,
        backend: str,
        message: str,
        *,
        returncode: int | None = None,
        stderr: str = "",
        platform: str | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.backend = backend
        self.returncode = returncode
        self.stderr = stderr
        self.platform = platform


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


#: Exit code each backend uses to report "the entry does not exist".
MISSING_CODES = {"security": 44, "secret-tool": 1, "powershell": 44}


def _ps_quote(value: str) -> str:
    """Quote one value for embedding in a single-quoted PowerShell string."""

    return "'" + value.replace("'", "''") + "'"


def _windows_script(verb: str, service: str, account: str) -> str:
    """Build a PowerShell script over the Windows `PasswordVault`.

    The vault is the Windows Credential Manager view for the current user.
    `load` prints the stored secret; `save` reads the new secret from stdin
    and replaces any existing entry; `delete` exits 44 when nothing matched.
    """

    vault = (
        "[Windows.Security.Credentials.PasswordVault,"
        "Windows.Security.Credentials,ContentType=WindowsRuntime]"
    )
    service = _ps_quote(service)
    account = _ps_quote(account)
    if verb == "load":
        return (
            "$ErrorActionPreference = 'Stop'\n"
            "try {\n"
            f"  $vault = {vault}\n"
            f"  $cred = $vault.Retrieve({service}, {account})\n"
            "  $cred.RetrievePassword()\n"
            "  [Console]::Out.Write($cred.Password)\n"
            "} catch { exit 44 }\n"
        )
    if verb == "save":
        return (
            "$ErrorActionPreference = 'Stop'\n"
            "try {\n"
            f"  $vault = {vault}\n"
            f"  try {{ $vault.Remove($vault.Retrieve({service}, {account})) }} catch {{}}\n"
            "  $secret = [Console]::In.ReadToEnd().Trim()\n"
            f"  $cred = New-Object Windows.Security.Credentials.PasswordCredential({service}, {account}, $secret)\n"
            "  $vault.Add($cred)\n"
            "} catch { exit 1 }\n"
        )
    return (
        "$ErrorActionPreference = 'Stop'\n"
        "try {\n"
        f"  $vault = {vault}\n"
        f"  $cred = $vault.Retrieve({service}, {account})\n"
        "  $vault.Remove($cred)\n"
        "} catch { exit 44 }\n"
    )


class KeyringKeyStore(KeyStore):
    """Keep the signer record in the OS keyring through a platform CLI.

    `platform` and `runner` are injectable so the adapter can be tested
    without touching the real keyring. A `runner` takes `(command, secret)`
    and returns an object with `returncode`, `stdout`, and `stderr`, which
    is what `subprocess.run` returns.

    The macOS backend has to pass the secret on the command line because
    `security add-generic-password` has no stdin form, so it is visible to
    same-user process listings; the Linux backend sends it on `secret-tool`
    stdin, and the Windows backend pipes it into PowerShell. Treat the macOS
    path as a development convenience, not a hardened boundary, and prefer a
    native keyring binding in production.
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
            raise KeyringError(
                "backend_missing",
                self._backend,
                f"{self._backend} is not installed",
                platform=self.platform,
            )

    @staticmethod
    def backend_for(platform: str | None = None) -> str | None:
        """Return the CLI that backs `platform`, or None when unsupported."""

        platform = platform or sys.platform
        if platform == "darwin":
            return "security"
        if platform.startswith("linux"):
            return "secret-tool"
        if platform == "win32":
            return "powershell"
        return None

    def _missing_code(self) -> int:
        return MISSING_CODES[self._backend]

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
        if self._backend == "powershell":
            return [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _windows_script("load", self.service, self.account),
            ]
        return ["secret-tool", "lookup", "service", self.service, "account", self.account]

    def load(self) -> dict | None:
        result = self._runner(self._lookup_command(), None)
        if result.returncode == self._missing_code() and not result.stdout.strip():
            return None
        if result.returncode != 0:
            raise KeyringError(
                "lookup_failed",
                self._backend,
                f"{self._backend} lookup failed: {result.stderr.strip()}",
                returncode=result.returncode,
                stderr=result.stderr.strip(),
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
        elif self._backend == "powershell":
            command = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _windows_script("save", self.service, self.account),
            ]
            result = self._runner(command, payload)
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
            raise KeyringError(
                "store_failed",
                self._backend,
                f"{self._backend} store failed: {result.stderr.strip()}",
                returncode=result.returncode,
                stderr=result.stderr.strip(),
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
        elif self._backend == "powershell":
            command = [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                _windows_script("delete", self.service, self.account),
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


def migrate_key_store(
    source: KeyStore,
    target: KeyStore,
    *,
    delete_source: bool = True,
) -> dict:
    """Move one signer record from one backend to another (§10.4).

    The source record is validated with `signer_of` before anything is
    written, so a corrupt record fails the migration instead of being copied.
    The target is never silently overwritten: an occupied target with a
    different key aborts the migration, and an identical target makes the
    migration idempotent. The source is deleted only after the target
    verifiably holds the record. The report is JSON-serialisable so a CLI can
    print it directly.
    """

    report = {
        "source": type(source).__name__,
        "target": type(target).__name__,
    }
    record = source.load()
    if record is None:
        return {
            **report,
            "migrated": False,
            "reason": "no_key_in_source",
            "deleted_from_source": False,
        }
    signer = signer_of(record, what="migrating key record")
    existing = target.load()
    if existing is not None:
        try:
            existing_signer = signer_of(existing, what="existing target record")
        except ValueError:
            existing_signer = None
        if existing_signer is None or (
            existing_signer.kid != signer.kid
            or existing_signer.public_key != signer.public_key
        ):
            return {
                **report,
                "migrated": False,
                "reason": "target_occupied",
                "target_kid": existing.get("kid"),
                "deleted_from_source": False,
            }
    identical = existing == record
    if not identical:
        target.save(record)
        if target.load() != record:
            return {
                **report,
                "migrated": False,
                "reason": "target_verify_failed",
                "kid": signer.kid,
                "deleted_from_source": False,
            }
    deleted = False
    if delete_source:
        try:
            deleted = bool(source.delete())
        except NotImplementedError:
            deleted = False
    return {
        **report,
        "migrated": True,
        "kid": signer.kid,
        "reason": "already_migrated" if identical else "copied",
        "deleted_from_source": deleted,
    }


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
