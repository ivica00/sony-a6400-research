/* Descriptor ownership transaction ONLY. Caller must first stop the controller,
 * drain callbacks and hold topology serialization. Does not disconnect USB,
 * change address limits, register drivers, or assert hardware quiescence. */
#ifndef A6400_UVC_PTP_DESCRIPTOR_LEASE_H
#define A6400_UVC_PTP_DESCRIPTOR_LEASE_H
#include "uvc_ptp_descriptors.h"
struct a6400_descriptor_arg {
    void *table, *extra;
    unsigned char extra_len,is_dual,max_speed,pad;
};
struct a6400_descriptor_ops {
    int (*save)(void *,const struct a6400_descriptor_arg *);
    void (*free)(void *);
};
enum { A6400_LEASE_EMPTY, A6400_LEASE_INSTALLING,
       A6400_LEASE_INSTALLED, A6400_LEASE_QUARANTINED };
struct a6400_descriptor_lease {
    unsigned int phase;
    void *gc, *original, *installed;
    struct a6400_uvc_ptp_candidate *source;
    unsigned int flags;
    unsigned char mode, max_speed, reserved[2];
    int last_error;
    void (*native_free)(void *);
};
int a6400_descriptor_install(struct a6400_descriptor_lease *,void *,
                            const struct a6400_descriptor_arg *,
                            const struct a6400_descriptor_ops *);
int a6400_descriptor_restore(struct a6400_descriptor_lease *,
                            const struct a6400_descriptor_ops *);
int a6400_descriptor_source_releasable(const struct a6400_descriptor_lease *);
#endif
