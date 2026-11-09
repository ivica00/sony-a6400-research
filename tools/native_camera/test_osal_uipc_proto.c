/* Test full freestanding OSAL UIPC protocol on a6400 */

#define SYS_exit   1
#define SYS_read   3
#define SYS_write  4
#define SYS_open   5
#define SYS_close  6
#define SYS_ioctl  54
#define SYS_mmap2  192

#define O_RDWR     2
#define PROT_READ  1
#define PROT_WRITE 2
#define MAP_SHARED 1

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

void _start(void) {
    print_str("OSAL_PROTO_START\n");
    int fd = sys_open("/dev/uipc", O_RDWR, 0);
    print_str("OPEN_FD=");
    print_int(fd);
    print_str("\n");
    if (fd < 0) {
        sys_exit(1);
    }

    /* 1. Init UIPC */
    unsigned int out_meta[8];
    for (int i = 0; i < 8; i++) out_meta[i] = 0;

    struct {
        unsigned int param;
        void *out_ptr;
    } req_init;
    req_init.param = 0;
    req_init.out_ptr = out_meta;

    int ret = sys_ioctl(fd, 0x80000010, &req_init);
    print_str("INIT_RET=");
    print_int(ret);
    print_str(" POOL_SIZE=");
    print_int(out_meta[0]);
    print_str("\n");
    if (ret != 0) {
        sys_close(fd);
        sys_exit(2);
    }

    /* 2. Mmap pool */
    void *pool = sys_mmap2(0, out_meta[0], PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    print_str("MMAP_POOL=");
    print_hex((unsigned int)pool);
    print_str("\n");
    if ((int)pool < 0 && (int)pool > -4096) {
        print_str("FAIL: mmap failed\n");
        sys_close(fd);
        sys_exit(3);
    }

    /* 3. Allocate dynamic reply queue: op 0x2a, param 729 */
    unsigned int reply_qid = 0;
    struct {
        unsigned int op;
        unsigned int param;
        unsigned int *id_out;
    } dyn_sub;
    dyn_sub.op = 0x2a;
    dyn_sub.param = 729;
    dyn_sub.id_out = &reply_qid;

    struct {
        unsigned int zero;
        void *sub_ptr;
    } dyn_req;
    dyn_req.zero = 0;
    dyn_req.sub_ptr = &dyn_sub;

    ret = sys_ioctl(fd, 0x8000000c, &dyn_req);
    print_str("DYN_ALLOC_RET=");
    print_int(ret);
    print_str(" REPLY_QID=");
    print_hex(reply_qid);
    print_str("\n");

    /* 4. Test valloc message for queue 0x01670464 */
    void *msg_ptr = 0;
    struct {
        void **msg_pptr;
        unsigned int size;
        unsigned int wait_flag;
    } val_sub;
    val_sub.msg_pptr = &msg_ptr;
    val_sub.size = 68; /* 68 bytes for SET_PATH */
    val_sub.wait_flag = 1;

    struct {
        unsigned int qid;
        void *sub_ptr;
    } val_req;
    val_req.qid = 0x01670464;
    val_req.sub_ptr = &val_sub;

    ret = sys_ioctl(fd, 0x8000000a, &val_req);
    print_str("VALLOC_RET=");
    print_int(ret);
    print_str(" MSG_PTR=");
    print_hex((unsigned int)msg_ptr);
    print_str("\n");

    /* 5. Free allocated message if successful */
    if (ret == 0 && msg_ptr != 0) {
        struct {
            unsigned int qid;
            void *msg_ptr;
        } free_req;
        free_req.qid = 0x01670464;
        free_req.msg_ptr = msg_ptr;
        ret = sys_ioctl(fd, 0x8000000b, &free_req);
        print_str("FREE_MSG_RET=");
        print_int(ret);
        print_str("\n");
    }

    /* 6. Free dynamic reply queue: op 0x4a */
    if (reply_qid != 0) {
        dyn_sub.op = 0x4a;
        dyn_sub.param = 0;
        dyn_sub.id_out = (unsigned int *)reply_qid;
        ret = sys_ioctl(fd, 0x8000000c, &dyn_req);
        print_str("DYN_FREE_RET=");
        print_int(ret);
        print_str("\n");
    }

    sys_close(fd);
    print_str("OSAL_PROTO_SUCCESS\n");
    sys_exit(0);
}
