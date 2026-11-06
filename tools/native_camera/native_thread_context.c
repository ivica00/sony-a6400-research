/* One-shot read-only main-thread context. No register or application writes. */
#define _DEFAULT_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <sys/ptrace.h>
#include <sys/wait.h>
#ifndef PTRACE_GET_THREAD_AREA
#define PTRACE_GET_THREAD_AREA 22
#endif
int main(void) {
    setvbuf(stdout,0,_IONBF,0);
    const int tid=149;
    int status=0,fd=-1,result=0;
    uint32_t tls=0,regs[18]={0}; unsigned char context[16]={0};
    if(ptrace(PTRACE_ATTACH,tid,0,0)) { printf("ATTACH error=%d\n",errno);return 1; }
    if(waitpid(tid,&status,0)!=tid || !WIFSTOPPED(status)) { result=-1;goto done; }
    if(ptrace(PTRACE_GET_THREAD_AREA,tid,0,&tls)) { result=-2;goto done; }
    if(ptrace(PTRACE_GETREGS,tid,0,regs)) { result=-3;goto done; }
    if(tls<0x144c0 || tls>=0x5f000000) { result=-4;goto done; }
    fd=open("/proc/149/mem",O_RDONLY);
    if(fd<0 || pread(fd,context,sizeof(context),tls-0x4c0+0x60)!=(int)sizeof(context)) { result=-5;goto done; }
    printf("CONTEXT tid=%d tls=%08x pc=%08x sp=%08x cpsr=%08x address=%08x data=",tid,tls,regs[15],regs[13],regs[16],tls-0x4c0+0x60);
    for(unsigned i=0;i<sizeof(context);i++) printf("%02x",context[i]);
    printf("\n");
done:
    if(fd>=0)close(fd);
    int saved=errno;
    if(ptrace(PTRACE_DETACH,tid,0,0)) { printf("DETACH error=%d\n",errno);return 2; }
    printf("END result=%d errno=%d\n",result,result?saved:0);
    return result?3:0;
}
