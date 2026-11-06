/* One-pass read-only ViewSettingMenu scan. Detach after each bounded chunk. */
#define _DEFAULT_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/ptrace.h>
#include <sys/wait.h>

static unsigned char buffer[262144];
static unsigned char found[32][0x1a4];
static uint32_t objects[32];
static unsigned count;
static int scan(uint32_t address,unsigned size) {
    int status,fd=-1,result=-1; pid_t waited;
    if(ptrace(PTRACE_ATTACH,149,0,0)) return -2;
    do { waited=waitpid(149,&status,0); } while(waited<0 && errno==EINTR);
    if(waited!=149 || !WIFSTOPPED(status)) goto done;
    fd=open("/proc/149/mem",O_RDONLY); if(fd<0) goto done;
    if(pread(fd,buffer,size,address)!=(int)size) goto done;
    for(unsigned i=0;i+4<=size;i+=4) {
        uint32_t value; memcpy(&value,buffer+i,4);
        if(value!=0x15ec8270) continue;
        if(count>=32) { result=-4; goto done; }
        objects[count]=address+i;
        if(pread(fd,found[count],sizeof(found[count]),objects[count])!=(int)sizeof(found[count])) goto done;
        count++;
    }
    result=0;
done:
    if(fd>=0) close(fd);
    if(ptrace(PTRACE_DETACH,149,0,0)) return -3;
    return result;
}
int main(void) {
    char line[512],comm[32]={0};
    FILE *f=fopen("/proc/149/comm","r");
    if(!f || !fgets(comm,sizeof(comm),f) || strcmp(comm,"im.elf\n")) return 2;
    fclose(f);
    int lock=open("/tmp_bt/native_viewsetting_scan.lock",O_WRONLY|O_CREAT,0600);
    struct flock lease={0}; lease.l_type=F_WRLCK; lease.l_whence=SEEK_SET;
    if(lock<0 || fcntl(lock,F_SETLK,&lease)) return 3;
    f=fopen("/proc/149/maps","r"); if(!f) return 4;
    unsigned ranges=0,chunks=0,failed=0; uint32_t bytes=0; int result=0;
    setvbuf(stdout,0,_IONBF,0);
    printf("VIEWSETTING_SCAN_V3 pid=%d read_only=1 atomic=0 max_bytes=805306368\n",getpid());
    while(fgets(line,sizeof(line),f)) {
        unsigned start,end; char mode[5]={0};
        if(sscanf(line,"%x-%x %4s",&start,&end,mode)!=3) continue;
        int stream=!strcmp(mode,"rw-s") && strstr(line,"/dev/stream");
        if((strcmp(mode,"rw-p") && !stream) || start<0x14000 || end>0x5f000000 || end<=start ||
           strstr(line,"[stack]")) continue;
        ranges++;
        for(uint32_t address=start;address<end;) {
            unsigned size=end-address;if(size>sizeof(buffer)) size=sizeof(buffer);
            if(bytes>768u*1024*1024-size || chunks>=4096) { result=-5; goto done; }
            result=scan(address,size);chunks++;bytes+=size;
            if(result) { failed++; printf("chunk_error address=%08x size=%u result=%d\n",address,size,result); if(result==-2 || result==-3 || result==-4) goto done; }
            address+=size; usleep(1000);
        }
    }
done:
    fclose(f);
    for(unsigned i=0;i<count;i++) {
        uint32_t provider;memcpy(&provider,found[i]+0x1a0,4);
        printf("candidate object=%08x provider=%08x data=",objects[i],provider);
        for(unsigned j=0;j<sizeof(found[i]);j++) printf("%02x",found[i][j]);
        printf("\n");
    }
    printf("END ranges=%u chunks=%u bytes=%u candidates=%u failed=%u result=%d\n",ranges,chunks,bytes,count,failed,result);
    close(lock);return result || failed?5:0;
}
