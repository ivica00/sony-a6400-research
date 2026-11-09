/* Bounded read-only PID149 CPU-consistent subset, requested by address ranges. */
#define _DEFAULT_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <sys/ptrace.h>
#include <sys/wait.h>
#include <sys/statvfs.h>
#include "native_freeze.h"
struct span { uint32_t address,size,offset; };
static struct span spans[64];
static unsigned char data[128*1024];
int main(void) {
    setvbuf(stdout,0,_IONBF,0);
    uint32_t request[4],pair[2],used=0;int result=0,fd=-1;
    FILE *file=fopen("/setting/native_bounded_snapshot.req","rb");
    if(!file || fread(request,1,sizeof(request),file)!=sizeof(request))return 1;
    if(request[0]!=0x52444d41 || request[1]!=1 || !request[2] || request[2]>64 || request[3])return 2;
    for(unsigned i=0;i<request[2];i++) {
        if(fread(pair,1,8,file)!=8 || !pair[1] || pair[1]>0x186bc || pair[0]<0x14000 ||
           pair[0]>0x5f000000-pair[1] || used>sizeof(data)-pair[1])return 3;
        spans[i]=(struct span){pair[0],pair[1],used};used+=pair[1];
    }
    if(fgetc(file)!=EOF || ferror(file))return 4;
    fclose(file);
    unsigned required=16+request[2]*sizeof(spans[0])+used;
    struct statvfs space;
    if(statvfs("/tmp_bt",&space) || (uint64_t)space.f_bavail*space.f_frsize<required+32768u)return 5;
    result=freeze_process();if(result){printf("CAPTURE result=%d\n",result);return 6;}
    fd=open("/proc/149/mem",O_RDONLY);if(fd<0)result=-1;
    for(unsigned i=0;!result && i<request[2];i++)
        if(pread(fd,data+spans[i].offset,spans[i].size,spans[i].address)!=(int)spans[i].size)result=-2;
    if(fd>=0)close(fd);
    if(freeze_resume())result=-3;
    printf("CAPTURE result=%d records=%u raw=%u\n",result,request[2],used);
    if(result)return 7;
    uint32_t header[4]={0x534c4159,2,request[2],used};
    file=fopen("/tmp_bt/native_bounded_snapshot.bin","wb");if(!file)return 8;
    result=(fwrite(header,1,sizeof(header),file)!=sizeof(header) ||
            fwrite(spans,sizeof(spans[0]),request[2],file)!=request[2] ||
            fwrite(data,1,used,file)!=used || fflush(file) || fsync(fileno(file)));
    if(fclose(file))result=1;
    printf("END result=%d bytes=%u\n",result,required);return result?9:0;
}
