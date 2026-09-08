#!/usr/bin/env bash
set -euo pipefail

readonly SSID="Frontier-Rover"
readonly PI_ADDRESS="10.42.0.1/24"

usage() {
    echo "Usage: sudo $0 --password-stdin" >&2
    exit 2
}

[[ ${EUID} -eq 0 ]] || {
    echo "Run this script with sudo." >&2
    exit 1
}

[[ ${1:-} == "--password-stdin" ]] || usage
IFS= read -r hotspot_password

if (( ${#hotspot_password} < 8 || ${#hotspot_password} > 63 )); then
    echo "The hotspot password must contain 8 to 63 characters." >&2
    exit 1
fi

if [[ -r /proc/device-tree/model ]] && \
   ! tr -d '\0' </proc/device-tree/model | grep -q "Raspberry Pi 4"; then
    echo "This setup is approved only for the Raspberry Pi 4." >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y hostapd iw

backup_dir="/var/backups/frontier-hotspot-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"
for path in \
    /etc/netplan/50-cloud-init.yaml \
    /etc/hostapd/hostapd.conf \
    /etc/default/hostapd \
    /etc/systemd/network/25-frontier-wlan0.network; do
    if [[ -e "$path" ]]; then
        cp -a "$path" "$backup_dir/$(basename "$path")"
    fi
done

install -d -m 0755 /etc/hostapd /etc/systemd/network

cat >/etc/netplan/50-cloud-init.yaml <<'EOF'
network:
  version: 2
  renderer: networkd
  ethernets:
    eth0:
      dhcp4: true
      optional: true
    usb0:
      dhcp4: false
      addresses:
        - 10.55.0.2/24
      optional: true
EOF
chmod 0600 /etc/netplan/50-cloud-init.yaml

cat >/etc/systemd/network/25-frontier-wlan0.network <<EOF
[Match]
Name=wlan0

[Link]
RequiredForOnline=no

[Network]
Address=${PI_ADDRESS}
ConfigureWithoutCarrier=yes
DHCPServer=yes
IPv6AcceptRA=no
LinkLocalAddressing=no
IPv4Forwarding=yes
IPMasquerade=ipv4

[DHCPServer]
PoolOffset=20
PoolSize=40
DefaultLeaseTimeSec=1h
MaxLeaseTimeSec=24h
EmitDNS=yes
DNS=1.1.1.1 8.8.8.8
EmitNTP=no
EmitRouter=yes
EOF
chmod 0644 /etc/systemd/network/25-frontier-wlan0.network

cat >/etc/hostapd/hostapd.conf <<EOF
interface=wlan0
driver=nl80211
ssid=${SSID}
country_code=AU
ieee80211d=1
hw_mode=a
channel=36
ieee80211n=1
ieee80211ac=1
wmm_enabled=1
auth_algs=1
wpa=2
wpa_passphrase=${hotspot_password}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
EOF
chmod 0600 /etc/hostapd/hostapd.conf
unset hotspot_password

cat >/etc/default/hostapd <<'EOF'
DAEMON_CONF="/etc/hostapd/hostapd.conf"
EOF
chmod 0644 /etc/default/hostapd

install -d -m 0755 /etc/systemd/system/hostapd.service.d
cat >/etc/systemd/system/hostapd.service.d/frontier.conf <<'EOF'
[Unit]
After=systemd-networkd.service
Wants=systemd-networkd.service

[Service]
ExecStartPre=-/usr/sbin/rfkill unblock wlan
ExecStartPre=-/usr/sbin/iw reg set AU
ExecStartPost=-/usr/sbin/iw dev wlan0 set power_save off
EOF

netplan generate
systemctl unmask hostapd
systemctl enable hostapd

echo "Hotspot configuration installed."
echo "Backup: $backup_dir"
echo "After reboot, connect to $SSID and open http://10.42.0.1:8765/."
