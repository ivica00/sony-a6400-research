# E0482 — Three declared stubs gain sourced values: ILCE-6100A, ILCE-6600, ILCE-7M3

Date: 2026-11-13. Offline packaged firmware only: no camera, no USB, no updater execution.
This record exists because `docs/ADDING_A_BIONZX_CAMERA.md` asks for exactly this and
`src/a6400/targets/catalog.py` declares `ilce_6100`, `ilce_6600` and `ilce_7m3` as stubs with
no claims. All three have a packaged Sony updater, so their kernel symbols, device-node table
and USB identity set can be sourced today.

## 0. What changes, in one paragraph

Three profiles stop being empty stubs. Each gains seven kernel symbol addresses from its own
decoded `vmlinux.bin`, a confirmed `CXD90045` identity from the package's own `config.yaml`,
the verified device-node table (which has **no** `/dev/usb/video` or `/dev/usb/audio` row on
any of the three), and the body's full stock USB id set from the same config. Nothing is copied
from the a6400: every value below was read out of that body's own package, and the records
show which package.

## 1. Inputs (each hash is the file that was read)

| body | package version | `config.yaml` model | `vmlinux.bin` SHA-256 | `devno.ko` SHA-256 |
| --- | --- | --- | --- | --- |
| `ILCE-6100A` | 1.01 | `0x81030018` | `51c1289c9cd698aa…` | `74096566ca4132ef…` |
| `ILCE-6600` | 1.10 | `0x81030014` | `0df851b67f6302ec…` | `d8115717d7596760…` |
| `ILCE-7M3` | 4.04 | `0x71030014` | `175df4fc47ddf51c…` | `65933cda6844661d…` |

Sizes: the two ILCE-6xxx `devno.ko` are 4,308 bytes, the a7 III's is 3,988; both `vmlinux.bin`
of the 8.2.7.6 generation are 4,117,760 bytes.

Build identity, from the banner inside each `vmlinux.bin`:

| body | gcc build tag | build machine | build date |
| --- | --- | --- | --- |
| `ILCE-6100A` | Sony CE Linux 8.2.7.6 | `jp10239@dic-build-scm-u20-009` | 2026-05-02 |
| `ILCE-6600` | Sony CE Linux 8.2.6.0 | `jp10239@dic-build-scm-344` | 2020-07-15 |
| `ILCE-7M3` | Sony CE Linux 8.2.7.6 | `jp10239@dic-build-scm-u20-009` | 2026-05-02 |

All three carry the vermagic `3.0.27_nl-rt106+ SMP preempt mod_unload ARMv7`, the same as the
a6400 and ZV-E10 chains.

## 2. Kernel symbols resolved offline

Decoded from each body's own `vmlinux.bin` with the existing
`tools/research/decode_kernel_kallsyms.py`; the tables are 24,514 symbols for the two 8.2.7.6
bodies and 24,421 for the a6600.

| symbol | `ILCE-6100A` | `ILCE-6600` | `ILCE-7M3` |
| --- | --- | --- | --- |
| `usb_gadgetcore_ioctl` | `0x602BC864` | `0x602B8844` | `0x602BC864` |
| `usb_gadgetcore_register_driver` | `0x602BC630` | `0x602B8610` | `0x602BC630` |
| `usb_gadgetcore_unregister_driver` | `0x602BC584` | `0x602B8560` | `0x602BC584` |
| `usb_gcw_start` | `0x602C1818` | `0x602BD7F8` | `0x602C1818` |
| `usb_gcw_stop` | `0x602C1854` | `0x602BD834` | `0x602C1854` |
| `setup_req` | `0x602BD4C4` | `0x602B94A4` | `0x602BD4C4` |
| `make_config_desc` | `0x602BFC74` | `0x602BBC54` | `0x602BFC74` |

**The ILCE-6100A and ILCE-7M3 values are identical on all seven symbols, and those are exactly
the seven the a6400 profile already carries.** This is the finding worth pausing on, because it
looks like the mistake the guide warns about.

It is not the same image. The `vmlinux.bin` hashes differ
(`51c1289c…` vs `175df4fc…` vs the a6400's `12eeec82…`), the builds are three years apart
(2026-05-02, 2026-05-02, 2019-05-27), and the full tables disagree in 9,124 of 24,421 common
names between the a6400 and the a6600. What is equal is a *region*: the USB gadget core. When
Sony rebuilt the kernel for a new body, that subsystem was compiled to the same placement. So
the equality is a measurement, not a copy, and the honest statement is narrow: **on these three
bodies the USB gadget-core entry points sit at the same addresses, while the surrounding kernel
differs.**

The a6600's seven values are also identical to the a6400's, even though its banner differs
(`8.2.6.0`, 2020-07-15) and its symbol table differs from the a6400's in 9,124 addresses. The
same region-equality explanation covers it; it is not evidence that the two images are the same.

## 3. The device-node table has no UVC row on any of the three

`devno.ko` carries a `udif_devnodes` object that `src/a6400/execution/zve10_uvc_enablement.py`
already parses. Run on the three bodies:

| body | table entries | `/dev/usb/*` nodes | `usb/video` | `usb/audio` |
| --- | --- | --- | --- | --- |
| `ILCE-6100A` | 88 | 17 | absent | absent |
| `ILCE-6600` | 88 | 17 | absent | absent |
| `ILCE-7M3` | 76 | 17 | absent | absent |
| `ZV-E10` (reference) | 90 | 19 | **present 248:33** | **present 248:32** |

The 17 shared nodes are `adb`, `buspwr`, `buspwric`, `cur`, `kikilog`, `massstorage`, `portmon`,
`sen`, `sicd_core`, `sicd_data`, `sicd_event`, `std`, `swic`, `ter`, `usb_extcmd`,
`usbg_bspwr`, `vspe`. `usb/massstorage` is `248:0` on all three.

**Why this matters for an open boundary.** E0321 recorded "kernel-side UVC support unknown" for
bodies without the module package. For these three the question is not unknown: the kernel-side
node table does not publish a video or audio node, so a UVC function could not appear at a
`/dev/usb/video` path even if a module were loaded. The module package (E0479) and the node
table are two independent halves of the same answer, and both say no on these bodies.

## 4. USB identity sets, from the package's own config

`config.yaml` in each package lists the stock descriptor pairs. The vendor id is `0x54C`
throughout; the pairs differ per body, so the set is body evidence:

| body | stock pairs | count |
| --- | --- | --- |
| `ILCE-6400` | `0448 047D 0BFE 0BFF 0CA7 0CA8` | 6 |
| `ILCE-6600` | the a6400's six plus `0D0D 0D0E 0D11 0D12` | 10 |
| `ILCE-6100A` | the a6600's ten plus `0F0A 0F0B` | 12 |
| `ILCE-7M3` | `0448 047D 07C7 07C8 0BEE 0BEF 0BFE 0BFF 0C01 0C02` | 10 |

The a6400's set is a strict subset of the a6600's, which is a strict subset of the a6100A's.
The a7 III diverges instead of extending: it shares `0448`, `047D`, `0BFE`, `0BFF` with the
others and carries four of its own (`07C7`, `07C8`, `0BEE`, `0BEF`).

`0x0CA8` appears in the a6400 set and is the mass-storage identity the project already records
as stock. It is also in the a6600 and a6100A sets, and **absent from the a7 III's**, which is
worth knowing before assuming one mass-storage id across the family.

The updater-mode pair `0x54C:0x3E2` is identical in all three packages. That is the identity
the updater presents, not the camera's operating identity, and it is not a profile claim.

## 5. Confidence and limitations

- **Measured:** every address, hash, table entry and pid set above, from the files named in
  table 1. Nothing here was inferred from a model name.
- **Not claimed:** that a resolved symbol is callable or that a module would load. A kallsyms
  entry is presence evidence, as the profile boundaries already state.
- **Not claimed:** any UIPC queue id for these three. Offline firmware does not carry the
  per-boot queue handles the a6400 profile records from a live `/proc/osal/uipc` read. They
  stay unknown rather than guessed.
- **Not claimed:** `soc_verified` beyond what the package proves. `crypterName: CXD90045` is
  the updater's own statement that the payload is for that SoC family; it is stronger than a
  model name and weaker than reading `/proc/cpuinfo` on the body.
- **Not claimed:** the two identical-address groups mean the bodies share an execution target.
  They have different device tables, different command tables (E0477: 285, 286 and 322) and
  different USB id sets, so a target still needs its own profile.
- **Version risk:** the a7 III package is `4.04`, the newest of the three. A camera in the field
  may run an older build whose USB region sits elsewhere; the addresses are exact for the
  packaged build named in table 1.

## 6. Dependent implementation

`src/a6400/targets/catalog.py`: `ILCE_6100`, `ILCE_6600` and `ILCE_7M3` become populated
profiles with `sources` naming this record and the paths it cites. `uipc_queues` stays empty.
`boundaries` states the three things this record does not establish. The registry keeps the
same five targets, so nothing that selects by `target_id` changes.

## 7. Reproduce

```bash
# symbols, per body (writes the decoded table and prints the match count)
python3 -I tools/research/decode_kernel_kallsyms.py \
    --input <unpacked>/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin

# device-node table
python3 -I tools/research/uvc_module_imports.py --devno <unpacked>/.../nflasha7_unpacked/kmod/devno.ko

# everything at once, including the cross-body comparison
python3 -I tools/research/cross_model_report.py data/a6400/work/unpacked data/a6400/work/unpacked_platform
```

## 8. Next experiment

The a6400 profile records `live_build_version` 8.2.6.0 against a packaged 8.2.5.7, and notes
that the two bases differ. The same question now applies to these three: each package names one
build, and a body in the field may run another. A single read-only `/proc/kallsyms` capture from
one of them would say whether the USB-region equality survives a build change, which is the
cheapest test of the explanation in section 2.
