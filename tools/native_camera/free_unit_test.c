/* free_unit_test.c */
#define SYS_exit 1
#define SYS_write 4
#define SYS_open 5
#define SYS_close 6
#define SYS_ioctl 54
#define SYS_mmap2 192

#define O_RDWR 2
#define PROT_READ 1
#define PROT_WRITE 2
#define MAP_SHARED 1
#define QUEUE_DMM 0x0061003c

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

void *memset(void *s, int c, unsigned int n) {
    char *p = (char *)s;
    while (n--) *p++ = (char)c;
    return s;
}

void _start(void) {
    int fd = sys_open("/dev/uipc", O_RDWR, 0);
    unsigned int out_meta[8] = {0};
    struct { unsigned int p; void *o; } init_req = {0, out_meta};
    sys_ioctl(fd, 0x80000010, &init_req);
    sys_mmap2(0, out_meta[0], PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);

    unsigned int qid = 0;
    struct { unsigned int op; unsigned int p; unsigned int *id; } dyn_sub = {0x2a, 729, &qid};
    struct { unsigned int z; void *s; } dyn_req = {0, &dyn_sub};
    sys_ioctl(fd, 0x8000000c, &dyn_req);

    void *msg = 0;
    struct { void **p; unsigned int sz; unsigned int w; } val_sub = {&msg, 32, 1};
    struct { unsigned int q; void *s; } val_req = {QUEUE_DMM, &val_sub};
    sys_ioctl(fd, 0x8000000a, &val_req);

    char *p = (char *)msg;
    for (int i = 0; i < 32; i++) p[i] = 0;
    *(unsigned short *)(p + 0) = 4; /* free */
    *(unsigned short *)(p + 2) = 0x08cb; /* handle */
    *(unsigned int *)(p - 4) = qid;

    struct { unsigned int q; void *m; } snd_req = {QUEUE_DMM, msg};
    sys_ioctl(fd, 0x80000004, &snd_req);

    void *reply = 0;
    struct { void **p; unsigned int tmo; } rcv_sub = {&reply, 800};
    struct { unsigned int q; void *s; } rcv_req = {qid, &rcv_sub};
    sys_ioctl(fd, 0x80000007, &rcv_req);

    short st = *(short *)((char *)reply + 2);
    sys_write(1, st == 0 ? "FREE_OK\n" : "FREE_ERR\n", 8);

    struct { unsigned int op; unsigned int p; unsigned int *id; } del_sub = {0x4a, 0, (unsigned int *)qid};
    struct { unsigned int z; void *s; } del_req = {0, &del_sub};
    sys_ioctl(fd, 0x8000000c, &del_req);
    sys_close(fd);
    sys_exit(0);
}
