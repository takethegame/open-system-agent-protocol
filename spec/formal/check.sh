#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The OSAP Authors
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
jar=${TLA2TOOLS_JAR:-$here/tla2tools.jar}

if [ ! -f "$jar" ]; then
  echo "missing tla2tools.jar; set TLA2TOOLS_JAR or see README.md" >&2
  exit 2
fi

run() {
  module=$1
  spec=${2:-$1}
  (cd "$here" && java -cp "$jar" tlc2.TLC \
    -config "$module.cfg" -workers 1 "$spec.tla")
}

expect_violation() {
  module=$1
  spec=$2
  expected=$3
  log=$(mktemp "${TMPDIR:-/tmp}/osap-tlc.XXXXXX")
  if run "$module" "$spec" >"$log" 2>&1; then
    echo "negative control passed unexpectedly: $module" >&2
    rm -f "$log"
    exit 1
  fi
  if ! grep -q "Invariant $expected is violated" "$log"; then
    echo "negative control $module failed for the wrong reason; see $log" >&2
    exit 1
  fi
  rm -f "$log"
  echo "OK: negative control $module reports $expected"
}

run Capability
run Task
run Consent
run Recovery

expect_violation CapabilityBroken Capability AttenuationMonotonic
expect_violation RecoveryBroken Recovery AtMostOnce

echo "OK: all positive models pass and both negative controls fail"
