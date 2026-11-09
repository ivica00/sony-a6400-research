/* Bounded read-only thread/stack candidates; NOT a call-stack unwinder. */
#define _DEFAULT_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/ptrace.h>
#include <sys/wait.h>
#include "native_freeze.h"
int main(void) {
    int result=freeze_process();if(result)return 5;
    int fd=open("/proc/149/mem",O_RDONLY);unsigned targets=0;
    if(fd<0)result=-1;
    else for(unsigned i=0;i<freeze_count;i++) {
        char path[80],name[32]={0};uint32_t regs[18]={0};
        snprintf(path,sizeof(path),"/proc/149/task/%d/comm",freeze_tids[i]);
        FILE *f=fopen(path,"r");if(!f)continue;
        if(!fgets(name,sizeof(name),f)){fclose(f);continue;}fclose(f);
        name[strcspn(name,"\n")]=0;
        if(strcmp(name,"im.elf") && strcmp(name,"Appframework") && strncmp(name,"THREAD_INFRA0",13) && strncmp(name,"uxengine_res",12) && strncmp(name,"ObjRenderer",11))continue;
        if(++targets>16){result=-2;break;}
        if(ptrace(PTRACE_GETREGS,freeze_tids[i],0,regs)){result=-3;break;}
        uint32_t stack[1024];int bytes=-1;
        if(regs[13]>=0x14000 && regs[13]<=0x5efff000)bytes=pread(fd,stack,sizeof(stack),regs[13]);
        printf("THREAD tid=%d name=%s pc=%08x lr=%08x sp=%08x stack_bytes=%d\n",freeze_tids[i],name,regs[15],regs[14],regs[13],bytes);
        unsigned matches=0;
        for(int j=0;j<bytes/4 && matches<12;j++) {
            uint32_t pc=stack[j]&~1u;
            if(pc>=0x6308d00 && pc<0x630b400){printf("STACK_CANDIDATE tid=%d offset=%x value=%08x unwound=0\n",freeze_tids[i],j*4,stack[j]);matches++;}
        }
    }
    if(fd>=0)close(fd);
    if(freeze_resume())result=-99;
    printf("END result=%d targets=%u writes=0\n",result,targets);fflush(stdout);return result?5:0;
}
