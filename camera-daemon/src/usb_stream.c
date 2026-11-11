/* a6400 UVC gadget-node client.
 *
 * Every ioctl number and argument structure is transcribed from the physically
 * exercised runner and feeder (a6400_uvc.h:1-22 lists the exact lines). Two
 * behaviours are load-bearing and deliberately explicit here:
 *
 *  1. SINGLE-FD. A second open() of the video node failed with -12/ENOMEM on
 *     fragmented memory (E0339:52-57). a6400_uvc_open() therefore has exactly
 *     ONE open attempt (plus the documented mknod retry when and only when the
 *     node does not exist yet), refuses to reuse an already-open handle, and
 *     never sleeps/retries an ENOMEM.
 *
 *  2. NODE CREATION IS CONFINED. devno.ko on this firmware does not create
 *     /dev/usb/video, so the helper may have to mknod major 248 minor 33
 *     (E0320/E0321). That is only legal under /tmp_bt (the 1 MiB tmpfs the
 *     project is confined to); any other path is refused with -EPERM instead of
 *     silently creating a device node outside the allowed scope.
 *
 * MOD_QUERY_DMA exists only in the authored shim; the stock driver returns
 * -25/ENOTTY (E0340:9-11). That is reported as -ENOTTY, not as a generic
 * failure, so the daemon can fall back to the REG_BUF-acknowledged window.
 */
#include "a6400_uvc.h"

#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/types.h>
#include <unistd.h>

_Static_assert(sizeof(struct a6400_uvc_probe_info) == 56,
               "uvc probe info must be exactly 56 bytes (uvc_ptp_feed_runner.c:45)");
_Static_assert(sizeof(struct a6400_uvc_reg_buf) == 8, "reg_buf ABI");
_Static_assert(sizeof(struct a6400_uvc_update) == 8, "update ABI");
_Static_assert(sizeof(struct a6400_uvc_dma_meta) == 16, "dma meta ABI");
_Static_assert(sizeof(struct a6400_uvc_stop_request) == 32, "stop request ABI");

/* The driver writes a 12-byte UVC header before the payload, so the usable
 * per-slot payload is slot_size - 12 (uvc_producer_admission.h:7,
 * uvc_composite_shim.c:1046-1050). a6400_uvc.h does not name it because it is
 * a frame-layer rule, so it is restated here only for the query sanity check. */
#define A6400_UVC_HEADER_RESERVE 12u

static void noop_callback(void)
{
}

static int normalize_ioctl(int rc)
{
    if (rc == 0)
        return 0;
    if (rc == -1)
        return -errno;
    return rc < 0 ? rc : -EIO;
}

/* The allowed node-creation namespace. "/tmp_bt/video" passes; "/tmp_bt2/x"
 * does not (the separator is part of the prefix). */
static int under_tmp_bt(const char *path)
{
    static const char prefix[] = "/tmp_bt/";

    return path && strncmp(path, prefix, sizeof prefix - 1u) == 0;
}

int a6400_uvc_open(struct a6400_uvc *u, const char *path)
{
    size_t n;
    struct stat st;

    if (!u)
        return -EINVAL;
    u->fd = -1;
    u->node_created = 0;
    u->path[0] = '\0';

    if (!path || !path[0])
        return -EINVAL;
    n = strlen(path);
    if (n >= sizeof u->path)
        return -ENAMETOOLONG;
    memcpy(u->path, path, n + 1u);

    u->fd = open(u->path, O_RDWR | O_CLOEXEC);
    if (u->fd >= 0)
        return 0;

    {
        int first = errno;

        /* Never retry a failed allocation. A second large DMA open cannot be
         * satisfied once the first one failed this way. */
        if (first != ENOENT)
            return -first;
    }

    if (!under_tmp_bt(u->path))
        return -EPERM; /* creation outside /tmp_bt is not allowed */

    if (mknod(u->path, S_IFCHR | 0600,
              makedev(A6400_UVC_NODE_MAJOR, A6400_UVC_NODE_MINOR)) != 0 &&
        errno != EEXIST)
        return -errno;

    u->node_created = 1;
    /* Exactly one attempt after creation, for the same ENOMEM reason. */
    u->fd = open(u->path, O_RDWR | O_CLOEXEC);
    if (u->fd < 0)
        return -errno;

    if (stat(u->path, &st) == 0 && !S_ISCHR(st.st_mode)) {
        (void)close(u->fd);
        u->fd = -1;
        return -ENODEV;
    }
    return 0;
}

void a6400_uvc_close(struct a6400_uvc *u)
{
    if (!u)
        return;
    if (u->fd >= 0)
        (void)close(u->fd);
    u->fd = -1;
    /* The node is deliberately NOT unlinked: removing a device node is a
     * destructive step the operator performs explicitly, and the daemon cannot
     * know whether another process is about to use it. */
}

int a6400_uvc_query_identity(struct a6400_uvc *u, uint16_t ids[2])
{
    if (!u || u->fd < 0 || !ids)
        return -EINVAL;
    ids[0] = ids[1] = 0;
    return normalize_ioctl(ioctl(u->fd, A6400_UVC_IOCTL_QUERY_IDENTITY, ids));
}

int a6400_uvc_query_usb_state(struct a6400_uvc *u, uint32_t state[4])
{
    if (!u || u->fd < 0 || !state)
        return -EINVAL;
    memset(state, 0, 4u * sizeof state[0]);
    return normalize_ioctl(ioctl(u->fd, A6400_UVC_IOCTL_QUERY_USB_STATE, state));
}

int a6400_uvc_init(struct a6400_uvc *u, const void *interfaces, uint8_t interface_count)
{
    struct a6400_uvc_probe_info info;
    unsigned i;

    if (!u || u->fd < 0)
        return -EINVAL;
    if (interface_count > A6400_UVC_INTERFACE_LIST_LEN)
        return -EINVAL;
    if (interface_count && !interfaces)
        return -EINVAL;

    memset(&info, 0, sizeof info);
    info.context = NULL;
    /* The authored module installs its own START thunk, so these callbacks are
     * never invoked; a no-op keeps the block well-formed (runner:197-204). */
    for (i = 0; i < 8u; i++)
        info.callbacks[i] = noop_callback;
    info.interfaces_ptr = (void *)(uintptr_t)interfaces;
    info.reserved44 = 0;
    info.interface_count = interface_count;
    info.reserved46 = 0;
    info.extra_info_ptr = NULL;
    info.extra_info_size = 0;

    return normalize_ioctl(ioctl(u->fd, A6400_UVC_IOCTL_INIT, &info));
}

int a6400_uvc_query_dma(struct a6400_uvc *u, struct a6400_uvc_dma_meta *meta)
{
    int rc;

    if (!u || u->fd < 0 || !meta)
        return -EINVAL;
    memset(meta, 0, sizeof *meta);
    rc = ioctl(u->fd, A6400_UVC_IOCTL_MOD_QUERY_DMA, meta);
    if (rc != 0)
        return normalize_ioctl(rc);
    /* Slot capacity is total/2 and must retain the 12-byte header reserve
     * (uvc_composite_shim.c:1002-1020). A reply that violates that is not
     * trusted. */
    if (!meta->total_size || !meta->slot_size ||
        meta->slot_size > meta->total_size ||
        meta->slot_size <= A6400_UVC_HEADER_RESERVE)
        return -EPROTO;
    return 0;
}

int a6400_uvc_reg_buf(struct a6400_uvc *u, uint32_t size, uint32_t phys)
{
    struct a6400_uvc_reg_buf reg;

    if (!u || u->fd < 0)
        return -EINVAL;
    if (!size || !phys)
        return -EINVAL;
    reg.size = size;
    reg.phys_addr = phys;
    return normalize_ioctl(ioctl(u->fd, A6400_UVC_IOCTL_REG_BUF, &reg));
}

int a6400_uvc_enable(struct a6400_uvc *u)
{
    if (!u || u->fd < 0)
        return -EINVAL;
    return normalize_ioctl(ioctl(u->fd, A6400_UVC_IOCTL_ENABLE, NULL));
}

int a6400_uvc_wait(struct a6400_uvc *u)
{
    if (!u || u->fd < 0)
        return -EINVAL;
    return normalize_ioctl(ioctl(u->fd, A6400_UVC_IOCTL_WAIT, NULL));
}

int a6400_uvc_update(struct a6400_uvc *u, uint32_t frame_size, uint32_t phys)
{
    struct a6400_uvc_update upd;

    if (!u || u->fd < 0)
        return -EINVAL;
    if (!frame_size || !phys)
        return -EINVAL;
    if (phys > 0xffffffffu - frame_size)
        return -EINVAL; /* wrap: the driver would reject it anyway */
    upd.frame_size = frame_size;
    upd.phys_addr = phys;
    return normalize_ioctl(ioctl(u->fd, A6400_UVC_IOCTL_UPDATE, &upd));
}

int a6400_uvc_unreg(struct a6400_uvc *u)
{
    if (!u || u->fd < 0)
        return -EINVAL;
    return normalize_ioctl(ioctl(u->fd, A6400_UVC_IOCTL_UNREG, NULL));
}

int a6400_uvc_stop(struct a6400_uvc *u)
{
    if (!u || u->fd < 0)
        return -EINVAL;
    return normalize_ioctl(ioctl(u->fd, A6400_UVC_IOCTL_STOP, NULL));
}
