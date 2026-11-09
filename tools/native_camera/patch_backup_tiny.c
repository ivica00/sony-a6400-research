/* Freestanding tiny ARM Linux patch utility for /setting/Backup.bin */

#define SYS_exit   1
#define SYS_read   3
#define SYS_write  4
#define SYS_open   5
#define SYS_close  6
#define SYS_lseek  19
#define SYS_sync   36

#define O_RDONLY 0
#define O_RDWR   2

#define SEEK_SET 0

#define EXPECTED_SIZE 1171036
#define OFF_CHECKSUM 32
#define OFF_FORCE_BACKUP 1145720
#define OFF_DEFAULT_WIDTH_HI 1145723

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

static void print_str(const char *s) {
    int len = 0;
    while (s[len]) len++;
    sys_write(1, s, len);
}

static void print_hex2(unsigned char b) {
    char h[2];
    const char *hex = "0123456789abcdef";
    h[0] = hex[(b >> 4) & 0xf];
    h[1] = hex[b & 0xf];
    sys_write(1, h, 2);
}

void main2(int argc, char **argv);

__attribute__((naked)) void _start(void) {
    __asm__ __volatile__(
        "mov r2, sp\n"
        "ldr r0, [r2]\n"       /* r0 = argc */
        "add r1, r2, #4\n"     /* r1 = argv */
        "b main2\n"
    );
}

void main2(int argc, char **argv) {
    if (argc < 2) {
        print_str("Usage: patch_backup [check|apply|revert]\n");
        sys_exit(1);
    }

    const char *cmd = argv[1];
    int is_apply = (cmd[0] == 'a');
    int is_revert = (cmd[0] == 'r');
    int is_check = (cmd[0] == 'c');

    int fd = sys_open("/setting/Backup.bin", is_check ? O_RDONLY : O_RDWR, 0);
    if (fd < 0) {
        print_str("ERR: cannot open /setting/Backup.bin\n");
        sys_exit(2);
    }

    int sz = sys_lseek(fd, 0, 2); // SEEK_END
    if (sz != EXPECTED_SIZE) {
        print_str("ERR: unexpected size\n");
        sys_close(fd);
        sys_exit(3);
    }

    unsigned char b_chk = 0, b_force = 0, b_width_hi = 0;

    sys_lseek(fd, OFF_CHECKSUM, SEEK_SET);
    sys_read(fd, &b_chk, 1);

    sys_lseek(fd, OFF_FORCE_BACKUP, SEEK_SET);
    sys_read(fd, &b_force, 1);

    sys_lseek(fd, OFF_DEFAULT_WIDTH_HI, SEEK_SET);
    sys_read(fd, &b_width_hi, 1);

    print_str("Backup.bin state: chk=");
    print_hex2(b_chk);
    print_str(" force=");
    print_hex2(b_force);
    print_str(" width_hi=");
    print_hex2(b_width_hi);
    print_str("\n");

    if (is_check) {
        if (b_chk == 0x25 && b_force == 0x00 && b_width_hi == 0x02) {
            print_str("STATUS: ORIGINAL (640x480 LiveView, force_backup=0)\n");
        } else if (b_chk == 0x2b && b_force == 0x01 && b_width_hi == 0x07) {
            print_str("STATUS: PATCHED (1920x1080 LiveView, force_backup=1)\n");
        } else {
            print_str("STATUS: UNKNOWN\n");
        }
        sys_close(fd);
        sys_exit(0);
    }

    if (is_apply) {
        if (b_chk != 0x25 || b_force != 0x00 || b_width_hi != 0x02) {
            print_str("ERR: preimage mismatch for apply!\n");
            sys_close(fd);
            sys_exit(4);
        }
        b_chk = 0x2b;
        b_force = 0x01;
        b_width_hi = 0x07;

        sys_lseek(fd, OFF_CHECKSUM, SEEK_SET);
        sys_write(fd, &b_chk, 1);

        sys_lseek(fd, OFF_FORCE_BACKUP, SEEK_SET);
        sys_write(fd, &b_force, 1);

        sys_lseek(fd, OFF_DEFAULT_WIDTH_HI, SEEK_SET);
        sys_write(fd, &b_width_hi, 1);

        sys_close(fd);
        sys_sync();
        print_str("SUCCESS: 1080p LiveView patch applied\n");
        sys_exit(0);
    }

    if (is_revert) {
        if (b_chk != 0x2b || b_force != 0x01 || b_width_hi != 0x07) {
            print_str("ERR: preimage mismatch for revert!\n");
            sys_close(fd);
            sys_exit(5);
        }
        b_chk = 0x25;
        b_force = 0x00;
        b_width_hi = 0x02;

        sys_lseek(fd, OFF_CHECKSUM, SEEK_SET);
        sys_write(fd, &b_chk, 1);

        sys_lseek(fd, OFF_FORCE_BACKUP, SEEK_SET);
        sys_write(fd, &b_force, 1);

        sys_lseek(fd, OFF_DEFAULT_WIDTH_HI, SEEK_SET);
        sys_write(fd, &b_width_hi, 1);

        sys_close(fd);
        sys_sync();
        print_str("SUCCESS: Reverted to ORIGINAL\n");
        sys_exit(0);
    }

    sys_close(fd);
    sys_exit(0);
}
