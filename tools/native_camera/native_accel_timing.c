/* Bounded read-only acquisition through the original accel driver. */
#define _DEFAULT_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <sys/statvfs.h>
#include <time.h>

struct message { uint32_t header[4],op,output,unused[2],status; };
struct request { uint32_t queue,message; };
struct sample { uint64_t before,after; int32_t result,error; uint32_t status; unsigned char data[16]; };
static struct sample samples[128];
static void expired(int signum) { (void)signum; _exit(124); }
static uint64_t now_us(void) {
    struct timespec value;
    if(syscall(SYS_clock_gettime,CLOCK_MONOTONIC,&value)) _exit(125);
    return (uint64_t)value.tv_sec*1000000u+(unsigned)value.tv_nsec/1000u;
}
int main(void) {
    setvbuf(stdout,0,_IONBF,0);signal(SIGALRM,expired);
    struct statvfs space;
    if(statvfs("/tmp_bt",&space) || (uint64_t)space.f_bavail*space.f_frsize<65536) {
        printf("SPACE insufficient\n");return 1;
    }
    int fd=open("/dev/uipc",O_RDWR);
    if(fd<0) { printf("OPEN errno=%d\n",errno);return 2; }
    uint32_t geometry[4]={0};struct request handshake={0,(uint32_t)(uintptr_t)geometry};
    if(ioctl(fd,0x80000010UL,&handshake) || geometry[0]!=0x100000) { close(fd);return 3; }
    void *pool=mmap(0,geometry[0],PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
    if(pool==MAP_FAILED) { close(fd);return 4; }
    struct message identity={{sizeof(identity),0,0,0},4,0,{0,0},0xffffffff};
    struct request identify={0x00a30281,(uint32_t)(uintptr_t)&identity};
    alarm(3);int ir=ioctl(fd,0x80000006UL,&identify);alarm(0);
    if(ir || identity.status || identity.output!=1) { munmap(pool,geometry[0]);close(fd);return 5; }
    printf("BEGIN clock=MONOTONIC units=us identity_matches_0x2a=1 requested_interval_us=2000 capacity=128\n");
    alarm(4);unsigned count=0;int failed=0;
    for(unsigned n=0;n<128;n++) {
        struct sample *s=&samples[n];
        struct message m={{sizeof(m),0,0,0},5,(uint32_t)(uintptr_t)s->data,{0,0},0xffffffff};
        struct request r={0x00a30281,(uint32_t)(uintptr_t)&m};
        s->before=now_us();errno=0;s->result=ioctl(fd,0x80000006UL,&r);
        s->error=errno;s->after=now_us();s->status=m.status;count++;
        if(s->result || s->status || s->data[0]!=1) { failed=1;break; }
        usleep(2000);
    }
    alarm(0);munmap(pool,geometry[0]);close(fd);
    for(unsigned n=0;n<count;n++) {
        struct sample *s=&samples[n];
        int x=(int16_t)((unsigned)s->data[8]|((unsigned)s->data[9]<<8));
        int y=(int16_t)((unsigned)s->data[10]|((unsigned)s->data[11]<<8));
        int z=(int16_t)((unsigned)s->data[12]|((unsigned)s->data[13]<<8));
        printf("S %u %llu %llu %d %d %u %u %d %d %d\n",n,
            (unsigned long long)s->before,(unsigned long long)s->after,
            s->result,s->error,s->status,s->data[0],x,y,z);
    }
    printf("END count=%u result=%d\n",count,failed);return failed?6:0;
}
