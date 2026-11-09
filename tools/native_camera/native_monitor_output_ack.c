/* Acknowledge preserved output, publish the fixed non-writing help probe, or
 * publish one fixed step of the bounded SD journal sequence. The journal path,
 * size and initial value are compile-time constants; only the validated
 * expected-file path is supplied by the caller. Native single-consumer cursor
 * protocol; not a multi-reader CAS or an exclusive input-producer certificate. */
#define _DEFAULT_SOURCE
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include "native_monitor_snapshot.h"

struct a6400_monitor_snapshot a6400_monitor_snapshot;
unsigned int a6400_monitor_published_end=0xffffffffu;
unsigned int a6400_monitor_sd_guard_stage;
#define A6400_JOURNAL_PATH "A:/A6400J.DAT"
#define A6400_JOURNAL_SIZE 64
#define A6400_JOURNAL_IVAL "0xE0235000"
#define A6400_JOURNAL_STEPS 10
/* Only the fresh run-owned RAM expected path is accepted; the journal commands
 * themselves stay fixed and never contain caller-supplied free text. */
static int a6400_mon_expected_path(const char *p)
{
    if(!p || strlen(p)>=180 || strncmp(p,"/tmp_bt/mon_sd_",15))return 0;
    for(int i=0;i<8;i++)if(p[15+i]<'0'||p[15+i]>'9')return 0;
    if(p[23]!='_')return 0;
    for(int i=0;i<6;i++)if(p[24+i]<'0'||p[24+i]>'9')return 0;
    return !strcmp(p+30,".expected");
}

int __attribute__((noinline)) a6400_mon_ack_check(const unsigned int h[4],unsigned int r,unsigned int w)
{
    return h && h[0]<0x400 && h[1]<0x400 && h[0]==h[1] &&
        h[2]<0x7bf0 && h[3]<0x7bf0 && h[2]==r && h[3]==w;
}
int __attribute__((noinline)) a6400_mon_probe_ack_check(const unsigned int h[4],unsigned int r,unsigned int w,unsigned int input_end)
{
    return h && h[0]<0x400 && h[1]<0x400 && input_end<0x400 && h[1]==input_end &&
        h[2]<0x7bf0 && h[3]<0x7bf0 && h[2]==r && h[3]==w;
}
/* Native SPSC producer may append behind a preserved prefix. With the same
 * read cursor it cannot lap/overwrite that prefix (one slot remains unused).
 * This is not a certificate against a separate consumer or cursor ABA. */
int __attribute__((noinline)) a6400_mon_prefix_ack_check(const unsigned int h[4],unsigned int r,unsigned int w,unsigned int input_end)
{
    if(!h || r>=0x7bf0 || w>=0x7bf0 || h[0]>=0x400 || h[1]>=0x400 ||
       h[2]!=r || h[3]>=0x7bf0)return 0;
    if(input_end==0xffffffffu) {if(h[0]!=h[1])return 0;}
    else if(input_end>=0x400 || h[1]!=input_end)return 0;
    return (w+0x7bf0-r)%0x7bf0 <= (h[3]+0x7bf0-r)%0x7bf0;
}
static int exact(int fd,unsigned int address,void *data,unsigned int size)
{return pread(fd,data,size,address)==(ssize_t)size ? 0:-1;}
/* Read-only admission for one fixed SD information query. Values are resolved
 * from fresh mappings by the caller; this is not a filesystem-owner token. */
int a6400_mon_sd_identity(int mem,unsigned int mwf,unsigned int fs)
{
    static const unsigned char prefix[16]={0x2d,0xe9,0xf0,0x4f,0x01,0x28,0x4a,0x4c,0x99,0xb0,0x0a,0xaf,0x7c,0x44,0x40,0xf3};
    unsigned char code[16],device[10],name[13],prefix_text[8],first;
    unsigned int table,status,drive,sub,user,prefix_cell,first_cell,row[3];unsigned short state;
    a6400_monitor_sd_guard_stage=1;
    if(!mwf || !fs || mwf>0xfff00000u || fs>0xfff00000u ||
       exact(mem,fs+0x1583c,code,16) || memcmp(code,prefix,16))return 0;
    a6400_monitor_sd_guard_stage=2;
    if(
       exact(mem,fs+0x6bff0,&table,4) || !table || exact(mem,table,&drive,4) ||
       !drive || drive>0xfffff000u || exact(mem,drive+0x954,device,10) || memcmp(device,"/dev/mmca",10))return 0;
    a6400_monitor_sd_guard_stage=3;
    if(exact(mem,fs+0x6c034,&status,4) || !status || exact(mem,status,&state,2) || state!=1)return 0;
    a6400_monitor_sd_guard_stage=4;
    if(
       exact(mem,fs+0x6bfe8,&sub,4) || !sub || sub>0xfffff000u ||
       exact(mem,sub+60,row,12) || row[1]!=fs+0x1583d ||
       exact(mem,row[0],name,13) || memcmp(name,"getdriveinfo",13))return 0;
    a6400_monitor_sd_guard_stage=5;
    if(
       exact(mem,mwf+0x418d8,&prefix_cell,4) || !prefix_cell ||
       exact(mem,prefix_cell,prefix_text,8) || memcmp(prefix_text,"\0\0\0\0\0\0\0",8) ||
       exact(mem,mwf+0x419f0,&first_cell,4) || !first_cell || exact(mem,first_cell,&first,1) || first ||
       exact(mem,mwf+0x41940,&user,4) || !user || user>0xfffff000u)return 0;
    a6400_monitor_sd_guard_stage=6;
    unsigned int matches=0;
    for(unsigned int i=0;i<129;i++) {
        if(exact(mem,user+12*i,row,12))return 0;
        if(!row[0])continue;
        if(exact(mem,row[0],name,6))return 0;
        if(!memcmp(name,"IFSYS",6)) {
            if(row[1]!=fs+0x15c61)return 0;
            matches++;
        }
    }
    if(matches!=1)return 0;
    a6400_monitor_sd_guard_stage=0;return 1;
}
#ifdef A6400_MONITOR_EMBEDDED
int a6400_monitor_action(int argc,char **argv)
#else
int main(int argc,char **argv)
#endif
{
#ifndef A6400_MONITOR_EMBEDDED
    setvbuf(stdout,NULL,_IONBF,0);
    setvbuf(stderr,NULL,_IONBF,0);
#endif
    static const unsigned char code[16]={0x98,0xb5,0x00,0xaf,0x07,0x4b,0x08,0x4a,0x7b,0x44,0x9c,0x58,0x20,0x68,0xf7,0xf7};
    int probe=argc==2 && !strcmp(argv[1],"--probe-help");
    a6400_monitor_published_end=0xffffffffu;
    a6400_monitor_sd_guard_stage=0;
    int sd=argc==2 && !strcmp(argv[1],"--probe-sd-info");
    probe=probe || sd;
    int journal=argc==4 && !strcmp(argv[1],"--publish-journal");
    int tables=argc==2 && !strcmp(argv[1],"--sd-tables");
    int step=0;const char *expected=0;
    int snapshot=argc==2 && !strcmp(argv[1],"--snapshot-output");
    memset(&a6400_monitor_snapshot,0,sizeof(a6400_monitor_snapshot));
    int prefix=(argc==4 && !strcmp(argv[1],"--ack-preserved-prefix")) ||
               (argc==5 && !strcmp(argv[1],"--ack-probe-prefix"));
    int pump=argc==5 && (!strcmp(argv[1],"--ack-probe-output") || !strcmp(argv[1],"--ack-probe-prefix"));
    if(!probe && !snapshot && !prefix && !pump && !journal && !tables && (argc!=4 || strcmp(argv[1],"--ack-preserved-output")))return 2;
    char *tail;unsigned long r=0,w=0,input_end=0;
    if(journal){
        step=(int)strtoul(argv[2],&tail,10);if(*tail || step<0 || step>=A6400_JOURNAL_STEPS ||
           !a6400_mon_expected_path(argv[3]))return 2;
        expected=argv[3];
    }
    if(!probe && !snapshot && !journal) {
        r=strtoul(argv[2],&tail,10);if(*tail || r>=0x7bf0)return 2;
        w=strtoul(argv[3],&tail,10);if(*tail || w>=0x7bf0)return 2;
        if(pump){input_end=strtoul(argv[4],&tail,10);if(*tail || input_end>=0x400)return 2;}
    }
    unsigned int base=0,fsbase=0,start,end,offset;char line[512],perms[8];
    FILE *maps=fopen("/proc/149/maps","r");if(!maps)return 3;
    while(fgets(line,sizeof(line),maps)) {
      if((sd || journal || tables) && strstr(line,"/usr/lib/libInfraFsys.so") &&
         sscanf(line,"%x-%x %7s %x",&start,&end,perms,&offset)==4 && !offset && strchr(perms,'x')) {
          if(fsbase){fclose(maps);return 3;}fsbase=start;
      }
      if(strstr(line,"/usr/lib/libMWF.so") &&
        sscanf(line,"%x-%x %7s %x",&start,&end,perms,&offset)==4 && !offset && strchr(perms,'x')) {
        if(base){fclose(maps);return 3;}base=start;
      }
    }
    fclose(maps);if(!base)return 3;
    int mem=open("/proc/149/mem",O_RDONLY);if(mem<0)return 4;
    unsigned char observed[16];unsigned int cells[3],ptrs[3],in[4],out[4];
    const unsigned int got[3]={0x41950,0x41830,0x41a2c};
    if(exact(mem,base+0x251c0,observed,16) || memcmp(code,observed,16)){close(mem);return 4;}
    if(tables) {
        static const unsigned char fs_code[16]={0x2d,0xe9,0xf0,0x4f,0x01,0x28,0x4a,0x4c,0x99,0xb0,0x0a,0xaf,0x7c,0x44,0x40,0xf3};
        unsigned char fsc[16],dev[32];unsigned int words[52],table=0,drive=0;unsigned char letter=0,devlen=0;
        if(!fsbase || exact(mem,fsbase+0x1583c,fsc,16) || memcmp(fsc,fs_code,16)) {
            printf("SD_TABLES unmapped no_read\n");close(mem);return 4;
        }
        if(exact(mem,fsbase+0xa9998,words,sizeof(words))) {
            printf("SD_TABLES read_failed no_read\n");close(mem);return 4;
        }
        printf("SD_TABLES fsbase=%08x g_fsys=%08x\n",fsbase,fsbase+0xa9998);
        for(unsigned int i=0;i<52;i++)if(words[i])
            printf("SD_TABLE idx=%u role=%s ptr=%08x\n",i,i<26?"letter":"device",words[i]);
        if(!exact(mem,fsbase+0x6bff0,&table,4) && table && !exact(mem,table,&drive,4) && drive &&
           !exact(mem,drive+10,&letter,1) && !exact(mem,drive+0x973,&devlen,1) && devlen<31 &&
           !exact(mem,drive+0x954,dev,31)) {
            dev[31]=0;
            printf("SD_MOUNT drive=%08x letter=%02x devlen=%u device=%s\n",drive,letter,devlen,dev);
        }
        close(mem);return 0;
    }
    for(unsigned int i=0;i<3;i++)if(exact(mem,base+got[i],&cells[i],4) || !cells[i] ||
        exact(mem,cells[i],&ptrs[i],4) || !ptrs[i]){close(mem);return 4;}
    if(exact(mem,ptrs[0],in,16) || exact(mem,ptrs[1],out,16)){close(mem);return 4;}
    unsigned int b=ptrs[2];
    if(b>0xffff8000u || in[0]!=b || in[1]!=b+4 || in[2]!=b+16 || in[3]!=0x400 ||
       out[0]!=b+8 || out[1]!=b+12 || out[2]!=b+0x410 || out[3]!=0x7bf0){close(mem);return 5;}
    maps=fopen("/proc/149/maps","r");if(!maps){close(mem);return 5;}
    unsigned int physical=0,matches=0;
    while(fgets(line,sizeof(line),maps))if(strstr(line,"/dev/mem") &&
        sscanf(line,"%x-%x %7s %x",&start,&end,perms,&offset)==4 && start<=b &&
        (uint64_t)b+0x8000<=end) {
        uint64_t p=(uint64_t)offset+b-start;
        if(p+0x8000>0x80000000u){fclose(maps);close(mem);return 5;}
        physical=(unsigned int)p;matches++;
    }
    fclose(maps);if(matches!=1 || (physical&3u)){close(mem);return 5;}
    int fd=open("/dev/mem",(snapshot ? O_RDONLY:O_RDWR)|O_SYNC);if(fd<0){close(mem);return 6;}
    unsigned int before[4],again[4],after[4],in_again[4],out_again[4];
    if(exact(fd,physical,before,16))goto reject;
    if(snapshot) {
        if(before[0]>=0x400 || before[1]>=0x400 || before[2]>=0x7bf0 || before[3]>=0x7bf0)goto reject;
        unsigned int count=(before[3]+0x7bf0-before[2])%0x7bf0;
        unsigned int first=0x7bf0-before[2];if(first>count)first=count;
        if(exact(fd,physical+0x410+before[2],a6400_monitor_snapshot.data,first) ||
           (count>first && exact(fd,physical+0x410,a6400_monitor_snapshot.data+first,count-first)))goto reject;
        a6400_monitor_snapshot.size=count;
    } else if(probe || journal) {
        if(!a6400_mon_ack_check(before,before[2],before[3]) || before[2]!=before[3])goto reject;
    } else if(prefix ? !a6400_mon_prefix_ack_check(before,(unsigned int)r,(unsigned int)w,pump?(unsigned int)input_end:0xffffffffu) :
              pump ? !a6400_mon_probe_ack_check(before,(unsigned int)r,(unsigned int)w,(unsigned int)input_end) :
                     !a6400_mon_ack_check(before,(unsigned int)r,(unsigned int)w))goto reject;
    usleep(20000);
    if(exact(fd,physical,again,16))goto reject;
    if(prefix) {
        if(!a6400_mon_prefix_ack_check(again,(unsigned int)r,(unsigned int)w,pump?(unsigned int)input_end:0xffffffffu) ||
           (again[3]+0x7bf0-(unsigned int)r)%0x7bf0 < (before[3]+0x7bf0-(unsigned int)r)%0x7bf0 ||
           (!pump && (before[0]!=again[0] || before[1]!=again[1])))goto reject;
    } else if(memcmp(before,again,16))goto reject;
    if(
       exact(mem,ptrs[0],in_again,16) || memcmp(in,in_again,16) ||
       exact(mem,ptrs[1],out_again,16) || memcmp(out,out_again,16))goto reject;
    for(unsigned int i=0;i<3;i++) {
        unsigned int cell,ptr;
        if(exact(mem,base+got[i],&cell,4) || cell!=cells[i] || exact(mem,cell,&ptr,4) || ptr!=ptrs[i])goto reject;
    }
    if(snapshot) {
        memcpy(a6400_monitor_snapshot.header,before,sizeof(before));
        printf("SNAPSHOT_OK bytes=%u input=%u/%u output=%u/%u no_write\n",
            a6400_monitor_snapshot.size,before[0],before[1],before[2],before[3]);
        close(fd);close(mem);return 0;
    }
    if(probe || journal) {
        char command[512];unsigned int count;
        if(probe) snprintf(command,sizeof(command),"%s",sd?"IFSYS getdriveinfo A\r":"? GETHOME\r");
        else {
            switch(step) {
            case 0: snprintf(command,sizeof(command),"IFSYS getdriveinfo A\r");break;
            case 1: snprintf(command,sizeof(command),"IFSYS cmp %s %s\r",expected,expected);break;
            case 2: snprintf(command,sizeof(command),"IFSYS cmp %s %s\r",A6400_JOURNAL_PATH,A6400_JOURNAL_PATH);break;
            case 3: snprintf(command,sizeof(command),"IFSYS writeandflash %s %d %s\r",A6400_JOURNAL_PATH,A6400_JOURNAL_SIZE,A6400_JOURNAL_IVAL);break;
            case 4: snprintf(command,sizeof(command),"IFSYS cmp %s %s\r",expected,A6400_JOURNAL_PATH);break;
            case 5: snprintf(command,sizeof(command),"IFSYS flush %s\r",A6400_JOURNAL_PATH);break;
            case 6: snprintf(command,sizeof(command),"IFSYS cmp %s %s\r",expected,A6400_JOURNAL_PATH);break;
            case 7: snprintf(command,sizeof(command),"IFSYS ls /dev/mmca/\r");break;
            case 8: snprintf(command,sizeof(command),"IFSYS dump /dev/mmca/A6400J.DAT\r");break;
            case 9: snprintf(command,sizeof(command),"IFSYS dump %s\r",A6400_JOURNAL_PATH);break;
            default: goto reject;
            }
        }
        count=(unsigned int)strlen(command);if(!count || count>=sizeof(command))goto reject;
        unsigned int cursor_cell,mode_cell,table_address,cursor,mode,row[3];unsigned char name[2],help[5];
        if(exact(mem,base+0x419c4,&cursor_cell,4) || exact(mem,base+0x419dc,&mode_cell,4) ||
           exact(mem,base+0x4197c,&table_address,4) || !cursor_cell || !mode_cell || !table_address ||
           exact(mem,cursor_cell,&cursor,4) || cursor || exact(mem,mode_cell,&mode,4) || mode)goto reject;
        if(sd || journal) {if(!a6400_mon_sd_identity(mem,base,fsbase))goto reject;}
        else if(exact(mem,table_address+240,row,12) || row[1]!=base+0x24119 ||
           exact(mem,row[0],name,2) || memcmp(name,"?",2) || exact(mem,row[2],help,5) || memcmp(help,"HELP",5))goto reject;
        unsigned int start_at=before[1],first=0x400-start_at;
        if(first>count)first=count;
        if(pwrite(fd,command,first,physical+16+start_at)!=(ssize_t)first ||
           (count>first && pwrite(fd,command+first,count-first,physical+16)!=(ssize_t)(count-first))) {
            printf("PROBE_DATA_UNCONFIRMED not_published no_retry\n");close(fd);close(mem);return 10;
        }
        if(exact(fd,physical,again,16) || memcmp(before,again,16) ||
           exact(mem,cursor_cell,&cursor,4) || cursor || exact(mem,mode_cell,&mode,4) || mode ||
           ((sd||journal) && !a6400_mon_sd_identity(mem,base,fsbase))) {
            printf("PROBE_PREPUBLISH_CHANGED not_published no_retry\n");close(fd);close(mem);return 11;
        }
        unsigned int target=(start_at+count)%0x400;
        __sync_synchronize();ssize_t n=pwrite(fd,&target,4,physical+4);
        if(n!=4){printf("PROBE_PUBLISH_UNCONFIRMED no_retry\n");close(fd);close(mem);return 12;}
        a6400_monitor_published_end=target;
        if(journal) printf("JOURNAL_PUBLISHED step=%d bytes=%u input_end=%u command=IFSYS_FIXED result_not_yet_known\n",step,count,target);
        else printf("PROBE_PUBLISHED bytes=%u input_end=%u command=%s result_not_yet_known\n",count,target,sd?"IFSYS_GETDRIVEINFO_A":"HELP_GETHOME");
        close(fd);close(mem);return 0;
    }
    if(r==w){printf("ACK_EMPTY no_write\n");close(fd);close(mem);return 0;}
    /* Caller has durably preserved exactly the snapshot ending at w. Never
     * update producer/input cursors or roll back over a concurrent consumer. */
    unsigned int target=(unsigned int)w;
    __sync_synchronize();
    ssize_t n=pwrite(fd,&target,4,physical+8);
    if(n!=4){printf("ACK_WRITE_UNCONFIRMED bytes=%ld errno=%d no_retry\n",(long)n,errno);close(fd);close(mem);return 8;}
    if(exact(fd,physical,after,16) || after[2]!=target){printf("ACK_POSTSTATE_UNCONFIRMED no_retry\n");close(fd);close(mem);return 9;}
    printf("ACK_OK physical=%08x previous_read=%lu preserved_end=%lu input=%u/%u output=%u/%u\n",physical,r,w,after[0],after[1],after[2],after[3]);
    close(fd);close(mem);return 0;
reject:
    memset(&a6400_monitor_snapshot,0,sizeof(a6400_monitor_snapshot));
    printf("ACK_REJECTED no_write sd_guard_stage=%u\n",a6400_monitor_sd_guard_stage);close(fd);close(mem);return 7;
}
