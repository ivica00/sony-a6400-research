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
#include <signal.h>

static unsigned char buffer[262144];
static unsigned char found[32][0x380];
static uint32_t objects[32];
static unsigned count;
static unsigned visited;
static int readword(int fd,uint32_t address,uint32_t *out) {
    if(address<0x14000 || address>0x5efffffc) return -1;
    return pread(fd,out,4,address)==4?0:-1;
}
static int menu_walk(int fd,uint32_t root,unsigned depth,uint32_t *menu) {
    uint32_t link;
    if(depth>48 || readword(fd,root+0x10,&link)) return -20;
    link&=~3u;
    while(link) {
        uint32_t object,vt,tree_type,self;
        if(link<8 || ++visited>2048) return -21;
        object=link-8;
        if(readword(fd,object,&vt) || readword(fd,object+4,&tree_type) ||
           readword(fd,object+0x1c,&self) || self!=object || tree_type!=0x7063b28) return -22;
        if(vt==0x15f1f1d0) { *menu=object;return 1; }
        int rc=menu_walk(fd,object+4,depth+1,menu);if(rc) return rc;
        if(readword(fd,object+8,&link) || (link&3)) return -23;
    }
    return 0;
}
static int wait_menu_sample(uint32_t *menu) {
    int status,fd=-1,result=-1;pid_t waited;
    if(ptrace(PTRACE_ATTACH,149,0,0)) return -2;
    do { waited=waitpid(149,&status,0); } while(waited<0 && errno==EINTR);
    if(waited!=149 || !WIFSTOPPED(status)) goto done;
    fd=open("/proc/149/mem",O_RDONLY);if(fd<0) goto done;
    uint32_t system,node,layer,owner,next,container=0x956f0+0x484;
    if(readword(fd,0x7108058,&system) || system!=0x956f0 || readword(fd,container+0xc,&node)) goto done;
    visited=0;result=0;
    for(unsigned layers=0;node!=container+0x10;layers++) {
        if(layers>=64 || readword(fd,node,&layer) || readword(fd,node+4,&owner) ||
           readword(fd,node+0xc,&next) || owner!=container) { result=-24;break; }
        result=menu_walk(fd,layer+0x18,0,menu);if(result) break;
        node=next;
    }
done:
    if(fd>=0) close(fd);
    if(ptrace(PTRACE_DETACH,149,0,0)) return -3;
    return result;
}
struct model { uint32_t address; unsigned char data[64]; };
struct state { unsigned char controller[0x380]; struct model path[8]; unsigned depth; int path_result; };
static struct state current,previous;
static int observe(uint32_t object) {
    int status,fd=-1,result=-1; pid_t waited;
    memset(&current,0,sizeof(current));
    if(ptrace(PTRACE_ATTACH,149,0,0)) return -2;
    do { waited=waitpid(149,&status,0); } while(waited<0 && errno==EINTR);
    if(waited!=149 || !WIFSTOPPED(status)) goto done;
    fd=open("/proc/149/mem",O_RDONLY); if(fd<0) goto done;
    if(pread(fd,current.controller,sizeof(current.controller),object)!=(int)sizeof(current.controller)) goto done;
    uint32_t vt,node;memcpy(&vt,current.controller,4);
    if(vt!=0x15ec8270) { result=-6;goto done; }
    memcpy(&node,current.controller+0x1a0,4);
    for(unsigned depth=0;depth<8 && node;depth++) {
        if(node<0x15000 || node>0x5effffc0) { current.path_result=-10;break; }
        for(unsigned k=0;k<depth;k++) if(current.path[k].address==node) { current.path_result=-11;goto path_done; }
        struct model *m=&current.path[depth];m->address=node;
        if(pread(fd,m->data,64,node)!=64) { current.path_result=-12;break; }
        current.depth=depth+1;
        uint32_t table,array,number,method;int32_t selected;
        memcpy(&table,m->data,4);memcpy(&array,m->data+4,4);memcpy(&number,m->data+8,4);memcpy(&selected,m->data+0x18,4);
        if(table<0x15000 || table>0x5effff0c || pread(fd,&method,4,table+0xf0)!=4) { current.path_result=-13;break; }
        if(method!=0x169262cd) { current.path_result=1;break; }
        if(!array || !number || selected<=0) break;
        if(number>128 || (unsigned)selected>number || array<0x15000 || array>0x5efffe00) { current.path_result=-14;break; }
        if(pread(fd,&node,4,array+4*((unsigned)selected-1))!=4) { current.path_result=-15;break; }
        if(depth==7 && node) current.path_result=2;
    }
path_done:
    result=0;
done:
    if(fd>=0) close(fd);
    if(ptrace(PTRACE_DETACH,149,0,0)) return -3;
    return result;
}
static void hexout(const unsigned char *data,unsigned size) {
    for(unsigned j=0;j<size;j++) printf("%02x",data[j]);
    printf("\n");
}
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
    int lock=open("/tmp_bt/native_menu_controller_probe.lock",O_WRONLY|O_CREAT,0600);
    struct flock lease={0}; lease.l_type=F_WRLCK; lease.l_whence=SEEK_SET;
    if(lock<0 || fcntl(lock,F_SETLK,&lease)) return 3;
    signal(SIGHUP,SIG_IGN);setsid();
    setvbuf(stdout,0,_IONBF,0);
    printf("MENU_CONTROLLER_PROBE_V2 pid=%d read_only=1 atomic=0 wait_menu_samples=600 wait_interval_us=500000 max_samples=1800\n",getpid());
    uint32_t menu=0;int menu_seen=0;
    for(unsigned attempt=0;attempt<600;attempt++) {
        if(access("/tmp_bt/native_menu_controller_probe_v2.stop",F_OK)==0) break;
        int rc=wait_menu_sample(&menu);
        if(rc==1) { printf("MENU_DETECTED attempt=%u object=%08x\n",attempt,menu);menu_seen=1;break; }
        if(attempt%20==0 || rc<0) printf("wait_menu attempt=%u result=%d\n",attempt,rc);
        usleep(500000);
    }
    if(!menu_seen) { printf("END reason=menu_not_observed\n");close(lock);return 5; }
    f=fopen("/proc/149/maps","r"); if(!f) return 4;
    unsigned ranges=0,chunks=0,failed=0; uint32_t bytes=0; int result=0;
    setvbuf(stdout,0,_IONBF,0);
    printf("VIEWSETTING_SCAN_V1 pid=%d read_only=1 atomic=0 max_bytes=805306368\n",getpid());
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
    if(!result && !failed) for(unsigned candidate=0;candidate<count;candidate++) {
        uint32_t provider;memcpy(&provider,found[candidate]+0x1a0,4);
        if(provider!=0x160f5cec) continue;
        printf("OBSERVE object=%08x provider=%08x\n",objects[candidate],provider);
        memset(&previous,0,sizeof(previous));
        unsigned sample;
        for(sample=0;sample<1800;sample++) {
            if(access("/tmp_bt/native_menu_controller_probe_v2.stop",F_OK)==0) break;
            if(lseek(STDOUT_FILENO,0,SEEK_CUR)>=8*1024*1024) break;
            int rc=observe(objects[candidate]);
            if(rc) { printf("observer_error sample=%u result=%d\n",sample,rc);break; }
            if(sample==0 || memcmp(&current,&previous,sizeof(current))) {
                printf("STATE sample=%u object=%08x depth=%u path_result=%d data=",sample,objects[candidate],current.depth,current.path_result);
                hexout(current.controller,sizeof(current.controller));
                for(unsigned j=0;j<current.depth;j++) {
                    printf("model depth=%u address=%08x data=",j,current.path[j].address);
                    hexout(current.path[j].data,64);
                }
                memcpy(&previous,&current,sizeof(current));
            }
            if(sample%100==0) printf("heartbeat sample=%u\n",sample);
            usleep(100000);
        }
        printf("OBSERVE_END samples=%u\n",sample);break;
    }
    close(lock);return result || failed?5:0;
}
