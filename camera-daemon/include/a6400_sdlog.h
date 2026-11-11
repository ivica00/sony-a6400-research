/* Optional crash-safe SD logging: policy, mount/verify state and helpers.
 *
 * Why this file exists (E0350): a battery pull is the only guaranteed recovery
 * from a wedged composite/USB session, and it wipes the camera RAM `/tmp_bt`
 * tmpfs that held the daemon log and receipt. The SD card is the only storage
 * that survives that pull, so the daemon may mirror its JSONL log and its final
 * receipt to a vfat card - but only under gates that make it impossible to touch
 * internal flash, to mount while the camera app owns the card, or to lose the
 * stream because of a slow/failed card.
 *
 * LAYERING
 *   - `a6400_sd_*` policy functions in src/sd_policy.c are PURE: no libc file
 *     descriptors, no syscalls, no clock. They are the part the host tests link.
 *   - src/sd_mount.c uses them plus open/mount/umount2/stat/read.
 *   - src/log.c mirrors each completed line to the second sink.
 *
 * EVIDENCE USED (read-only MSC observations, not re-probed here)
 *   - /dev/mmca = 250:10 and /dev/mmca1 = 250:11 exist (brw-rw-rw-); vfat is in
 *     /proc/filesystems. The SD partition node is `/dev/mmca1` (E0222).
 *   - In MSC /proc/mounts shows only internal-flash vfat mounts
 *     (/tmp,/etc,/system,/setting,/lens,/cert,/log on /dev/nflasha*) plus
 *     tmpfs /tmp_bt (1 MiB). The rootfs is ext2 read-only, so the mount point
 *     must be created under /tmp_bt (`/tmp_bt/sd`).
 *   - The camera app owns the SD in Mass Storage; the only safe window is after
 *     PC Remote (054c:0caa) is confirmed and before INIT/streaming.
 *   - E0222: /proc/mounts reports names/majors, so verification must accept only
 *     the exact `/dev/mmca1` device string and back it with a stat() block-node
 *     identity check (250:11), never a substring or a guessed drive letter.
 *   - E0236: the camera Fsys applies 8.3 limits, so every file name here is 8.3.
 */
#ifndef A6400_SDLOG_H
#define A6400_SDLOG_H

#include <stdint.h>

#define A6400_SD_DEV_DEFAULT   "/dev/mmca1"
#define A6400_SD_MOUNT_DEFAULT "/tmp_bt/sd"

/* 8.3 names (E0236). */
#define A6400_SD_LOG_NAME      "A6400LD.LOG"
#define A6400_SD_LOG_ROTATED   "A6400LD.1"
#define A6400_SD_RECEIPT_NAME  "A6400RCPT.JSON"
#define A6400_SD_SENTINEL_NAME "A6400SNT.TMP"

#define A6400_SD_LOG_ROTATE_BYTES (128u * 1024u)
#define A6400_SD_PATH_MAX   128u
#define A6400_SD_REASON_MAX 96u
#define A6400_SD_NAME_MAX   16u

/* The SD partition node is 250:11. E0222: never infer the device from a drive
 * letter or from a major/minor read out of /proc/mounts; this is the backing
 * identity check the mount helper performs with stat(). */
#define A6400_SD_BLK_MAJOR 250u
#define A6400_SD_BLK_MINOR 11u

/* Policy / helper result codes. Negative so callers can return plain errno too;
 * the receipt records the exact number. */
enum a6400_sd_rc {
    A6400_SD_OK = 0,
    A6400_SD_ERR_ARG = -1,
    A6400_SD_ERR_INTERNAL_FLASH = -2,
    A6400_SD_ERR_WRONG_DEVICE = -3,
    A6400_SD_ERR_NOT_ABSOLUTE = -4,
    A6400_SD_ERR_UNSAFE_PATH = -5,
    A6400_SD_ERR_OUTSIDE_TMP_BT = -6,
    A6400_SD_ERR_FORBIDDEN_MOUNT = -7,
    A6400_SD_ERR_NOT_83 = -8,
    A6400_SD_ERR_NO_CONSENT = -9,
    A6400_SD_ERR_DRY_RUN = -10,
    A6400_SD_ERR_MSC = -11,
    A6400_SD_ERR_PCREMOTE_UNCONFIRMED = -12,
    A6400_SD_ERR_AFTER_INIT = -13,
    A6400_SD_ERR_STREAMING = -14,
    A6400_SD_ERR_ALREADY_MOUNTED = -15,
    A6400_SD_ERR_NOT_BLOCK = -16,
    A6400_SD_ERR_DEVICE_IDENTITY = -17,
    A6400_SD_ERR_MOUNT = -18,
    A6400_SD_ERR_VERIFY = -19,
    A6400_SD_ERR_SENTINEL = -20,
    A6400_SD_ERR_IO = -21,
};

/* ---- pure policy (host-tested) ------------------------------------------- */

/* Accepts exactly `/dev/mmca1`. Refuses internal flash explicitly (nflasha*)
 * and fails closed for every other node, including the whole-card /dev/mmca. */
int a6400_sd_device_policy(const char *dev);

/* Mount point must be a real child of /tmp_bt: not /tmp_bt itself (that is the
 * tmpfs root holding the RAM receipt), no `..`, no `//`, no trailing slash, no
 * forbidden internal-flash mount points. */
int a6400_sd_mountpoint_policy(const char *mountpoint);

/* 8.3 name check: 1..8 base chars, optional '.' + 1..3 ext, no path parts. */
int a6400_sd_name_is_83(const char *name);

/* Mount-window gate. Allowed only when --sd-log AND --sd-mount are set, this is
 * not a dry run, the camera is NOT in Mass Storage, PC Remote has been
 * confirmed, and INIT/streaming have not started. */
struct a6400_sd_window {
    int sd_log;
    int sd_mount;
    int dry_run;
    int pcremote_confirmed; /* identity read 054c:0caa */
    int init_started;
    int streaming;
    int msc_mode;           /* 1 = Mass Storage / camera app owns the SD */
};

int a6400_sd_mount_window(const struct a6400_sd_window *w);

/* True when `incoming` bytes no longer fit under `cap` on a non-empty file.
 * A single line longer than the cap still rotates (the logger refuses such a
 * line long before this point). */
int a6400_sd_should_rotate(uint32_t written, uint32_t incoming, uint32_t cap);

/* Exact read-back comparison for the sentinel file. Returns 1 on an exact
 * length+byte match, 0 otherwise (a short read is a failure, never a pass). */
int a6400_sd_sentinel_matches(const char *readback, uint32_t read_len,
                              const char *expect, uint32_t expect_len);

/* Parses one /proc/mounts line into its (octal-unescaped) device and mount
 * point. Returns 1 when a line was parsed, 0 for an empty/short line, and a
 * negative code when a field does not fit. */
int a6400_sd_parse_mount_line(const char *line, char *dev, uint32_t dev_cap,
                              char *mountpoint, uint32_t mountpoint_cap);

/* 1 when the mount table already contains this device mounted at this exact
 * mount point; 0 when it does not; negative on argument error. */
int a6400_sd_mounts_contains(const char *mounts, const char *dev,
                             const char *mountpoint);

/* Bitmask of conflicts that make a mount unsafe:
 *   bit 0 = the device is already mounted anywhere
 *   bit 1 = the mount point is already used by another device
 * Returns 0 for "clean", negative on argument error. */
int a6400_sd_mounts_conflict(const char *mounts, const char *dev,
                             const char *mountpoint);

/* ---- mount / receipt state (camera-side) --------------------------------- */

struct a6400_sd_status {
    int      enabled;           /* --sd-log */
    int      mount_requested;   /* --sd-mount */
    int      attempted;
    int      mounted;           /* only 1 after mount + /proc/mounts + sentinel */
    int      device_ok;
    int      verified;          /* exact device+mountpoint in /proc/mounts */
    int      sentinel_ok;
    int      mount_rc;          /* 0 or a negative policy/errno code */
    int      unmount_rc;        /* 0 ok, negative errno, 1 = not attempted */
    int      unmount_attempted;
    int      open_rc;           /* SD log sink open result */
    int      sync_mode;         /* 1 = O_SYNC, 0 = fsync per line, -1 unknown */
    int      receipt_written;   /* 1 = A6400RCPT.JSON copied + fsynced */
    uint32_t errors;            /* failed opens/writes/verifications */
    uint32_t rotations;
    char     device[A6400_SD_PATH_MAX];
    char     mountpoint[A6400_SD_PATH_MAX];
    char     reason[A6400_SD_REASON_MAX];
};

void a6400_sd_status_init(struct a6400_sd_status *st, int enabled,
                          int mount_requested, const char *dev,
                          const char *mountpoint);

/* Runs the gate, validates the device/block identity and /proc/mounts, mkdir's
 * the /tmp_bt mount point, mounts vfat, re-reads /proc/mounts, then writes and
 * reads back a sentinel. Returns 0 ONLY when the mount is verified and the
 * sentinel matched; every other outcome is an explicit negative code with
 * `st->mounted == 0`. A failed verification unmounts what it just mounted. */
int a6400_sd_mount(struct a6400_sd_status *st, const struct a6400_sd_window *w);

/* Unmounts when mounted; tolerates failure and records it (mounted stays 1 when
 * the kernel still has it, so the receipt does not claim a clean unmount). */
int a6400_sd_unmount(struct a6400_sd_status *st);

/* Copies the receipt JSON to <mountpoint>/A6400RCPT.JSON with O_SYNC + fsync.
 * This is the durable receipt; failure is counted, never hidden. */
int a6400_sd_write_receipt(struct a6400_sd_status *st, const char *json,
                           uint32_t len);

#endif /* A6400_SDLOG_H */
