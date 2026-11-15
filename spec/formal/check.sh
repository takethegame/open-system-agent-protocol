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

run Capability
run Task

log=$(mktemp "${TMPDIR:-/tmp}/osap-tlc.XXXXXX")
trap 'rm -f "$log"' EXIT
if run CapabilityBroken Capability >"$log" 2>&1; then
  echo "negative control passed unexpectedly: attenuation is not constrained" >&2
  exit 1
fi
if ! grep -q "Invariant AttenuationMonotonic is violated" "$log"; then
  echo "negative control failed for the wrong reason; see $log" >&2
  exit 1
fi

echo "OK: Capability and Task have no violations; the broken attenuation control fails"
