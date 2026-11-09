/* Read-only native filesystem table observer; output confined to fresh RAM files.
 * No ptrace, function calls into Sony, module, mount or SD write. */
#define _DEFAULT_SOURCE
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/stat.h>

static const unsigned char prefix[16]={0x2d,0xe9,0xf0,0x4f,0x89,0x46,0xdf,0xf8,0x20,0x18,0xa9,0xb0,0x04,0x46,0x01,0x20};
static unsigned int find_base(void)
{
    char line[512],permissions[8];unsigned int start,end,offset;
    FILE *maps=fopen("/proc/149/maps","r");
    if(!maps)return 0;
    while(fgets(line,sizeof(line),maps))
        if(strstr(line,"/usr/lib/libInfraFsys.so") &&
           sscanf(line,"%x-%x %7s %x",&start,&end,permissions,&offset)==4 &&
           offset==0 && strchr(permissions,'x')) {fclose(maps);return start;}
    fclose(maps);return 0;
}
static int sample(FILE *out,unsigned int second)
{
    unsigned int base=find_base(),table[26],table_address,status_address;unsigned short state;unsigned char code[16];
    int fd=open("/proc/149/mem",O_RDONLY);
    if(fd<0 || !base){if(fd>=0)close(fd);fprintf(out,"SAMPLE sec=%u unavailable errno=%d\n",second,errno);return -1;}
    if(pread(fd,code,sizeof(code),base+0x1bf84)!=sizeof(code) || memcmp(code,prefix,sizeof(code)) ||
       pread(fd,&table_address,4,base+0x6bff0)!=4 ||
       pread(fd,&status_address,4,base+0x6c034)!=4 || !table_address || !status_address ||
       pread(fd,&state,sizeof(state),status_address)!=sizeof(state) ||
       pread(fd,table,sizeof(table),table_address)!=sizeof(table)) {
        close(fd);fprintf(out,"SAMPLE sec=%u rejected_identity_or_read\n",second);return -1;
    }
    fprintf(out,"SAMPLE sec=%u base=%08x status=%04x table=%08x state=%08x",second,base,state,table_address,status_address);
    for(unsigned int i=0;i<26;i++)if(table[i]) {
        unsigned char header[16];ssize_t n=pread(fd,header,sizeof(header),table[i]);
        fprintf(out," drive=%c ptr=%08x header_read=%ld",'A'+i,table[i],(long)n);
        if(n==sizeof(header)) {fprintf(out," header=");for(unsigned int j=0;j<16;j++)fprintf(out,"%02x",header[j]);}
        unsigned char device[128];ssize_t dn=pread(fd,device,sizeof(device),table[i]+0x954);
        fprintf(out," device_read=%ld",(long)dn);
        if(dn>0) {
            unsigned char *end=memchr(device,0,(size_t)dn);
            if(end) {fprintf(out," device_hex=");for(unsigned char *p=device;p<end;p++)fprintf(out,"%02x",*p);}
            else fprintf(out," device_unterminated=1");
        }
    }
    fputc('\n',out);close(fd);return 0;
}
int main(int argc,char **argv)
{
    if(argc!=2 || strncmp(argv[1],"/tmp_bt/",8) || strstr(argv[1],"..") || strlen(argv[1])>180)return 2;
    int fd=open(argv[1],O_RDWR|O_CREAT|O_EXCL,0600);
    if(fd<0)return 3;
    FILE *out=fdopen(fd,"w+");if(!out){close(fd);return 4;}
    setvbuf(out,0,_IONBF,0);
    fprintf(out,"FSYS_OBSERVER READY pid=%ld duration=40 interval=2 no_ptrace no_native_calls\n",(long)getpid());
    for(unsigned int sec=0;sec<=40;sec+=2){sample(out,sec);if(sec<40)sleep(2);}
    fprintf(out,"FSYS_OBSERVER COMPLETE\n");fflush(out);
    /* Keep the original inode open across any RAM pathname unlink on switch. */
    char receipt[200];snprintf(receipt,sizeof(receipt),"%s.receipt",argv[1]);
    int target=open(receipt,O_WRONLY|O_CREAT|O_EXCL,0600);
    if(target<0){fclose(out);return 5;}
    if(fseek(out,0,SEEK_SET)){close(target);fclose(out);return 6;}
    char data[1024];size_t n;unsigned int total=0;
    while((n=fread(data,1,sizeof(data),out))) {
        total+=(unsigned int)n;if(total>32768){close(target);fclose(out);return 7;}
        for(size_t k=0;k<n;) {ssize_t written=write(target,data+k,n-k);if(written<0 && errno==EINTR)continue;if(written<=0){close(target);fclose(out);return 8;}k+=(size_t)written;}
    }
    int result=ferror(out)?9:0;close(target);fclose(out);return result;
}
