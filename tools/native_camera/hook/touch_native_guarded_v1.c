/* Experimental native touch gates. Exact original-function guards, no scanner,
 * evdev reader, synthesized navigation, event injection, threads or subprocesses.
 * NOT DEPLOYED: requires explicit runtime-patch approval. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <stdint.h>
#include <elf.h>
#include <sys/ptrace.h>
#include <sys/wait.h>

static const unsigned char input_original[] = {
    0x98,0xb5,0x00,0xaf,0x04,0x46,0x34,0xf5,0xd4,0xec,0x30,0xb1,0x21,0x46,
    0x33,0xf5,0x9c,0xec,0x33,0xf5,0x60,0xee,0x01,0x20,0x98,0xbd,0x98,0xbd};
static const unsigned char menu_original[] = {
    0x80,0xb5,0x00,0xaf,0x03,0x68,0x19,0xb1,0xd3,0xf8,0x08,0x31,0x00,0x21,
    0x02,0xe0,0xd3,0xf8,0x08,0x31,0x02,0x21,0x98,0x47,0x80,0xbd};

static uintptr_t module_base(const char *name) {
    FILE *maps = fopen("/proc/149/maps", "r");
    char line[512];
    uintptr_t found = 0;
    unsigned matches = 0;
    if (!maps) return 0;
    while (fgets(line, sizeof(line), maps)) {
        if (strstr(line, name) && strstr(line, "r-xp 00000000 ")) {
            found = strtoul(line, NULL, 16);
            matches++;
        }
    }
    fclose(maps);
    return matches == 1 ? found : 0;
}

/* Resolve exact exported names from the camera's own on-disk ELF. A changed
 * export offset does not relax either original function-byte guard. */
static uintptr_t exported_offset(const char *path, const char *name, FILE *out) {
    Elf32_Ehdr eh;
    Elf32_Shdr sections[256];
    uintptr_t result = 0;
    unsigned matches = 0;
    int fd = open(path, O_RDONLY);
    if (fd < 0) return 0;
    if (pread(fd, &eh, sizeof(eh), 0) != sizeof(eh) || memcmp(eh.e_ident, ELFMAG, SELFMAG)
        || eh.e_ident[EI_CLASS] != ELFCLASS32 || eh.e_ident[EI_DATA] != ELFDATA2LSB
        || eh.e_machine != EM_ARM || eh.e_type != ET_DYN
        || eh.e_shentsize != sizeof(Elf32_Shdr) || !eh.e_shnum || eh.e_shnum > 256
        || eh.e_shoff > 0x4000000) goto finish;
    unsigned bytes = eh.e_shnum * sizeof(Elf32_Shdr);
    if (pread(fd, sections, bytes, eh.e_shoff) != (ssize_t)bytes) goto finish;
    for (unsigned s=0; s<eh.e_shnum; s++) {
        Elf32_Shdr *symbols = &sections[s];
        if (symbols->sh_type != SHT_DYNSYM || symbols->sh_link >= eh.e_shnum
            || symbols->sh_entsize != sizeof(Elf32_Sym) || symbols->sh_size > 0x800000) continue;
        Elf32_Shdr *strings = &sections[symbols->sh_link];
        if (strings->sh_size > 0x800000 || strings->sh_offset > 0x4000000
            || symbols->sh_offset > 0x4000000) continue;
        char *names = malloc(strings->sh_size);
        Elf32_Sym *table = malloc(symbols->sh_size);
        if (!names || !table) { free(names); free(table); goto finish; }
        if (pread(fd, names, strings->sh_size, strings->sh_offset) == (ssize_t)strings->sh_size
            && pread(fd, table, symbols->sh_size, symbols->sh_offset) == (ssize_t)symbols->sh_size) {
            for (unsigned i=0; i<symbols->sh_size/sizeof(Elf32_Sym); i++) {
                Elf32_Sym *sym = &table[i];
                if (sym->st_shndx != SHN_UNDEF && ELF32_ST_TYPE(sym->st_info) == STT_FUNC
                    && sym->st_name < strings->sh_size
                    && memchr(names+sym->st_name, 0, strings->sh_size-sym->st_name)
                    && !strcmp(names+sym->st_name, name)) {
                    result = sym->st_value & ~1u; matches++;
                }
            }
        }
        free(names); free(table);
    }
finish:
    close(fd);
    fprintf(out, "export=%s offset=%08lx matches=%u\n", name, (unsigned long)result, matches);
    return matches == 1 ? result : 0;
}

static int peek_bytes(uintptr_t address, unsigned char *bytes, unsigned count) {
    for (unsigned i = 0; i < count;) {
        uintptr_t aligned = (address + i) & ~(uintptr_t)3;
        errno = 0;
        long word = ptrace(PTRACE_PEEKTEXT, 149, (void *)aligned, NULL);
        if (word == -1 && errno) return -1;
        unsigned offset = (address + i) & 3;
        unsigned n = 4 - offset;
        if (n > count - i) n = count - i;
        memcpy(bytes + i, (unsigned char *)&word + offset, n);
        i += n;
    }
    return 0;
}

static int store_halfword(uintptr_t address, unsigned short expected, unsigned short value) {
    uintptr_t aligned = address & ~(uintptr_t)3;
    unsigned shift = (address & 3) * 8;
    if ((address & 1) || (address & 3) == 3) return -1;
    errno = 0;
    long old = ptrace(PTRACE_PEEKTEXT, 149, (void *)aligned, NULL);
    if ((old == -1 && errno) || (((uint32_t)old >> shift) & 0xffff) != expected) return -1;
    uint32_t changed = ((uint32_t)old & ~((uint32_t)0xffff << shift)) | ((uint32_t)value << shift);
    if (ptrace(PTRACE_POKETEXT, 149, (void *)aligned, (void *)(uintptr_t)changed)) return -1;
    unsigned char actual[2];
    return peek_bytes(address, actual, 2) || memcmp(actual, &value, 2) ? -1 : 0;
}

__attribute__((constructor)) static void native_touch_attempt(void) {
    int entry_errno = errno;
    if (access("/setting/disable_touch_patch", F_OK) == 0) return;
    int fd = open("/setting/touch_native_guarded_v3.log", O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (fd < 0) { errno = entry_errno; return; }
    FILE *out = fdopen(fd, "w");
    if (!out) { close(fd); errno = entry_errno; return; }
    int attached = 0, status;
    unsigned char input[sizeof(input_original)], menu[sizeof(menu_original)];
    unsigned char input_expected[sizeof(input_original)], menu_expected[sizeof(menu_original)];
    char comm[32] = {0};
    fprintf(out, "TOUCH_NATIVE_GUARDED_V3 collector=%d uid=%d\n", getpid(), getuid());
    int cfd = open("/proc/149/comm", O_RDONLY);
    if (cfd < 0) { fprintf(out, "FAIL: process comm unavailable\n"); goto done; }
    int n = read(cfd, comm, sizeof(comm)-1);
    close(cfd);
    if (n < 0 || strcmp(comm, "im.elf\n")) { fprintf(out, "FAIL: PID 149 is not im.elf\n"); goto done; }
    uintptr_t obj = module_base("/libObj.so");
    uintptr_t view = module_base("/viewUnified2.so");
    fprintf(out, "libObj=%08lx viewUnified2=%08lx\n", (unsigned long)obj, (unsigned long)view);
    if (!obj || !view) { fprintf(out, "FAIL: missing or ambiguous maps\n"); goto done; }
    uintptr_t input_offset = exported_offset("/usr/lib/libObj.so", "_ZN12InputService12setTpEventSwEb", out);
    uintptr_t menu_offset = exported_offset("/usr/lib/viewUnified2.so", "_ZN18PAS_MenuSelectMode12setTouchableEb", out);
    if (!input_offset || !menu_offset) { fprintf(out, "FAIL: exact symbol resolution\n"); goto done; }
    uintptr_t input_fn = obj + input_offset, menu_fn = view + menu_offset;
    if (ptrace(PTRACE_ATTACH, 149, NULL, NULL)) { fprintf(out, "FAIL: attach errno=%d\n", errno); goto done; }
    attached = 1;
    if (waitpid(149, &status, 0) != 149 || !WIFSTOPPED(status)) {
        fprintf(out, "FAIL: no confirmed stop\n"); goto done;
    }
    if (peek_bytes(input_fn, input, sizeof(input)) || peek_bytes(menu_fn, menu, sizeof(menu))) {
        fprintf(out, "FAIL: function read errno=%d\n", errno); goto done;
    }
    fprintf(out, "input_bytes=");
    for (unsigned i=0; i<sizeof(input); i++) fprintf(out, "%02x", input[i]);
    fprintf(out, "\nmenu_bytes=");
    for (unsigned i=0; i<sizeof(menu); i++) fprintf(out, "%02x", menu[i]);
    fprintf(out, "\n");
    if (memcmp(input, input_original, sizeof(input)) || memcmp(menu, menu_original, sizeof(menu))) {
        fprintf(out, "FAIL: original-function identity mismatch; NO WRITES\n"); goto done;
    }
    /* Mark rollback required before attempting either write: a verification
     * failure can occur after the kernel has already stored the new word. */
    memcpy(input_expected, input_original, sizeof(input_expected));
    memcpy(menu_expected, menu_original, sizeof(menu_expected));
    input_expected[4] = 0x01; input_expected[5] = 0x24;
    menu_expected[6] = 0x00; menu_expected[7] = 0xbf;
    if (store_halfword(input_fn+4, 0x4604, 0x2401) || store_halfword(menu_fn+6, 0xb119, 0xbf00)
        || peek_bytes(input_fn, input, sizeof(input)) || peek_bytes(menu_fn, menu, sizeof(menu))
        || memcmp(input, input_expected, sizeof(input)) || memcmp(menu, menu_expected, sizeof(menu))) {
        unsigned char actual[2];
        int failures = 0;
        if (peek_bytes(menu_fn+6, actual, 2)) failures++;
        else if (!memcmp(actual, "\x00\xbf", 2)) failures += store_halfword(menu_fn+6, 0xbf00, 0xb119) != 0;
        else if (memcmp(actual, "\x19\xb1", 2)) failures++;
        if (peek_bytes(input_fn+4, actual, 2)) failures++;
        else if (!memcmp(actual, "\x01\x24", 2)) failures += store_halfword(input_fn+4, 0x2401, 0x4604) != 0;
        else if (memcmp(actual, "\x04\x46", 2)) failures++;
        fprintf(out, "FAIL: write/verification; rollback_failures=%d\n", failures);
        goto done;
    }
    fprintf(out, "BYTES_VERIFIED: two native touch gates patched; UI behavior NOT VERIFIED\n");
done:
    if (attached && ptrace(PTRACE_DETACH, 149, NULL, NULL)) fprintf(out, "FAIL: detach errno=%d\n", errno);
    fprintf(out, "END TOUCH_NATIVE_GUARDED_V3\n");
    fclose(out);
    errno = entry_errno;
}
