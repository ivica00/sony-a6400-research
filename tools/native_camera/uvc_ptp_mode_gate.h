/* MOD admission primitive, not Sony firmware behavior. All native mode-change
 * entries must be routed through it before it can provide cross-owner exclusion.
 * Storage/code lifetime and callback draining are separate caller obligations. */
#ifndef A6400_UVC_PTP_MODE_GATE_H
#define A6400_UVC_PTP_MODE_GATE_H
struct a6400_uvc_mode_gate { volatile unsigned int word; };
int a6400_uvc_mode_enter(struct a6400_uvc_mode_gate *);
int a6400_uvc_mode_leave(struct a6400_uvc_mode_gate *);
int a6400_uvc_mode_claim(struct a6400_uvc_mode_gate *);
int a6400_uvc_mode_release(struct a6400_uvc_mode_gate *);
#endif
