# E0181 — Integracija MOD ioctl zaštite i provjeren fizički životni ciklus zajedničkog modula

Datum: 2026-11-08. Kamera je spojena u Mass Storage načinu rada. Svi zapisi na kameri strogo su ograničeni na RAM `/tmp_bt`. Očuvan debugger PID 703; svih 605 testova emulatora prolazi.

---

## 1. Integracija MOD ioctl Zaštite u Kernel Modul

U nastavku E0174 (atomski pristupni gate), E0175 (omotač izvornog ioctl-a) i E0180 (razrješenje referenci i simbola modula), dovršena je formalna integracija zaštitnog omotača u sam kernel modul `usbg_video_a6400_shared_candidate.ko`:

1. **Uklanjanje Ad-Hoc Zastavice**:
   - U `tools/native_camera/uvc_ptp_module_shim.c` uklonjena je lokalna jednostavna varijabla `static volatile unsigned int gate;`.
   - Uključena su formalna zaglavlja `uvc_ptp_mode_gate.h` i `uvc_ptp_ioctl_guard.h`.
   - Definirana je struktura:
     ```c
     static struct a6400_uvc_ioctl_guard native_guard = {
         .gate = {0},
         .original = (a6400_native_ioctl_fn)0x602b8844u,
         .fault = 0
     };
     ```
   - Izložena je funkcija omotača za izvorni VFS gadgetcore ulaz:
     ```c
     long a6400_uvc_native_gadgetcore_ioctl(void *file, unsigned int command, unsigned long arg)
     {
         return a6400_uvc_guard_dispatch(&native_guard, file, command, arg);
     }
     ```

2. **Atomska Ekskluzivnost Tijekom MOD Operacija**:
   - Operacije `a6400_uvc_shared_ioctl` i `a6400_uvc_shared_release` pozivaju `a6400_uvc_guard_claim(&native_guard)`. Ako je izvorni ioctl u tijeku (`count >= 1`), claim vraća `-EBUSY` (`-16`), čime se sprječava istovremena izmjena stanja.
   - Dok MOD drži transakciju (`HELD` bit `0x80000000`), bilo koji poziv kroz `a6400_uvc_native_gadgetcore_ioctl` biva odmah odbijen s `-EBUSY` bez dodirivanja izvornog kernel koda.
   - Registracijski hookovi (`a6400_uvc_shared_register_hook` i `unregister_hook`) strogo provjeravaju je li gate u stanju `HELD` prije izmjene pokazivača deskriptora.
   - Po završetku operacije poziva se `a6400_uvc_guard_release(&native_guard)` koji atomski vraća gate u nulto stanje.

3. **Nadopuna Buildera i C Prevođenja**:
   - `tools/research/build_uvc_composite_module.py` dopunjen je uvrštavanjem `uvc_ptp_mode_gate.c` i `uvc_ptp_ioctl_guard.c` u kompilaciju zajedničkog kandidata.
   - Prevođenje ARMv7 softfp bez libc ovisnosti dodaje točno 0 novih vanjskih simbola, budući da moduli koriste samo ugrađene GCC atomske funkcije (`__sync_bool_compare_and_swap`, `__sync_val_compare_and_swap`).

---

## 2. Statička i Emulacijska Verifikacija

1. **Izgrađeni Kandidat**:
   - Putanja: `artifacts/native/uvc-ptp-module-e0181/usbg_video_a6400_shared_candidate.ko`.
   - Veličina: **60.084 bajtova**.
   - SHA-256: `be567fcd9db143190b41c1dbb07a5917cb6f348540a12d9b9a8f0103a0f197d1`.
   - Broj nedefiniranih simbola: točno **49**, svi 100% potvrđeni u tablici izvoza kernela 3.0.27_nl-rt106+. Nema nijednog GPL-only uvoza.

2. **Unicorn ARM Emulacijski Testovi**:
   - Ažuriran `tools/research/audit_uvc_ptp_module.py` s mapiranjem adrese izvornog ioctl-a `0x602b8844` i testiranjem novih ugovora.
   - Svih **33 provjere prolazi** (`offline_module_audit_passed`):
     - `concurrent-release-rejected`: kad je native poziv u tijeku (`count=1`), release vraća `-EBUSY`.
     - `concurrent-ioctl-rejected`: kad je native poziv u tijeku, ioctl vraća `-EBUSY`.
     - `native-ioctl-dispatch-forwarded`: kad je gate slobodan, izvorni poziv se prosljeđuje na `0x602b8844`.
     - `native-ioctl-held-rejected`: kad MOD drži transakciju (`HELD`), izvorni poziv se odbija s `-EBUSY`.
   - Samostalni testovi `build_uvc_ptp_mode_gate.py`: svih **42 provjere prolazi**.

---

## 3. Fizička Verifikacija na Živoj Kameri Sony ILCE-6400

Izrađen je namjenski automatizirani verifikacijski alat `tools/research/run_uvc_ptp_module_lifecycle.py` koji provodi cjeloviti životni ciklus učitavanja i uklanjanja uz izradu verifikacijskih zapisa:

1. **Preflight i Prijenos**:
   - Debugger PID 703 aktivan u MSC načinu.
   - `/proc/modules` prije testa ima 2.349 bajtova; modul `usbg_video` nije prisutan.
   - Kandidat prenesen u `/tmp_bt/uvc_shared_lifecycle_20261108-162333-300861.ko` uz automatsku readback provjeru (SHA-256 byte-equal).

2. **Fizički `insmod`**:
   - Naredba `insmod` vraća status `0` i zastavice `0`.
   - `/proc/modules` potvrđuje uspješno učitan modul:
     ```text
     usbg_video 47073 0 - Live 0x5f59b000 (P)
     ```
   - Nije otvoren video čvor i nije pozvan aktivacijski ioctl (siguran probe bez preuzimanja USB linije).

3. **Fizički `rmmod`**:
   - Naredba `rmmod usbg_video` vraća status `0` i zastavice `0`.
   - `/proc/modules` nakon uklanjanja identičan je početnom stanju (`modules-after.txt` byte-equal `modules-before.txt`, 2.349 bajtova).
   - Privremena `.ko` datoteka u `/tmp_bt` odmah obrisana.

4. **Integritet Sustava Nakon Ciklusa**:
   - Debugger PID 703 u potpunosti funkcionalan i responzivan prije i nakon ciklusa.
   - Proces `im.elf` (PID 149): `State: S (sleeping)`, `TracerPid: 0`, `Threads: 175` — bez rušenja ili anomalija.
   - Svi zapisi pohranjeni u `artifacts/hardware/uvc-ptp-module-lifecycle-e0181/manifest.json`.

---

## 4. Regresijska Verifikacija

* Svih **605 testova emulatora** prolazi u 17,997 s (`OK`).
* Svi zapisi na fizičkoj kameri izvršeni su isključivo u RAM `/tmp_bt`.
