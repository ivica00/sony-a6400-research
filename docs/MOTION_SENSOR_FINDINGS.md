# Motion sensor investigation — 2026-11-06

Read-only investigation; no sensor commands, application calls, memory patches,
SD writes or observers installed.

## Concrete evidence

The connected camera reports loaded `accel` (9024 bytes), `mag` and `compass`
modules. Receipt: `artifacts/hardware/motion-sensor-readonly-survey.json`.
The Linux input inventory was empty; `/sys/bus/iio/devices` does not exist.
Absence of an IIO interface does not establish absence of a sensor.

Original extracted `nflasha15_unpacked/kmod/accel.ko` contains functions
`accel_init_mma8452q`, `accel_res_mma8452q`, `accel_sus_mma8452q`,
`acc_api_cb` and `psm_acc_async_thread`. This identifies a concrete MMA8452Q
driver implementation, but not a verified chip identity read or active sample rate.
NXP describes MMA8452Q as a three-axis, 12-bit accelerometer with 1.56–800 Hz
output rates: https://www.nxp.com/products/MMA8452Q . This is a chip capability,
not a demonstrated camera logging rate.

Original firmware string survey found `MPR_CMD_GSENSOR_GET_VALUE`,
`PARAMID_GYRO_ANGLE`, `api_get_gyro_act_sens_rsrc`, an X/Y/Z gyro diagnostic,
`Gyro Data >> (yaw:%d, pit:%d, roll:%d)` and `gyro_sync_id`.
Some `av-cam.bin` gyro messages explicitly concern the lens.
Shared firmware support and diagnostic names do not prove a body gyro exists
or that a particular stream is populated on this model.

Survey artifacts: `artifacts/analysis/motion-sensor-string-survey.json` and
`artifacts/analysis/motion-sensor-symbol-survey.json` (file offsets and ELF values).

Disassembly of `dataflowInfraFramework.so` establishes that GyroDataTiming
get/set methods merely copy eight bytes at object+0x24; GyroInfo get/set methods
copy a single byte at +0x2c. These methods are metadata accessors, not established
raw XYZ sample readers.

## Next boundary

Trace the original accel module callback/UIPC protocol and its raw sample buffer;
verify model-specific initialization, units, freshness, and timestamps before
attempting a logger. Separate logging frequency from actual sensor updates.
Then trace the gyro diagnostic producers to distinguish body, lens and unused
shared code. No working sample logger or gyro hardware identification is claimed.

An accelerometer can support gravity-based tilt under suitable motion conditions,
but faster sampling alone cannot distinguish gravity from linear acceleration or
recover rotation about gravity. It can assist image-based stabilization, but does
not replace a three-axis gyro for general rotational video stabilization.
Reference: https://www.analog.com/en/resources/app-notes/an-1057.html .

## USB debugger follow-up: live reads succeeded

The original `/usr/kmod/accel.ko` was downloaded through the normal USB debugger.
Its entire text, relocation, data and rodata sections match the extracted driver.
Whole files differ, so whole-file equality is NOT claimed. The camera copy of
`osal_uipc.ko` has text differences; its original `__k_4u_snd_sync_direct` and
`osal_snd_sync_direct` function bodies match the extracted versions exactly.
Copies and section comparison are under `artifacts/hardware/` as
`accel-camera-original.ko`, `osal_uipc-camera-original.ko`, and
`accel-original-driver-comparison.json`. Disassembly is retained under
`artifacts/analysis/accel-driver-disassembly.txt` and `accel-full-text.txt`.

The driver registers queues 0x00a30281 and 0x00a30282 with `acc_api_cb`.
Its operation 4 reads WHO_AM_I register 0x0d and compares against 0x2a.
Operation 5 reads six bytes starting at register 1 through the original I2C
message path, decodes signed 12-bit XYZ, applies the driver's axis matrix and
copies a 16-byte result to the supplied userspace pointer. Valid byte is +0,
signed XYZ are +8/+10/+12; the other bytes are uninitialized kernel padding,
NOT additional sensor channels or timestamps. The first raw receipt preserves
these bytes for audit; the final helper prints only meaningful fields.

`tools/native_camera/native_accel_read.c` is a bounded, standalone native client.
It connects to `/dev/uipc` using ioctl 0x80000010 and maps the original 1 MiB
pool without writing pool contents itself. Direct ioctl 0x80000006 carries
the queue and a pointer to a message with 16-byte outer header and 20-byte
callback payload. The initial attempt omitted connect/mmap and correctly failed
with EINVAL; this is retained in `accel-read-first.json`.

The connected helper successfully ran eight reads, followed by a revised helper
that checked identity and ran 128 immediate reads. Identity matched 0x2a;
all 128 reads had ioctl=0, errno=0, callback status=0, valid=1 and reached END.
Observed values were X=-5, Y=13, Z=-1008..-1007 in original driver units.
Call durations were 506..1039 microseconds, median 522.5, total 74594.
Only two distinct XYZ triples and one adjacent transition occurred.
**This establishes fast access to live values, not a 1.9 kHz sensor update rate.**
Actual output data rate, units/range configuration, video synchronization and
freshness indication remain unverified. No motion challenge was performed.

Final binary SHA256:
`6a3bc67cfacd6e54d270dae62b3344eff8a157c6c10277cdf7bcfcdaeecbcf34`.
Receipts: `artifacts/hardware/accel-read-connected.json`,
`accel-read-series.json`, `accel-read-series.log`, and
`artifacts/analysis/accel-read-series-summary.json`.
The helper was uploaded/readback-verified to `/tmp_bt/native_accel_read`,
executed and terminated; its final log remains there. No observer is armed.
No sensor init/config/start/stop commands, camera application calls, RAM patches,
SD writes or startup changes were sent. Original driver recovery paths remain
original firmware behavior, not a bypass introduced by the helper.

Next: determine configured output data rate and sample freshness using the
original protocol, then perform a timestamped motion challenge. The read path
is now proven; a long SD logger and a body gyro are still unproven.

## Gyroscope follow-up: current firmware path is disabled

The retained extracted `av-cam.bin` is NOT the current camera image. Its function
addresses and data must not be used as current sensor bindings. Initial physical
RAM comparisons rejected those old function/string bytes; the old global read
in `gyro-state-read-attempt.json` is therefore uninterpretable as sensor state.
No writes or calls used those rejected addresses.

The actual `/system/av-cam.bin` was downloaded completely through the normal USB
debugger to `artifacts/hardware/av-cam-camera-original.bin`: 16803048 bytes,
SHA256 `dd8f8d0cc74ad4b70100e5728cf8b159b5155e7fb50eaf1147b99c9054740209`.
The ORIL entry header establishes base 0x635c6000. Original Thumb PIC references
were resolved through literal-load plus PC-add instructions, not guessed from
string presence. `tools.research.gyro_firmware_xrefs` reproduces the bounded
static search. Its report is `gyro-current-firmware-xrefs.json`.

Current original functions:

- 0x63a70574: `api_get_acc_act_sens_rsrc` diagnostic-associated getter.
- 0x63a70674: `api_get_gyro_act_sens_rsrc` diagnostic-associated getter.
- Both decode bytes +0x91..+0x96 of shared state at 0x643bc30c; the accelerator
  masks low four bits, whereas the gyro getter does not. Different signed-byte
  3x3 axis matrices are at +0xb4 and +0xbd. The buffer is shared/multiplexed;
  it must not be interpreted as simultaneous independent accel and gyro streams.
- 0x63a70734 returns state byte +0xc6. The initializer at 0x63a70744 and lifecycle
  routine at 0x63a7013c branch around bus allocation/handler registration when
  that byte is zero. Backup descriptor 0x64579660 binds it to unit 0x0197006a.

`python -m tools.research.capture_gyro_state` verifies live initialization,
getter/guard code and backup descriptor bytes against the downloaded current
image before reading the associated ordinary RAM through `/dev/mem`.
Three non-atomic states, 200 ms apart, consistently have enable guard=0,
five bus resource IDs=-1, zero raw buffer and zero accel/gyro matrices.
Receipt: `artifacts/hardware/gyro-verified-state-survey.json`.
Summary: `artifacts/analysis/gyro-current-guard-summary.json`.
These establish that THIS ACTSENS path is disabled in the observed USB state.
They do not establish that all possible gyro paths are disabled or that the
body physically lacks a gyro. No enabling, probing arbitrary I2C addresses,
sensor writes or camera application calls were attempted.

Additional `Gyro Data >>` / `gyro_sync_id` references resolve to FC algorithm
consumers (current code around 0x63b16798 and 0x63b207ec), but their producer,
hardware origin and active status remain unproved. Explicit `LC->LENS` gyro
strings remain a separate lens path. Do not label all gyro strings body IMU data.

An additional libObj static trace identifies the `PARAMID_GYRO_ANGLE` renderer
consumer requesting parameter 0x1069 and processing one signed angle, not an
XYZ angular-rate stream. Its upstream producer and purpose are not established;
the provisional `gyro-level-*` artifact filenames are not proof of a level-gauge
connection. Those libObj windows have not been checked against current live code.

Outcome: live accelerometer reading is proven; no usable body gyro stream has
been found. Next useful work is to identify the FC gyro producer and compare
model configuration/hardware evidence, rather than force-enable this zeroed path.
No observer/hook was armed, no SD writes or boot changes occurred.

## Digital level: original accelerometer path identified and live buffer read

The digital level has a separate, explicit path from the earlier renderer
`GYRO_ANGLE`/MultiView angle consumer. The relevant UI names are
`PAS_WaterLeveling` and `InputService::startDigitalLevelNotify()`.
The latter current original function at libObj ELF VA 0x3cf428 sends opcode 3 to service
queue 0x012f0335; opcode 4 in the paired method stops notifications.
The older extracted function is at 0x3cf4a0; checking that stale address against
the camera failed and was rejected. The current symbol was resolved from the
camera's own ELF dynamic symbols. Its current file bytes match live process code.
The current disassembly independently confirms opcode3 and queue0x012f0335;
byte equality with the older extracted function body is NOT claimed:
`artifacts/hardware/digital-level-inputservice-code.json`.
No start/stop method was called during this investigation.

The queue is handled by `/usr/lib/libdig_level.so`, which is loaded in PID149.
The camera copy was preserved as `artifacts/hardware/libdig_level-camera-original.so`,
26688 bytes, SHA256
`799d58d4317d59233899646c199188234162107845c3b5634db2947b51d78e8a`.
Its full text, rodata, data and relocation sections match the extracted original
(whole-file equality is not claimed). Receipt:
`artifacts/hardware/digital-level-original-comparison.json`.

Original chain, in libdig_level ELF virtual addresses:

- Main loop 0x3b08 calls 0x1f50 at 0x3d74.
- 0x1f50 constructs operation 5 and calls 0x1eb8, which sends the original
  20-byte request to queue 0x00a30281. This is the SAME original MMA8452Q
  accelerometer operation independently exercised by `native_accel_read.c`.
- The valid 16-byte samples have signed XYZ at +8/+10/+12. The loop copies them
  into a ring at member+0x90, with count/index at +0x8d/+0x8e.
- At 0x3e5c..0x3eec the original loop sums/averages those XYZ components.
  Subsequent original code uses calibrated axis data and `atan2`, `sqrt`, and
  trigonometric functions to obtain inclination. For example, 0x3fd4 calls
  atan2 on acceleration components; 0x3fd8..0x400e computes another inclination
  with a square-root denominator. It is not integrating an XYZ angular-rate stream.
- The notification path includes `psm_dig_level_req_notify_angle` and
  `psm_dig_level_angle_notification`, matching the digital-level service.

PLT names in `artifacts/analysis/digital-level-plt.json` were resolved from
actual ARM PLT instructions and exact relocation slots, not a guessed fixed
entry stride (this library has interworking stubs). Full original disassembly
is `artifacts/analysis/libdig-level-disassembly.txt`.

Current process map establishes load base 0x0bd71000. Live code for the raw
wrapper, main-loop acquisition/averaging/math and notification scopes matches
the original camera library. The member object was derived from the initializer's
literal/PC-add at 0x4d14/0x4d20: ELF VA 0xe2f0, runtime 0x0bd7f2f0.
At capture it reports mode2, sample count4/index2, ring0x00206730, error0.
`artifacts/hardware/digital-level-live-code-state.json` preserves this evidence.

Three additional bounded reads, 200ms apart, found valid=1 in all four ring
entries, with XYZ around [-3,12..13,-1008..-1007], changing between reads.
Receipt: `artifacts/hardware/digital-level-live-sample-ring.json`.
These reads are non-atomic and are not a measured sensor output rate or a
controlled-motion experiment. No firmware function was called, no configuration
was changed, and no physical UI rendering observation was claimed.

Conclusion: there is strong direct code and live-state evidence for the
digital level's accelerometer-based inclination path on this camera.
The existence/functioning of the level therefore does not establish a body gyro.
The other FC/lens gyro producers remain open research; usable body gyro data
has still not been demonstrated. No hook/observer is armed.

## FC gyro-labelled data: SMOD input connection

Continued current-image static tracing located writes to the fields consumed
near the `Gyro Data >>` diagnostic. The input-population routine at 0x63b27c80
copies input+0x98/+0x9c/+0xa0 to destination+0x92c/+0x930/+0x934.
Its nearby resolved diagnostic is explicitly
`sMod GMV    >> (x:%d, y:%d, a:%d)` (PIC add at 0x63b27d5a).
The previously identified FC consumer at 0x63b16798 passes its +0x930/+0x934
pair to 0x63b1b98c and later prints the converted pair in the yaw/pitch positions
of `Gyro Data >> (yaw:%d, pit:%d, roll:%d)`.

This is evidence connecting the gyro-labelled pair to SMOD global image-motion
fields, rather than evidence of a physical gyro read. It remains a static
dataflow connection between the corresponding FC structure fields, not a live
execution trace proving object identity across calls. The origin of the third
roll diagnostic is still open; do not generalize this finding to every firmware
field named gyro. The candidate producer's direct caller is 0x63dc1e62.

Actual code bytes in all three relevant current-image windows were checked
read-only against physical camera RAM:
`artifacts/hardware/fc-gyro-smod-source-verification.json`.
Original static evidence is retained as
`artifacts/analysis/fc-gyro-field-writers.json` and
`artifacts/analysis/fc-gyro-input-population.txt`.
No camera function, sensor command, memory patch, SD write or hook was used.

## Possible accelerometer-assisted stabilization

MMA8452Q may supply a slow gravity/horizon reference when translational
acceleration is small. A candidate post-processing experiment could use it for
gentle horizon correction or combine it with video-derived motion estimates.
This is a proposed use, not demonstrated stabilization or a finished mod.
Dynamic acceleration corrupts gravity-based tilt; increasing sample rate does
not resolve that ambiguity or make rotation about gravity observable. A raw
accelerometer-to-gyro unit conversion cannot recover the missing motion.
Timing, calibrated units, actual output rate, video synchronization, and the
camera/optical-axis alignment remain prerequisites for an evaluated prototype.
Primary reference: https://www.analog.com/en/resources/app-notes/an-1057.html .
