/* Read-only observational preflight. Does not stop tasks or certify quiescence.
 * Freestanding ARM Linux: only open/read-directory/stat/write/close/exit calls. */
#include <asm/unistd.h>
#include <asm/stat.h>
#include <asm/fcntl.h>
static unsigned char procbuf[4096],fdbuf[4096],taskbuf[4096];
static unsigned int errors,owners,threads;
static int sc3(int n,unsigned int a,unsigned int b,unsigned int c)
{
    register unsigned int r0 __asm__("r0")=a;
    register unsigned int r1 __asm__("r1")=b;
    register unsigned int r2 __asm__("r2")=c;
    register int r7 __asm__("r7")=n;
    __asm__ volatile("svc 0":"+r"(r0):"r"(r1),"r"(r2),"r"(r7):"memory","cc");
    return (int)r0;
}
static unsigned int len(const char *s){unsigned int n=0;while(s[n])++n;return n;}
static void output(const char *s){unsigned int n=len(s);while(n){int r=sc3(__NR_write,1,(unsigned int)s,n);if(r<=0)return;s+=r;n-=(unsigned int)r;}}
static char *copy(char *p,const char *s){while(*s)*p++=*s++;*p=0;return p;}
static char *number(char *p,unsigned int n){char b[10];unsigned int k=0;do{volatile unsigned int q=(unsigned int)(((unsigned long long)n*0xcccccccdu)>>35);b[k++]=(char)('0'+n-q*10);n=q;}while(n);while(k)*p++=b[--k];*p=0;return p;}
static int numeric(const char *s,unsigned int limit)
{
    unsigned int n=0;if(!*s)return -1;
    for(;*s;++s){unsigned int d=(unsigned int)(*s-'0');if(d>9 || n>(limit-d)/10)return -1;n=n*10+d;}
    return (int)n;
}
static int open_dir(const char *p){return sc3(__NR_open,(unsigned int)p,O_RDONLY|O_DIRECTORY,0);}
static void close_fd(int fd){(void)sc3(__NR_close,(unsigned int)fd,0,0);}
static int entries(int fd,unsigned char *buffer){int n=sc3(__NR_getdents64,(unsigned int)fd,(unsigned int)buffer,4096);if(n<0)++errors;return n;}
static unsigned int record_size(unsigned char *p){return p[16]|((unsigned int)p[17]<<8);}
static int valid_record(unsigned char *p,unsigned int remain)
{
    unsigned int size;if(remain<20)return 0;size=record_size(p);
    if(size<20 || size>remain)return 0;
    for(unsigned int i=19;i<size;++i)if(!p[i])return 1;
    return 0;
}
static void task_inventory(unsigned int pid)
{
    char path[64],line[80];char *p=copy(path,"/proc/");p=number(p,pid);copy(p,"/task");
    int fd=open_dir(path);unsigned int count=0;if(fd<0){++errors;return;}
    for(;;){int n=entries(fd,taskbuf);if(n<=0)break;
        for(unsigned int off=0;off<(unsigned int)n;){unsigned char *e=taskbuf+off;
            if(!valid_record(e,(unsigned int)n-off)){++errors;close_fd(fd);return;}
            int tid=numeric((char *)e+19,0x7fffffffu);
            if(tid>=0){p=copy(line,"TASK pid=");p=number(p,pid);p=copy(p," tid=");p=number(p,(unsigned int)tid);copy(p,"\n");output(line);++threads;
                if(++count>4096){++errors;close_fd(fd);return;}}
            off+=record_size(e);
        }
    }
    close_fd(fd);
}
static void fd_inventory(unsigned int pid)
{
    char path[80],line[100];char *p=copy(path,"/proc/");p=number(p,pid);p=copy(p,"/fd/");char *suffix=p;
    int fd=open_dir(path);unsigned int count=0,found=0;if(fd<0){++errors;return;}
    for(;;){int n=entries(fd,fdbuf);if(n<=0)break;
        for(unsigned int off=0;off<(unsigned int)n;){unsigned char *e=fdbuf+off;
            if(!valid_record(e,(unsigned int)n-off)){++errors;close_fd(fd);return;}
            int id=numeric((char *)e+19,0x7fffffffu);
            if(id>=0){struct stat64 st;number(suffix,(unsigned int)id);
                if(sc3(__NR_stat64,(unsigned int)path,(unsigned int)&st,0)<0)++errors;
                else if((st.st_mode&0170000)==0020000 && st.st_rdev==0xf201u){
                    p=copy(line,"OWNER pid=");p=number(p,pid);p=copy(p," fd=");p=number(p,(unsigned int)id);copy(p," major=242 minor=1\n");output(line);++owners;found=1;}
                if(++count>65536){++errors;close_fd(fd);return;}}
            off+=record_size(e);
        }
    }
    close_fd(fd);if(found)task_inventory(pid);
}
void _start(void)
{
    struct stat64 st;char line[120];unsigned int count=0;int fd;
    output("UVC_OWNER_INVENTORY version=1 observational=1 freeze=0 writes=0\n");
    if(sc3(__NR_stat64,(unsigned int)"/dev/usb/gadgetcore",(unsigned int)&st,0)<0 ||
       (st.st_mode&0170000)!=0020000 || st.st_rdev!=0xf201u){output("END status=node_mismatch\n");sc3(__NR_exit,2,0,0);for(;;){}}
    fd=open_dir("/proc");if(fd<0){output("END status=proc_unavailable\n");sc3(__NR_exit,3,0,0);for(;;){}}
    for(;;){int n=entries(fd,procbuf);if(n<=0)break;
        for(unsigned int off=0;off<(unsigned int)n;){unsigned char *e=procbuf+off;
            if(!valid_record(e,(unsigned int)n-off)){++errors;goto done;}
            int pid=numeric((char *)e+19,0x7fffffffu);if(pid>0){fd_inventory((unsigned int)pid);if(++count>4096){++errors;goto done;}}
            off+=record_size(e);
        }
    }
done:
    close_fd(fd);char *p=copy(line,"END owners=");p=number(p,owners);p=copy(p," threads=");p=number(p,threads);p=copy(p," errors=");p=number(p,errors);copy(p," observational=1\n");output(line);
    sc3(__NR_exit,errors?1:0,0,0);for(;;){}
}
