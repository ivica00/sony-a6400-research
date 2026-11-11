/*
 * uvc_dma_probe.c - bounded READ-ONLY ARMv7 diagnostic for the ILCE-6400
 * liveview / DMA frame-source question.
 *
 * WHAT THIS IS
 *   A single freestanding ELF (direct `svc 0` syscalls, no libc) meant to be
 *   copied to /tmp_bt on the camera and executed from RAM.  Its DEFAULT mode is
 *   purely observational: it reads /proc, /sys, /dev directory entries and device
 *   node metadata, and emits one JSON report.  It never writes camera state, never
 *   opens a device node for I/O, never mmaps /dev/mem, and never scans memory.
 *
 * WHY (evidence)
 *   The frame source for a <35 ms liveview transport is the Scalar GET_JPEG ring
 *   behind OSAL queue 0x0167046a: artifacts/analysis/recon-e0348/LIVEVIEW_DMA.md
 *   sections 1.a, 3.5 and 5.  Section 5 lists exactly which runtime facts are
 *   missing: whether the ring is live in PC Remote, whether a foreign GET_JPEG
 *   sees it, the DMM unit geometry per outstanding frame, the loaded module /
 *   kallsyms surface, UDC state, device-node identity, and the /proc/osal tables.
 *   This program collects those read-only facts and, behind two explicit
 *   opt-ins, performs ONE decisive foreign GET_JPEG poll sequence.
 *
 * SAFETY BOUNDARIES (see probes/README.md)
 *   - No bulk /dev/mem scan, ever.  AGENTS.MD records that a 16 MiB /dev/mem chunk
 *     read dropped USB and rebooted the camera (E0454).  This build refuses
 *     --devmem unless compiled with PROBE_ENABLE_DEVMEM=1, and even then accepts at
 *     most ONE read of at most 4096 bytes (no loop, no scan).
 *   - Every file read is capped, every directory walk is capped, every loop is
 *     capped; caps are declared in the report `bounds` object.
 *   - /proc/osal/uipc is opened ONCE and read forward in chunks (no lseek, no
 *     reopen) because it is a multi-stage generated file.
 *   - No syscall in the default path changes camera state: open(O_RDONLY), read,
 *     getdents64, stat64, readlink, write to our own output file, close.
 *   - The opt-in GET_JPEG probe is a camera-side DataflowInfra transaction whose
 *     PC-Remote ownership side effects are UNMEASURED.  It requires both
 *     --poll-get-jpeg N (N<=100) and --i-understand-foreign-get-jpeg, prints a
 *     prominent warning, and if a reply reports ready!=0 it completes the
 *     documented DMM close/free sequence for both handles or stops with exit 2 and
 *     reports the ambiguity.  It never copies or invents frame bytes.
 *
 * OUTPUT
 *   JSON to --out (default /tmp_bt/uvc_dma_probe.json), human log on stdout, and a
 *   final stdout line `PROBE_RESULT {json-one-liner}`.  The JSON is a pure function
 *   of the collected data, so it is generated twice (file, then stdout) rather than
 *   buffered whole in memory.
 *
 * EXIT CODES
 *   0 complete   - every section collected inside its declared cap
 *   2 partial    - at least one section was unreadable/truncated or the GET_JPEG
 *                  reply made DMM cleanup ambiguous; JSON is still valid
 *   3 refused    - unsafe/unknown arguments, or an opt-in prerequisite is missing
 *   4 fatal      - could not emit the report at all
 *
 * BUILD
 *   probes/build_probe.py (WSL arm-linux-gnueabi-gcc) or, for the fixture smoke
 *   test, the same file compiled for x86-64 with -DPROBE_HOST_STUB and
 *   -DPROBE_HOST_ROOT="<temp dir>" (paths are re-rooted, no camera data involved).
 */

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef int s32;
typedef __SIZE_TYPE__ usize;

/*
 * Freestanding memory primitives.  The build uses -ffreestanding (so the compiler
 * must not synthesise libc calls), and these definitions are the link-time backstop
 * for the same names, matching tools/native_camera/uvc_sensor_feeder_30fps.c:167-178.
 */
void *memset(void *dst, int c, usize n) {
    u8 *p = (u8 *)dst;
    while (n-- > 0u) *p++ = (u8)c;
    return dst;
}

void *memcpy(void *dst, const void *src, usize n) {
    u8 *d = (u8 *)dst;
    const u8 *s = (const u8 *)src;
    while (n-- > 0u) *d++ = *s++;
    return dst;
}

usize strlen(const char *s) {
    usize n = 0;
    while (s[n] != '\0') n++;
    return n;
}

/* ------------------------------------------------------------------ */
/* compile-time switches                                              */
/* ------------------------------------------------------------------ */

#ifndef PROBE_ENABLE_DEVMEM
#define PROBE_ENABLE_DEVMEM 0
#endif

#if defined(PROBE_HOST_STUB)
#define PROBE_HOST 1
#ifndef PROBE_HOST_ROOT
#error "PROBE_HOST_STUB builds require -DPROBE_HOST_ROOT=\"<temp dir>\""
#endif
#else
#define PROBE_HOST 0
#endif

/* caps; every one is echoed in the report `bounds` object */
#define CAP_MAPS 65536u          /* /proc/<pid>/maps text                      */
#define CAP_UIPC 131072u         /* /proc/osal/uipc read-once window           */
#define CAP_KALLSYMS (16u * 1024u * 1024u)  /* kallsyms streaming cap         */
#define CAP_SMALL 4096u          /* chunk size for streaming reads             */
#define CAP_STATUS 8192u         /* /proc/<pid>/status                         */
#define CAP_IDENTITY 2048u       /* /proc/version, /proc/devices               */
#define CAP_FD 256u              /* /proc/<pid>/fd entries                     */
#define CAP_DIR_NAMES 192u       /* entries listed per directory               */
#define CAP_MODULES 48u
#define CAP_UDC 4u
#define CAP_TARGET_MAPS 64u
#define CAP_POLLS 100u
#define CAP_DEVMEM 4096u
#define CAP_NOTES 16u
#define NAME_MAX 40u
#define TEXT_MAX 512u
#define PATH_MAX 320u
#define NOTE_LEN 240u

#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT 64
#define O_TRUNC 512

#define EPERM 1
#define ENOENT 2
#define EINTR 4
#define EIO 5
#define ENXIO 6
#define EBADF 9
#define EAGAIN 11
#define ENOMEM 12
#define EACCES 13
#define EBUSY 16
#define ENODEV 19
#define ENOTDIR 20
#define EINVAL 22
#define ENOTTY 25
#define EPIPE 32
#define ENAMETOOLONG 36
#define ENOSYS 38
#define ELOOP 40
#define EOPNOTSUPP 95
#define ETIMEDOUT 110

#define LAYOUT_NONE 0
#define LAYOUT_STAT64 1
#define LAYOUT_OLDSTAT 2
#define LAYOUT_HOST 3

/* ------------------------------------------------------------------ */
/* tiny freestanding string / number helpers                          */
/* ------------------------------------------------------------------ */

static u32 s_len(const char *s) {
    u32 n = 0;
    while (s[n] != '\0') n++;
    return n;
}

static int s_eq(const char *a, const char *b) {
    while (*a != '\0' && *a == *b) { a++; b++; }
    return *a == *b;
}

static void s_copy(char *dst, u32 cap, const char *src) {
    u32 i = 0;
    if (cap == 0u) return;
    while (i + 1u < cap && src[i] != '\0') { dst[i] = src[i]; i++; }
    dst[i] = '\0';
}

static void s_app(char *dst, u32 cap, u32 *pos, const char *src) {
    u32 p = *pos;
    while (*src != '\0' && p + 1u < cap) { dst[p++] = *src++; }
    dst[p] = '\0';
    *pos = p;
}

static void s_app_u32(char *dst, u32 cap, u32 *pos, u32 v) {
    char tmp[12];
    u32 i = 0;
    if (v == 0u) { s_app(dst, cap, pos, "0"); return; }
    while (v > 0u && i < sizeof(tmp)) { tmp[i++] = (char)('0' + (v % 10u)); v /= 10u; }
    while (i > 0u) {
        char one[2];
        one[0] = tmp[--i];
        one[1] = '\0';
        s_app(dst, cap, pos, one);
    }
}

static int s_has(const char *hay, const char *needle) {
    u32 i, j;
    if (*needle == '\0') return 1;
    for (i = 0; hay[i] != '\0'; i++) {
        for (j = 0; needle[j] != '\0'; j++) {
            if (hay[i + j] != needle[j]) break;
        }
        if (needle[j] == '\0') return 1;
    }
    return 0;
}

static void s_trim(char *s) {
    u32 n = s_len(s);
    while (n > 0u) {
        char c = s[n - 1u];
        if (c == '\n' || c == '\r' || c == ' ' || c == '\t') { s[n - 1u] = '\0'; n--; }
        else break;
    }
    {
        u32 start = 0;
        while (s[start] == ' ' || s[start] == '\t') start++;
        if (start > 0u) {
            u32 i = 0;
            while (s[start + i] != '\0') { s[i] = s[start + i]; i++; }
            s[i] = '\0';
        }
    }
}

/* keeps only printable ASCII; used for values that must not carry control bytes */
static void s_sanitize(char *s) {
    u32 i = 0;
    while (s[i] != '\0') {
        u8 c = (u8)s[i];
        if (c < 0x20u || c > 0x7eu) s[i] = '?';
        i++;
    }
}

static int hex_val(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

/* decimal parse; returns 0 on any non-digit */
static int parse_dec(const char *s, u32 *out) {
    u32 v = 0;
    u32 i = 0;
    if (s[0] == '\0') return -1;
    while (s[i] != '\0') {
        if (s[i] < '0' || s[i] > '9') return -1;
        if (v > 429496729u) return -1;
        v = v * 10u + (u32)(s[i] - '0');
        i++;
    }
    *out = v;
    return 0;
}

/* decimal or 0x-prefixed hex parse */
static int parse_num(const char *s, u32 *out) {
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
        u32 v = 0;
        u32 i = 2;
        if (s[i] == '\0') return -1;
        while (s[i] != '\0') {
            int h = hex_val(s[i]);
            if (h < 0 || v > 0x0fffffffu) return -1;
            v = (v << 4) | (u32)h;
            i++;
        }
        *out = v;
        return 0;
    }
    return parse_dec(s, out);
}

/* parses the first whitespace-delimited token of a line as hex (maps/kallsyms) */
static int parse_hex_token(const char *s, u32 *out, u32 *consumed) {
    u32 v = 0;
    u32 i = 0;
    while (s[i] != '\0' && s[i] != ' ' && s[i] != '\t' && s[i] != '-' && s[i] != '\n') {
        int h = hex_val(s[i]);
        if (h < 0) return -1;
        if (v > 0x0fffffffu) return -1;
        v = (v << 4) | (u32)h;
        i++;
    }
    if (i == 0u) return -1;
    *out = v;
    if (consumed != 0) *consumed = i;
    return 0;
}

/* little-endian field readers for kernel ABI structures (both host and target) */
static u32 rd32(const u8 *p) {
    return (u32)p[0] | ((u32)p[1] << 8) | ((u32)p[2] << 16) | ((u32)p[3] << 24);
}
static u32 rd16(const u8 *p) {
    return (u32)p[0] | ((u32)p[1] << 8);
}

static const char *errno_name(int err) {
    switch (err) {
    case 0: return "OK";
    case EPERM: return "EPERM";
    case ENOENT: return "ENOENT";
    case EINTR: return "EINTR";
    case EIO: return "EIO";
    case ENXIO: return "ENXIO";
    case EBADF: return "EBADF";
    case EAGAIN: return "EAGAIN";
    case ENOMEM: return "ENOMEM";
    case EACCES: return "EACCES";
    case EBUSY: return "EBUSY";
    case ENODEV: return "ENODEV";
    case ENOTDIR: return "ENOTDIR";
    case EINVAL: return "EINVAL";
    case ENOTTY: return "ENOTTY";
    case EPIPE: return "EPIPE";
    case ENAMETOOLONG: return "ENAMETOOLONG";
    case ENOSYS: return "ENOSYS";
    case ELOOP: return "ELOOP";
    case EOPNOTSUPP: return "EOPNOTSUPP";
    case ETIMEDOUT: return "ETIMEDOUT";
    default: return "UNKNOWN";
    }
}

/* ------------------------------------------------------------------ */
/* syscall layer: ARM direct svc, or x86-64 host fixture stub         */
/* ------------------------------------------------------------------ */

static int fs_open_ro(const char *path);
static int fs_open_rw(const char *path);
static int fs_open_out(const char *path);
static int fs_close(int fd);
static int fs_read(int fd, void *buf, u32 len);
static int fs_write(int fd, const void *buf, u32 len);
static int fs_lseek(int fd, u32 off);
static int fs_getdents(int fd, void *buf, u32 len);
static int fs_readlink(const char *path, char *buf, u32 len);
static int fs_stat_node(const char *path, u32 *mode, u32 *rdev, int *layout);
static int fs_ioctl(int fd, u32 req, void *arg);
static void *fs_mmap(u32 len, int fd);
static void fs_exit(int code) __attribute__((noreturn, unused));

#if !PROBE_HOST

static inline int svc1(int n, int a0) {
    register int r0 __asm__("r0") = a0;
    register int r7 __asm__("r7") = n;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r7) : "memory");
    return r0;
}

static inline int svc2(int n, int a0, int a1) {
    register int r0 __asm__("r0") = a0;
    register int r1 __asm__("r1") = a1;
    register int r7 __asm__("r7") = n;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r7) : "memory");
    return r0;
}

static inline int svc3(int n, int a0, int a1, int a2) {
    register int r0 __asm__("r0") = a0;
    register int r1 __asm__("r1") = a1;
    register int r2 __asm__("r2") = a2;
    register int r7 __asm__("r7") = n;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}

static int fs_open_ro(const char *path) {
    return svc3(5 /* open */, (int)path, O_RDONLY, 0);
}
/* the opt-in poll path opens /dev/uipc read-write, exactly like the feeder */
static int fs_open_rw(const char *path) {
    return svc3(5 /* open */, (int)path, 2 /* O_RDWR */, 0);
}
/* the single write path: our own report file, O_WRONLY|O_CREAT|O_TRUNC 0644 */
static int fs_open_out(const char *path) {
    return svc3(5 /* open */, (int)path, O_WRONLY | O_CREAT | O_TRUNC, 0644);
}
static int fs_close(int fd) { return svc1(6 /* close */, fd); }
static int fs_read(int fd, void *buf, u32 len) { return svc3(3, fd, (int)buf, (int)len); }
static int fs_write(int fd, const void *buf, u32 len) { return svc3(4, fd, (int)buf, (int)len); }
static int __attribute__((unused)) fs_lseek(int fd, u32 off) { return svc3(19 /* lseek */, fd, (int)off, 0 /* SEEK_SET */); }
static int fs_getdents(int fd, void *buf, u32 len) { return svc3(217 /* getdents64 */, fd, (int)buf, (int)len); }
static int fs_readlink(const char *path, char *buf, u32 len) {
    return svc3(85 /* readlink */, (int)path, (int)buf, (int)len);
}
static int fs_ioctl(int fd, u32 req, void *arg) {
    return svc3(54 /* ioctl */, fd, (int)req, (int)arg);
}

static void *fs_mmap(u32 len, int fd) {
    register int r0 __asm__("r0") = 0;
    register int r1 __asm__("r1") = (int)len;
    register int r2 __asm__("r2") = 3;          /* PROT_READ|PROT_WRITE */
    register int r3 __asm__("r3") = 1;          /* MAP_SHARED           */
    register int r4 __asm__("r4") = fd;
    register int r5 __asm__("r5") = 0;
    register int r7 __asm__("r7") = 192;        /* mmap2 */
    __asm__ __volatile__("svc 0"
                         : "=r"(r0)
                         : "r"(r0), "r"(r1), "r"(r2), "r"(r3), "r"(r4), "r"(r5), "r"(r7)
                         : "memory");
    return (void *)r0;
}

/*
 * ARM stat layout, validated at run time by the S_IFMT bits.
 *
 *   stat64 (__NR 195): st_dev u64 @0, __st_ino u32 @12, st_mode u32 @16,
 *                      st_rdev u64 @32  (arch/arm uapi struct stat64)
 *   stat   (__NR 106): st_dev u32 @0, st_ino u32 @4, st_mode u16 @8,
 *                      st_rdev u32 @16  (arch/arm uapi legacy struct stat)
 *
 * Nothing is reported as a major:minor unless st_mode decodes to a known file
 * type, so a wrong layout assumption produces an explicit ENOSYS entry instead of
 * a plausible-looking wrong device number.  The layout actually used is reported
 * verbatim in the JSON.
 */
static u32 rd32(const u8 *p);
static u32 rd16(const u8 *p);

static int mode_is_known(u32 mode) {
    u32 t = mode & 0xf000u;
    return t == 0x1000u || t == 0x2000u || t == 0x4000u || t == 0x6000u ||
           t == 0x8000u || t == 0xa000u || t == 0xc000u;
}

static int fs_stat_node(const char *path, u32 *mode, u32 *rdev, int *layout) {
    u8 raw[128];
    int ret;
    u32 i;
    for (i = 0; i < (u32)sizeof(raw); i++) raw[i] = 0;

    ret = svc2(195 /* stat64 */, (int)path, (int)raw);
    if (ret == 0) {
        u32 m = rd32(raw + 16);
        if (mode_is_known(m)) {
            *mode = m;
            *rdev = rd32(raw + 32);
            *layout = LAYOUT_STAT64;
            return 0;
        }
        /* layout rejected: fall through to the legacy syscall before failing */
    } else if ((u32)(-ret) != (u32)ENOSYS) {
        return ret;
    }

    for (i = 0; i < (u32)sizeof(raw); i++) raw[i] = 0;
    ret = svc2(106 /* stat */, (int)path, (int)raw);
    if (ret == 0) {
        u32 m = rd16(raw + 8);
        if (mode_is_known(m)) {
            *mode = m;
            *rdev = rd32(raw + 16);
            *layout = LAYOUT_OLDSTAT;
            return 0;
        }
    } else {
        return ret;
    }
    /* both syscalls answered but no layout decoded: refuse to invent dev_t */
    *layout = LAYOUT_NONE;
    *mode = 0;
    *rdev = 0;
    return -ENOSYS;
}

static void fs_exit(int code) {
    svc1(1 /* exit */, code);
    for (;;) { }
}

#else /* PROBE_HOST */

#define AT_FDCWD (-100)

static long host_syscall1(long n, long a1) {
    long ret;
    __asm__ __volatile__("syscall" : "=a"(ret) : "a"(n), "D"(a1) : "rcx", "r11", "memory");
    return ret;
}
static long host_syscall3(long n, long a1, long a2, long a3) {
    long ret;
    __asm__ __volatile__("syscall"
                         : "=a"(ret)
                         : "a"(n), "D"(a1), "S"(a2), "d"(a3)
                         : "rcx", "r11", "memory");
    return ret;
}
static long host_syscall4(long n, long a1, long a2, long a3, long a4) {
    long ret;
    register long r10 __asm__("r10") = a4;
    __asm__ __volatile__("syscall"
                         : "=a"(ret)
                         : "a"(n), "D"(a1), "S"(a2), "d"(a3), "r"(r10)
                         : "rcx", "r11", "memory");
    return ret;
}

/*
 * Every absolute path is re-rooted under PROBE_HOST_ROOT so the fixture run can
 * only ever read the synthetic tree.  A rotating set of buffers keeps nested
 * calls safe without allocation.
 */
static char g_root_buf[4][512];
static u32 g_root_slot;

static const char *hpath(const char *path) {
    char *b;
    u32 pos = 0;
    if (PROBE_HOST_ROOT[0] == '\0') return path;
    if (path[0] != '/') return path;
    g_root_slot = (g_root_slot + 1u) & 3u;
    b = g_root_buf[g_root_slot];
    b[0] = '\0';
    s_app(b, 512u, &pos, PROBE_HOST_ROOT);
    s_app(b, 512u, &pos, path);
    return b;
}

static int fs_open_ro(const char *path) {
    const char *p = hpath(path);
    return (int)host_syscall4(257 /* openat */, AT_FDCWD, (long)p, O_RDONLY, 0);
}
static int fs_open_rw(const char *path) {
    const char *p = hpath(path);
    return (int)host_syscall4(257 /* openat */, AT_FDCWD, (long)p, 2 /* O_RDWR */, 0);
}
static int fs_open_out(const char *path) {
    const char *p = hpath(path);
    return (int)host_syscall4(257 /* openat */, AT_FDCWD, (long)p,
                              O_WRONLY | O_CREAT | O_TRUNC, 0644);
}
static int fs_close(int fd) { return (int)host_syscall1(3, fd); }
static int fs_read(int fd, void *buf, u32 len) { return (int)host_syscall3(0, fd, (long)buf, len); }
static int fs_write(int fd, const void *buf, u32 len) { return (int)host_syscall3(1, fd, (long)buf, len); }
static int __attribute__((unused)) fs_lseek(int fd, u32 off) { return (int)host_syscall3(8, fd, off, 0); }
static int fs_getdents(int fd, void *buf, u32 len) { return (int)host_syscall3(217, fd, (long)buf, len); }
static int fs_readlink(const char *path, char *buf, u32 len) {
    const char *p = hpath(path);
    return (int)host_syscall4(267 /* readlinkat */, AT_FDCWD, (long)p, (long)buf, len);
}

/* x86-64 struct stat: st_dev @0, st_ino @8, st_nlink @16, st_mode @24, st_rdev @40 */
static int fs_stat_node(const char *path, u32 *mode, u32 *rdev, int *layout) {
    const char *p = hpath(path);
    u8 raw[160];
    int ret;
    u32 i;
    for (i = 0; i < (u32)sizeof(raw); i++) raw[i] = 0;
    ret = (int)host_syscall4(262 /* newfstatat */, AT_FDCWD, (long)p, (long)raw, 0);
    if (ret != 0) return ret;
    *mode = rd32(raw + 24);
    *rdev = rd32(raw + 40);
    *layout = LAYOUT_HOST;
    return 0;
}

static int fs_ioctl(int fd, u32 req, void *arg) {
    (void)fd; (void)req; (void)arg;
    return -ENOSYS;   /* host fixture has no camera UIPC */
}
static void *fs_mmap(u32 len, int fd) {
    (void)len; (void)fd;
    return (void *)0;
}
static void fs_exit(int code) { host_syscall1(231 /* exit_group */, code); for (;;) { } }

#endif /* PROBE_HOST */

/* ------------------------------------------------------------------ */
/* console + buffered JSON writer                                     */
/* ------------------------------------------------------------------ */

static int g_stdout = 1;

static void write_all(int fd, const void *buf, u32 len) {
    const char *p = (const char *)buf;
    u32 done = 0;
    while (done < len) {
        int n = fs_write(fd, p + done, len - done);
        if (n <= 0) return;
        done += (u32)n;
    }
}

static void log_raw(const char *s) { write_all(g_stdout, s, s_len(s)); }
static void log_line(const char *s) { log_raw(s); log_raw("\n"); }

static void log_u32(u32 v) {
    char tmp[12];
    u32 pos = 0;
    tmp[0] = '\0';
    s_app_u32(tmp, sizeof(tmp), &pos, v);
    write_all(g_stdout, tmp, pos);
}

static void log_hex(u32 v) {
    static const char hexd[] = "0123456789abcdef";
    char tmp[11];
    int i;
    tmp[0] = '0';
    tmp[1] = 'x';
    for (i = 7; i >= 0; i--) tmp[2 + (7 - i)] = hexd[(v >> (u32)(i * 4)) & 0xfu];
    tmp[10] = '\0';
    write_all(g_stdout, tmp, 10);
}

struct jw {
    int fd;
    u32 len;
    int failed;
    char buf[8192];
};

static void jw_flush(struct jw *w) {
    if (w->len > 0u && !w->failed) {
        int n = fs_write(w->fd, w->buf, w->len);
        if (n <= 0 || (u32)n != w->len) w->failed = 1;
        w->len = 0;
    }
}

static void jw_put(struct jw *w, const char *s, u32 n) {
    u32 i;
    if (w->failed) return;
    for (i = 0; i < n; i++) {
        if (w->len == (u32)sizeof(w->buf)) jw_flush(w);
        if (w->failed) return;
        w->buf[w->len++] = s[i];
    }
}

static void jw_c(struct jw *w, char c) {
    if (w->len == (u32)sizeof(w->buf)) jw_flush(w);
    if (w->failed) return;
    w->buf[w->len++] = c;
}

static void jw_str(struct jw *w, const char *s) {
    static const char hexd[] = "0123456789abcdef";
    jw_c(w, '"');
    while (*s != '\0') {
        u8 c = (u8)*s++;
        if (c == '"' || c == '\\') { jw_c(w, '\\'); jw_c(w, (char)c); }
        else if (c == '\n') { jw_put(w, "\\n", 2); }
        else if (c == '\r') { jw_put(w, "\\r", 2); }
        else if (c == '\t') { jw_put(w, "\\t", 2); }
        else if (c < 0x20u || c > 0x7eu) {
            char esc[6];
            esc[0] = '\\'; esc[1] = 'u'; esc[2] = '0'; esc[3] = '0';
            esc[4] = hexd[(c >> 4) & 0xfu];
            esc[5] = hexd[c & 0xfu];
            jw_put(w, esc, 6);
        } else {
            jw_c(w, (char)c);
        }
    }
    jw_c(w, '"');
}

static void jw_u32(struct jw *w, u32 v) {
    char tmp[12];
    u32 pos = 0;
    tmp[0] = '\0';
    s_app_u32(tmp, sizeof(tmp), &pos, v);
    jw_put(w, tmp, pos);
}

static void jw_i32(struct jw *w, int v) {
    if (v < 0) { jw_c(w, '-'); jw_u32(w, (u32)(-(long)v)); }
    else jw_u32(w, (u32)v);
}

/* hex values are emitted as JSON strings: "0x00000000" (never a JSON hex literal) */
static void jw_hex(struct jw *w, u32 v) {
    static const char hexd[] = "0123456789abcdef";
    char tmp[11];
    int i;
    tmp[0] = '0';
    tmp[1] = 'x';
    for (i = 7; i >= 0; i--) tmp[2 + (7 - i)] = hexd[(v >> (u32)(i * 4)) & 0xfu];
    tmp[10] = '\0';
    jw_c(w, '"');
    jw_put(w, tmp, 10);
    jw_c(w, '"');
}

static void jw_key(struct jw *w, const char *k) { jw_str(w, k); jw_c(w, ':'); }
static void jw_null(struct jw *w) { jw_put(w, "null", 4); }
static void jw_bool(struct jw *w, int v) { jw_put(w, v ? "true" : "false", v ? 4u : 5u); }

/* ------------------------------------------------------------------ */
/* bounded readers                                                    */
/* ------------------------------------------------------------------ */

struct read_result {
    int err;          /* 0 or negative errno                         */
    u32 bytes;
    int truncated;    /* file had more data than the cap allowed     */
};

/* text read: NUL-terminated, control bytes preserved for JSON escaping */
static struct read_result read_text(const char *path, char *buf, u32 cap) {
    struct read_result r;
    int fd;
    u32 len = 0;
    r.err = 0;
    r.bytes = 0;
    r.truncated = 0;
    if (cap == 0u) return r;
    buf[0] = '\0';
    fd = fs_open_ro(path);
    if (fd < 0) { r.err = fd; return r; }
    for (;;) {
        int n;
        if (len + 1u >= cap) {
            u8 probe_byte;
            int extra = fs_read(fd, &probe_byte, 1);
            if (extra > 0) r.truncated = 1;
            break;
        }
        n = fs_read(fd, buf + len, cap - 1u - len);
        if (n < 0) { r.err = n; break; }
        if (n == 0) break;
        len += (u32)n;
    }
    buf[len] = '\0';
    r.bytes = len;
    fs_close(fd);
    return r;
}

/* binary read: no NUL appended semantics, capped window */
static struct read_result read_bytes(const char *path, u8 *buf, u32 cap) {
    struct read_result r;
    int fd;
    u32 len = 0;
    r.err = 0;
    r.bytes = 0;
    r.truncated = 0;
    fd = fs_open_ro(path);
    if (fd < 0) { r.err = fd; return r; }
    for (;;) {
        int n;
        if (len >= cap) {
            u8 probe_byte;
            int extra = fs_read(fd, &probe_byte, 1);
            if (extra > 0) r.truncated = 1;
            break;
        }
        n = fs_read(fd, buf + len, cap - len);
        if (n < 0) { r.err = n; break; }
        if (n == 0) break;
        len += (u32)n;
    }
    r.bytes = len;
    fs_close(fd);
    return r;
}

/* struct linux_dirent64 { u64 ino; s64 off; u16 reclen; u8 type; char name[]; } */
struct listing {
    int err;
    u32 count;
    int truncated;
    char names[CAP_DIR_NAMES][NAME_MAX];
};

static void dir_list(const char *path, struct listing *out) {
    u8 buf[CAP_SMALL];
    int fd;
    int loops = 0;
    out->err = 0;
    out->count = 0;
    out->truncated = 0;
    fd = fs_open_ro(path);
    if (fd < 0) { out->err = fd; return; }
    while (loops < 64) {
        int n;
        u32 off = 0;
        loops++;
        n = fs_getdents(fd, buf, (u32)sizeof(buf));
        if (n < 0) { out->err = n; break; }
        if (n == 0) break;
        while (off + 19u <= (u32)n) {
            u32 reclen = rd16(buf + off + 16);
            const char *name = (const char *)(buf + off + 19);
            if (reclen < 19u || off + reclen > (u32)n) break;
            off += reclen;
            if (name[0] == '.') continue;
            if (out->count >= CAP_DIR_NAMES) { out->truncated = 1; break; }
            s_copy(out->names[out->count], NAME_MAX, name);
            s_sanitize(out->names[out->count]);
            out->count++;
        }
        if (out->truncated) break;
    }
    fs_close(fd);
}

static u32 dir_count(const char *path, int *err_out) {
    u8 buf[CAP_SMALL];
    int fd;
    u32 count = 0;
    int loops = 0;
    u32 seen = 0;
    *err_out = 0;
    fd = fs_open_ro(path);
    if (fd < 0) { *err_out = fd; return 0; }
    while (loops < 64) {
        int n;
        u32 off = 0;
        loops++;
        n = fs_getdents(fd, buf, (u32)sizeof(buf));
        if (n < 0) { *err_out = n; break; }
        if (n == 0) break;
        while (off + 19u <= (u32)n) {
            u32 reclen = rd16(buf + off + 16);
            const char *name = (const char *)(buf + off + 19);
            if (reclen < 19u || off + reclen > (u32)n) break;
            off += reclen;
            if (name[0] == '.') continue;
            count++;
            if (++seen >= 8192u) { loops = 64; break; }
        }
    }
    fs_close(fd);
    return count;
}

/* ------------------------------------------------------------------ */
/* report model                                                       */
/* ------------------------------------------------------------------ */

struct mod_info {
    char name[NAME_MAX];
    char deps[NAME_MAX];
    u32 size;
    u32 refcount;
    char state[16];
    u32 address;
    int address_ok;
};

struct attr_val {
    int ok;            /* 1 = value read, 0 = errno recorded */
    int err;
    char value[48];
};

struct udc_info {
    char name[NAME_MAX];
    struct attr_val state;
    struct attr_val current_speed;
    struct attr_val maximum_speed;
    struct attr_val active;
    struct attr_val is_otg;
};

struct node_stat {
    const char *path;
    int present;
    int err;
    int layout;
    u32 mode;
    u32 major;
    u32 minor;
    int has_dev;
};

struct map_entry {
    char path[TEXT_MAX];
    char perms[8];
    char target[NAME_MAX];
    u32 base;
    u32 end;
};

struct fd_entry {
    char fd[8];
    char target[128];
    int err;
};

struct sym_entry {
    const char *name;
    int found;
    int restricted;
    u32 address;
    char type;
};

struct poll_entry {
    int valid;
    int err;
    int ready;
    int recv_ret;
    int has_frame;
    u32 size_shift;
    u32 handle1;
    u32 handle2;
    int cleanup[4];      /* open, close, free(handle1), free(handle2) */
    int cleanup_ok;
};

struct jpeg_frame {
    int have;
    int cleanup_complete;
    int open_status;
    int close_status;
    int free_status;
    int free2_status;
    u32 handle1;
    u32 handle2;
    u32 size_shift;
    u32 size_upper_bound;
    u32 phys;
    u32 dmm_size;
};

struct bounds {
    u32 maps_cap;
    u32 maps_bytes;
    int maps_truncated;
    u32 uipc_cap;
    u32 uipc_bytes;
    int uipc_truncated;
    u32 kallsyms_cap;
    u32 kallsyms_bytes;
    u32 fd_cap;
    u32 fd_entries;
    u32 dir_cap;
    u32 get_jpeg_polls_cap;
    u32 poll_count;
    u32 devmem_cap;
    u32 devmem_len;
    u32 read_chunk;
    u32 loops_capped;
    int bulk_scan;
    int opened_device_node;
};

struct report {
    /* identity */
    char uptime[64];
    char version[TEXT_MAX];
    char cmdline[TEXT_MAX];
    char devices[CAP_IDENTITY];
    int identity_err[4];

    /* modules */
    struct mod_info modules[CAP_MODULES];
    u32 module_count;
    int modules_err;

    /* udc */
    struct udc_info udc[CAP_UDC];
    u32 udc_count;
    int udc_err;

    /* devnodes */
    struct listing dev_listing;
    struct listing dev_usb_listing;
    struct node_stat nodes[7];
    u32 node_count;

    /* pid149 */
    struct {
        char key[24];
        char value[64];
    } status[12];
    u32 status_count;
    int status_err;
    u32 maps_bytes;
    int maps_truncated;
    int maps_err;
    u32 mapping_lines;
    struct map_entry maps[CAP_TARGET_MAPS];
    u32 map_count;
    u32 fd_count;
    int fd_err;
    struct fd_entry fds[CAP_FD];
    u32 fd_used;
    u32 thread_count;
    int thread_err;

    /* kallsyms */
    int kallsyms_readable;
    u32 kallsyms_bytes;
    struct sym_entry syms[11];

    /* uipc */
    int uipc_opened;
    int uipc_err;
    u32 uipc_bytes;
    int uipc_truncated;
    char minfo_head[160];
    int minfo_err;
    char ulogio_head[160];
    int ulogio_err;

    /* poll */
    u32 poll_count;
    struct poll_entry polls[CAP_POLLS];
    struct jpeg_frame frame;
    int poll_error;              /* negative errno from osal init, or 0 */
    int poll_attempts;

    struct bounds bnd;
    char notes[CAP_NOTES][NOTE_LEN];
    u32 note_count;
    int exit_code;
};

static struct report g_rep;
static char g_maps_buf[CAP_MAPS];
static u8 g_uipc_buf[CAP_UIPC];

static void add_note(const char *s) {
    if (g_rep.note_count >= CAP_NOTES) return;
    s_copy(g_rep.notes[g_rep.note_count], NOTE_LEN, s);
    g_rep.note_count++;
}

/* ------------------------------------------------------------------ */
/* collection                                                         */
/* ------------------------------------------------------------------ */

static void collect_identity(void) {
    struct read_result r;
    r = read_text("/proc/uptime", g_rep.uptime, sizeof(g_rep.uptime));
    g_rep.identity_err[0] = r.err;
    s_trim(g_rep.uptime);
    r = read_text("/proc/version", g_rep.version, sizeof(g_rep.version));
    g_rep.identity_err[1] = r.err;
    s_trim(g_rep.version);
    r = read_text("/proc/cmdline", g_rep.cmdline, sizeof(g_rep.cmdline));
    g_rep.identity_err[2] = r.err;
    s_trim(g_rep.cmdline);
    r = read_text("/proc/devices", g_rep.devices, sizeof(g_rep.devices));
    g_rep.identity_err[3] = r.err;
    s_trim(g_rep.devices);
}

static void collect_modules(void) {
    static char text[16384];
    struct read_result r = read_text("/proc/modules", text, sizeof(text));
    char *p = text;
    g_rep.modules_err = r.err;
    if (r.err != 0) return;
    while (*p != '\0' && g_rep.module_count < CAP_MODULES) {
        char line[512];
        char *q = line;
        u32 tok = 0;
        struct mod_info *m = &g_rep.modules[g_rep.module_count];
        while (*p != '\0' && *p != '\n') { if (q < line + sizeof(line) - 1) *q++ = *p; p++; }
        if (*p == '\n') p++;
        *q = '\0';
        if (line[0] == '\0') continue;
        m->address_ok = 0;
        q = line;
        while (*q != '\0' && tok < 6) {
            char *start = q;
            char save;
            while (*q != '\0' && *q != ' ') q++;
            save = *q;
            *q = '\0';
            if (tok == 0) s_copy(m->name, NAME_MAX, start);
            else if (tok == 1) (void)parse_dec(start, &m->size);
            else if (tok == 2) (void)parse_dec(start, &m->refcount);
            else if (tok == 3) s_copy(m->deps, NAME_MAX, start);
            else if (tok == 4) s_copy(m->state, sizeof(m->state), start);
            else if (tok == 5) {
                u32 v = 0;
                if (parse_num(start, &v) == 0) { m->address = v; m->address_ok = 1; }
            }
            *q = save;
            if (*q == ' ') q++;
            tok++;
        }
        s_sanitize(m->name);
        s_sanitize(m->deps);
        s_sanitize(m->state);
        if (m->name[0] != '\0') { s_trim(m->name); g_rep.module_count++; }
    }
}

static void udc_read_attr(const char *dir, const char *attr, struct attr_val *out) {
    char path[PATH_MAX];
    struct read_result r;
    u32 pos = 0;
    path[0] = '\0';
    s_app(path, sizeof(path), &pos, dir);
    s_app(path, sizeof(path), &pos, "/");
    s_app(path, sizeof(path), &pos, attr);
    r = read_text(path, out->value, sizeof(out->value));
    if (r.err != 0) { out->ok = 0; out->err = r.err; out->value[0] = '\0'; return; }
    out->ok = 1;
    out->err = 0;
    s_trim(out->value);
    s_sanitize(out->value);
}

static void collect_udc(void) {
    struct listing ls;
    u32 i;
    dir_list("/sys/class/udc", &ls);
    g_rep.udc_err = ls.err;
    if (ls.err != 0) return;
    for (i = 0; i < ls.count && g_rep.udc_count < CAP_UDC; i++) {
        char dir[PATH_MAX];
        u32 pos = 0;
        struct udc_info *u = &g_rep.udc[g_rep.udc_count];
        dir[0] = '\0';
        s_app(dir, sizeof(dir), &pos, "/sys/class/udc/");
        s_app(dir, sizeof(dir), &pos, ls.names[i]);
        s_copy(u->name, NAME_MAX, ls.names[i]);
        udc_read_attr(dir, "state", &u->state);
        udc_read_attr(dir, "current_speed", &u->current_speed);
        udc_read_attr(dir, "maximum_speed", &u->maximum_speed);
        udc_read_attr(dir, "active", &u->active);
        udc_read_attr(dir, "is_otg", &u->is_otg);
        g_rep.udc_count++;
    }
}

static void collect_devnodes(void) {
    static const char *paths[7] = {
        "/dev/usb/event", "/dev/usb/video", "/dev/usb/audio", "/dev/stream",
        "/dev/stream2", "/dev/uipc", "/dev/dmpgles2"
    };
    u32 i;
    dir_list("/dev", &g_rep.dev_listing);
    dir_list("/dev/usb", &g_rep.dev_usb_listing);
    for (i = 0; i < 7u; i++) {
        struct node_stat *n = &g_rep.nodes[i];
        u32 mode = 0, rdev = 0;
        int layout = LAYOUT_NONE;
        int ret;
        n->path = paths[i];
        n->layout = LAYOUT_NONE;
        n->has_dev = 0;
        ret = fs_stat_node(paths[i], &mode, &rdev, &layout);
        if (ret == 0) {
            n->present = 1;
            n->err = 0;
            n->mode = mode;
            n->layout = layout;
            /* dev_t: major = bits 8..19, minor = bits 0..7 | bits 20..31 */
            n->major = (rdev >> 8) & 0xfffu;
            n->minor = (rdev & 0xffu) | ((rdev >> 12) & 0xfff00u);
            n->has_dev = 1;
        } else {
            n->present = 0;
            n->err = ret;
        }
        g_rep.node_count = i + 1u;
    }
}

static const char *map_target(const char *path) {
    static const char *targets[9] = {
        "im.elf", "libInfraUsbCmn", "libInfraPtpControl", "libInfraPtpExtCmd",
        "libptp", "libMWF", "libObj", "dmpgles2", "libosal"
    };
    u32 i;
    for (i = 0; i < 9u; i++) {
        if (s_has(path, targets[i])) return targets[i];
    }
    return (const char *)0;
}

static void collect_maps(void) {
    struct read_result r = read_bytes("/proc/149/maps", (u8 *)g_maps_buf, CAP_MAPS - 1u);
    char *line;
    g_rep.maps_err = r.err;
    g_rep.maps_bytes = r.bytes;
    g_rep.maps_truncated = r.truncated;
    if (r.err != 0) return;
    g_maps_buf[r.bytes] = '\0';
    line = g_maps_buf;
    while (*line != '\0') {
        char *next = line;
        char *p;
        u32 base = 0, end = 0, consumed = 0;
        char path[TEXT_MAX];
        char perms[8];
        const char *target;
        while (*next != '\0' && *next != '\n') next++;
        if (*next == '\n') { *next = '\0'; next++; }
        g_rep.mapping_lines++;
        /* start-end */
        if (parse_hex_token(line, &base, &consumed) != 0) { line = next; continue; }
        if (line[consumed] != '-') { line = next; continue; }
        if (parse_hex_token(line + consumed + 1u, &end, &consumed) != 0) { line = next; continue; }
        p = line;
        while (*p != '\0' && *p != ' ') p++;
        while (*p == ' ') p++;
        s_copy(perms, sizeof(perms), p);
        {
            u32 k = 0;
            while (k + 1u < sizeof(perms) && perms[k] != '\0' && perms[k] != ' ') k++;
            perms[k] = '\0';
        }
        /* skip perms, offset, dev and inode fields; the remainder is the path */
        {
            u32 skipped = 0;
            p = line;
            while (*p != '\0' && *p != ' ') p++;      /* address range */
            while (skipped < 4u) {
                while (*p == ' ') p++;
                while (*p != '\0' && *p != ' ') p++;
                skipped++;
            }
            while (*p == ' ') p++;
        }
        s_copy(path, sizeof(path), p);
        s_trim(path);
        target = map_target(path);
        if (target != 0 && g_rep.map_count < CAP_TARGET_MAPS) {
            struct map_entry *e = &g_rep.maps[g_rep.map_count];
            s_copy(e->path, sizeof(e->path), path);
            s_copy(e->perms, sizeof(e->perms), perms);
            s_copy(e->target, sizeof(e->target), target);
            e->base = base;
            e->end = end;
            g_rep.map_count++;
        }
        line = next;
    }
}

static void collect_fds(void) {
    struct listing ls;
    u32 i;
    int err = 0;
    u32 total = dir_count("/proc/149/fd", &err);
    g_rep.fd_err = err;
    g_rep.fd_count = total;
    if (err != 0) return;
    dir_list("/proc/149/fd", &ls);
    if (ls.err != 0) { g_rep.fd_err = ls.err; return; }
    for (i = 0; i < ls.count && g_rep.fd_used < CAP_FD; i++) {
        struct fd_entry *e = &g_rep.fds[g_rep.fd_used];
        char path[PATH_MAX];
        u32 pos = 0;
        int n;
        path[0] = '\0';
        s_app(path, sizeof(path), &pos, "/proc/149/fd/");
        s_app(path, sizeof(path), &pos, ls.names[i]);
        s_copy(e->fd, sizeof(e->fd), ls.names[i]);
        n = fs_readlink(path, e->target, (u32)sizeof(e->target) - 1u);
        if (n < 0) { e->err = n; e->target[0] = '\0'; }
        else {
            e->err = 0;
            e->target[(u32)n] = '\0';
            s_sanitize(e->target);
        }
        g_rep.fd_used++;
    }
}

static void collect_status(void) {
    static const char *keys[12] = {
        "Name:", "State:", "Tgid:", "Pid:", "PPid:", "Threads:",
        "VmSize:", "VmRSS:", "VmLib:", "CapEff:", "NoNewPrivs:", "Seccomp:"
    };
    static char text[CAP_STATUS];
    struct read_result r = read_text("/proc/149/status", text, sizeof(text));
    u32 k;

    g_rep.status_err = r.err;
    if (r.err != 0) return;
    for (k = 0; k < 12u; k++) {
        u32 off = 0;
        while (text[off] != '\0') {
            char line[160];
            u32 n = 0;
            char *v;
            while (text[off] != '\0' && text[off] != '\n') {
                if (n + 1u < (u32)sizeof(line)) line[n++] = text[off];
                off++;
            }
            line[n] = '\0';
            if (text[off] == '\n') off++;
            if (!s_has(line, keys[k])) continue;
            v = line;
            while (*v != '\0' && *v != '\t' && *v != ' ') v++;
            while (*v == '\t' || *v == ' ') v++;
            if (g_rep.status_count >= 12u) break;
            s_copy(g_rep.status[g_rep.status_count].key, 24u, keys[k]);
            {
                char *colon = g_rep.status[g_rep.status_count].key;
                while (*colon != '\0' && *colon != ':') colon++;
                *colon = '\0';
            }
            s_copy(g_rep.status[g_rep.status_count].value, 64u, v);
            s_trim(g_rep.status[g_rep.status_count].value);
            s_sanitize(g_rep.status[g_rep.status_count].value);
            g_rep.status_count++;
            break;
        }
    }
}

static void collect_kallsyms(void) {
    static const char *names[11] = {
        "usb_gadgetcore_register_driver", "usb_gadgetcore_unregister_driver",
        "usb_sync_alloc_phys_buffer", "usb_sync_free_phys_buffer",
        "dma330_mem_transfer_async", "osal_snd_msg", "osal_rcv_msg_tmo",
        "usb_gcw_start", "usb_gcw_stop", "make_config_desc", "setup_req"
    };
    static char chunk[CAP_SMALL];
    static char line[256];
    int fd;
    u32 line_len = 0;
    u32 total = 0;
    u32 i;
    int loops = 0;

    for (i = 0; i < 11u; i++) {
        g_rep.syms[i].name = names[i];
        g_rep.syms[i].found = 0;
        g_rep.syms[i].restricted = 0;
        g_rep.syms[i].address = 0;
        g_rep.syms[i].type = '?';
    }
    fd = fs_open_ro("/proc/kallsyms");
    if (fd < 0) { g_rep.kallsyms_readable = 0; add_note("kallsyms open failed"); return; }
    g_rep.kallsyms_readable = 1;
    while (loops < 8192) {
        int n;
        u32 off;
        loops++;
        n = fs_read(fd, chunk, (u32)sizeof(chunk));
        if (n < 0) { g_rep.kallsyms_readable = 0; break; }
        if (n == 0) break;
        total += (u32)n;
        for (off = 0; off < (u32)n; off++) {
            char c = chunk[off];
            if (c == '\n') {
                char *p = line;
                u32 addr = 0;
                u32 consumed = 0;
                char type = '?';
                char *name;
                u32 k;
                line[line_len] = '\0';
                line_len = 0;
                if (parse_hex_token(p, &addr, &consumed) != 0) continue;
                p += consumed;
                while (*p == ' ') p++;
                if (*p == '\0') continue;
                type = *p++;
                while (*p == ' ') p++;
                name = p;
                {
                    char *end = name;
                    while (*end != '\0' && *end != ' ' && *end != '\t') end++;
                    *end = '\0';
                }
                for (k = 0; k < 11u; k++) {
                    if (!g_rep.syms[k].found && s_eq(name, names[k])) {
                        g_rep.syms[k].found = 1;
                        g_rep.syms[k].address = addr;
                        g_rep.syms[k].type = type;
                        g_rep.syms[k].restricted = (addr == 0u);
                    }
                }
                continue;
            }
            if (line_len + 1u < (u32)sizeof(line)) line[line_len++] = c;
        }
        if (total >= CAP_KALLSYMS) break;
    }
    fs_close(fd);
    g_rep.kallsyms_bytes = total;
    if (total == 0u) {
        g_rep.kallsyms_readable = 0;
        add_note("kallsyms returned no bytes (kptr/perms?)");
    }
}

static u32 count_sub(const u8 *buf, u32 len, const char *needle, u32 nlen, int case_insensitive) {
    u32 i, j, count = 0;
    if (nlen == 0u || len < nlen) return 0;
    for (i = 0; i + nlen <= len; i++) {
        for (j = 0; j < nlen; j++) {
            u8 a = buf[i + j];
            u8 b = (u8)needle[j];
            if (case_insensitive) {
                if (a >= 'A' && a <= 'Z') a = (u8)(a - 'A' + 'a');
                if (b >= 'A' && b <= 'Z') b = (u8)(b - 'A' + 'a');
            }
            if (a != b) break;
        }
        if (j == nlen) count++;
    }
    return count;
}

struct qid_count {
    u32 qid;
    u32 lower8;
    u32 upper8;
    u32 prefixed;
    u32 raw_le;
};

static struct qid_count g_qids[4];

static void collect_uipc(void) {
    static const char *ids[4] = { "0167046a", "0061003c", "00CA8192", "012002DA" };
    struct read_result r;
    struct read_result m;
    static char head[160];
    u32 i;

    r = read_bytes("/proc/osal/uipc", g_uipc_buf, CAP_UIPC);
    g_rep.uipc_err = r.err;
    g_rep.uipc_bytes = r.bytes;
    g_rep.uipc_truncated = r.truncated;
    g_rep.uipc_opened = (r.err == 0 || r.bytes > 0u) ? 1 : 0;
    /*
     * The four ids are named constants from the evidence, not observations, so
     * they are always reported (with zero counts) even when the window is empty.
     */
    for (i = 0; i < 4u; i++) {
        char lower[9];
        char upper[9];
        char prefixed[11];
        u32 qid = 0;
        u32 k;
        for (k = 0; k < 8u; k++) {
            char c = ids[i][k];
            lower[k] = (c >= 'A' && c <= 'F') ? (char)(c - 'A' + 'a') : c;
            upper[k] = (c >= 'a' && c <= 'f') ? (char)(c - 'a' + 'A') : c;
            qid = (qid << 4) | (u32)hex_val(lower[k]);
        }
        lower[8] = '\0';
        upper[8] = '\0';
        prefixed[0] = '0';
        prefixed[1] = 'x';
        for (k = 0; k < 8u; k++) prefixed[2 + k] = lower[k];
        prefixed[10] = '\0';
        g_qids[i].qid = qid;
        g_qids[i].lower8 = 0;
        g_qids[i].upper8 = 0;
        g_qids[i].prefixed = 0;
        g_qids[i].raw_le = 0;
        if (r.bytes == 0u) continue;
        g_qids[i].lower8 = count_sub(g_uipc_buf, r.bytes, lower, 8u, 1);
        g_qids[i].upper8 = count_sub(g_uipc_buf, r.bytes, upper, 8u, 0);
        g_qids[i].prefixed = count_sub(g_uipc_buf, r.bytes, prefixed, 10u, 1);
        {
            /* the queue id is a 32-bit value; its raw on-disk form is LE */
            u8 raw[4];
            u32 c = 0;
            u32 pos;
            raw[0] = (u8)(qid & 0xffu);
            raw[1] = (u8)((qid >> 8) & 0xffu);
            raw[2] = (u8)((qid >> 16) & 0xffu);
            raw[3] = (u8)((qid >> 24) & 0xffu);
            for (pos = 0; pos + 4u <= r.bytes; pos++) {
                if (g_uipc_buf[pos] == raw[0] && g_uipc_buf[pos + 1u] == raw[1] &&
                    g_uipc_buf[pos + 2u] == raw[2] && g_uipc_buf[pos + 3u] == raw[3]) c++;
            }
            g_qids[i].raw_le = c;
        }
    }

    m = read_text("/proc/osal/minfo", head, sizeof(head));
    g_rep.minfo_err = m.err;
    s_trim(head);
    s_copy(g_rep.minfo_head, sizeof(g_rep.minfo_head), head);
    s_sanitize(g_rep.minfo_head);
    m = read_text("/proc/osal/ulogio", head, sizeof(head));
    g_rep.ulogio_err = m.err;
    s_trim(head);
    s_copy(g_rep.ulogio_head, sizeof(g_rep.ulogio_head), head);
    s_sanitize(g_rep.ulogio_head);

    g_rep.bnd.uipc_bytes = r.bytes;
    g_rep.bnd.uipc_truncated = r.truncated;
}

/* ------------------------------------------------------------------ */
/* opt-in foreign GET_JPEG poll (OSAL/DMM/DataflowInfra)              */
/* ------------------------------------------------------------------ */

#define QUEUE_SCALAR 0x0167046au
#define QUEUE_DMM 0x0061003cu

static int g_uipc_fd = -1;
static u32 g_reply_qid;

static int osal_valloc_msg(u32 qid, void **p_msg, u32 size) {
    struct { void **msg_pptr; u32 size; u32 wait_flag; } val_sub;
    struct { u32 qid; void *sub_ptr; } val_req;
    val_sub.msg_pptr = p_msg;
    val_sub.size = size;
    val_sub.wait_flag = 1;
    val_req.qid = qid;
    val_req.sub_ptr = &val_sub;
    return fs_ioctl(g_uipc_fd, 0x8000000au, &val_req);
}

static int osal_free_msg(u32 qid, void *msg) {
    struct { u32 qid; void *msg_ptr; } req;
    req.qid = qid;
    req.msg_ptr = msg;
    return fs_ioctl(g_uipc_fd, 0x8000000bu, &req);
}

static int osal_send_msg(u32 qid, void *msg) {
    struct { u32 qid; void *msg_ptr; } req;
    req.qid = qid;
    req.msg_ptr = msg;
    return fs_ioctl(g_uipc_fd, 0x80000004u, &req);
}

static int osal_recv_msg(u32 qid, void **p_msg, u32 timeout_ms) {
    struct { void **msg_pptr; u32 timeout_ms; } rcv_sub;
    struct { u32 qid; void *sub_ptr; } rcv_req;
    rcv_sub.msg_pptr = p_msg;
    rcv_sub.timeout_ms = timeout_ms;
    rcv_req.qid = qid;
    rcv_req.sub_ptr = &rcv_sub;
    return fs_ioctl(g_uipc_fd, 0x80000007u, &rcv_req);
}

static void purge_reply_queue(void) {
    int guard = 0;
    while (guard < 64) {
        void *msg = 0;
        struct { void **p; u32 tmo; } rcv_sub;
        struct { u32 q; void *s; } rcv_req;
        int r;
        guard++;
        rcv_sub.p = &msg;
        rcv_sub.tmo = 0;
        rcv_req.q = g_reply_qid;
        rcv_req.s = &rcv_sub;
        r = fs_ioctl(g_uipc_fd, 0x80000007u, &rcv_req);
        if (r != 0 || !msg) break;
        osal_free_msg(g_reply_qid, msg);
    }
}

static int osal_init(void) {
    u32 out_meta[8];
    struct { u32 param; void *out_ptr; } req_init;
    struct { u32 op; u32 param; u32 *id_out; } dyn_sub;
    struct { u32 zero; void *sub_ptr; } dyn_req;
    void *pool;
    u32 i;

    /*
     * O_RDWR matches the physically proven feeder call
     * (tools/native_camera/uvc_sensor_feeder_30fps.c:276); this open only ever
     * happens on the opt-in --poll-get-jpeg path, never in the default mode.
     */
    g_uipc_fd = fs_open_rw("/dev/uipc");
    if (g_uipc_fd < 0) return -EACCES;
    for (i = 0; i < 8u; i++) out_meta[i] = 0;
    req_init.param = 0;
    req_init.out_ptr = out_meta;
    if (fs_ioctl(g_uipc_fd, 0x80000010u, &req_init) != 0) return -EIO;
    pool = fs_mmap(out_meta[0], g_uipc_fd);
    if (pool == (void *)0) return -ENOMEM;
    dyn_sub.op = 0x2au;
    dyn_sub.param = 729u;
    dyn_sub.id_out = &g_reply_qid;
    dyn_req.zero = 0;
    dyn_req.sub_ptr = &dyn_sub;
    if (fs_ioctl(g_uipc_fd, 0x8000000cu, &dyn_req) != 0) return -EIO;
    purge_reply_queue();
    return 0;
}

static void osal_cleanup(void) {
    if (g_reply_qid != 0u && g_uipc_fd >= 0) {
        struct { u32 op; u32 param; u32 *id_out; } dyn_sub;
        struct { u32 zero; void *sub_ptr; } dyn_req;
        purge_reply_queue();
        dyn_sub.op = 0x4au;
        dyn_sub.param = 0;
        dyn_sub.id_out = &g_reply_qid;
        dyn_req.zero = 0;
        dyn_req.sub_ptr = &dyn_sub;
        (void)fs_ioctl(g_uipc_fd, 0x8000000cu, &dyn_req);
        g_reply_qid = 0;
    }
    if (g_uipc_fd >= 0) { fs_close(g_uipc_fd); g_uipc_fd = -1; }
}

static int dmm_unit_op(u32 opcode, u32 handle, u32 *p_phys, u32 *p_size) {
    void *msg = 0;
    int ret = osal_valloc_msg(QUEUE_DMM, &msg, 24);
    u8 *p;
    void *reply = 0;
    int status;
    if (ret != 0 || !msg) return -1;
    p = (u8 *)msg;
    {
        u32 i;
        for (i = 0; i < 24u; i++) p[i] = 0;
    }
    *(u16 *)(p + 0x00) = (u16)opcode;
    *(u16 *)(p + 0x02) = (u16)handle;
    if (opcode == 5u) *(u32 *)(p + 0x0c) = 0xffffffffu;
    *(u32 *)((char *)msg - 4) = g_reply_qid;
    if (osal_send_msg(QUEUE_DMM, msg) != 0) return -2;
    if (osal_recv_msg(g_reply_qid, &reply, 800u) != 0 || !reply) return -3;
    status = (int)*(short *)((char *)reply + 2);
    if (status == 0 && opcode == 5u && p_phys != 0 && p_size != 0) {
        *p_phys = *(u32 *)((char *)reply + 16);
        *p_size = *(u32 *)((char *)reply + 20);
    }
    osal_free_msg(g_reply_qid, reply);
    return status;
}

static void fill_dataflow_header(u8 *hdr, u32 reply_id, u16 payload_len) {
    *(u32 *)(hdr + 0x00) = reply_id;
    *(u32 *)(hdr + 0x04) = 0xa0a0a0a0u;
    *(u16 *)(hdr + 0x08) = 1;
    *(u16 *)(hdr + 0x0a) = (u16)(20u + (u32)payload_len);
    *(u32 *)(hdr + 0x0c) = 20;
    *(u32 *)(hdr + 0x10) = 20;
}

/*
 * The exact 40-byte DataflowInfra GET_JPEG packet from
 * tools/native_camera/uvc_sensor_feeder_30fps.c:484-529 (payload byte +0x0f =
 * 0x20 JPEG selector, byte +0x10 = 1 poll, total_len 0x14).
 */
static int send_get_jpeg(struct poll_entry *pe) {
    void *msg = 0;
    u8 *p;
    void *reply = 0;
    u8 *r_payload;
    int ret;
    u32 i;

    purge_reply_queue();
    ret = osal_valloc_msg(QUEUE_SCALAR, &msg, 40);
    if (ret != 0 || !msg) { pe->recv_ret = -1; return 1; }
    p = (u8 *)msg;
    for (i = 0; i < 40u; i++) p[i] = 0;
    fill_dataflow_header(p, g_reply_qid, 20);
    p[20 + 0x00] = 0x09;
    p[20 + 0x01] = 0x20;
    p[20 + 0x02] = 0x00;
    p[20 + 0x03] = 0x01;
    p[20 + 0x04] = 0x14;
    p[20 + 0x05] = 0x00;
    p[20 + 0x06] = 0x01;
    p[20 + 0x07] = 0x00;
    p[20 + 0x08] = 0x00;
    p[20 + 0x09] = 0x00;
    p[20 + 0x0a] = 0x00;
    p[20 + 0x0b] = 0x00;
    p[20 + 0x0c] = 0x00;
    p[20 + 0x0d] = 0x00;
    p[20 + 0x0e] = 0x00;
    p[20 + 0x0f] = 0x20;
    p[20 + 0x10] = 0x01;
    if (osal_send_msg(QUEUE_SCALAR, msg) != 0) { pe->recv_ret = -2; return 1; }
    if (osal_recv_msg(g_reply_qid, &reply, 100u) != 0 || !reply) {
        pe->recv_ret = -3;
        return 1;
    }
    r_payload = (u8 *)reply + 20;
    pe->err = (int)*(u32 *)(r_payload + 12);
    pe->ready = (int)*(u8 *)(r_payload + 16);
    pe->recv_ret = 0;
    if (pe->err == 0 && pe->ready != 0) {
        pe->size_shift = *(u16 *)(r_payload + 22);
        pe->handle1 = *(u16 *)(r_payload + 20);
        pe->handle2 = *(u16 *)(r_payload + 24);
        pe->has_frame = 1;
    }
    osal_free_msg(g_reply_qid, reply);
    return 0;
}

/*
 * Runs the poll sequence.  Returns the number of polls completed.  Sets
 * g_rep.poll_error on OSAL setup failure and g_rep.frame.cleanup_complete=0 if a
 * ready reply could not be fully closed/freed (ambiguity -> exit 2).
 */
static void run_poll_sequence(u32 requested) {
    u32 i;
    int ret = osal_init();
    if (ret != 0) {
        g_rep.poll_error = ret;
        add_note("GET_JPEG polls not attempted: OSAL /dev/uipc setup failed");
        return;
    }
    g_rep.bnd.opened_device_node = 1;
    for (i = 0; i < requested && i < CAP_POLLS; i++) {
        struct poll_entry *pe = &g_rep.polls[i];
        pe->valid = 1;
        g_rep.poll_attempts++;
        if (send_get_jpeg(pe) != 0) {
            /* transport failure: keep the slot, stop polling */
            g_rep.poll_count = i + 1u;
            add_note("GET_JPEG poll transport failure; sequence stopped");
            break;
        }
        g_rep.poll_count = i + 1u;
        if (pe->has_frame) {
            struct jpeg_frame *f = &g_rep.frame;
            f->have = 1;
            f->handle1 = pe->handle1;
            f->handle2 = pe->handle2;
            f->size_shift = pe->size_shift;
            f->size_upper_bound = pe->size_shift << 7;
            f->open_status = dmm_unit_op(5u, pe->handle1, &f->phys, &f->dmm_size);
            f->close_status = dmm_unit_op(6u, pe->handle1, 0, 0);
            f->free_status = dmm_unit_op(4u, pe->handle1, 0, 0);
            f->free2_status = dmm_unit_op(4u, pe->handle2, 0, 0);
            pe->cleanup[0] = f->open_status;
            pe->cleanup[1] = f->close_status;
            pe->cleanup[2] = f->free_status;
            pe->cleanup[3] = f->free2_status;
            pe->cleanup_ok = (f->open_status == 0 && f->close_status == 0 &&
                              f->free_status == 0 && f->free2_status == 0);
            f->cleanup_complete = pe->cleanup_ok;
            if (!pe->cleanup_ok) {
                add_note("ready GET_JPEG reply: DMM close/free sequence incomplete (ambiguity)");
            }
            /* one decisive frame is enough; never keep polling a held unit */
            break;
        }
    }
    osal_cleanup();
}

/* ------------------------------------------------------------------ */
/* optional bounded /dev/mem read (compile-time opt-in)               */
/* ------------------------------------------------------------------ */

struct devmem_result {
    int requested;
    int err;
    u32 pa;
    u32 bytes;
    u32 nonzero;
    char hex[65];
};

static struct devmem_result g_devmem;

/*
 * One bounded read, no loop and no scan.  Compiled out to a refusal unless the
 * build sets PROBE_ENABLE_DEVMEM=1 (default 0).
 */
static void run_devmem(u32 pa, u32 len) {
    int fd;
    u8 buf[CAP_DEVMEM];
    u32 i;
    int ret;
    static const char hexd[] = "0123456789abcdef";
    u32 hexlen = 0;

    g_devmem.requested = 1;
    g_devmem.pa = pa;
    g_devmem.err = 0;
    g_devmem.bytes = 0;
    g_devmem.nonzero = 0;
    g_devmem.hex[0] = '\0';
    g_rep.bnd.devmem_len = len;

#if !PROBE_ENABLE_DEVMEM
    g_devmem.err = -EPERM;
    add_note("devmem: refused, build has PROBE_ENABLE_DEVMEM=0");
    (void)fd; (void)buf; (void)i; (void)ret; (void)hexd; (void)hexlen; (void)len;
#else
    fd = fs_open_ro("/dev/mem");
    if (fd < 0) {
        g_devmem.err = fd;
        add_note("devmem: /dev/mem O_RDONLY open failed");
        return;
    }
    g_rep.bnd.opened_device_node = 1;
    ret = fs_lseek(fd, pa);
    if (ret < 0) {
        fs_close(fd);
        g_devmem.err = ret;
        add_note("devmem: lseek to PA failed");
        return;
    }
    ret = fs_read(fd, buf, len);
    fs_close(fd);
    if (ret <= 0) {
        g_devmem.err = (ret < 0) ? ret : -EIO;
        add_note("devmem: read failed");
        return;
    }
    g_devmem.bytes = (u32)ret;
    g_rep.bnd.devmem_len = (u32)ret;
    if ((u32)ret < len) add_note("devmem: short read");
    for (i = 0; i < (u32)ret; i++) {
        u8 c = buf[i];
        if (c != 0u) g_devmem.nonzero++;
        if (i < 32u) {
            g_devmem.hex[hexlen++] = hexd[(c >> 4) & 0xfu];
            g_devmem.hex[hexlen++] = hexd[c & 0xfu];
        }
    }
    g_devmem.hex[hexlen] = '\0';
    add_note("devmem: single bounded read performed (no scan)");
    (void)fd;
#endif
    (void)len;
}

/* ------------------------------------------------------------------ */
/* JSON emission                                                      */
/* ------------------------------------------------------------------ */

static void emit_attr(struct jw *w, const struct attr_val *a) {
    if (a->ok) {
        jw_c(w, '{');
        jw_key(w, "value"); jw_str(w, a->value);
        jw_c(w, '}');
    } else {
        jw_c(w, '{');
        jw_key(w, "errno"); jw_i32(w, a->err);
        jw_c(w, ',');
        jw_key(w, "errno_name"); jw_str(w, errno_name(-a->err));
        jw_c(w, '}');
    }
}

static void emit_node(struct jw *w, const struct node_stat *n) {
    jw_c(w, '{');
    jw_key(w, "path"); jw_str(w, n->path);
    jw_c(w, ',');
    jw_key(w, "present"); jw_bool(w, n->present);
    jw_c(w, ',');
    if (n->present && n->has_dev) {
        jw_key(w, "major"); jw_u32(w, n->major);
        jw_c(w, ',');
        jw_key(w, "minor"); jw_u32(w, n->minor);
        jw_c(w, ',');
        jw_key(w, "mode"); jw_hex(w, n->mode);
        jw_c(w, ',');
        jw_key(w, "layout");
        jw_str(w, n->layout == LAYOUT_STAT64 ? "arm-stat64-195" :
                  n->layout == LAYOUT_OLDSTAT ? "arm-stat-106" :
                  n->layout == LAYOUT_HOST ? "host-x86_64-stat" : "unknown");
        jw_c(w, ',');
        jw_key(w, "errno"); jw_null(w);
    } else if (n->present) {
        jw_key(w, "errno"); jw_i32(w, -ENOSYS);
        jw_c(w, ',');
        jw_key(w, "errno_name"); jw_str(w, errno_name(ENOSYS));
        jw_c(w, ',');
        jw_key(w, "detail"); jw_str(w, "stat layout not validated");
    } else {
        jw_key(w, "errno"); jw_i32(w, n->err);
        jw_c(w, ',');
        jw_key(w, "errno_name"); jw_str(w, errno_name(-n->err));
    }
    jw_c(w, '}');
}

static void emit_listing(struct jw *w, const struct listing *ls) {
    u32 i;
    jw_c(w, '{');
    if (ls->err != 0) {
        jw_key(w, "errno"); jw_i32(w, ls->err);
        jw_c(w, ',');
        jw_key(w, "errno_name"); jw_str(w, errno_name(-ls->err));
        jw_c(w, ',');
        jw_key(w, "count"); jw_u32(w, 0);
        jw_c(w, ',');
        jw_key(w, "names"); jw_put(w, "[]", 2);
    } else {
        jw_key(w, "errno"); jw_null(w);
        jw_c(w, ',');
        jw_key(w, "count"); jw_u32(w, ls->count);
        jw_c(w, ',');
        jw_key(w, "truncated"); jw_bool(w, ls->truncated);
        jw_c(w, ',');
        jw_key(w, "names"); jw_c(w, '[');
        for (i = 0; i < ls->count; i++) {
            if (i != 0u) jw_c(w, ',');
            jw_str(w, ls->names[i]);
        }
        jw_c(w, ']');
    }
    jw_c(w, '}');
}

static void emit_report(struct jw *w) {
    u32 i;
    jw_c(w, '{');

    jw_key(w, "schema"); jw_str(w, "a6400-uvc-dma-probe/1");
    jw_c(w, ',');
    jw_key(w, "tool");
    jw_c(w, '{');
    jw_key(w, "name"); jw_str(w, "uvc_dma_probe");
    jw_c(w, ',');
    jw_key(w, "devmem_build_enabled"); jw_i32(w, PROBE_ENABLE_DEVMEM ? 1 : 0);
    jw_c(w, ',');
    jw_key(w, "host_fixture"); jw_bool(w, PROBE_HOST ? 1 : 0);
    jw_c(w, '}');
    jw_c(w, ',');

    /* identity */
    jw_key(w, "identity");
    jw_c(w, '{');
    jw_key(w, "uptime"); jw_str(w, g_rep.uptime);
    jw_c(w, ',');
    jw_key(w, "version"); jw_str(w, g_rep.version);
    jw_c(w, ',');
    jw_key(w, "cmdline"); jw_str(w, g_rep.cmdline);
    jw_c(w, ',');
    jw_key(w, "devices"); jw_str(w, g_rep.devices);
    jw_c(w, '}');
    jw_c(w, ',');

    /* modules */
    jw_key(w, "modules");
    if (g_rep.modules_err != 0) {
        jw_c(w, '{');
        jw_key(w, "errno"); jw_i32(w, g_rep.modules_err);
        jw_c(w, ',');
        jw_key(w, "entries"); jw_put(w, "[]", 2);
        jw_c(w, '}');
    } else {
        jw_c(w, '[');
        for (i = 0; i < g_rep.module_count; i++) {
            const struct mod_info *m = &g_rep.modules[i];
            if (i != 0u) jw_c(w, ',');
            jw_c(w, '{');
            jw_key(w, "name"); jw_str(w, m->name);
            jw_c(w, ',');
            jw_key(w, "size"); jw_u32(w, m->size);
            jw_c(w, ',');
            jw_key(w, "refcount"); jw_u32(w, m->refcount);
            jw_c(w, ',');
            jw_key(w, "deps"); jw_str(w, m->deps);
            jw_c(w, ',');
            jw_key(w, "state"); jw_str(w, m->state);
            jw_c(w, ',');
            jw_key(w, "address");
            if (m->address_ok) jw_hex(w, m->address); else jw_null(w);
            jw_c(w, '}');
        }
        jw_c(w, ']');
    }
    jw_c(w, ',');

    /* udc */
    jw_key(w, "udc");
    if (g_rep.udc_err != 0) {
        jw_c(w, '{');
        jw_key(w, "errno"); jw_i32(w, g_rep.udc_err);
        jw_c(w, ',');
        jw_key(w, "entries"); jw_put(w, "[]", 2);
        jw_c(w, '}');
    } else {
        jw_c(w, '[');
        for (i = 0; i < g_rep.udc_count; i++) {
            const struct udc_info *u = &g_rep.udc[i];
            if (i != 0u) jw_c(w, ',');
            jw_c(w, '{');
            jw_key(w, "name"); jw_str(w, u->name);
            jw_c(w, ',');
            jw_key(w, "state"); emit_attr(w, &u->state);
            jw_c(w, ',');
            jw_key(w, "current_speed"); emit_attr(w, &u->current_speed);
            jw_c(w, ',');
            jw_key(w, "maximum_speed"); emit_attr(w, &u->maximum_speed);
            jw_c(w, ',');
            jw_key(w, "active"); emit_attr(w, &u->active);
            jw_c(w, ',');
            jw_key(w, "is_otg"); emit_attr(w, &u->is_otg);
            jw_c(w, '}');
        }
        jw_c(w, ']');
    }
    jw_c(w, ',');

    /* devnodes */
    jw_key(w, "devnodes");
    jw_c(w, '{');
    jw_key(w, "listings"); jw_c(w, '[');
    jw_c(w, '{');
    jw_key(w, "path"); jw_str(w, "/dev");
    jw_c(w, ',');
    jw_key(w, "listing");
    emit_listing(w, &g_rep.dev_listing);
    jw_c(w, '}');
    jw_c(w, ',');
    jw_c(w, '{');
    jw_key(w, "path"); jw_str(w, "/dev/usb");
    jw_c(w, ',');
    jw_key(w, "listing");
    emit_listing(w, &g_rep.dev_usb_listing);
    jw_c(w, '}');
    jw_c(w, ']');
    jw_c(w, ',');
    jw_key(w, "stat"); jw_c(w, '[');
    for (i = 0; i < g_rep.node_count; i++) {
        if (i != 0u) jw_c(w, ',');
        emit_node(w, &g_rep.nodes[i]);
    }
    jw_c(w, ']');
    jw_c(w, '}');
    jw_c(w, ',');

    /* pid149 */
    jw_key(w, "pid149");
    jw_c(w, '{');
    jw_key(w, "status");
    if (g_rep.status_err != 0) {
        jw_c(w, '{');
        jw_key(w, "errno"); jw_i32(w, g_rep.status_err);
        jw_c(w, '}');
    } else {
        jw_c(w, '{');
        for (i = 0; i < g_rep.status_count; i++) {
            if (i != 0u) jw_c(w, ',');
            jw_str(w, g_rep.status[i].key);
            jw_c(w, ':');
            jw_str(w, g_rep.status[i].value);
        }
        jw_c(w, '}');
    }
    jw_c(w, ',');
    jw_key(w, "maps_bytes"); jw_u32(w, g_rep.maps_bytes);
    jw_c(w, ',');
    jw_key(w, "maps_truncated"); jw_bool(w, g_rep.maps_truncated);
    jw_c(w, ',');
    jw_key(w, "mapping_lines"); jw_u32(w, g_rep.mapping_lines);
    jw_c(w, ',');
    jw_key(w, "mappings"); jw_c(w, '[');
    for (i = 0; i < g_rep.map_count; i++) {
        const struct map_entry *e = &g_rep.maps[i];
        if (i != 0u) jw_c(w, ',');
        jw_c(w, '{');
        jw_key(w, "path"); jw_str(w, e->path);
        jw_c(w, ',');
        jw_key(w, "target"); jw_str(w, e->target);
        jw_c(w, ',');
        jw_key(w, "base"); jw_u32(w, e->base);
        jw_c(w, ',');
        jw_key(w, "end"); jw_u32(w, e->end);
        jw_c(w, ',');
        jw_key(w, "perms"); jw_str(w, e->perms);
        jw_c(w, '}');
    }
    jw_c(w, ']');
    jw_c(w, ',');
    jw_key(w, "fd_count"); jw_u32(w, g_rep.fd_count);
    jw_c(w, ',');
    jw_key(w, "fds"); jw_c(w, '[');
    for (i = 0; i < g_rep.fd_used; i++) {
        const struct fd_entry *e = &g_rep.fds[i];
        if (i != 0u) jw_c(w, ',');
        jw_c(w, '{');
        jw_key(w, "fd"); jw_str(w, e->fd);
        jw_c(w, ',');
        if (e->err == 0) {
            jw_key(w, "target"); jw_str(w, e->target);
        } else {
            jw_key(w, "errno"); jw_i32(w, e->err);
        }
        jw_c(w, '}');
    }
    jw_c(w, ']');
    jw_c(w, ',');
    jw_key(w, "thread_count"); jw_u32(w, g_rep.thread_count);
    jw_c(w, ',');
    jw_key(w, "thread_err");
    if (g_rep.thread_err == 0) jw_null(w); else jw_i32(w, g_rep.thread_err);
    jw_c(w, '}');
    jw_c(w, ',');

    /* kallsyms */
    jw_key(w, "kallsyms");
    jw_c(w, '{');
    jw_key(w, "readable"); jw_bool(w, g_rep.kallsyms_readable);
    jw_c(w, ',');
    jw_key(w, "bytes_read"); jw_u32(w, g_rep.kallsyms_bytes);
    jw_c(w, ',');
    jw_key(w, "symbols"); jw_c(w, '{');
    for (i = 0; i < 11u; i++) {
        if (i != 0u) jw_c(w, ',');
        jw_str(w, g_rep.syms[i].name);
        jw_c(w, ':');
        if (!g_rep.syms[i].found) {
            jw_null(w);
        } else {
            jw_c(w, '{');
            jw_key(w, "address"); jw_hex(w, g_rep.syms[i].address);
            jw_c(w, ',');
            jw_key(w, "type"); jw_c(w, '"'); jw_c(w, g_rep.syms[i].type); jw_c(w, '"');
            jw_c(w, ',');
            jw_key(w, "restricted"); jw_bool(w, g_rep.syms[i].restricted);
            jw_c(w, '}');
        }
    }
    jw_c(w, '}');
    jw_c(w, '}');
    jw_c(w, ',');

    /* uipc */
    jw_key(w, "uipc");
    jw_c(w, '{');
    jw_key(w, "opened"); jw_bool(w, g_rep.uipc_opened);
    jw_c(w, ',');
    jw_key(w, "errno");
    if (g_rep.uipc_err == 0) jw_null(w); else jw_i32(w, g_rep.uipc_err);
    jw_c(w, ',');
    jw_key(w, "bytes_read"); jw_u32(w, g_rep.uipc_bytes);
    jw_c(w, ',');
    jw_key(w, "truncated"); jw_bool(w, g_rep.uipc_truncated);
    jw_c(w, ',');
    jw_key(w, "minfo_head"); jw_str(w, g_rep.minfo_head);
    jw_c(w, ',');
    jw_key(w, "minfo_errno");
    if (g_rep.minfo_err == 0) jw_null(w); else jw_i32(w, g_rep.minfo_err);
    jw_c(w, ',');
    jw_key(w, "ulogio_head"); jw_str(w, g_rep.ulogio_head);
    jw_c(w, ',');
    jw_key(w, "ulogio_errno");
    if (g_rep.ulogio_err == 0) jw_null(w); else jw_i32(w, g_rep.ulogio_err);
    jw_c(w, ',');
    jw_key(w, "counts"); jw_c(w, '[');
    for (i = 0; i < 4u; i++) {
        if (i != 0u) jw_c(w, ',');
        jw_c(w, '{');
        jw_key(w, "qid"); jw_hex(w, g_qids[i].qid);
        jw_c(w, ',');
        jw_key(w, "ascii_8hex_lower"); jw_u32(w, g_qids[i].lower8);
        jw_c(w, ',');
        jw_key(w, "ascii_8hex_upper"); jw_u32(w, g_qids[i].upper8);
        jw_c(w, ',');
        jw_key(w, "ascii_0x"); jw_u32(w, g_qids[i].prefixed);
        jw_c(w, ',');
        jw_key(w, "raw_le_bytes"); jw_u32(w, g_qids[i].raw_le);
        jw_c(w, '}');
    }
    jw_c(w, ']');
    jw_c(w, '}');
    jw_c(w, ',');

    /* get_jpeg_polls */
    jw_key(w, "get_jpeg_polls");
    if (g_rep.poll_count == 0u) {
        jw_null(w);
    } else {
        jw_c(w, '[');
        for (i = 0; i < g_rep.poll_count; i++) {
            const struct poll_entry *pe = &g_rep.polls[i];
            if (i != 0u) jw_c(w, ',');
            jw_c(w, '{');
            jw_key(w, "index"); jw_u32(w, i);
            jw_c(w, ',');
            jw_key(w, "err"); jw_i32(w, pe->err);
            jw_c(w, ',');
            jw_key(w, "ready"); jw_i32(w, pe->ready);
            jw_c(w, ',');
            jw_key(w, "size_shift");
            if (pe->has_frame) jw_u32(w, pe->size_shift); else jw_null(w);
            jw_c(w, ',');
            jw_key(w, "handle1");
            if (pe->has_frame) jw_u32(w, pe->handle1); else jw_null(w);
            jw_c(w, ',');
            jw_key(w, "handle2");
            if (pe->has_frame) jw_u32(w, pe->handle2); else jw_null(w);
            jw_c(w, ',');
            jw_key(w, "recv_ret"); jw_i32(w, pe->recv_ret);
            jw_c(w, ',');
            jw_key(w, "dmm_cleanup");
            if (pe->has_frame) {
                jw_c(w, '{');
                jw_key(w, "open"); jw_i32(w, pe->cleanup[0]);
                jw_c(w, ',');
                jw_key(w, "close"); jw_i32(w, pe->cleanup[1]);
                jw_c(w, ',');
                jw_key(w, "free_handle1"); jw_i32(w, pe->cleanup[2]);
                jw_c(w, ',');
                jw_key(w, "free_handle2"); jw_i32(w, pe->cleanup[3]);
                jw_c(w, ',');
                jw_key(w, "complete"); jw_bool(w, pe->cleanup_ok);
                jw_c(w, '}');
            } else {
                jw_null(w);
            }
            jw_c(w, '}');
        }
        jw_c(w, ']');
    }
    jw_c(w, ',');

    /* get_jpeg_frame: the single decisive reply, if any */
    jw_key(w, "get_jpeg_frame");
    if (!g_rep.frame.have) {
        jw_null(w);
    } else {
        const struct jpeg_frame *f = &g_rep.frame;
        jw_c(w, '{');
        jw_key(w, "handle1"); jw_u32(w, f->handle1);
        jw_c(w, ',');
        jw_key(w, "handle2"); jw_u32(w, f->handle2);
        jw_c(w, ',');
        jw_key(w, "size_shift"); jw_u32(w, f->size_shift);
        jw_c(w, ',');
        jw_key(w, "size_upper_bound"); jw_u32(w, f->size_upper_bound);
        jw_c(w, ',');
        jw_key(w, "dmm_open_status"); jw_i32(w, f->open_status);
        jw_c(w, ',');
        jw_key(w, "dmm_phys"); jw_hex(w, f->phys);
        jw_c(w, ',');
        jw_key(w, "dmm_size"); jw_u32(w, f->dmm_size);
        jw_c(w, ',');
        jw_key(w, "dmm_close_status"); jw_i32(w, f->close_status);
        jw_c(w, ',');
        jw_key(w, "dmm_free_status"); jw_i32(w, f->free_status);
        jw_c(w, ',');
        jw_key(w, "dmm_free2_status"); jw_i32(w, f->free2_status);
        jw_c(w, ',');
        jw_key(w, "cleanup_complete"); jw_bool(w, f->cleanup_complete);
        jw_c(w, '}');
    }
    jw_c(w, ',');
    jw_key(w, "get_jpeg_error");
    if (g_rep.poll_error == 0) jw_null(w); else jw_i32(w, g_rep.poll_error);
    jw_c(w, ',');

    /* devmem (only when --devmem was requested) */
    if (g_devmem.requested) {
        jw_key(w, "devmem");
        jw_c(w, '{');
        jw_key(w, "pa"); jw_hex(w, g_devmem.pa);
        jw_c(w, ',');
        jw_key(w, "len"); jw_u32(w, g_rep.bnd.devmem_len);
        jw_c(w, ',');
        jw_key(w, "bytes_read"); jw_u32(w, g_devmem.bytes);
        jw_c(w, ',');
        jw_key(w, "nonzero_bytes"); jw_u32(w, g_devmem.nonzero);
        jw_c(w, ',');
        jw_key(w, "head_hex"); jw_str(w, g_devmem.hex);
        jw_c(w, ',');
        jw_key(w, "errno");
        if (g_devmem.err == 0) jw_null(w); else jw_i32(w, g_devmem.err);
        jw_c(w, '}');
        jw_c(w, ',');
    }

    /* bounds */
    jw_key(w, "bounds");
    jw_c(w, '{');
    jw_key(w, "maps_cap_bytes"); jw_u32(w, g_rep.bnd.maps_cap);
    jw_c(w, ',');
    jw_key(w, "maps_bytes_read"); jw_u32(w, g_rep.bnd.maps_bytes);
    jw_c(w, ',');
    jw_key(w, "maps_truncated"); jw_bool(w, g_rep.bnd.maps_truncated);
    jw_c(w, ',');
    jw_key(w, "uipc_cap_bytes"); jw_u32(w, g_rep.bnd.uipc_cap);
    jw_c(w, ',');
    jw_key(w, "uipc_bytes_read"); jw_u32(w, g_rep.bnd.uipc_bytes);
    jw_c(w, ',');
    jw_key(w, "uipc_truncated"); jw_bool(w, g_rep.bnd.uipc_truncated);
    jw_c(w, ',');
    jw_key(w, "kallsyms_cap_bytes"); jw_u32(w, g_rep.bnd.kallsyms_cap);
    jw_c(w, ',');
    jw_key(w, "kallsyms_bytes_read"); jw_u32(w, g_rep.bnd.kallsyms_bytes);
    jw_c(w, ',');
    jw_key(w, "fd_cap"); jw_u32(w, g_rep.bnd.fd_cap);
    jw_c(w, ',');
    jw_key(w, "fd_entries"); jw_u32(w, g_rep.bnd.fd_entries);
    jw_c(w, ',');
    jw_key(w, "dir_names_cap"); jw_u32(w, g_rep.bnd.dir_cap);
    jw_c(w, ',');
    jw_key(w, "get_jpeg_polls_cap"); jw_u32(w, g_rep.bnd.get_jpeg_polls_cap);
    jw_c(w, ',');
    jw_key(w, "poll_count"); jw_u32(w, g_rep.bnd.poll_count);
    jw_c(w, ',');
    jw_key(w, "devmem_len_cap"); jw_u32(w, g_rep.bnd.devmem_cap);
    jw_c(w, ',');
    jw_key(w, "devmem_len"); jw_u32(w, g_rep.bnd.devmem_len);
    jw_c(w, ',');
    jw_key(w, "read_chunk_bytes"); jw_u32(w, g_rep.bnd.read_chunk);
    jw_c(w, ',');
    jw_key(w, "loops_capped"); jw_bool(w, 1);
    jw_c(w, ',');
    jw_key(w, "bulk_devmem_scan"); jw_bool(w, g_rep.bnd.bulk_scan);
    jw_c(w, ',');
    jw_key(w, "device_node_opened_for_io"); jw_bool(w, g_rep.bnd.opened_device_node);
    jw_c(w, '}');
    jw_c(w, ',');

    /* notes */
    jw_key(w, "notes"); jw_c(w, '[');
    for (i = 0; i < g_rep.note_count; i++) {
        if (i != 0u) jw_c(w, ',');
        jw_str(w, g_rep.notes[i]);
    }
    jw_c(w, ']');
    jw_c(w, ',');
    jw_key(w, "exit_code"); jw_i32(w, g_rep.exit_code);
    jw_c(w, '}');
}

/* ------------------------------------------------------------------ */
/* arguments                                                          */
/* ------------------------------------------------------------------ */

struct opts {
    const char *out_path;
    u32 poll_count;
    int poll_ack;
    int devmem_set;
    u32 devmem_pa;
    u32 devmem_len;
};

#define ARGS_OK 0
#define ARGS_HELP 1
#define ARGS_UNSAFE 2

static void print_help(void) {
    log_line("uvc_dma_probe - bounded READ-ONLY ILCE-6400 liveview/DMA diagnostic");
    log_line("");
    log_line("usage: uvc_dma_probe [--out PATH] [--poll-get-jpeg N --i-understand-foreign-get-jpeg]");
    log_line("                     [--devmem PA LEN] [--help]");
    log_line("");
    log_line("  --out PATH     JSON report path (default /tmp_bt/uvc_dma_probe.json)");
    log_line("  --poll-get-jpeg N");
    log_line("                 1..100 foreign DataflowInfra GET_JPEG polls on queue 0x0167046a.");
    log_line("                 CAMERA-SIDE TRANSACTION: requires --i-understand-foreign-get-jpeg");
    log_line("                 and explicit user authorization. Ownership side effects unmeasured.");
    log_line("  --i-understand-foreign-get-jpeg");
    log_line("                 acknowledgement string required by --poll-get-jpeg");
    log_line("  --devmem PA LEN");
    log_line("                 one bounded /dev/mem read; needs PROBE_ENABLE_DEVMEM=1 build and LEN<=4096");
    log_line("  --help         this text");
    log_line("");
    log_line("exit: 0 complete, 2 partial, 3 refused (unsafe args), 4 fatal");
    log_line("No bulk /dev/mem scan, no device open for I/O, no writes outside --out.");
}

static int parse_args(int argc, char **argv, struct opts *o) {
    int i;
    o->out_path = "/tmp_bt/uvc_dma_probe.json";
    o->poll_count = 0;
    o->poll_ack = 0;
    o->devmem_set = 0;
    o->devmem_pa = 0;
    o->devmem_len = 0;

    for (i = 1; i < argc; i++) {
        const char *a = argv[i];
        if (s_eq(a, "--help") || s_eq(a, "-h")) return ARGS_HELP;
        if (s_eq(a, "--out")) {
            if (i + 1 >= argc) return ARGS_UNSAFE;
            o->out_path = argv[++i];
            if (o->out_path[0] == '\0') return ARGS_UNSAFE;
            continue;
        }
        if (s_eq(a, "--poll-get-jpeg")) {
            u32 v = 0;
            if (i + 1 >= argc) return ARGS_UNSAFE;
            if (parse_dec(argv[++i], &v) != 0) return ARGS_UNSAFE;
            if (v == 0u || v > CAP_POLLS) return ARGS_UNSAFE;
            o->poll_count = v;
            continue;
        }
        if (s_eq(a, "--i-understand-foreign-get-jpeg")) { o->poll_ack = 1; continue; }
        if (s_eq(a, "--devmem")) {
            u32 pa = 0, len = 0;
            if (i + 2 >= argc) return ARGS_UNSAFE;
            if (parse_num(argv[++i], &pa) != 0) return ARGS_UNSAFE;
            if (parse_num(argv[++i], &len) != 0) return ARGS_UNSAFE;
            if (pa == 0u || len == 0u || len > CAP_DEVMEM) return ARGS_UNSAFE;
            if (pa > 0xffffffffu - len) return ARGS_UNSAFE;
            o->devmem_set = 1;
            o->devmem_pa = pa;
            o->devmem_len = len;
            continue;
        }
        return ARGS_UNSAFE;
    }
    return ARGS_OK;
}

/* ------------------------------------------------------------------ */
/* main                                                               */
/* ------------------------------------------------------------------ */

int probe_main(int argc, char **argv) {
    struct opts o;
    struct jw w;
    int rc;
    int out_fd;
    int partial = 0;
    int failed = 0;
    int uipc_trunc;

    rc = parse_args(argc, argv, &o);
    if (rc == ARGS_HELP) { print_help(); return 0; }
    if (rc != ARGS_OK) {
        log_line("[probe] REFUSED: unknown or unsafe argument");
        log_line("[probe] run with --help for the accepted argument set");
        return 3;
    }
    if (o.poll_count > 0u && !o.poll_ack) {
        log_line("[probe] REFUSED: --poll-get-jpeg requires --i-understand-foreign-get-jpeg");
        log_line("[probe] nothing was sent; no camera-side transaction was started");
        return 3;
    }
#if !PROBE_ENABLE_DEVMEM
    if (o.devmem_set) {
        log_line("[probe] REFUSED: build has PROBE_ENABLE_DEVMEM=0; rebuild with 1 to allow");
        log_line("[probe] one bounded <=4096-byte read");
        return 3;
    }
#endif

    log_line("=== A6400 UVC/DMA READ-ONLY PROBE ===");
    log_line("[probe] mode: observational only; no device node is opened for I/O,");
    log_line("[probe]       no /dev/mem is opened unless --devmem, no camera state is written");
    log_line("[probe] bounds: every read and every loop is capped (see bounds in the JSON)");

    g_rep.bnd.maps_cap = CAP_MAPS;
    g_rep.bnd.uipc_cap = CAP_UIPC;
    g_rep.bnd.kallsyms_cap = CAP_KALLSYMS;
    g_rep.bnd.fd_cap = CAP_FD;
    g_rep.bnd.dir_cap = CAP_DIR_NAMES;
    g_rep.bnd.get_jpeg_polls_cap = CAP_POLLS;
    g_rep.bnd.devmem_cap = CAP_DEVMEM;
    g_rep.bnd.read_chunk = CAP_SMALL;
    g_rep.bnd.bulk_scan = 0;
    g_rep.bnd.opened_device_node = 0;

    add_note("read-only diagnostic; no bulk /dev/mem scan (AGENTS.MD E0454)");
    add_note("probe authored offline; the authoring task did not run it on hardware");
    add_note("every read and directory walk is capped; caps are in bounds");

    /* ---- observational collection ---- */
    collect_identity();
    collect_modules();
    collect_udc();
    collect_devnodes();
    collect_status();
    collect_maps();
    collect_fds();
    g_rep.thread_count = dir_count("/proc/149/task", &g_rep.thread_err);
    collect_kallsyms();
    collect_uipc();

    g_rep.bnd.maps_bytes = g_rep.maps_bytes;
    g_rep.bnd.maps_truncated = g_rep.maps_truncated;
    g_rep.bnd.kallsyms_bytes = g_rep.kallsyms_bytes;
    g_rep.bnd.fd_entries = g_rep.fd_used;
    g_rep.bnd.poll_count = 0;

    if (g_rep.identity_err[0] != 0 || g_rep.identity_err[1] != 0 ||
        g_rep.identity_err[2] != 0 || g_rep.modules_err != 0 ||
        g_rep.udc_err != 0 || g_rep.status_err != 0 || g_rep.maps_err != 0 ||
        g_rep.maps_truncated || g_rep.fd_err != 0 ||
        g_rep.kallsyms_readable == 0 || g_rep.uipc_err != 0 ||
        g_rep.uipc_truncated) {
        partial = 1;
    }
    uipc_trunc = g_rep.uipc_truncated;
    if (uipc_trunc) add_note("uipc window truncated at cap; counts are lower bounds");
    if (g_rep.dev_listing.err != 0) add_note("/dev listing failed (see devnodes.listings)");
    if (g_rep.dev_usb_listing.err != 0) add_note("/dev/usb listing failed (see devnodes.listings)");

    /* ---- optional bounded /dev/mem read ---- */
    if (o.devmem_set) {
        log_line("[probe] --devmem: performing ONE bounded read");
        run_devmem(o.devmem_pa, o.devmem_len);
        if (g_devmem.err != 0) partial = 1;
    }

    /* ---- opt-in foreign GET_JPEG poll ---- */
    if (o.poll_count > 0u) {
        log_line("");
        log_line("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!");
        log_line("!! WARNING: --poll-get-jpeg is a CAMERA-SIDE DataflowInfra       !!");
        log_line("!! transaction on queue 0x0167046a (Scalar GET_JPEG, 40-byte     !!");
        log_line("!! packet). It is NOT a passive read. The PC-Remote ownership    !!");
        log_line("!! side effects of a foreign poll are UNMEASURED, and the frame  !!");
        log_line("!! unit it may hand back is closed/freed by this probe or the    !!");
        log_line("!! probe stops with exit 2 and reports the ambiguity.            !!");
        log_line("!! Requires explicit user authorization before any hardware run. !!");
        log_line("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!");
        add_note("GET_JPEG polls requested with --i-understand-foreign-get-jpeg: "
                 "camera-side transaction, ownership side effects unmeasured");
        run_poll_sequence(o.poll_count);
        g_rep.bnd.poll_count = g_rep.poll_count;
        log_line("[probe] polls completed: ");
        log_u32(g_rep.poll_count);
        log_line("");
        if (g_rep.poll_error != 0) partial = 1;
        if (g_rep.frame.have && !g_rep.frame.cleanup_complete) partial = 1;
        if (g_rep.frame.have) {
            log_line("[probe] first frame reply: size_shift=");
            log_u32(g_rep.frame.size_shift);
            log_line(" phys=");
            log_hex(g_rep.frame.phys);
            log_line(" dmm_size=");
            log_u32(g_rep.frame.dmm_size);
            log_line("");
        }
    } else {
        add_note("GET_JPEG polls not requested (default observational mode)");
    }

    g_rep.exit_code = partial ? 2 : 0;

    /* ---- emit ---- */
    out_fd = fs_open_out(o.out_path);
    if (out_fd < 0) {
        log_line("[probe] FATAL: cannot open --out path for writing");
        return 4;
    }
    w.fd = out_fd;
    w.len = 0;
    w.failed = 0;
    emit_report(&w);
    jw_c(&w, '\n');
    jw_flush(&w);
    failed = w.failed;
    fs_close(out_fd);
    if (failed) {
        log_line("[probe] FATAL: short write to --out");
        return 4;
    }
    log_line("[probe] report written to --out");
    log_line(partial ? "[probe] result: PARTIAL (see notes/bounds)"
                     : "[probe] result: COMPLETE");

    log_line("PROBE_RESULT below");
    write_all(g_stdout, "PROBE_RESULT ", 13);
    w.fd = g_stdout;
    w.len = 0;
    w.failed = 0;
    emit_report(&w);
    jw_c(&w, '\n');
    jw_flush(&w);
    if (w.failed) return 4;
    return g_rep.exit_code;
}

/* ------------------------------------------------------------------ */
/* entry point                                                        */
/* ------------------------------------------------------------------ */

#if !PROBE_HOST
__attribute__((naked, noreturn)) void _start(void) {
    __asm__ __volatile__(
        "mov r0, sp\n\t"
        "ldr r1, [r0]\n\t"
        "add r2, r0, #4\n\t"
        "mov r0, r1\n\t"
        "mov r1, r2\n\t"
        "bl probe_main\n\t"
        "mov r7, #1\n\t"
        "svc #0\n\t"
        "b .\n\t");
}
#else /* PROBE_HOST entry: x86-64, argv from the raw entry stack */

/*
 * A naked/asm entry is required: any C prologue may adjust %rsp before the
 * compiler-supplied "mov %rsp" would run, which would lose argc/argv.
 */
__asm__(
    ".text\n"
    ".globl _start\n"
    ".type _start,@function\n"
    "_start:\n"
    "xor %rbp, %rbp\n"
    "mov (%rsp), %rdi\n"
    "lea 8(%rsp), %rsi\n"
    "and $-16, %rsp\n"
    "call probe_main\n"
    "mov %eax, %edi\n"
    "mov $231, %eax\n"
    "syscall\n"
    "hlt\n"
    ".size _start, .-_start\n");
#endif
