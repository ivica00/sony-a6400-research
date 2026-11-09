#include "uvc_ptp_stop_attest.h"
extern unsigned long __copy_from_user(void *,const void *,unsigned long);
extern unsigned long __copy_to_user(void *,const void *,unsigned long);
extern void *filp_open(const char *,int,int);
extern int filp_close(void *,void *);
extern long vfs_read(void *,char *,unsigned long,long long *);

static int field(const char *buffer,unsigned int length,const char *key,unsigned int wanted)
{
    unsigned int i=0,found=0;
    while(i<length) {
        unsigned int start=i,j=0,value=0,digits=0;
        while(i<length && buffer[i]!='\n')i++;
        if(i==length)break; /* Ignore an incomplete final line. */
        while(key[j] && start+j<i && buffer[start+j]==key[j])j++;
        if(!key[j]) {
            start+=j;
            while(start<i && (buffer[start]==' '||buffer[start]=='\t'))start++;
            while(start<i && buffer[start]>='0' && buffer[start]<='9') {
                unsigned int digit=(unsigned int)(buffer[start++]-'0');
                if(value>(0x7fffffffu-digit)/10u)return -116;
                value=value*10u+digit;digits++;
            }
            if(!digits || start!=i || value!=wanted || found++)return -116;
        }
        i++;
    }
    return found==1 ? 0:-116;
}

static int member(unsigned int tid,unsigned int expected_count)
{
    char path[64]="/proc/149/task/",digits[10],buffer[384];
    unsigned int count=0,pos=15,n=tid,sp,*limit,old;
    long long offset=0;
    long size;
    void *file;
    int ret,closed;
    do {digits[count++]=(char)('0'+n%10u);n/=10u;}while(n);
    while(count)path[pos++]=digits[--count];
    path[pos++]='/';path[pos++]='s';path[pos++]='t';path[pos++]='a';
    path[pos++]='t';path[pos++]='u';path[pos++]='s';path[pos]=0;
    file=filp_open(path,0,0);
    if((unsigned long)file>=0xfffff001u)return (int)(long)file;
    if(!file)return -116;
    __asm__ volatile("mov %0, sp":"=r"(sp));
    limit=(unsigned int *)((sp&~0x1fffu)+8);old=*limit;*limit=0xffffffffu;
    size=vfs_read(file,buffer,sizeof(buffer),&offset);
    *limit=old;
    closed=filp_close(file,0);
    if(size<0)return (int)size;
    if(closed)return closed;
    if(size>(long)sizeof(buffer))return -116;
    ret=field(buffer,(unsigned int)size,"Tgid:",149);
    if(!ret)ret=field(buffer,(unsigned int)size,"Pid:",tid);
    return ret ? ret:field(buffer,(unsigned int)size,"Threads:",expected_count);
}

static __attribute__((noinline)) long snapshot(long (*native_ptrace)(long,long,unsigned long,unsigned long),
                     long command,unsigned int tid,void *output)
{
    unsigned int sp,old;
    volatile unsigned int *limit;
    long result;
    __asm__ volatile("mov %0, sp":"=r"(sp));
    limit=(volatile unsigned int *)((sp&~0x1fffu)+8);old=*limit;*limit=0xffffffffu;
    __asm__ volatile("":::"memory");
    result=native_ptrace(command,(long)tid,0,(unsigned long)output);
    __asm__ volatile("":::"memory");
    *limit=old;
    return result;
}

long a6400_uvc_with_stops(unsigned long argument,a6400_stop_consumer consumer,void *context)
{
    struct a6400_stop_request request;
    struct a6400_verified_stops scope;
    unsigned int tids[512],registers[18]={0},info[32]={0},i,j,leader=0;
    long ret;
    const volatile unsigned int *entry=(const volatile unsigned int *)0x6013f324u;
    long (*native_ptrace)(long,long,unsigned long,unsigned long)=
        (long (*)(long,long,unsigned long,unsigned long))0x6013f324u;
    if(!argument || __copy_from_user(&request,(const void *)argument,sizeof(request)))return -14;
    request.completed=0;request.error=0;
    if(request.version!=2 || request.owner!=149 || !request.count || request.count>512 ||
       !request.tids || (request.tids&3u) || request.registers || request.siginfo ||
       request.tids>0xffffffffu-request.count*4u) {
        ret=-22;goto done;
    }
    /* Exact selected entry instructions; not a complete live-kernel identity. */
    if(entry[0]!=0xe1a0c00du || entry[1]!=0xe92dd9f0u){ret=-116;goto done;}
    if(__copy_from_user(tids,(const void *)request.tids,request.count*4u)){ret=-14;goto done;}
    for(i=0;i<request.count;i++) {
        if(!tids[i] || tids[i]>0x7fffffffu){ret=-22;goto done;}
        if(tids[i]==149)leader=1;
        for(j=0;j<i;j++)if(tids[j]==tids[i]){ret=-22;goto done;}
    }
    if(!leader){ret=-22;goto done;}
    for(i=0;i<request.count;i++) {
        ret=member(tids[i],request.count);if(ret)goto done;
        ret=snapshot(native_ptrace,12,tids[i],registers);if(ret)goto done;
        if((registers[16]&31u)!=16u){ret=-116;goto done;}
        ret=snapshot(native_ptrace,0x4202,tids[i],info);if(ret)goto done;
        if(info[0]!=19u){ret=-116;goto done;}
        request.completed++;
    }
    scope.owner=149;scope.count=request.count;scope.tids=tids;
    ret=consumer ? consumer(context,&scope):0;
done:
    request.error=(int)ret;
    if(__copy_to_user((void *)argument,&request,sizeof(request)))return -14;
    return ret;
}

long a6400_uvc_attest_stops(unsigned long argument)
{
    return a6400_uvc_with_stops(argument,0,0);
}
