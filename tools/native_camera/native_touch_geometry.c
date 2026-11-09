/* Read-only coupled held-touch/menu geometry. No application calls or hooks. */
#define main retained_resource_observer_main
#include "native_layout_resource_snapshot_v12.c"
#undef main

/* Source-derived WidgetBase::getParent path: widget+4 tree node, parent at
   node+0xc with low tag bits, parent's +0x18 points back to its widget. A
   parent without its own parent is the outer sentinel, not another widget. */
static int capture_ancestors(int fd,uint32_t widget) {
    uint32_t seen[48];unsigned count=0;
    while(count<48) {
        for(unsigned i=0;i<count;i++)if(seen[i]==widget)return -193;
        seen[count++]=widget;
        unsigned char *current=capture(fd,widget,0xa0);if(!current)return -194;
        uint32_t parent=field(current,0x10)&~3u;
        if(!parent)break;
        unsigned char *node=capture(fd,parent,32);if(!node)return -195;
        if(!(field(node,12)&~3u))break;
        widget=field(node,0x18);
        unsigned char *next=capture(fd,widget,0xa0);
        if(!next || field(next,4)!=0x7063b28 || field(next,0x1c)!=widget)return -196;
    }
    if(count>=48)return -197;
    printf("ANCESTORS widgets=%u result=0\n",count);return 0;
}
static int locate(int fd,uint32_t *menu) {
    uint32_t system,node,layer,owner,next,container=0x956f0+0x484;
    if(readword(fd,0x7108058,&system) || system!=0x956f0 || readword(fd,container+0xc,&node))return -180;
    visited=0;
    for(unsigned n=0;node!=container+0x10;n++) {
        if(n>=64 || readword(fd,node,&layer) || readword(fd,node+4,&owner) ||
           readword(fd,node+0xc,&next) || owner!=container)return -181;
        int rc=menu_walk(fd,layer+0x18,0,menu);if(rc)return rc;
        node=next;
    }
    return 0;
}
static int coupled(int preflight_only) {
    int result=freeze_process(),fd=-1;if(result)return result;
    fd=open("/proc/149/mem",O_RDONLY);if(fd<0){result=-182;goto done;}
    unsigned char *mouse=capture(fd,0x956f0+0x4a8,80);
    if(!mouse || !capture(fd,0x7108058,4)){result=-183;goto done;}
    uint32_t tls=0;
    if(ptrace(22,380,0,&tls) || tls<0x144c0 || tls>0x5effff00 ||
       !capture(fd,tls,0x60) || !capture(fd,tls-0x4c0+0x60,16)){result=-184;goto done;}
    printf("UI_TLS tid=380 value=%08x\n",tls);
    int16_t x,y,rawx,rawy;memcpy(&x,mouse,2);memcpy(&y,mouse+2,2);
    memcpy(&rawx,mouse+4,2);memcpy(&rawy,mouse+6,2);
    printf("MOUSE framebuffer=%d,%d raw=%d,%d buttons=%08x\n",x,y,rawx,rawy,field(mouse,8));
    if(preflight_only){result=0;goto done;}
    if(rawx==32767 || rawy==32767 || !(field(mouse,8)&1)){result=1;goto done;}
    uint32_t menu=0;result=locate(fd,&menu);if(result!=1){result=result?result:1;goto done;}
    unsigned char *state=capture(fd,menu,0x186bc);
    if(!state || field(state,0)!=0x15f1f1d0 || field(state,0x1c)!=menu){result=-185;goto done;}
    result=capture_ancestors(fd,menu);if(result)goto done;
    if(!capture(fd,0x709a38c,4)){result=-198;goto done;}
    printf("REFRESH_GLOBAL address=0709a38c result=0\n");
    unsigned char *slot=capture(fd,0x7107f34,4);if(!slot){result=-186;goto done;}
    result=capture_registry(fd,field(slot,0),0xaadca2c7,0);if(result)goto done;
    result=capture_model(fd,field(state,0x186ac));if(result)goto done;
    if(!capture(fd,0x15f1f1d0,512)){result=-187;goto done;}
    for(unsigned row=0;row<6;row++) {
        unsigned char *widget=capture(fd,menu+0x9350+row*0x1118,0xa0);
        if(!widget || !capture(fd,field(widget,0),256)){result=-188;goto done;}
    }
    printf("COUPLED menu=%08x provider=%08x mode=%u focus=%u cached_row=%d records=%u bytes=%u\n",
        menu,field(state,0x186ac),state[0x21],state[0x1d8],(int)field(state,0x1f8),record_count,used);
    result=0;
done:
    if(fd>=0)close(fd);
    if(freeze_resume())result=-99;
    return result;
}
int main(int argc,char **argv) {
    int pf=argc==2 && !strcmp(argv[1],"--preflight");
    if(argc!=1 && !pf)return 2;
    char comm[32]={0};FILE *identity=fopen("/proc/149/comm","r");
    if(!identity)return 2;
    int valid=fgets(comm,sizeof(comm),identity) && !strcmp(comm,"im.elf\n");fclose(identity);if(!valid)return 2;
    if(pf){
        struct statvfs space;int rc=statvfs("/tmp_bt",&space)?-189:0;
        if(!rc)printf("SPACE free=%llu reserve=32768\n",(unsigned long long)space.f_bavail*space.f_frsize);
        if(!rc)rc=coupled(1);
        printf("PREFLIGHT result=%d\n",rc);fflush(stdout);return rc?5:0;
    }
    int lock=open("/tmp_bt/native_touch_geometry.lock",O_WRONLY|O_CREAT,0600);
    struct flock lease={0};lease.l_type=F_WRLCK;lease.l_whence=SEEK_SET;
    if(lock<0 || fcntl(lock,F_SETLK,&lease))return 3;
    signal(SIGHUP,SIG_IGN);setsid();
    printf("NATIVE_TOUCH_GEOMETRY pid=%d read_only=1 max_wait=1800 interval_us=500000 no_app_calls=1 dma_atomic=0\n",getpid());fflush(stdout);
    int result=1,fd=open("/proc/149/mem",O_RDONLY);
    if(fd<0){close(lock);return 4;}
    for(unsigned attempt=0;attempt<1800;attempt++) {
        if(!access("/tmp_bt/native_touch_geometry.stop",F_OK))break;
        uint32_t raw,buttons;
        if(!readword(fd,0x956f0+0x4ac,&raw) && !readword(fd,0x956f0+0x4b0,&buttons) &&
           (raw&65535)!=32767 && (raw>>16)!=32767 && (buttons&1)) {
            used=record_count=seen_view_count=0;
            result=coupled(0);
            printf("ATTEMPT index=%u result=%d\n",attempt,result);fflush(stdout);
            if(result<=0)break;
        }
        if(attempt%20==0){printf("WAIT attempt=%u result=%d\n",attempt,result);fflush(stdout);}
        usleep(500000);
    }
    close(fd);
    if(!result) {
        uint32_t header[4]={0x534c4159,2,record_count,used};
        unsigned required=sizeof(header)+record_count*sizeof(records[0])+used;
        struct statvfs space;
        if(statvfs("/tmp_bt",&space) || (uint64_t)space.f_bavail*space.f_frsize<required+32768u)result=-189;
        else {
            FILE *f=fopen("/tmp_bt/native_touch_geometry.bin","wb");
            if(!f)result=-190;
            else {
                if(fwrite(header,1,sizeof(header),f)!=sizeof(header) ||
                   fwrite(records,sizeof(records[0]),record_count,f)!=record_count ||
                   fwrite(bytes,1,used,f)!=used || fflush(f) || fsync(fileno(f)))result=-191;
                if(fclose(f))result=-192;
            }
        }
        printf("BINARY result=%d bytes=%u records=%u\n",result,required,record_count);
    }
    printf("END result=%d\n",result);int output_error=fflush(stdout)||ferror(stdout);close(lock);
    return result || output_error?5:0;
}
