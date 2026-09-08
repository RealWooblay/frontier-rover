#!/usr/bin/env bash
set -Eeuo pipefail

readonly WIFI_INTERFACE="wlan0"
readonly WIFI_COUNTRY="AU"
readonly JETSON_ADDRESS="192.168.50.2/24"
readonly USB_RECOVERY_ADDRESS="10.55.0.2/24"

usage() {
    echo "Usage: sudo $0 --ssid-file PATH --password-file PATH" >&2
    exit 2
}

[[ ${EUID} -eq 0 ]] || {
    echo "Run this script as root." >&2
    exit 1
}

[[ ${1:-} == "--ssid-file" && -n ${2:-} && \
   ${3:-} == "--password-file" && -n ${4:-} ]] || usage

ssid_file=$2
password_file=$4
[[ -r $ssid_file && -r $password_file ]] || {
    echo "The Wi-Fi credential files are missing." >&2
    exit 1
}

IFS= read -r wifi_ssid <"$ssid_file"
IFS= read -r wifi_password <"$password_file"
[[ -n $wifi_ssid ]] || {
    echo "The Wi-Fi SSID is empty." >&2
    exit 1
}
(( ${#wifi_password} >= 8 && ${#wifi_password} <= 63 )) || {
    echo "The Wi-Fi password must contain 8 to 63 characters." >&2
    exit 1
}

ssid_yaml=$(/usr/bin/python3 -c \
    'import json, sys; print(json.dumps(sys.argv[1]))' "$wifi_ssid")
password_yaml=$(/usr/bin/python3 -c \
    'import json, sys; print(json.dumps(sys.argv[1]))' "$wifi_password")

backup_dir="/var/backups/frontier-client-network-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$backup_dir"

for path in \
    /etc/netplan \
    /etc/systemd/network/25-frontier-wlan0.network \
    /etc/hostapd \
    /etc/default/hostapd \
    /etc/systemd/system/hostapd.service \
    /etc/systemd/system/hostapd.service.d; do
    if [[ -e $path || -L $path ]]; then
        cp -a "$path" "$backup_dir/" 2>/dev/null || true
    fi
done

old_services=(
    hostapd.service
    frontier-hotspot-bootstrap.service
    frontier-network-start.service
    frontier-wifi-recovery.service
    frontier-wifi-watchdog.service
    frontier-wifi-diagnostic.service
    frontier-usb-gadget.service
)

for service in "${old_services[@]}"; do
    systemctl disable --now "$service" >/dev/null 2>&1 || true
done

systemctl mask hostapd.service >/dev/null 2>&1 || true

rm -f \
    /etc/systemd/network/25-frontier-wlan0.network \
    /etc/systemd/system/hostapd.service.d/frontier.conf \
    /etc/systemd/system/frontier-hotspot-bootstrap.service \
    /etc/systemd/system/frontier-network-start.service \
    /etc/systemd/system/frontier-wifi-recovery.service \
    /etc/systemd/system/frontier-wifi-watchdog.service \
    /etc/systemd/system/frontier-wifi-diagnostic.service \
    /etc/systemd/system/frontier-usb-gadget.service \
    /usr/local/sbin/frontier-hotspot-bootstrap.sh \
    /usr/local/sbin/setup-frontier-hotspot.sh \
    /usr/local/sbin/frontier-wifi-watchdog.sh \
    /usr/local/sbin/frontier-wifi-diagnostic.sh

rmdir /etc/systemd/system/hostapd.service.d 2>/dev/null || true

cat >/etc/systemd/system/frontier-usb-recovery.service <<'EOF'
[Unit]
Description=Assign the Frontier USB recovery address
After=systemd-modules-load.service

[Service]
Type=oneshot
ExecStart=/sbin/modprobe g_ether
ExecStart=/bin/sh -c 'for i in $(seq 1 100); do test -e /sys/class/net/usb0 && exit 0; sleep 0.1; done; exit 1'
ExecStart=/usr/sbin/ip link set usb0 up
ExecStart=/usr/sbin/ip address replace 10.55.0.2/24 dev usb0
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 /etc/systemd/system/frontier-usb-recovery.service

install -d -m 0755 /etc/netplan /etc/cloud/cloud.cfg.d
find /etc/netplan -maxdepth 1 -type f -name '*.yaml' -delete

(
umask 077
cat >/etc/netplan/50-frontier.yaml <<EOF
network:
  version: 2
  renderer: networkd
  ethernets:
    eth0:
      dhcp4: true
      addresses:
        - ${JETSON_ADDRESS}
      optional: true
      dhcp4-overrides:
        route-metric: 200
    usb0:
      dhcp4: false
      addresses:
        - ${USB_RECOVERY_ADDRESS}
      optional: true
  wifis:
    ${WIFI_INTERFACE}:
      dhcp4: true
      optional: true
      regulatory-domain: ${WIFI_COUNTRY}
      dhcp4-overrides:
        route-metric: 100
      access-points:
        ${ssid_yaml}:
          password: ${password_yaml}
EOF
chmod 0600 /etc/netplan/50-frontier.yaml
)

cat >/etc/cloud/cloud.cfg.d/99-disable-network-config.cfg <<'EOF'
network: {config: disabled}
EOF
chmod 0644 /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg

hostnamectl set-hostname frontier-pi
if grep -qE '^127\.0\.1\.1[[:space:]]' /etc/hosts; then
    sed -i -E 's/^127\.0\.1\.1[[:space:]].*/127.0.1.1 frontier-pi/' /etc/hosts
else
    printf '127.0.1.1 frontier-pi\n' >>/etc/hosts
fi

cat >/etc/systemd/system/frontier-wifi-power-save.service <<'EOF'
[Unit]
Description=Disable Raspberry Pi Wi-Fi power saving
After=sys-subsystem-net-devices-wlan0.device
Wants=sys-subsystem-net-devices-wlan0.device

[Service]
Type=oneshot
ExecStart=/usr/sbin/iw dev wlan0 set power_save off
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
chmod 0644 /etc/systemd/system/frontier-wifi-power-save.service

systemctl daemon-reload
systemctl enable --now frontier-usb-recovery.service
systemctl enable frontier-wifi-power-save.service frontier-network-report.service

umask 022
/usr/sbin/netplan generate
/usr/sbin/netplan apply
/usr/bin/systemctl restart frontier-usb-recovery.service
/usr/sbin/iw reg set "$WIFI_COUNTRY" || true

wifi_address=""
for _ in $(seq 1 90); do
    wifi_address=$(/usr/sbin/ip -4 -o address show dev "$WIFI_INTERFACE" scope global 2>/dev/null | \
        /usr/bin/awk '{print $4}' | head -n 1)
    [[ -n $wifi_address ]] && break
    sleep 2
done

[[ -n $wifi_address ]] || {
    echo "Wi-Fi did not obtain an IPv4 address within three minutes." >&2
    exit 1
}

connected_ssid=$(/usr/sbin/iw dev "$WIFI_INTERFACE" link | \
    /usr/bin/sed -n 's/^[[:space:]]*SSID: //p')
[[ $connected_ssid == "$wifi_ssid" ]] || {
    echo "Wi-Fi joined '$connected_ssid' instead of '$wifi_ssid'." >&2
    exit 1
}

/usr/sbin/iw dev "$WIFI_INTERFACE" set power_save off

gateway=$(/usr/sbin/ip route show default dev "$WIFI_INTERFACE" | \
    /usr/bin/awk '/default via/{print $3; exit}')
[[ -n $gateway ]] || {
    echo "Wi-Fi has no default gateway." >&2
    exit 1
}
/usr/bin/ping -c 2 -W 3 "$gateway" >/dev/null
/usr/bin/getent ahostsv4 archive.ubuntu.com >/dev/null

if ! dpkg-query -W -f='${Status}\n' avahi-daemon 2>/dev/null | \
    grep -q 'install ok installed'; then
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y avahi-daemon
fi

systemctl enable --now avahi-daemon.service ssh.service
systemctl enable --now frontier-rover-control.service
systemctl restart frontier-rover-control.service

for _ in $(seq 1 30); do
    if /usr/bin/python3 -c \
        'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8765/", timeout=2).read(1)' \
        >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

/usr/bin/python3 -c \
    'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8765/", timeout=3).read(1)'

echo "Wi-Fi client network verified."
echo "SSID: $connected_ssid"
echo "Address: $wifi_address"
echo "Jetson Ethernet address: $JETSON_ADDRESS"
echo "Controller: http://frontier-pi.local:8765/"
echo "Backup: $backup_dir"

unset wifi_password password_yaml
sync
