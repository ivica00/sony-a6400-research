/* Run only on the host: exercises command framing, errors and shell bounds.
 * Does not invoke debug_main or open a camera device. */
#define main debug_main
#include "../../devcrashday_a6400/a6400_usb_debugd.c"
#undef main
#include <assert.h>

static struct packet make_request(unsigned op,const char *data) {
    struct packet q={0}; q.magic=MAGIC; q.version=1; q.op=op; q.id=71;
    if(data) { q.length=strlen(data); memcpy(q.data,data,q.length); }
    return q;
}
int main(void) {
    struct packet q=make_request(1,NULL),r;
    dispatch(&q,&r); assert(r.id==71 && r.status==0 && r.length>0 && r.length<DATA);
    q.magic=0; dispatch(&q,&r); assert(r.status==-EPROTO);
    q=make_request(2,"relative"); q.arg1=8; dispatch(&q,&r); assert(r.status==-EINVAL);
    q=make_request(2,"/proc/self/comm"); q.arg1=16; dispatch(&q,&r); assert(!r.status && r.length>0);
    q=make_request(7,NULL); q.arg0=getpid(); dispatch(&q,&r); assert(!r.status && r.length>0);
    q=make_request(3,"printf ok; exit 7"); dispatch(&q,&r);
    assert(r.status==7 && r.length==2 && !memcmp(r.data,"ok",2));
    q=make_request(3,"head -c 5000 /dev/zero"); dispatch(&q,&r);
    assert(!r.status && r.length==DATA && (r.flags&TRUNCATED));
    q=make_request(3,"sleep 6"); dispatch(&q,&r);
    assert(r.status==-ETIMEDOUT && (r.flags&TIMED_OUT));
    puts("USB debugger dispatch: framing, errno, exit code, truncation, timeout passed.");
    return 0;
}
