/* Minimal read-only probe for the GPES/Sugilite BAR (E0341 physical evidence).
 *
 * Opens /dev/mem O_RDONLY and mmaps the GPES BAR physical window 0xF1000000
 * (16 KiB) with PROT_READ only, then prints a small set of status/ack
 * registers. It never writes the BAR, never opens /dev/dmpgles2, never
 * touches /dev/stream and never switches camera mode. Linked against the
 * preserved Sony libc like the existing native helpers.
 */
#include <fcntl.h>
#include <stdint.h>
#include <sys/mman.h>
#include <unistd.h>

static void emit(const char *text, unsigned length)
{
    (void)write(1, text, length);
}

static void emit_word(const char *name, uint32_t value)
{
    static const char digits[] = "0123456789abcdef";
    char out[16];
    unsigned i = 0;
    while (name[i] && i < 4) {
        out[i] = name[i];
        i++;
    }
    out[i++] = '=';
    for (int shift = 28; shift >= 0; shift -= 4) {
        out[i++] = digits[(value >> shift) & 0xf];
    }
    out[i++] = '\n';
    emit(out, i);
}

int main(void)
{
    int fd = open("/dev/mem", O_RDONLY);
    if (fd < 0) {
        emit("OERR\n", 5);
        return 2;
    }
    volatile unsigned char *base = (volatile unsigned char *)mmap(
        0, 0x4000, PROT_READ, MAP_SHARED, fd, 0xF1000000UL);
    if (base == MAP_FAILED) {
        emit("MERR\n", 5);
        (void)close(fd);
        return 3;
    }
    static const uint32_t offsets[] = {
        0x00, 0x04, 0x08, 0x1c, 0x34, 0x38, 0x3c, 0x44,
        0xc0, 0xc18, 0x1000, 0x1004
    };
    for (unsigned index = 0; index < sizeof(offsets) / sizeof(offsets[0]); index++) {
        uint32_t offset = offsets[index];
        char name[5];
        name[0] = "0123456789abcdef"[(offset >> 12) & 0xf];
        name[1] = "0123456789abcdef"[(offset >> 8) & 0xf];
        name[2] = "0123456789abcdef"[(offset >> 4) & 0xf];
        name[3] = "0123456789abcdef"[offset & 0xf];
        emit_word(name, *(volatile uint32_t *)(base + offset));
    }
    emit("OK\n", 3);
    (void)munmap((void *)base, 0x4000);
    (void)close(fd);
    return 0;
}
