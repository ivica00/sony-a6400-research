/*
 * uvc_sensor_feeder_30fps.c - Coherent 30 FPS UVC Feeder with Native Sensor JPEG Source
 *
 * Direct Linux ARMv7-A EABI syscalls (svc 0) - standalone, zero libc dependencies.
 * 
 * Pipeline:
 * 1. OSAL UIPC init -> DMM Rule 5 activation -> SET_PATH start (1280x720 30FPS)
 * 2. Character device /tmp_bt/video open -> IOCTL_UVC_MOD_QUERY_DMA -> IOCTL_UVC_INIT
 * 3. IOCTL_UVC_REG_BUF (owned coherent DMA) -> IOCTL_UVC_ENABLE
 * 4. Streaming loop (33.33ms absolute CLOCK_MONOTONIC pacing):
 *    - Query GET_JPEG from QUEUE_SCALAR (0x0167046a)
 *    - If ready: DMM open -> copy to coherent ping-pong DMA slot -> DMM close & free
 *    - If not ready: keep active/fallback frame in coherent slot
 *    - IOCTL_UVC_WAIT -> IOCTL_UVC_UPDATE
 * 5. Clean teardown: SET_PATH stop (0) -> Rule 0 restore -> IOCTL_UVC_UNREG -> IOCTL_UVC_STOP
 */

#define SYS_exit            1
#define SYS_read            3
#define SYS_write           4
#define SYS_open            5
#define SYS_close           6
#define SYS_ioctl           54
#define SYS_nanosleep       162
#define SYS_mmap2           192
#define SYS_clock_gettime   263
#define SYS_clock_nanosleep 265

#define O_RDONLY    0
#define O_WRONLY    1
#define O_RDWR      2
#define O_CREAT     64
#define O_TRUNC     512

#define PROT_READ   1
#define PROT_WRITE  2
#define MAP_SHARED  1

#define CLOCK_MONOTONIC     1
#define TIMER_ABSTIME       1

/* UVC IOCTLs */
#define IOCTL_UVC_INIT         0x4038e000
#define IOCTL_UVC_STOP         0x0000e001
#define IOCTL_UVC_REG_BUF      0x4008f000
#define IOCTL_UVC_UNREG        0x0000f001
#define IOCTL_UVC_UPDATE       0x4008f003
#define IOCTL_UVC_WAIT         0x0000f002
#define IOCTL_UVC_ENABLE       0x0000f006
#define IOCTL_UVC_MOD_QUERY_DMA 0x8010f020

#define QUEUE_SCALAR   0x0167046a
#define QUEUE_DMM      0x0061003c

struct timespec {
    long tv_sec;
    long tv_nsec;
};

struct a6400_uvc_dma_metadata {
    unsigned int phys_addr;
    unsigned int total_size;
    unsigned int slot_size;
    unsigned int max_frame_payload;
};

struct usbg_video_buf_info {
    unsigned int size;
    unsigned int phys_addr;
};

struct usbg_video_data_info {
    unsigned int frame_size;
    unsigned int phys_addr;
};

struct uvc_user_probe_info {
    void *context;
    void (*callbacks[8])(void);
    void *interfaces_ptr;
    unsigned int reserved40;
    unsigned char reserved44;
    unsigned char interface_count;
    unsigned short reserved46;
    void *extra_info_ptr;
    unsigned int extra_info_size;
};

static void dummy_cb(void) {}

static unsigned char g_interfaces[4] = { 0, 0, 1, 1 };

/* Fallback 1280x720 test pattern */
#include "test_pattern_720p.h"

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

static inline int sys_clock_gettime(int clk_id, struct timespec *tp) {
    register int r0 __asm__("r0") = clk_id;
    register int r1 __asm__("r1") = (int)tp;
    register int r7 __asm__("r7") = SYS_clock_gettime;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r7) : "memory");
    return r0;
}

static inline int sys_clock_nanosleep(int clk_id, int flags, const struct timespec *req, struct timespec *rem) {
    register int r0 __asm__("r0") = clk_id;
    register int r1 __asm__("r1") = flags;
    register int r2 __asm__("r2") = (int)req;
    register int r3 __asm__("r3") = (int)rem;
    register int r7 __asm__("r7") = SYS_clock_nanosleep;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r3), "r"(r7) : "memory");
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

void *memcpy(void *dest, const void *src, unsigned int n) {
    char *d = (char *)dest;
    const char *s = (const char *)src;
    while (n--) *d++ = *s++;
    return dest;
}

static void print_str(const char *s) {
    int len = 0;
    while (s[len]) len++;
    sys_write(1, s, len);
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

/* OSAL /dev/uipc */
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

/* DMM */
static int dmm_set_alloc_rule(unsigned char rule, unsigned short mode) {
    void *msg = 0;
    int ret = osal_valloc_msg(QUEUE_DMM, &msg, 32);
    if (ret != 0 || !msg) return -1;

    unsigned char *p = (unsigned char *)msg;
    memset(p, 0, 32);
    *(unsigned short *)(p + 0x00) = 20;
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

static int dmm_free_unit(unsigned int handle) {
    if (handle == 0 || handle == 0xffff) return 0;
    void *msg = 0;
    int ret = osal_valloc_msg(QUEUE_DMM, &msg, 24);
    if (ret != 0 || !msg) return -1;

    unsigned char *p = (unsigned char *)msg;
    memset(p, 0, 24);
    *(unsigned short *)(p + 0x00) = 4;
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
    *(unsigned short *)(p + 0x00) = 5;
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
    *(unsigned short *)(p + 0x00) = 6;
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

/* Dataflow */
static void fill_dataflow_header(unsigned char *hdr, unsigned int reply_id, unsigned short payload_len) {
    *(unsigned int   *)(hdr + 0x00) = reply_id;
    *(unsigned int   *)(hdr + 0x04) = 0xa0a0a0a0;
    *(unsigned short *)(hdr + 0x08) = 1;
    *(unsigned short *)(hdr + 0x0a) = (unsigned short)(20 + payload_len);
    *(unsigned int   *)(hdr + 0x0c) = 20;
    *(unsigned int   *)(hdr + 0x10) = 20;
}

static int send_set_path(int path_enable, int rate_fps, int width, int comp_level, int param_val, int timeout_ms) {
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
    ret = osal_recv_msg(g_reply_qid, &reply, 50);
    if (ret != 0 || !reply) return -3;

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
    print_str("=== A6400 COHERENT SENSOR UVC FEEDER (30 FPS) ===\n");

    /* 1. OSAL & DMM initialization */
    int ret = osal_init();
    if (ret != 0) {
        print_str("[ERR] OSAL init failed: ");
        print_int(ret);
        print_str("\n");
        sys_exit(1);
    }

    int st_rule = dmm_set_alloc_rule(5, 0);
    print_str("[feeder] DMM Rule 5 status=");
    print_int(st_rule);
    print_str("\n");

    /* SET_PATH reset first, then start 720p30 */
    send_set_path(0, 0, 0, 0, 0, 1500);
    ret = send_set_path(1, 30, 1280, 5, 300, 5000);
    print_str("[feeder] SET_PATH 720p30 status=");
    print_int(ret);
    print_str("\n");

    /* 2. Character device /tmp_bt/video open */
    int uvc_fd = sys_open("/tmp_bt/video", O_RDWR, 0);
    if (uvc_fd < 0) {
        print_str("[ERR] Failed to open /tmp_bt/video: ");
        print_int(uvc_fd);
        print_str("\n");
        send_set_path(0, 0, 0, 0, 0, 1500);
        dmm_set_alloc_rule(0, 0);
        osal_cleanup();
        sys_exit(2);
    }

    /* 3. Query coherent DMA metadata */
    struct a6400_uvc_dma_metadata dma_meta;
    memset(&dma_meta, 0, sizeof(dma_meta));
    ret = sys_ioctl(uvc_fd, IOCTL_UVC_MOD_QUERY_DMA, &dma_meta);
    if (ret != 0) {
        print_str("[ERR] IOCTL_UVC_MOD_QUERY_DMA failed: ");
        print_int(ret);
        print_str("\n");
        sys_close(uvc_fd);
        send_set_path(0, 0, 0, 0, 0, 1500);
        dmm_set_alloc_rule(0, 0);
        osal_cleanup();
        sys_exit(3);
    }

    print_str("[feeder] Owned DMA: phys=");
    print_hex(dma_meta.phys_addr);
    print_str(" total=");
    print_int(dma_meta.total_size);
    print_str(" slot=");
    print_int(dma_meta.slot_size);
    print_str(" max_payload=");
    print_int(dma_meta.max_frame_payload);
    print_str("\n");

    /* 4. Register UVC driver descriptors */
    struct uvc_user_probe_info probe_info;
    memset(&probe_info, 0, sizeof(probe_info));
    probe_info.context = 0;
    for (int i = 0; i < 8; i++) probe_info.callbacks[i] = dummy_cb;
    probe_info.interfaces_ptr = g_interfaces;
    probe_info.interface_count = 2;

    ret = sys_ioctl(uvc_fd, IOCTL_UVC_INIT, &probe_info);
    print_str("[feeder] IOCTL_UVC_INIT status=");
    print_int(ret);
    print_str("\n");
    if (ret != 0) {
        sys_close(uvc_fd);
        send_set_path(0, 0, 0, 0, 0, 1500);
        dmm_set_alloc_rule(0, 0);
        osal_cleanup();
        sys_exit(4);
    }

    /* 5. Register DMA Buffer */
    struct usbg_video_buf_info reg_buf;
    reg_buf.size = dma_meta.total_size;
    reg_buf.phys_addr = dma_meta.phys_addr;
    ret = sys_ioctl(uvc_fd, IOCTL_UVC_REG_BUF, &reg_buf);
    print_str("[feeder] IOCTL_UVC_REG_BUF status=");
    print_int(ret);
    print_str("\n");

    /* 6. Enable Bulk endpoint */
    ret = sys_ioctl(uvc_fd, IOCTL_UVC_ENABLE, (void *)0);
    print_str("[feeder] IOCTL_UVC_ENABLE status=");
    print_int(ret);
    print_str("\n");

    /* 7. Map DMA buffer via /dev/mem to initialize with 720p pattern */
    int mem_fd = sys_open("/dev/mem", O_RDWR, 0);
    void *dma_mapped = 0;
    if (mem_fd >= 0) {
        unsigned int page_base = dma_meta.phys_addr & ~0xfff;
        unsigned int page_offset = dma_meta.phys_addr & 0xfff;
        unsigned int map_len = (page_offset + dma_meta.total_size + 0xfff) & ~0xfff;
        void *m = sys_mmap2(0, map_len, PROT_READ | PROT_WRITE, MAP_SHARED, mem_fd, page_base >> 12);
        if ((int)m >= 0 || (int)m <= -4096) {
            dma_mapped = (char *)m + page_offset;
            /* Copy test pattern to slot 0 */
            if (sizeof(s_test_jpeg_720p) <= dma_meta.max_frame_payload) {
                memcpy(dma_mapped, s_test_jpeg_720p, sizeof(s_test_jpeg_720p));
                /* Also copy to slot 1 */
                if (dma_meta.total_size >= dma_meta.slot_size * 2) {
                    memcpy((char *)dma_mapped + dma_meta.slot_size, s_test_jpeg_720p, sizeof(s_test_jpeg_720p));
                }
            }
        }
    }

    print_str("[feeder] Streaming loop starting (30 FPS, CLOCK_MONOTONIC)...\n");

    struct timespec next_frame;
    sys_clock_gettime(CLOCK_MONOTONIC, &next_frame);

    int total_frames = 0;
    int sensor_frames = 0;
    int active_slot = 0;
    int fps_count = 0;
    unsigned int current_frame_size = sizeof(s_test_jpeg_720p);

    struct usbg_video_data_info data_info;

    /* Feed for up to 900 frames (30 seconds) or until stop signal */
    for (int tick = 0; tick < 900; tick++) {
        /* Check stop signal */
        int stop_fd = sys_open("/tmp_bt/stop_feeder", O_RDONLY, 0);
        if (stop_fd >= 0) {
            sys_close(stop_fd);
            print_str("[feeder] Stop signal detected via /tmp_bt/stop_feeder\n");
            break;
        }

        /* Try to acquire native frame from sensor */
        unsigned int handle1 = 0, f_size = 0, handle2 = 0;
        int got_frame = send_get_jpeg(&handle1, &f_size, &handle2);
        if (got_frame == 0 && f_size > 0 && handle1 != 0 && handle1 != 0xffff) {
            /* Open DMM unit to read sensor frame */
            unsigned int frame_phys = 0, dmm_sz = 0;
            if (dmm_open_unit(handle1, &frame_phys, &dmm_sz) == 0 && frame_phys != 0) {
                if (f_size <= dma_meta.max_frame_payload && dma_mapped && mem_fd >= 0) {
                    /* Map frame and copy into coherent ping-pong slot */
                    unsigned int fp_base = frame_phys & ~0xfff;
                    unsigned int fp_off = frame_phys & 0xfff;
                    unsigned int fp_len = (fp_off + f_size + 0xfff) & ~0xfff;
                    void *f_map = sys_mmap2(0, fp_len, PROT_READ, MAP_SHARED, mem_fd, fp_base >> 12);
                    if ((int)f_map >= 0 || (int)f_map <= -4096) {
                        char *slot_ptr = (char *)dma_mapped + (active_slot * dma_meta.slot_size);
                        memcpy(slot_ptr, (char *)f_map + fp_off, f_size);
                        current_frame_size = f_size;
                        sensor_frames++;
                    }
                }
                dmm_close_unit(handle1);
                dmm_free_unit(handle1);
            }
            if (handle2 != 0 && handle2 != 0xffff) dmm_free_unit(handle2);
        }

        /* Submit frame */
        data_info.frame_size = current_frame_size;
        data_info.phys_addr = dma_meta.phys_addr + (active_slot * dma_meta.slot_size);

        ret = sys_ioctl(uvc_fd, IOCTL_UVC_WAIT, (void *)0);
        if (ret == 0) {
            ret = sys_ioctl(uvc_fd, IOCTL_UVC_UPDATE, &data_info);
        }

        if (ret == 0) {
            total_frames++;
            active_slot = 1 - active_slot; /* toggle ping-pong slot */
            fps_count++;
            if (fps_count >= 30) {
                fps_count = 0;
                print_str("[feeder] 30 FPS tick=");
                print_int(total_frames);
                print_str(" (sensor_frames=");
                print_int(sensor_frames);
                print_str(")\n");
            }
        } else if (ret < 0 && ret != -16) {
            print_str("[feeder] UVC transfer error: ");
            print_int(ret);
            print_str("\n");
            break;
        }

        /* 30 FPS deadline */
        next_frame.tv_nsec += 33333333L;
        if (next_frame.tv_nsec >= 1000000000L) {
            next_frame.tv_nsec -= 1000000000L;
            next_frame.tv_sec++;
        }
        sys_clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next_frame, 0);
    }

    print_str("[feeder] Streaming loop completed: total_frames=");
    print_int(total_frames);
    print_str(" sensor_frames=");
    print_int(sensor_frames);
    print_str("\n");

    /* 8. Teardown */
    print_str("[feeder] Teardown: unregistering UVC...\n");
    sys_ioctl(uvc_fd, IOCTL_UVC_UNREG, (void *)0);
    sys_ioctl(uvc_fd, IOCTL_UVC_STOP, (void *)0);
    sys_close(uvc_fd);

    if (mem_fd >= 0) sys_close(mem_fd);

    print_str("[feeder] Teardown: resetting SET_PATH...\n");
    send_set_path(0, 0, 0, 0, 0, 1500);

    print_str("[feeder] Teardown: restoring Rule 0...\n");
    dmm_set_alloc_rule(0, 0);

    osal_cleanup();
    print_str("=== A6400 FEEDER SESSION CLEANLY TERMINATED ===\n");
    sys_exit(0);
}
