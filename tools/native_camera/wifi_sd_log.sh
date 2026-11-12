#!/bin/sh
# Run from /tmp_bt with the Windows camera bound exclusively to libusb.
set -eu
mode=$1
case "$mode" in
    check) samples=24; name=WIFICHEK.LOG ;;
    capture) samples=720; name=WIFICRSH.LOG ;;
    *) exit 2 ;;
esac

[ "${2:-}" = exclusive-libusb ] || exit 2
device=/dev/mmca1
mountpoint=/tmp_bt/wifi-sd-log
status=/tmp_bt/wifi-sd-log.status
mounted=no

report() {
    printf '%s\n' "$*" >> "$status"
}

cleanup() {
    if [ "$mounted" = yes ]; then
        sync
        if umount "$mountpoint"; then
            report unmounted
        else
            report unmount_failed
            return
        fi
    fi
    rmdir "$mountpoint" 2>/dev/null || :
}

trap cleanup EXIT
trap 'exit 1' HUP INT TERM
: > "$status"
report "armed $mode"

# 250:11 is mmca10p1 in /proc/partitions and /dev/mmca1 on this camera.
grep -Eq '^[[:space:]]*250[[:space:]]+11[[:space:]]+[0-9]+[[:space:]]+mmca10p1$' /proc/partitions
[ -b "$device" ]
if grep -Eq '^/dev/mmca(1|10|10p1) ' /proc/mounts; then
    report card_already_mounted
    exit 1
fi
mkdir "$mountpoint"
mount -t vfat -o sync,dirsync "$device" "$mountpoint"
mounted=yes
grep -q "^$device $mountpoint vfat rw," /proc/mounts
log=$mountpoint/$name

# Never overwrite an earlier capture.
set -C
if [ -e "$log" ]; then report log_already_exists; exit 1; fi
printf 'A6400 Wi-Fi logger %s\n' "$mode" > "$log"
set +C
sync
report "mounted and synced $name"

previous=
i=0
while [ "$i" -lt "$samples" ]; do
    if grep -E '^/dev/mmca(1|10|10p1) ' /proc/mounts | grep -Fv " $mountpoint "; then
        report card_mount_conflict
        exit 1
    fi
    messages=$(dmesg -s 131072 | grep -Ei 'wlan|bcmdhd|sdio|mmcio|mmc_|cmd5|cmd52|cccr|hw_wrapper|exception|warmboot' || :)
    if [ "$messages" != "$previous" ]; then
        { printf '\n--- uptime '; cat /proc/uptime; printf '%s\n' "$messages"; } >> "$log"
        sync
        previous=$messages
    fi
    i=$((i + 1))
    /bin/busybox usleep 250000
done
printf '\nCapture ended\n' >> "$log"
sync
grep -q 'Capture ended' "$log"
report "verified $name"
