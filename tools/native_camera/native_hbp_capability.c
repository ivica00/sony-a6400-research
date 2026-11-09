/* Read ARM hardware-breakpoint capabilities only; never set a breakpoint. */
#define _DEFAULT_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <unistd.h>
#include <errno.h>
#include <sys/ptrace.h>
#include <sys/wait.h>
#include "native_freeze.h"
int main(void) {
    int result=freeze_process();
    if(result){printf("END result=%d\n",result);fflush(stdout);return 5;}
    uint32_t info=0;errno=0;
    long status=ptrace(29,149,0,&info);int error=errno;
    printf("HBP_CAPABILITY request=29 tid=149 status=%ld errno=%d info=%08x writes=0\n",status,error,info);
    int resumed=freeze_resume();
    printf("END result=%d\n",resumed);
    fflush(stdout);return resumed?5:0;
}
