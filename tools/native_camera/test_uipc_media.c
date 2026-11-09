/*
 * test_uipc_media.c
 * Test OSAL UIPC queue allocation and messaging on 0x00318474 and 0x00ca8192
 */

#define SYS_exit      1
#define SYS_write     4
#define SYS_open      5
#define SYS_close     6
#define SYS_ioctl     54
#define SYS_nanosleep 162
#define SYS_mmap2     192

#define O_RDWR        2
#define PROT_READ     1
#define PROT_WRITE    2
#define MAP_SHARED    1

#define QUEUE_OBJMEDIA 0x00318474
#define QUEUE_APPMGR   0x00ca8192
#define QUEUE_SCALAR   0x0167046a
#define QUEUE_DMM      0x0061003c

struct timespec { long tv_sec; long tv_nsec; };

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
static inline int sys_write(int fd, const void *buf, int count) {
    register int r0 __asm__("r0") = fd;
    register int r1 __asm__("r1") = (int)buf;
    register int r2 __asm__("r2") = count;
    register int r7 __asm__("r7") = SYS_write;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}
static inline int sys_ioctl(int fd, unsigned long req, void *arg) {
    register int r0 __asm__("r0") = fd;
    register int r1 __asm__("r1") = (int)req;
    register int r2 __asm__("r2") = (int)arg;
    register int r7 __asm__("r7") = SYS_ioctl;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}
static inline void *sys_mmap2(void *addr, unsigned long length, int prot, int flags, int fd, unsigned long pgoff) {
    register int r0 __asm__("r0") = (int)addr;
    register int r1 __asm__("r1") = (int)length;
    register int r2 __asm__("r2") = prot;
    register int r3 __asm__("r3") = flags;
    register int r4 __asm__("r4") = fd;
    register int r5 __asm__("r5") = (int)pgoff;
    register int r7 __asm__("r7") = SYS_mmap2;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r3), "r"(r4), "r"(r5), "r"(r7) : "memory");
    return (void *)r0;
}
static inline void sys_exit(int c) {
    register int r0 __asm__("r0") = c;
    register int r7 __asm__("r7") = SYS_exit;
    __asm__ __volatile__("svc 0" : : "r"(r0), "r"(r7) : "memory");
    while(1){}
}

static void print_str(const char *s) {
    int len = 0; while (s[len]) len++; sys_write(1, s, len);
}
static void print_int(int v) {
    char buf[16]; int i = 0;
    if (v < 0) { sys_write(1, "-", 1); v = -v; }
    if (v == 0) { sys_write(1, "0", 1); return; }
    while (v > 0) { buf[i++] = '0' + (v % 10); v /= 10; }
    for (int j = 0; j < i/2; j++) { char t = buf[j]; buf[j] = buf[i-1-j]; buf[i-1-j] = t; }
    sys_write(1, buf, i);
}

void *memset(void *s, int c, unsigned int n) {
    char *p = (char *)s;
    while (n--) *p++ = (char)c;
    return s;
}

static int uipc_fd = -1;
static unsigned int g_reply_qid = 0;

static int osal_valloc_msg(unsigned int qid, void **p_msg, unsigned int size) {
    struct { void **msg_pptr; unsigned int size; unsigned int wait_flag; } val_sub;
    val_sub.msg_pptr = p_msg;
    val_sub.size = size;
    val_sub.wait_flag = 1;

    struct { unsigned int qid; void *sub_ptr; } val_req;
    val_req.qid = qid;
    val_req.sub_ptr = &val_sub;

    return sys_ioctl(uipc_fd, 0x8000000a, &val_req);
}

static int osal_free_msg(unsigned int qid, void *msg) {
    struct { unsigned int qid; void *msg_ptr; } req;
    req.qid = qid;
    req.msg_ptr = msg;
    return sys_ioctl(uipc_fd, 0x8000000b, &req);
}

void _start(void) {
    print_str("=== TEST UIPC QUEUES ===\n");
    uipc_fd = sys_open("/dev/uipc", O_RDWR, 0);
    if (uipc_fd < 0) { print_str("open /dev/uipc failed\n"); sys_exit(1); }

    unsigned int out_meta[8];
    memset(out_meta, 0, sizeof(out_meta));
    struct { unsigned int param; void *out_ptr; } req_init;
    req_init.param = 0;
    req_init.out_ptr = out_meta;

    int ret = sys_ioctl(uipc_fd, 0x80000010, &req_init);
    print_str("IOCTL_INIT ret="); print_int(ret); print_str("\n");
    if (ret != 0) sys_exit(2);

    void *pool = sys_mmap2(0, out_meta[0], PROT_READ | PROT_WRITE, MAP_SHARED, uipc_fd, 0);
    print_str("MMAP_POOL pool="); print_int((int)pool); print_str("\n");

    // Test valloc on 0x00318474 (ObjMedia)
    void *msg_media = 0;
    int ret_media = osal_valloc_msg(QUEUE_OBJMEDIA, &msg_media, 8);
    print_str("VALLOC_OBJMEDIA (0x00318474, size=8) ret="); print_int(ret_media);
    print_str(" msg="); print_int((int)msg_media); print_str("\n");
    if (ret_media == 0 && msg_media) {
        osal_free_msg(QUEUE_OBJMEDIA, msg_media);
    }

    // Test valloc on 0x00ca8192 (AppMgr)
    void *msg_app = 0;
    int ret_app = osal_valloc_msg(QUEUE_APPMGR, &msg_app, 32);
    print_str("VALLOC_APPMGR (0x00ca8192, size=32) ret="); print_int(ret_app);
    print_str(" msg="); print_int((int)msg_app); print_str("\n");
    if (ret_app == 0 && msg_app) {
        osal_free_msg(QUEUE_APPMGR, msg_app);
    }

    // Test valloc on 0x0167046a (Scalar)
    void *msg_scalar = 0;
    int ret_scalar = osal_valloc_msg(QUEUE_SCALAR, &msg_scalar, 40);
    print_str("VALLOC_SCALAR (0x0167046a, size=40) ret="); print_int(ret_scalar);
    print_str(" msg="); print_int((int)msg_scalar); print_str("\n");
    if (ret_scalar == 0 && msg_scalar) {
        osal_free_msg(QUEUE_SCALAR, msg_scalar);
    }

    sys_close(uipc_fd);
    print_str("=== TEST FINISHED ===\n");
    sys_exit(0);
}
