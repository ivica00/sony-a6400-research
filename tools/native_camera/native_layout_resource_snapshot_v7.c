/* Finite read-only active-menu registry and widget snapshot. */
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
struct record { uint32_t address,size,offset; };
static struct record records[2048];
static unsigned char bytes[2*1024*1024];
static unsigned used,record_count;
static unsigned char *capture(int fd,uint32_t address,unsigned size) {
    if(address<0x14000 || address>0x5f000000-size || !size || size>0x186bc) return 0;
    for(unsigned i=0;i<record_count;i++)
        if(records[i].address==address && records[i].size>=size) return bytes+records[i].offset;
    if(record_count>=2048 || used>512u*1024-size) return 0;
    if(pread(fd,bytes+used,size,address)!=(int)size) return 0;
    records[record_count++]=(struct record){address,size,used};
    unsigned char *result=bytes+used;used+=size;return result;
}
static uint32_t field(const unsigned char *data,unsigned offset) {
    uint32_t value;memcpy(&value,data+offset,4);return value;
}
static uint32_t seen_views[128];
static unsigned seen_view_count;
static int capture_registry(int fd,uint32_t registry,uint32_t filter,unsigned depth);
static int capture_view(int fd,uint32_t view,unsigned depth) {
    if(depth>8 || seen_view_count>=128) return -29;
    for(unsigned i=0;i<seen_view_count;i++) if(seen_views[i]==view) return 0;
    seen_views[seen_view_count++]=view;
    unsigned char *data=capture(fd,view,0x1a4);if(!data) return -30;
    uint32_t table=field(data,0),resource=field(data,0x18);
    if(!capture(fd,table,0x40)) return -31;
    unsigned char *provider=capture(fd,resource,128);if(!provider) return -32;
    unsigned char *methods=capture(fd,field(provider,0),0x90);if(!methods) return -33;
    if(!capture(fd,field(methods,0x8c)&~1u,512)) return -34;
    unsigned total=0;
    for(unsigned bucket=0;bucket<16;bucket++) {
        uint32_t node=field(data,0x1c+4*bucket);
        unsigned chain=0;
        while(node) {
            if(++chain>512 || ++total>1024) return -35;
            unsigned char *entry=capture(fd,node,32);if(!entry) return -36;
            if((field(entry,8)&15)!=bucket) return -37;
            uint32_t widget=field(entry,0x10),vt;
            if(widget) {
                if(readword(fd,widget,&vt)) return -38;
                unsigned size=vt==0x15f1f1d0?0x186bc:(vt==0x705ff60?0x18c:160);
                unsigned char *state=capture(fd,widget,size);if(!state || field(state,0)!=vt) return -39;
                if(vt==0x705ff60) {
                    int rc=capture_registry(fd,widget+0x14c,field(state,0x13c),depth+1);
                    if(rc) return rc;
                }
            }
            node=field(entry,12);
        }
    }
    return 0;
}
static int capture_registry(int fd,uint32_t registry,uint32_t filter,unsigned depth) {
    unsigned char *root=capture(fd,registry,64);if(!root) return -60;
    unsigned total=0,matched=0;
    for(unsigned bucket=0;bucket<16;bucket++) {
        uint32_t node=field(root,4*bucket);unsigned chain=0;
        while(node) {
            if(++chain>128 || ++total>256) return -61;
            unsigned char *entry=capture(fd,node,0x60);if(!entry) return -62;
            if((field(entry,8)&15)!=bucket) return -63;
            if(field(entry,8)==filter) {
                matched++;unsigned views=0;
                for(unsigned vb=0;vb<16;vb++) {
                    uint32_t view=field(entry,0x14+4*vb);unsigned vc=0;
                    while(view) {
                        if(++vc>64 || ++views>128) return -64;
                        unsigned char *v=capture(fd,view,0x1a4);if(!v) return -65;
                        if((field(v,8)&15)!=vb) return -66;
                        int rc=capture_view(fd,view,depth);if(rc) return rc;
                        view=field(v,12);
                    }
                }
                if(!views) return -67;
            }
            node=field(entry,12);
        }
    }
    return matched==1?0:-68;
}
static int capture_model(int fd,uint32_t node) {
    for(unsigned depth=0;depth<6;depth++) {
        unsigned char *model=capture(fd,node,64);if(!model)return -110;
        if(field(model,0)!=0x16c183e8)return -111;
        uint32_t count=field(model,8),selected=field(model,0x18);
        if(count>128)return -112;
        if(!count)return 0;
        unsigned char *array=capture(fd,field(model,4),count*4);if(!array)return -113;
        for(unsigned i=0;i<count;i++)if(!capture(fd,field(array,i*4),64))return -114;
        if(selected<1 || selected>count)return -115;
        node=field(array,(selected-1)*4);
    }
    return -116;
}
static int capture_resource_list(int fd,uint32_t owner,uint32_t active) {
    unsigned char *root=capture(fd,owner+0x4c,8);if(!root)return -120;
    uint32_t node=field(root,0),previous=0,last=field(root,4);
    unsigned count=0,nonzero=0,present=0;
    while(node) {
        if(node<0x14008 || ++count>768)return -121;
        unsigned char *chunk=capture(fd,node-8,64);if(!chunk)return -122;
        unsigned char *entry=chunk+8;
        if(field(entry,4)!=previous)return -123;
        uint32_t payload=field(entry,8);
        unsigned char *resource=capture(fd,payload,64);if(!resource)return -124;
        /* Original resource property read: resource+0x10 -> blob header.
           Preserve the prefix in the SAME freeze, never later USB heap bytes. */
        uint32_t blob=field(resource,0x10);
        if(blob && !capture(fd,blob,64))return -127;
        uint16_t references;memcpy(&references,resource+0xc,2);
        if(references)nonzero++;
        if(payload==active)present++;
        uint32_t size=field(chunk,4);
        if((size&4) && !(size&2) && (size&~7u)>=16 && (size&~7u)<0x100000) {
            unsigned char *heap=capture(fd,(node-8)&0xfff00000u,16);
            if(heap && !capture(fd,field(heap,0),0x450))return -125;
        }
        previous=node;node=field(entry,0);
    }
    if(previous!=last)return -126;
    printf("RESOURCE_LIST nodes=%u nonzero_references=%u active_present=%u\n",count,nonzero,present);
    return 0;
}
/* Original malloc fastbins: arena+8+4*bin. Same CPU freeze; no heap writes. */
static int capture_fastbins(int fd,uint32_t preferred) {
    uint32_t arenas[32],seen[512];unsigned arena_count=0,total=0;
    if(preferred)arenas[arena_count++]=preferred;
    unsigned existing=record_count;
    for(unsigned i=0;i<existing;i++) if(records[i].size==0x450) {
        uint32_t arena=records[i].address;
        unsigned j;for(j=0;j<arena_count;j++)if(arenas[j]==arena)break;
        if(j==arena_count){if(arena_count>=32)return -140;arenas[arena_count++]=arena;}
    }
    for(unsigned a=0;a<arena_count;a++) {
        unsigned char *state=capture(fd,arenas[a],0x450);if(!state)return -141;
        unsigned nodes=0;
        for(unsigned bin=0;bin<10;bin++) {
            uint32_t chunk=field(state,8+4*bin);unsigned chain=0;
            while(chunk) {
                if(chain>=16 || total>=384) {
                    printf("FASTBIN_PREFIX arena=%08x bin=%u nodes=%u next=%08x truncated=1\n",arenas[a],bin,chain,chunk);
                    break;
                }
                if(chunk&7)return -142;
                chain++;
                for(unsigned j=0;j<total;j++)if(seen[j]==chunk)return -143;
                seen[total++]=chunk;nodes++;
                unsigned char *header=capture(fd,chunk,16);if(!header)return -144;
                unsigned size=field(header,4)&~7u;
                if(size!=(bin+2)*8 || size>0x100)return -145;
                uint32_t next=field(header,8);
                if(!capture(fd,chunk,size+8))return -146;
                chunk=next;
            }
        }
        printf("FASTBINS arena=%08x nodes=%u\n",arenas[a],nodes);
    }
    printf("FASTBINS_END arenas=%u nodes=%u prefix_only=1 result=0\n",arena_count,total);
    return arena_count?0:-147;
}
static int capture_libc_data(int fd) {
    /* Original libc free (0x431c9d0) read 0x43b8230. Capture exactly the libc rw-p
       data page and following anonymous bss mapping, only if /proc/149/maps still
       reports those exact mappings (no assumed layout). */
    FILE *maps=fopen("/proc/149/maps","r");if(!maps)return -130;
    char line[256];int data=0,bss=0;
    while(fgets(line,sizeof(line),maps)) {
        if(!strncmp(line,"043b7000-043b8000 rw-p ",23) && strstr(line,"libc-2.11.2.so"))data=1;
        if(!strncmp(line,"043b8000-043bb000 rw-p ",23) && strstr(line,"00:00 0"))bss=1;
    }
    fclose(maps);
    if(!data||!bss)return -131;
    if(!capture(fd,0x43b7000,0x1000)||!capture(fd,0x43b8000,0x3000))return -132;
    printf("LIBC_DATA data=043b7000/1000 bss=043b8000/3000\n");
    return 0;
}static int snapshot(uint32_t menu) {
    int fd=-1,result=-1;
    int barrier=freeze_process();if(barrier)return barrier;
    fd=open("/proc/149/mem",O_RDONLY);if(fd<0) goto done;
    unsigned char *storage=capture(fd,0x7107f34,4);if(!storage) goto done;
    uint32_t registry=field(storage,0);
    unsigned char *root=capture(fd,registry,64);if(!root) goto done;
    unsigned total=0,matched=0;
    for(unsigned bucket=0;bucket<16;bucket++) {
        uint32_t node=field(root,4*bucket);unsigned chain=0;
        while(node) {
            if(++chain>128 || ++total>256) { result=-40;goto done; }
            unsigned char *entry=capture(fd,node,0x60);if(!entry) { result=-41;goto done; }
            if((field(entry,8)&15)!=bucket) { result=-42;goto done; }
            if(field(entry,8)==0xaadca2c7) {
                matched++;unsigned views=0;
                for(unsigned vb=0;vb<16;vb++) {
                    uint32_t view=field(entry,0x14+4*vb);unsigned vc=0;
                    while(view) {
                        if(++vc>64 || ++views>128) { result=-43;goto done; }
                        unsigned char *v=capture(fd,view,0x1a4);if(!v) { result=-44;goto done; }
                        if((field(v,8)&15)!=vb) { result=-45;goto done; }
                        result=capture_view(fd,view,0);if(result) goto done;
                        view=field(v,12);
                    }
                }
                if(!views) { result=-46;goto done; }
            }
            node=field(entry,12);
        }
    }
    if(matched!=1) { result=-47;goto done; }
    unsigned char *state=capture(fd,menu,0x186bc);
    if(!state || field(state,0)!=0x15f1f1d0 || field(state,0x1c)!=menu) { result=-48;goto done; }
    uint32_t reference=field(state,0x127b4);
    unsigned char *resource=capture(fd,reference,0x40);
    if(!resource){result=-80;goto done;}
    uint32_t active_blob=field(resource,0x10);
    if(active_blob && !capture(fd,active_blob,64)){result=-128;goto done;}
    uint16_t references;memcpy(&references,resource+0xc,2);
    uint32_t owner=field(resource,4);
    printf("RESOURCE menu_field=127b4 object=%08x owner=%08x references=%u\n",reference,owner,(unsigned)references);
    unsigned char *manager=capture(fd,owner,0x90);
    if(!manager || !capture(fd,field(manager,0),0x90)){result=-81;goto done;}
    result=capture_resource_list(fd,owner,reference);if(result)goto done;
    result=capture_model(fd,field(state,0x186ac));if(result)goto done;
    uint32_t tls=0;
    if(ptrace(22,149,0,&tls) || tls<0x144c0 || tls>0x5effff00){result=-82;goto done;}
    unsigned char *thread=capture(fd,tls,0x60);
    if(!thread || !capture(fd,tls-0x4c0+0x60,16)){result=-83;goto done;}
    uint32_t arena=field(thread,0x34);
    if(arena && !capture(fd,arena,0x450)){result=-84;goto done;}
    printf("MAIN_TLS value=%08x allocator=%08x\n",tls,arena);
    result=capture_libc_data(fd);if(result)goto done;
    result=capture_fastbins(fd,arena);if(result)goto done;
    result=0;
done:
    if(fd>=0) close(fd);
    if(freeze_resume()) return -99;
    return result;
}
static int preflight(void) {
    int result=freeze_process();if(result)return result;
    int fd=open("/proc/149/mem",O_RDONLY);
    uint32_t tls=0,arena=0;
    if(fd<0)result=-150;
    else if(ptrace(22,149,0,&tls))result=-151;
    else {
        unsigned char *thread=capture(fd,tls,0x60);
        if(!thread)result=-152;
        else {
            arena=field(thread,0x34);
            result=capture_resource_list(fd,0x6c880,0x1a2cace0);
            if(!result && !capture(fd,arena,0x450))result=-153;
            if(!result)result=capture_fastbins(fd,arena);
        }
    }
    if(fd>=0)close(fd);
    if(freeze_resume())result=-99;
    printf("PREFLIGHT result=%d records=%u bytes=%u tls=%08x arena=%08x\n",result,record_count,used,tls,arena);
    if(fflush(stdout) || ferror(stdout))return 5;
    return result?5:0;
}
int main(int argc,char **argv) {
    char comm[32]={0};FILE *f=fopen("/proc/149/comm","r");
    if(!f || !fgets(comm,sizeof(comm),f) || strcmp(comm,"im.elf\n")) return 2;
    fclose(f);
    if(argc==2 && !strcmp(argv[1],"--preflight"))return preflight();
    if(argc!=1)return 2;
    int lock=open("/tmp_bt/native_layout_resource_snapshot_v7.lock",O_WRONLY|O_CREAT,0600);
    struct flock lease={0};lease.l_type=F_WRLCK;lease.l_whence=SEEK_SET;
    if(lock<0 || fcntl(lock,F_SETLK,&lease)) return 3;
    signal(SIGHUP,SIG_IGN);setsid();
    printf("NATIVE_LAYOUT_RESOURCE_SNAPSHOT_V7 pid=%d read_only=1 process_threads_stopped_during_capture=1 dma_atomic=0 max_wait=3600 interval_us=500000 binary=1\n",getpid());fflush(stdout);
    struct statvfs initial_space;
    if(statvfs("/tmp_bt",&initial_space)) { printf("START_ERROR statvfs=%d\n",errno);return 6; }
    printf("SPACE_START blocks=%lu available=%lu frsize=%lu\n",(unsigned long)initial_space.f_blocks,
           (unsigned long)initial_space.f_bavail,(unsigned long)initial_space.f_frsize);fflush(stdout);
    int result=-50;uint32_t menu=0;
    for(unsigned i=0;i<3600;i++) {
        if(access("/tmp_bt/native_layout_resource_snapshot_v7.stop",F_OK)==0) break;
        int rc=wait_menu_sample(&menu);
        if(rc==1) {
            printf("MENU_DETECTED attempt=%u object=%08x\n",i,menu);fflush(stdout);
            usleep(1000000);
            for(unsigned retry=0;retry<5;retry++) {
                used=0;record_count=0;seen_view_count=0;
                result=snapshot(menu);
                printf("capture_attempt=%u result=%d records=%u bytes=%u\n",retry,result,record_count,used);fflush(stdout);
                if(!result) break;
                usleep(500000);
            }
            break;
        }
        if(i%20==0 || rc<0) { printf("wait_menu attempt=%u result=%d\n",i,rc);fflush(stdout); }
        usleep(500000);
    }
    printf("SNAPSHOT result=%d records=%u bytes=%u menu=%08x\n",result,record_count,used,menu);
    uint32_t header[4]={0x534c4159,2,record_count,used};
    unsigned required=sizeof(header)+record_count*sizeof(records[0])+used;
    struct statvfs space;
    if(statvfs("/tmp_bt",&space)) { printf("OUTPUT_ERROR statvfs=%d\n",errno);result=-70; }
    else {
        uint64_t free_bytes=(uint64_t)space.f_bavail*space.f_frsize;
        printf("SPACE free=%llu required=%u\n",(unsigned long long)free_bytes,required);
        if(free_bytes<(uint64_t)required+32768) result=-71;
    }
    if(!result) {
        FILE *binary=fopen("/tmp_bt/native_layout_resource_snapshot_v7.bin","wb");
        if(!binary) result=-72;
        else {
            if(fwrite(header,1,sizeof(header),binary)!=sizeof(header) ||
               fwrite(records,sizeof(records[0]),record_count,binary)!=record_count ||
               fwrite(bytes,1,used,binary)!=used || fflush(binary) || fsync(fileno(binary))) result=-73;
            if(fclose(binary)) result=-74;
        }
        printf("BINARY result=%d bytes=%u errno=%d\n",result,required,result?errno:0);
    }
    printf("END result=%d\n",result);
    int output_error=fflush(stdout) || ferror(stdout);
    close(lock);return result || output_error?5:0;
}
