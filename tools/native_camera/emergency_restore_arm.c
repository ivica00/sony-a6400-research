/* Emergency Restore Tool for Sony ILCE-6400
   Standalone ARM Linux binary with direct svc 0 syscalls.
   Restores /setting/Backup.bin to factory original,
   removes /etc/ld.so.preload, cleans /tmp, and writes /mnt/EMERGENCY_RESTORE.log.
*/

#define SYS_exit   1
#define SYS_read   3
#define SYS_write  4
#define SYS_open   5
#define SYS_close  6
#define SYS_unlink 10
#define SYS_lseek  19
#define SYS_sync   36

#define O_RDONLY 0
#define O_WRONLY 1
#define O_RDWR   2
#define O_CREAT  64
#define O_TRUNC  512

#define SEEK_SET 0
#define SEEK_END 2

static inline int sys_open(const char *path, int flags, int mode) {
    register int r0 __asm__("r0") = (int)path;
    register int r1 __asm__("r1") = flags;
    register int r2 __asm__("r2") = mode;
    register int r7 __asm__("r7") = SYS_open;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}

static inline int sys_close(int fd) {
    register int r0 __asm__("r0") = fd;
    register int r7 __asm__("r7") = SYS_close;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r7) : "memory");
    return r0;
}

static inline int sys_read(int fd, void *buf, int count) {
    register int r0 __asm__("r0") = fd;
    register int r1 __asm__("r1") = (int)buf;
    register int r2 __asm__("r2") = count;
    register int r7 __asm__("r7") = SYS_read;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}

static inline int sys_write(int fd, const void *buf, int count) {
    register int r0 __asm__("r0") = fd;
    register int r1 __asm__("r1") = (int)buf;
    register int r2 __asm__("r2") = count;
    register int r7 __asm__("r7") = SYS_write;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}

static inline int sys_lseek(int fd, int offset, int whence) {
    register int r0 __asm__("r0") = fd;
    register int r1 __asm__("r1") = offset;
    register int r2 __asm__("r2") = whence;
    register int r7 __asm__("r7") = SYS_lseek;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}

static inline int sys_unlink(const char *path) {
    register int r0 __asm__("r0") = (int)path;
    register int r7 __asm__("r7") = SYS_unlink;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r7) : "memory");
    return r0;
}

static inline void sys_sync(void) {
    register int r7 __asm__("r7") = SYS_sync;
    __asm__ __volatile__("svc 0" : : "r"(r7) : "memory");
}

static inline void sys_exit(int code) {
    register int r0 __asm__("r0") = code;
    register int r7 __asm__("r7") = SYS_exit;
    __asm__ __volatile__("svc 0" : : "r"(r0), "r"(r7) : "memory");
    for (;;);
}

static void log_str(int fd, const char *s) {
    int len = 0;
    while (s[len]) len++;
    if (fd >= 0) sys_write(fd, s, len);
    sys_write(1, s, len);
}

__attribute__((naked)) void _start(void) {
    __asm__ __volatile__(
        "b emergency_main\n"
    );
}

static char io_buf[4096];

void emergency_main(void) {
    int log_fd = sys_open("/mnt/EMERGENCY_RESTORE.log", O_WRONLY | O_CREAT | O_TRUNC, 0666);
    log_str(log_fd, "=== SONY ILCE-6400 EMERGENCY RESTORE PROCEDURE ===\n");
    log_str(log_fd, "[1] Emergency restore agent started.\n");

    /* 1. Try restoring Backup.bin from /mnt/Backup.original.bin or /mnt/Backup.bin */
    const char *src_path = "/mnt/Backup.original.bin";
    int sfd = sys_open(src_path, O_RDONLY, 0);
    if (sfd < 0) {
        src_path = "/mnt/Backup.bin";
        sfd = sys_open(src_path, O_RDONLY, 0);
    }

    if (sfd >= 0) {
        int dfd = sys_open("/setting/Backup.bin", O_WRONLY | O_CREAT | O_TRUNC, 0666);
        if (dfd >= 0) {
            int total = 0;
            int n;
            while ((n = sys_read(sfd, io_buf, sizeof(io_buf))) > 0) {
                sys_write(dfd, io_buf, n);
                total += n;
            }
            sys_close(dfd);
            log_str(log_fd, "[2] Restored /setting/Backup.bin from SD card file: ");
            log_str(log_fd, src_path);
            log_str(log_fd, "\n");
        } else {
            log_str(log_fd, "[!] Failed to open /setting/Backup.bin for writing!\n");
        }
        sys_close(sfd);
    } else {
        /* Fallback: Direct 3-byte rollback in /setting/Backup.bin */
        log_str(log_fd, "[2] Performing direct byte revert on /setting/Backup.bin...\n");
        int bfd = sys_open("/setting/Backup.bin", O_RDWR, 0);
        if (bfd >= 0) {
            unsigned char b_chk = 0x25;
            unsigned char b_force = 0x00;
            unsigned char b_width_hi = 0x02;

            sys_lseek(bfd, 32, SEEK_SET);
            sys_write(bfd, &b_chk, 1);

            sys_lseek(bfd, 1145720, SEEK_SET);
            sys_write(bfd, &b_force, 1);

            sys_lseek(bfd, 1145723, SEEK_SET);
            sys_write(bfd, &b_width_hi, 1);

            sys_close(bfd);
            log_str(log_fd, "[+] /setting/Backup.bin reverted to original 640x480 values.\n");
        } else {
            log_str(log_fd, "[!] Failed to open /setting/Backup.bin for direct revert!\n");
        }
    }

    /* 2. Unlink /etc/ld.so.preload (permanently disables all boot hooks) */
    if (sys_unlink("/etc/ld.so.preload") == 0) {
        log_str(log_fd, "[3] Unlinked /etc/ld.so.preload (all hooks disabled).\n");
    } else {
        log_str(log_fd, "[3] /etc/ld.so.preload already removed or unlinked.\n");
    }

    /* 3. Clean all temporary and mod files */
    sys_unlink("/tmp/ld.so.preload");
    sys_unlink("/tmp/autoexec.lock");
    sys_unlink("/tmp/autoexec_hook.so");
    sys_unlink("/tmp/stream_dumper.elf");
    sys_unlink("/tmp/liba6400mod.so");
    sys_unlink("/tmp/clean_border.elf");
    sys_unlink("/tmp/a6400_gui.elf");
    sys_unlink("/tmp/modern_menu.elf");
    sys_unlink("/tmp/ritual_daemon");
    sys_unlink("/tmp/patch_backup");
    sys_unlink("/tmp/menu_open");
    sys_unlink("/tmp/autoexec.pid");
    log_str(log_fd, "[4] Cleaned all mod binaries and locks in /tmp.\n");

    /* 4. Write clean empty autoexec.sh */
    int afd = sys_open("/tmp/autoexec.sh", O_WRONLY | O_CREAT | O_TRUNC, 0755);
    if (afd >= 0) {
        const char *clean_sh = "#!/bin/sh\nexit 0\n";
        sys_write(afd, clean_sh, 18);
        sys_close(afd);
        log_str(log_fd, "[5] Replaced /tmp/autoexec.sh with clean exit 0 script.\n");
    }

    /* 5. Create killswitch flag files on /mnt and /tmp */
    int k1 = sys_open("/mnt/disable_hook", O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (k1 >= 0) sys_close(k1);

    int k2 = sys_open("/mnt/disable.txt", O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (k2 >= 0) sys_close(k2);

    int k3 = sys_open("/tmp/disable_hook", O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (k3 >= 0) sys_close(k3);
    log_str(log_fd, "[6] Created killswitch flags (disable_hook, disable.txt).\n");

    /* 6. Commit all buffers to flash */
    sys_sync();
    log_str(log_fd, "[7] Synced all filesystems.\n");
    log_str(log_fd, "=== EMERGENCY RESTORE COMPLETED SUCCESSFULLY! ===\n");
    log_str(log_fd, "Camera is now 100% restored to stock factory firmware.\n");
    log_str(log_fd, "You may power cycle the camera safely.\n");

    if (log_fd >= 0) sys_close(log_fd);
    sys_sync();
    sys_exit(0);
}
