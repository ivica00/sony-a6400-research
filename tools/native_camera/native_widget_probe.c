/* Finite read-only observer of verified WidgetSystem mouse records. */
#define _DEFAULT_SOURCE
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <sys/ptrace.h>
#include <sys/wait.h>
#include <sys/syscall.h>
#include <time.h>
static volatile sig_atomic_t stopped;
struct widget_record { uint32_t object,parent,depth; unsigned char data[48]; };
static struct widget_record widgets[1024];
static unsigned widget_count;
static int read_at(int fd,uint32_t address,void *out,unsigned size) {
    if(address<0x15000 || address>0x5f000000-size) return -1;
    return pread(fd,out,size,address)==(int)size?0:-1;
}
static int word(int fd,uint32_t address,uint32_t *out) {
    return read_at(fd,address,out,4);
}
static uint32_t field(const unsigned char *data,unsigned offset) {
    uint32_t value; memcpy(&value,data+offset,4); return value;
}
static int walk(int fd,uint32_t root,uint32_t parent,unsigned depth) {
    uint32_t link;
    if(depth>48 || word(fd,root+0x10,&link)) return -10;
    link &= ~3u;
    while(link) {
        if(link<8 || widget_count>=1024) return -11;
        uint32_t object=link-8;
        for(unsigned j=0;j<widget_count;j++) if(widgets[j].object==object) return -12;
        struct widget_record *record=&widgets[widget_count++];
        record->object=object; record->parent=parent; record->depth=depth;
        if(read_at(fd,object,record->data,48)) return -13;
        if(field(record->data,4)!=0x7063b28 || field(record->data,0x1c)!=object)
            return -14;
        int rc=walk(fd,object+4,object,depth+1);
        if(rc) return rc;
        link=field(record->data,8);
        if(link&3) return -15;
    }
    return 0;
}
static int tree(int fd) {
    uint32_t container=0x956f0+0x484,node,owner,layer,next;
    widget_count=0;
    if(word(fd,container+0xc,&node)) return -20;
    unsigned layers=0;
    while(node!=container+0x10) {
        if(++layers>64 || word(fd,node,&layer) || word(fd,node+4,&owner) ||
           word(fd,node+0xc,&next) || owner!=container) return -21;
        int rc=walk(fd,layer+0x18,layer,0);
        if(rc) return rc;
        node=next;
    }
    return 0;
}
static void stop(int s) { (void)s; stopped=1; }
static unsigned now(void) {
    struct timespec t;
    if(syscall(SYS_clock_gettime,CLOCK_MONOTONIC,&t)) return 0;
    return (unsigned)t.tv_sec*1000+t.tv_nsec/1000000;
}
static int sample(unsigned index) {
    static unsigned char previous[80];
    unsigned char records[80]; uint32_t pointer=0; int status,rc=-1,fd=-1;
    unsigned begin=now(); int tree_rc=0,tree_read=0;
    if(ptrace(PTRACE_ATTACH,149,0,0)) return -2;
    pid_t waited;
    do { waited=waitpid(149,&status,0); } while(waited<0 && errno==EINTR);
    if(waited!=149 || !WIFSTOPPED(status)) goto done;
    fd=open("/proc/149/mem",O_RDONLY);
    if(fd<0 || pread(fd,&pointer,4,0x7108058)!=4 || pointer!=0x956f0) goto done;
    if(pread(fd,records,80,pointer+0x4a8)!=80) goto done;
    if(index%10==0 || memcmp(previous,records,80)) {
        tree_read=1; tree_rc=tree(fd);
    }
    rc=0;
done:
    if(fd>=0) close(fd);
    if(ptrace(PTRACE_DETACH,149,0,0)) return -3;
    if(rc) return rc;
    if(tree_read) {
        static uint32_t previous_hash; uint32_t hash=2166136261u;
        const unsigned char *bytes=(const unsigned char *)widgets;
        for(unsigned j=0;j<widget_count*sizeof(widgets[0]);j++) hash=(hash^bytes[j])*16777619u;
        if(index==0 || hash!=previous_hash || tree_rc) {
            printf("TREE sample=%u ms=%u result=%d count=%u read_ms=%u\n",index,now(),tree_rc,widget_count,now()-begin);
            for(unsigned j=0;j<widget_count;j++) {
                struct widget_record *r=&widgets[j];
                printf("widget object=%08x parent=%08x depth=%u data=",r->object,r->parent,r->depth);
                for(unsigned k=0;k<48;k++) printf("%02x",r->data[k]);
                printf("\n");
            }
            previous_hash=hash;
        }
    }
    if(index==0 || memcmp(previous,records,80)) {
        printf("change sample=%u ms=%u read_ms=%u data=",index,now(),now()-begin);
        for(unsigned j=0;j<80;j++) printf("%02x",records[j]);
        printf("\n"); memcpy(previous,records,80);
    }
    if(index%100==0) printf("heartbeat sample=%u ms=%u read_ms=%u\n",index,now(),now()-begin);
    return 0;
}
int main(void) {
    char comm[32]={0}; FILE *f=fopen("/proc/149/comm","r");
    if(!f || !fgets(comm,sizeof(comm),f) || strcmp(comm,"im.elf\n")) return 2;
    fclose(f);
    int lock=open("/tmp_bt/native_widget_probe.lock",O_WRONLY|O_CREAT,0600);
    if(lock<0) return 3;
    struct flock lease={0}; lease.l_type=F_WRLCK; lease.l_whence=SEEK_SET;
    if(fcntl(lock,F_SETLK,&lease)) return 4;
    signal(SIGTERM,stop); signal(SIGINT,stop); signal(SIGHUP,SIG_IGN); setsid();
    setvbuf(stdout,0,_IONBF,0);
    printf("NATIVE_WIDGET_PROBE_V1 pid=%d ms=%u read_only=1 atomic=0 samples=1800 interval_us=100000 max_widgets=1024\n",getpid(),now());
    unsigned i; int rc=0;
    for(i=0;i<1800 && !stopped;i++) {
        if(access("/tmp_bt/native_widget_probe.stop",F_OK)==0) break;
        rc=sample(i); if(rc) break;
        usleep(100000);
    }
    printf("END samples=%u ms=%u result=%d\n",i,now(),rc);
    close(lock); return rc?5:0;
}
