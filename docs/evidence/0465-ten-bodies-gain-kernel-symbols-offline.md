# E0465 — Ten bodies gain evidence-backed kernel symbols offline, without a camera

Date: 2026-11-13. **Strictly offline.** No camera, no USB, no `/proc` read, no firmware write.
Inputs: the thirteen official updaters of E0462. This record exists to move bodies out of
`STATUS_UNVERIFIED` stub without a physical probe, which is the one step
`docs/ADDING_A_BIONZX_CAMERA.md` currently requires a camera for.

## 0. Short answer

1. **The six USB-side kernel symbols this repository's profile schema asks for are resolvable
   from the packaged image alone, for every body in the corpus.** Ten bodies that are stubs or
   partial today can carry real addresses instead of a declared stub.
2. **The offline decode is byte-identical to a live read where both exist.** For `ILCE-6400`,
   the seven kernel symbols this project already holds from a live `/proc/kallsyms` read
   (E0348) match the offline decode exactly, all seven. That is the calibration that makes an
   offline-only profile defensible.
3. **`osal_snd_msg`, `osal_rcv_msg_tmo` and `dma330_mem_transfer_async` are not kernel
   symbols at all** — they live in `osal_uipc.ko` and `dma330.ko`. A profile that requires them
   from `kallsyms` cannot be filled for any body; the schema's symbol list needs to say which
   layer each symbol belongs to.
4. **Addresses are per-build, and symbol-set equality does not carry them.** `ILCE-6100A`,
   `ILCE-7M3` and `ILCE-7RM4A` share one symbol set, yet 4,033 of the 4,042 addresses that
   differ between them are function symbols (E0462), so their values cannot be derived from
   one another by an offset. A copied address is wrong; a transcribed one from the same image
   is right.

## 1. Calibration against a live read

`ILCE-6400`, offline decode of the 8.2.5.7 package versus the live `/proc/kallsyms` values this
repository already records (E0348):

| symbol | live (E0348) | offline (this record) | |
| --- | --- | --- | --- |
| `usb_gadgetcore_ioctl` | `0x602b8844` | `0x602b8844` | match |
| `usb_gadgetcore_register_driver` | `0x602b8610` | `0x602b8610` | match |
| `usb_gadgetcore_unregister_driver` | `0x602b8560` | `0x602b8560` | match |
| `usb_gcw_start` | `0x602bd7f8` | `0x602bd7f8` | match |
| `usb_gcw_stop` | `0x602bd834` | `0x602bd834` | match |
| `setup_req` | `0x602b94a4` | `0x602b94a4` | match |
| `make_config_desc` | `0x602bbc54` | `0x602bbc54` | match |

7 of 7. The three remaining symbols in the schema's list (`osal_snd_msg`,
`osal_rcv_msg_tmo`, `dma330_mem_transfer_async`) are **absent from the kernel symbol table of
every body** and are exported by `osal_uipc.ko` and `dma330.ko` instead — see E0464's
import-attribution table. Their live values are module addresses, which is why they look like
`0x5f04916c` in the catalogue rather than `0x602b…`.

## 2. The six resolvable symbols, per body

| body | build | `usb_gadgetcore_ioctl` | `…register_driver` | `usb_gcw_start` | `usb_gcw_stop` | `setup_req` | `make_config_desc` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `ILCE-6600` | 8.2.6.0 | `0x602b8844` | `0x602b8610` | `0x602bd7f8` | `0x602bd834` | `0x602b94a4` | `0x602bbc54` |
| `ILCE-7M3` | 8.2.7.6 | `0x602bc864` | `0x602bc630` | `0x602c1818` | `0x602c1854` | `0x602bd4c4` | `0x602bfc74` |
| `ILCE-7C` | 8.2.7.6 | `0x602bccf8` | `0x602bcaac` | `0x602c1e4c` | `0x602c1e88` | `0x602bd9d8` | `0x602c0204` |
| `ILCE-7RM3` | 8.2.5.7 | `0x602b81d8` | `0x602b7fa4` | `0x602bd18c` | `0x602bd1c8` | `0x602b8e38` | `0x602bb5e8` |
| `ILCE-7RM4` | 8.2.6.0 | `0x602bb810` | `0x602bb5dc` | `0x602c07c4` | `0x602c0800` | `0x602bc470` | `0x602bec20` |
| `ILCE-7RM4A` | 8.2.7.6 | `0x602bc860` | `0x602bc62c` | `0x602c1814` | `0x602c1850` | `0x602bd4c0` | `0x602bfc70` |
| `ILCE-9` | 8.2.5.7 | `0x602bb860` | `0x602bb62c` | `0x602c0814` | `0x602c0850` | `0x602bc4c0` | `0x602bec70` |
| `ILCE-9M2` | 8.2.6.0 | `0x602bc3e4` | `0x602bc1b0` | `0x602c1398` | `0x602c13d4` | `0x602bd044` | `0x602bf7f4` |
| `ZV-1` | 8.2.6.0 | `0x602bca2c` | `0x602bc7e0` | `0x602c1b80` | `0x602c1bbc` | `0x602bd70c` | `0x602bff38` |
| `DSC-RX0M2` | 8.2.6.0 | `0x602b8cd8` | `0x602b8a8c` | `0x602bde2c` | `0x602bde68` | `0x602b99b8` | `0x602bc1e4` |

`ILCE-6600`'s six values are *identical* to `ILCE-6400`'s, which is consistent with E0462's
finding that the two kernels are one symbol set.

Note the near-misses that make a copied address dangerous: `ILCE-7RM4A` sits exactly
`0x1000` away from `ILCE-9` on all six symbols, and `ILCE-7M3` sits exactly `0x4` away from
`ILCE-7RM4A` on all six — despite `ILCE-7M3` and `ILCE-7RM4A` sharing one symbol set. A
constant delta is visible only when you have both images; copying one body's value to another
is wrong by a fixed amount that no reader can notice.

## 3. What each body can now claim

For a body whose kernel is in this corpus, these fields become sourceable from evidence rather
than from a stub:

- `kernel_version` — from the image's own banner (`3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7`);
- `firmware_version` — the updater's published version, which is the input's identity;
- `kallsyms.*` — the six symbols above, from this record;
- `soc_verified` — still **not** claimable from a `fwtool` arch field. `docs/ADDING_A_BIONZX_CAMERA.md`
  is right that a third-party table is not a SoC measurement; this record does not change that.

`uipc_queues` and `usb` are **not** filled here: queue ids and PIDs come from the application
layer and from the host bus respectively, and neither is contained in a packaged image in a
form this record measured. Those stay as boundaries.

## 4. Alternative explanations

- **"Offline symbol addresses differ from the running camera's because of relocation."** Not
  for kallsyms: the kernel is not loaded at a randomised base on this platform, and E0348's
  live values match the package byte for byte. The banner note in the a6400 profile ("only
  kallsyms addresses are ASLR-free") is confirmed, not contradicted.
- **"The package is 8.2.5.7 but the live camera runs 8.2.6.0, so the decode may be stale."**
  That is a real risk for any body whose installed firmware is newer than its published
  package, and it is why the reference above is stated as *the 8.2.5.7 package* and not as
  *the camera*. Where a body's live build is known to differ, the profile must record both.
- **"A resolved symbol is presence evidence, not callability."** Agreed and preserved: this
  record adds addresses, not behaviour claims.

## 5. Confidence and limitations

- **Confirmed from artifacts:** all six symbol values for all ten bodies; the seven-way
  match against the live `ILCE-6400` read; the absence of the three module-layer symbols from
  every kernel table.
- **Not examined:** whether a given body's installed firmware matches its published package;
  `uipc_queues`; USB PIDs and `bcdDevice`; anything requiring a running camera.
- **The schema change is proposed, not made.** This record states that three of the ten
  symbols in the profile schema cannot ever come from `kallsyms`; whether to relabel them is
  the owner's call.

## 6. Dependent implementation/scenarios

- `ILCE-6100`, `ILCE-6600` and `ILCE-7M3` stubs can become sourced profiles with these values.
- A future body without a camera can be onboarded to the point of a sourced profile, with the
  read-only probe needed only for `uipc_queues`, USB identity and the SoC measurement.

## 7. Reproduce

```bash
# one body, six values
python3 -I tools/research/decode_kernel_kallsyms.py \
    --input <unpacked>/<body>/.../nflasha3_unpacked/vmlinux.bin \
    --sha256 <sha256> --output <body>.json
python3 -c "
import json,sys
s={x['name']:x['address'] for x in json.load(open('<body>.json'))['symbols']}
for n in ('usb_gadgetcore_ioctl','usb_gadgetcore_register_driver','usb_gcw_start',
          'usb_gcw_stop','setup_req','make_config_desc'): print(n, hex(s[n]))"

# every body, plus the reference calibration
python3 -I tools/research/cross_model_report.py <unpacked-root> --reference a6400 --json r.json
```

Expected: the ten rows of section 2, and `ILCE-6400`'s six values equal to its live values.

## 8. Next experiment

Take `ILCE-9` (build 8.2.5.7, but a *unique* symbol set) and check whether its six values can
be derived from the `ILCE-6400` package by the delta between the two builds rather than read
from its own package. If a derivation exists, a body's profile becomes predictable from a
neighbour; if it does not, the per-body package is confirmed as necessary.
