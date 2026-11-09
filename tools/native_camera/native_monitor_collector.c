/* Bounded collector with passive, fixed SD-info and fixed SD-journal modes.
 * Keeps its own RAM inode open across ordinary mode transitions; the journal
 * commands are fixed compile-time text and the expected-file path is validated.
 * No arbitrary command text; no filesystem mount or raw storage write. */
#define _DEFAULT_SOURCE
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include "native_monitor_snapshot.h"
int a6400_monitor_action(int argc,char **argv);

#define A6400_JOURNAL_PATH "A:/A6400J.DAT"
#define A6400_JOURNAL_SIZE 64
#define A6400_JOURNAL_IVAL 0xE0235000ull
#define JOURNAL_ANSWER 16384
static unsigned int log_capacity=32768;

static int write_all(int fd,const void *buffer,unsigned int size)
{
    const unsigned char *p=buffer;
    while(size) {
        ssize_t n=write(fd,p,size);
        if(n<0 && errno==EINTR)continue;
        if(n<=0)return -1;
        p+=n;size-=(unsigned int)n;
    }
    return 0;
}
static int preserve(int fd,const void *buffer,unsigned int size,unsigned int *total)
{
    unsigned char check[256];const unsigned char *p=buffer;
    unsigned int start=*total;
    if(size>log_capacity-*total || write_all(fd,buffer,size))return -1;
    *total+=size;
    if(fsync(fd))return -1;
    for(unsigned int offset=0;offset<size;) {
        unsigned int count=size-offset;if(count>sizeof(check))count=sizeof(check);
        if(pread(fd,check,count,start+offset)!=(ssize_t)count || memcmp(check,p+offset,count))return -1;
        offset+=count;
    }
    return 0;
}
static int expected_path(const char *log,char *out,unsigned int size)
{
    unsigned int n=strlen(log);
    if(n<5 || strcmp(log+n-4,".log") || n-4+10>size)return -1;
    memcpy(out,log,n-4);memcpy(out+n-4,".expected",10);return 0;
}
static int create_expected(const char *path)
{
    unsigned char data[A6400_JOURNAL_SIZE],check[16];
    for(unsigned int i=0;i<A6400_JOURNAL_SIZE/8;i++) {
        uint64_t value=A6400_JOURNAL_IVAL+i;
        for(unsigned int b=0;b<8;b++)data[i*8+b]=(unsigned char)(value>>(8*b));
    }
    int fd=open(path,O_RDWR|O_CREAT|O_EXCL,0600);if(fd<0)return -1;
    if(write_all(fd,data,sizeof(data)) || fsync(fd)){close(fd);return -1;}
    for(unsigned int offset=0;offset<sizeof(data);) {
        unsigned int count=sizeof(data)-offset;if(count>sizeof(check))count=sizeof(check);
        if(pread(fd,check,count,offset)!=(ssize_t)count || memcmp(check,data+offset,count)){close(fd);return -1;}
        offset+=count;
    }
    close(fd);return 0;
}
/* Exact verdicts for the fixed sequence. Silence after cmp is only a match if
 * no failure text is present; the command prompt is the completion marker. */
static int journal_step_ok(unsigned int step,const char *answer)
{
    switch(step) {
    case 0: return strstr(answer,"result = 0x00000000") && strstr(answer,"filesystemType   = 0x0003");
    case 1: return !strstr(answer,"Can't open file") && !strstr(answer,"Differ") && !strstr(answer,"illegal");
    case 2: return strstr(answer,"Can't open file") && strstr(answer,A6400_JOURNAL_PATH);
    case 3: return strstr(answer,"Write To ") && strstr(answer,A6400_JOURNAL_PATH) &&
                   !strstr(answer,"write err") && !strstr(answer,"Fsys_Open err");
    case 4: case 6: return !strstr(answer,"Differ") && !strstr(answer,"Can't open file") && !strstr(answer,"illegal");
    case 5: return strstr(answer,"Fsys_Flush OK") && !strstr(answer,"Fsys_Flush err");
    default: return 0;
    }
}
/* Publish one fixed step, preserving every output chunk before its prefix
 * acknowledgement; returns 0 only after the prompt was preserved. */
static int journal_cmd(int fd,unsigned int *total,unsigned int step,const char *expected,char *answer,unsigned int *used)
{
    unsigned int endpoint=0xffffffffu;int published=0;char line[240],step_text[8];
    snprintf(step_text,sizeof(step_text),"%u",step);
    answer[0]=0;*used=0;
    for(unsigned int second=0;second<=180;second++) {
        char *args[]={"monitor","--publish-journal",step_text,(char *)expected,NULL};
        int result=a6400_monitor_action(4,args);
        if(!result){endpoint=a6400_monitor_published_end;published=1;break;}
        if(result!=3 && result!=4 && result!=7)return -1;
        char *peek[]={"monitor","--snapshot-output",NULL};
        if(!a6400_monitor_action(2,peek) && a6400_monitor_snapshot.size) {
            const struct a6400_monitor_snapshot *s=&a6400_monitor_snapshot;
            unsigned int r=s->header[2],w=s->header[3];
            int n=snprintf(line,sizeof(line),"JOURNAL_PREOUTPUT step=%u bytes=%u output=%u/%u\n",step,s->size,r,w);
            if(preserve(fd,line,(unsigned int)n,total) || preserve(fd,s->data,s->size,total))return -1;
            char read_text[16],write_text[16];
            snprintf(read_text,sizeof(read_text),"%u",r);snprintf(write_text,sizeof(write_text),"%u",w);
            char *ack[]={"monitor","--ack-preserved-prefix",read_text,write_text,NULL};
            if(a6400_monitor_action(4,ack))return -1;
        }
        if(second<180)sleep(1);
    }
    if(!published)return -1;
    for(unsigned int second=0;second<=60;second++) {
        char *peek[]={"monitor","--snapshot-output",NULL};
        int result=a6400_monitor_action(2,peek);
        if(!result && a6400_monitor_snapshot.size) {
            const struct a6400_monitor_snapshot *s=&a6400_monitor_snapshot;
            if(*used+s->size>=JOURNAL_ANSWER)return -1;
            unsigned int r=s->header[2],w=s->header[3];
            int n=snprintf(line,sizeof(line),"JOURNAL_CHUNK step=%u bytes=%u input=%u/%u output=%u/%u\n",step,s->size,s->header[0],s->header[1],r,w);
            if(preserve(fd,line,(unsigned int)n,total) || preserve(fd,s->data,s->size,total))return -1;
            memcpy(answer+*used,s->data,s->size);*used+=s->size;answer[*used]=0;
            char read_text[16],write_text[16],end_text[16];
            snprintf(read_text,sizeof(read_text),"%u",r);snprintf(write_text,sizeof(write_text),"%u",w);
            snprintf(end_text,sizeof(end_text),"%u",endpoint);
            char *ack[]={"monitor","--ack-probe-prefix",read_text,write_text,end_text,NULL};
            if(a6400_monitor_action(5,ack))return -1;
            if(strstr(answer,"MWF>"))return 0;
        }
        if(second<60)sleep(1);
    }
    return -1;
}
static int sd_journal(int fd,unsigned int *total,const char *expected,int verify)
{
    static const unsigned int write_steps[]={0,1,2,3,4,5,6};
    static const unsigned int verify_steps[]={0,4};
    const unsigned int *steps=verify?verify_steps:write_steps;
    unsigned int count=verify?2:7,used,step,result=0;
    char answer[JOURNAL_ANSWER],line[220];
    for(unsigned int i=0;i<count;i++) {
        step=steps[i];used=0;
        if(journal_cmd(fd,total,step,expected,answer,&used)) {
            int n=snprintf(line,sizeof(line),"JOURNAL_STEP step=%u published=0 result=0\n",step);
            if(preserve(fd,line,(unsigned int)n,total))return -1;
            goto done;
        }
        int ok=journal_step_ok(step,answer);
        int n=snprintf(line,sizeof(line),"JOURNAL_VERDICT step=%u bytes=%u ok=%d\n",step,used,ok);
        if(preserve(fd,line,(unsigned int)n,total))return -1;
        if(!ok)goto done;
    }
    result=1;
done:
    {
        int n=snprintf(line,sizeof(line),"JOURNAL_SESSION_COMPLETE mode=%s steps=%u result=%u\n",verify?"verify":"write",count,result);
        if(preserve(fd,line,(unsigned int)n,total))return -1;
    }
    return result?1:-1;
}
/* Returns observed success only after the fixed query reply and final quiet
 * consumed-input snapshot. Publication/worker-wrapper return is insufficient. */
static int sd_query(int fd,unsigned int *total)
{
    unsigned int endpoint=0xffffffffu;int published=0;
    char line[200],answer[8192];unsigned int used=0;answer[0]=0;
    for(unsigned int second=0;second<=180;second++) {
        char *peek[]={"monitor","--snapshot-output",NULL};
        int observed=a6400_monitor_action(2,peek);
        if(!observed && a6400_monitor_snapshot.size) {
            const struct a6400_monitor_snapshot *s=&a6400_monitor_snapshot;
            if(s->header[0]!=s->header[1])return -1;
            unsigned int r=s->header[2],w=s->header[3];
            int n=snprintf(line,sizeof(line),"PREQUERY_NATIVE_OUTPUT bytes=%u output=%u/%u\n",s->size,r,w);
            if(preserve(fd,line,(unsigned int)n,total) || preserve(fd,s->data,s->size,total))return -1;
            char read_text[16],write_text[16];
            snprintf(read_text,sizeof(read_text),"%u",r);snprintf(write_text,sizeof(write_text),"%u",w);
            char *ack[]={"monitor","--ack-preserved-prefix",read_text,write_text,NULL};
            if(a6400_monitor_action(4,ack))return -1;
            if(second<180)sleep(1);
            continue;
        }
        char *args[]={"monitor","--probe-sd-info",NULL};
        int result=a6400_monitor_action(2,args);
        if(!result) {endpoint=a6400_monitor_published_end;published=1;break;}
        /* Only pre-publication identity/read rejection can be retried. Payload
         * or cursor uncertainty (10..12) is terminal, never resent. */
        if(result!=3 && result!=4 && result!=7)return -1;
        if(second<180)sleep(1);
    }
    int n=snprintf(line,sizeof(line),"SD_QUERY published=%d endpoint=%u result_not_yet_known\n",published,endpoint);
    if(preserve(fd,line,(unsigned int)n,total))return -1;
    if(!published || endpoint>=0x400)return 0;
    for(unsigned int second=0;second<=60;second++) {
        char *args[]={"monitor","--snapshot-output",NULL};
        int result=a6400_monitor_action(2,args);
        if(!result) {
            const struct a6400_monitor_snapshot *s=&a6400_monitor_snapshot;
            if(s->header[1]!=endpoint)return -1;
            if(s->size) {
                if(s->size>=sizeof(answer)-used)return -1;
                unsigned int r=s->header[2],w=s->header[3];
                n=snprintf(line,sizeof(line),"QUERY_CHUNK bytes=%u input=%u/%u output=%u/%u\n",s->size,s->header[0],s->header[1],r,w);
                if(preserve(fd,line,(unsigned int)n,total) || preserve(fd,s->data,s->size,total))return -1;
                memcpy(answer+used,s->data,s->size);used+=s->size;answer[used]=0;
                char read_text[16],write_text[16],end_text[16];
                snprintf(read_text,sizeof(read_text),"%u",r);snprintf(write_text,sizeof(write_text),"%u",w);
                snprintf(end_text,sizeof(end_text),"%u",endpoint);
                char *ack[]={"monitor","--ack-probe-prefix",read_text,write_text,end_text,NULL};
                if(a6400_monitor_action(5,ack))return -1;
            } else if(s->header[0]==endpoint && used && strstr(answer,"MWF>")) {
                return strstr(answer,"result = 0x00000000") && strstr(answer,"filesystemType") ? 1:-1;
            }
        }
        if(second<60)sleep(1);
    }
    return -1;
}
static int sd_probe(int fd,unsigned int *total,const char *expected)
{
    static const unsigned int steps[]={7,8,9};
    unsigned int used,step,result=0;
    char answer[JOURNAL_ANSWER],line[220];int n;
    for(unsigned int i=0;i<3;i++) {
        step=steps[i];used=0;
        if(journal_cmd(fd,total,step,expected,answer,&used)) {
            n=snprintf(line,sizeof(line),"PROBE_STEP step=%u published=0 result=0\n",step);
            if(preserve(fd,line,(unsigned int)n,total))return -1;
            goto done;
        }
        n=snprintf(line,sizeof(line),"PROBE_STEP step=%u bytes=%u result=1\n",step,used);
        if(preserve(fd,line,(unsigned int)n,total))return -1;
        /* Read the live tables only after the first command passed SD identity,
         * i.e. while the PC Remote volume association is active. */
        if(i==0) {
            char *tab[]={"monitor","--sd-tables",NULL};
            int tr=a6400_monitor_action(2,tab);
            n=snprintf(line,sizeof(line),"PROBE_TABLES result=%d\n",tr);
            if(preserve(fd,line,(unsigned int)n,total))return -1;
        }
    }
    result=1;
done:
    n=snprintf(line,sizeof(line),"PROBE_SESSION_COMPLETE steps=3 result=%u\n",result);
    if(preserve(fd,line,(unsigned int)n,total))return -1;
    return result?1:-1;
}
static int sd_idle(int fd,unsigned int *total)
{
    char line[120];
    sleep(90);
    int n=snprintf(line,sizeof(line),"IDLE_SESSION_COMPLETE result=1\n");
    if(preserve(fd,line,(unsigned int)n,total))return -1;
    return 1;
}
int main(int argc,char **argv)
{
    setvbuf(stdout,NULL,_IONBF,0);setvbuf(stderr,NULL,_IONBF,0);
    int query=argc==3 && !strcmp(argv[2],"--sd-info");
    int journal=argc==3 && (!strcmp(argv[2],"--sd-journal") || !strcmp(argv[2],"--sd-journal-verify"));
    int verify=journal && !strcmp(argv[2],"--sd-journal-verify");
    int probe_mode=argc==3 && !strcmp(argv[2],"--sd-probe");
    int idle=argc==3 && !strcmp(argv[2],"--sd-idle");
    if((argc!=2 && !query && !journal && !probe_mode && !idle) || strncmp(argv[1],"/tmp_bt/",8) || strstr(argv[1],"..") ||
       strlen(argv[1])>180 || !argv[1][8])return 2;
    char expected[220];
    if((journal || probe_mode || idle) && expected_path(argv[1],expected,sizeof(expected)))return 2;
    if(journal || probe_mode || idle)log_capacity=262144;
    int fd=open(argv[1],O_RDWR|O_CREAT|O_EXCL,0600);if(fd<0)return 3;
    if((journal || probe_mode || idle) && create_expected(expected)){close(fd);return 4;}
    char line[180];unsigned int total=0;
    int n=snprintf(line,sizeof(line),"MONITOR_COLLECTOR READY pid=%ld mode=%s bounded_RAM_log\n",(long)getpid(),query?"fixed_sd_info":probe_mode?"sd_probe":idle?"sd_idle":journal?(verify?"sd_journal_verify":"sd_journal"):"passive");
    if(write_all(fd,line,(unsigned int)n) || fsync(fd)){close(fd);return 4;}
    total+=(unsigned int)n;
    printf("%s",line);
    /* Let the mode transition and the PC Remote application settle before any
     * /dev/mem or monitor-ring access; the user is told to switch promptly. */
    if(journal || probe_mode)sleep(30);
    /* At most one full output snapshot: repeated non-consuming snapshots would
     * duplicate bytes and could fill the RAM log. No execution-success claim. */
    int captured=0;
    int query_result=0,journal_result=0,probe_result=0,idle_result=0;
    if(query)query_result=sd_query(fd,&total);
    else if(journal)journal_result=sd_journal(fd,&total,expected,verify);
    else if(probe_mode)probe_result=sd_probe(fd,&total,expected);
    else if(idle)idle_result=sd_idle(fd,&total);
    for(unsigned int second=0;!query && !journal && !probe_mode && !idle && second<=60;second++) {
        char *args[]={"monitor","--snapshot-output",NULL};
        int result=captured ? -1:a6400_monitor_action(2,args);
        if(!result && a6400_monitor_snapshot.size) {
            const struct a6400_monitor_snapshot *s=&a6400_monitor_snapshot;
            n=snprintf(line,sizeof(line),"SNAPSHOT second=%u bytes=%u input=%u/%u output=%u/%u\n",second,s->size,s->header[0],s->header[1],s->header[2],s->header[3]);
            if(write_all(fd,line,(unsigned int)n) || write_all(fd,s->data,s->size) ||
               write_all(fd,"\nEND_SNAPSHOT\n",14) || fsync(fd)){close(fd);return 5;}
            total+=(unsigned int)n+s->size+14;captured=1;
        }
        if(second<60)sleep(1);
    }
    if(!query && !journal && !probe_mode && !idle) {
        n=snprintf(line,sizeof(line),"MONITOR_COLLECTOR SAMPLES_COMPLETE captured=%d query=%d result=%d receipt_pending\n",captured,query,query_result);
        if(preserve(fd,line,(unsigned int)n,&total)){close(fd);return 6;}
    }
    /* Read back the held inode before copying to a fresh receipt pathname.
     * RAM fsync is not restart durability. Fail without deleting evidence. */
    if(total>log_capacity || lseek(fd,0,SEEK_SET)!=0){close(fd);return 7;}
    char receipt[200];snprintf(receipt,sizeof(receipt),"%s.receipt",argv[1]);
    int out=open(receipt,O_RDWR|O_CREAT|O_EXCL,0600);if(out<0){close(fd);return 8;}
    unsigned char buffer[1024],verify_bytes[1024];unsigned int copied=0;
    while(copied<total) {
        unsigned int count=total-copied;if(count>sizeof(buffer))count=sizeof(buffer);
        if(pread(fd,buffer,count,copied)!=(ssize_t)count || write_all(out,buffer,count) ||
           pread(out,verify_bytes,count,copied)!=(ssize_t)count || memcmp(buffer,verify_bytes,count)) {
            close(out);close(fd);return 9;
        }
        copied+=count;
    }
    int result=fsync(out)?10:0;
    if(!result)printf("MONITOR_COLLECTOR RECEIPT_VERIFIED bytes=%u captured=%d query_result=%d RAM_only\n",total,captured,query_result);
    if(!result && query && query_result!=1)result=11;
    if(!result && journal && journal_result!=1)result=11;
    if(!result && probe_mode && probe_result!=1)result=11;
    if(!result && idle && idle_result!=1)result=11;
    close(out);close(fd);return result;
}
