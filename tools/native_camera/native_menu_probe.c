/* Read-only, finite diagnostic sampler. No code writes or key injection. */
#define _DEFAULT_SOURCE
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/ptrace.h>
#include <sys/wait.h>
#include <signal.h>
#include <time.h>
#include <sys/syscall.h>

static volatile sig_atomic_t stopped;
static void stop(int sig) { (void)sig; stopped=1; }
struct candidate { uint32_t address,mode,menu_data,child_vtable,kind; };
static struct { uint32_t address; char name[64]; } targets[16];
static unsigned target_count;
static uint32_t minimum_target=UINT32_MAX,maximum_target;
static struct candidate previous[32];
static unsigned previous_count=99,logged;

static uint32_t timestamp(void) {
    struct timespec value;
    if(syscall(SYS_clock_gettime,CLOCK_MONOTONIC,&value)) return 0;
    return (uint32_t)value.tv_sec*1000+(uint32_t)value.tv_nsec/1000000;
}

static int probe(unsigned sample) {
    uint32_t began=timestamp();
    char comm[32]={0},line[512];
    FILE *f=fopen("/proc/149/comm","r");
    if(!f || !fgets(comm,sizeof(comm),f)) { if(f) fclose(f); return -1; }
    fclose(f);
    if(strcmp(comm,"im.elf\n")) return -1;
    struct { uint32_t start,end; } ranges[12];
    unsigned range_count=0,total=0;
    f=fopen("/proc/149/maps","r"); if(!f) return -1;
    while(fgets(line,sizeof(line),f)) {
        char *tail; uint32_t start=strtoul(line,&tail,16);
        if(*tail!='-') continue;
        uint32_t end=strtoul(tail+1,&tail,16);
        int stream=strstr(tail," rw-s 202e0000 ")!=NULL && strstr(tail,"/dev/stream")!=NULL;
        if((!strstr(tail," rw-p ") && !stream) || end<=start) continue;
        int named=strstr(tail,"[heap]")!=NULL || strstr(tail,"/usr/lib/viewUnified2.so")!=NULL;
        int large_anonymous=strstr(tail," 00:00 0")!=NULL && !strchr(tail,'[') && !strchr(tail,'/')
                            && end-start>2*1024*1024;
        if(!named && !large_anonymous && !stream) continue;
        if(stream && end-start!=32*1024*1024) { fclose(f); return -14; }
        if(range_count>=12 || (!stream && end-start>16*1024*1024) || total+end-start>80*1024*1024) { fclose(f); return -13; }
        ranges[range_count].start=start; ranges[range_count++].end=end; total+=end-start;
    }
    fclose(f); if(!range_count) return -1;
    if(ptrace(PTRACE_ATTACH,149,NULL,NULL)) { printf("sample=%u attach_error=%d\n",sample,errno); return 0; }
    int status; pid_t waited;
    do { waited=waitpid(149,&status,0); } while(waited<0 && errno==EINTR);
    int memory=-1,failed=0;
    struct candidate found[32]; memset(found,0,sizeof(found)); unsigned count=0;
    unsigned char *buffer=NULL;
    if(waited!=149 || !WIFSTOPPED(status)) { failed=1; goto done; }
    memory=open("/proc/149/mem",O_RDONLY);
    buffer=malloc(65536);
    if(memory<0 || !buffer) { failed=1; goto done; }
    if(previous_count>0 && previous_count<=32 && sample%2) {
        for(unsigned i=0;i<previous_count;i++) {
            uint32_t value;
            struct candidate item=previous[i];
            if(pread(memory,&value,4,item.address)!=4 || value!=targets[item.kind].address) continue;
            if(pread(memory,&item.mode,4,item.address+0x180)!=4
                || pread(memory,&item.menu_data,4,item.address+0x1d8)!=4
                || pread(memory,&item.child_vtable,4,item.address+0x228)!=4) continue;
            found[count++]=item;
        }
        if(count) goto done;
    }
    for(unsigned region=0;region<range_count;region++) {
        for(uint32_t address=ranges[region].start;address<ranges[region].end;address+=65536) {
            unsigned size=ranges[region].end-address; if(size>65536) size=65536;
            int n=pread(memory,buffer,size,address);
            if(n<0) { failed=1; break; }
            for(unsigned offset=0;offset+4<=(unsigned)n;offset+=4) {
                uint32_t value; memcpy(&value,buffer+offset,4);
                if(value<minimum_target || value>maximum_target) continue;
                unsigned kind;
                for(kind=0;kind<target_count;kind++) if(value==targets[kind].address) break;
                if(kind==target_count || count>=32) continue;
                uint32_t object=address+offset;
                if(object+0x22c>ranges[region].end) continue;
                struct candidate item={object,0,0,0,kind};
                if(pread(memory,&item.mode,4,object+0x180)!=4
                    || pread(memory,&item.menu_data,4,object+0x1d8)!=4
                    || pread(memory,&item.child_vtable,4,object+0x228)!=4) continue;
                found[count++]=item;
            }
            if(stopped) break;
        }
        if(stopped) break;
    }
done:
    if(memory>=0) close(memory);
    free(buffer);
    if(ptrace(PTRACE_DETACH,149,NULL,NULL)) { printf("DETACH_ERROR=%d\n",errno); return -1; }
    if(failed) { printf("sample=%u scan_error=%d\n",sample,errno); return -1; }
    if(previous_count!=count || memcmp(previous,found,sizeof(found))) {
        printf("sample=%u uptime_ms=%u scan_ms=%u range_bytes=%u candidates=%u atomic=0\n",sample,timestamp(),timestamp()-began,total,count);
        for(unsigned i=0;i<count && logged<300;i++,logged++) {
            printf("class=%s candidate=%08x raw_180=%u raw_1d8=%08x raw_228=%08x\n",
                   targets[found[i].kind].name,found[i].address,found[i].mode,found[i].menu_data,found[i].child_vtable);
        }
        memcpy(previous,found,sizeof(found)); previous_count=count;
    }
    if(sample%6==0) printf("heartbeat sample=%u uptime_ms=%u scan_ms=%u candidates=%u\n",sample,timestamp(),timestamp()-began,count);
    return 0;
}

int main(int argc,char **argv) {
    if(argc!=2 || strcmp(argv[1],"/tmp_bt/native_menu_targets.txt")) return 2;
    FILE *config=fopen(argv[1],"r"); if(!config) return 2;
    char line[128];
    while(fgets(line,sizeof(line),config)) {
        char *tail; uint32_t value=strtoul(line,&tail,16);
        while(*tail==' ') tail++;
        char *nl=strchr(tail,'\n'); if(nl) *nl=0;
        if(target_count>=16 || value<0x155e6000 || value>=0x160ed000 || (value&3)
            || !*tail || strlen(tail)>=64) { fclose(config); return 2; }
        targets[target_count].address=value;
        if(value<minimum_target) minimum_target=value;
        if(value>maximum_target) maximum_target=value;
        strcpy(targets[target_count++].name,tail);
    }
    fclose(config); if(!target_count) return 2;
    int lock=open("/tmp_bt/native_menu_probe.lock",O_WRONLY|O_CREAT,0600);
    if(lock<0) return 3;
    struct flock lease={0}; lease.l_type=F_WRLCK; lease.l_whence=SEEK_SET;
    if(fcntl(lock,F_SETLK,&lease)) { close(lock); return 4; }
    signal(SIGTERM,stop); signal(SIGINT,stop); signal(SIGHUP,SIG_IGN); setsid();
    FILE *pid=fopen("/tmp_bt/native_menu_probe.pid","w");
    if(pid) { fprintf(pid,"%d\n",getpid()); fclose(pid); }
    setvbuf(stdout,NULL,_IONBF,0);
    printf("NATIVE_MENU_PROBE_V2 pid=%d start_ms=%u targets=%u max_samples=144 interval_seconds=5 read_only=1\n",getpid(),timestamp(),target_count);
    unsigned attempted=0; int result=0; const char *reason="completed";
    for(unsigned sample=0;sample<144 && !stopped;sample++) {
        if(access("/tmp_bt/native_menu_probe.stop",F_OK)==0) { reason="stop_marker"; break; }
        attempted++;
        result=probe(sample);
        if(result) { reason="probe_error"; break; }
        for(unsigned tick=0;tick<50 && !stopped;tick++) usleep(100000);
    }
    if(stopped) reason="signal";
    printf("END NATIVE_MENU_PROBE_V2 end_ms=%u attempted=%u reason=%s result=%d\n",timestamp(),attempted,reason,result);
    close(lock); return 0;
}
