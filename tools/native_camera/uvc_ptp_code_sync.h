#ifndef A6400_UVC_PTP_CODE_SYNC_H
#define A6400_UVC_PTP_CODE_SYNC_H
/* Instruction visibility only, NOT old-caller retirement. Caller serializes
 * updates and pins callback code until this synchronous operation returns. */
int a6400_uvc_sync_code(unsigned long,unsigned long);
#endif
