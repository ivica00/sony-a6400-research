/* Bounded original-driver read requests only. No sensor init/config/start/stop. */
#define _DEFAULT_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/ioctl.h>
#include <sys/time.h>
#include <signal.h>
#include <sys/mman.h>

struct message { uint32_t header[4]; uint32_t op, output, unused[2], status; };
struct request { uint32_t queue, message; };
static void timeout_handler(int signum) { (void)signum; _exit(124); }
int main(void) {
    setvbuf(stdout,0,_IONBF,0);
    signal(SIGALRM,timeout_handler);
    int fd=open("/dev/uipc",O_RDWR);
    if(fd<0) { printf("OPEN errno=%d\n",errno); return 1; }
    uint32_t geometry[4]={0};
    struct request handshake={0,(uint32_t)(uintptr_t)geometry};
    errno=0;
    int connected=ioctl(fd,0x80000010UL,&handshake);
    printf("CONNECT result=%d errno=%d pool=%u variable=%u fixed=%u\n",connected,errno,geometry[0],geometry[1],geometry[2]);
    if(connected || geometry[0]!=0x100000) { close(fd);return 2; }
    void *pool=mmap(0,geometry[0],PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
    if(pool==MAP_FAILED) { printf("MMAP errno=%d\n",errno);close(fd);return 3; }
    struct message identity={{sizeof(identity),0,0,0},4,0,{0,0},0xffffffff};
    struct request identify={0x00a30281,(uint32_t)(uintptr_t)&identity};
    alarm(3);errno=0;
    int id_result=ioctl(fd,0x80000006UL,&identify),id_errno=errno;
    alarm(0);
    printf("IDENTITY ioctl=%d errno=%d status=%u matches_0x2a=%u\n",id_result,id_errno,identity.status,identity.output);
    if(id_result || identity.status || identity.output!=1) { munmap(pool,geometry[0]);close(fd);return 4; }
    for(unsigned n=0;n<128;n++) {
        unsigned char output[16]={0};
        struct message m={{sizeof(m),0,0,0},5,(uint32_t)(uintptr_t)output,{0,0},0xffffffff};
        struct request r={0x00a30281,(uint32_t)(uintptr_t)&m};
        struct timeval before,after;
        gettimeofday(&before,0); alarm(3); errno=0;
        int result=ioctl(fd,0x80000006UL,&r),saved=errno;
        alarm(0); gettimeofday(&after,0);
        long elapsed=(after.tv_sec-before.tv_sec)*1000000L+after.tv_usec-before.tv_usec;
        int16_t x=(int16_t)((unsigned)output[8]|((unsigned)output[9]<<8));
        int16_t y=(int16_t)((unsigned)output[10]|((unsigned)output[11]<<8));
        int16_t z=(int16_t)((unsigned)output[12]|((unsigned)output[13]<<8));
        printf("READ n=%u ioctl=%d errno=%d status=%u us=%ld valid=%u xyz=%d,%d,%d\n",n,result,saved,m.status,elapsed,output[0],x,y,z);
        if(result || m.status) break;
    }
    munmap(pool,geometry[0]);close(fd); printf("END\n");return 0;
}
