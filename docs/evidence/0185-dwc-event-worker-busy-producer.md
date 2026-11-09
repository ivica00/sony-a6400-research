# E0185 — DWC event worker produces the pullup busy bit

## Source and scope

Offline analysis and execution of original kernel SHA-256 `12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`. No camera access, upload, mode change or module change. E0182 remains the module candidate; combined activation is not ready.

## Producer and consumer linkage

E0184 pullup uses `*(dwc+0xcc)` as its event object and waits for bit 0 of object+0x10 to clear. Original `dwc3_thread_interrupt` at `0x602b1378` reads the same table at dwc+0xcc, indexing entries by event-buffer index. On a nonzero event count from the MMIO window, it stores count at event+0xc and sets bit 0 at event+0x10 (`0x602b13d4..13dc`).

After processing the counted records it zeroes event+0xc and clears only bit 0 at event+0x10 (`0x602b18a8..18b8`). Other flag bits are preserved. Each processed record advances the ring position by four modulo 4096 and acknowledges four bytes to the event-count MMIO register. Therefore the first-buffer busy bit consumed by pullup is owned by this original kernel event worker, not a MOD completion variable. This does not establish that only one event buffer exists physically; the worker iterates dwc+0x2c8, while pullup reads the first table entry.

The worker calls `dwc3_ep0_interrupt` at `0x602b1444` for enabled endpoint zero/one events. Separately, original `dwc3_ep0_delegate_req` (`0x602b28e4`) unlocks dwc+0x70 and enables migration, calls the gadget driver's setup callback at driver+0x10, then disables migration and relocks before returning the callback result. Callback lifetime is therefore not protected simply by continuously holding that lock.

## Executed original controls

New `tools/research/probe_uvc_ptp_event_busy.py` passes **4 cases**:

- complete original event-worker execution with zero, one and two records (0/4/8 bytes), checking exact busy set/clear, record acknowledgements, ring position and preservation of other flag bits;
- complete original setup-delegate body, checking argument identity, unlock/migration/callback/relock order and propagation of -95.

```
python -m tools.research.probe_uvc_ptp_event_busy --output-dir artifacts/analysis/uvc-ptp-event-busy-e0185
```

Manifest: `artifacts/analysis/uvc-ptp-event-busy-e0185/manifest.json`.

The worker uses explicit event/MMIO fixtures and a disabled endpoint, so it does not execute an EP0 callback. The delegate case is a separate probe with an explicit setup callback double. Locks, migration and optional MMIO barrier hook are fixtures/doubles; there is no physical IRQ, hardware completion or end-to-end EP0 claim. Existing module tests were not rerun because module code did not change.

## Implication and remaining work

This resolves the producer identity behind E0184's busy loop and shows why lock ownership alone cannot establish callback retirement. It does not establish the execution context or dependencies of every callback reached by the event worker, nor that a future event cannot start after the observed clear. Keep publication CPU barrier and USB teardown as separate stages. Next verify actual gadget setup callback completion and the hardware event-admission/stop contract before enabling or retiring descriptor hooks. No new hook is installed and the camera remains appropriate in Mass Storage.
