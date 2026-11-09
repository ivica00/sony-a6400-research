/*
 * test_sensor_activate_and_acquire.c
 *
 * Combines PTP-style shooting activation on ObjMedia (0x0000610c)
 * with verified DMM Rule 5 and ScalarInfra SET_PATH on QUEUE_SCALAR (0x0167046a),
 * then polls GET_JPEG for real sensor frames.
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
#define QUEUE_MEDIA    0x0000610c
#define QUEUE_REMOTE   0x01690472

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

static inline void sys_exit(int c) {
    register int r0 __asm__("r0") = c;
    register int r7 __asm__("r7") = SYS_exit;
    __asm__ __volatile__("svc 0" : : "r"(r0), "r"(r7) : "memory");
    while(1){}
}

static void print_str(const char *s) {
    int len = 0; while (s[len]) len++; sys_write(1, s, len);
}
static void print_hex(unsigned int v) {
    const char h[] = "0123456789abcdef";
    char b[11] = "0x00000000";
    for (int i=7; i>=0; i--) b[2 + (7-i)] = h[(v >> (i*4)) & 0xf];
    sys_write(1, b, 10);
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
    char buf[16]; int i = 0;
    if (v < 0) { sys_write(1, "-", 1); v = -v; }
    if (v == 0) { sys_write(1, "0", 1); return; }
    while (v > 0) { buf[i++] = '0' + (v % 10); v /= 10; }
    for (int j = 0; j < i/2; j++) { char t = buf[j]; buf[j] = buf[i-1-j]; buf[i-1-j] = t; }
    sys_write(1, buf, i);
}
static void msleep(int ms) {
    struct timespec ts;
    ts.tv_sec = ms / 1000;
    ts.tv_nsec = (ms % 1000) * 1000000L;
    sys_nanosleep(&ts, 0);
}
void *memset(void *s, int c, unsigned int n) {
    char *p = (char *)s;
    while (n--) *p++ = (char)c;
    return s;
}

unsigned int strlen(const char *s) {
    unsigned int len = 0;
    while (s[len]) len++;
    return len;
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
    while (1) {
        void *msg = 0;
        struct { void **p; unsigned int tmo; } rcv_sub = {&msg, 0};
        struct { unsigned int q; void *s; } rcv_req = {g_reply_qid, &rcv_sub};
        int r = sys_ioctl(uipc_fd, 0x80000007, &rcv_req);
        if (r != 0 || !msg) break;
        osal_free_msg(g_reply_qid, msg);
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

/* Verified DMM wire framing: reply_qid at msg-4 */
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

static void fill_dataflow_header(unsigned char *hdr, unsigned int reply_id, unsigned short payload_len) {
    *(unsigned int   *)(hdr + 0x00) = reply_id;
    *(unsigned int   *)(hdr + 0x04) = 0xa0a0a0a0;
    *(unsigned short *)(hdr + 0x08) = 1;
    *(unsigned short *)(hdr + 0x0a) = (unsigned short)(20 + payload_len);
    *(unsigned int   *)(hdr + 0x0c) = 20;
    *(unsigned int   *)(hdr + 0x10) = 20;
}

static int send_set_path(int path_enable, int rate_fps, int comp_level, int width, int param_val, int timeout_ms) {
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

    int status = *(int *)((char *)reply + 20 + 12);
    osal_free_msg(g_reply_qid, reply);
    return status;
}

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

    unsigned char *r_payload = (unsigned char *)reply + 20;
    unsigned int err = *(unsigned int *)(r_payload + 12);
    unsigned char ready = *(unsigned char *)(r_payload + 16);

    print_str("      [GET_JPEG] err=");
    print_int(err);
    print_str(" ready=");
    print_int(ready);

    if (err != 0 || ready == 0) {
        print_str("\n");
        osal_free_msg(g_reply_qid, reply);
        return 1; /* Not ready */
    }

    *p_handle1 = *(unsigned short *)(r_payload + 20);
    unsigned short size_shift = *(unsigned short *)(r_payload + 22);
    *p_size = ((unsigned int)size_shift) << 7;
    *p_handle2 = *(unsigned short *)(r_payload + 24);

    print_str(" handle1=");
    print_hex(*p_handle1);
    print_str(" size=");
    print_int(*p_size);
    print_str(" handle2=");
    print_hex(*p_handle2);
    print_str("\n");

    osal_free_msg(g_reply_qid, reply);
    return 0;
}

/* Send ObjMsg to ObjMedia / ObjRemote */
static int send_mwf_objmsg(unsigned int target_qid, unsigned int category_id, unsigned int msg_id, unsigned int p_id, unsigned int p_val) {
    purge_reply_queue();
    void *msg = 0;
    unsigned int msg_size = (p_id != 0) ? 24 : 12;
    int ret = osal_valloc_msg(target_qid, &msg, msg_size);
    if (ret != 0 || !msg) return -1;

    unsigned char *p = (unsigned char *)msg;
    for (unsigned int i = 0; i < msg_size; i++) p[i] = 0;

    unsigned int *w = (unsigned int *)msg;
    w[0] = category_id;
    w[1] = msg_id;
    w[2] = (p_id != 0) ? 1 : 0;

    if (p_id != 0) {
        w[3] = p_id;
        w[4] = 7; /* Param::Type 7 = int */
        w[5] = p_val;
    }

    ret = osal_send_msg(target_qid, msg);
    return ret;
}

void _start(void) {
    print_str("=== A6400 LIVE SENSOR ACTIVATION & ACQUISITION ===\n");

    int ret = osal_init();
    print_str("OSAL_INIT="); print_int(ret); print_str("\n");
    if (ret != 0) { osal_cleanup(); sys_exit(1); }

    /* Step 1: DMM Rule 5 activation */
    print_str("[1] Activating DMM Rule 5...\n");
    int r5 = dmm_set_alloc_rule(5, 0);
    print_str("    Rule 5 RET="); print_int(r5); print_str("\n");

    /* Step 2: ObjMedia PTP-style activation sequence */
    print_str("[2] Sending PTP Activation Sequence to ObjMedia (0x0000610c)...\n");
    /* 2a: ObjMsg(0x610c, 3) RemoteAppActivatedEvt */
    int s1 = send_mwf_objmsg(QUEUE_MEDIA, 0x610c, 3, 0, 0);
    print_str("    [2a] ObjMsg(0x610c, 3) RemoteAppActivated RET="); print_int(s1); print_str("\n");

    /* 2b: ObjMsg(0x610c, 0x100d) actionRemoteAppActInact */
    int s2 = send_mwf_objmsg(QUEUE_MEDIA, 0x610c, 0x100d, 0, 0);
    print_str("    [2b] ObjMsg(0x610c, 0x100d) RemoteAppAct RET="); print_int(s2); print_str("\n");

    /* 2c: ObjMsg(0x610c, 0x14) PC Priority (Param 0x1000 = 0xd25a) */
    int s3 = send_mwf_objmsg(QUEUE_MEDIA, 0x610c, 0x14, 0x1000, 0xd25a);
    print_str("    [2c] ObjMsg(0x610c, 0x14) PC Priority RET="); print_int(s3); print_str("\n");

    /* 2d: ObjMsg(0x610c, 0x15) LiveView ON (Param 0x1002 = 0x9e000001) */
    int s4 = send_mwf_objmsg(QUEUE_MEDIA, 0x610c, 0x15, 0x1002, 0x9e000001);
    print_str("    [2d] ObjMsg(0x610c, 0x15) LiveView ON RET="); print_int(s4); print_str("\n");

    /* Step 3: ObjRemote ping on 0x01690472 */
    print_str("[3] Pinging ObjRemote (0x01690472)...\n");
    int s5 = send_mwf_objmsg(QUEUE_REMOTE, 0x6108, 1, 0, 0);
    print_str("    ObjRemote ping RET="); print_int(s5); print_str("\n");

    /* Sleep 1000ms for ISP and sensor wake-up */
    print_str("[4] Waiting 1000ms for ISP wake-up...\n");
    msleep(1000);

    /* Step 5: SET_PATH reset then start (1280x720, 30 FPS) on QUEUE_SCALAR */
    unsigned short h276 = 0xffff, h274 = 0xffff;
    int st_g276 = dmm_get_unit_handle(0x276, &h276);
    int st_g274 = dmm_get_unit_handle(0x274, &h274);
    if (st_g276 == 0 && h276 != 0 && h276 != 0xffff) dmm_free_unit(h276);
    if (st_g274 == 0 && h274 != 0 && h274 != 0xffff) dmm_free_unit(h274);

    print_str("[5a] Sending SET_PATH reset to QUEUE_SCALAR...\n");
    int rst_ret = send_set_path(0, 0, 0, 0, 0, 1500);
    print_str("    SET_PATH reset RET="); print_int(rst_ret); print_str("\n");

    print_str("[5b] Sending SET_PATH start (1280x720 30FPS) to QUEUE_SCALAR...\n");
    int sp_ret = send_set_path(1, 30, 5, 1280, 300, 5000);
    print_str("    SET_PATH start RET="); print_int(sp_ret); print_str("\n");

    /* Step 6: Polling GET_JPEG for real frames */
    print_str("[6] Polling GET_JPEG for sensor frames (up to 30 iterations)...\n");
    unsigned int h1 = 0, sz = 0, h2 = 0;
    int got_frame = 0;

    for (int iter = 0; iter < 30; iter++) {
        msleep(200);
        int gr = send_get_jpeg(&h1, &sz, &h2);
        if (gr == 0 && sz > 0) {
            print_str(">>> SENSOR FRAME ACQUIRED! iter=");
            print_int(iter);
            print_str(" size=");
            print_int(sz);
            print_str(" handle1=");
            print_hex(h1);
            print_str("\n");
            got_frame = 1;

            /* Open DMM unit to get physical address */
            unsigned int phys = 0, unit_size = 0;
            int op_ret = dmm_open_unit(h1, &phys, &unit_size);
            print_str("    DMM OpenUnit(h1) RET=");
            print_int(op_ret);
            print_str(" PHYS=");
            print_hex(phys);
            print_str(" UNIT_SZ=");
            print_int(unit_size);
            print_str("\n");

            if (op_ret == 0 && phys != 0) {
                int km_fd = sys_open("/dev/kmem", O_RDONLY, 0);
                if (km_fd >= 0) {
                    void *mapped = sys_mmap2(0, sz + 4096, PROT_READ, MAP_SHARED, km_fd, phys >> 12);
                    if ((int)mapped > 0) {
                        unsigned char *fb = (unsigned char *)mapped + (phys & 0xfff);
                        print_str("    SOI: ");
                        print_byte_hex(fb[0]);
                        print_byte_hex(fb[1]);
                        print_str(" EOI: ");
                        print_byte_hex(fb[sz-2]);
                        print_byte_hex(fb[sz-1]);
                        print_str("\n");

                        /* Save frame */
                        int out_fd = sys_open("/tmp_bt/sensor_frame_720p.jpg", O_WRONLY | O_CREAT | O_TRUNC, 0666);
                        if (out_fd >= 0) {
                            sys_write(out_fd, fb, sz);
                            sys_close(out_fd);
                            print_str("    Saved sensor frame to /tmp_bt/sensor_frame_720p.jpg\n");
                        }
                    }
                    sys_close(km_fd);
                }
                dmm_close_unit(h1);
            }
            break;
        }
    }

    if (!got_frame) {
        print_str("[-] No ready sensor frame within timeout.\n");
    }

    /* Step 7: Teardown */
    print_str("[7] Teardown & cleanup...\n");
    int stop_ret = send_set_path(0, 0, 0, 0, 0, 2000);
    print_str("    SET_PATH stop RET="); print_int(stop_ret); print_str("\n");

    h276 = 0xffff; h274 = 0xffff;
    st_g276 = dmm_get_unit_handle(0x276, &h276);
    st_g274 = dmm_get_unit_handle(0x274, &h274);
    if (st_g276 == 0 && h276 != 0 && h276 != 0xffff) dmm_free_unit(h276);
    if (st_g274 == 0 && h274 != 0 && h274 != 0xffff) dmm_free_unit(h274);

    int r0 = dmm_set_alloc_rule(0, 0);
    print_str("    Rule 0 restored RET="); print_int(r0); print_str("\n");

    osal_cleanup();
    print_str("=== TEST FINISHED ===\n");
    sys_exit(0);
}
