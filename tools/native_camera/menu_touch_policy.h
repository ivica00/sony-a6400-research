/* Explicit MOD adapter policy. Live UI-thread bindings are required. */
#ifndef MENU_TOUCH_POLICY_H
#define MENU_TOUCH_POLICY_H
#include <stdint.h>
#ifdef _WIN32
#define MT_API __declspec(dllexport)
#else
#define MT_API
#endif
struct mt_event { uint32_t type; uint8_t mouse,button; };
struct mt_context {
    uint32_t active,menu,page,generation;
    uint32_t expected_tid,current_tid,rows,current_row,mouse;
};
struct mt_state { uint32_t armed,menu,page,generation,mouse,button,row; };
struct mt_ops {
    void *user;
    int (*position)(void *,unsigned,int16_t *,int16_t *);
    int (*hit)(void *,unsigned,int16_t,int16_t);
    int (*select)(void *,unsigned);
    void (*refresh)(void *);
};
enum { MT_IDLE=0,MT_ARMED=1,MT_SELECTED=2,MT_SAME=3,MT_CANCELLED=4,
       MT_INVALID=-1,MT_WRONG_THREAD=-2,MT_BACKEND=-3,MT_AMBIGUOUS=-4 };
/* MouseEvent is 24 bytes; parameters are NOT assumed to be coordinates.
   Native getters prove mouse@0/button@1/type@8. Gesture types are not remapped. */
MT_API int mt_decode(const uint8_t *,unsigned,struct mt_event *);
/* Bindings must use original coordinate, hit, selection and refresh methods.
   Caller must prove active main MENU/lifetime generation and UI-thread identity.
   This module contains no firmware addresses, hooks, RAM writes or host UI. */
MT_API int mt_process(struct mt_state *,const struct mt_context *,const struct mt_event *,const struct mt_ops *);
#endif
