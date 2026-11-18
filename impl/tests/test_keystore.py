# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Unit tests for the private consent-key store (§10.4)."""

import json
import tempfile
import unittest
from pathlib import Path

from osap import JsonStore, consent_flow, keystore, pcs


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class FakeRunner:
    """Record calls and replay prepared results in order."""

    def __init__(self, *results):
        self.calls = []
        self._results = list(results)

    def __call__(self, command, secret):
        self.calls.append((list(command), secret))
        if self._results:
            return self._results.pop(0)
        return FakeResult()


class FakeKeyring:
    """Emulate the subset of `security` / `secret-tool` this adapter uses."""

    def __init__(self, platform="darwin"):
        self.platform = platform
        self.stored = None
        self.calls = []

    def __call__(self, command, secret):
        self.calls.append((list(command), secret))
        tool, verb = command[0], command[1]
        if tool == "security" and verb == "find-generic-password":
            if self.stored is None:
                return FakeResult(44)
            return FakeResult(0, self.stored + "\n")
        if tool == "security" and verb == "add-generic-password":
            self.stored = command[-1]
            return FakeResult(0)
        if tool == "security" and verb == "delete-generic-password":
            existed = self.stored is not None
            self.stored = None
            return FakeResult(0 if existed else 44)
        if tool == "secret-tool" and verb == "lookup":
            if self.stored is None:
                return FakeResult(1)
            return FakeResult(0, self.stored)
        if tool == "secret-tool" and verb == "store":
            self.stored = secret
            return FakeResult(0)
        if tool == "secret-tool" and verb == "clear":
            existed = self.stored is not None
            self.stored = None
            return FakeResult(0 if existed else 1)
        return FakeResult(2, stderr=f"unexpected {command}")


class RecordTests(unittest.TestCase):
    def test_record_round_trips(self):
        signer = pcs.ConsentSigner.generate(kid="pcs-record")
        record = keystore.record_of(signer)
        self.assertEqual(
            sorted(record), ["kid", "private_key", "public_key"]
        )
        restored = keystore.signer_of(record)
        self.assertEqual(restored.kid, signer.kid)
        self.assertEqual(restored.public_key, signer.public_key)
        self.assertEqual(restored.export_private(), signer.export_private())

    def test_record_accepts_a_missing_public_key(self):
        signer = pcs.ConsentSigner.generate(kid="pcs-record")
        record = keystore.record_of(signer)
        del record["public_key"]
        self.assertEqual(keystore.signer_of(record).public_key, signer.public_key)

    def test_record_rejects_a_non_object(self):
        with self.assertRaises(ValueError):
            keystore.signer_of(["not", "a", "record"])

    def test_record_rejects_missing_fields(self):
        signer = pcs.ConsentSigner.generate()
        for field in ("kid", "private_key"):
            record = keystore.record_of(signer)
            del record[field]
            with self.assertRaises(ValueError):
                keystore.signer_of(record)

    def test_record_rejects_non_string_fields(self):
        signer = pcs.ConsentSigner.generate()
        for field, value in (("kid", 7), ("private_key", 7)):
            record = keystore.record_of(signer)
            record[field] = value
            with self.assertRaises(ValueError):
                keystore.signer_of(record)

    def test_record_rejects_an_empty_kid(self):
        record = keystore.record_of(pcs.ConsentSigner.generate())
        record["kid"] = ""
        with self.assertRaises(ValueError):
            keystore.signer_of(record)

    def test_record_rejects_an_invalid_private_key(self):
        record = keystore.record_of(pcs.ConsentSigner.generate())
        record["private_key"] = "not-a-key"
        with self.assertRaises(ValueError):
            keystore.signer_of(record)

    def test_record_rejects_a_mismatched_public_key(self):
        record = keystore.record_of(pcs.ConsentSigner.generate())
        record["public_key"] = pcs.ConsentSigner.generate().public_key
        with self.assertRaises(ValueError):
            keystore.signer_of(record)


class JsonKeyStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "keys.json"

    def test_save_and_load_round_trip(self):
        signer = pcs.ConsentSigner.generate(kid="pcs-json")
        store = JsonStore(self.path)
        keys = keystore.JsonKeyStore(store)
        self.assertIsNone(keys.load())
        keys.save(keystore.record_of(signer))
        self.assertEqual(keys.load()["kid"], "pcs-json")
        self.assertEqual(
            JsonStore(self.path).get(keystore.SIGNING_KEY_SECTION)["kid"],
            "pcs-json",
        )

    def test_default_section_matches_the_flow_constant(self):
        self.assertEqual(keystore.SIGNING_KEY_SECTION, consent_flow.SIGNING_KEY_SECTION)

    def test_load_of_a_missing_section_is_none(self):
        self.assertIsNone(keystore.JsonKeyStore(JsonStore(self.path)).load())

    def test_delete_reports_whether_a_record_existed(self):
        keys = keystore.JsonKeyStore(JsonStore(self.path))
        keys.save(keystore.record_of(pcs.ConsentSigner.generate()))
        self.assertTrue(keys.delete())
        self.assertFalse(keys.delete())
        self.assertIsNone(keys.load())

    def test_save_rejects_a_non_object(self):
        keys = keystore.JsonKeyStore(JsonStore(self.path))
        with self.assertRaises(ValueError):
            keys.save("not a record")


class MemoryKeyStoreTests(unittest.TestCase):
    def test_empty_store_returns_none(self):
        self.assertIsNone(keystore.MemoryKeyStore().load())

    def test_constructor_seeds_a_record(self):
        record = keystore.record_of(pcs.ConsentSigner.generate())
        self.assertEqual(keystore.MemoryKeyStore(record).load(), record)

    def test_saved_records_are_detached_from_callers(self):
        keys = keystore.MemoryKeyStore()
        record = keystore.record_of(pcs.ConsentSigner.generate())
        keys.save(record)
        record["kid"] = "mutated"
        loaded = keys.load()
        loaded["kid"] = "mutated-again"
        self.assertNotIn(keys.load()["kid"], ("mutated", "mutated-again"))

    def test_delete_reports_whether_a_record_existed(self):
        keys = keystore.MemoryKeyStore(keystore.record_of(pcs.ConsentSigner.generate()))
        self.assertTrue(keys.delete())
        self.assertFalse(keys.delete())

    def test_save_rejects_a_non_object(self):
        with self.assertRaises(ValueError):
            keystore.MemoryKeyStore().save(None)


class AsKeyStoreTests(unittest.TestCase):
    def test_none_stays_none(self):
        self.assertIsNone(keystore.as_key_store(None))

    def test_a_key_store_passes_through(self):
        memory = keystore.MemoryKeyStore()
        self.assertIs(keystore.as_key_store(memory), memory)

    def test_a_json_store_is_wrapped(self):
        with tempfile.TemporaryDirectory() as directory:
            wrapped = keystore.as_key_store(JsonStore(Path(directory) / "s.json"))
        self.assertIsInstance(wrapped, keystore.JsonKeyStore)

    def test_an_unrelated_object_is_rejected(self):
        with self.assertRaises(TypeError):
            keystore.as_key_store(object())

    def test_a_dict_is_rejected(self):
        with self.assertRaises(TypeError):
            keystore.as_key_store({"consent.pcs_key": {}})


class KeyringKeyStoreTests(unittest.TestCase):
    def test_backend_for_each_platform(self):
        self.assertEqual(keystore.KeyringKeyStore.backend_for("darwin"), "security")
        self.assertEqual(keystore.KeyringKeyStore.backend_for("linux"), "secret-tool")
        self.assertEqual(
            keystore.KeyringKeyStore.backend_for("linux2"), "secret-tool"
        )
        self.assertIsNone(keystore.KeyringKeyStore.backend_for("win32"))

    def test_an_unsupported_platform_is_rejected(self):
        with self.assertRaises(ValueError):
            keystore.KeyringKeyStore(platform="win32", runner=FakeRunner())

    def test_availability_follows_the_backend(self):
        self.assertFalse(keystore.KeyringKeyStore.available(platform="win32"))

    def test_macos_load_parses_the_stored_record(self):
        signer = pcs.ConsentSigner.generate(kid="pcs-keyring")
        runner = FakeRunner(FakeResult(0, json.dumps(keystore.record_of(signer))))
        store = keystore.KeyringKeyStore(platform="darwin", runner=runner)
        self.assertEqual(store.load(), keystore.record_of(signer))

    def test_macos_load_of_a_missing_entry_is_none(self):
        runner = FakeRunner(FakeResult(44))
        store = keystore.KeyringKeyStore(platform="darwin", runner=runner)
        self.assertIsNone(store.load())
        self.assertEqual(runner.calls[0][0][:2], ["security", "find-generic-password"])

    def test_linux_load_of_a_missing_entry_is_none(self):
        runner = FakeRunner(FakeResult(1))
        store = keystore.KeyringKeyStore(platform="linux", runner=runner)
        self.assertIsNone(store.load())
        self.assertEqual(runner.calls[0][0][:2], ["secret-tool", "lookup"])

    def test_an_empty_entry_is_none(self):
        runner = FakeRunner(FakeResult(0, "  \n"))
        store = keystore.KeyringKeyStore(platform="darwin", runner=runner)
        self.assertIsNone(store.load())

    def test_a_lookup_failure_raises(self):
        runner = FakeRunner(FakeResult(2, stderr="denied"))
        store = keystore.KeyringKeyStore(platform="darwin", runner=runner)
        with self.assertRaises(RuntimeError) as caught:
            store.load()
        self.assertIn("denied", str(caught.exception))

    def test_invalid_json_raises_value_error(self):
        runner = FakeRunner(FakeResult(0, "{not json"))
        store = keystore.KeyringKeyStore(platform="darwin", runner=runner)
        with self.assertRaises(ValueError):
            store.load()

    def test_a_non_object_entry_raises_value_error(self):
        runner = FakeRunner(FakeResult(0, "[1, 2]"))
        store = keystore.KeyringKeyStore(platform="darwin", runner=runner)
        with self.assertRaises(ValueError):
            store.load()

    def test_macos_save_passes_the_secret_on_the_command_line(self):
        signer = pcs.ConsentSigner.generate(kid="pcs-keyring")
        record = keystore.record_of(signer)
        runner = FakeRunner(FakeResult(0))
        store = keystore.KeyringKeyStore(platform="darwin", runner=runner)
        store.save(record)
        command, secret = runner.calls[0]
        self.assertIn("add-generic-password", command)
        self.assertIn("-U", command)
        self.assertIsNone(secret)
        self.assertEqual(command[-1], json.dumps(record, sort_keys=True))

    def test_linux_save_sends_the_secret_on_stdin(self):
        signer = pcs.ConsentSigner.generate(kid="pcs-keyring")
        record = keystore.record_of(signer)
        runner = FakeRunner(FakeResult(0))
        store = keystore.KeyringKeyStore(platform="linux", runner=runner)
        store.save(record)
        command, secret = runner.calls[0]
        self.assertEqual(command[:3], ["secret-tool", "store", "--label=osap-consent"])
        self.assertEqual(secret, json.dumps(record, sort_keys=True))

    def test_a_store_failure_raises(self):
        runner = FakeRunner(FakeResult(1, stderr="locked"))
        store = keystore.KeyringKeyStore(platform="linux", runner=runner)
        with self.assertRaises(RuntimeError) as caught:
            store.save(keystore.record_of(pcs.ConsentSigner.generate()))
        self.assertIn("locked", str(caught.exception))

    def test_save_rejects_a_non_object(self):
        store = keystore.KeyringKeyStore(platform="darwin", runner=FakeRunner())
        with self.assertRaises(ValueError):
            store.save("not a record")

    def test_macos_delete_reports_whether_an_entry_existed(self):
        keyring = FakeKeyring("darwin")
        store = keystore.KeyringKeyStore(platform="darwin", runner=keyring)
        store.save(keystore.record_of(pcs.ConsentSigner.generate()))
        self.assertTrue(store.delete())
        self.assertFalse(store.delete())

    def test_linux_delete_reports_whether_an_entry_existed(self):
        keyring = FakeKeyring("linux")
        store = keystore.KeyringKeyStore(platform="linux", runner=keyring)
        store.save(keystore.record_of(pcs.ConsentSigner.generate()))
        self.assertTrue(store.delete())
        self.assertFalse(store.delete())

    def test_a_flow_reuses_the_keyring_signer_across_instances(self):
        keyring = FakeKeyring("darwin")
        keys = keystore.KeyringKeyStore(platform="darwin", runner=keyring)
        first = consent_flow.ConsentFlow(user="user://local/example-user", key_store=keys)
        second = consent_flow.ConsentFlow(user="user://local/example-user", key_store=keys)
        self.assertEqual(second.signer.kid, first.signer.kid)
        self.assertEqual(second.signer.public_key, first.signer.public_key)
        self.assertIsNotNone(keyring.stored)

    def test_a_corrupt_keyring_entry_cannot_build_a_flow(self):
        keyring = FakeKeyring("darwin")
        keyring.stored = '{"kid": "pcs-broken"}'
        keys = keystore.KeyringKeyStore(platform="darwin", runner=keyring)
        with self.assertRaises(ValueError):
            consent_flow.ConsentFlow(user="user://local/example-user", key_store=keys)

    def test_a_flow_signs_with_the_loaded_keyring_key(self):
        keyring = FakeKeyring("linux")
        keys = keystore.KeyringKeyStore(platform="linux", runner=keyring)
        flow = consent_flow.ConsentFlow(user="user://local/example-user", key_store=keys)
        receipt = flow.signer.sign({"receipt_id": "receipt_flow"})
        self.assertTrue(
            pcs.verify_receipt(receipt, flow.pcs_key["public_key"], kid=flow.signer.kid)
        )


class FlowIsolationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.state_path = Path(self.directory.name) / "state.json"

    def test_a_memory_key_store_keeps_the_receipt_store_clean(self):
        state = JsonStore(self.state_path)
        keys = keystore.MemoryKeyStore()
        flow = consent_flow.ConsentFlow(
            user="user://local/example-user", store=state, key_store=keys
        )
        self.assertIsNone(state.get(consent_flow.SIGNING_KEY_SECTION))
        self.assertEqual(keys.load()["kid"], flow.signer.kid)

        reopened = consent_flow.ConsentFlow(
            user="user://local/example-user", store=state, key_store=keys
        )
        self.assertEqual(reopened.signer.kid, flow.signer.kid)

    def test_an_explicit_json_key_store_still_works(self):
        state = JsonStore(self.state_path)
        keys = keystore.JsonKeyStore(JsonStore(Path(self.directory.name) / "keys.json"))
        flow = consent_flow.ConsentFlow(
            user="user://local/example-user", store=state, key_store=keys
        )
        self.assertIsNone(state.get(consent_flow.SIGNING_KEY_SECTION))
        self.assertEqual(keys.load()["kid"], flow.signer.kid)

    def test_a_bare_json_store_key_store_still_works(self):
        state = JsonStore(self.state_path)
        keys = JsonStore(Path(self.directory.name) / "keys.json")
        flow = consent_flow.ConsentFlow(
            user="user://local/example-user", store=state, key_store=keys
        )
        self.assertEqual(keys.get(keystore.SIGNING_KEY_SECTION)["kid"], flow.signer.kid)

    def test_an_unusable_key_store_is_rejected(self):
        with self.assertRaises(TypeError):
            consent_flow.ConsentFlow(
                user="user://local/example-user", key_store=object()
            )

    def test_an_injected_signer_ignores_the_key_store(self):
        keys = keystore.MemoryKeyStore()
        signer = pcs.ConsentSigner.generate(kid="pcs-injected")
        flow = consent_flow.ConsentFlow(
            user="user://local/example-user", key_store=keys, signer=signer
        )
        self.assertIs(flow.signer, signer)
        self.assertIsNone(keys.load())


if __name__ == "__main__":
    unittest.main()
