/* OFFLINE candidate: no registration, USB transition or camera calls. */
#ifndef A6400_UVC_PTP_DESCRIPTORS_H
#define A6400_UVC_PTP_DESCRIPTORS_H

struct a6400_candidate_endpoint {
    unsigned char address, attributes;
    unsigned short max_packet;
    unsigned char interval, reserved5[3];
    unsigned int extra_size;
    const void *extra;
    const void *companion;
};
struct a6400_candidate_alternate {
    unsigned char alternate, endpoint_count, reserved2[2];
    struct a6400_candidate_endpoint *endpoints;
    unsigned char klass, subclass, protocol, string_index;
    unsigned int extra_size;
    void *extra;
};
struct a6400_candidate_interface {
    unsigned char number, alternate_count, reserved2[2];
    struct a6400_candidate_alternate *alternates;
};
struct a6400_candidate_config {
    unsigned char index, value, interface_count, reserved3;
    struct a6400_candidate_interface *interfaces;
    unsigned char string_index, attributes, max_power, reserved11;
    void *otg;
    unsigned int reserved16;
    void *associations;
};
struct a6400_candidate_device {
    unsigned char device_fields[5];
    unsigned char config_count;
    unsigned char reserved6[2];
    struct a6400_candidate_config *configs;
    unsigned int reserved12;
};
struct a6400_candidate_string {
    unsigned char index, size, reserved[2];
    const void *data;
};
struct a6400_candidate_language {
    unsigned short language;
    unsigned char string_count, reserved;
    struct a6400_candidate_string *strings;
};

/* Native Sony per-speed table (16-byte entries). HS is entry zero, as
 * demonstrated by original make_config_desc speed==3/type==2. */
struct a6400_uvc_ptp_candidate {
    struct a6400_candidate_device speed[3];
    unsigned char metadata[40]; /* native descriptor table total = 88 bytes */
    struct a6400_candidate_config config;
    struct a6400_candidate_interface interfaces[3];
    struct a6400_candidate_alternate alternates[3];
    struct a6400_candidate_endpoint ptp_endpoints[3];
    struct a6400_candidate_endpoint video_endpoint;
    unsigned char vc_extra[40];
    unsigned char vs_extra[61];
    struct a6400_candidate_language language;
    struct a6400_candidate_string strings[3];
    unsigned char string_data[3][64];
    struct a6400_candidate_config fs_config;
    struct a6400_candidate_interface fs_interface;
    struct a6400_candidate_alternate fs_alternate;
    struct a6400_candidate_endpoint fs_endpoints[3];
};

void a6400_uvc_ptp_candidate_init(struct a6400_uvc_ptp_candidate *candidate);
/* Raw, independently bounded USB descriptors read from this camera. Inputs
 * must outlive this synchronous call only; all string payloads are copied.
 * Current supported source uses indices 1/2/3 and LANGID 0409. */
int a6400_uvc_ptp_candidate_identity(struct a6400_uvc_ptp_candidate *candidate,
                                  const unsigned char *device,
                                  const unsigned char *manufacturer,
                                  const unsigned char *product,
                                  const unsigned char *serial);
/* Insert one video IAD into a complete original-serialized configuration.
 * Call before applying the host's requested-length truncation. */
int a6400_uvc_ptp_candidate_add_iad(unsigned char *wire,
                                 unsigned int length,
                                 unsigned int capacity);
/* Offline candidate EP0 path. Caller must hold descriptor topology stable
 * and provide actual gadgetcore/output objects. HS configuration zero only. */
int a6400_uvc_ptp_candidate_config_reply(struct a6400_uvc_ptp_candidate *candidate,
                                      void *gadgetcore,
                                      const unsigned char *setup,
                                      unsigned char *output,
                                      unsigned int output_capacity);
/* Unified synchronous native descriptor path. HS: PTP+UVC; FS: PTP-only.
 * Supports device/config/string/qualifier/other-speed, not live registration. */
int a6400_uvc_ptp_candidate_descriptor_reply(struct a6400_uvc_ptp_candidate *candidate,
                                          void *gadgetcore,
                                          const unsigned char *setup,
                                          unsigned char *output,
                                          unsigned int output_capacity);
/* Caller must establish native allocator provenance and stabilize this graph.
 * Check contents against the immutable template; does not acquire a lock. */
int a6400_uvc_ptp_validate_native_copy(struct a6400_uvc_ptp_candidate *candidate,
                                     const void *native_table);
#endif
