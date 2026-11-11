#!/bin/sh
# run_probe.sh - run the read-only UVC/DMA probe ON the camera (from /tmp_bt).
#
# This script runs on the CAMERA (BusyBox/POSIX sh), not on the host. It is
# deployed to /tmp_bt together with the probe binary; see probes/README.md for the
# host-side push/exec commands. It performs no deployment itself and never writes
# to internal flash.
#
#   OUT=/tmp_bt           default directory for the JSON report and the log
#   --sd                  additionally mirror the JSON report and log to a detected
#                         writable vfat mount among /mnt/sd, /mnt, /media/sd.
#                         Mounts backed by /dev/nflasha* (internal flash) and
#                         /setting are refused by name, never by guesswork.
#   --out DIR             put the report and log in DIR instead of /tmp_bt
#   --help                this text
#   anything else         passed through to the probe, e.g.
#                         --poll-get-jpeg 20 --i-understand-foreign-get-jpeg
#
# The script prints the receipt paths it wrote and exits with the probe's exit
# code (0 complete, 2 partial, 3 refused, 4 fatal). It never ignores that code.

set -u

PROBE=${PROBE:-/tmp_bt/uvc_dma_probe}
OUT=${OUT:-/tmp_bt}
MOUNTS=${MOUNTS:-/proc/mounts}   # overridable only so the script can be tested offline
MIRROR=0

usage() {
    sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
    case "$1" in
        --sd)
            MIRROR=1
            shift
            ;;
        --out)
            if [ $# -lt 2 ]; then
                echo "run_probe: --out needs a directory" >&2
                exit 3
            fi
            OUT=$2
            shift 2
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        --)
            shift
            break
            ;;
        *)
            break
            ;;
    esac
done

if [ ! -x "$PROBE" ]; then
    echo "run_probe: $PROBE is missing or not executable" >&2
    echo "run_probe: deploy it first (host side, see probes/README.md)" >&2
    exit 3
fi

if ! mkdir -p "$OUT" 2>/dev/null; then
    echo "run_probe: cannot create output directory $OUT" >&2
    exit 3
fi
if [ ! -w "$OUT" ]; then
    echo "run_probe: output directory $OUT is not writable" >&2
    exit 3
fi

JSON="$OUT/uvc_dma_probe.json"
LOG="$OUT/uvc_dma_probe.log"

echo "run_probe: probe $PROBE"
echo "run_probe: report $JSON"
echo "run_probe: log    $LOG"
echo "run_probe: observational mode unless a probe opt-in is passed below"

"$PROBE" --out "$JSON" "$@" >"$LOG" 2>&1
rc=$?

# Always show the probe's own log, then keep the exit code.
cat "$LOG"
echo "run_probe: probe exit code $rc"

if [ ! -s "$JSON" ]; then
    echo "run_probe: NO report at $JSON (probe did not emit JSON)" >&2
    if [ "$rc" -eq 0 ]; then
        rc=4
    fi
fi

# Locate a writable vfat mount, refusing internal flash by device name.
find_sd_mount() {
    for wanted in /mnt/sd /mnt /media/sd; do
        src=""
        fstype=""
        while read -r m_src m_mp m_type m_rest; do
            if [ "$m_mp" = "$wanted" ]; then
                src=$m_src
                fstype=$m_type
                break
            fi
        done < "$MOUNTS"
        [ -n "$src" ] || continue
        [ "$fstype" = "vfat" ] || continue
        case "$src" in
            /dev/nflasha*)
                echo "run_probe: refusing $wanted: $src is internal flash (nflasha)" >&2
                continue
                ;;
        esac
        case "$wanted" in
            /setting|/)
                echo "run_probe: refusing $wanted: internal setting/root" >&2
                continue
                ;;
        esac
        [ -d "$wanted" ] || continue
        [ -w "$wanted" ] || continue
        echo "$wanted"
        return 0
    done
    return 1
}

if [ "$MIRROR" -eq 1 ]; then
    if DEST=$(find_sd_mount); then
        ok=1
        if cp "$JSON" "$DEST/uvc_dma_probe.json" 2>/dev/null; then
            if cmp -s "$JSON" "$DEST/uvc_dma_probe.json"; then
                echo "run_probe: receipt $DEST/uvc_dma_probe.json (read-back identical)"
            else
                echo "run_probe: read-back MISMATCH at $DEST/uvc_dma_probe.json" >&2
                ok=0
            fi
        else
            echo "run_probe: copy of the report to $DEST failed" >&2
            ok=0
        fi
        if cp "$LOG" "$DEST/uvc_dma_probe.log" 2>/dev/null; then
            echo "run_probe: receipt $DEST/uvc_dma_probe.log"
        else
            echo "run_probe: copy of the log to $DEST failed" >&2
            ok=0
        fi
        if [ "$ok" -eq 0 ] && [ "$rc" -eq 0 ]; then
            rc=2   # the run itself may be fine, but the mirror is incomplete
        fi
    else
        echo "run_probe: --sd requested but no writable vfat mount among" >&2
        echo "run_probe: /mnt/sd, /mnt, /media/sd (or all are refused as internal)" >&2
        if [ "$rc" -eq 0 ]; then
            rc=2
        fi
    fi
else
    echo "run_probe: receipt $JSON"
    echo "run_probe: receipt $LOG"
fi

exit "$rc"
