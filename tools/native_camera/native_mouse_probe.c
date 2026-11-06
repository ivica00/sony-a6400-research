/* Finite read-only observer of verified WidgetSystem mouse records. */
#define _DEFAULT_SOURCE
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <sys/ptrace.h>
#include <sys/wait.h>
#include <sys/syscall.h>
#include <time.h>
static volatile sig_atomic_t stopped;
static void stop(int s) { (void)s; stopped=1; }
static unsigned now(void) {
    struct timespec t;
    if(syscall(SYS_clock_gettime,CLOCK_MONOTONIC,&t)) return 0;
    return (unsigned)t.tv_sec*1000+t.tv_nsec/1000000;
}
static int sample(unsigned index) {
    static unsigned char previous[80];
    unsigned char records[80]; uint32_t pointer=0; int status,rc=-1,fd=-1;
    unsigned begin=now();
    if(ptrace(PTRACE_ATTACH,149,0,0)) return -2;
    pid_t waited;
    do { waited=waitpid(149,&status,0); } while(waited<0 && errno==EINTR);
    if(waited!=149 || !WIFSTOPPED(status)) goto done;
    fd=open("/proc/149/mem",O_RDONLY);
    if(fd<0 || pread(fd,&pointer,4,0x7108058)!=4 || pointer!=0x956f0) goto done;
    if(pread(fd,records,80,pointer+0x4a8)!=80) goto done;
    rc=0;
done:
    if(fd>=0) close(fd);
    if(ptrace(PTRACE_DETACH,149,0,0)) return -3;
    if(rc) return rc;
    if(index==0 || memcmp(previous,records,80)) {
        printf("change sample=%u ms=%u read_ms=%u data=",index,now(),now()-begin);
        for(unsigned j=0;j<80;j++) printf("%02x",records[j]);
        printf("\n"); memcpy(previous,records,80);
    }
    if(index%100==0) printf("heartbeat sample=%u ms=%u read_ms=%u\n",index,now(),now()-begin);
    return 0;
}
int main(void) {
    char comm[32]={0}; FILE *f=fopen("/proc/149/comm","r");
    if(!f || !fgets(comm,sizeof(comm),f) || strcmp(comm,"im.elf\n")) return 2;
    fclose(f);
    int lock=open("/tmp_bt/native_mouse_probe.lock",O_WRONLY|O_CREAT,0600);
    if(lock<0) return 3;
    struct flock lease={0}; lease.l_type=F_WRLCK; lease.l_whence=SEEK_SET;
    if(fcntl(lock,F_SETLK,&lease)) return 4;
    signal(SIGTERM,stop); signal(SIGINT,stop); signal(SIGHUP,SIG_IGN); setsid();
    setvbuf(stdout,0,_IONBF,0);
    printf("NATIVE_MOUSE_PROBE_V1 pid=%d ms=%u read_only=1 atomic=0 samples=1800 interval_us=100000\n",getpid(),now());
    unsigned i; int rc=0;
    for(i=0;i<1800 && !stopped;i++) {
        if(access("/tmp_bt/native_mouse_probe.stop",F_OK)==0) break;
        rc=sample(i); if(rc) break;
        usleep(100000);
    }
    printf("END samples=%u ms=%u result=%d\n",i,now(),rc);
    close(lock); return rc?5:0;
}
