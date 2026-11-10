/* Minimal read-only camera probe for the MPR erased-state ioctl (E0305).
 *
 * Opens /dev/nflasha4 O_RDONLY and issues exactly one read-only query:
 *   ioctl(fd, 0x80014123, &byte)   -> EXT_CSD[0xB5] (emmc_seq_get_erased_mem_cont)
 * Prints "B=<hex>\n" on success, "OERR\n" on open failure, "IERR\n" on ioctl
 * failure. Never writes the device, never switches mode, never calls another
 * ioctl. Linked against the preserved Sony libc like the existing native helpers.
 */
#include <fcntl.h>
#include <stdint.h>
#include <sys/ioctl.h>
#include <unistd.h>

static void emit(const char *text, unsigned length)
{
    (void)write(1, text, length);
}

static void emit_byte(unsigned char value)
{
    static const char digits[] = "0123456789abcdef";
    char out[5];
    out[0] = 'B';
    out[1] = '=';
    out[2] = digits[(value >> 4) & 0xf];
    out[3] = digits[value & 0xf];
    out[4] = '\n';
    emit(out, sizeof(out));
}

int main(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    unsigned char value = 0;
    int fd = open("/dev/nflasha4", O_RDONLY);
    if (fd < 0) {
        emit("OERR\n", 5);
        return 2;
    }
    int result = ioctl(fd, 0x80014123UL, &value);
    (void)close(fd);
    if (result < 0) {
        emit("IERR\n", 5);
        return 3;
    }
    emit_byte(value);
    return 0;
}
