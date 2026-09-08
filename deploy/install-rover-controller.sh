#!/usr/bin/env bash
set -Eeuo pipefail

[[ ${EUID} -eq 0 ]] || {
    echo "Run this installer with sudo." >&2
    exit 1
}

readonly DEPLOY_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

install -m 0644 \
    "$DEPLOY_DIR/frontier-rover-control.service" \
    /etc/systemd/system/frontier-rover-control.service
install -m 0644 \
    "$DEPLOY_DIR/frontier-rover-poweroff.path" \
    /etc/systemd/system/frontier-rover-poweroff.path
install -m 0644 \
    "$DEPLOY_DIR/frontier-rover-poweroff.service" \
    /etc/systemd/system/frontier-rover-poweroff.service

systemctl daemon-reload
systemctl enable --now frontier-rover-poweroff.path
systemctl enable frontier-rover-control.service
systemctl restart frontier-rover-control.service

systemctl is-active --quiet frontier-rover-control.service
systemctl is-active --quiet frontier-rover-poweroff.path
test -d /run/frontier-rover
test "$(stat -c %U:%G /run/frontier-rover)" = "rover:rover"
test -d /var/lib/frontier-rover
test "$(stat -c %U:%G /var/lib/frontier-rover)" = "rover:rover"

echo "Rover controller and safe poweroff path installed."
