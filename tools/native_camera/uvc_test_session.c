/* Freestanding native ARM UVC test session utility.
 * Opens /tmp_bt/video, registers UVC driver and DMA buffer,
 * holds UVC USB state for specified seconds (allowing Windows to enumerate),
 * then cleanly unregisters and restores Mass Storage mode.
 */

#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define DEV_PATH "/tmp_bt/video"

/* IOCTL opcodes verified from usbg_video.ko */
#define IOCTL_REG_VIDEO_DRV           0x4038e000u
#define IOCTL_REG_VIDEO_DATA_BUF_INFO 0x4008f000u
#define IOCTL_UNREG_VIDEO_DATA_BUF    0x0000f001u
#define IOCTL_UNREG_VIDEO_DRV         0x0000e001u

struct reg_video_drv_arg {
    unsigned char pad[56];
};

struct reg_video_data_buf_arg {
    unsigned int size;
    unsigned int phys_addr;
};

static volatile int g_keep_running = 1;

static void sig_handler(int sig)
{
    (void)sig;
    g_keep_running = 0;
}

int main(int argc, char **argv)
{
    int duration = 20;
    int fd;
    int ret;
    struct reg_video_drv_arg reg_drv;
    struct reg_video_data_buf_arg reg_buf;

    if (argc > 1) {
        duration = atoi(argv[1]);
        if (duration <= 0) duration = 20;
    }

    signal(SIGINT, sig_handler);
    signal(SIGTERM, sig_handler);

    printf("[uvc_test] opening %s...\n", DEV_PATH);
    fd = open(DEV_PATH, O_RDWR);
    if (fd < 0) {
        perror("[uvc_test] open failed");
        return 1;
    }
    printf("[uvc_test] open success (fd=%d)\n", fd);

    /* 1. Register Video Driver -> commits UVC descriptors */
    memset(&reg_drv, 0, sizeof(reg_drv));
    printf("[uvc_test] calling RegVideoDrv (0x%08x)...\n", IOCTL_REG_VIDEO_DRV);
    ret = ioctl(fd, IOCTL_REG_VIDEO_DRV, &reg_drv);
    printf("[uvc_test] RegVideoDrv result=%d\n", ret);
    if (ret != 0) {
        close(fd);
        return 2;
    }

    /* 2. Register DMA Data Buffer */
    memset(&reg_buf, 0, sizeof(reg_buf));
    reg_buf.size = 1294u * 1024u;
    reg_buf.phys_addr = 0x20000000u;
    printf("[uvc_test] calling RegVideoDataBufInfo (size=%u phys=0x%x)...\n",
           reg_buf.size, reg_buf.phys_addr);
    ret = ioctl(fd, IOCTL_REG_VIDEO_DATA_BUF_INFO, &reg_buf);
    printf("[uvc_test] RegVideoDataBufInfo result=%d\n", ret);

    printf("[uvc_test] *** UVC ONLINE *** Holding for %d seconds...\n", duration);
    fflush(stdout);

    for (int i = 0; i < duration && g_keep_running; i++) {
        sleep(1);
    }

    /* 3. Teardown and restore Mass Storage */
    printf("[uvc_test] Unregistering DMA buffer...\n");
    ret = ioctl(fd, IOCTL_UNREG_VIDEO_DATA_BUF);
    printf("[uvc_test] UnregVideoDataBufInfo result=%d\n", ret);

    printf("[uvc_test] Unregistering Video Driver (restoring MSC)...\n");
    ret = ioctl(fd, IOCTL_UNREG_VIDEO_DRV);
    printf("[uvc_test] UnregVideoDrv result=%d\n", ret);

    close(fd);
    printf("[uvc_test] TEST_SESSION_DONE_MSC_RESTORED\n");
    return 0;
}
