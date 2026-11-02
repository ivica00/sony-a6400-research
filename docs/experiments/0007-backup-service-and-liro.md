# Experiment 0007: Backup service and LIRO startup

Question: does the module request depend on unsupplied backup-service replies, and what does the original LIRO entry do with a zero address?

Use the hash-checked inputs and commands in [E0029](../evidence/0029-backup-service-guard-and-liro-entry.md). Strict process runs have three million instructions and 45 seconds, no injected messages, and no backup response. Stop before acknowledging queue `0x003e014d`, preserving request words, PC, syscall and zero supplied replies.

Run a separate historical control with `--backup-service unverified-ack`. Preserve old reports; do not present that run's settings, address or downstream module request as camera-runtime facts. The default no-response interpreter baseline remains unchanged.

For isolated LIRO windows, use explicit constructed section/state/stack mappings and only the three preimage-checked ABS32 literals. Stop before external calls. Address conversion controls are constructed inputs; no resulting address is selected as a real machine map. Do not execute module registration, kernel threads, firmware entry or camera operations.

Reject zero-filled service results inferred from untouched messages, forced negative service responses, invented persistent settings, skipped recipient execution presented as success, or automatic mapping of unknown firmware addresses. Require bounds and provenance checks for host-side IPC copies. Keep timeout, fault, unexpected flow and budget exhaustion distinct from reached boundaries.
