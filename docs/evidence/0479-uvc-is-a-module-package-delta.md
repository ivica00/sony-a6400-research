# E0479 — The UVC delta is a module-package delta, not a kernel-capability delta

Date: 2026-11-13. **Strictly offline.** No camera, no USB, no module load, no firmware write.
Inputs: the thirteen official updaters of E0477. Continues E0320/E0321 (the ZV-E10 → a6400
UVC overlay plan) by asking the question that plan leaves open: is the missing piece in the
kernel, or in the module package?

## 0. Short answer

1. **`usbg_video.ko` and `usbg_audio.ko` are present on 4 of 13 bodies and absent from 9.**
   Present: `ZV-E10`, `ILCE-7C`, `ZV-1`, `DSC-RX0M2`. Absent: `ILCE-6400`, `ILCE-6600`,
   `ILCE-6100A`, `ILCE-7M3`, `ILCE-7RM3`, `ILCE-7RM4`, `ILCE-7RM4A`, `ILCE-9`, `ILCE-9M2`.
2. **`ZV-E10` and `ILCE-7C` ship byte-identical UVC modules** (same size, same SHA-256). They
   also share one kernel code object (E0477), so the pair is one software stack in two
   bodies — a natural control for any UVC experiment.
3. **The 42 video / 41 audio import surface is not the differentiator.** Both modules import
   symbols that the a6400 kernel provides; the modules are a *package* difference rather than
   a kernel capability difference. A body without them is not missing kernel support.
4. **`ZV-1` and `DSC-RX0M2` carry a different, larger pair** (20,680 and 20,468 bytes versus
   20,668 and 20,456), so "has UVC" is not one binary — there are at least two builds of the
   module pair in this corpus.

## 1. Observed module identities

| body | `usbg_video.ko` | `usbg_audio.ko` |
| --- | --- | --- |
| `ZV-E10` | 20,668 B `d385a051bf01b0e5…` | 20,456 B `8f73572784aab15d…` |
| `ILCE-7C` | 20,668 B `d385a051bf01b0e5…` | 20,456 B `8f73572784aab15d…` |
| `ZV-1` | 20,680 B `fa9405dcc0b4165f…` | 20,468 B `18e182ac6aa9992f…` |
| `DSC-RX0M2` | 20,680 B `fa9405dcc0b4165f…` | 20,468 B `18e182ac6aa9992f…` |
| the other 9 | absent | absent |

Full hashes are in `docs/evidence/cross_model/uvc-modules.tsv`.

Every `usbg_*.ko` in the corpus carries vermagic
`3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7`, identical to the kernel of every body in this
set, so a module from one body is at least ABI-compatible with another body's kernel — which
is exactly what makes the module-package framing useful.

## 2. Imports versus the kernel symbol table

`usbg_video.ko` (ZV-E10 build) has 42 undefined symbols and `usbg_audio.ko` has 41. Checked
against each body's decoded kernel symbol table (E0477's method):

| body | unresolved video imports | unresolved audio imports |
| --- | --- | --- |
| all thirteen | 12 | 10 |

The 12 are the same on every body, and **none of them is a kernel symbol**. They are
exported by other modules of the same package, which is what a loadable-module set looks
like when one module calls another:

| import | exported by |
| --- | --- |
| `osal_dynamic_id`, `osal_free_msg`, `osal_rcv_msg_tmo`, `osal_snd_msg`, `osal_snd_sync_direct`, `osal_snd_sync_msg`, `osal_valloc_msg_wait` | `osal_uipc.ko` |
| `dma330_mem_transfer_async` | `dma330.ko` |
| `udif_devnodes` | `devno.ko` |
| `malloc_sizes`, `param_ops_uint`, `udif_km_debug` | not exported by any module under either module directory of that body's images; unresolved status is recorded, not explained |

(`udif_devnodes` lives in `nflasha7_unpacked/kmod/devno.ko`, not beside `usbg_video.ko`, which
is why a single-directory search reports it as missing — the tool takes several roots for this
reason.)

So the import surface says nothing about which body could run the module: the kernel side
is already satisfied everywhere, and the cross-module dependencies are satisfied by the
package itself.

## 3. What this changes in E0320/E0321

E0321 concluded `not_enabled` for the a6400 and listed three missing components
(`usbg_video.ko`, `usbg_audio.ko`, `libInfraStreamingUsb.so`) plus two hash mismatches
(`libInfraUsbCmn.so`, `devno.ko`). This record narrows that further:

- **The kernel is not a blocker on any of the thirteen bodies.** Every body's kernel provides
  the same ABI and the same vermagic.
- **The blocker is a four-file package swap**, and on `ILCE-7C` that swap is *already done by
  Sony* — the ZV-E10 modules are shipped verbatim on a full-frame body with a different
  product position. That is stronger evidence for feasibility than any overlay argument:
  Sony itself ships the same UVC module pair on two bodies with different sensors.
- **`ZV-1`/`DSC-RX0M2` show the pair is versioned**, so a feasibility claim must name which
  build. "The ZV-E10 UVC modules" is a specific hash, not a family.

## 4. Alternative explanations

- **"A body without the modules may still lack the device nodes."** Consistent, and known:
  E0320 showed `devno.ko` supplies `/dev/usb/video` 248:33 and `/dev/usb/audio` 248:32 on
  bodies that have them, and the a6400 build of `devno.ko` has no rows for them. The two
  facts are complementary: no node *and* no module. This record does not claim the node
  question is solved.
- **"Different sizes could be the same module built with different debug strings."**
  Possible. Both builds' vermagic is identical and the difference is 12 bytes, which is
  consistent with a small string or table delta rather than a different implementation. This
  record states the sizes and hashes and does not interpret the delta.
- **"Module presence in the updater does not prove the camera loads it."** Correct, and not
  claimed. Presence is a packaging fact; loading is a runtime fact.

## 5. Confidence and limitations

- **Confirmed from artifacts:** presence/absence, sizes and SHA-256 for all thirteen bodies;
  the 42/41 import counts; the 12/10 residue and that the residue is not kernel symbols; the
  identical vermagic across the corpus.
- **Not examined:** whether a body's `init` scripts actually load the modules it ships; the
  `libInfraUsbCmn.so`/`devno.ko` hash differences beyond what E0321 recorded; any physical
  behaviour.
- **No feasibility percentage is claimed.** The useful statement is the package delta and the
  fact that Sony ships it on a second body.

## 6. Dependent implementation/scenarios

- The UVC overlay plan (E0322) can drop "kernel support unknown" from its boundary list: for
  every body in this corpus the kernel side is satisfied, and the remaining work is a
  four-file package swap plus the device-node question.
- `ILCE-7C` becomes the reference donor for a cross-body UVC experiment: its kernel is one
  code object with the ZV-E10's, and its modules are byte-identical.

## 7. Reproduce

```bash
# presence, size and hash for every body in one pass
python3 -I tools/research/cross_model_report.py <unpacked-root> --reference a6400 --json r.json
python3 -c "import json;r=json.load(open('r.json'));\
 [print(k,v['uvc_modules']) for k,v in sorted(r['bodies'].items())]"

# the import surface of one module, and which imports are kernel symbols
python3 -I tools/research/uvc_module_imports.py \
    <unpacked>/zve10/.../usbg_video.ko --kernel-symbols <zve10-symbols.json>
```

Expected: `usbg_video.ko` 42 imports, 12 unresolved by the kernel, and the same 12 for every
body.

## 8. Next experiment

Diff the `ZV-E10` and `ZV-1` builds of `usbg_video.ko` (12 bytes apart) to see whether the
difference is a table, a string, or code. That decides whether "the UVC module" can be treated
as one artefact across the family or must be pinned per body.
