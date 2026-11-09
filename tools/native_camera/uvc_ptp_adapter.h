/* Offline-only adapter pieces. Not bound to a live callback. */
#ifndef A6400_UVC_PTP_ADAPTER_H
#define A6400_UVC_PTP_ADAPTER_H
/* Caller owns both 8-byte buffers. Output must remain alive for every native
 * consumer. This API does not establish callback/completion lifetime. */
int a6400_uvc_ptp_translate_setup(const unsigned char *wire,
                                unsigned int wire_interface,
                                unsigned char *native);
/* Returns the native gadgetcore wrapper for enabled HS Bulk IN 0x82.
 * dwc/list must originate from the kernel START contract, never host pointers. */
unsigned int a6400_uvc_ptp_select_endpoint(void *dwc, unsigned int packed_count,
                                        void *const *list);
#endif
