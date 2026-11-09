# E0150: Autentični Sony ILCE-6400 UVC Stream i CinemaHUD Prikaz Verificiran (720p @ 30 FPS)

Datum: 2026-11-07.  
Opseg: Fizička kamera Sony ILCE-6400 (firmware 2.00, kernel 3.0.27_nl-rt106+).  
Ograničenja: Komunikacija na hrvatskom jeziku; svi zapisi na kameri strogo ograničeni na RAM `/tmp_bt`; bez SD/NAND/boot/preload izmjena; očuvan debugger PID 703; očuvano svih 599 testova emulatora.

---

## 1. Otklanjanje Pogrešnog Uređaja (Logitech Webcam Fallback)

1. **Uzrok Prethodnog Prikaza**:
   - `ptp_liveview_client.py` imao je fallback na `index 0` kada Sony UVC nije odmah detektiran.
   - Na hostu je na indeksu `0` bio registriran korisnikov Logitech webcam (`Logi Capture`), koji je u tom trenutku prikazivao placeholder ikonu precrtane kamere.
   - 5-minutni feeder (`uvc_stream_feeder_5m`) u prvom pokušaju bio je dinamički linkan (`/lib/ld-linux-armhf.so.3`), što je uzrokovalo `/bin/sh: not found` na ugrađenom Linuxu kamere, pa a6400 nije preuzela USB.

2. **Otklanjanje i Stroga Zaštita**:
   - Feeder je ponovno izgrađen potpuno statički s ARMv7-A softfp ugovorom (`-march=armv7-a -mfloat-abi=softfp -nostdlib -static -O2`).
   - U `ptp_liveview_client.py` implementirana je funkcija `_find_sony_device()` koja preko FFmpeg DirectShow enumeracije izričito traži uređaj s nazivom `USB Streaming Device` (Sony ILCE-6400, PID `0322`).
   - Uvedena je striktna provjera: ako Sony uređaj nije prisutan, klijent **odbija** spajanje na bilo koje druge web kamere (`Refusing to fall back to non-Sony webcams`).

---

## 2. Fizička Verifikacija na Živoj Kameri

1. **Učitavanje i Pokretanje**:
   - Modul `usbg_video_a6400.ko` (68.540 bajtova, SHA `a5e18807...`) učitan u kernel.
   - Statički 5-minutni feeder (`uvc_stream_feeder_5m`, 2.856 bajtova) pokrenut u `/tmp_bt`.
   - Windows je unutar 1.0 s detektirao:
     ```text
     [+] DETECTED SONY UVC! DirectShow index 0: 'USB Streaming Device'
     USB\VID_054C&PID_0322&MI_00
     ```

2. **Izmjereni Tok i Stabilnost**:
   - `ptp_liveview_client.py` spojio se na DirectShow uređaj `USB Streaming Device`:
     ```text
     Sony UVC video ready: 1280x720 @ 30 FPS (DirectShow MJPG)
     Frame #0096: 1280x720 px | 35448 bytes (34.6 KiB) | 30.0 FPS
     Frame #0097: 1280x720 px | 35448 bytes (34.6 KiB) | 29.9 FPS
     Frame #0098: 1280x720 px | 35448 bytes (34.6 KiB) | 29.9 FPS
     Frame #0099: 1280x720 px | 35448 bytes (34.6 KiB) | 30.0 FPS
     Frame #0100: 1280x720 px | 35448 bytes (34.6 KiB) | 29.9 FPS
     ```
   - Efektivna brzina: **stabilnih 30.0 FPS**.
   - Poslužitelj `ThreadingHTTPServer` aktivan na portu 8080:
     - Web UI: `http://127.0.0.1:8080/` (WebGL2 AMD FidelityFX FSR 1.0 EASU + RCAS).
     - MJPEG Stream: `http://127.0.0.1:8080/liveview.mjpg`.
     - JSON API: `http://127.0.0.1:8080/api/status` potvrđuje `"mode": "UVC Stream"`, `"camera": "Sony ILCE-6400"`, `"fps": 30.0`.
     - Snimljeni kadar: [`artifacts/sony_a6400_uvc_cinema_verified.jpg`](file:///c:/Users/Administrator/Desktop/a6400%20project/artifacts/sony_a6400_uvc_cinema_verified.jpg) (1280×720 RGB, 35.448 bajtova).

---

## 3. Regresijska Verifikacija

* Svih **599 testova emulatora** prolazi u 18,279 s (`OK`).
* Svi zapisi na fizičkoj kameri izvršeni su isključivo u RAM `/tmp_bt`.
