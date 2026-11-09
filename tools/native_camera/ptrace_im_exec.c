/*
 * ptrace_im_exec.c
 * Standalone ARM tool to execute arbitrary functions inside im.elf (PID 149)
 * Usage: ptrace_im_exec <func_addr_hex> <is_thumb 0|1> [r0_hex] [r1_hex] [r2_hex] [r3_hex]
 */

#define SYS_exit      1
#define SYS_write     4
#define SYS_ptrace    26
#define SYS_wait4     114

#define PTRACE_ATTACH    16
#define PTRACE_DETACH    17
#define PTRACE_GETREGS   12
#define PTRACE_SETREGS   13
#define PTRACE_CONT      7
#define PTRACE_PEEKDATA  1
#define PTRACE_POKEDATA  4

struct user_regs_arm {
    unsigned long uregs[18];
};

void main_c(unsigned long *sp);
__asm__(
".global _start\n"
"_start:\n"
"    mov r0, sp\n"
"    b main_c\n"
);

static inline int sys_write(int fd, const void *buf, int count) {
    register int r0 __asm__("r0") = fd;
    register int r1 __asm__("r1") = (int)buf;
    register int r2 __asm__("r2") = count;
    register int r7 __asm__("r7") = SYS_write;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r7) : "memory");
    return r0;
}
static inline int sys_ptrace(int req, int pid, void *addr, void *data) {
    register int r0 __asm__("r0") = req;
    register int r1 __asm__("r1") = pid;
    register int r2 __asm__("r2") = (int)addr;
    register int r3 __asm__("r3") = (int)data;
    register int r7 __asm__("r7") = SYS_ptrace;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r3), "r"(r7) : "memory");
    return r0;
}
static inline int sys_wait4(int pid, int *status, int options, void *rusage) {
    register int r0 __asm__("r0") = pid;
    register int r1 __asm__("r1") = (int)status;
    register int r2 __asm__("r2") = options;
    register int r3 __asm__("r3") = (int)rusage;
    register int r7 __asm__("r7") = SYS_wait4;
    __asm__ __volatile__("svc 0" : "=r"(r0) : "r"(r0), "r"(r1), "r"(r2), "r"(r3), "r"(r7) : "memory");
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
static void print_int(int v) {
    char buf[16]; int i = 0;
    if (v < 0) { sys_write(1, "-", 1); v = -v; }
    if (v == 0) { sys_write(1, "0", 1); return; }
    while (v > 0) { buf[i++] = '0' + (v % 10); v /= 10; }
    for (int j = 0; j < i/2; j++) { char t = buf[j]; buf[j] = buf[i-1-j]; buf[i-1-j] = t; }
    sys_write(1, buf, i);
}

void *memcpy(void *dest, const void *src, unsigned int n) {
    char *d = (char *)dest;
    const char *s = (const char *)src;
    while (n--) *d++ = *s++;
    return dest;
}

static unsigned long parse_hex(const char *s) {
    unsigned long val = 0;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) s += 2;
    while (*s) {
        char c = *s++;
        val <<= 4;
        if (c >= '0' && c <= '9') val |= (c - '0');
        else if (c >= 'a' && c <= 'f') val |= (c - 'a' + 10);
        else if (c >= 'A' && c <= 'F') val |= (c - 'A' + 10);
        else break;
    }
    return val;
}

static unsigned long parse_dec(const char *s) {
    unsigned long val = 0;
    while (*s >= '0' && *s <= '9') {
        val = val * 10 + (*s++ - '0');
    }
    return val;
}

void main_c(unsigned long *sp) {
    int argc = (int)sp[0];
    char **argv = (char **)&sp[1];

    if (argc < 3) {
        print_str("Usage: ptrace_im_exec <func_hex> <is_thumb 0|1> [r0] [r1] [r2] [r3]\n");
        sys_exit(1);
    }

    unsigned long func_addr = parse_hex(argv[1]);
    int is_thumb = (int)parse_dec(argv[2]);
    unsigned long a0 = (argc > 3) ? parse_hex(argv[3]) : 0;
    unsigned long a1 = (argc > 4) ? parse_hex(argv[4]) : 0;
    unsigned long a2 = (argc > 5) ? parse_hex(argv[5]) : 0;
    unsigned long a3 = (argc > 6) ? parse_hex(argv[6]) : 0;

    print_str("PTRACE EXEC: func="); print_hex(func_addr);
    print_str(" thumb="); print_int(is_thumb);
    print_str(" r0="); print_hex(a0);
    print_str(" r1="); print_hex(a1);
    print_str(" r2="); print_hex(a2);
    print_str(" r3="); print_hex(a3);
    print_str("\n");

    int pid = 149;
    int status = 0;

    int ret = sys_ptrace(PTRACE_ATTACH, pid, 0, 0);
    if (ret != 0) {
        print_str("ERR: PTRACE_ATTACH ret="); print_int(ret); print_str("\n");
        sys_exit(2);
    }

    sys_wait4(pid, &status, 0, 0);

    struct user_regs_arm orig_regs, call_regs;
    ret = sys_ptrace(PTRACE_GETREGS, pid, 0, &orig_regs);
    if (ret != 0) {
        print_str("ERR: PTRACE_GETREGS\n");
        sys_ptrace(PTRACE_DETACH, pid, 0, 0);
        sys_exit(3);
    }

    call_regs = orig_regs;
    unsigned long trap_addr = (call_regs.uregs[13] - 16) & ~7;
    long orig_stack_word = sys_ptrace(PTRACE_PEEKDATA, pid, (void *)trap_addr, 0);
    sys_ptrace(PTRACE_POKEDATA, pid, (void *)trap_addr, (void *)0xe7f001f0);

    call_regs.uregs[0] = a0;
    call_regs.uregs[1] = a1;
    call_regs.uregs[2] = a2;
    call_regs.uregs[3] = a3;
    call_regs.uregs[14] = trap_addr; // LR -> trap
    call_regs.uregs[15] = func_addr; // PC
    if (is_thumb) {
        call_regs.uregs[16] |= 0x20; // CPSR T bit
    } else {
        call_regs.uregs[16] &= ~0x20;
    }
    call_regs.uregs[13] = trap_addr; // SP

    ret = sys_ptrace(PTRACE_SETREGS, pid, 0, &call_regs);
    if (ret != 0) {
        print_str("ERR: PTRACE_SETREGS\n");
        sys_ptrace(PTRACE_POKEDATA, pid, (void *)trap_addr, (void *)orig_stack_word);
        sys_ptrace(PTRACE_DETACH, pid, 0, 0);
        sys_exit(4);
    }

    ret = sys_ptrace(PTRACE_CONT, pid, 0, 0);
    if (ret != 0) {
        print_str("ERR: PTRACE_CONT\n");
        sys_ptrace(PTRACE_POKEDATA, pid, (void *)trap_addr, (void *)orig_stack_word);
        sys_ptrace(PTRACE_DETACH, pid, 0, 0);
        sys_exit(5);
    }

    // Wait for the function to complete (hit trap)
    sys_wait4(pid, &status, 0, 0);

    struct user_regs_arm res_regs;
    sys_ptrace(PTRACE_GETREGS, pid, 0, &res_regs);

    // Restore stack and registers
    sys_ptrace(PTRACE_POKEDATA, pid, (void *)trap_addr, (void *)orig_stack_word);
    sys_ptrace(PTRACE_SETREGS, pid, 0, &orig_regs);
    sys_ptrace(PTRACE_DETACH, pid, 0, 0);

    print_str("EXEC SUCCESS: RET_R0="); print_hex(res_regs.uregs[0]);
    print_str(" STATUS="); print_hex(status);
    print_str(" FINAL_PC="); print_hex(res_regs.uregs[15]);
    print_str("\n");

    sys_exit(0);
}
