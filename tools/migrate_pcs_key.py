# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
"""Move the PCS consent key from a JSON store into the OS keyring (§10.4).

One-shot migration helper for deployments that started with the default
plain-JSON key store and want the private consent key out of the receipts
file. The migration validates the record, never overwrites a different key
in the target, deletes the JSON section only after the target verifiably
holds the record, and prints a JSON report:

    python3 tools/migrate_pcs_key.py --json state.json
    python3 tools/migrate_pcs_key.py --json state.json --to keyring --keep-source
    python3 tools/migrate_pcs_key.py --json state.json --service osap-consent --account pcs

`--to json:<path>` copies between JSON layouts (for example to a dedicated
key file); `--to keyring` uses the platform backend of the current machine
(`security` on macOS, `secret-tool` on Linux, PowerShell over the Windows
`PasswordVault` on Windows). A missing backend CLI fails with
`KeyringError(reason="backend_missing")` and exit code 1.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "impl"))

from osap import JsonStore, keystore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", required=True, help="JSON store holding consent.pcs_key")
    parser.add_argument("--section", default=keystore.SIGNING_KEY_SECTION)
    parser.add_argument(
        "--to",
        default="keyring",
        help="'keyring' or 'json:<path>' (default: keyring)",
    )
    parser.add_argument("--service", default="osap-consent")
    parser.add_argument("--account", default="pcs")
    parser.add_argument("--keep-source", action="store_true")
    parser.add_argument(
        "--platform",
        default=None,
        help="override the platform backend selection (for testing)",
    )
    arguments = parser.parse_args()

    source = keystore.JsonKeyStore(JsonStore(arguments.json), section=arguments.section)
    if arguments.to == "keyring":
        target = keystore.KeyringKeyStore(
            service=arguments.service,
            account=arguments.account,
            platform=arguments.platform,
        )
    elif arguments.to.startswith("json:"):
        target = keystore.JsonKeyStore(
            JsonStore(arguments.to[len("json:") :]), section=arguments.section
        )
    else:
        parser.error("--to must be 'keyring' or 'json:<path>'")

    try:
        report = keystore.migrate_key_store(
            source, target, delete_source=not arguments.keep_source
        )
    except (keystore.KeyringError, ValueError) as error:
        detail = getattr(error, "reason", None)
        print(
            json.dumps(
                {
                    "migrated": False,
                    "reason": detail or type(error).__name__,
                    "message": str(error),
                }
            )
        )
        return 1
    print(json.dumps(report, sort_keys=True))
    if report.get("migrated"):
        return 0
    return 0 if report.get("reason") == "no_key_in_source" else 1


if __name__ == "__main__":
    sys.exit(main())
