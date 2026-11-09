#include "uvc_ptp_descriptor_lease.h"
_Static_assert(sizeof(void *)==4,"ARM32 ABI");
_Static_assert(sizeof(struct a6400_descriptor_arg)==12,"native save argument ABI");

static void **root(void *gc) { return (void **)((unsigned char *)gc+0x6c); }

static void restore_snapshot(struct a6400_descriptor_lease *s)
{
    unsigned char *gc=s->gc;
    unsigned int i;
    *root(gc)=s->original;
    *(unsigned int *)(gc+0x68)=s->flags;
    gc[0x84]=s->mode;gc[0x85]=s->max_speed;
    for (i=0;i<sizeof(*s);++i) ((unsigned char *)s)[i]=0;
}

int a6400_descriptor_install(struct a6400_descriptor_lease *s,void *gc,
                            const struct a6400_descriptor_arg *arg,
                            const struct a6400_descriptor_ops *ops)
{
    int error;
    if (!s || !gc || !arg || !arg->table || !ops || !ops->save || !ops->free) return -22;
    if (s->phase) return -16;
    if (!*root(gc) || *root(gc)==arg->table) return -22;
    if (arg->extra || arg->extra_len || arg->is_dual || arg->max_speed!=1 || arg->pad) return -22;
    if (a6400_uvc_ptp_validate_native_copy(arg->table,arg->table)) return -22;
    s->gc=gc;s->original=*root(gc);s->installed=0;s->source=arg->table;
    s->native_free=ops->free;
    s->flags=*(unsigned int *)((unsigned char *)gc+0x68);
    s->mode=((unsigned char *)gc)[0x84];s->max_speed=((unsigned char *)gc)[0x85];
    s->phase=A6400_LEASE_INSTALLING;s->last_error=0;
    /* Native save's failure path calls free_desc_tbl(gc). Do not expose the
     * preserved PC Remote root to that cleanup, even on a pre-allocation fault. */
    *root(gc)=0;
    error=ops->save(gc,arg);
    s->installed=*root(gc);
    if (error) {
        if (!s->installed) { restore_snapshot(s);return error; }
        s->last_error=error;s->phase=A6400_LEASE_QUARANTINED;return -16;
    }
    if (!s->installed) { restore_snapshot(s);return -5; }
    if (s->installed==s->original || s->installed==s->source ||
        a6400_uvc_ptp_validate_native_copy(s->source,s->installed)) {
        s->last_error=-22;s->phase=A6400_LEASE_QUARANTINED;return -22;
    }
    s->phase=A6400_LEASE_INSTALLED;return 0;
}

int a6400_descriptor_restore(struct a6400_descriptor_lease *s,
                            const struct a6400_descriptor_ops *ops)
{
    if (!s || !ops || !ops->free) return -22;
    if (s->phase==A6400_LEASE_EMPTY) return 0;
    if (s->phase!=A6400_LEASE_INSTALLED) return -16;
    if (ops->free!=s->native_free) return -22;
    if (!s->gc || !s->installed || *root(s->gc)!=s->installed) return -116;
    ops->free(s->gc);
    if (*root(s->gc)) {
        s->last_error=-5;s->phase=A6400_LEASE_QUARANTINED;return -5;
    }
    restore_snapshot(s);return 0;
}

int a6400_descriptor_source_releasable(const struct a6400_descriptor_lease *s)
{
    return s && s->phase==A6400_LEASE_EMPTY;
}
