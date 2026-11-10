# E0278 — F9-0: the liveview/PTP start path and the USB gadget framework

Date: 2026-11-09. Offline only.

## `actionSicdStart`

`InfraRemoteUsb::actionSicdStart` (0xae78): reads the USB speed/type field (`[this+0x2c]`, values
`101`/`200`), calls **`PTP_init`** (libptp, `0xb9a6`) with a GOT-selected context, then waits via
the resource callback. `PTP_init` in `libptp` initialises the ptpm mailbox/semaphore/worker
threads (`ptpm_ini_mbx`, `ptpm_ini_sem`, `ptpm_thread_start`); it does **not** itself touch the UDC.

## USB gadget framework (`libInfraUsbCmn.so`)

- Strings: `gadgetcore`, `usb_gadget`, `pullup`.
- Symbols: `CUsbGadget::createGadget` (0x88b8), `CUsbGadget::deleteGadget` (0x893c),
  `CUsbGadgetStill::on_create` (0xe874) / `on_delete` (0xe924), plus `CUsbGadgetAdb`/`Sen`.
- `createGadget`/`on_create` register a gadget with the gadgetcore (function pointers/UDC
  operations); this is the layer that can cause the USB disconnect/re-enumeration when the
  PTP/stillimage function is created or deleted.

## Interpretation

The liveview/PTP start does not reset the UDC in `libptp`; the reset/re-enumeration is most
likely in the **USB gadget framework** when the app creates/registers the stillimage/PTP gadget
(`CUsbGadgetStill::on_create` / `CUsbGadget::createGadget`) at SICD/liveview start. The shim
hooks only `make_config_desc`; a gadget create/delete path that rebuilds the function outside
that hook could re-enumerate the device without the composite descriptors (or without the PTP
child), which matches the Windows "device disconnected" observation.

## Next

- Disassemble `CUsbGadgetStill::on_create` (0xe874) and the gadget register/UDC calls to identify
  the exact disconnect trigger and whether `make_config_desc` is invoked on that path.
- Determine hook coverage: intercept the app's gadget create/delete, or re-apply the composite
  descriptors after the app's re-enumeration.
