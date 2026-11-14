# E0172 — Original Kernel Acknowledgment to Final Callback Unregistration

Date: 2026-11-08. Offline continuation of E0171. No physical camera access or production module changes.

## New Executed Boundary

`tools/research/probe_uvc_ptp_kernel_unregister.py --acknowledgement` now executes the original `__k_4u_wait_cb` at `.text+0xe8c`, the original queue lookup at `.text+0x2330`, `finish_callback` at `.text+0x4154`, and the original empty-queue processing continuation at `.text+0x2d10`, alongside the previously verified wait/wake/unregister/free_cb functions.

The source remains a6400 `osal_uipc.ko` SHA-256 `3743275bc964a2804b80cde4f589f60876b795fbeeccd3cbf2c18a0da2dc8567`. Original ELF relocations were applied. Decisions and callback count changes are not host replacements.

## Full Verified Sequence

1. The original unregister helper for a callback executed by another thread sets the retire flag, registers a stack waiter, and stops before `schedule`. The actual emulated CPU context of the waiter is preserved.
2. On a separate stack, the original kernel `wait_cb` receives a 16-byte input. User-copy is an explicit replacement; the contents, per-worker owner, and current task are explicit fixture data.
3. The original code binds the worker slot to the task, takes the previous callback and message from the per-worker slot, and clears the previous callback slot **before** final processing.
4. For the verified asynchronous callback, original `finish_callback` finds the queue through an actual lookup on fixture queue ID 13, decrements active count `1→0`, and calls the original wake helper.
5. The wake helper removes the waiter, clears its callback pointer, and calls `wake_up_process` for the waiter (service replacement). The registration is still not freed until the waiter resumes.
6. The acknowledgment thread stops at `schedule` while waiting for new work from the empty queue. After restoring the waiter's CPU context, original unregister continues, original `free_cb` decrements the allocation counter, passes the block to the final allocator (explicit replacement), and clears the registered slot.

Unlike the positive completion fixture of E0171, the new acknowledgment case **does not set active count to zero via a host write**. Original `finish_callback` does that. The user callback itself was not executed in this kernel test; the per-worker pending slot is an explicit initial fixture. E0170 separately proves the original user callback return up to the next wait ioctl.

## Worker Identity

A negative path was also verified:

- If the slot is already bound to another task pointer, `wait_cb` returns `-EINVAL` (`-22`), without clearing the pending callback or changing the count.
- Index 4 is rejected with `-EINVAL`; the original check allows indices `0..3`. The callback remains pending and active.

This provides a concrete kernel contract for binding the executor. It does not prove the physical TID, the number of current workers, or their process identity on the connected camera.

## Checks and Exact Scope

**40 checks pass**, including the earlier 26 and 14 additional checks for the acknowledgment chain and negative inputs. Manifest: `artifacts/analysis/uvc-ptp-ack-e0172/manifest.json`; log: `artifacts/uvc-ptp-ack-e0172.log`. The basic mode without the acknowledgement option passes all 26 checks again; probe syntax was verified.

The verified profile is an asynchronous callback, an empty queue for the next job, and a disabled queue flag that enables additional message freeing. `finish_callback` paths for other profiles, message ownership, real locks, the scheduler, copy services, and the final allocator are not proven. Lock/unlock, `schedule` boundaries, and `wake_up_process` remain explicit services; physical concurrency or a successful camera transaction is not claimed.

## Consequence and Next Step

For this profile, the safe boundary for OSAL unregistration from another thread is **acknowledgment of the previous callback, waking the waiter, and successful return of the waiter**, with resources preserved during waiting and on interrupt. Exiting the user callback function or sending status alone is not a sufficient substitute signal.

This OSAL contract must not be automatically applied to gadgetcore/EP0 callbacks. The shared E0164 module uses different callbacks and still does not have proven shared coordination with original USB mode changes. The next integration decision should connect the confirmed main USB thread, its direct stop entries, and the lifetime of EP0/gadget callbacks; there is no need to guess further about OSAL completion of this profile.

The module remains unloaded and `physical_test_ready:false`. Production code was not modified; the last full project regression remains 605 tests from E0164. Concurrent sensor UVC and PTP on the camera remain incomplete.
