# E0279 — F9-0: the stillimage gadget is (re)created via a gadgetcore ioctl

Date: 2026-11-09. Offline only.

## `CUsbGadgetStill::on_create` (0xe874, libInfraUsbCmn)

- Builds a create-info struct on the stack from the service/gadget registration fields
  (speed/attributes at `[r6+8..13]`, zeros at `[r7+0x30/0x34]`).
- Loads the gadget-core fd from `[r5+0x8c]` and calls `ioctl(fd, cmd, &creinfo)`.
- The command literal at `0xe900` is `0x403800e0`; the call goes through the ioctl thunk at
  `0x7b20`. Return `<0` maps to error code 9, else 0.

## Interpretation

The app creates/registers the stillimage/PTP gadget with a **gadgetcore ioctl**, not by calling
the kernel `make_config_desc` directly. The ioctl is the likely UDC re-enumeration trigger that
Windows reports as "device disconnected" when liveview/SICD starts (E0277). The module shim hooks
only the kernel `make_config_desc` BL (`0x602b95cc`); if the gadgetcore ioctl path uses the
create-info descriptors (reference templates) instead of the patched function, the composite
descriptors are bypassed on the app's re-create.

## Next

- Decode the create-info struct fields and the gadgetcore ioctl handler (kernel `usb/gadgetcore`)
  to see which descriptor source the create path uses.
- Determine hook coverage: intercept the ioctl/create-info (or the gadgetcore handler) to re-apply
  the composite descriptors after the app's re-enumeration; alternatively confirm whether the
  patched `make_config_desc` is invoked on this path.
