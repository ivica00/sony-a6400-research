/* Read-only display-ground-truth capture for the ILCE-6400.
 *
 * Opens /dev/stream read-only and maps OSD/heap pages with PROT_READ only.
 * Writes only bounded dumps under /tmp_bt (the authorized diagnostic tmpfs).
 * Usage:
 *   capture_display_readonly osd_a|osd_b|sugilite OFFSET SIZE /tmp_bt/FILE
 *   capture_display_readonly summary
 * OFFSET is relative to the surface physical base and must be page aligned.
 */
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#define OSD_A_PA        0x23a80000ULL
#define OSD_B_PA        0x23b16000ULL
#define SUGILITE_PA     0x202e1000ULL
#define GL_COMMON_PA    0x202e0000ULL
#define GL_COMMON_SIZE  (32UL * 1024UL * 1024UL)
#define OSD_SIZE        (640UL * 480UL * 2UL)
#define SUGILITE_SIZE   (960UL * 540UL * 2UL)
#define BLOCK_SIZE      (64UL * 1024UL)

static int surface_base(const char *name, uint64_t *base, unsigned long long *size)
{
    if (!strcmp(name, "osd_a")) { *base = OSD_A_PA; *size = OSD_SIZE; return 0; }
    if (!strcmp(name, "osd_b")) { *base = OSD_B_PA; *size = OSD_SIZE; return 0; }
    if (!strcmp(name, "sugilite")) { *base = SUGILITE_PA; *size = SUGILITE_SIZE; return 0; }
    return -1;
}

static int dump_surface(const char *name, unsigned long long offset,
                        unsigned long long size, const char *path)
{
    uint64_t base = 0;
    unsigned long long surface_size = 0;
    int fd;
    void *mapped;
    FILE *out;

    if (surface_base(name, &base, &surface_size) != 0) {
        fprintf(stderr, "unknown surface %s\n", name);
        return 2;
    }
    if (strncmp(path, "/tmp_bt/", 8) != 0) {
        fprintf(stderr, "refusing output outside /tmp_bt: %s\n", path);
        return 2;
    }
    if ((offset & 0xfffULL) != 0 || size == 0 || offset + size > surface_size) {
        fprintf(stderr, "invalid range offset=%llu size=%llu surface=%llu\n",
                offset, size, surface_size);
        return 2;
    }
    fd = open("/dev/stream", O_RDONLY);
    if (fd < 0) {
        fprintf(stderr, "open /dev/stream O_RDONLY failed errno=%d\n", errno);
        return 3;
    }
    mapped = mmap(NULL, (size_t)size, PROT_READ, MAP_SHARED, fd,
                  (off_t)(base + offset));
    if (mapped == MAP_FAILED) {
        fprintf(stderr, "mmap %s failed errno=%d\n", name, errno);
        close(fd);
        return 4;
    }
    out = fopen(path, "wb");
    if (!out) {
        fprintf(stderr, "fopen %s failed errno=%d\n", path, errno);
        munmap(mapped, (size_t)size);
        close(fd);
        return 5;
    }
    if (fwrite(mapped, 1, (size_t)size, out) != (size_t)size) {
        fprintf(stderr, "short write %s errno=%d\n", path, errno);
        fclose(out);
        munmap(mapped, (size_t)size);
        close(fd);
        return 5;
    }
    fflush(out);
    fsync(fileno(out));
    fclose(out);
    munmap(mapped, (size_t)size);
    close(fd);
    printf("DUMP %s physical=0x%llx offset=%llu size=%llu path=%s\n",
           name, (unsigned long long)(base + offset), offset, size, path);
    return 0;
}

static int scan_gl_common(void)
{
    int fd;
    unsigned char *mapped;
    unsigned long block;
    unsigned long nonzero_total = 0;

    fd = open("/dev/stream", O_RDONLY);
    if (fd < 0) {
        fprintf(stderr, "open /dev/stream O_RDONLY failed errno=%d\n", errno);
        return 3;
    }
    mapped = mmap(NULL, GL_COMMON_SIZE, PROT_READ, MAP_SHARED, fd, (off_t)GL_COMMON_PA);
    if (mapped == MAP_FAILED) {
        fprintf(stderr, "mmap gl_common failed errno=%d\n", errno);
        close(fd);
        return 4;
    }
    for (block = 0; block < GL_COMMON_SIZE / BLOCK_SIZE; block++) {
        const unsigned char *p = mapped + block * BLOCK_SIZE;
        unsigned long nonzero = 0;
        unsigned long i;
        for (i = 0; i < BLOCK_SIZE; i++)
            if (p[i]) nonzero++;
        if (nonzero) {
            printf("BLOCK offset=0x%lx nonzero=%lu\n", block * BLOCK_SIZE, nonzero);
            nonzero_total += nonzero;
        }
    }
    printf("GL_COMMON nonzero_total=%lu\n", nonzero_total);
    munmap(mapped, GL_COMMON_SIZE);
    close(fd);
    return 0;
}

int main(int argc, char **argv)
{
    int result;
    if (argc == 2 && !strcmp(argv[1], "summary")) {
        result = scan_gl_common();
    } else if (argc == 5) {
        unsigned long long offset = strtoull(argv[2], NULL, 0);
        unsigned long long size = strtoull(argv[3], NULL, 0);
        result = dump_surface(argv[1], offset, size, argv[4]);
    } else {
        fprintf(stderr, "usage: %s osd_a|osd_b|sugilite OFFSET SIZE /tmp_bt/FILE | summary\n", argv[0]);
        return 2;
    }
    printf("END result=%d\n", result);
    return result;
}
