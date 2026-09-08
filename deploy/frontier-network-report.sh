#!/usr/bin/env bash
set -u

readonly STATUS_FILE=/boot/firmware/frontier-network-status.txt
readonly TEMP_FILE=/run/frontier-network-status.txt

wifi_address=""
for _ in $(seq 1 60); do
    wifi_address=$(/usr/sbin/ip -4 -o address show dev wlan0 scope global 2>/dev/null | \
        /usr/bin/awk '{print $4}' | head -n 1)
    [[ -n $wifi_address ]] && break
    sleep 2
done

{
    printf 'timestamp=%s\n' "$(date -Is)"
    printf 'hostname=%s\n' "$(hostname)"
    printf 'wifi_address=%s\n' "${wifi_address:-NONE}"
    printf 'wifi_link='; /usr/sbin/iw dev wlan0 link 2>&1 | tr '\n' ' '; echo
    printf 'wifi_power_save='; /usr/sbin/iw dev wlan0 get power_save 2>&1 || true
    printf 'routes:\n'; /usr/sbin/ip -4 route || true
    printf 'ssh=%s\n' "$(systemctl is-active ssh.service 2>/dev/null || true)"
    printf 'controller=%s\n' "$(systemctl is-active frontier-rover-control.service 2>/dev/null || true)"
    printf 'avahi=%s\n' "$(systemctl is-active avahi-daemon.service 2>/dev/null || true)"
    printf 'hostapd=%s\n' "$(systemctl is-active hostapd.service 2>/dev/null || true)"
    printf 'failed_units:\n'; systemctl --failed --no-pager || true
    printf 'power_status='; vcgencmd get_throttled 2>&1 || true
    printf 'kernel_power_or_storage_events:\n'
    journalctl -b -k --no-pager 2>/dev/null | \
        grep -Ei 'under.?voltage|voltage normalised|mmc.*error|I/O error' | tail -n 30 || true
} >"$TEMP_FILE"

install -m 0644 "$TEMP_FILE" "$STATUS_FILE"
sync
