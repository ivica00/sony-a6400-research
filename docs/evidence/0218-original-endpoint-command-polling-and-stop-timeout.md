# E0218 — Endpoint command polling and STOP timeout handling

Date: 2026-11-09. Offline only; no physical access, upload or module changes.

## Original endpoint command

`probe_uvc_ptp_endpoint_command.py` executes original command602b0220 from the pinned kernel with a scripted MMIO register bank. It verifies native parameter writes, command/busy publication, poll count and PHY-restore service arguments.

The original loop initializes a500-attempt counter. It returns0 when bit0x400 clears; persistent busy produces500polls,499delay calls and result-110. Delay helper60257f04 is a service recorder, so this is a bounded poll-count proof, **not** a measured elapsed deadline or physical timeout. Mode4 skips the PHY register adjustment; the tested mode0 saves0x140, clears those bits and passes the saved value to restore. Nonzero command-status bits with busy already clear still produce0 in this body; no hardware success beyond busy clear is established.

## Original STOP wrapper

The same probe also executes602b03d8 through the original command body. With resource index0 it returns without command or delay. With a nonzero index it issues the ENDTRANSFER-shaped command, handles a timeout through the original warning path, clears endpoint resource index+0x57 and flag0x10 at+0x4c, and calls the post-command delay helper. Those bookkeeping fields are cleared even when the command returned-110. The wrapper is void; cleared resource/flag alone is therefore not proof that hardware accepted STOP or DMA ceased.

Seven passing cases: immediate completion, completion on third poll, persistent busy timeout, status bits with busy clear, idle STOP, completed STOP and STOP with command timeout. The timeout-wrapper case verifies original warning-path execution and subsequent bookkeeping clear. Warning emission, zeroing, optional MMIO callback absence, delay and PHY restore are explicit service fixtures.

Artifacts: `artifacts/analysis/uvc-ptp-endpoint-command-e0218/manifest.json`. MMIO timing is scripted, not camera observation. No real command timing, hardware stop, DMA termination, IRQ interaction or configured teardown is proven. The persistent busy command register remains busy in the emulated register bank after wrapper bookkeeping clears; this demonstrates why software fields cannot be used as a DMA completion certificate.

## Implications

The command poll itself is bounded under returning service doubles; it differs from E0184's unbounded pullup busy wait. It does not establish which path blocked E0210. Actual lock acquisition, delay calibration, pullup event-busy producer, and callbacks remain separate. E0212 video-control rejection and E0215 runner checks remain offline; do not bypass native STOP or unload merely because resource fields cleared.

No general-suite rerun for this isolated tool; last612passing result remains E0215. Camera last verified recovered MSC. Next: join command failure semantics with native teardown receipts and establish recoverable observation before further physical activation.
