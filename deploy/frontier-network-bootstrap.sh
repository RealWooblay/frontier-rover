#!/usr/bin/env bash
set -Eeuo pipefail

readonly STATUS_FILE=/boot/firmware/frontier-network-install.txt
readonly SETUP_SCRIPT=/usr/local/sbin/setup-frontier-client-network.sh
readonly SSID_FILE=/etc/frontier-wifi-ssid
readonly PASSWORD_FILE=/etc/frontier-wifi-password

exec > >(tee "$STATUS_FILE") 2>&1

failure() {
    result=$?
    printf '[%s] FAILED with status %s.\n' "$(date -Is)" "$result"
    sync
    exit "$result"
}
trap failure ERR

printf '[%s] Starting the one-time network convergence.\n' "$(date -Is)"
"$SETUP_SCRIPT" --ssid-file "$SSID_FILE" --password-file "$PASSWORD_FILE"

rm -f "$SSID_FILE" "$PASSWORD_FILE"
systemctl disable frontier-network-bootstrap.service
/usr/local/sbin/frontier-network-report.sh

printf '[%s] READY. The Pi is a home Wi-Fi client, not a hotspot.\n' "$(date -Is)"
sync
