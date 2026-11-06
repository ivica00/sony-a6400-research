/* Start the native USB debugger once per boot. No firmware/RAM patching. */
#include <unistd.h>
#include <fcntl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <errno.h>

__attribute__((constructor)) static void launch(void) {
    if(getuid()!=0 || access("/setting/disable_usb_debug",F_OK)==0) return;
    int lock=open("/tmp_bt/a6400_usb_debug_launcher.once",O_WRONLY|O_CREAT|O_EXCL,0600);
    if(lock<0) return;
    close(lock);
    pid_t child=fork();
    if(child<0) { unlink("/tmp_bt/a6400_usb_debug_launcher.once"); return; }
    if(child>0) {
        while(waitpid(child,NULL,0)<0 && errno==EINTR) {}
        return;
    }
    if(fork()!=0) _exit(0);
    setsid();
    for(int fd=0;fd<256;fd++) close(fd);
    int input=open("/dev/null",O_RDONLY);
    if(input>=0 && input!=0) { dup2(input,0); close(input); }
    int output=open("/setting/a6400_usb_debug_launcher.log",O_WRONLY|O_CREAT|O_APPEND,0600);
    if(output>=0) { dup2(output,1); dup2(output,2); if(output>2) close(output); }
    char *argv[]={"a6400_usb_debugd.elf",NULL};
    char *env[]={"PATH=/usr/bin:/bin:/sbin:/usr/sbin:/setting",NULL};
    execve("/setting/a6400_usb_debugd.elf",argv,env);
    write(2,"USB debugger exec failed\n",25);
    _exit(127);
}
