# Experiment 0005: Original libc clone return

Question: can original libc instructions own pthread entry and return while preserving the guarded startup boundaries?

Use the hash-checked firmware inputs, static namespace and explicit assumptions recorded in [E0027](../evidence/0027-original-clone-return-and-phase-survey.md). Execute its exact reproduction commands in fresh probes. Supply no queue stimuli, entropy, writable mount state, kernel-module insertion or device writes. Keep the earlier reports separately; do not replace their results to match new instruction counts.

Controls: the default no-response probe must retain its first syscall at 1,183 instructions; unsupported clone flags and unwritable parent-TID memory must stop before mutation; constructed ARM fixtures must demonstrate a copied syscall continuation and guest-controlled dispatch/return for both ARM and Thumb functions at different addresses.

Bounds: `a` has three million instructions/60 seconds; `i` has 45 million/240 seconds; `l` has three million/45 seconds. Budget exhaustion and timeouts are distinct outcomes, never successful initialization. Reports retain syscall return PCs, copied CPSR, thread/TLS observations, file operations, library activation results and framebuffer transactions.

Interpretation: worker termination and event-loop execution validate only those bounded process observations. `i` must retain its unsupplied entropy guard, and `l` must retain its unknown metadata guard unless separate evidence establishes those contracts. Failed library loads remain failures. VFP/NEON state and camera scheduler behavior are outside this experiment. No camera UI milestone is claimed without original display submissions and validated decoding.
