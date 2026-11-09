/* Target-specific public module-reference ABI, verified against Sony kernel.
 * Call only from an already module-owned file operation, while module is LIVE. */
#ifndef A6400_MODULE_SELF_REF_H
#define A6400_MODULE_SELF_REF_H
int a6400_module_self_get(void);
void a6400_module_self_put(void);
#endif
