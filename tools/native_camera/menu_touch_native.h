/* Exact-version native bindings. NOT a hook installer or lifetime observer. */
#ifndef MENU_TOUCH_NATIVE_H
#define MENU_TOUCH_NATIVE_H
#include "menu_touch_policy.h"
struct mt_native_binding {
    volatile uint32_t *epoch;
    struct mt_context context;
    int fault;
};
/* epoch MUST be driven by verified native lifetime/transition hooks. An
   invented constant is not a valid deployment. NULL/zero fails closed.
   Caller dispatches only from the natural input consumer on UI TID380. */
int mt_native_context(volatile uint32_t *epoch,struct mt_context *out);
int mt_native_bind(struct mt_native_binding *,volatile uint32_t *,struct mt_ops *);
#endif
