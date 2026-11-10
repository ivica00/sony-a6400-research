# E0280 — F9-0: shim patch site is setup_req+0x128; gadget reset is setup_disconnect/usb_gcw_stop/start

Date: 2026-11-09. Offline + read-only MSC `/proc/kallsyms`.

## Symbol mapping (Camera `/proc/kallsyms`, MSC, read-only)

| Address | Symbol |
| --- | --- |
| `0x602b95cc` (shim BL patch) | `setup_req + 0x128` |
| `0x602bbc54` | `make_config_desc` |
| `0x602b9464` | `setup_disconnect` |
| `0x602bd834` | `usb_gcw_stop` |
| `0x602bd7f8` | `usb_gcw_start` |

## Interpretation

- The shim patches `setup_req+0x128` so the **configuration descriptor** request calls the module's
  hook instead of `make_config_desc`; the composite descriptors are therefore used when the host
  requests the configuration.
- The app's stillimage/PTP gadget create (`CUsbGadgetStill::on_create` → gadgetcore ioctl
  `0x403800e0`) goes through `usb_gcw_stop` / `usb_gcw_start` / `setup_disconnect` — the UDC
  restart that Windows reports as a disconnect/re-enumeration.
- On re-enumeration the config descriptor is still patched (composite), yet the host did not show
  the PTP child (E0277). So the failure is not the config-descriptor source; it is in the
  gadget/function registration or enumeration timing around the app's re-create (e.g., the
  stillimage function not bound/registered on the re-created gadget, or the host enumerating
  before the gadget is fully configured).

## Next

- Host capture of the transition (Windows PnP/USB events + SetupAPI) to see what device appears
  after the disconnect and which descriptor/child fails.
- Inspect the app's gadget re-create registration (which functions/interfaces are bound after
  `usb_gcw_start`) and whether the module can hook `usb_gcw_stop`/`usb_gcw_start` or re-apply
  function registration to restore the PTP child.
