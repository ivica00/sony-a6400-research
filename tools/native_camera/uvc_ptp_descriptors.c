/* Native descriptor-layout candidate, intentionally separate from the live
 * module. The original Sony kernel serializer is used for offline validation.
 * No assumption about live driver registration or sensor/DMM ownership. */
#include "uvc_ptp_descriptors.h"
#include "zve10_uvc_tree.h"

_Static_assert(sizeof(void *) == 4, "ARM32 descriptor ABI");
_Static_assert(sizeof(struct a6400_candidate_endpoint) == 20, "endpoint ABI");
_Static_assert(sizeof(struct a6400_candidate_alternate) == 20, "alternate ABI");
_Static_assert(sizeof(struct a6400_candidate_interface) == 8, "interface ABI");
_Static_assert(sizeof(struct a6400_candidate_config) == 24, "config ABI");
_Static_assert(sizeof(struct a6400_candidate_device) == 16, "speed table ABI");
_Static_assert(__builtin_offsetof(struct a6400_uvc_ptp_candidate,config)==88, "native table ABI");
_Static_assert(sizeof(struct a6400_candidate_string)==8, "string ABI");
_Static_assert(sizeof(struct a6400_candidate_language)==8, "language ABI");

void a6400_uvc_ptp_candidate_init(struct a6400_uvc_ptp_candidate *p)
{
    unsigned int i;
    unsigned char *bytes = (unsigned char *)p;
    for (i=0; i<sizeof(*p); ++i) bytes[i]=0;
    /* HS carries PTP+UVC. FS fallback keeps the original PTP protocol only;
     * endpoint packet/interval values are bound to remotepc_interface_desc. */
    p->speed[0].config_count=1;
    p->speed[0].configs=&p->config;
    p->config.value=1;
    p->config.interface_count=3;
    p->config.interfaces=p->interfaces;
    p->config.attributes=0x80;
    p->config.max_power=250; /* captured PC Remote bMaxPower */
    for (i=0; i<3; ++i) {
        p->interfaces[i].number=(unsigned char)i;
        p->interfaces[i].alternate_count=1;
        p->interfaces[i].alternates=&p->alternates[i];
    }
    p->alternates[0].endpoint_count=3;
    p->alternates[0].endpoints=p->ptp_endpoints;
    p->alternates[0].klass=6;
    p->alternates[0].subclass=1;
    p->alternates[0].protocol=1;
    p->ptp_endpoints[0].address=0x81;
    p->ptp_endpoints[0].attributes=2;
    p->ptp_endpoints[0].max_packet=512;
    p->ptp_endpoints[1].address=0x02;
    p->ptp_endpoints[1].attributes=2;
    p->ptp_endpoints[1].max_packet=512;
    p->ptp_endpoints[2].address=0x83;
    p->ptp_endpoints[2].attributes=3;
    p->ptp_endpoints[2].max_packet=32;
    p->ptp_endpoints[2].interval=7;
    for (i=0; i<sizeof(p->vc_extra); ++i)
        p->vc_extra[i]=s_desc_12598_template[i];
    for (i=0; i<sizeof(p->vs_extra); ++i)
        p->vs_extra[i]=s_desc_12625_template[i];
    p->vc_extra[12]=2; /* baInterfaceNr: new VideoStreaming interface */
    p->vs_extra[6]=0x84; /* VS input header bEndpointAddress */
    p->alternates[1].klass=0x0e;
    p->alternates[1].subclass=1;
    p->alternates[1].extra_size=sizeof(p->vc_extra);
    p->alternates[1].extra=p->vc_extra;
    p->alternates[2].klass=0x0e;
    p->alternates[2].subclass=2;
    p->alternates[2].extra_size=sizeof(p->vs_extra);
    p->alternates[2].extra=p->vs_extra;
    p->alternates[2].endpoint_count=1;
    p->alternates[2].endpoints=&p->video_endpoint;
    p->video_endpoint.address=0x84;
    p->video_endpoint.attributes=2;
    p->video_endpoint.max_packet=512;
    p->video_endpoint.reserved5[0]=2;
    p->speed[1].config_count=1;
    p->speed[1].configs=&p->fs_config;
    p->fs_config.value=1;p->fs_config.interface_count=1;
    p->fs_config.interfaces=&p->fs_interface;
    p->fs_config.attributes=0x80;p->fs_config.max_power=250;
    p->fs_interface.alternate_count=1;
    p->fs_interface.alternates=&p->fs_alternate;
    p->fs_alternate.endpoint_count=3;
    p->fs_alternate.endpoints=p->fs_endpoints;
    p->fs_alternate.klass=6;p->fs_alternate.subclass=1;p->fs_alternate.protocol=1;
    for (i=0;i<3;++i) {
        p->ptp_endpoints[i].reserved5[0]=2;
        p->fs_endpoints[i]=p->ptp_endpoints[i];
        p->fs_endpoints[i].reserved5[0]=1;
    }
    p->fs_endpoints[0].max_packet=64;p->fs_endpoints[1].max_packet=64;
    p->fs_endpoints[2].interval=10;
}

int a6400_uvc_ptp_candidate_identity(struct a6400_uvc_ptp_candidate *p,
                                  const unsigned char *device,
                                  const unsigned char *manufacturer,
                                  const unsigned char *product,
                                  const unsigned char *serial)
{
    const unsigned char *source[3]={manufacturer,product,serial};
    unsigned int i,j;
    if (!p || !device || device[0]!=18 || device[1]!=1 ||
        device[14]!=1 || device[15]!=2 || device[16]!=3 || device[17]!=1)
        return -22;
    for (i=0;i<3;++i)
        if (!source[i] || source[i][0]<2 || source[i][0]>66 ||
            (source[i][0]&1) || source[i][1]!=3) return -22;
    p->speed[0].device_fields[0]=device[2];
    p->speed[0].device_fields[1]=device[3];
    p->speed[0].device_fields[2]=0xef;
    p->speed[0].device_fields[3]=2;
    p->speed[0].device_fields[4]=1; /* composite/IAD grouping candidate */
    for (i=0;i<5;++i) p->speed[1].device_fields[i]=p->speed[0].device_fields[i];
    for (i=0;i<6;++i) p->metadata[i]=device[8+i]; /* VID/PID/bcdDevice */
    p->metadata[7]=1;p->metadata[8]=2;p->metadata[9]=3;
    p->metadata[10]=1;
    *(void **)&p->metadata[12]=&p->language;
    p->language.language=0x0409;
    p->language.string_count=3;
    p->language.strings=p->strings;
    for (i=0;i<3;++i) {
        unsigned int size=source[i][0]-2;
        p->strings[i].index=(unsigned char)(i+1);
        p->strings[i].size=(unsigned char)size;
        p->strings[i].data=p->string_data[i];
        for (j=0;j<64;++j)
            p->string_data[i][j]=j<size ? source[i][j+2]:0;
    }
    return 0;
}

int a6400_uvc_ptp_candidate_add_iad(unsigned char *p, unsigned int length,
                                 unsigned int capacity)
{
    static const unsigned char iad[8]={8,11,1,2,14,3,0,0};
    unsigned int offset=9, insertion=0, i;
    if (!p || length<9 || length>65527 || capacity<length || capacity-length<8)
        return -22;
    if (p[0]!=9 || p[1]!=2 || p[4]!=3 ||
        ((unsigned int)p[2] | ((unsigned int)p[3]<<8))!=length) return -22;
    /* Validate the whole chain before moving any byte. No partial writes on
     * rejection, repeated insertion, malformed length, or ambiguous VC. */
    while (offset<length) {
        unsigned int n=p[offset];
        if (n<2 || n>length-offset || p[offset+1]==11) return -22;
        if (p[offset+1]==4) {
            if (n!=9) return -22;
            if (p[offset+2]==1 && p[offset+3]==0 &&
                p[offset+5]==14 && p[offset+6]==1) {
                if (insertion) return -22;
                insertion=offset;
            }
        }
        offset+=n;
    }
    if (!insertion) return -22;
    for (i=length; i>insertion; --i) p[i+7]=p[i-1];
    for (i=0; i<8; ++i) p[insertion+i]=iad[i];
    length+=8;
    p[2]=(unsigned char)length;
    p[3]=(unsigned char)(length>>8);
    return (int)length;
}

static int bounded_topology(struct a6400_uvc_ptp_candidate *p)
{
    unsigned int i;
    if (p->speed[0].config_count!=1 || p->speed[0].configs!=&p->config ||
        p->config.index!=0 || p->config.interface_count!=3 ||
        p->config.interfaces!=p->interfaces || p->config.otg) return 0;
    for (i=0; i<3; ++i) {
        struct a6400_candidate_alternate *a=&p->alternates[i];
        if (p->interfaces[i].number!=i || p->interfaces[i].alternate_count!=1 ||
            p->interfaces[i].alternates!=a || a->alternate) return 0;
    }
    if (p->alternates[0].endpoint_count!=3 ||
        p->alternates[0].endpoints!=p->ptp_endpoints || p->alternates[0].extra_size ||
        p->alternates[1].endpoint_count || p->alternates[1].extra_size!=40 ||
        p->alternates[1].extra!=p->vc_extra || p->alternates[2].endpoint_count!=1 ||
        p->alternates[2].endpoints!=&p->video_endpoint ||
        p->alternates[2].extra_size!=61 || p->alternates[2].extra!=p->vs_extra) return 0;
    for (i=0; i<3; ++i)
        if (p->ptp_endpoints[i].extra_size || p->ptp_endpoints[i].companion) return 0;
    return !p->video_endpoint.extra_size && !p->video_endpoint.companion;
}

int a6400_uvc_ptp_candidate_config_reply(struct a6400_uvc_ptp_candidate *p,
                                      void *gc, const unsigned char *setup,
                                      unsigned char *output, unsigned int capacity)
{
    typedef int (*sony_serializer)(void *,const void *,void *,int);
    unsigned char request[8], staging[512];
    unsigned int i, requested, copy_length;
    void *gadget;
    int length;
    if (!p || !gc || !setup || !output) return -22;
    if (setup[0]!=0x80 || setup[1]!=6 || setup[2]!=0 || setup[3]!=2 ||
        setup[4]!=0 || setup[5]!=0) return -22;
    if (*(void **)((unsigned char *)gc+0x6c)!=p || !bounded_topology(p)) return -22;
    gadget=*(void **)gc;
    if (!gadget || *(unsigned int *)((unsigned char *)gadget+0x20)!=3) return -22;
    requested=(unsigned int)setup[6] | ((unsigned int)setup[7]<<8);
    copy_length=requested<173 ? requested:173;
    if (capacity<copy_length) return -28;
    if (copy_length &&
        (((unsigned int)output-(unsigned int)setup<8u) ||
         ((unsigned int)setup-(unsigned int)output<copy_length) ||
         ((unsigned int)output-(unsigned int)p<sizeof(*p)) ||
         ((unsigned int)p-(unsigned int)output<copy_length))) return -22;
    /* Only bounded, caller-stabilized topology reaches the native serializer.
     * It writes the full tree before applying wLength, so stage a full buffer.
     * No EP0 request or caller output is modified until all work succeeds. */
    for (i=0; i<8; ++i) request[i]=setup[i];
    request[6]=0;request[7]=2; /* local synchronous wLength = 512 */
    length=((sony_serializer)0x602bbc54u)(gc,request,staging,2);
    if (length<0) return length;
    if (length!=165) return -22;
    length=a6400_uvc_ptp_candidate_add_iad(staging,(unsigned int)length,sizeof(staging));
    if (length!=173) return -22;
    for (i=0; i<copy_length; ++i) output[i]=staging[i];
    return (int)copy_length;
}

static int bounded_identity_and_fs(struct a6400_uvc_ptp_candidate *p)
{
    unsigned int i;
    if (p->speed[1].config_count!=1 || p->speed[1].configs!=&p->fs_config ||
        p->fs_config.index || p->fs_config.interface_count!=1 || p->fs_config.otg ||
        p->fs_config.interfaces!=&p->fs_interface || p->fs_interface.number ||
        p->fs_interface.alternate_count!=1 || p->fs_interface.alternates!=&p->fs_alternate ||
        p->fs_alternate.alternate || p->fs_alternate.endpoint_count!=3 ||
        p->fs_alternate.endpoints!=p->fs_endpoints || p->fs_alternate.extra_size) return 0;
    if (p->metadata[10]!=1 || *(void **)&p->metadata[12]!=&p->language ||
        p->language.language!=0x0409 || p->language.string_count!=3 ||
        p->language.strings!=p->strings) return 0;
    for (i=0;i<3;++i)
        if (p->fs_endpoints[i].extra_size || p->fs_endpoints[i].companion ||
            p->strings[i].index!=i+1 || p->strings[i].size>64 ||
            (p->strings[i].size&1) || p->strings[i].data!=p->string_data[i]) return 0;
    return 1;
}

static int same_bytes(const void *a,const void *b,unsigned int n)
{
    const unsigned char *x=a,*y=b;
    unsigned int i;
    if (!a || !b) return 0;
    for (i=0;i<n;++i) if (x[i]!=y[i]) return 0;
    return 1;
}

static int same_native_config(const struct a6400_candidate_config *expected,
                              const struct a6400_candidate_config *actual)
{
    unsigned int i,j,k;
    if (!actual || !same_bytes(expected,actual,4) ||
        !same_bytes(&expected->string_index,&actual->string_index,4) ||
        actual->otg || actual->associations || !actual->interfaces) return 0;
    for (i=0;i<expected->interface_count;++i) {
        const struct a6400_candidate_interface *e=&expected->interfaces[i],*a=&actual->interfaces[i];
        if (!same_bytes(e,a,4) || !a->alternates) return 0;
        for (j=0;j<e->alternate_count;++j) {
            const struct a6400_candidate_alternate *ea=&e->alternates[j],*aa=&a->alternates[j];
            if (!same_bytes(ea,aa,4) || !same_bytes(&ea->klass,&aa->klass,4) ||
                ea->extra_size!=aa->extra_size ||
                (ea->extra_size && !same_bytes(ea->extra,aa->extra,ea->extra_size)) ||
                (ea->endpoint_count && !aa->endpoints)) return 0;
            for (k=0;k<ea->endpoint_count;++k) {
                const struct a6400_candidate_endpoint *ep=&ea->endpoints[k],*ap=&aa->endpoints[k];
                if (!same_bytes(ep,ap,8) || ap->extra_size || ap->companion) return 0;
            }
        }
    }
    return 1;
}

int a6400_uvc_ptp_validate_native_copy(struct a6400_uvc_ptp_candidate *p,
                                     const void *native_table)
{
    const struct a6400_candidate_device *speed=native_table;
    const unsigned char *metadata;
    const struct a6400_candidate_language *language;
    unsigned int i;
    if (!p || !native_table || !bounded_topology(p) || !bounded_identity_and_fs(p)) return -22;
    for (i=0;i<3;++i) {
        if (!same_bytes(&p->speed[i],&speed[i],8)) return -22;
        if (i<2) {
            if (!same_native_config(p->speed[i].configs,speed[i].configs)) return -22;
        } else if (speed[i].configs) return -22;
    }
    metadata=(const unsigned char *)native_table+48;
    if (!same_bytes(p->metadata,metadata,12) || !same_bytes(p->metadata+16,metadata+16,24)) return -22;
    language=*(const struct a6400_candidate_language *const *)(metadata+12);
    if (!language || !same_bytes(&p->language,language,4) || !language->strings) return -22;
    for (i=0;i<3;++i) {
        const struct a6400_candidate_string *a=&language->strings[i],*e=&p->strings[i];
        if (!same_bytes(e,a,4) || !same_bytes(e->data,a->data,e->size)) return -22;
    }
    return 0;
}

int a6400_uvc_ptp_candidate_descriptor_reply(struct a6400_uvc_ptp_candidate *p,
                                          void *gc,const unsigned char *setup,
                                          unsigned char *output,unsigned int capacity)
{
    typedef int (*serialize3)(void *,const void *,void *);
    typedef int (*serialize4)(void *,const void *,void *,int);
    unsigned char request[8],staging[512];
    unsigned int kind,index,speed,requested,expected,n,i;
    void *gadget;
    int length;
    if (!p || !gc || !setup || !output || setup[0]!=0x80 || setup[1]!=6) return -22;
    if (a6400_uvc_ptp_validate_native_copy(p,*(void **)((unsigned char *)gc+0x6c))) return -22;
    gadget=*(void **)gc;
    if (!gadget) return -22;
    speed=*(unsigned int *)((unsigned char *)gadget+0x20);
    if (speed!=2 && speed!=3) return -22;
    kind=setup[3];index=setup[2];
    if (kind==3) {
        if (index>3 || (index && (setup[4]!=9 || setup[5]!=4)) ||
            (!index && (setup[4] || setup[5]))) return -22;
        expected=index ? (unsigned int)p->strings[index-1].size+2:4;
    } else {
        if (index || setup[4] || setup[5]) return -22;
        if (kind==1) expected=18;
        else if (kind==6) expected=10;
        else if (kind==2 || kind==7)
            expected=((speed==3)==(kind==2)) ? 173:39;
        else return -22;
    }
    requested=(unsigned int)setup[6] | ((unsigned int)setup[7]<<8);
    n=requested<expected ? requested:expected;
    if (capacity<n) return -28;
    if (n && (((unsigned int)output-(unsigned int)setup<8u) ||
        ((unsigned int)setup-(unsigned int)output<n) ||
        ((unsigned int)output-(unsigned int)p<sizeof(*p)) ||
        ((unsigned int)p-(unsigned int)output<n))) return -22;
    for (i=0;i<8;++i) request[i]=setup[i];
    request[6]=0;request[7]=2;
    if (kind==1) length=((serialize3)0x602bb988u)(gc,request,staging);
    else if (kind==3) length=((serialize3)0x602bc0ccu)(gc,request,staging);
    else if (kind==6) length=((serialize3)0x602bbfecu)(gc,request,staging);
    else {
        length=((serialize4)0x602bbc54u)(gc,request,staging,(int)kind);
        if (length<0) return length;
        if (expected==173) {
            if (length!=165) return -22;
            staging[1]=2; /* IAD validator expects CONFIGURATION, not OTHER_SPEED */
            length=a6400_uvc_ptp_candidate_add_iad(staging,165,sizeof(staging));
            staging[1]=(unsigned char)kind;
        }
    }
    if (length<0) return length;
    if ((unsigned int)length!=expected) return -22;
    for (i=0;i<n;++i) output[i]=staging[i];
    return (int)n;
}
