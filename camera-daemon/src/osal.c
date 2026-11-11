/* a6400 OSAL (/dev/uipc) client, DMM service operations and the Scalar
 * DataflowInfra SET_PATH / GET_JPEG requests.
 *
 * Every ioctl number, request struct, field offset and timeout in this file is
 * transcribed from the physically run feeder
 * tools/native_camera/uvc_sensor_feeder_30fps.c:221-529. No value here is a
 * memory address: the queue ids are named OSAL message destinations and the
 * 0x2a/729 pair is the dynamic-id protocol parameter that feeder used.
 *
 * Return convention (documented once, used everywhere below):
 *   0            success
 *   -errno       a system call failed (open/ioctl/mmap)
 *   -EIO         the driver/peer accepted the call but reported failure
 *   -ETIMEDOUT   no reply arrived inside the bound
 *   -EPROTO      the reply was shorter/less plausible than the ABI guarantees
 *   >0           (DMM/scalar helpers only) the original status value from the
 *                reply, so the caller can log exactly what the camera said.
 */
#include "a6400_osal.h"

#include <errno.h>
#include <fcntl.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <unistd.h>

/* ---- /dev/uipc client ABI ------------------------------------------------ */
/* Field order and sizes mirror the feeder's compound literals. All targets are
 * 32-bit ARM EABI (or the x86-64 host test build); the structs below are laid
 * out by the compiler exactly as the ioctl ABI expects. */

struct uipc_valloc_sub {
    void    **msg_pptr;
    uint32_t  size;
    uint32_t  wait_flag;
};

struct uipc_qid_sub {
    uint32_t  qid;
    void     *sub_ptr;
};

struct uipc_msg_req {
    uint32_t  qid;
    void     *msg_ptr;
};

struct uipc_recv_sub {
    void    **msg_pptr;
    uint32_t  timeout_ms;
};

struct uipc_pool_init_req {
    uint32_t  param;
    void     *out_ptr;
};

struct uipc_dynid_sub {
    uint32_t  op;
    uint32_t  param;
    uint32_t *id_out;
};

struct uipc_dynid_req {
    uint32_t  zero;
    void     *sub_ptr;
};

static int normalize_ioctl(int rc)
{
    if (rc == 0)
        return 0;
    if (rc == -1)
        return -errno;
    return rc < 0 ? rc : -EIO;
}

int a6400_uipc_open(struct a6400_uipc *u)
{
    uint32_t out_meta[8];
    struct uipc_pool_init_req init_req;
    struct uipc_dynid_sub dyn_sub;
    struct uipc_dynid_req dyn_req;
    void *pool;
    int rc;

    if (!u)
        return -EINVAL;
    u->fd = -1;
    u->reply_qid = 0;
    u->pool = NULL;
    u->pool_size = 0;

    u->fd = open(A6400_UIPC_DEV_PATH, O_RDWR | O_CLOEXEC);
    if (u->fd < 0)
        return -errno;

    memset(out_meta, 0, sizeof out_meta);
    init_req.param = 0;
    init_req.out_ptr = out_meta;
    rc = ioctl(u->fd, A6400_UIPC_IOCTL_POOL_INIT, &init_req);
    if (rc != 0) {
        int e = normalize_ioctl(rc);

        close(u->fd);
        u->fd = -1;
        return e;
    }
    if (!out_meta[0]) {
        close(u->fd);
        u->fd = -1;
        return -EPROTO;
    }

    /* The shared pool is the only region this client ever hands to the kernel;
     * message pointers below are offsets into it, never addresses we invent. */
    pool = mmap(NULL, out_meta[0], PROT_READ | PROT_WRITE, MAP_SHARED, u->fd, 0);
    if (pool == MAP_FAILED) {
        int e = -errno;

        close(u->fd);
        u->fd = -1;
        return e;
    }
    u->pool = pool;
    u->pool_size = out_meta[0];

    /* Dynamic reply id: acquire, never a literal. Feeder used op 0x2a with
     * parameter 729 (uvc_sensor_feeder_30fps.c:291-299). */
    dyn_sub.op = A6400_UIPC_DYNID_ACQUIRE;
    dyn_sub.param = A6400_UIPC_DYNID_ACQUIRE_PARAM;
    dyn_sub.id_out = &u->reply_qid;
    dyn_req.zero = 0;
    dyn_req.sub_ptr = &dyn_sub;
    rc = ioctl(u->fd, A6400_UIPC_IOCTL_DYNAMIC_ID, &dyn_req);
    if (rc != 0 || !u->reply_qid) {
        int e = normalize_ioctl(rc);

        munmap(u->pool, u->pool_size);
        u->pool = NULL;
        u->pool_size = 0;
        close(u->fd);
        u->fd = -1;
        return e ? e : -EPROTO;
    }

    a6400_uipc_purge(u);
    return 0;
}

void a6400_uipc_close(struct a6400_uipc *u)
{
    if (!u)
        return;
    if (u->fd >= 0) {
        if (u->reply_qid) {
            struct uipc_dynid_sub dyn_sub;
            struct uipc_dynid_req dyn_req;

            a6400_uipc_purge(u);
            dyn_sub.op = A6400_UIPC_DYNID_RELEASE;
            dyn_sub.param = 0;
            /* The physically run feeder passed the id value where the ABI
             * expects the id pointer (uvc_sensor_feeder_30fps.c:312). Keep the
             * exact call shape: the kernel driver reads the value, and changing
             * it here would be an untested ABI edit. */
            dyn_sub.id_out = (uint32_t *)(uintptr_t)u->reply_qid;
            dyn_req.zero = 0;
            dyn_req.sub_ptr = &dyn_sub;
            (void)ioctl(u->fd, A6400_UIPC_IOCTL_DYNAMIC_ID, &dyn_req);
            u->reply_qid = 0;
        }
        if (u->pool && u->pool_size)
            (void)munmap(u->pool, u->pool_size);
        u->pool = NULL;
        u->pool_size = 0;
        (void)close(u->fd);
        u->fd = -1;
    }
}

int a6400_uipc_valloc(struct a6400_uipc *u, uint32_t qid, void **msg, uint32_t size)
{
    struct uipc_valloc_sub sub;
    struct uipc_qid_sub req;
    int rc;

    if (!u || u->fd < 0 || !msg || !size)
        return -EINVAL;
    *msg = NULL;
    sub.msg_pptr = msg;
    sub.size = size;
    sub.wait_flag = 1; /* feeder:225-235 */
    req.qid = qid;
    req.sub_ptr = &sub;
    rc = ioctl(u->fd, A6400_UIPC_IOCTL_VALLOC, &req);
    if (rc != 0)
        return normalize_ioctl(rc);
    if (!*msg)
        return -EPROTO;
    return 0;
}

int a6400_uipc_free_msg(struct a6400_uipc *u, uint32_t qid, void *msg)
{
    struct uipc_msg_req req;

    if (!u || u->fd < 0 || !msg)
        return -EINVAL;
    req.qid = qid;
    req.msg_ptr = msg;
    return normalize_ioctl(ioctl(u->fd, A6400_UIPC_IOCTL_FREE, &req));
}

int a6400_uipc_send(struct a6400_uipc *u, uint32_t qid, void *msg)
{
    struct uipc_msg_req req;

    if (!u || u->fd < 0 || !msg)
        return -EINVAL;
    req.qid = qid;
    req.msg_ptr = msg;
    return normalize_ioctl(ioctl(u->fd, A6400_UIPC_IOCTL_SEND, &req));
}

int a6400_uipc_recv(struct a6400_uipc *u, uint32_t qid, void **msg, uint32_t timeout_ms)
{
    struct uipc_recv_sub sub;
    struct uipc_qid_sub req;
    int rc;

    if (!u || u->fd < 0 || !msg)
        return -EINVAL;
    *msg = NULL;
    sub.msg_pptr = msg;
    sub.timeout_ms = timeout_ms;
    req.qid = qid;
    req.sub_ptr = &sub;
    rc = ioctl(u->fd, A6400_UIPC_IOCTL_RECV, &req);
    if (rc != 0)
        return normalize_ioctl(rc);
    if (!*msg)
        return -EPROTO;
    return 0;
}

void a6400_uipc_purge(struct a6400_uipc *u)
{
    if (!u || u->fd < 0 || !u->reply_qid)
        return;
    for (;;) {
        void *msg = NULL;

        if (a6400_uipc_recv(u, u->reply_qid, &msg, 0) != 0 || !msg)
            break;
        (void)a6400_uipc_free_msg(u, u->reply_qid, msg);
    }
}

/* ---- DMM service --------------------------------------------------------- */
/* A DMM message is a pool allocation whose four prefix bytes carry the reply
 * queue id (feeder:336,360,384). `msg - 4` is inside the pool allocation, not
 * an arbitrary pointer. */

static void put_reply_qid(void *msg, uint32_t qid)
{
    memcpy((uint8_t *)msg - A6400_UIPC_MSG_PREFIX, &qid, sizeof qid);
}

static int16_t read_status(const void *reply)
{
    int16_t status = 0;

    memcpy(&status, (const uint8_t *)reply + A6400_DMM_REPLY_STATUS, sizeof status);
    return status;
}

/* Sends one prepared DMM message and returns the reply status cast to int. */
static int dmm_call(struct a6400_dmm *d, void *msg, uint32_t qid)
{
    void *reply = NULL;
    int rc, status;

    rc = a6400_uipc_send(d->uipc, qid, msg);
    if (rc != 0) {
        (void)a6400_uipc_free_msg(d->uipc, qid, msg);
        return -EIO;
    }
    rc = a6400_uipc_recv(d->uipc, d->uipc->reply_qid, &reply, 800);
    if (rc != 0 || !reply)
        return rc != 0 ? rc : -EPROTO;

    status = (int)read_status(reply);
    (void)a6400_uipc_free_msg(d->uipc, d->uipc->reply_qid, reply);
    return status;
}

int a6400_dmm_set_rule(struct a6400_dmm *d, uint8_t rule, uint16_t mode)
{
    uint8_t *p;
    void *msg = NULL;
    uint16_t op = (uint16_t)A6400_DMM_OP_SET_RULE;
    int rc;

    if (!d || !d->uipc || d->uipc->fd < 0)
        return -EINVAL;
    rc = a6400_uipc_valloc(d->uipc, A6400_UIPC_Q_DMM, &msg, 32);
    if (rc != 0)
        return rc;

    p = (uint8_t *)msg;
    memset(p, 0, 32);
    memcpy(p + 0x00, &op, sizeof op);
    p[0x02] = rule;
    memcpy(p + 0x16, &mode, sizeof mode);
    put_reply_qid(msg, d->uipc->reply_qid);
    return dmm_call(d, msg, A6400_UIPC_Q_DMM);
}

int a6400_dmm_open_unit(struct a6400_dmm *d, uint32_t handle,
                        uint32_t *phys, uint32_t *size)
{
    uint8_t *p;
    void *msg = NULL, *reply = NULL;
    uint16_t op = (uint16_t)A6400_DMM_OP_OPEN;
    uint16_t h = (uint16_t)handle;
    uint32_t wildcard = 0xffffffffu;
    int rc, status;

    if (!d || !d->uipc || d->uipc->fd < 0 || !phys || !size)
        return -EINVAL;
    rc = a6400_uipc_valloc(d->uipc, A6400_UIPC_Q_DMM, &msg, 24);
    if (rc != 0)
        return rc;

    p = (uint8_t *)msg;
    memset(p, 0, 24);
    memcpy(p + 0x00, &op, sizeof op);
    memcpy(p + 0x02, &h, sizeof h);
    memcpy(p + 0x0c, &wildcard, sizeof wildcard); /* feeder:383 */
    put_reply_qid(msg, d->uipc->reply_qid);

    rc = a6400_uipc_send(d->uipc, A6400_UIPC_Q_DMM, msg);
    if (rc != 0) {
        (void)a6400_uipc_free_msg(d->uipc, A6400_UIPC_Q_DMM, msg);
        return -EIO;
    }
    rc = a6400_uipc_recv(d->uipc, d->uipc->reply_qid, &reply, 800);
    if (rc != 0 || !reply)
        return rc != 0 ? rc : -EPROTO;

    status = (int)read_status(reply);
    if (status != 0) {
        (void)a6400_uipc_free_msg(d->uipc, d->uipc->reply_qid, reply);
        return status; /* never mask a failed unit open */
    }
    memcpy(phys, (const uint8_t *)reply + A6400_DMM_REPLY_OPEN_PHYS, sizeof *phys);
    memcpy(size, (const uint8_t *)reply + A6400_DMM_REPLY_OPEN_SIZE, sizeof *size);
    (void)a6400_uipc_free_msg(d->uipc, d->uipc->reply_qid, reply);
    return 0;
}

static int dmm_simple_op(struct a6400_dmm *d, uint16_t op, uint32_t handle)
{
    uint8_t *p;
    void *msg = NULL;
    uint16_t h = (uint16_t)handle;
    int rc;

    if (!d || !d->uipc || d->uipc->fd < 0)
        return -EINVAL;
    rc = a6400_uipc_valloc(d->uipc, A6400_UIPC_Q_DMM, &msg, 24);
    if (rc != 0)
        return rc;

    p = (uint8_t *)msg;
    memset(p, 0, 24);
    memcpy(p + 0x00, &op, sizeof op);
    memcpy(p + 0x02, &h, sizeof h);
    put_reply_qid(msg, d->uipc->reply_qid);
    return dmm_call(d, msg, A6400_UIPC_Q_DMM);
}

int a6400_dmm_close_unit(struct a6400_dmm *d, uint32_t handle)
{
    if (!handle || handle == 0xffffu)
        return 0; /* feeder:407-408: absent unit is not an error */
    return dmm_simple_op(d, (uint16_t)A6400_DMM_OP_CLOSE, handle);
}

int a6400_dmm_free_unit(struct a6400_dmm *d, uint32_t handle)
{
    if (!handle || handle == 0xffffu)
        return 0; /* feeder:351-352 */
    return dmm_simple_op(d, (uint16_t)A6400_DMM_OP_FREE, handle);
}

/* ---- DataflowInfra ------------------------------------------------------- */

static void fill_dataflow_header(uint8_t *hdr, uint32_t reply_id,
                                 uint16_t payload_len)
{
    uint32_t v32;
    uint16_t v16;

    v32 = reply_id;
    memcpy(hdr + 0x00, &v32, sizeof v32);
    v32 = A6400_DATAFLOW_MARKER;
    memcpy(hdr + 0x04, &v32, sizeof v32);
    v16 = 1; /* message number */
    memcpy(hdr + 0x08, &v16, sizeof v16);
    v16 = (uint16_t)(A6400_DATAFLOW_HEADER_SIZE + payload_len);
    memcpy(hdr + 0x0a, &v16, sizeof v16);
    v32 = A6400_DATAFLOW_HEADER_SIZE;
    memcpy(hdr + 0x0c, &v32, sizeof v32);
    v32 = A6400_DATAFLOW_HEADER_SIZE;
    memcpy(hdr + 0x10, &v32, sizeof v32);
}

int a6400_scalar_set_path(struct a6400_dmm *d, const struct a6400_scalar_path_cfg *cfg)
{
    uint8_t *p, *payload;
    void *msg = NULL, *reply = NULL;
    uint16_t v16;
    uint32_t v32;
    int rc, status;

    if (!d || !d->uipc || d->uipc->fd < 0 || !cfg)
        return -EINVAL;
    if (cfg->enable && !cfg->timeout_ms)
        return -EINVAL; /* a start request must always be bounded */

    a6400_uipc_purge(d->uipc);
    rc = a6400_uipc_valloc(d->uipc, A6400_UIPC_Q_SCALAR, &msg, 88);
    if (rc != 0)
        return rc;

    p = (uint8_t *)msg;
    memset(p, 0, 88);
    fill_dataflow_header(p, d->uipc->reply_qid, 68);

    payload = p + A6400_DATAFLOW_HEADER_SIZE;
    v16 = 0x2009; memcpy(payload + 0x00, &v16, sizeof v16);
    v16 = 0x0100; memcpy(payload + 0x02, &v16, sizeof v16);
    v16 = 0x0044; memcpy(payload + 0x04, &v16, sizeof v16);
    v16 = 1;      memcpy(payload + 0x06, &v16, sizeof v16);
    v32 = 0;      memcpy(payload + 0x08, &v32, sizeof v32);
    v16 = 0;      memcpy(payload + 0x0c, &v16, sizeof v16);
    payload[0x0e] = 0;
    payload[0x0f] = (uint8_t)A6400_DF_SELECTOR_PATH; /* feeder:459 */
    v16 = (uint16_t)(cfg->rate_fps << 8);
    memcpy(payload + 0x10, &v16, sizeof v16);
    payload[0x12] = 1;
    payload[0x13] = (uint8_t)cfg->comp_level;
    v16 = (uint16_t)cfg->width;
    memcpy(payload + 0x14, &v16, sizeof v16);
    v16 = 0; memcpy(payload + 0x16, &v16, sizeof v16);
    v32 = cfg->param_val;
    memcpy(payload + 0x18, &v32, sizeof v32);
    payload[0x1c] = 0;
    payload[0x1d] = 1;
    payload[0x1e] = 4;
    payload[0x1f] = 1;
    payload[0x40] = (uint8_t)(cfg->enable ? 1 : 0);

    rc = a6400_uipc_send(d->uipc, A6400_UIPC_Q_SCALAR, msg);
    if (rc != 0) {
        (void)a6400_uipc_free_msg(d->uipc, A6400_UIPC_Q_SCALAR, msg);
        return -EIO;
    }
    rc = a6400_uipc_recv(d->uipc, d->uipc->reply_qid, &reply, cfg->timeout_ms);
    if (rc != 0 || !reply)
        return rc != 0 ? rc : -EPROTO;

    /* The original handler's status word sits 12 bytes into the payload. */
    memcpy(&status, (const uint8_t *)reply + A6400_DATAFLOW_HEADER_SIZE + 12,
           sizeof status);
    (void)a6400_uipc_free_msg(d->uipc, d->uipc->reply_qid, reply);
    return status;
}

int a6400_scalar_get_jpeg(struct a6400_dmm *d, uint32_t timeout_ms,
                          struct a6400_jpeg_result *out)
{
    uint8_t *p, *payload;
    const uint8_t *r_payload;
    void *msg = NULL, *reply = NULL;
    uint16_t v16;
    uint32_t v32;
    int rc;

    if (!d || !d->uipc || d->uipc->fd < 0 || !out)
        return -EINVAL;
    memset(out, 0, sizeof *out);

    a6400_uipc_purge(d->uipc);
    rc = a6400_uipc_valloc(d->uipc, A6400_UIPC_Q_SCALAR, &msg, 40);
    if (rc != 0)
        return rc;

    p = (uint8_t *)msg;
    memset(p, 0, 40);
    fill_dataflow_header(p, d->uipc->reply_qid, 20);

    payload = p + A6400_DATAFLOW_HEADER_SIZE;
    v16 = 0x2009; memcpy(payload + 0x00, &v16, sizeof v16);
    v16 = 0x0100; memcpy(payload + 0x02, &v16, sizeof v16);
    v16 = 0x0014; memcpy(payload + 0x04, &v16, sizeof v16);
    v16 = 1;      memcpy(payload + 0x06, &v16, sizeof v16);
    v32 = 0;      memcpy(payload + 0x08, &v32, sizeof v32);
    v16 = 0;      memcpy(payload + 0x0c, &v16, sizeof v16);
    payload[0x0e] = 0;
    payload[0x0f] = (uint8_t)A6400_DF_SELECTOR_JPEG; /* feeder:503 */
    payload[0x10] = 1;                               /* poll */

    rc = a6400_uipc_send(d->uipc, A6400_UIPC_Q_SCALAR, msg);
    if (rc != 0) {
        (void)a6400_uipc_free_msg(d->uipc, A6400_UIPC_Q_SCALAR, msg);
        return -EIO;
    }
    rc = a6400_uipc_recv(d->uipc, d->uipc->reply_qid, &reply, timeout_ms);
    if (rc != 0 || !reply)
        return rc != 0 ? rc : -EPROTO;

    r_payload = (const uint8_t *)reply + A6400_DATAFLOW_HEADER_SIZE;
    memcpy(&out->err, r_payload + 12, sizeof out->err);
    out->ready = r_payload[16];

    if (out->err != 0 || out->ready == 0) {
        /* Ownership was NOT transferred: the handler kept its buffers. */
        (void)a6400_uipc_free_msg(d->uipc, d->uipc->reply_qid, reply);
        return 1;
    }

    {
        uint16_t handle1 = 0, size_shift = 0, handle2 = 0;

        memcpy(&handle1, r_payload + 20, sizeof handle1);
        memcpy(&size_shift, r_payload + 22, sizeof size_shift);
        memcpy(&handle2, r_payload + 24, sizeof handle2);
        out->handle1 = handle1;
        out->size_shift = size_shift;
        out->size_upper_bound = (uint32_t)size_shift << 7;
        out->handle2 = handle2;
    }
    (void)a6400_uipc_free_msg(d->uipc, d->uipc->reply_qid, reply);
    return 0;
}
