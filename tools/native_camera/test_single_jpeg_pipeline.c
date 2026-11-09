/*
 * test_single_jpeg_pipeline.c - Freestanding ARM test of the complete DMM Rule 5 + SET_PATH + GET_JPEG pipeline
 */

#define SYS_exit      1
#define SYS_read      3
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

#define QUEUE_SCALAR  0x0167046a
#define QUEUE_DMM     0x0061003c

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

void *memset(void *s, int c, unsigned int n) {
    char *p = (char *)s;
    while (n--) *p++ = (char)c;
    return s;
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

static void msleep(int ms) {
    struct timespec ts;
    ts.tv_sec = ms / 1000;
    ts.tv_nsec = (ms % 1000) * 1000000L;
    sys_nanosleep(&ts, 0);
}

static int uipc_fd = -1;
static unsigned int g_reply_qid = 0;

static int osal_init(void) {
    uipc_fd = sys_open("/dev/uipc", O_RDWR, 0);
    if (uipc_fd < 0) return -1;

    unsigned int out_meta[8];
    memset(out_meta, 0, sizeof(out_meta));
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

/* DMM Operations */
static int dmm_set_alloc_rule(unsigned char rule, unsigned short mode) {
    void *msg = 0;
    int ret = osal_valloc_msg(QUEUE_DMM, &msg, 32);
    if (ret != 0 || !msg) return -1;

    unsigned char *p = (unsigned char *)msg;
    memset(p, 0, 32);
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

static int dmm_alloc_unit_new(unsigned int unit_type, unsigned short flags, unsigned short *out_handle) {
    void *msg = 0;
    int ret = osal_valloc_msg(QUEUE_DMM, &msg, 32);
    if (ret != 0 || !msg) return -1;

    unsigned char *p = (unsigned char *)msg;
    memset(p, 0, 32);
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

static int dmm_free_unit(unsigned short handle) {
    if (handle == 0 || handle == 0xffff) return 0;
    void *msg = 0;
    int ret = osal_valloc_msg(QUEUE_DMM, &msg, 32);
    if (ret != 0 || !msg) return -1;

    unsigned char *p = (unsigned char *)msg;
    memset(p, 0, 32);
    *(unsigned short *)(p + 0x00) = 4; /* opcode 4 */
    *(unsigned short *)(p + 0x02) = handle;
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

/* DataflowInfra Header */
static void fill_dataflow_header(unsigned char *hdr, unsigned int reply_id, unsigned short payload_len) {
    *(unsigned int   *)(hdr + 0x00) = reply_id;
    *(unsigned int   *)(hdr + 0x04) = 0xa0a0a0a0;
    *(unsigned short *)(hdr + 0x08) = 1;
    *(unsigned short *)(hdr + 0x0a) = (unsigned short)(20 + payload_len);
    *(unsigned int   *)(hdr + 0x0c) = 20;
    *(unsigned int   *)(hdr + 0x10) = 20;
}

/* SET_PATH */
static int send_set_path(int path_enable, int rate_fps, int width, int comp_level, int param_val) {
    void *msg = 0;
    int ret = osal_valloc_msg(QUEUE_SCALAR, &msg, 88);
    if (ret != 0 || !msg) return -1;

    unsigned char *p = (unsigned char *)msg;
    memset(p, 0, 88);
    fill_dataflow_header(p, g_reply_qid, 68);

    unsigned char *payload = p + 20;
    *(unsigned short *)(payload + 0x00) = 0x2009;
    *(unsigned short *)(payload + 0x02) = 0x0100;
    *(unsigned short *)(payload + 0x04) = 0x0044;
    *(unsigned short *)(payload + 0x06) = 1;
    *(unsigned int   *)(payload + 0x08) = 0;
    *(unsigned short *)(payload + 0x0c) = 0;
    *(unsigned char  *)(payload + 0x0e) = 0;
    *(unsigned char  *)(payload + 0x0f) = 0x50;
    *(unsigned short *)(payload + 0x10) = (unsigned short)(rate_fps << 8);
    *(unsigned char  *)(payload + 0x12) = 1;
    *(unsigned char  *)(payload + 0x13) = (unsigned char)comp_level;
    *(unsigned short *)(payload + 0x14) = (unsigned short)width;
    *(unsigned short *)(payload + 0x16) = 0;
    *(unsigned int   *)(payload + 0x18) = (unsigned int)param_val;
    *(unsigned char  *)(payload + 0x1c) = 0;
    *(unsigned char  *)(payload + 0x1d) = 1;
    *(unsigned char  *)(payload + 0x1e) = 4;
    *(unsigned char  *)(payload + 0x1f) = 1;
    *(unsigned char  *)(payload + 0x40) = (unsigned char)(path_enable ? 1 : 0);

    ret = osal_send_msg(QUEUE_SCALAR, msg);
    if (ret != 0) return -2;

    void *reply = 0;
    ret = osal_recv_msg(g_reply_qid, &reply, 800);
    if (ret != 0 || !reply) return -3;

    int status = *(int *)((char *)reply + 20 + 12);
    osal_free_msg(g_reply_qid, reply);
    return status;
}

/* GET_JPEG */
static int send_get_jpeg(unsigned int *p_handle1, unsigned int *p_size, unsigned int *p_handle2, unsigned char *p_ready) {
    void *msg = 0;
    int ret = osal_valloc_msg(QUEUE_SCALAR, &msg, 40);
    if (ret != 0 || !msg) return -1;

    unsigned char *p = (unsigned char *)msg;
    memset(p, 0, 40);
    fill_dataflow_header(p, g_reply_qid, 20);

    unsigned char *payload = p + 20;
    *(unsigned short *)(payload + 0x00) = 0x2009;
    *(unsigned short *)(payload + 0x02) = 0x0100;
    *(unsigned short *)(payload + 0x04) = 0x0014;
    *(unsigned short *)(payload + 0x06) = 1;
    *(unsigned int   *)(payload + 0x08) = 0;
    *(unsigned short *)(payload + 0x0c) = 0;
    *(unsigned char  *)(payload + 0x0e) = 0;
    *(unsigned char  *)(payload + 0x0f) = 0x20;
    *(unsigned char  *)(payload + 0x10) = 1;

    ret = osal_send_msg(QUEUE_SCALAR, msg);
    if (ret != 0) return -2;

    void *reply = 0;
    ret = osal_recv_msg(g_reply_qid, &reply, 800);
    if (ret != 0 || !reply) return -3;

    unsigned char *r_payload = (unsigned char *)reply + 20;
    unsigned int err = *(unsigned int *)(r_payload + 12);
    unsigned char ready = *(unsigned char *)(r_payload + 16);
    if (p_ready) *p_ready = ready;

    if (err == 0 && ready != 0) {
        *p_handle1 = *(unsigned short *)(r_payload + 20);
        unsigned short size_shift = *(unsigned short *)(r_payload + 22);
        *p_size = ((unsigned int)size_shift) << 7;
        *p_handle2 = *(unsigned short *)(r_payload + 24);
    }

    osal_free_msg(g_reply_qid, reply);
    return err;
}

void _start(void) {
    print_str("[TEST_PIPELINE] Initializing OSAL...\n");
    int ret = osal_init();
    if (ret != 0) {
        print_str("[TEST_PIPELINE] OSAL init failed: ");
        print_int(ret);
        print_str("\n");
        sys_exit(1);
    }
    print_str("[TEST_PIPELINE] OSAL init OK, qid=");
    print_hex(g_reply_qid);
    print_str("\n");

    /* 1. Set Rule 5 */
    print_str("[TEST_PIPELINE] Setting DMM Rule 5...\n");
    int st_rule = dmm_set_alloc_rule(5, 0);
    print_str("[TEST_PIPELINE] SetAllocRule(5) ret=");
    print_int(st_rule);
    print_str("\n");

    /* 2. Allocate UnitType 0x276 (JPEG Sequence Buffer) */
    unsigned short h276 = 0xffff;
    int st_276 = dmm_alloc_unit_new(0x276, 0, &h276);
    print_str("[TEST_PIPELINE] AllocUnitNew(0x276) ret=");
    print_int(st_276);
    print_str(" handle=");
    print_hex(h276);
    print_str("\n");

    /* 3. Allocate UnitType 0x274 (JPEG Frame Buffer) */
    unsigned short h274 = 0xffff;
    int st_274 = dmm_alloc_unit_new(0x274, 0, &h274);
    print_str("[TEST_PIPELINE] AllocUnitNew(0x274) ret=");
    print_int(st_274);
    print_str(" handle=");
    print_hex(h274);
    print_str("\n");

    /* 4. Reset path first (status 0) */
    print_str("[TEST_PIPELINE] Sending SET_PATH reset...\n");
    int st_reset = send_set_path(0, 30, 1280, 1, 0x1e00);
    print_str("[TEST_PIPELINE] SET_PATH reset ret=");
    print_int(st_reset);
    print_str("\n");

    /* 5. Start path (status 1: 1280x720 @ 30 FPS) */
    print_str("[TEST_PIPELINE] Sending SET_PATH start (1280x720 30FPS)...\n");
    int st_start = send_set_path(1, 30, 1280, 1, 0x1e00);
    print_str("[TEST_PIPELINE] SET_PATH start ret=");
    print_int(st_start);
    print_str("\n");

    /* 6. Poll GET_JPEG for 5 iterations */
    print_str("[TEST_PIPELINE] Polling GET_JPEG...\n");
    for (int iter = 0; iter < 5; iter++) {
        unsigned int h1 = 0, sz = 0, h2 = 0;
        unsigned char ready = 0;
        int get_err = send_get_jpeg(&h1, &sz, &h2, &ready);
        print_str("  iter ");
        print_int(iter);
        print_str(": err=");
        print_int(get_err);
        print_str(" ready=");
        print_int(ready);
        if (ready) {
            print_str(" h1=");
            print_hex(h1);
            print_str(" sz=");
            print_int(sz);
            print_str(" h2=");
            print_hex(h2);
        }
        print_str("\n");
        msleep(100);
    }

    /* 7. Stop path (status 0) */
    print_str("[TEST_PIPELINE] Sending SET_PATH stop...\n");
    int st_stop = send_set_path(0, 30, 1280, 1, 0x1e00);
    print_str("[TEST_PIPELINE] SET_PATH stop ret=");
    print_int(st_stop);
    print_str("\n");

    /* 8. Free DMM units */
    if (h274 != 0xffff) {
        print_str("[TEST_PIPELINE] Freeing Unit 0x274...\n");
        int st_f274 = dmm_free_unit(h274);
        print_str("[TEST_PIPELINE] Free 0x274 ret=");
        print_int(st_f274);
        print_str("\n");
    }
    if (h276 != 0xffff) {
        print_str("[TEST_PIPELINE] Freeing Unit 0x276...\n");
        int st_f276 = dmm_free_unit(h276);
        print_str("[TEST_PIPELINE] Free 0x276 ret=");
        print_int(st_f276);
        print_str("\n");
    }

    /* 9. Restore Rule 0 */
    print_str("[TEST_PIPELINE] Restoring Rule 0...\n");
    int st_r0 = dmm_set_alloc_rule(0, 0);
    print_str("[TEST_PIPELINE] SetAllocRule(0) ret=");
    print_int(st_r0);
    print_str("\n");

    osal_cleanup();
    print_str("[TEST_PIPELINE] Complete.\n");
    sys_exit(0);
}
