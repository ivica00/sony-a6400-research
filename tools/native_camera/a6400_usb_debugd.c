/* Native USB debug channel over the existing mass-storage external-command
 * driver. No Senser/updater operations, network listener, or firmware patch.
 *
 * Protocol v2 (E0401) adds four read-only/persistent-debug operations on top of
 * the v1 file/shell/ptrace surface:
 *   8  usb_state : bounded camera/USB/debugger state receipt
 *   9  recover   : process-context removal of allowlisted authored modules and
 *                  a post-state receipt (never an arbitrary command, never
 *                  force-unload, never a physical-memory write)
 *   10 dmesg     : non-destructive kernel printk ring readout (SYSLOG_ACTION_READ_ALL)
 *   11 ring_dump : raw read of the cmdline-verified warm-reboot klog ring
 *                  (klog.addr/klog.size from /proc/cmdline) through /dev/mem O_RDONLY
 *   12 ring_info : klog ring header validation, CRC32 and boot-segment receipt
 *
 * The klog ring is the camera kernel's own warm-reboot log buffer
 * (`klog.addr=0x035a5000 klog.size=0x20000` in the verified a6400 cmdline); the
 * kernel keeps it across a warm reboot when its "klog" magic survives (see the
 * preserved-vmlinux keep/initialize path recorded in E0401). This user-space
 * daemon only reads it; it never allocates, clears or writes that region.
 */
#define _DEFAULT_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <dirent.h>
#include <poll.h>
#include <time.h>
#include <sys/ioctl.h>
#include <sys/ptrace.h>
#include <sys/wait.h>
#include <sys/syscall.h>

#define FRAME 4096
#define DATA (FRAME-32)
#define MAGIC 0x44343641u /* A64D */
#define TRUNCATED 1u
#define TIMED_OUT 2u
#define KLOG_MAGIC 0x676f6c6bu /* "klog" little-endian, observed in the live header */
#define KLOG_HEADER 12u
#define KLOG_MAX_BYTES 0x20000u
#define RECOVER_ARG 0x52454356u /* 'RECV': caller must name the operation */
#define OP_INFO 1
#define OP_READ 2
#define OP_EXEC 3
#define OP_MEM 4
#define OP_PS 6
#define OP_THREADS 7
#define OP_USB_STATE 8
#define OP_RECOVER 9
#define OP_DMESG 10
#define OP_RING_DUMP 11
#define OP_RING_INFO 12
#define OP_PING 13
#define DBG_NODE "/dev/a6400_dbg"
struct packet { uint32_t magic; uint16_t version, op; uint32_t id; int32_t status;
    uint32_t length, flags, arg0, arg1; unsigned char data[DATA]; };
struct registration { uint8_t opcode, reserved; uint16_t feature; uint32_t receive_size, send_size; };
struct transfer { uint32_t buffer, size, remaining, timeout_ms; uint16_t flags, reserved; };
_Static_assert(sizeof(struct packet)==FRAME,"packet ABI");
_Static_assert(sizeof(struct registration)==12,"registration ABI");
_Static_assert(sizeof(struct transfer)==20,"transfer ABI");
static volatile sig_atomic_t stopping;
static volatile int g_dbg_active;
static void stop_requested(int sig) { (void)sig; stopping=1; }
static int debug_monotonic(struct timespec *value) {
    return syscall(SYS_clock_gettime,CLOCK_MONOTONIC,value);
}

static int transfer_frame_timeout(int fd, unsigned long command, struct packet *packet,
                                  unsigned timeout_ms) {
    struct transfer t = { (uint32_t)(uintptr_t)packet, FRAME, 0, timeout_ms, 0, 0 };
    if (ioctl(fd,command,&t)) return -errno;
    return t.size == FRAME && t.remaining == 0 ? 0 : -EMSGSIZE;
}

static int transfer_frame(int fd, unsigned long command, struct packet *packet) {
    return transfer_frame_timeout(fd,command,packet,1000);
}

static int path_from_request(const struct packet *q, char *path) {
    if (!q->length || q->length>=512 || q->data[0]!='/'
        || memchr(q->data,0,q->length)) return -EINVAL;
    memcpy(path,q->data,q->length); path[q->length]=0; return 0;
}

/* Bounded, NUL-terminating text read of a kernel view. Never writes to it. */
static int read_text_file(const char *path, char *buffer, unsigned capacity) {
    if (!capacity) return -EINVAL;
    int fd=open(path,O_RDONLY|O_NONBLOCK);
    if (fd<0) return -errno;
    unsigned used=0;
    while (used+1<capacity) {
        ssize_t n=read(fd,buffer+used,capacity-1-used);
        if (n<0) { if (errno==EINTR) continue; int error=-errno; close(fd); buffer[used]=0; return error; }
        if (!n) break;
        used+=(unsigned)n;
    }
    close(fd); buffer[used]=0; buffer[capacity-1]=0;
    return (int)used;
}

/* Find "<key>=0x..." in a /proc text file. Rejects missing or malformed keys. */
static int hex_key_value(const char *text, const char *key, unsigned *value) {
    size_t n=strlen(key);
    const char *p=text;
    while ((p=strstr(p,key))) {
        if ((p==text || p[-1]==' ' || p[-1]=='\n') && p[n]=='=') {
            const char *v=p+n+1;
            char *end;
            unsigned long parsed=strtoul(v,&end,16);
            if (end==v || parsed>0xfffffffful) return -EINVAL;
            *value=(unsigned)parsed;
            return 0;
        }
        p+=n;
    }
    return -ENOENT;
}

/* True only when [address,address+size) lies inside one /proc/iomem System RAM range. */
static int system_ram_contains(unsigned address, unsigned size, char *receipt, size_t receipt_size) {
    char text[8192];
    int n=read_text_file("/proc/iomem",text,sizeof(text));
    if (n<0) return n;
    unsigned long end_address=(unsigned long)address+(unsigned long)size;
    const char *line=text;
    while (*line) {
        char *next=strchr(line,'\n');
        char saved=next?*next:0;
        if (next) *next=0;
        unsigned long start,end; char label[96];
        if (sscanf(line,"%lx-%lx : %95[^\n]",&start,&end,label)==3
            && !strcmp(label,"System RAM")
            && address>=start && end_address<=end+1) {
            snprintf(receipt,receipt_size,"%08lx-%08lx System RAM",start,end);
            if (next) *next=saved;
            return 0;
        }
        if (next) *next=saved;
        if (!next) break;
        line=next+1;
    }
    return -ERANGE;
}

static int read_physical(unsigned address, void *buffer, unsigned size) {
    if (!size || size>KLOG_MAX_BYTES) return -EINVAL;
    int fd=open("/dev/mem",O_RDONLY);
    if (fd<0) return -errno;
    ssize_t n=pread(fd,buffer,size,(off_t)address);
    int error=errno;
    close(fd);
    if (n<0) return -error;
    return (unsigned)n==size ? 0 : -EIO;
}

static uint32_t crc32_bytes(const unsigned char *data, unsigned size) {
    uint32_t crc=0xffffffffu;
    for (unsigned i=0;i<size;i++) {
        crc^=data[i];
        for (unsigned bit=0;bit<8;bit++) crc = (crc>>1) ^ (0xedb88320u & (uint32_t)-(int32_t)(crc&1));
    }
    return ~crc;
}

struct klog_ring {
    int valid;
    int header_read;
    unsigned address, capacity;
    unsigned write_position, wrap;
    unsigned data_bytes;
    uint32_t crc;
    unsigned warmboot_markers;
    char ram_receipt[64];
    char error[96];
};

static void klog_inspect(struct klog_ring *ring) {
    memset(ring,0,sizeof(*ring));
    snprintf(ring->error,sizeof(ring->error),"unresolved");
    char cmdline[4096];
    int n=read_text_file("/proc/cmdline",cmdline,sizeof(cmdline));
    if (n<0) { snprintf(ring->error,sizeof(ring->error),"cmdline_read_error(%d)",n); return; }
    unsigned address, capacity;
    int a=hex_key_value(cmdline,"klog.addr",&address);
    int c=hex_key_value(cmdline,"klog.size",&capacity);
    if (a||c) { snprintf(ring->error,sizeof(ring->error),"cmdline_klog_absent"); return; }
    if (!capacity || capacity>KLOG_MAX_BYTES) {
        snprintf(ring->error,sizeof(ring->error),"klog_size_rejected(0x%x)",capacity); return;
    }
    char ram[64];
    int r=system_ram_contains(address,capacity,ram,sizeof(ram));
    if (r<0) { snprintf(ring->error,sizeof(ring->error),"klog_not_in_system_ram(%d)",r); return; }
    snprintf(ring->ram_receipt,sizeof(ring->ram_receipt),"%s",ram);
    ring->address=address; ring->capacity=capacity;
    unsigned char header[KLOG_HEADER];
    if (read_physical(address,header,KLOG_HEADER)) {
        snprintf(ring->error,sizeof(ring->error),"klog_header_read_failed"); return;
    }
    ring->header_read=1;
    uint32_t magic; unsigned position,wrap;
    memcpy(&magic,header,4); memcpy(&position,header+4,4); memcpy(&wrap,header+8,4);
    if (magic!=KLOG_MAGIC) {
        snprintf(ring->error,sizeof(ring->error),"klog_magic_mismatch(0x%08x)",magic); return;
    }
    if (position>capacity) {
        snprintf(ring->error,sizeof(ring->error),"klog_write_position_rejected(%u>%u)",position,capacity); return;
    }
    unsigned char *region=malloc(capacity);
    if (!region) { snprintf(ring->error,sizeof(ring->error),"klog_region_alloc_failed"); return; }
    if (read_physical(address,region,capacity)) {
        free(region); snprintf(ring->error,sizeof(ring->error),"klog_region_read_failed"); return;
    }
    ring->write_position=position; ring->wrap=wrap;
    ring->data_bytes=position;
    ring->crc=crc32_bytes(region,KLOG_HEADER+position);
    for (unsigned i=KLOG_HEADER;i+10<=KLOG_HEADER+position;) {
        if (!memcmp(region+i,"WARMBOOT\n",9)) { ring->warmboot_markers++; i+=9; }
        else i++;
    }
    free(region);
    ring->valid=1;
    ring->error[0]=0;
}

static char kernel_log_buffer[KLOG_MAX_BYTES+64];
static int kernel_log(unsigned *total) {
    long n=syscall(SYS_syslog,3,kernel_log_buffer,(long)sizeof(kernel_log_buffer)); /* SYSLOG_ACTION_READ_ALL */
    if (n<0) return -errno;
    *total=(unsigned)n;
    return 0;
}

static int module_line(const char *text, const char *name) {
    size_t n=strlen(name);
    const char *line=text;
    while (line && *line) {
        if (!strncmp(line,name,n) && (line[n]==' ' || line[n]=='\t')) return 1;
        line=strchr(line,'\n');
        if (line) line++;
    }
    return 0;
}

static const char *const custom_modules[] = {
    "usbg_video_a6400",
    "usbg_video_a6400_shared_candidate",
    "a6400_debug_ring",
    "a6400_debug_hook",
    0
};
static const char *const usb_modules[] = {
    "usb_extcmd","usbg_stillimage","usbg_storage","usbg_sen","usb_darwin","usb_buspwr",0
};

static void append_packet(char *target, unsigned capacity, unsigned *used,
                          const char *format, ...) __attribute__((format(printf,4,5)));
static void append_packet(char *target, unsigned capacity, unsigned *used,
                          const char *format, ...) {
    if (*used>=capacity) return;
    va_list args;
    va_start(args,format);
    int n=vsnprintf(target+*used,capacity-*used,format,args);
    va_end(args);
    if (n>0) {
        *used+=(unsigned)n;
        if (*used>capacity) *used=capacity;
    }
}

static void file_read(const struct packet *q, struct packet *r) {
    char path[512];
    r->status=path_from_request(q,path);
    if (r->status) return;
    unsigned size=q->arg1;
    if (!size || size>DATA) { r->status=-EINVAL; return; }
    int fd=open(path,O_RDONLY|O_NONBLOCK);
    if (fd<0) { r->status=-errno; return; }
    int n=pread(fd,r->data,size,q->arg0);
    if (n<0) r->status=-errno;
    else r->length=n;
    close(fd);
}

static void processes(const struct packet *q,struct packet *r) {
    char root[64];
    if(q->op==OP_THREADS) {
        if(!q->arg0 || q->arg0>0x7fffffff) { r->status=-EINVAL; return; }
        snprintf(root,sizeof(root),"/proc/%u/task",q->arg0);
    } else strcpy(root,"/proc");
    DIR *directory=opendir(root);
    struct dirent *entry;
    if (!directory) { r->status=-errno; return; }
    while ((entry=readdir(directory))) {
        char *tail;
        unsigned long pid=strtoul(entry->d_name,&tail,10);
        if (!pid || *tail) continue;
        char path[128], comm[64]={0}, line[96];
        snprintf(path,sizeof(path),"%s/%lu/comm",root,pid);
        int fd=open(path,O_RDONLY);
        if (fd>=0) { int n=read(fd,comm,sizeof(comm)-1); if(n>0) comm[n]=0; close(fd); }
        char *nl=strchr(comm,'\n'); if(nl) *nl=0;
        int n=snprintf(line,sizeof(line),"%lu %s\n",pid,comm);
        if (n<0 || (unsigned)n>=sizeof(line)) continue;
        if (r->length+(unsigned)n>DATA) { r->flags|=TRUNCATED; break; }
        memcpy(r->data+r->length,line,n); r->length+=n;
    }
    closedir(directory);
}

static void memory_read(const struct packet *q,struct packet *r) {
    uint32_t count;
    if(q->length!=4 || !q->arg0 || q->arg0==(uint32_t)getpid()) { r->status=-EINVAL; return; }
    memcpy(&count,q->data,4);
    if(!count || count>DATA || q->arg1>UINT32_MAX-count) { r->status=-EINVAL; return; }
    pid_t pid=(pid_t)q->arg0;
    int status;
    if(ptrace(PTRACE_ATTACH,pid,NULL,NULL)) { r->status=-errno; return; }
    pid_t waited;
    do { waited=waitpid(pid,&status,0); } while(waited<0 && errno==EINTR);
    if(waited!=pid || !WIFSTOPPED(status)) r->status=-ECHILD;
    else {
        for(unsigned i=0;i<count;) {
            uintptr_t address=q->arg1+i, aligned=address&~(uintptr_t)3;
            errno=0;
            long word=ptrace(PTRACE_PEEKDATA,pid,(void*)aligned,NULL);
            if(word==-1 && errno) { r->status=-errno; break; }
            unsigned offset=address&3, n=4-offset;
            if(n>count-i) n=count-i;
            memcpy(r->data+i,(unsigned char*)&word+offset,n); i+=n; r->length=i;
        }
    }
    if(ptrace(PTRACE_DETACH,pid,NULL,NULL) && !r->status) r->status=-errno;
}

static void execute(const struct packet *q,struct packet *r) {
    if(!q->length || q->length>=DATA || memchr(q->data,0,q->length)) { r->status=-EINVAL; return; }
    char command[DATA+1]; memcpy(command,q->data,q->length); command[q->length]=0;
    struct timespec start,now;
    if(debug_monotonic(&start)) { r->status=-errno; return; }
    int pipes[2];
    if(pipe(pipes)) { r->status=-errno; return; }
    pid_t child=fork();
    if(child<0) { r->status=-errno; close(pipes[0]); close(pipes[1]); return; }
    if(!child) {
        setpgid(0,0); close(pipes[0]); dup2(pipes[1],1); dup2(pipes[1],2); close(pipes[1]);
        char *argv[]={"sh","-c",command,NULL};
        char *environment[]={"PATH=/usr/bin:/bin:/sbin:/usr/sbin:/setting",NULL};
        execve("/bin/sh",argv,environment); _exit(127);
    }
    close(pipes[1]); setpgid(child,child);
    fcntl(pipes[0],F_SETFL,O_NONBLOCK);
    int status=0, finished=0, eof=0, expired=0;
    /* Bounded 5 seconds. Continue draining even when the output buffer fills. */
    while(!stopping) {
        if(debug_monotonic(&now)
            || (now.tv_sec-start.tv_sec)*1000+(now.tv_nsec-start.tv_nsec)/1000000>=5000) { expired=1; break; }
        struct pollfd pfd={pipes[0],POLLIN|POLLHUP,0}; poll(&pfd,1,50);
        unsigned char chunk[512]; int n=-1;
        for(unsigned drain=0;drain<64 && (n=read(pipes[0],chunk,sizeof(chunk)))>0;drain++) {
            unsigned keep=DATA-r->length;
            if(keep>(unsigned)n) keep=n;
            memcpy(r->data+r->length,chunk,keep); r->length+=keep;
            if(keep<(unsigned)n) r->flags|=TRUNCATED;
        }
        if(n==0) eof=1;
        if(!finished && waitpid(child,&status,WNOHANG)==child) finished=1;
        if(finished && eof) break;
        if(eof && !finished) usleep(1000);
    }
    if(!finished || expired || stopping) {
        kill(-child,SIGKILL);
        if(!finished) { kill(child,SIGKILL); waitpid(child,&status,0); }
        r->flags|=TIMED_OUT; r->status=-ETIMEDOUT;
    } else if(WIFEXITED(status)) r->status=WEXITSTATUS(status);
    else if(WIFSIGNALED(status)) r->status=128+WTERMSIG(status);
    close(pipes[0]);
}

static unsigned uptime_seconds(void) {
    char text[64];
    if (read_text_file("/proc/uptime",text,sizeof(text))<0) return 0;
    return (unsigned)strtoul(text,0,10);
}

static void usb_state(const struct packet *q,struct packet *r) {
    (void)q;
    char text[4096]; unsigned used=0;
    append_packet(text,sizeof(text),&used,
        "A6400_USB_DEBUG_STATE\nprotocol=2\npid=%d\nuid=%d\neuid=%d\ngid=%d\nuptime_s=%u\n"
        "transport=usb_extcmd\nfeature=0x23\nopcode=0x7a\n"
        "transports=usb_extcmd,a6400_dbg\n"
        "ops=info,read,exec,vmem,processes,threads,usb_state,recover,dmesg,ring_dump,ring_info,ping,exit\n",
        getpid(),getuid(),geteuid(),getgid(),uptime_seconds());
    append_packet(text,sizeof(text),&used,"transport.dbg_node=%s\n",
        access(DBG_NODE,F_OK)==0?"present":"absent");
    append_packet(text,sizeof(text),&used,"transport.dbg_active=%s\n",g_dbg_active?"yes":"no");
    char file[4096];
    if (read_text_file("/sys/class/udc/dwc3.0/state",file,sizeof(file))>=0) {
        char *nl=strchr(file,'\n'); if(nl) *nl=0;
        append_packet(text,sizeof(text),&used,"udc=dwc3.0\nudc.state=%s\n",file);
    } else append_packet(text,sizeof(text),&used,"udc.state=unavailable\n");
    if (read_text_file("/sys/class/udc/dwc3.0/current_speed",file,sizeof(file))>=0) {
        char *nl=strchr(file,'\n'); if(nl) *nl=0;
        append_packet(text,sizeof(text),&used,"udc.speed=%s\n",file);
    } else append_packet(text,sizeof(text),&used,"udc.speed=unavailable\n");
    if (read_text_file("/proc/modules",file,sizeof(file))<0) file[0]=0;
    unsigned custom_count=0; unsigned off=0;
    for (const char *const *name=custom_modules;*name;name++) {
        if (!module_line(file,*name)) continue;
        if (!custom_count) append_packet(text,sizeof(text),&used,"modules.custom=");
        append_packet(text,sizeof(text),&used,"%s%s",custom_count?",":"",*name);
        custom_count++;
    }
    append_packet(text,sizeof(text),&used,custom_count?"\n":"modules.custom=none\n");
    append_packet(text,sizeof(text),&used,"modules.usb=");
    for (const char *const *name=usb_modules;*name;name++)
        append_packet(text,sizeof(text),&used,"%s%s:%s",off++?",":"",*name,module_line(file,*name)?"present":"absent");
    append_packet(text,sizeof(text),&used,"\n");
    append_packet(text,sizeof(text),&used,"nodes=");
    const char *nodes[]={"/dev/usb/usb_extcmd","/dev/usb/gadgetcore","/dev/usb/otgcore","/dev/usb/event","/dev/usb/sen",0};
    off=0;
    for (const char *const *node=nodes;*node;node++)
        append_packet(text,sizeof(text),&used,"%s%s:%s",off++?",":"",*node,access(*node,F_OK)==0?"present":"absent");
    append_packet(text,sizeof(text),&used,"\n");
    struct klog_ring ring; klog_inspect(&ring);
    if (ring.valid)
        append_packet(text,sizeof(text),&used,"klog.valid=1\nklog.addr=0x%08x\nklog.size=0x%08x\n"
            "klog.write_position=%u\nklog.wrap=%u\nklog.data_bytes=%u\nklog.crc32=0x%08x\nklog.warmboot_markers=%u\nklog.ram=%s\n",
            ring.address,ring.capacity,ring.write_position,ring.wrap,ring.data_bytes,ring.crc,ring.warmboot_markers,ring.ram_receipt);
    else append_packet(text,sizeof(text),&used,"klog.valid=0\nklog.error=%s\n",ring.error);
    unsigned total=0; int result=kernel_log(&total);
    append_packet(text,sizeof(text),&used,"dmesg.bytes=%u\n",result?0u:total);
    append_packet(text,sizeof(text),&used,"recover.allowed=");
    for (const char *const *name=custom_modules;*name;name++) append_packet(text,sizeof(text),&used,"%s%s",name==custom_modules?"":",",*name);
    append_packet(text,sizeof(text),&used,"\n");
    r->length=used<DATA?used:DATA; memcpy(r->data,text,r->length); if(used>DATA) r->flags|=TRUNCATED;
}

static void dmesg_read(const struct packet *q,struct packet *r) {
    unsigned total=0;
    int result=kernel_log(&total);
    if (result) { r->status=result; return; }
    unsigned offset=q->arg0, size=q->arg1;
    if (!size || size>DATA) { r->status=-EINVAL; return; }
    if (offset>total) { r->status=-ERANGE; return; }
    unsigned available=total-offset;
    if (size>available) size=available;
    memcpy(r->data,kernel_log_buffer+offset,size); r->length=size;
    r->arg0=total;
}

static void ring_dump(const struct packet *q,struct packet *r) {
    struct klog_ring ring; klog_inspect(&ring);
    if (!ring.valid) { r->status=-ENODATA; r->length=0; return; }
    unsigned offset=q->arg0, size=q->arg1;
    if (!size || size>DATA) { r->status=-EINVAL; return; }
    if (offset>=ring.capacity) { r->status=-ERANGE; return; }
    unsigned available=ring.capacity-offset;
    if (size>available) size=available;
    static unsigned char chunk[KLOG_MAX_BYTES];
    int result=read_physical(ring.address+offset,chunk,size);
    if (result) { r->status=result; return; }
    memcpy(r->data,chunk,size); r->length=size;
    r->arg0=KLOG_HEADER+ring.data_bytes; /* valid ring bytes, header + data */
    r->arg1=ring.crc;
}

static void ring_info(const struct packet *q,struct packet *r) {
    (void)q;
    struct klog_ring ring; klog_inspect(&ring);
    unsigned used=0;
    append_packet((char*)r->data,DATA,&used,"KLOG_RING_V1\n");
    if (!ring.valid) {
        append_packet((char*)r->data,DATA,&used,"valid=0\nerror=%s\n",ring.error);
        r->status=0; r->length=used; return;
    }
    append_packet((char*)r->data,DATA,&used,
        "valid=1\nsource=/proc/cmdline\nklog.addr=0x%08x\nklog.size=0x%08x\nram=%s\n"
        "header.magic=klog\nheader.write_position=%u\nheader.wrap=%u\n"
        "data_bytes=%u\ncrc32=0x%08x\nwarmboot_markers=%u\n",
        ring.address,ring.capacity,ring.ram_receipt,ring.write_position,ring.wrap,
        ring.data_bytes,ring.crc,ring.warmboot_markers);
    r->length=used;
}

static void recover(const struct packet *q,struct packet *r) {
    if (q->arg1!=RECOVER_ARG) { r->status=-EPERM; return; }
    struct timespec started; debug_monotonic(&started);
    char text[4096]; unsigned used=0;
    append_packet(text,sizeof(text),&used,
        "RECOVER_V1\nprotocol=2\npid=%d\nuid=%d\nmode=process_context\nforce_unload=no\nphysical_memory_write=no\n",
        getpid(),getuid());
    char modules[4096];
    if (read_text_file("/proc/modules",modules,sizeof(modules))<0) modules[0]=0;
    unsigned custom_count=0;
    for (const char *const *name=custom_modules;*name;name++) if (module_line(modules,*name)) custom_count++;
    unsigned pre_count=custom_count;
    append_packet(text,sizeof(text),&used,"pre.custom_modules=%u\n",custom_count);
    unsigned unloaded=0, busy=0, failed=0;
    for (const char *const *name=custom_modules;*name;name++) {
        if (!module_line(modules,*name)) { append_packet(text,sizeof(text),&used,"module.%s=absent\n",*name); continue; }
        int finished=0;
        for (unsigned attempt=0;attempt<20 && !finished;attempt++) {
            long result=syscall(SYS_delete_module,*name,O_NONBLOCK);
            if (result==0) { append_packet(text,sizeof(text),&used,"module.%s=unloaded\n",*name); unloaded++; finished=1; break; }
            int error=errno;
            if (error==ENOENT) { append_packet(text,sizeof(text),&used,"module.%s=absent\n",*name); finished=1; break; }
            if (error==EWOULDBLOCK || error==EBUSY || error==EAGAIN) { usleep(100000); continue; }
            append_packet(text,sizeof(text),&used,"module.%s=error_%d\n",*name,error); failed++; finished=1; break;
        }
        if (!finished) { append_packet(text,sizeof(text),&used,"module.%s=busy_%u_ms\n",*name,20u*100u); busy++; }
    }
    /* Re-read the live module table; only an observed absence is reported as clean. */
    char after[4096];
    int after_ok=read_text_file("/proc/modules",after,sizeof(after))>=0;
    unsigned remaining=0;
    if (after_ok) for (const char *const *name=custom_modules;*name;name++) if (module_line(after,*name)) remaining++;
    append_packet(text,sizeof(text),&used,"post.custom_modules=%u\n",after_ok?remaining:0xffffffffu);
    char file[4096];
    if (read_text_file("/sys/class/udc/dwc3.0/state",file,sizeof(file))>=0) {
        char *nl=strchr(file,'\n'); if(nl) *nl=0;
        append_packet(text,sizeof(text),&used,"post.udc.state=%s\n",file);
    } else append_packet(text,sizeof(text),&used,"post.udc.state=unavailable\n");
    struct klog_ring ring; klog_inspect(&ring);
    append_packet(text,sizeof(text),&used,"post.klog.valid=%d\n",ring.valid);
    if (ring.valid) append_packet(text,sizeof(text),&used,"post.klog.crc32=0x%08x\npost.klog.data_bytes=%u\n",ring.crc,ring.data_bytes);
    unsigned total=0;
    int dmesg_ok=kernel_log(&total)==0;
    append_packet(text,sizeof(text),&used,"post.dmesg.bytes=%u\n",dmesg_ok?total:0);
    const char *result = (!after_ok || remaining) ? "modules_remaining" : (busy?"busy":(failed?"failed":"clean"));
    const char *descriptors = !after_ok ? "unverified" :
        (!pre_count ? "already_stock" : (remaining ? "unverified" : "module_unload_path"));
    append_packet(text,sizeof(text),&used,
        "unloaded=%u\nbusy=%u\nfailed=%u\nresult=%s\ncustom_modules_absent=%s\nstock_descriptors=%s\n"
        "host_next=send_sony_req_reconnect_0x9282_to_msc\n",
        unloaded,busy,failed,result,(!after_ok||remaining)?"no":"yes",descriptors);
    struct timespec finished; debug_monotonic(&finished);
    append_packet(text,sizeof(text),&used,"elapsed_ms=%ld\n",
        (finished.tv_sec-started.tv_sec)*1000+(finished.tv_nsec-started.tv_nsec)/1000000);
    r->length=used<DATA?used:DATA; memcpy(r->data,text,r->length); if(used>DATA) r->flags|=TRUNCATED;
}

static void dispatch(const struct packet *q,struct packet *r) {
    memset(r,0,sizeof(*r)); r->magic=MAGIC; r->version=1; r->id=q->id; r->op=q->op;
    if(q->magic!=MAGIC || q->version!=1 || q->length>DATA || q->status || q->flags) { r->status=-EPROTO; return; }
    switch(q->op) {
    case OP_INFO:
        r->length=snprintf((char*)r->data,DATA,
            "A6400_USB_DEBUG_V1\nprotocol=2\npid=%d\nuid=%d\neuid=%d\ngid=%d\ntransport=usb_extcmd\ntransports=usb_extcmd,a6400_dbg\nfeature=0x23\n"
            "ops=info,read,exec,vmem,processes,threads,usb_state,recover,dmesg,ring_dump,ring_info,ping,exit\n"
            "exec_timeout_ms=5000\nmax_data=%d\n",
            getpid(),getuid(),geteuid(),getgid(),DATA); break;
    case OP_READ: file_read(q,r); break;
    case OP_EXEC: execute(q,r); break;
    case OP_MEM: memory_read(q,r); break;
    case OP_PS: case OP_THREADS: processes(q,r); break;
    case OP_USB_STATE: usb_state(q,r); break;
    case OP_RECOVER: recover(q,r); break;
    case OP_DMESG: dmesg_read(q,r); break;
    case OP_RING_DUMP: ring_dump(q,r); break;
    case OP_RING_INFO: ring_info(q,r); break;
    case OP_PING:
        r->arg0=q->arg0;
        r->length=snprintf((char*)r->data,DATA,
            "PONG protocol=2 nonce=0x%08x pid=%d transport=%s\n",
            q->arg0,getpid(),g_dbg_active?"a6400_dbg":"usb_extcmd");
        break;
    case 255: stopping=1; break;
    default: r->status=-ENOSYS; break;
    }
}

int main(void) {
    const char *inherited_lock=getenv("A6400_LAUNCH_LOCK_FD");
    if(inherited_lock) {
        char *end;
        long fd=strtol(inherited_lock,&end,10);
        if(*inherited_lock && !*end && fd>=3 && fd<=0x7fffffff)
            fcntl((int)fd,F_SETFD,FD_CLOEXEC);
    }
    int log=open("/setting/a6400_usb_debugd.log",O_WRONLY|O_CREAT|O_APPEND,0600);
    if(log>=0) { dup2(log,2); if(log!=2) close(log); }
    int lock=open("/tmp/a6400_usb_debugd.lock",O_WRONLY|O_CREAT|O_NOFOLLOW,0600);
    if(lock<0) { dprintf(2,"debug lock open failed errno=%d\n",errno); return 2; }
    struct flock flock={0}; flock.l_type=F_WRLCK; flock.l_whence=SEEK_SET;
    int locked=0;
    for(unsigned attempt=0;attempt<100 && !stopping;attempt++) {
        if(fcntl(lock,F_SETLK,&flock)==0) { locked=1; break; }
        int error=errno;
        if(error!=EACCES && error!=EAGAIN) break;
        usleep(100000);
    }
    if(!locked) { dprintf(2,"debug lock busy errno=%d\n",errno); close(lock); return 0; }
    fcntl(lock,F_SETFD,FD_CLOEXEC);
    signal(SIGTERM,stop_requested); signal(SIGINT,stop_requested); signal(SIGPIPE,SIG_IGN);
    /* Registration is retried: an upgraded daemon can be staged while the
     * previous instance still owns feature 0x23 and take over immediately after
     * it unregisters (duplicate registration returns EALREADY=114). */
    int fd=-1, registered=0;
    for (unsigned attempt=0;attempt<100 && !stopping;attempt++) {
        fd=open("/dev/usb/usb_extcmd",O_RDWR);
        if (fd>=0) {
            fcntl(fd,F_SETFD,FD_CLOEXEC);
            struct registration reg={0x7a,0,0x23,FRAME,FRAME};
            if (ioctl(fd,0xc00ceb00u,&reg)==0) { registered=1; break; }
            int error=errno;
            close(fd); fd=-1;
            if (error!=EALREADY && error!=EBUSY && error!=EAGAIN && error!=ENODEV) break;
        }
        if (attempt==0 || attempt%20==0) dprintf(2,"debug registration retry attempt=%u errno=%d\n",attempt,errno);
        usleep(100000);
    }
    if (!registered) {
        dprintf(2,"debug register failed errno=%d\n",errno);
        close(lock);
        return 4;
    }
    dprintf(2,"debug registered pid=%d uid=%d feature=0x23 protocol=2\n",getpid(),getuid());
    static struct packet request,response,dbg_request,dbg_response;
    int dbg=-1; time_t dbg_last_attempt=0;
    while(!stopping) {
        if (dbg<0) {
            time_t now=time(0);
            if (now-dbg_last_attempt>=1) {
                dbg=open(DBG_NODE,O_RDWR|O_NONBLOCK);
                dbg_last_attempt=now;
                if (dbg>=0) dprintf(2,"dbg transport opened pid=%d\n",getpid());
            }
        }
        if (dbg>=0) {
            struct pollfd pfd={dbg,POLLIN,0};
            int ready=poll(&pfd,1,0);
            if (ready>0 && (pfd.revents&(POLLIN|POLLERR|POLLHUP))) {
                ssize_t n=read(dbg,&dbg_request,FRAME);
                if (n==(ssize_t)FRAME) {
                    dispatch(&dbg_request,&dbg_response);
                    ssize_t written=write(dbg,&dbg_response,FRAME);
                    if (written!=(ssize_t)FRAME)
                        dprintf(2,"dbg response failed written=%ld errno=%d\n",(long)written,errno);
                } else if (n<0 && errno!=EAGAIN && errno!=EINTR) {
                    dprintf(2,"dbg transport closed errno=%d\n",errno);
                    close(dbg); dbg=-1;
                }
            } else if (ready>0 && (pfd.revents&(POLLERR|POLLHUP))) {
                close(dbg); dbg=-1;
            }
        }
        g_dbg_active = dbg>=0;
        int result=transfer_frame_timeout(fd,0xc014eb02u,&request,dbg>=0?100u:1000u);
        if(result) { if(!stopping && dbg<0) usleep(20000); continue; }
        dispatch(&request,&response);
        result=transfer_frame(fd,0xc014eb03u,&response);
        if(result) dprintf(2,"debug response failed result=%d\n",result);
    }
    if (dbg>=0) { close(dbg); dbg=-1; }
    g_dbg_active=0;
    uint16_t feature=0x23;
    int result=ioctl(fd,0xc002eb01u,&feature);
    dprintf(2,"debug unregister result=%d errno=%d\n",result,result?errno:0);
    close(fd); close(lock); return result?5:0;
}
