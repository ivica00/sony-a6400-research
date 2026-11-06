/* Native USB debug channel over the existing mass-storage external-command
 * driver. No Senser/updater operations, network listener, or firmware patch. */
#define _DEFAULT_SOURCE
#include <stdio.h>
#include <stdlib.h>
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
struct packet { uint32_t magic; uint16_t version, op; uint32_t id; int32_t status;
    uint32_t length, flags, arg0, arg1; unsigned char data[DATA]; };
struct registration { uint8_t opcode, reserved; uint16_t feature; uint32_t receive_size, send_size; };
struct transfer { uint32_t buffer, size, remaining, timeout_ms; uint16_t flags, reserved; };
_Static_assert(sizeof(struct packet)==FRAME,"packet ABI");
_Static_assert(sizeof(struct registration)==12,"registration ABI");
_Static_assert(sizeof(struct transfer)==20,"transfer ABI");
static volatile sig_atomic_t stopping;
static void stop_requested(int sig) { (void)sig; stopping=1; }
static int debug_monotonic(struct timespec *value) {
    return syscall(SYS_clock_gettime,CLOCK_MONOTONIC,value);
}

static int transfer_frame(int fd, unsigned long command, struct packet *packet) {
    struct transfer t = { (uint32_t)(uintptr_t)packet, FRAME, 0, 1000, 0, 0 };
    if (ioctl(fd,command,&t)) return -errno;
    return t.size == FRAME && t.remaining == 0 ? 0 : -EMSGSIZE;
}

static int path_from_request(const struct packet *q, char *path) {
    if (!q->length || q->length>=512 || q->data[0]!='/'
        || memchr(q->data,0,q->length)) return -EINVAL;
    memcpy(path,q->data,q->length); path[q->length]=0; return 0;
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
    if(q->op==7) {
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

static void dispatch(const struct packet *q,struct packet *r) {
    memset(r,0,sizeof(*r)); r->magic=MAGIC; r->version=1; r->id=q->id; r->op=q->op;
    if(q->magic!=MAGIC || q->version!=1 || q->length>DATA || q->status || q->flags) { r->status=-EPROTO; return; }
    switch(q->op) {
    case 1:
        r->length=snprintf((char*)r->data,DATA,
            "A6400_USB_DEBUG_V1\npid=%d\nuid=%d\neuid=%d\ngid=%d\ntransport=usb_extcmd\nfeature=0x23\n"
            "ops=info,read,exec,vmem,processes,threads,exit\nexec_timeout_ms=5000\nmax_data=%d\n",
            getpid(),getuid(),geteuid(),getgid(),DATA); break;
    case 2: file_read(q,r); break;
    case 3: execute(q,r); break;
    case 4: memory_read(q,r); break;
    case 6: case 7: processes(q,r); break;
    case 255: stopping=1; break;
    default: r->status=-ENOSYS; break;
    }
}

int main(void) {
    int log=open("/setting/a6400_usb_debugd.log",O_WRONLY|O_CREAT|O_APPEND,0600);
    if(log>=0) { dup2(log,2); if(log!=2) close(log); }
    int lock=open("/tmp_bt/a6400_usb_debugd.lock",O_WRONLY|O_CREAT,0600);
    if(lock<0) return 2;
    struct flock flock={0}; flock.l_type=F_WRLCK; flock.l_whence=SEEK_SET;
    if(fcntl(lock,F_SETLK,&flock)) { close(lock); return 0; }
    fcntl(lock,F_SETFD,FD_CLOEXEC);
    signal(SIGTERM,stop_requested); signal(SIGINT,stop_requested); signal(SIGPIPE,SIG_IGN);
    int fd=open("/dev/usb/usb_extcmd",O_RDWR);
    if(fd<0) { dprintf(2,"debug open failed errno=%d\n",errno); close(lock); return 3; }
    fcntl(fd,F_SETFD,FD_CLOEXEC);
    struct registration reg={0x7a,0,0x23,FRAME,FRAME};
    if(ioctl(fd,0xc00ceb00u,&reg)) {
        dprintf(2,"debug register failed errno=%d\n",errno); close(fd); close(lock); return 4;
    }
    dprintf(2,"debug registered pid=%d uid=%d feature=0x23\n",getpid(),getuid());
    struct packet request,response;
    while(!stopping) {
        int result=transfer_frame(fd,0xc014eb02u,&request);
        if(result) { if(!stopping) usleep(20000); continue; }
        dispatch(&request,&response);
        result=transfer_frame(fd,0xc014eb03u,&response);
        if(result) dprintf(2,"debug response failed result=%d\n",result);
    }
    uint16_t feature=0x23;
    int result=ioctl(fd,0xc002eb01u,&feature);
    dprintf(2,"debug unregister result=%d errno=%d\n",result,result?errno:0);
    close(fd); close(lock); return result?5:0;
}
