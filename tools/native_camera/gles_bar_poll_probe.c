/* Minimal read-only GPES BAR status poll (E0341/E0313 physical evidence).
 *
 * mmaps the GPES BAR 0xF1000000 (16 KiB) read-only and polls BAR+0x34 for a
 * bounded window, recording distinct nonzero values and counts. It never
 * writes the BAR, never opens /dev/dmpgles2 or /dev/stream.
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
    out[8] = '\n';
    emit(out, 9);
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
    volatile uint32_t *status = (volatile uint32_t *)(base + 0x34);
    uint32_t values[8] = {0};
    uint32_t counts[8] = {0};
    unsigned distinct = 0;
    uint32_t samples = 0;
    uint32_t nonzero = 0;
    for (uint32_t index = 0; index < 2000000U; index++) {
        uint32_t value = *status;
        samples++;
        if (value == 0) {
            continue;
        }
        nonzero++;
        unsigned found = distinct;
        for (unsigned slot = 0; slot < distinct; slot++) {
            if (values[slot] == value) {
                found = slot;
                break;
            }
        }
        if (found == distinct) {
            if (distinct < 8) {
                values[distinct] = value;
                counts[distinct] = 0;
                found = distinct++;
            } else {
                found = 7;
            }
        }
        counts[found]++;
    }
    emit("S=", 2);
    emit_u32(samples);
    emit("N=", 2);
    emit_u32(nonzero);
    for (unsigned slot = 0; slot < distinct; slot++) {
        emit("V=", 2);
        emit_u32(values[slot]);
        emit("C=", 2);
        emit_u32(counts[slot]);
    }
    emit("OK\n", 3);
    (void)munmap((void *)base, 0x4000);
    (void)close(fd);
    return 0;
}
