/* Actual native_freeze.h with explicit libc/ptrace fixtures; no camera. */
#define _DEFAULT_SOURCE
#include <stdio.h>
#include <unistd.h>
#include <sys/ptrace.h>
#include <sys/wait.h>
#include <dirent.h>
#include <stdlib.h>
#include <time.h>
#include <sys/syscall.h>
#include <stdarg.h>
__attribute__((noreturn,noinline)) void fail(int n){(void)n;for(;;){}}
#define CHECK(c) ((c)?(void)0:fail(__LINE__))
static int failures,detach101,detach102,index_,pending,exited;
static DIR *fake_open(const char *p){(void)p;index_=0;return (DIR *)1;}
static int fake_close(DIR *p){(void)p;return 0;}
static struct dirent *fake_read(DIR *p){
 static struct dirent e;(void)p;if(index_==2)return 0;
 e.d_name[0]='1';e.d_name[1]='0';e.d_name[2]=(char)('1'+index_++);e.d_name[3]=0;return &e;
}
static long fake_number(const char *s,char **end,int base){long n=0;(void)base;while(*s>='0'&&*s<='9')n=n*10+*s++-'0';*end=(char *)s;return n;}
static long fake_clock(long number,...){va_list ap;struct timespec *t;CHECK(number==SYS_clock_gettime);va_start(ap,number);(void)va_arg(ap,int);t=va_arg(ap,struct timespec *);va_end(ap);t->tv_sec=1;t->tv_nsec=0;return 0;}
static long fake_ptrace(int request,int tid,...){
 if(request==PTRACE_ATTACH)return 0;
 CHECK(request==PTRACE_DETACH);
 if(tid==101){detach101++;if(failures)return -1;}else{CHECK(tid==102);detach102++;}return 0;
}
static pid_t fake_wait(pid_t tid,int *status,int flags){(void)flags;if(pending)return 0;*status=exited?0:0x137f;return tid;}
static int fake_printf(const char *s,...){(void)s;return 0;}
static int fake_sleep(unsigned int t){(void)t;return 0;}
#define opendir fake_open
#define closedir fake_close
#define readdir fake_read
#define strtol fake_number
#define syscall fake_clock
#define ptrace fake_ptrace
#define waitpid fake_wait
#define printf fake_printf
#define usleep fake_sleep
#include "native_freeze.h"
int main(void){
 freeze_count=freeze_attached=2;freeze_tids[0]=101;freeze_tids[1]=102;
 freeze_owned[0]=freeze_owned[1]=freeze_stopped[0]=freeze_stopped[1]=1;
 failures=1;CHECK(freeze_resume()==-92);CHECK(freeze_owned[0]&&!freeze_owned[1]);
 CHECK(detach101==1&&detach102==1);CHECK(freeze_process()==-100);
 failures=0;CHECK(!freeze_resume());CHECK(detach101==2&&detach102==1);
 CHECK(!freeze_process());CHECK(freeze_owned[0]&&freeze_owned[1]);
 failures=1;CHECK(freeze_resume()==-92);
 failures=0;CHECK(!freeze_recover_process());CHECK(freeze_owned[0]&&freeze_owned[1]);
 CHECK(!freeze_resume());
 freeze_count=freeze_attached=1;freeze_tids[0]=101;freeze_owned[0]=1;freeze_stopped[0]=0;
 pending=1;CHECK(freeze_resume()==-92);CHECK(freeze_owned[0]);
 pending=0;CHECK(!freeze_resume());CHECK(!freeze_owned[0]);
 freeze_owned[0]=1;freeze_stopped[0]=0;exited=1;
 {int old=detach101;CHECK(!freeze_resume());CHECK(!freeze_owned[0]&&detach101==old);}
 return 0;
}
