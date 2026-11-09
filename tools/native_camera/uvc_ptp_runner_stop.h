#ifndef A6400_UVC_RUNNER_STOP_H
#define A6400_UVC_RUNNER_STOP_H
/* Permission to retire requires both successful STOP and an idle receipt.
 * This does not bound or cancel a blocked kernel call. */
struct a6400_runner_stop_ops {
    int (*stop)(void *);
    int (*status)(void *, int [4]);
};
static inline int a6400_runner_stop_verified(const struct a6400_runner_stop_ops *ops,
                                           void *context, int state[4])
{
    unsigned int i;
    if (!ops || !ops->stop || !ops->status || !state) return 0;
    for (i=0;i<4;++i) state[i]=-1;
    if (ops->stop(context)) return 0;
    if (ops->status(context,state)) return 0;
    /* phase IDLE, pin absent, descriptor hooks absent, no retained error */
    for (i=0;i<4;++i) if (state[i]) return 0;
    return 1;
}
#endif
