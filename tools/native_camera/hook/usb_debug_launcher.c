/* Start one debugger process even when /tmp_bt is absent. */
#include <unistd.h>
#include <fcntl.h>
#include <sys/types.h>
#include <sys/file.h>
#include <sys/wait.h>
#include <errno.h>
#include <stdio.h>

__attribute__((constructor)) static void launch(void) {
    if(getuid()!=0 || access("/setting/disable_usb_debug",F_OK)==0) return;
    int lock=open("/tmp/a6400_usb_debug_launcher.lock",O_RDWR|O_CREAT|O_NOFOLLOW,0600);
    if(lock<0) return;
    /* flock follows the open file description across fork and exec. */
    if(flock(lock,LOCK_EX|LOCK_NB)<0) { close(lock); return; }
    if(lock<3) {
        int inherited=fcntl(lock,F_DUPFD,3);
        close(lock);
        if(inherited<0) return;
        lock=inherited;
    }
    pid_t child=fork();
    if(child<0) { close(lock); return; }
    if(child>0) {
        close(lock);
        while(waitpid(child,NULL,0)<0 && errno==EINTR) {}
        return;
    }
    if(fork()!=0) _exit(0);
    setsid();
    for(int fd=0;fd<256;fd++) if(fd!=lock) close(fd);
    int input=open("/dev/null",O_RDONLY);
    if(input>=0 && input!=0) { dup2(input,0); close(input); }
    int output=open("/setting/a6400_usb_debug_launcher.log",O_WRONLY|O_CREAT|O_APPEND,0600);
    if(output>=0) { dup2(output,1); dup2(output,2); if(output>2) close(output); }
    char *argv[]={"a6400_usb_debugd.elf",NULL};
    char inherited_lock[48];
    snprintf(inherited_lock,sizeof(inherited_lock),"A6400_LAUNCH_LOCK_FD=%d",lock);
    char *env[]={"PATH=/usr/bin:/bin:/sbin:/usr/sbin:/setting",inherited_lock,NULL};
    execve("/setting/a6400_usb_debugd.elf",argv,env);
    write(2,"USB debugger exec failed\n",25);
    _exit(127);
}
