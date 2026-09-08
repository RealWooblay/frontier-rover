#!/bin/zsh
set -euo pipefail

export PATH=/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/opt/homebrew/sbin

readonly WHOLE_DISK=/dev/disk4
readonly BOOT_DEVICE=/dev/disk4s1
readonly ROOT_DEVICE=/dev/disk4s2
readonly BOOT_VOLUME=/Volumes/system-boot
readonly EXPECTED_SIZE='127.9 GB'
readonly EXPECTED_SSID='Optus_8DC016_5GHz'
readonly DISKUTIL=/usr/sbin/diskutil
readonly DEBUGFS=/opt/homebrew/opt/e2fsprogs/sbin/debugfs
readonly E2FSCK=/opt/homebrew/opt/e2fsprogs/sbin/e2fsck
readonly DEPLOY_DIR=/Users/jackcoleman/Developer/frontier-rover/deploy

readonly SETUP_SOURCE=$DEPLOY_DIR/setup-frontier-client-network.sh
readonly BOOTSTRAP_SOURCE=$DEPLOY_DIR/frontier-network-bootstrap.sh
readonly BOOTSTRAP_SERVICE_SOURCE=$DEPLOY_DIR/frontier-network-bootstrap.service
readonly REPORT_SOURCE=$DEPLOY_DIR/frontier-network-report.sh
readonly REPORT_SERVICE_SOURCE=$DEPLOY_DIR/frontier-network-report.service
readonly USB_RECOVERY_SERVICE_SOURCE=$DEPLOY_DIR/frontier-usb-recovery.service

readonly SETUP_REMOTE=/usr/local/sbin/setup-frontier-client-network.sh
readonly BOOTSTRAP_REMOTE=/usr/local/sbin/frontier-network-bootstrap.sh
readonly BOOTSTRAP_SERVICE_REMOTE=/etc/systemd/system/frontier-network-bootstrap.service
readonly REPORT_REMOTE=/usr/local/sbin/frontier-network-report.sh
readonly REPORT_SERVICE_REMOTE=/etc/systemd/system/frontier-network-report.service
readonly SSID_REMOTE=/etc/frontier-wifi-ssid
readonly PASSWORD_REMOTE=/etc/frontier-wifi-password
readonly NETPLAN_REMOTE=/etc/netplan/50-frontier.yaml

[[ $EUID -eq 0 ]] || {
    echo "Run this script with sudo."
    exit 1
}

for required_path in "$DEBUGFS" "$E2FSCK" "$SETUP_SOURCE" "$BOOTSTRAP_SOURCE" \
    "$BOOTSTRAP_SERVICE_SOURCE" "$REPORT_SOURCE" "$REPORT_SERVICE_SOURCE" \
    "$USB_RECOVERY_SERVICE_SOURCE"; do
    [[ -e $required_path ]] || {
        echo "Required file is missing: $required_path"
        exit 1
    }
done

[[ -b $WHOLE_DISK && -b $BOOT_DEVICE && -b $ROOT_DEVICE ]] || {
    echo "The expected Raspberry Pi card is not /dev/disk4. Nothing was changed."
    exit 1
}

disk_info=$("$DISKUTIL" info "$WHOLE_DISK")
print -r -- "$disk_info" | grep -q 'Device Location:.*External'
print -r -- "$disk_info" | grep -q "Disk Size:.*${EXPECTED_SIZE}"

disk_layout=$("$DISKUTIL" list "$WHOLE_DISK")
print -r -- "$disk_layout" | grep -q 'Windows_FAT_32 system-boot'
print -r -- "$disk_layout" | grep -q 'Linux.*disk4s2'

"$DISKUTIL" mount "$BOOT_DEVICE" >/dev/null 2>&1 || true
[[ -f $BOOT_VOLUME/network-config ]] || {
    echo "The existing boot network configuration is missing. Nothing was changed."
    exit 1
}

wifi_password=$(/usr/bin/awk -v wanted="$EXPECTED_SSID" '
    index($0, "\"" wanted "\"") { found=1; next }
    found && /password:/ {
        value=$0
        sub(/^[^:]*:[[:space:]]*/, "", value)
        gsub(/^\"|\"$/, "", value)
        print value
        exit
    }
' "$BOOT_VOLUME/network-config")

(( ${#wifi_password} >= 8 && ${#wifi_password} <= 63 )) || {
    echo "Could not read the exact 5 GHz Wi-Fi password. Nothing was changed."
    exit 1
}

stamp=$(date +%Y%m%d-%H%M%S)
backup=/private/tmp/frontier-network-backup-$stamp
work=/private/tmp/frontier-network-work-$stamp
mkdir -m 0700 "$backup" "$work"

cleanup() {
    rm -rf "$work"
}
trap cleanup EXIT

print -r -- "$EXPECTED_SSID" >"$work/ssid"
print -r -- "$wifi_password" >"$work/password"
chmod 0600 "$work/ssid" "$work/password"

ssid_yaml=$(/usr/bin/python3 -c \
    'import json, sys; print(json.dumps(sys.argv[1]))' "$EXPECTED_SSID")
password_yaml=$(/usr/bin/python3 -c \
    'import json, sys; print(json.dumps(sys.argv[1]))' "$wifi_password")

cat >"$work/50-frontier.yaml" <<EOF
network:
  version: 2
  renderer: networkd
  ethernets:
    eth0:
      dhcp4: true
      addresses:
        - 192.168.50.2/24
      optional: true
      dhcp4-overrides:
        route-metric: 200
    usb0:
      dhcp4: false
      addresses:
        - 10.55.0.2/24
      optional: true
  wifis:
    wlan0:
      dhcp4: true
      optional: true
      regulatory-domain: AU
      dhcp4-overrides:
        route-metric: 100
      access-points:
        ${ssid_yaml}:
          password: ${password_yaml}
EOF
chmod 0600 "$work/50-frontier.yaml"

cat >"$work/99-disable-network-config.cfg" <<'EOF'
network: {config: disabled}
EOF
chmod 0644 "$work/99-disable-network-config.cfg"

unset wifi_password password_yaml

echo "1/6 Backing up the visible boot configuration."
cp -a "$BOOT_VOLUME/network-config" "$backup/network-config"
cp -a "$BOOT_VOLUME/user-data" "$backup/user-data" 2>/dev/null || true
cp -a "$BOOT_VOLUME/frontier-hotspot-status.txt" "$backup/" 2>/dev/null || true

echo "2/6 Unmounting and checking the Linux filesystem."
"$DISKUTIL" unmountDisk "$WHOLE_DISK"
set +e
"$E2FSCK" -fy "$ROOT_DEVICE"
fsck_result=$?
set -e
if (( fsck_result > 1 )); then
    echo "Filesystem repair failed with status $fsck_result. No network files were written."
    exit 1
fi

dump_if_present() {
    local remote=$1
    local name=${remote//\//_}
    "$DEBUGFS" -R "dump -p $remote $backup/$name" "$ROOT_DEVICE" >/dev/null 2>&1 || true
}

replace_file() {
    local source=$1
    local remote=$2
    local mode=$3
    local uid=${4:-0}
    local gid=${5:-0}

    "$DEBUGFS" -w -R "rm $remote" "$ROOT_DEVICE" >/dev/null 2>&1 || true
    "$DEBUGFS" -w -R "write $source $remote" "$ROOT_DEVICE" >/dev/null
    "$DEBUGFS" -w -R "set_inode_field $remote mode $mode" "$ROOT_DEVICE" >/dev/null
    "$DEBUGFS" -w -R "set_inode_field $remote uid $uid" "$ROOT_DEVICE" >/dev/null
    "$DEBUGFS" -w -R "set_inode_field $remote gid $gid" "$ROOT_DEVICE" >/dev/null
}

remove_file() {
    "$DEBUGFS" -w -R "rm $1" "$ROOT_DEVICE" >/dev/null 2>&1 || true
}

make_symlink() {
    local link=$1
    local target=$2
    remove_file "$link"
    "$DEBUGFS" -w -R "symlink $link $target" "$ROOT_DEVICE" >/dev/null
}

verify_file() {
    local source=$1
    local remote=$2
    local output=$work/${remote//\//_}.verify
    "$DEBUGFS" -R "dump -p $remote $output" "$ROOT_DEVICE" >/dev/null
    cmp -s "$source" "$output" || {
        echo "Verification failed for $remote. Do not boot the card."
        exit 1
    }
}

echo "3/6 Backing up the active Linux network configuration."
for remote in \
    /etc/netplan/50-cloud-init.yaml \
    /etc/netplan/50-frontier.yaml \
    /etc/netplan/99-wifi-recovery.yaml \
    /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg \
    /etc/systemd/network/25-frontier-wlan0.network \
    /etc/hostapd/hostapd.conf \
    /etc/default/hostapd \
    /etc/systemd/system/hostapd.service \
    /etc/systemd/system/frontier-hotspot-bootstrap.service \
    /etc/systemd/system/frontier-network-start.service \
    /etc/systemd/system/frontier-wifi-recovery.service \
    /etc/systemd/system/frontier-wifi-watchdog.service \
    /etc/systemd/system/frontier-wifi-diagnostic.service \
    /etc/systemd/system/frontier-usb-gadget.service; do
    dump_if_present "$remote"
done
"$DEBUGFS" -R 'ls -l /etc/netplan' "$ROOT_DEVICE" >"$backup/netplan-list.txt" 2>&1 || true
"$DEBUGFS" -R 'ls -l /etc/systemd/system/multi-user.target.wants' "$ROOT_DEVICE" \
    >"$backup/enabled-services-list.txt" 2>&1 || true

echo "4/6 Installing one authoritative network configuration."
for remote in \
    /etc/netplan/50-cloud-init.yaml \
    /etc/netplan/50-frontier.yaml \
    /etc/netplan/99-wifi-recovery.yaml; do
    remove_file "$remote"
done

replace_file "$work/50-frontier.yaml" "$NETPLAN_REMOTE" 0100600
replace_file \
    "$work/99-disable-network-config.cfg" \
    /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg \
    0100644
replace_file "$SETUP_SOURCE" "$SETUP_REMOTE" 0100755
replace_file "$BOOTSTRAP_SOURCE" "$BOOTSTRAP_REMOTE" 0100755
replace_file "$BOOTSTRAP_SERVICE_SOURCE" "$BOOTSTRAP_SERVICE_REMOTE" 0100644
replace_file "$REPORT_SOURCE" "$REPORT_REMOTE" 0100755
replace_file "$REPORT_SERVICE_SOURCE" "$REPORT_SERVICE_REMOTE" 0100644
replace_file \
    "$USB_RECOVERY_SERVICE_SOURCE" \
    /etc/systemd/system/frontier-usb-recovery.service \
    0100644
replace_file "$work/ssid" "$SSID_REMOTE" 0100600
replace_file "$work/password" "$PASSWORD_REMOTE" 0100600

for remote in \
    /etc/systemd/network/25-frontier-wlan0.network \
    /etc/systemd/system/multi-user.target.wants/hostapd.service \
    /etc/systemd/system/multi-user.target.wants/frontier-hotspot-bootstrap.service \
    /etc/systemd/system/multi-user.target.wants/frontier-network-start.service \
    /etc/systemd/system/multi-user.target.wants/frontier-wifi-recovery.service \
    /etc/systemd/system/multi-user.target.wants/frontier-wifi-watchdog.service \
    /etc/systemd/system/multi-user.target.wants/frontier-wifi-diagnostic.service \
    /etc/systemd/system/multi-user.target.wants/frontier-usb-gadget.service; do
    remove_file "$remote"
done

make_symlink /etc/systemd/system/hostapd.service /dev/null
make_symlink \
    /etc/systemd/system/multi-user.target.wants/frontier-network-bootstrap.service \
    ../frontier-network-bootstrap.service
make_symlink \
    /etc/systemd/system/multi-user.target.wants/frontier-network-report.service \
    ../frontier-network-report.service
make_symlink \
    /etc/systemd/system/multi-user.target.wants/frontier-usb-recovery.service \
    ../frontier-usb-recovery.service

echo "5/6 Verifying every installed file and the ext4 filesystem."
verify_file "$work/50-frontier.yaml" "$NETPLAN_REMOTE"
verify_file \
    "$work/99-disable-network-config.cfg" \
    /etc/cloud/cloud.cfg.d/99-disable-network-config.cfg
verify_file "$SETUP_SOURCE" "$SETUP_REMOTE"
verify_file "$BOOTSTRAP_SOURCE" "$BOOTSTRAP_REMOTE"
verify_file "$BOOTSTRAP_SERVICE_SOURCE" "$BOOTSTRAP_SERVICE_REMOTE"
verify_file "$REPORT_SOURCE" "$REPORT_REMOTE"
verify_file "$REPORT_SERVICE_SOURCE" "$REPORT_SERVICE_REMOTE"
verify_file \
    "$USB_RECOVERY_SERVICE_SOURCE" \
    /etc/systemd/system/frontier-usb-recovery.service
verify_file "$work/ssid" "$SSID_REMOTE"
verify_file "$work/password" "$PASSWORD_REMOTE"

"$DEBUGFS" -R 'stat /etc/systemd/system/hostapd.service' "$ROOT_DEVICE" 2>&1 | \
    grep -q '/dev/null' || {
        echo "Verification failed: hostapd is not masked. Do not boot the card."
        exit 1
    }
"$DEBUGFS" -R \
    'stat /etc/systemd/system/multi-user.target.wants/frontier-network-bootstrap.service' \
    "$ROOT_DEVICE" 2>&1 | grep -q 'frontier-network-bootstrap.service' || {
    echo "Verification failed: the one-time bootstrap is not enabled."
    exit 1
}
"$DEBUGFS" -R \
    'stat /etc/systemd/system/multi-user.target.wants/frontier-usb-recovery.service' \
    "$ROOT_DEVICE" 2>&1 | grep -q 'frontier-usb-recovery.service' || {
        echo "Verification failed: USB recovery is not enabled."
        exit 1
    }

set +e
"$E2FSCK" -fn "$ROOT_DEVICE"
verify_fs_result=$?
set -e
if (( verify_fs_result != 0 )); then
    echo "Post-write filesystem verification failed. Do not boot the card."
    exit 1
fi

echo "6/6 Removing the obsolete first-boot Wi-Fi seed and ejecting safely."
"$DISKUTIL" mount "$BOOT_DEVICE" >/dev/null
rm -f \
    "$BOOT_VOLUME/network-config" \
    "$BOOT_VOLUME/frontier-hotspot-status.txt" \
    "$BOOT_VOLUME/frontier-network-install.txt" \
    "$BOOT_VOLUME/frontier-network-status.txt"

cat >"$BOOT_VOLUME/frontier-network-plan.txt" <<'EOF'
Normal control: Mac and Pi join Optus_8DC016_5GHz.
Controller: http://frontier-pi.local:8765/
SSH: ssh rover@frontier-pi.local
Jetson direct Ethernet: Jetson 192.168.50.1, Pi 192.168.50.2.
The Pi is not configured as a Wi-Fi hotspot.
EOF

sync
"$DISKUTIL" eject "$WHOLE_DISK"

echo "Network repair installed and verified."
echo "Backup: $backup"
echo "The card has been safely ejected."
