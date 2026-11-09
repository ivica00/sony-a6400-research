/* Explicit MOD ABI bridge. The caller must supply actual registration masks
 * and must quiesce/unregister both native descriptors before retirement. */
#ifndef A6400_UVC_CALLBACK_BRIDGE_H
#define A6400_UVC_CALLBACK_BRIDGE_H
typedef unsigned int uvc_u32;
typedef unsigned char uvc_u8;
struct uvc_old_descriptor {
    uvc_u32 name;
    uvc_u8 config, interface_number, reserved[2];
    uvc_u32 private_data;
    uvc_u8 alternate, state_reserved[3];
    uvc_u32 callback[9];
};
struct uvc_reference_descriptor {
    uvc_u32 name;
    uvc_u8 config, primary_interface, reserved[2];
    const uvc_u8 *interfaces;
    uvc_u8 interface_count, count_reserved[3];
    uvc_u32 private_data;
    uvc_u8 alternate, state_reserved[3];
    uvc_u32 callback[9];
};
struct uvc_bridge {
    uvc_u32 magic;
    volatile uvc_u32 active, in_flight, started;
    int last_error;
    struct uvc_reference_descriptor *reference;
    struct uvc_reference_descriptor snapshot;
    uvc_u8 interface_snapshot[2];
    struct uvc_old_descriptor shadow[2];
    uvc_u32 started_interface;
    /* Optional native endpoint validation; returns matching gadgetcore wrapper. */
    uvc_u32 (*bulk_endpoint)(uvc_u32 count, uvc_u32 array);
};
typedef int (*uvc_register_fn)(struct uvc_old_descriptor *);
typedef int (*uvc_unregister_fn)(struct uvc_old_descriptor *);

uvc_u32 a6400_uvc_bridge_size(void);
int a6400_uvc_bridge_prepare(struct uvc_bridge *, struct uvc_reference_descriptor *);
int a6400_uvc_bridge_activate(struct uvc_bridge *, uvc_u32 registered_mask);
int a6400_uvc_bridge_quiesce(struct uvc_bridge *);
int a6400_uvc_bridge_retire(struct uvc_bridge *, uvc_u32 still_registered_mask);
int a6400_uvc_bridge_register(struct uvc_bridge *, uvc_register_fn, uvc_unregister_fn);
int a6400_uvc_bridge_unregister(struct uvc_bridge *, uvc_unregister_fn);
struct uvc_old_descriptor *a6400_uvc_bridge_shadow(struct uvc_bridge *, uvc_u32 index);
int a6400_uvc_bridge_last_error(struct uvc_bridge *);
#endif
