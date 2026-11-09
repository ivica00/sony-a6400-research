# E0212 — OBS video open and enumeration control boundary

Date: 2026-11-09. User reports OBS was open during E0210 and has now closed it. No camera access or deployment in this step.

## Direct OBS evidence

Read-only inspection of the local OBS log `2026-11-09 10-30-08.txt` found device settings for ILCE-6400, exact `VID_054C&PID_0CAA&MI_01`, at 10:30:15.087 local Europe/Sarajevo time (09:30:15.087 UTC). Requested settings: MJPEG, 1280x720, 30 FPS. This is within the E0210 host monitoring window. It supports attempted opening/configuration of the new Sony UVC child, rather than a mere unrelated running OBS process.

OBS begins shutting down at 10:30:18.661. DirectShow ConnectPins reports aborted I/O `0x800703E3` at 10:30:20.208. Because this error follows shutdown, it must not be presented as proof that the camera caused it. The log does not prove a specific USB PROBE/COMMIT packet, successful stream start, frames, or that OBS caused the camera freeze. Exact camera hang site/time remains unknown; E0210's freeze must not be attributed exclusively to STOP.

Minimal relevant excerpt and source hash retained in `artifacts/analysis/uvc-obs-e0212/`; unrelated OBS sources are omitted. Official context: https://obsproject.com/kb/video-capture-sources describes DirectShow capture and device deactivation. OBS being open alone does not establish camera usage; the exact device-path entry is the session-specific evidence here.

## Source gap and change

The shared enumeration candidate suppressed reference video START/submission, but its bridge still forwarded CLASS/VENDOR callbacks to the reference video module. Thus START suppression was not complete exclusion of host video-control activity. No evidence yet establishes that the reference handler blocked.

New explicit `A6400_UVC_ENUMERATION_ONLY` build policy, enabled only for the shared enumeration candidate, returns NOT_HANDLED (2) for bridge CLASS/VENDOR callbacks before target dispatch. Existing original dispatcher tests (E0186) establish exhausted callbacks map to rejection; no physical EP0 STALL or Windows binding under this new policy is claimed. Full bridge builds without the policy retain their prior dispatch. This is a temporary enumeration-only boundary, not implementation of UVC streaming controls or a proven freeze fix.

New isolated builder flag and `probe_uvc_enumeration_controls.py` execute the compiled bridge with callback recorders. Twelve cases across both shadows and CLASS/VENDOR requests verify rejection, no callback dispatch, and byte-equal request preservation. These tests do not execute the reference video handler or hardware.

Offline module: 72512 bytes, SHA-256 `1bcb464842e8d478a8735be46161689f6d3e8c280c6b048bd94a2687f9e33b23`, `artifacts/native/uvc-ptp-module-e0212/usbg_video_a6400_shared_candidate.ko`. 118 module ARM checks pass, 55 imports verified; all 612 general tests pass in 18.997 seconds. No physical load/test occurred.

## Next boundary

Keep OBS closed for the next eventual baseline, but do not rely on application absence as firmware safety. A video client should be handled or rejected without freezing the camera. Configured-session teardown and recoverable stage observation remain open (E0211); this control rejection alone does not authorize calling another physical test ready. Sensor video and actual PTP camera-control transactions remain unproven.
