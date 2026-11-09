/*
 * probe_dmm_rule.c - Freestanding ARM utility to query and test DMM AllocRule and unit allocation
 *
 * Implements:
 * 1. OSAL /dev/uipc initialization
 * 2. Opcode 0x1a (26): GetUnitHandle(unit_type)
 * 3. Opcode 0x14 (20): SetAllocRule(rule, mode)
 * 4. Opcode 0x01 (1):  AllocUnitNew(unit_type, flags)
 * 5. Safe restoration of Rule 0 before exit
 */

#define SYS_exit      1
#define SYS_read      3
#define SYS_write     4
#define SYS_open      5
#define SYS_close     6
#define SYS_ioctl     54
#define SYS_nanosleep 162
#define SYS_mmap2     192

#define O_RDONLY   0
#define O_WRONLY   1
#define O_RDWR     2

#define PROT_READ  1
#define PROT_WRITE 2
#define MAP_SHARED 1

#define QUEUE_DMM  0x0061003c

struct timespec {
    long tv_sec;
    long tv_nsec;
};

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

static inline void sys_nanosleep(const struct timespec *req, struct timespec *rem) {
    register int r0 __asm__("r0") = (int)req;
    register int r1 __asm__("r1") = (int)rem;
    register int r7 __asm__("r7") = SYS_nanosleep;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r7) : "memory");
}

static inline void sys_exit(int code) {
    register int r0 __asm__("r0") = code;
    register int r7 __asm__("r7") = SYS_exit;
    __asm__ __volatile__("svc 0" : : "r"(r0), "r"(r7) : "memory");
    while (1) {}
}

static void print_str(const char *s) {
    int len = 0;
    while (s[len]) len++;
    sys_write(1, s, len);
}

static void print_hex(unsigned int val) {
    char buf[11];
    buf[0] = '0';
    buf[1] = 'x';
    const char hex_chars[] = "0123456789abcdef";
    for (int i = 7; i >= 0; i--) {
        buf[2 + (7 - i)] = hex_chars[(val >> (i * 4)) & 0xf];
    }
    buf[10] = '\0';
    sys_write(1, buf, 10);
}

static void print_int(int v) {
    char buf[16];
    int i = 0;
    if (v < 0) {
        sys_write(1, "-", 1);
        v = -v;
    }
    if (v == 0) {
        sys_write(1, "0", 1);
        return;
    }
    while (v > 0) {
        buf[i++] = '0' + (v % 10);
        v /= 10;
    }
    for (int j = 0; j < i / 2; j++) {
        char tmp = buf[j];
        buf[j] = buf[i - 1 - j];
        buf[i - 1 - j] = tmp;
    }
    sys_write(1, buf, i);
}

static void my_memset(void *dst, int val, int n) {
    char *d = (char *)dst;
    for (int i = 0; i < n; i++) d[i] = (char)val;
}

static int uipc_fd = -1;
static unsigned int g_reply_qid = 0;

static int osal_init(void) {
    uipc_fd = sys_open("/dev/uipc", O_RDWR, 0);
    if (uipc_fd < 0) return -1;

    unsigned int out_meta[8];
    my_memset(out_meta, 0, sizeof(out_meta));
    struct { unsigned int param; void *out_ptr; } req_init;
    req_init.param = 0;
    req_init.out_ptr = out_meta;

    int ret = sys_ioctl(uipc_fd, 0x80000010, &req_init);
    if (ret != 0) return -2;

    void *pool = sys_mmap2(0, out_meta[0], PROT_READ | PROT_WRITE, MAP_SHARED, uipc_fd, 0);
    if ((int)pool < 0 && (int)pool > -4096) return -3;

    struct { unsigned int op; unsigned int param; unsigned int *id_out; } dyn_sub;
    dyn_sub.op = 0x2a;
    dyn_sub.param = 729;
    dyn_sub.id_out = &g_reply_qid;
    struct { unsigned int zero; void *sub_ptr; } dyn_req;
    dyn_req.zero = 0;
    dyn_req.sub_ptr = &dyn_sub;

    ret = sys_ioctl(uipc_fd, 0x8000000c, &dyn_req);
    if (ret != 0) return -4;

    return 0;
}

static void osal_cleanup(void) {
    if (g_reply_qid != 0 && uipc_fd >= 0) {
        struct { unsigned int op; unsigned int param; unsigned int *id_out; } dyn_sub;
        dyn_sub.op = 0x4a;
        dyn_sub.param = 0;
        dyn_sub.id_out = (unsigned int *)g_reply_qid;
        struct { unsigned int zero; void *sub_ptr; } dyn_req;
        dyn_req.zero = 0;
        dyn_req.sub_ptr = &dyn_sub;
        sys_ioctl(uipc_fd, 0x8000000c, &dyn_req);
        g_reply_qid = 0;
    }
    if (uipc_fd >= 0) {
        sys_close(uipc_fd);
        uipc_fd = -1;
    }
}

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

static int osal_send_msg(unsigned int qid, void *msg) {
    struct { unsigned int qid; void *msg_ptr; } req;
    req.qid = qid;
    req.msg_ptr = msg;
    return sys_ioctl(uipc_fd, 0x80000004, &req);
}

static int osal_recv_msg(unsigned int qid, void **p_msg, unsigned int timeout_ms) {
    struct { void **msg_pptr; unsigned int timeout_ms; } rcv_sub;
    rcv_sub.msg_pptr = p_msg;
    rcv_sub.timeout_ms = timeout_ms;

    struct { unsigned int qid; void *sub_ptr; } rcv_req;
    rcv_req.qid = qid;
    rcv_req.sub_ptr = &rcv_sub;

    return sys_ioctl(uipc_fd, 0x80000007, &rcv_req);
}

/* Opcode 0x1a (26): GetUnitHandle */
static int dmm_get_unit_handle(unsigned int unit_type, unsigned short *out_handle) {
    void *msg = 0;
    int ret = osal_valloc_msg(QUEUE_DMM, &msg, 32);
    if (ret != 0 || !msg) return -1;

    unsigned char *p = (unsigned char *)msg;
    my_memset(p, 0, 32);
    *(unsigned short *)(p + 0x00) = 26; /* opcode 26 = 0x1a */
    *(unsigned int   *)(p + 0x04) = unit_type;
    *(unsigned int   *)((char *)msg - 4) = g_reply_qid;

    ret = osal_send_msg(QUEUE_DMM, msg);
    if (ret != 0) return -2;

    void *reply = 0;
    ret = osal_recv_msg(g_reply_qid, &reply, 800);
    if (ret != 0 || !reply) return -3;

    short status = *(short *)((char *)reply + 2);
    unsigned short handle = *(unsigned short *)((char *)reply + 4);
    if (out_handle) *out_handle = handle;

    osal_free_msg(g_reply_qid, reply);
    return status;
}

/* Opcode 0x14 (20): SetAllocRule */
static int dmm_set_alloc_rule(unsigned char rule, unsigned short mode) {
    void *msg = 0;
    int ret = osal_valloc_msg(QUEUE_DMM, &msg, 32);
    if (ret != 0 || !msg) return -1;

    unsigned char *p = (unsigned char *)msg;
    my_memset(p, 0, 32);
    *(unsigned short *)(p + 0x00) = 20; /* opcode 20 = 0x14 */
    *(unsigned char  *)(p + 0x02) = rule;
    *(unsigned short *)(p + 0x16) = mode;
    *(unsigned int   *)((char *)msg - 4) = g_reply_qid;

    ret = osal_send_msg(QUEUE_DMM, msg);
    if (ret != 0) return -2;

    void *reply = 0;
    ret = osal_recv_msg(g_reply_qid, &reply, 800);
    if (ret != 0 || !reply) return -3;

    short status = *(short *)((char *)reply + 2);
    osal_free_msg(g_reply_qid, reply);
    return status;
}

/* Opcode 0x01 (1): AllocUnitNew */
static int dmm_alloc_unit_new(unsigned int unit_type, unsigned short flags, unsigned short *out_handle) {
    void *msg = 0;
    int ret = osal_valloc_msg(QUEUE_DMM, &msg, 32);
    if (ret != 0 || !msg) return -1;

    unsigned char *p = (unsigned char *)msg;
    my_memset(p, 0, 32);
    *(unsigned short *)(p + 0x00) = 1; /* opcode 1 */
    *(unsigned int   *)(p + 0x04) = unit_type;
    *(unsigned short *)(p + 0x16) = flags;
    *(unsigned int   *)((char *)msg - 4) = g_reply_qid;

    ret = osal_send_msg(QUEUE_DMM, msg);
    if (ret != 0) return -2;

    void *reply = 0;
    ret = osal_recv_msg(g_reply_qid, &reply, 800);
    if (ret != 0 || !reply) return -3;

    short status = *(short *)((char *)reply + 2);
    unsigned short handle = *(unsigned short *)((char *)reply + 4);
    if (out_handle) *out_handle = handle;

    osal_free_msg(g_reply_qid, reply);
    return status;
}

void _start(void) {
    print_str("[PROBE_DMM] OSAL init...\n");
    int ret = osal_init();
    if (ret != 0) {
        print_str("[PROBE_DMM] OSAL init failed: ");
        print_int(ret);
        print_str("\n");
        sys_exit(1);
    }
    print_str("[PROBE_DMM] OSAL init OK, reply_qid=");
    print_hex(g_reply_qid);
    print_str("\n");

    /* 1. Pre-check Unit 0x276 & 0x274 */
    unsigned short h276 = 0xffff, h274 = 0xffff;
    int st276 = dmm_get_unit_handle(0x276, &h276);
    int st274 = dmm_get_unit_handle(0x274, &h274);
    print_str("[PROBE_DMM] BEFORE SetAllocRule: 0x276 st=");
    print_int(st276);
    print_str(" h=");
    print_hex(h276);
    print_str(", 0x274 st=");
    print_int(st274);
    print_str(" h=");
    print_hex(h274);
    print_str("\n");

    /* 2. Set Rule 5 (Shooting / LiveView) */
    print_str("[PROBE_DMM] Calling SetAllocRule(5, 0)...\n");
    int st_set5 = dmm_set_alloc_rule(5, 0);
    print_str("[PROBE_DMM] SetAllocRule(5) result=");
    print_int(st_set5);
    print_str("\n");

    /* 3. Check if Unit 0x276 can be queried or allocated */
    h276 = 0xffff;
    st276 = dmm_get_unit_handle(0x276, &h276);
    print_str("[PROBE_DMM] AFTER SetAllocRule(5): 0x276 st=");
    print_int(st276);
    print_str(" h=");
    print_hex(h276);
    print_str("\n");

    /* If not automatically allocated, try AllocUnitNew(0x276, 0) */
    if (st276 != 0 || h276 == 0xffff) {
        print_str("[PROBE_DMM] Trying AllocUnitNew(0x276, 0)...\n");
        unsigned short alloc_h = 0xffff;
        int alloc_st = dmm_alloc_unit_new(0x276, 0, &alloc_h);
        print_str("[PROBE_DMM] AllocUnitNew(0x276) st=");
        print_int(alloc_st);
        print_str(" h=");
        print_hex(alloc_h);
        print_str("\n");
    }

    /* 4. Restore Rule 0 for safety */
    print_str("[PROBE_DMM] Restoring SetAllocRule(0, 0)...\n");
    int st_set0 = dmm_set_alloc_rule(0, 0);
    print_str("[PROBE_DMM] SetAllocRule(0) result=");
    print_int(st_set0);
    print_str("\n");

    osal_cleanup();
    print_str("[PROBE_DMM] Done.\n");
    sys_exit(0);
}
