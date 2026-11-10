/* Read-only GPES BAR register survey (E0313 physical evidence).
 *
 * mmaps the 128 KiB dmpgles2/GPES window at 0xF1000000 read-only and samples
 * the command/semaphore register block used by libObj's RM executor (BAR
 * offsets observed in the e0372 emulator MMIO trace), printing up to three
 * distinct values with counts per offset. Never writes the BAR.
 */
#include <fcntl.h>
#include <stdint.h>
#include <sys/mman.h>
#include <unistd.h>

static void emit(const char *text, unsigned length)
{
    (void)write(1, text, length);
}

static void emit_u32(uint32_t value)
{
    static const char digits[] = "0123456789abcdef";
    char out[9];
    for (int index = 0; index < 8; index++) {
        out[index] = digits[(value >> (28 - index * 4)) & 0xf];
    }
    out[8] = ' ';
    emit(out, 9);
}

static const uint32_t offsets[] = {
    0x00, 0x04, 0x08, 0x0c, 0x10, 0x14, 0x30, 0x34, 0x38, 0x3c, 0x44,
    0xe8, 0xec, 0xf0, 0xf4, 0xf8, 0xfc, 0x100, 0x104, 0x108, 0x10c,
    0x110, 0x114, 0x118, 0x11c, 0x120, 0x124, 0x128, 0x12c, 0x130,
    0x134, 0x138, 0x13c, 0x140, 0x144, 0x148, 0x14c, 0x150, 0x154,
    0x158, 0x15c, 0x160, 0x164, 0x168, 0x16c, 0x170
};

int main(void)
{
    int fd = open("/dev/mem", O_RDONLY);
    if (fd < 0) {
        emit("OERR\n", 5);
        return 2;
    }
    volatile unsigned char *base = (volatile unsigned char *)mmap(
        0, 0x20000, PROT_READ, MAP_SHARED, fd, 0xF1000000UL);
    if (base == MAP_FAILED) {
        emit("MERR\n", 5);
        (void)close(fd);
        return 3;
    }
    const uint32_t samples = 20000;
    for (unsigned index = 0; index < sizeof(offsets) / sizeof(offsets[0]); index++) {
        uint32_t offset = offsets[index];
        volatile uint32_t *reg = (volatile uint32_t *)(base + offset);
        uint32_t values[3] = {0};
        uint32_t counts[3] = {0};
        unsigned distinct = 0;
        for (uint32_t n = 0; n < samples; n++) {
            uint32_t value = *reg;
            unsigned slot = 0;
            while (slot < distinct && values[slot] != value) {
                slot++;
            }
            if (slot == distinct) {
                if (distinct < 3) {
                    values[distinct] = value;
                    counts[distinct] = 0;
                    slot = distinct++;
                } else {
                    slot = 2;
                }
            }
            counts[slot]++;
        }
        char name[5];
        name[0] = "0123456789abcdef"[(offset >> 12) & 0xf];
        name[1] = "0123456789abcdef"[(offset >> 8) & 0xf];
        name[2] = "0123456789abcdef"[(offset >> 4) & 0xf];
        name[3] = "0123456789abcdef"[offset & 0xf];
        unsigned i = 4;
        emit(name, i);
        emit("=", 1);
        for (unsigned slot = 0; slot < distinct; slot++) {
            emit_u32(values[slot]);
            emit_u32(counts[slot]);
        }
        emit("\n", 1);
    }
    emit("OK\n", 3);
    (void)munmap((void *)base, 0x20000);
    (void)close(fd);
    return 0;
}
