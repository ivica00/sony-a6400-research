/*
 * test_ptrace_call.c
 * Safely tests ptrace function execution inside im.elf (PID 149)
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

void _start(void) {
    print_str("=== TEST PTRACE CALL IN IM.ELF (PID 149) ===\n");
    int pid = 149;
    int status = 0;

    int ret = sys_ptrace(PTRACE_ATTACH, pid, 0, 0);
    print_str("PTRACE_ATTACH ret="); print_int(ret); print_str("\n");
    if (ret != 0) sys_exit(1);

    sys_wait4(pid, &status, 0, 0);
    print_str("ATTACH status="); print_hex(status); print_str("\n");

    struct user_regs_arm orig_regs, call_regs;
    ret = sys_ptrace(PTRACE_GETREGS, pid, 0, &orig_regs);
    print_str("PTRACE_GETREGS ret="); print_int(ret); print_str("\n");
    if (ret != 0) { sys_ptrace(PTRACE_DETACH, pid, 0, 0); sys_exit(2); }

    print_str("Current PC="); print_hex(orig_regs.uregs[15]);
    print_str(" SP="); print_hex(orig_regs.uregs[13]);
    print_str(" CPSR="); print_hex(orig_regs.uregs[16]);
    print_str("\n");

    // Copy original registers
    call_regs = orig_regs;

    // We will place a trap word (0xe7f001f0 = undefined instruction) on the stack
    // Align stack down by 16 bytes
    unsigned long trap_addr = (call_regs.uregs[13] - 16) & ~7;
    // Save original stack word
    long orig_stack_word = sys_ptrace(PTRACE_PEEKDATA, pid, (void *)trap_addr, 0);
    // Write undefined instruction (ARM trap: 0xe7f001f0)
    sys_ptrace(PTRACE_POKEDATA, pid, (void *)trap_addr, (void *)0xe7f001f0);

    // Target function: InhInfo::RefInhMgrList() at 0x041150c0 (Thumb: 0x041150c1)
    unsigned long func_addr = 0x041150c0;

    // Set registers for function call:
    // LR = trap_addr (in ARM mode)
    call_regs.uregs[14] = trap_addr;
    // PC = func_addr
    call_regs.uregs[15] = func_addr;
    // Thumb mode: CPSR bit 5 (0x20)
    call_regs.uregs[16] |= 0x20;
    // SP = trap_addr
    call_regs.uregs[13] = trap_addr;

    ret = sys_ptrace(PTRACE_SETREGS, pid, 0, &call_regs);
    print_str("PTRACE_SETREGS ret="); print_int(ret); print_str("\n");

    // Continue process
    ret = sys_ptrace(PTRACE_CONT, pid, 0, 0);
    print_str("PTRACE_CONT ret="); print_int(ret); print_str("\n");

    // Wait for trap
    sys_wait4(pid, &status, 0, 0);
    print_str("TRAP status="); print_hex(status); print_str("\n");

    // Read result registers
    struct user_regs_arm res_regs;
    sys_ptrace(PTRACE_GETREGS, pid, 0, &res_regs);
    print_str("Return R0="); print_hex(res_regs.uregs[0]);
    print_str(" PC="); print_hex(res_regs.uregs[15]);
    print_str("\n");

    // Restore original stack word
    sys_ptrace(PTRACE_POKEDATA, pid, (void *)trap_addr, (void *)orig_stack_word);

    // Restore original registers
    sys_ptrace(PTRACE_SETREGS, pid, 0, &orig_regs);

    // Detach cleanly
    sys_ptrace(PTRACE_DETACH, pid, 0, 0);
    print_str("PTRACE_DETACH clean\n");

    print_str("=== TEST FINISHED ===\n");
    sys_exit(0);
}
