#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>

#define BACKUP_PATH "/setting/Backup.bin"
#define EXPECTED_SIZE 1171036

#define OFF_CHECKSUM 32
#define OFF_FORCE_BACKUP 1145720
#define OFF_DEFAULT_WIDTH_HI 1145723

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s [check|apply|revert]\n", argv[0]);
        return 1;
    }

    const char *action = argv[1];
    int is_apply = (strcmp(action, "apply") == 0);
    int is_revert = (strcmp(action, "revert") == 0);
    int is_check = (strcmp(action, "check") == 0);

    if (!is_apply && !is_revert && !is_check) {
        fprintf(stderr, "Invalid action '%s'. Use check, apply, or revert.\n", action);
        return 1;
    }

    int fd = open(BACKUP_PATH, is_check ? O_RDONLY : O_RDWR);
    if (fd < 0) {
        perror("Failed to open " BACKUP_PATH);
        return 2;
    }

    struct stat st;
    if (fstat(fd, &st) != 0) {
        perror("fstat failed");
        close(fd);
        return 3;
    }

    if (st.st_size != EXPECTED_SIZE) {
        fprintf(stderr, "Unexpected file size: %lld (expected %d)\n", (long long)st.st_size, EXPECTED_SIZE);
        close(fd);
        return 4;
    }

    unsigned char b_chk = 0, b_force = 0, b_width_hi = 0;

    lseek(fd, OFF_CHECKSUM, SEEK_SET);
    if (read(fd, &b_chk, 1) != 1) { perror("read chk"); close(fd); return 5; }

    lseek(fd, OFF_FORCE_BACKUP, SEEK_SET);
    if (read(fd, &b_force, 1) != 1) { perror("read force"); close(fd); return 5; }

    lseek(fd, OFF_DEFAULT_WIDTH_HI, SEEK_SET);
    if (read(fd, &b_width_hi, 1) != 1) { perror("read width_hi"); close(fd); return 5; }

    printf("Current state in %s:\n", BACKUP_PATH);
    printf("  [0x%05x] Checksum byte: 0x%02x\n", OFF_CHECKSUM, b_chk);
    printf("  [0x%05x] force_backup: 0x%02x\n", OFF_FORCE_BACKUP, b_force);
    printf("  [0x%05x] width_hi:     0x%02x\n", OFF_DEFAULT_WIDTH_HI, b_width_hi);

    if (is_check) {
        if (b_chk == 0x25 && b_force == 0x00 && b_width_hi == 0x02) {
            printf("STATUS: ORIGINAL (640x480 LiveView, force_backup=0)\n");
        } else if (b_chk == 0x2b && b_force == 0x01 && b_width_hi == 0x07) {
            printf("STATUS: PATCHED (1920x1080 LiveView, force_backup=1)\n");
        } else {
            printf("STATUS: UNKNOWN / MODIFIED\n");
        }
        close(fd);
        return 0;
    }

    if (is_apply) {
        if (b_chk != 0x25 || b_force != 0x00 || b_width_hi != 0x02) {
            fprintf(stderr, "Preimage mismatch! Refusing to apply patch over non-original bytes.\n");
            close(fd);
            return 6;
        }

        b_chk = 0x2b;
        b_force = 0x01;
        b_width_hi = 0x07;

        lseek(fd, OFF_CHECKSUM, SEEK_SET);
        if (write(fd, &b_chk, 1) != 1) { perror("write chk"); close(fd); return 7; }

        lseek(fd, OFF_FORCE_BACKUP, SEEK_SET);
        if (write(fd, &b_force, 1) != 1) { perror("write force"); close(fd); return 7; }

        lseek(fd, OFF_DEFAULT_WIDTH_HI, SEEK_SET);
        if (write(fd, &b_width_hi, 1) != 1) { perror("write width_hi"); close(fd); return 7; }

        fsync(fd);
        close(fd);
        sync();
        printf("SUCCESS: Applied 1080p LiveView patch to %s\n", BACKUP_PATH);
        return 0;
    }

    if (is_revert) {
        if (b_chk != 0x2b || b_force != 0x01 || b_width_hi != 0x07) {
            fprintf(stderr, "Preimage mismatch! Bytes do not match expected patched state.\n");
            close(fd);
            return 6;
        }

        b_chk = 0x25;
        b_force = 0x00;
        b_width_hi = 0x02;

        lseek(fd, OFF_CHECKSUM, SEEK_SET);
        if (write(fd, &b_chk, 1) != 1) { perror("write chk"); close(fd); return 7; }

        lseek(fd, OFF_FORCE_BACKUP, SEEK_SET);
        if (write(fd, &b_force, 1) != 1) { perror("write force"); close(fd); return 7; }

        lseek(fd, OFF_DEFAULT_WIDTH_HI, SEEK_SET);
        if (write(fd, &b_width_hi, 1) != 1) { perror("write width_hi"); close(fd); return 7; }

        fsync(fd);
        close(fd);
        sync();
        printf("SUCCESS: Reverted %s to ORIGINAL 640x480 LiveView\n", BACKUP_PATH);
        return 0;
    }

    close(fd);
    return 0;
}
