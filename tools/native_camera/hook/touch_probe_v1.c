/* Bounded, one-shot diagnostics. No ptrace, memory writes, key injection,
 * child processes, threads, shell commands, or input-event reads. */
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <string.h>
#include <dirent.h>
#include <sys/ioctl.h>
#include <linux/input.h>

static void copy_text(FILE *out, const char *path, unsigned limit) {
    char buf[512];
    int fd = open(path, O_RDONLY);
    fprintf(out, "\n=== %s (open=%d errno=%d) ===\n", path, fd, fd < 0 ? errno : 0);
    if (fd < 0) return;
    while (limit) {
        unsigned count = limit < sizeof(buf) ? limit : sizeof(buf);
        int n = read(fd, buf, count);
        if (n <= 0) break;
        fwrite(buf, 1, n, out);
        limit -= n;
    }
    close(fd);
}

static void list_dir(FILE *out, const char *path) {
    DIR *dir = opendir(path);
    struct dirent *entry;
    unsigned count = 0;
    fprintf(out, "\n=== directory %s errno=%d ===\n", path, dir ? 0 : errno);
    if (!dir) return;
    while (count++ < 160 && (entry = readdir(dir))) fprintf(out, "%s\n", entry->d_name);
    closedir(dir);
}

static void selected_maps(FILE *out) {
    FILE *source = fopen("/proc/149/maps", "r");
    char line[512];
    unsigned lines = 0;
    fprintf(out, "\n=== selected /proc/149/maps errno=%d ===\n", source ? 0 : errno);
    if (!source) return;
    while (lines++ < 2048 && fgets(line, sizeof(line), source)) {
        if (strstr(line, "/libObj.so") || strstr(line, "/viewUnified2.so")) fputs(line, out);
    }
    fprintf(out, "scanned_lines=%u eof=%d\n", lines, feof(source));
    fclose(source);
}

__attribute__((constructor)) static void collect(void) {
    int saved_errno = errno;
    int maps_fd = open("/setting/touch_probe_maps_v2.log", O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (maps_fd >= 0) {
        FILE *maps = fdopen(maps_fd, "w");
        if (maps) {
            fprintf(maps, "TOUCH_MAPS_V2 collector_pid=%d uid=%d\n", getpid(), getuid());
            copy_text(maps, "/proc/uptime", 128);
            copy_text(maps, "/proc/149/comm", 128);
            selected_maps(maps);
            fprintf(maps, "\nEND TOUCH_MAPS_V2\n");
            fclose(maps);
        } else close(maps_fd);
    }
    int fd = open("/setting/touch_probe_v1.log", O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (fd < 0) { errno = saved_errno; return; }
    FILE *out = fdopen(fd, "w");
    if (!out) { close(fd); errno = saved_errno; return; }
    fprintf(out, "TOUCH_PROBE_V1 pid=%d uid=%d; diagnostics only\n", getpid(), getuid());
    copy_text(out, "/proc/self/comm", 128);
    copy_text(out, "/proc/bus/input/devices", 6000);
    copy_text(out, "/proc/modules", 4000);
    copy_text(out, "/proc/mounts", 4000);
    list_dir(out, "/dev/input");
    list_dir(out, "/dev");
    for (int i = 0; i < 3; i++) {
        char path[64], name[128] = {0};
        snprintf(path, sizeof(path), "/dev/input/event%d", i);
        int input = open(path, O_RDONLY | O_NONBLOCK);
        fprintf(out, "\n%s open=%d errno=%d\n", path, input, input < 0 ? errno : 0);
        if (input >= 0) {
            int result = ioctl(input, EVIOCGNAME(sizeof(name)-1), name);
            fprintf(out, "EVIOCGNAME=%d errno=%d name=%s\n", result, result < 0 ? errno : 0, name);
            close(input);
        }
    }
    fprintf(out, "\nEND TOUCH_PROBE_V1\n");
    fclose(out);
    errno = saved_errno;
}
