/* Sony a6400 UVC + PTP Shared Enumeration Session Runner.
 * Confined strictly to /tmp_bt.
 *
 * Enforces verified lifecycle:
 * Phase A: Freeze 174 threads of PID 149 -> IOCTL A6400_UVC_ENTRY_HOOK_PUBLISH -> Resume.
 * Phase B: IOCTL_UVC_INIT (0x4038e000) -> Starts composite session.
 * Phase C: Hold session for requested duration (allowing host enumeration).
 * Phase D: IOCTL_UVC_STOP (0x0000e001) -> Ends composite session.
 * Phase E: Freeze 174 threads of PID 149 -> IOCTL A6400_UVC_ENTRY_HOOK_RETIRE -> Resume.
 */

#define _DEFAULT_SOURCE
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/ioctl.h>
#include <sys/ptrace.h>
#include <sys/wait.h>
#include <time.h>

#include "uvc_ptp_stop_attest.h"
#include "uvc_ptp_entry_hook.h"
#include "native_freeze.h"
#include "uvc_ptp_runner_stop.h"

#define IOCTL_UVC_INIT      0x4038e000u
#define IOCTL_UVC_STOP      0x0000e001u

struct uvc_user_probe_info {
    void *context;
    void (*callbacks[8])(void);
    void *interfaces_ptr;
    unsigned int reserved40;
    unsigned char reserved44;
    unsigned char interface_count;
    unsigned short reserved46;
    void *extra_info_ptr;
    unsigned int extra_info_size;
};
_Static_assert(sizeof(struct uvc_user_probe_info) == 56, "uvc_user_probe_info size must be exactly 56 bytes");

static unsigned char g_interfaces[4] = { 0, 0, 1, 1 };
static void dummy_cb(void) {}

static volatile sig_atomic_t g_stop_requested = 0;

static void sig_handler(int sig)
{
    (void)sig;
    g_stop_requested = 1;
}

static struct a6400_stop_request attest;
static const char *receipt_path;
static int preserve_receipt(void);

static int stop_session(void *context)
{ return ioctl(*(int *)context,IOCTL_UVC_STOP,0); }
static int read_session_status(void *context,int state[4])
{ return ioctl(*(int *)context,0x8010f022u,state); }

static void retain_failed_session(int fd,const int state[4]) __attribute__((noreturn));
static void retain_failed_session(int fd,const int state[4])
{
    printf("SESSION_RUNNER RETAINED fd=%d phase=%d pin=%d hooks=%d error=%d; no retire/close/retry\n",
           fd,state[0],state[1],state[2],state[3]);
    fflush(stdout);fflush(stderr);
    if(receipt_path && preserve_receipt())
        fprintf(stderr,"RETAINED receipt_copy_failed errno=%d\n",errno);
    /* Keep the descriptor alive. Exiting would implicitly invoke release and
     * could retry failed cleanup. A blocked STOP never reaches this branch. */
    for(;;) pause();
}

static int run_session(int argc, char **argv)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    setvbuf(stderr, NULL, _IONBF, 0);

    int duration = 90;
    int wait_pcremote = 0;
    int wait_timeout = 300;
    const char *device_path = "/tmp_bt/video";
    int fd = -1, ret = 0, published = 0, session_active = 0, init_attempted = 0;

    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--duration") && i + 1 < argc) {
            duration = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "--timeout") && i + 1 < argc) {
            wait_timeout = atoi(argv[++i]);
        } else if (!strcmp(argv[i], "--wait-pcremote")) {
            wait_pcremote = 1;
        } else if (!strcmp(argv[i], "--device") && i + 1 < argc) {
            device_path = argv[++i];
        } else if (!strcmp(argv[i], "--receipt") && i + 1 < argc) {
            receipt_path = argv[++i];
            if(strncmp(receipt_path,"/tmp_bt/",8) || strstr(receipt_path,"/../") || strlen(receipt_path)>200) {
                fprintf(stderr,"Receipt must be a bounded /tmp_bt path\n");return 1;
            }
        } else if (!strcmp(argv[i], "--help")) {
            printf("Usage: %s [--duration <sec>] [--wait-pcremote] [--timeout <sec>] [--device <path>] [--receipt /tmp_bt/path]\n", argv[0]);
            return 0;
        }
    }

    if (duration <= 0 || duration > 300) {
        fprintf(stderr, "Invalid duration %d (must be 1..300)\n", duration);
        return 1;
    }

    signal(SIGINT, sig_handler);
    signal(SIGTERM, sig_handler);

    printf("SESSION_RUNNER start target=149 duration=%d wait_pcremote=%d timeout=%d device=%s\n",
           duration, wait_pcremote, wait_timeout, device_path);
    fflush(stdout);

    fd = open(device_path, O_RDWR);
    if (fd < 0) {
        fprintf(stderr, "FAIL open device %s: %s (errno=%d)\n", device_path, strerror(errno), errno);
        return 1;
    }

    if (wait_pcremote) {
        printf("STEP 0: Waiting for camera to enter PC Remote mode (0x054c:0x0caa, timeout=%ds)...\n", wait_timeout);
        fflush(stdout);
        unsigned short ids[2] = {0, 0};
        int waited = 0, found = 0;
        while (waited < wait_timeout && !g_stop_requested) {
            ret = ioctl(fd, A6400_UVC_QUERY_IDENTITY, ids);
            if (ret == 0 && ids[0] == 0x054cu && ids[1] == 0x0caau) {
                found = 1;
                printf("STEP 0: Detected PC Remote mode (0x054c:0x0caa) at %d seconds! Settling 2s...\n", waited);
                fflush(stdout);
                sleep(2);
                break;
            }
            sleep(1);
            waited++;
        }
        if (!found) {
            fprintf(stderr, "FAIL timeout waiting for PC Remote (last seen: 0x%04x:0x%04x ret=%d)\n",
                    ids[0], ids[1], ret);
            close(fd);
            return 9;
        }
    }

    /* Phase A: Freeze -> Publish Entry Hook -> Resume */
    printf("STEP 1: Freezing PID 149 for entry hook publication...\n");
    fflush(stdout);
    ret = freeze_process();
    if (ret != 0) {
        fprintf(stderr, "FAIL freeze_process: %d\n", ret);
        close(fd);
        return 2;
    }

    attest.version = 2;
    attest.owner = 149;
    attest.count = freeze_count;
    attest.tids = (uint32_t)(uintptr_t)freeze_tids;
    ret = ioctl(fd, A6400_UVC_ENTRY_HOOK_PUBLISH, &attest);
    int pub_errno = errno;

    int resume_ret = freeze_resume();
    if (resume_ret != 0) {
        fprintf(stderr, "CRITICAL freeze_resume failed: %d\n", resume_ret);
        close(fd);
        return 3;
    }

    if (ret != 0 || attest.error != 0 || attest.completed != freeze_count) {
        fprintf(stderr, "FAIL A6400_UVC_ENTRY_HOOK_PUBLISH ret=%d errno=%d completed=%u expected=%u error=%d\n",
                ret, pub_errno, attest.completed, attest.count, attest.error);
        close(fd);
        return 4;
    }
    published = 1;
    printf("STEP 1: Entry hook published at 0x602b8844, 4-core sync complete, threads resumed.\n");
    fflush(stdout);

    /* Phase B: Initialize UVC/PTP Session */
    printf("STEP 2: Initializing composite UVC+PTP session (IOCTL_UVC_INIT)...\n");
    fflush(stdout);
    struct uvc_user_probe_info info;
    memset(&info, 0, sizeof(info));
    info.context = 0;
    for (int i = 0; i < 8; ++i) info.callbacks[i] = dummy_cb;
    info.interfaces_ptr = g_interfaces;
    info.interface_count = 2;
    info.extra_info_ptr = NULL;
    info.extra_info_size = 0;

    init_attempted = 1;
    ret = ioctl(fd, IOCTL_UVC_INIT, &info);
    printf("STEP 2: IOCTL_UVC_INIT returned ret=%d errno=%d (%s)\n", ret, errno, strerror(errno));
    fflush(stdout);
    if (ret != 0) {
        fprintf(stderr, "FAIL IOCTL_UVC_INIT: ret=%d errno=%d (%s)\n", ret, errno, strerror(errno));
        goto teardown;
    }
    session_active = 1;
    printf("STEP 2: Composite session ACTIVE! Holding for %d seconds...\n", duration);
    fflush(stdout);

    /* Phase C: Hold Session */
    unsigned int last_usb_state[4]={0xffffffffu,0xffffffffu,0xffffffffu,0xffffffffu};
    int last_state_error=0;
    for (int sec = 0; sec < duration && !g_stop_requested; ++sec) {
        unsigned int usb_state[4];
        int state_ret=ioctl(fd,A6400_UVC_QUERY_USB_STATE,usb_state);
        if(!state_ret && (last_state_error || memcmp(usb_state,last_usb_state,sizeof(usb_state)))) {
            printf("USB_STATE sec=%d flags=%08x config=%u mode=%u speed=%u\n",sec,
                   usb_state[0],usb_state[1],usb_state[2],usb_state[3]);
            memcpy(last_usb_state,usb_state,sizeof(usb_state));
        } else if(state_ret && (sec==0 || errno!=last_state_error))printf("USB_STATE unavailable sec=%d errno=%d\n",sec,errno);
        last_state_error=state_ret ? errno:0;
        sleep(1);
    }

teardown:
    /* Phase D: Stop Session if active */
    if (init_attempted) {
        printf("STEP 3: Stopping composite session (IOCTL_UVC_STOP)...\n");
        fflush(stdout);
        int state[4];
        const struct a6400_runner_stop_ops stop_ops={stop_session,read_session_status};
        if (!a6400_runner_stop_verified(&stop_ops,&fd,state)) retain_failed_session(fd,state);
        printf("STEP 3: Composite session stopped; IDLE/unpinned/no hooks/no error verified.\n");
        fflush(stdout);
    }

    /* Phase E: Freeze -> Retire Entry Hook -> Resume */
    if (published) {
        printf("STEP 4: Freezing PID 149 for entry hook retirement...\n");
        fflush(stdout);
        int freeze_ret = freeze_process();
        if (freeze_ret != 0) {
            fprintf(stderr, "CRITICAL freeze_process before retire failed: %d\n", freeze_ret);
            close(fd);
            return 5;
        }

        attest.version = 2;
        attest.owner = 149;
        attest.count = freeze_count;
        attest.tids = (uint32_t)(uintptr_t)freeze_tids;
        ret = ioctl(fd, A6400_UVC_ENTRY_HOOK_RETIRE, &attest);
        int ret_errno = errno;

        resume_ret = freeze_resume();
        if (resume_ret != 0) {
            fprintf(stderr, "CRITICAL freeze_resume after retire failed: %d\n", resume_ret);
            close(fd);
            return 6;
        }

        if (ret != 0 || attest.error != 0 || attest.completed != freeze_count) {
            fprintf(stderr, "FAIL A6400_UVC_ENTRY_HOOK_RETIRE ret=%d errno=%d completed=%u expected=%u error=%d\n",
                    ret, ret_errno, attest.completed, attest.count, attest.error);
            close(fd);
            return 7;
        }
        printf("STEP 4: Entry hook retired, 0xe1a0c00d restored, 4-core sync complete, threads resumed.\n");
        fflush(stdout);
    }

    close(fd);
    printf("SESSION_RUNNER complete result=%d\n",session_active ? 0:8);
    fflush(stdout);
    return session_active ? 0 : 8;
}

static int preserve_receipt(void)
{
    char buffer[4096];unsigned int total=0;
    int source=open("/proc/self/fd/1",O_RDONLY),target;
    if(source<0)return -1;
    target=open(receipt_path,O_WRONLY|O_CREAT|O_EXCL,0600);
    if(target<0){close(source);return -1;}
    for(;;) {
        ssize_t size=read(source,buffer,sizeof(buffer));
        if(size<0 && errno==EINTR)continue;
        if(size<0){close(source);close(target);return -1;}
        if(!size)break;
        if((unsigned int)size>256u*1024u-total){close(source);close(target);return -1;}
        total+=(unsigned int)size;
        for(ssize_t written=0;written<size;) {
            ssize_t n=write(target,buffer+written,(size_t)(size-written));
            if(n<0 && errno==EINTR)continue;
            if(n<=0){close(source);close(target);return -1;}
            written+=n;
        }
    }
    close(source);return close(target);
}

int main(int argc,char **argv)
{
    int result=run_session(argc,argv);
    fflush(stdout);fflush(stderr);
    /* A warmboot may unlink RAM pathnames while stdout's inode is still open.
     * Preserve that log under a fresh RAM pathname only after teardown. */
    if(receipt_path && preserve_receipt()) {
        fprintf(stderr,"SESSION_RUNNER receipt_copy_failed errno=%d\n",errno);
        return result ? result:10;
    }
    return result;
}
