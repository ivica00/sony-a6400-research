#ifndef A6400_NATIVE_MONITOR_SNAPSHOT_H
#define A6400_NATIVE_MONITOR_SNAPSHOT_H
/* Private collector memory, never a pointer into Sony's process. A successful
 * snapshot does not consume output or certify exclusive cursor ownership. */
struct a6400_monitor_snapshot {
    unsigned int header[4];
    unsigned int size;
    unsigned char data[0x7bf0];
};
extern struct a6400_monitor_snapshot a6400_monitor_snapshot;
/* Set only after confirmed publication by the current action; UINT_MAX else. */
extern unsigned int a6400_monitor_published_end;
#endif
