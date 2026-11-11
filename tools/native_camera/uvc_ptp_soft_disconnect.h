/* Ordered soft-disconnect teardown for the shared a6400 UVC/PTP candidate.
 *
 * The shared build tears a configured UVC+PTP session down with the native
 * Sony primitives, but the order matters: the original clear-configuration
 * (0x602b90cc) stops interfaces 0/1/2 and runs the interface STOP ownership
 * path (E0211/E0213/E0250), the reference driver's STOP callback clears its
 * endpoint map through usbg_cmn_clear_ep_list (E0136/E0319), and only then may
 * the UDC be pulled down and re-armed (E0252 was the only clean physical
 * teardown and it did exactly this order).
 *
 * This module owns that order. Every phase is gated on the state the previous
 * phase produced, every phase is recorded, and the two invariants that keep a
 * half-torn gadget from becoming a host-visible "unknown device" are enforced:
 *
 *   1. The descriptor table the module installed is never freed or replaced
 *      while the EP0 descriptor hooks are still bound, and never freed while a
 *      shadow driver record is still registered (the native guards require a
 *      stopped controller for both, so the order below satisfies them).
 *   2. After the UDC has been stopped, a later phase failure does not skip the
 *      reconnect: D+ is raised again with whatever descriptor table is coherent
 *      at that point, so the host can still enumerate and the owner's next USB
 *      mode transition starts from a connected gadget instead of a dead one.
 *
 * Failures are still failures: the first error is returned, the session is
 * held by the caller, the module stays pinned and no verified-stop receipt is
 * produced. Nothing here invents a successful teardown.
 */
#ifndef A6400_UVC_PTP_SOFT_DISCONNECT_H
#define A6400_UVC_PTP_SOFT_DISCONNECT_H

struct a6400_uvc_ptp_session;

/* Ordered phases. The value is the bit index in the trace phase mask and the
 * value recorded in failed_phase. */
enum {
    A6400_TD_UNCONFIGURE = 0,   /* original clear-configuration 0x602b90cc */
    A6400_TD_BRIDGE_QUIESCE,    /* reference STOP callback (ep list release) */
    A6400_TD_EP_MAP,            /* reference endpoint map must be released */
    A6400_TD_UDC_DOWN,          /* pullup(0) + setup_disconnect + gcw_stop */
    A6400_TD_UNBIND_EP0,        /* restore the four EP0 descriptor call sites */
    A6400_TD_UNREGISTER,        /* unregister/demote both shadow drivers */
    A6400_TD_DESCRIPTOR,        /* free installed table, restore saved root */
    A6400_TD_DEMOTE,            /* shadow records to tail (usbg_stillimage first) */
    A6400_TD_RECONNECT,         /* gcw_start + EP0 arm + pullup(1) */
    A6400_TD_PHASE_COUNT
};

enum {
    A6400_TD_DESC_UNTOUCHED = 0,
    A6400_TD_DESC_RESTORED,      /* saved original root reinstalled */
    A6400_TD_DESC_OWNER_KEPT,    /* owner replaced it; left in place */
    A6400_TD_DESC_NOT_INSTALLED  /* lease never installed */
};

enum {
    A6400_TD_EP_UNKNOWN = 0,
    A6400_TD_EP_CLEARED,   /* context present, ctx+0xB4 released */
    A6400_TD_EP_RESIDUAL,  /* context present, ctx+0xB4 still points at a list */
    A6400_TD_EP_ABSENT     /* no reference video context on this boot */
};

/* Fixed 18-word record. Written once per teardown attempt and kept in the
 * session so a held session still reports where it stopped. */
struct a6400_uvc_teardown_trace {
    unsigned int version;
    unsigned int phases;          /* executed phase bitmask */
    unsigned int failed_phase;    /* A6400_TD_* or A6400_TD_PHASE_COUNT */
    int first_error;
    unsigned int stream_stopped;  /* reference STOP delivered by this call */
    unsigned int ep_state;        /* A6400_TD_EP_* */
    unsigned int ep_id;           /* reference ctx+0xB2 (read-only residue) */
    unsigned int ep_list;         /* reference ctx+0xB4 (0 = released) */
    unsigned int ep_count;        /* reference ctx+0xB8 (read-only residue) */
    unsigned int descriptor_state;/* A6400_TD_DESC_* */
    void *descriptor_root;        /* gc+0x6c after the descriptor phase */
    unsigned int drivers_retired; /* both shadow records unregistered */
    int shadow_records;           /* shadow records left in gc->drv_list */
    unsigned int udc_down;        /* stop pair executed in this attempt */
    int reconnect;                /* 0 not attempted, 1 raised, <0 error */
    unsigned int transitions;     /* stop/start pair completed count (0/1) */
    unsigned int reserved;
};

/* Runs the ordered teardown exactly once per attempt. The caller keeps the
 * session ownership rules: a nonzero result must hold the session. */
int a6400_uvc_soft_disconnect(struct a6400_uvc_ptp_session *,
                              struct a6400_uvc_teardown_trace *);

#endif
