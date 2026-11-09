# E0202 — Original synchronous SMP completion ordering

`probe_uvc_ptp_smp_completion.py` executes original retained kernel generic_smp_call_function_interrupt0x6016114c, csd_lock_wait0x60160a8c and csd_unlock0x60160e30, plus original on_each_cpu wrapper/helper bodies. Kernel SHA-256 is checked against the established original image.

**11 controls pass**. Explicit request/list fixtures target two remote CPUs. A non-target CPU does not acknowledge. After the first callback returns, count remains1 and completion lock stays set. Pausing inside the last callback keeps the original waiter spinning. Only after the last callback returns does original code clear the last CPU bit, decrement count0, unlink the request and unlock; the original waiter then returns. Separate original on_each_cpu controls show wait0/1/2 forwarded as0/1/1 and local callback invoked with IRQ masked, restoring prior IRQ state afterward.

Callback bodies and list locks are explicit doubles. In on_each_cpu cases remote dispatch is a recorder; acknowledgement execution is tested separately with original interrupt bodies. This is not physical IPI/cache publication or retirement of unrelated ioctl callers.

```
python -m tools.research.probe_uvc_ptp_smp_completion --output-dir artifacts/analysis/uvc-ptp-smp-completion-e0202
```

No camera operation in this probe. It establishes the completion contract needed by E0203's synchronous code-visibility provider, without interpreting it as a whole-system caller barrier.
