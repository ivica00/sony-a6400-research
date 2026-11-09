/* One-shot coherent subset of PID149 heap state. No application calls/writes. */
#define _DEFAULT_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <dirent.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <sys/ptrace.h>
#include <sys/wait.h>
#include <sys/syscall.h>
#include <time.h>
#define MAX_THREADS 512
static pid_t tids[MAX_THREADS];
static unsigned attached;
static unsigned char bytes[0x4a8];
static unsigned long long now_ms(void) {
    struct timespec t;if(syscall(SYS_clock_gettime,CLOCK_MONOTONIC,&t)) return 0;
    return (unsigned long long)t.tv_sec*1000+t.tv_nsec/1000000;
}
static int enumerate(pid_t *out,unsigned *count) {
    DIR *dir=opendir("/proc/149/task");struct dirent *entry;unsigned n=0;
    if(!dir)return -1;
    while((entry=readdir(dir))) {
        char *end;long id=strtol(entry->d_name,&end,10);
        if(!*entry->d_name || *end || id<=0)continue;
        if(n>=MAX_THREADS){*count=n;closedir(dir);return -2;}out[n++]=(pid_t)id;
    }
    closedir(dir);*count=n;return 0;
}
int main(void) {
    setvbuf(stdout,0,_IONBF,0);
    unsigned count=0,confirmed=0;pid_t check[MAX_THREADS];
    int result=0,status=0,fd=-1;unsigned long long begin=now_ms();
    if(!begin){printf("CLOCK_FAILED\n");return 1;}
    int enumeration=enumerate(tids,&count);
    if(enumeration || !count){printf("ENUM_FAILED result=%d count=%u errno=%d\n",enumeration,count,errno);return 1;}
    for(unsigned i=0;i<count;i++) {
        if(ptrace(PTRACE_ATTACH,tids[i],0,0)){result=-3;goto resume;}
        attached++;
        for(;;) {
            pid_t got=waitpid(tids[i],&status,__WALL|WNOHANG);
            if(got==tids[i] && WIFSTOPPED(status))break;
            if(got<0 || now_ms()-begin>2000){result=-4;goto resume;}
            usleep(1000);
        }
    }
    if(enumerate(check,&confirmed) || confirmed!=count){result=-5;goto resume;}
    for(unsigned i=0;i<confirmed;i++) {
        unsigned j;for(j=0;j<count;j++)if(check[i]==tids[j])break;
        if(j==count){result=-6;goto resume;}
    }
    fd=open("/proc/149/mem",O_RDONLY);if(fd<0){result=-7;goto resume;}
    if(pread(fd,bytes,0x450,0x27800000)!=0x450 ||
       pread(fd,bytes+0x450,0x50,0x27837c70)!=0x50 ||
       pread(fd,bytes+0x4a0,8,0x6c8cc)!=8){result=-8;goto resume;}
resume:
    if(fd>=0)close(fd);
    for(unsigned i=attached;i;i--) {
        if(ptrace(PTRACE_DETACH,tids[i-1],0,0)){printf("DETACH_FAIL tid=%d errno=%d\n",tids[i-1],errno);result=-9;}
    }
    unsigned long long elapsed=now_ms()-begin;
    printf("SNAPSHOT result=%d threads=%u confirmed=%u resumed=%u elapsed_ms=%llu\n",result,count,confirmed,attached,elapsed);
    if(result)return 2;
    FILE *file=fopen("/tmp_bt/native_resource_snapshot.bin","wb");if(!file){printf("OPEN_FAILED errno=%d\n",errno);return 3;}
    result=(fwrite(bytes,1,sizeof(bytes),file)!=sizeof(bytes) || fflush(file) || fsync(fileno(file)));
    if(fclose(file))result=1;
    printf("END result=%d bytes=%u\n",result,(unsigned)sizeof(bytes));
    return result?4:0;
}
