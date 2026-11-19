# Linux `systemd --user` units

These units are examples for the Linux binding profile in
[`../profile.md`](../profile.md). They assume the executables are installed in
`/usr/libexec/` and that the distribution provides a working `systemd --user`
manager.

## Install

```bash
install -d -m 0700 ~/.config/systemd/user
install -m 0644 osap-*.service osap-bus.socket ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now osap-bus.socket
systemctl --user enable --now osap-registry.service
systemctl --user enable --now osap-consent.service
systemctl --user enable --now osap-capability.service
systemctl --user enable --now osap-context.service
systemctl --user enable --now osap-audit.service
```

`osap-bus.socket` owns `$XDG_RUNTIME_DIR/osap/bus.sock` with mode `0600`. The
parent directory is created with mode `0700`. The bus service acquires
`org.osap.Bus`; the auxiliary services acquire their own names.

## Activation choice

Use **one** of these paths for the bus:

1. **systemd socket activation** (recommended): enable `osap-bus.socket` and
   let the first connection start `osap-bus.service`.
2. **D-Bus activation**: install the files from [`../dbus/`](../dbus/) and do
   not enable `osap-bus.socket`.

Running both can create two bus instances. The installation script should
check `systemctl --user is-enabled osap-bus.socket` and remove or disable the
other path.

The auxiliary services are `Type=dbus` and can be started on demand by D-Bus
activation or by `systemctl --user enable --now`. They are `PartOf` the bus
service, so stopping the bus stops them as well.

## Paths

- Runtime: `%t/osap` (`$XDG_RUNTIME_DIR/osap`), mode `0700`.
- State: `%S/osap` (`$XDG_STATE_HOME/osap`), mode `0700`.
- Audit and consent stores live under the state directory; the bus stores
  session indexes there when persistence is enabled.

## Hardening

The units set `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`,
`RestrictAddressFamilies=AF_UNIX`, `CapabilityBoundingSet=`, and a
`@system-service` system-call filter. `ProtectHome` is `yes` for services that
do not need the home directory and `read-only` for the registry and context
services that may read manifests or portal-backed files.

Some distributions or file-handle flows need a narrower filter. Test on the
target distribution. Do not remove hardening to fix a local failure; add the
smallest exception and document it.
