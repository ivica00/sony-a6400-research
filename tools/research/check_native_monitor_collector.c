/* Linux-host fault fixture for the actual collector body. No camera access. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <stdarg.h>
#include <stdlib.h>
#include <sys/types.h>
#include "../native_camera/native_monitor_snapshot.h"
static int fixture_open(const char *,int,...);
static int fixture_close(int);
static int fixture_fsync(int);
static ssize_t fixture_write(int,const void *,size_t);
static ssize_t fixture_pread(int,void *,size_t,off_t);
static off_t fixture_lseek(int,off_t,int);
static unsigned int fixture_sleep(unsigned int);
#define open fixture_open
#define close fixture_close
#define fsync fixture_fsync
#define write fixture_write
#define pread fixture_pread
#define lseek fixture_lseek
#define sleep fixture_sleep
#define main collector_main
#include "../native_camera/native_monitor_collector.c"
#undef main
struct a6400_monitor_snapshot a6400_monitor_snapshot;
unsigned int a6400_monitor_published_end=0xffffffffu;
static unsigned char files[3][32768];
static unsigned int lengths[3],calls,closed,scenario,syncs,acks,probes,snapshots,corrupted,native_acks,prepeeks,journal_published,journal_step,journal_publishes[10];
static int fixture_open(const char *p,int flags,...)
{
    assert((flags&(O_CREAT|O_EXCL))==(O_CREAT|O_EXCL));
    if(scenario==1){errno=EEXIST;return -1;}
    if(scenario>=11) {
        if(strstr(p,".expected"))return 4;
        return strstr(p,".receipt")?5:3;
    }
    return strstr(p,".receipt")?4:3;
}
static int fixture_close(int fd){assert(fd==3 || fd==4 || fd==5);closed++;return 0;}
static int fixture_fsync(int fd){assert(fd==3 || fd==4 || fd==5);syncs++;return scenario==2?-1:0;}
static ssize_t fixture_write(int fd,const void *p,size_t n)
{
    unsigned int i=(unsigned int)fd-3;assert(i<3);
    if(scenario==3 && fd==(scenario<11?4:5))return 0;
    /* Every write is short, exercising write_all rather than assuming success. */
    if(n>7)n=7;
    assert(lengths[i]+n<=sizeof(files[i]));
    memcpy(files[i]+lengths[i],p,n);lengths[i]+=(unsigned int)n;return (ssize_t)n;
}
static ssize_t fixture_pread(int fd,void *p,size_t n,off_t o)
{
    unsigned int i=(unsigned int)fd-3;assert(i<3 && o>=0);
    if((size_t)o+n>lengths[i])return -1;
    memcpy(p,files[i]+o,n);
    if(scenario==4 && fd==(scenario<11?4:5) && n)((unsigned char *)p)[0]^=1;
    if(scenario==8 && fd==3 && probes && n && !corrupted++)((unsigned char *)p)[0]^=1;
    if(scenario==10 && fd==3 && prepeeks && n && !corrupted++)((unsigned char *)p)[0]^=1;
    return (ssize_t)n;
}
static off_t fixture_lseek(int fd,off_t o,int whence)
{assert(fd==3 && !o && whence==SEEK_SET);return 0;}
static unsigned int fixture_sleep(unsigned int seconds){assert(seconds==1 || seconds==30 || seconds==90);return 0;}
static const char *journal_answer(unsigned int step)
{
    switch(step) {
    case 0:return "result = 0x00000000\r\nfilesystemType   = 0x0003\r\nMWF>\r\n";
    case 1:return "MWF>\r\n";
    case 2:return scenario==12?"MWF>\r\n":"Can't open file A:/A6400J.DAT\r\nMWF>\r\n";
    case 3:return scenario==13?"Write To A:/A6400J.DAT: Size\r\nwrite err 0x00000005\r\nMWF>\r\n":"Write To A:/A6400J.DAT: Size\r\nMWF>\r\n";
    case 4:return scenario==17?"File Contents Differ A:/A6400J.DAT, A:/A6400J.DAT\r\nMWF>\r\n":"MWF>\r\n";
    case 5:return scenario==18?"Fsys_Flush err 0x00000005\r\nMWF>\r\n":"Fsys_Flush OK\r\nMWF>\r\n";
    default:return "MWF>\r\n";
    }
}
int a6400_monitor_action(int argc,char **argv)
{
    calls++;
    if(!strcmp(argv[1],"--ack-preserved-prefix") && argc==4) {
        assert(!probes);assert(scenario>=11 || strstr((char *)files[0],"BG!"));native_acks++;return 0;
    }
    if(!strcmp(argv[1],"--probe-sd-info")) {
        assert(argc==2);probes++;a6400_monitor_published_end=20;
        return scenario==7?12:0;
    }
    if(!strcmp(argv[1],"--publish-journal")) {
        assert(argc==4 && scenario>=11);
        journal_step=(unsigned int)strtoul(argv[2],0,10);assert(journal_step<10);
        journal_publishes[journal_step]++;journal_published=1;
        a6400_monitor_published_end=40;return 0;
    }
    if(!strcmp(argv[1],"--sd-tables")) {assert(argc==2);return 0;}
    if(!strcmp(argv[1],"--ack-probe-prefix")) {
        assert(argc==5 && !strcmp(argv[4],journal_published?"40":"20"));acks++;return 0;
    }
    assert(argc==2 && !strcmp(argv[1],"--snapshot-output"));
    memset(&a6400_monitor_snapshot,0,sizeof(a6400_monitor_snapshot));
    if(scenario==5)return 7;
    if(scenario>=11) {
        if(!journal_published)return 0;
        const char *answer=journal_answer(journal_step);
        a6400_monitor_snapshot.header[0]=a6400_monitor_snapshot.header[1]=40;
        a6400_monitor_snapshot.header[3]=(unsigned int)strlen(answer);
        a6400_monitor_snapshot.size=(unsigned int)strlen(answer);
        memcpy(a6400_monitor_snapshot.data,answer,a6400_monitor_snapshot.size);
        return 0;
    }
    if(scenario>=6) {
        if(!probes) {
            prepeeks++;
            if(scenario>=9 && !native_acks) {
                a6400_monitor_snapshot.size=3;
                a6400_monitor_snapshot.header[3]=3;
                memcpy(a6400_monitor_snapshot.data,"BG!",3);
            }
            return 0;
        }
        static const char answer[]="result = 0x00000000\r\nfilesystemType = 0x0001\r\nMWF>\r\n";
        a6400_monitor_snapshot.header[0]=a6400_monitor_snapshot.header[1]=20;
        if(!snapshots++) {
            a6400_monitor_snapshot.size=sizeof(answer)-1;
            memcpy(a6400_monitor_snapshot.data,answer,sizeof(answer)-1);
            a6400_monitor_snapshot.header[3]=sizeof(answer)-1;
        }
        return 0;
    }
    a6400_monitor_snapshot.size=3;memcpy(a6400_monitor_snapshot.data,"abc",3);
    return 0;
}
int main(void)
{
    char *args[]={"collector","/tmp_bt/fixture.log","--sd-info",NULL};
    const int expected[]={0,3,4,9,9,0,0,11,11,0,11};
    for(scenario=0;scenario<11;scenario++) {
        memset(files,0,sizeof(files));memset(lengths,0,sizeof(lengths));calls=closed=syncs=acks=probes=snapshots=corrupted=native_acks=prepeeks=0;
        assert(collector_main(scenario>=6?3:2,args)==expected[scenario]);
        if(scenario==0 || scenario==5) {
            assert(lengths[0]==lengths[1] && !memcmp(files[0],files[1],lengths[0]));
            assert(strstr((char *)files[0],scenario==5?"captured=0":"captured=1"));
            assert(calls==(scenario==5?61u:1u));assert(closed==2);
        }
        if(scenario>=6)assert(probes==(scenario==10?0u:1u) && acks==((scenario==6 || scenario==9)?1u:0u));
        if(scenario>=9)assert(native_acks==(scenario==9?1u:0u));
    }
    /* Journal scenarios: 11 success, 12 pre-existing target abort, 13 write error. */
    for(scenario=11;scenario<14;scenario++) {
        char *jargs[]={"collector","/tmp_bt/fixture.log","--sd-journal",NULL};
        memset(files,0,sizeof(files));memset(lengths,0,sizeof(lengths));memset(journal_publishes,0,sizeof(journal_publishes));
        calls=closed=syncs=acks=probes=snapshots=journal_published=journal_step=0;
        int jrc=collector_main(3,jargs);
        assert(jrc==(scenario==11?0:11));
        assert(lengths[2] && strstr((char *)files[2],"JOURNAL_VERDICT"));
        assert(lengths[1]==64);
        if(scenario==11) {
            assert(strstr((char *)files[2],"mode=write steps=7 result=1"));
            for(unsigned int i=0;i<7;i++)assert(journal_publishes[i]==1);
        }
        if(scenario==12) {
            assert(journal_publishes[0]==1 && journal_publishes[1]==1 && journal_publishes[2]==1 && !journal_publishes[3]);
            assert(strstr((char *)files[2],"JOURNAL_VERDICT step=2") && !strstr((char *)files[2],"Write To"));
        }
        if(scenario==13) {
            assert(journal_publishes[3]==1 && !journal_publishes[4]);
            assert(strstr((char *)files[2],"JOURNAL_VERDICT step=3"));
        }
    }
    /* Probe scenario 14: live-table read plus three fixed read-only commands. */
    {
        char *pargs[]={"collector","/tmp_bt/fixture.log","--sd-probe",NULL};
        memset(files,0,sizeof(files));memset(lengths,0,sizeof(lengths));memset(journal_publishes,0,sizeof(journal_publishes));
        calls=closed=syncs=acks=probes=snapshots=journal_published=journal_step=0;
        assert(collector_main(3,pargs)==0);
        assert(lengths[2] && strstr((char *)files[2],"PROBE_SESSION_COMPLETE steps=3 result=1"));
        assert(strstr((char *)files[2],"PROBE_TABLES result=0"));
        assert(journal_publishes[7]==1 && journal_publishes[8]==1 && journal_publishes[9]==1);
    }
    /* Idle scenario 15: same file/process footprint, no /dev/mem access. */
    {
        char *iargs[]={"collector","/tmp_bt/fixture.log","--sd-idle",NULL};
        memset(files,0,sizeof(files));memset(lengths,0,sizeof(lengths));
        calls=closed=syncs=acks=probes=snapshots=journal_published=journal_step=0;
        assert(collector_main(3,iargs)==0);
        assert(lengths[2] && strstr((char *)files[2],"IDLE_SESSION_COMPLETE result=1"));
        assert(lengths[1]==64);
    }
    /* Verify scenarios 16 success and 17 readback differ. */
    for(scenario=16;scenario<18;scenario++) {
        char *vargs[]={"collector","/tmp_bt/fixture.log","--sd-journal-verify",NULL};
        memset(files,0,sizeof(files));memset(lengths,0,sizeof(lengths));memset(journal_publishes,0,sizeof(journal_publishes));
        calls=closed=syncs=acks=probes=snapshots=journal_published=journal_step=0;
        assert(collector_main(3,vargs)==(scenario==16?0:11));
        assert(lengths[2] && strstr((char *)files[2],"JOURNAL_SESSION_COMPLETE mode=verify steps=2"));
        assert(strstr((char *)files[2],scenario==16?"result=1":"result=0"));
        assert(journal_publishes[0]==1 && journal_publishes[4]==1);
        assert(lengths[1]==64);
    }
    /* Write scenario 18: flush failure stops the session after step 5. */
    {
        char *fargs[]={"collector","/tmp_bt/fixture.log","--sd-journal",NULL};
        scenario=18;
        memset(files,0,sizeof(files));memset(lengths,0,sizeof(lengths));memset(journal_publishes,0,sizeof(journal_publishes));
        calls=closed=syncs=acks=probes=snapshots=journal_published=journal_step=0;
        assert(collector_main(3,fargs)==11);
        assert(lengths[2] && strstr((char *)files[2],"JOURNAL_VERDICT step=5"));
        assert(journal_publishes[5]==1 && !journal_publishes[6]);
    }
    puts("Three journal, two verify, one flush-failure, one probe, one idle and eleven collector fault/receipt/query cases passed; mocked IO, not hardware proof");
    return 0;
}
