/* CPU stop/resume receipt only. No application calls, hooks, or USB changes.
 * Saved user registers do not prove absence of pending kernel/DMA work. */
#define _DEFAULT_SOURCE
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/ptrace.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/ioctl.h>
#include "uvc_ptp_stop_attest.h"
#include "uvc_ptp_route_dryrun.h"
#include "native_freeze.h"
#ifndef A6400_UVC_ENTRY_HOOK_CYCLE
#define A6400_UVC_ENTRY_HOOK_CYCLE 0xc020f025u
#endif
static uint32_t registers[512][18];
static unsigned captured;
static char stop_sites[512][80];
static int stop_signo[512],stop_code[512];
static struct a6400_stop_request attest;

int main(int argc,char **argv)
{
    int result,resumed,device=-1,attest_result=0,attest_errno=0;
    int is_route_shadow=0,is_entry_hook=0;
    if(argc==5) {
        if(!strcmp(argv[4],"--route-shadow")) is_route_shadow=1;
        else if(!strcmp(argv[4],"--entry-hook")) is_entry_hook=1;
        else {
            puts("USB_FREEZE mode=preflight freeze=0 requires=--capture-once");fflush(stdout);return 2;
        }
    }
    if((argc!=2 && argc!=4 && argc!=5) || strcmp(argv[1],"--capture-once") ||
       (argc>=4 && (strcmp(argv[2],"--attest-device") || strncmp(argv[3],"/tmp_bt/",8)))) {
        puts("USB_FREEZE mode=preflight freeze=0 requires=--capture-once");fflush(stdout);return 2;
    }
    /* Force helper stdio initialization before stopping the other process. */
    puts("USB_FREEZE version=1 target=149 memory_writes=0 hooks=0 usb_changes=0");fflush(stdout);
    if(argc>=4) {
        device=open(argv[3],O_RDWR);
        if(device<0){printf("END result=-126 open_errno=%d capture=0\n",errno);fflush(stdout);return 1;}
    }
    result=freeze_process();
    if(result){if(device>=0)close(device);printf("END result=%d capture=0\n",result);fflush(stdout);return 1;}
    if(device>=0) {
        unsigned long cmd = A6400_UVC_ATTEST_STOPS;
        if(is_route_shadow) cmd = A6400_UVC_ROUTE_DRYRUN;
        else if(is_entry_hook) cmd = A6400_UVC_ENTRY_HOOK_CYCLE;
        attest.version=2;attest.owner=149;attest.count=freeze_count;
        attest.tids=(uint32_t)(uintptr_t)freeze_tids;
        attest_result=ioctl(device,cmd,&attest);
        if(attest_result)attest_errno=errno;
        if(attest_result || attest.error || attest.completed!=freeze_count)result=-127;
    }
    for(unsigned i=0;!result && i<freeze_count;++i) {
        if(freeze_ms()-freeze_begin>2000){result=-120;break;}
        if(ptrace(PTRACE_GETREGS,freeze_tids[i],0,registers[i])){result=-121;break;}
        if((registers[i][16]&31u)!=16u){result=-122;break;}
        {
            siginfo_t info;
            if(ptrace(PTRACE_GETSIGINFO,freeze_tids[i],0,&info)){result=-125;break;}
            stop_signo[i]=info.si_signo;stop_code[i]=info.si_code;
        }
        {
            char path[80];int fd,n;
            snprintf(path,sizeof(path),"/proc/149/task/%d/wchan",(int)freeze_tids[i]);
            fd=open(path,O_RDONLY);
            if(fd<0){result=-123;break;}
            n=(int)read(fd,stop_sites[i],sizeof(stop_sites[i])-1);
            close(fd);
            if(n<=0){result=-124;break;}
            stop_sites[i][n]=0;
            while(n && (stop_sites[i][n-1]=='\n'||stop_sites[i][n-1]=='\r'))stop_sites[i][--n]=0;
        }
        ++captured;
    }
    resumed=freeze_resume();
    if(resumed)result=resumed;
    if(device>=0) {
        close(device);
        printf("ATTEST result=%d errno=%d completed=%u expected=%u error=%d\n",
               attest_result,attest_errno,attest.completed,attest.count,attest.error);
        if(is_route_shadow)puts("ROUTE_SHADOW native_route_writes=0");
        else if(is_entry_hook)puts("ENTRY_HOOK verified_publication_cycle=1");
    }
    /* Emit per-thread data only after resuming all attached threads. */
    for(unsigned i=0;i<captured;++i) {
        printf("REG tid=%d pc=%08x sp=%08x cpsr=%08x orig_r0=%08x\n",
               (int)freeze_tids[i],registers[i][15],registers[i][13],registers[i][16],registers[i][17]);
        printf("STOP tid=%d wchan=%s signal=%u info_signal=%d info_code=%d\n",
               (int)freeze_tids[i],stop_sites[i],(unsigned)freeze_stop_signals[i],stop_signo[i],stop_code[i]);
    }
    printf("END result=%d captured=%u expected=%u saved_user_regs_only=1\n",result,captured,freeze_count);
    fflush(stdout);return result?1:0;
}
