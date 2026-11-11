/* a6400 UVC gadget-node ioctl ABI (usbg_video_a6400_*.ko).
 *
 * Transcribed from the physically exercised runner and feeder:
 *   - tools/native_camera/uvc_ptp_feed_runner.c:31,197-214 (INIT + probe info)
 *   - tools/native_camera/uvc_ptp_entry_hook.h:18-21 (session ioctls)
 *   - tools/native_camera/uvc_sensor_feeder_30fps.c:43-50 (UVC ioctl numbers)
 *   - tools/native_camera/uvc_composite_shim.c:989-1104 (MOD_QUERY_DMA layout,
 *     REG_BUF/UPDATE validation, capacity semantics)
 *   - docs/evidence/0145 (owned coherent DMA, MOD_QUERY_DMA ret=0, bad REG_BUF
 *     rejected with -22, oversized UPDATE rejected with -22)
 *   - docs/evidence/0319 (register/unregister + probe-info ABI decoded from the
 *     ZV-E10 reference module; 56-byte user probe info block)
 *
 * The node is a char device major 248 minor 33 on a6400 (E0320/E0321). The
 * devno.ko table on this firmware does not create the node, so the helper
 * creates it with mknod before opening (E0339).
 *
 * Session getters are provided by the authored module's shared ioctl
 * (uvc_ptp_module_shim.c): A6400_UVC_QUERY_IDENTITY and A6400_UVC_QUERY_USB_STATE.
 * They are used to prove the camera is in PC Remote before INIT, because INIT
 * returns -1/EINVAL in Mass Storage (E0342).
 */
#ifndef A6400_UVC_H
#define A6400_UVC_H

#include <stdint.h>
#include <stddef.h>
#include <sys/types.h>

#define A6400_UVC_NODE_PATH "/tmp_bt/video"
#define A6400_UVC_NODE_MAJOR 248u
#define A6400_UVC_NODE_MINOR 33u

/* ---- ioctls -------------------------------------------------------------- */

#define A6400_UVC_IOCTL_INIT        0x4038e000u  /* arg: 56-byte probe info */
#define A6400_UVC_IOCTL_STOP        0x0000e001u
#define A6400_UVC_IOCTL_REG_BUF     0x4008f000u  /* arg: struct reg_buf     */
#define A6400_UVC_IOCTL_UNREG       0x0000f001u
#define A6400_UVC_IOCTL_UPDATE      0x4008f003u  /* arg: struct update       */
#define A6400_UVC_IOCTL_WAIT        0x0000f002u
#define A6400_UVC_IOCTL_ENABLE      0x0000f006u
/* Present only in the authored module's shim; the stock ZV-E10 driver has no
 * such ioctl and returns -25/ENOTTY (E0340:9-11). The daemon must treat
 * ENOTTY as "query unavailable" and fall back to REG_BUF acceptance. */
#define A6400_UVC_IOCTL_MOD_QUERY_DMA 0x8010f020u

/* Session ioctls of the authored shared-enumeration module (E0339/E0347). */
#define A6400_UVC_IOCTL_QUERY_IDENTITY 0x8010f028u
#define A6400_UVC_IOCTL_QUERY_USB_STATE 0x8010f029u
#define A6400_UVC_IOCTL_ATTEST_STOPS    0xc020f023u
#define A6400_UVC_IOCTL_HOOK_PUBLISH    0xc020f026u
#define A6400_UVC_IOCTL_HOOK_RETIRE     0xc020f027u

/* ---- argument structures ------------------------------------------------- */

struct a6400_uvc_reg_buf {
    uint32_t size;       /* total registered window size in bytes */
    uint32_t phys_addr;  /* physical address of the window */
};

struct a6400_uvc_update {
    uint32_t frame_size; /* payload length of the MJPEG frame */
    uint32_t phys_addr;  /* physical address of the frame bytes */
};

/* Returned by A6400_UVC_IOCTL_MOD_QUERY_DMA. Slot capacity is total/2 and the
 * driver writes a 12-byte header before the payload, hence max_frame_payload
 * (uvc_composite_shim.c:1002-1020, uvc_producer_admission.h:7). */
struct a6400_uvc_dma_meta {
    uint32_t phys_addr;
    uint32_t total_size;
    uint32_t slot_size;
    uint32_t max_frame_payload;
};

/* 56-byte user probe info block passed to INIT. Layout and size are fixed by
 * uvc_ptp_feed_runner.c:34-48 (static assert) and E0319 section "register/
 * unregister + probe ABI". Fields not needed by a feeder are zero; the eight
 * callbacks are set to a no-op because the authored module installs its own
 * START thunk (uvc_composite_shim.c:820). */
struct a6400_uvc_probe_info {
    void        *context;
    void       (*callbacks[8])(void);
    void        *interfaces_ptr;
    uint32_t     reserved40;
    uint8_t      reserved44;
    uint8_t      interface_count;
    uint16_t     reserved46;
    void        *extra_info_ptr;
    uint32_t     extra_info_size;
};

#define A6400_UVC_INTERFACE_LIST_LEN 4u

/* Attestation request for the entry-hook lifecycle; must be built from a
 * verified ptrace stop scope (uvc_ptp_stop_attest.h:8-11, E0194/E0205). */
struct a6400_uvc_stop_request {
    uint32_t version;    /* 2 */
    uint32_t owner;      /* 149 (im.elf) */
    uint32_t count;      /* number of frozen TIDs */
    uint32_t tids;       /* pointer to uint32_t TID array */
    uint32_t registers;  /* 0 for version 2 */
    uint32_t siginfo;    /* 0 for version 2 */
    uint32_t completed;  /* out: TIDs verified by the module */
    int32_t  error;      /* out: module-side error */
};

/* ---- client -------------------------------------------------------------- */

struct a6400_uvc {
    int      fd;
    char     path[64];
    int      node_created;   /* 1 when this client created the mknod node */
};

/* Opens (and, if ENOENT, creates with mknod 248:33) the video node.
 * Returns 0 or a negative errno-style value. Never retries a second open when
 * the first failed with ENOMEM: a second large DMA open cannot be satisfied on
 * fragmented memory (E0339:52-57). */
int a6400_uvc_open(struct a6400_uvc *u, const char *path);

/* Closes the node only; it does not stop an active session. */
void a6400_uvc_close(struct a6400_uvc *u);

/* Identity query: writes {idVendor, idProduct}. PC Remote is 0x054c:0x0caa. */
int a6400_uvc_query_identity(struct a6400_uvc *u, uint16_t ids[2]);
/* USB state: {flags, config, mode, speed} (module-defined words). */
int a6400_uvc_query_usb_state(struct a6400_uvc *u, uint32_t state[4]);

/* Session: INIT with the feeder probe info, holds the composite session. */
int a6400_uvc_init(struct a6400_uvc *u, const void *interfaces, uint8_t interface_count);

/* Buffer/stream. `meta` may be NULL when MOD_QUERY_DMA is unavailable. */
int a6400_uvc_query_dma(struct a6400_uvc *u, struct a6400_uvc_dma_meta *meta);
int a6400_uvc_reg_buf(struct a6400_uvc *u, uint32_t size, uint32_t phys);
int a6400_uvc_enable(struct a6400_uvc *u);
int a6400_uvc_wait(struct a6400_uvc *u);
int a6400_uvc_update(struct a6400_uvc *u, uint32_t frame_size, uint32_t phys);
int a6400_uvc_unreg(struct a6400_uvc *u);
int a6400_uvc_stop(struct a6400_uvc *u);

#endif /* A6400_UVC_H */
