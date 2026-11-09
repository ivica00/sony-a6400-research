/*
 * uvc_acquire_single_jpeg.c - Standalone native ARM single JPEG frame acquisition
 *
 * Implements complete evidence-backed pipeline:
 * 1. Native OSAL UIPC channel initialization (/dev/uipc)
 * 2. Purge any stale messages in g_reply_qid
 * 3. DMM AllocRule 5 activation (Shooting / LiveView rule) on queue 0x0061003c
 * 4. Verify Unit 0x276 & 0x274 are unallocated so ScalarJpegOpen can allocate
 * 5. Synchronous SET_PATH configuration (1280x720 @ 30 FPS) on queue 0x0167046a
 * 6. Detailed dump of SET_PATH response packet
 * 7. Polling GET_JPEG frame request on queue 0x0167046a
 * 8. DMM unit open (cmd 5) to acquire physical address
 * 9. Save single verified frame to /tmp_bt/sensor_frame_720p.jpg
 * 10. Complete resource cleanup: DMM close & free frame, SET_PATH reset (cmd 0),
 *     clean any lingering units, Rule 0 restoration
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
#define O_CREAT    64
#define O_TRUNC    512

#define PROT_READ  1
#define PROT_WRITE 2
#define MAP_SHARED 1

#define QUEUE_SCALAR   0x0167046a
#define QUEUE_DMM      0x0061003c

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

static inline int sys_nanosleep(const struct timespec *req, struct timespec *rem) {
    register int r0 __asm__("r0") = (int)req;
    register int r1 __asm__("r1") = (int)rem;
    register int r7 __asm__("r7") = SYS_nanosleep;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r7) : "memory");
    return r0;
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

static void print_byte_hex(unsigned char b) {
    const char hex_chars[] = "0123456789abcdef";
    char buf[3];
    buf[0] = hex_chars[(b >> 4) & 0xf];
    buf[1] = hex_chars[b & 0xf];
    buf[2] = ' ';
    sys_write(1, buf, 3);
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

/* OSAL UIPC channel */
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

static void purge_reply_queue(void) {
    int count = 0;
    while (1) {
        void *msg = 0;
        struct { void **p; unsigned int tmo; } rcv_sub = {&msg, 0};
        struct { unsigned int q; void *s; } rcv_req = {g_reply_qid, &rcv_sub};
        int r = sys_ioctl(uipc_fd, 0x80000007, &rcv_req);
        if (r != 0 || !msg) break;
        osal_free_msg(g_reply_qid, msg);
        count++;
    }
    if (count > 0) {
        print_str("    Purged ");
        print_int(count);
        print_str(" stale messages from reply queue\n");
    }
}

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

    purge_reply_queue();
    return 0;
}

static void osal_cleanup(void) {
    if (g_reply_qid != 0 && uipc_fd >= 0) {
        purge_reply_queue();
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

/* DMM Operations on QUEUE_DMM (0x0061003c) */
static int dmm_set_alloc_rule(unsigned char rule, unsigned short mode) {
    void *msg = 0;
    int ret = osal_valloc_msg(QUEUE_DMM, &msg, 32);
    if (ret != 0 || !msg) return -1;

    unsigned char *p = (unsigned char *)msg;
    memset(p, 0, 32);
    *(unsigned short *)(p + 0x00) = 20; /* opcode 20: SetAllocRule */
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

static int dmm_get_unit_handle(unsigned int unit_type, unsigned short *out_handle) {
    void *msg = 0;
    int ret = osal_valloc_msg(QUEUE_DMM, &msg, 32);
    if (ret != 0 || !msg) return -1;

    unsigned char *p = (unsigned char *)msg;
    memset(p, 0, 32);
    *(unsigned short *)(p + 0x00) = 26; /* opcode 26: GetUnitHandle */
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

static int dmm_free_unit(unsigned int handle) {
    if (handle == 0 || handle == 0xffff) return 0;
    void *msg = 0;
    int ret = osal_valloc_msg(QUEUE_DMM, &msg, 24);
    if (ret != 0 || !msg) return -1;

    unsigned char *p = (unsigned char *)msg;
    memset(p, 0, 24);
    *(unsigned short *)(p + 0x00) = 4; /* opcode 4: FreeUnit */
    *(unsigned short *)(p + 0x02) = (unsigned short)handle;
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

static int dmm_open_unit(unsigned int handle, unsigned int *p_phys, unsigned int *p_size) {
    void *msg = 0;
    int ret = osal_valloc_msg(QUEUE_DMM, &msg, 24);
    if (ret != 0 || !msg) return -1;

    unsigned char *p = (unsigned char *)msg;
    memset(p, 0, 24);
    *(unsigned short *)(p + 0x00) = 5; /* opcode 5: OpenUnit */
    *(unsigned short *)(p + 0x02) = (unsigned short)handle;
    *(unsigned int   *)(p + 0x0c) = 0xffffffff;
    *(unsigned int   *)((char *)msg - 4) = g_reply_qid;

    ret = osal_send_msg(QUEUE_DMM, msg);
    if (ret != 0) return -2;

    void *reply = 0;
    ret = osal_recv_msg(g_reply_qid, &reply, 800);
    if (ret != 0 || !reply) return -3;

    short status = *(short *)((char *)reply + 2);
    if (status != 0) {
        osal_free_msg(g_reply_qid, reply);
        return status;
    }

    *p_phys = *(unsigned int *)((char *)reply + 16);
    *p_size = *(unsigned int *)((char *)reply + 20);

    osal_free_msg(g_reply_qid, reply);
    return 0;
}

static int dmm_close_unit(unsigned int handle) {
    if (handle == 0 || handle == 0xffff) return 0;
    void *msg = 0;
    int ret = osal_valloc_msg(QUEUE_DMM, &msg, 24);
    if (ret != 0 || !msg) return -1;

    unsigned char *p = (unsigned char *)msg;
    memset(p, 0, 24);
    *(unsigned short *)(p + 0x00) = 6; /* opcode 6: CloseUnit */
    *(unsigned short *)(p + 0x02) = (unsigned short)handle;
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

/* DataflowInfra Header - DataflowInfra uses internal reply_id at offset +0, do NOT touch msg[-4] */
static void fill_dataflow_header(unsigned char *hdr, unsigned int reply_id, unsigned short payload_len) {
    *(unsigned int   *)(hdr + 0x00) = reply_id;
    *(unsigned int   *)(hdr + 0x04) = 0xa0a0a0a0;
    *(unsigned short *)(hdr + 0x08) = 1;
    *(unsigned short *)(hdr + 0x0a) = (unsigned short)(20 + payload_len);
    *(unsigned int   *)(hdr + 0x0c) = 20;
    *(unsigned int   *)(hdr + 0x10) = 20;
}

/* SET_PATH: sends configuration packet (88 bytes) to QUEUE_SCALAR (0x0167046a) */
static int send_set_path(int path_enable, int rate_fps, int width, int comp_level, int param_val, int timeout_ms, int dump_resp) {
    purge_reply_queue();

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
    ret = osal_recv_msg(g_reply_qid, &reply, timeout_ms);
    if (ret != 0 || !reply) return -3;

    if (dump_resp) {
        print_str("    RESP_HEX: ");
        unsigned char *rb = (unsigned char *)reply;
        for (int i = 0; i < 48; i++) {
            print_byte_hex(rb[i]);
        }
        print_str("\n");
    }

    int status = *(int *)((char *)reply + 20 + 12);
    osal_free_msg(g_reply_qid, reply);
    return status;
}

/* GET_JPEG: requests current frame (40 bytes) from QUEUE_SCALAR (0x0167046a) */
static int send_get_jpeg(unsigned int *p_handle1, unsigned int *p_size, unsigned int *p_handle2) {
    purge_reply_queue();

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

    print_str("    GET_RESP_HEX: ");
    unsigned char *rb = (unsigned char *)reply;
    for (int i = 0; i < 40; i++) {
        print_byte_hex(rb[i]);
    }
    print_str("\n");

    unsigned char *r_payload = (unsigned char *)reply + 20;
    unsigned int err = *(unsigned int *)(r_payload + 12);
    unsigned char ready = *(unsigned char *)(r_payload + 16);

    if (err != 0 || ready == 0) {
        osal_free_msg(g_reply_qid, reply);
        return 1; /* Not ready */
    }

    *p_handle1 = *(unsigned short *)(r_payload + 20);
    unsigned short size_shift = *(unsigned short *)(r_payload + 22);
    *p_size = ((unsigned int)size_shift) << 7;
    *p_handle2 = *(unsigned short *)(r_payload + 24);

    osal_free_msg(g_reply_qid, reply);
    return 0;
}

void _start(void) {
    print_str("=== A6400 NATIVE SENSOR JPEG ACQUISITION ===\n");

    int ret = osal_init();
    print_str("OSAL_INIT=");
    print_int(ret);
    print_str(" REPLY_QID=");
    print_hex(g_reply_qid);
    print_str("\n");
    if (ret != 0) {
        osal_cleanup();
        sys_exit(1);
    }

    /* 1. Activate DMM Rule 5 */
    print_str("[1] Setting DMM Rule 5 (Shooting / LiveView)...\n");
    int st_rule = dmm_set_alloc_rule(5, 0);
    print_str("    DMM_RULE5_RET=");
    print_int(st_rule);
    print_str("\n");

    /* 2. Check and clean any lingering Unit 0x276 & 0x274 so ScalarJpegOpen can allocate freshly */
    unsigned short h276 = 0xffff, h274 = 0xffff;
    int st_g276 = dmm_get_unit_handle(0x276, &h276);
    int st_g274 = dmm_get_unit_handle(0x274, &h274);
    print_str("[2] Pre-check Unit 0x276 h=");
    print_hex(h276);
    print_str("; Unit 0x274 h=");
    print_hex(h274);
    print_str("\n");

    if (st_g276 == 0 && h276 != 0 && h276 != 0xffff) {
        print_str("    Freeing lingering 0x276...\n");
        dmm_free_unit(h276);
    }
    if (st_g274 == 0 && h274 != 0 && h274 != 0xffff) {
        print_str("    Freeing lingering 0x274...\n");
        dmm_free_unit(h274);
    }

    /* 3. SET_PATH reset first */
    print_str("[3] Sending SET_PATH reset...\n");
    ret = send_set_path(0, 0, 0, 0, 0, 1500, 1);
    print_str("    SET_PATH_RESET_RET=");
    print_int(ret);
    print_str("\n");

    /* 4. SET_PATH start (1280x720 30FPS, comp=5, param=300) with 5000ms timeout */
    print_str("[4] Sending SET_PATH start (1280x720, 30 FPS, comp=5, param=300, tmo=5000ms)...\n");
    ret = send_set_path(1, 30, 1280, 5, 300, 5000, 1);
    print_str("    SET_PATH_START_RET=");
    print_int(ret);
    print_str("\n");

    /* 5. Poll GET_JPEG for up to 30 attempts */
    print_str("[5] Polling GET_JPEG for sensor frame...\n");
    unsigned int handle1 = 0;
    unsigned int frame_size = 0;
    unsigned int handle2 = 0;
    int got_frame = 0;

    for (int attempt = 1; attempt <= 30; attempt++) {
        ret = send_get_jpeg(&handle1, &frame_size, &handle2);
        if (ret == 0 && frame_size > 0 && handle1 != 0 && handle1 != 0xffff) {
            print_str("    FRAME ACQUIRED on attempt ");
            print_int(attempt);
            print_str(": handle1=");
            print_hex(handle1);
            print_str(" size=");
            print_int(frame_size);
            print_str(" handle2=");
            print_hex(handle2);
            print_str("\n");
            got_frame = 1;
            break;
        }
        msleep(100);
    }

    if (got_frame) {
        /* 6. Open DMM unit of acquired frame */
        print_str("[6] Calling DMM open_unit on frame handle...\n");
        unsigned int phys_addr = 0;
        unsigned int dmm_size = 0;
        ret = dmm_open_unit(handle1, &phys_addr, &dmm_size);
        print_str("    DMM_OPEN_RET=");
        print_int(ret);
        print_str(" PHYS_ADDR=");
        print_hex(phys_addr);
        print_str(" DMM_SIZE=");
        print_int(dmm_size);
        print_str("\n");

        if (ret == 0 && phys_addr != 0) {
            int mem_fd = sys_open("/dev/mem", O_RDONLY, 0);
            if (mem_fd >= 0) {
                unsigned int page_base = phys_addr & ~0xfff;
                unsigned int page_offset = phys_addr & 0xfff;
                unsigned int map_len = (page_offset + frame_size + 0xfff) & ~0xfff;
                void *mapped = sys_mmap2(0, map_len, PROT_READ, MAP_SHARED, mem_fd, page_base >> 12);
                if ((int)mapped >= 0 || (int)mapped <= -4096) {
                    unsigned char *f_data = (unsigned char *)mapped + page_offset;
                    if (f_data[0] == 0xff && f_data[1] == 0xd8) {
                        print_str("    PASS: Verified JPEG SOI (0xFFD8)\n");
                    }
                    if (frame_size > 2 && f_data[frame_size - 2] == 0xff && f_data[frame_size - 1] == 0xd9) {
                        print_str("    PASS: Verified JPEG EOI (0xFFD9)\n");
                    }

                    /* Save frame to /tmp_bt/sensor_frame_720p.jpg */
                    int out_fd = sys_open("/tmp_bt/sensor_frame_720p.jpg", O_WRONLY | O_CREAT | O_TRUNC, 0666);
                    if (out_fd >= 0) {
                        int written = sys_write(out_fd, f_data, frame_size);
                        sys_close(out_fd);
                        print_str("    Saved ");
                        print_int(written);
                        print_str(" bytes to /tmp_bt/sensor_frame_720p.jpg\n");
                    }
                }
                sys_close(mem_fd);
            }
            dmm_close_unit(handle1);
            dmm_free_unit(handle1);
            if (handle2 != 0 && handle2 != 0xffff) dmm_free_unit(handle2);
        }
    } else {
        print_str("NOTE: No frame acquired in polling loop (ret=");
        print_int(ret);
        print_str(")\n");
    }

    /* 7. Reset SET_PATH back to idle */
    print_str("[7] Resetting SET_PATH back to idle...\n");
    ret = send_set_path(0, 0, 0, 0, 0, 1500, 1);
    print_str("    SET_PATH_STOP_RET=");
    print_int(ret);
    print_str("\n");

    /* 8. Check and clean any units created by ScalarJpegOpen before restoring Rule 0 */
    h276 = 0xffff;
    st_g276 = dmm_get_unit_handle(0x276, &h276);
    if (st_g276 == 0 && h276 != 0 && h276 != 0xffff) {
        print_str("    Cleanup Unit 0x276 h=");
        print_hex(h276);
        print_str("\n");
        dmm_free_unit(h276);
    }
    h274 = 0xffff;
    st_g274 = dmm_get_unit_handle(0x274, &h274);
    if (st_g274 == 0 && h274 != 0 && h274 != 0xffff) {
        print_str("    Cleanup Unit 0x274 h=");
        print_hex(h274);
        print_str("\n");
        dmm_free_unit(h274);
    }

    /* 9. Restore Rule 0 */
    print_str("[9] Restoring Rule 0...\n");
    int st_r0 = dmm_set_alloc_rule(0, 0);
    print_str("    RESTORE_RULE0_RET=");
    print_int(st_r0);
    print_str("\n");

    /* 10. OSAL cleanup */
    osal_cleanup();
    print_str("=== ACQUISITION EXECUTION FINISHED ===\n");
    sys_exit(0);
}
