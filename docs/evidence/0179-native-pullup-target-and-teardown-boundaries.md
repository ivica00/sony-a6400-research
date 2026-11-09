# E0179 — Stvarni USB pullup put i pojačan backend

Datum: 2026-11-08. Kamera u Mass Storageu. Nastavak E0178.

## Razlika između softverskog i hardverskog stopa

Originalni `usb_gcw_stop` (0x602bd834) poziva change_gcw_state(1) i vraća 0. To nije samostalna hardverska potvrda. Backend već prije njega poziva gadget pullup(0); dodana je stroga provjera da stvarni gadget ops+0x14 pokazuje upravo na a6400 `dwc3_gadget_pullup` **0x602b1d3c**. Početne instrukcije te funkcije uključene su u native fingerprints.

`tools/native_camera/uvc_ptp_native_backend.c` provjerava taj cilj prije preuzimanja backend konteksta i ponovno pri svakom pullup pozivu. Nepoznat target ili null ops odbijaju se. Promjena cilja tijekom aktivne sesije zadržava sesiju i owned deskriptore prije bilo kojeg daljnjeg native poziva; povratak provjerenog cilja omogućuje dovršetak čišćenja. Ovi MOD guardovi testirani su, a ne pretpostavljeni iz naziva funkcije.

## Izvršenje izvornog pullup tijela

`tools/research/probe_uvc_ptp_pullup_teardown.py` izvršava originalne ARM instrukcije pullup i GCW state funkcija iz SHA-provjerenog kernela. **14 provjera prolazi**.

Za pullup(0) izvorni redoslijed je: provjera busy opaque stanja, stop_active_transfers, disable EP0 out/in, moguća disconnect obavijest, run_stop(0), povratak njegova rezultata. Potvrđeni su endpoint argumenti i prijenos -110 greške iz run_stop servisa. Hardware servisi, brave i notification izričite su zamjene.

Kad native busy bit ostaje postavljen, izvorni kod otključa DWC, omogući migraciju i dođe do reschedule prije nego zaustavi transfere. U tom ogranku nije opažen vlastiti brojač timeouta. Pozitivni nastavak u testu dobiva **eksplicitni vanjski completion fixture**, ne izmišljenu hardversku potvrdu.

Zato CPU freeze E0178 ne smije sam postati dokaz završenog USB callbacka niti se smije pretpostaviti da se cijeli teardown može izvršiti dok su korisnički izvršitelji zaustavljeni. Native pullup može ovisiti o dovršetku prethodnog zahtjeva.

Izvještaj: `artifacts/analysis/uvc-ptp-pullup-e0179/manifest.json`.

## Izgradnja i provjere

Izgrađen je kandidat `artifacts/native/uvc-ptp-module-e0179/usbg_video_a6400_shared_candidate.ko`, **58628 bajtova**, SHA-256 `145ce31279ba172d1328d7369c74eea671fb78ce878696e854ffaca9f3b660b5`.

- **155** native backend ARM provjera prolazi, uključujući osam novih provjera targeta/zadržavanja/oporavka.
- **29** strukturnih i prevedenih module guard provjera prolazi.
- **605** projektnih testova prolazi u 14,781 s. Prvi pokušaj imao je četiri PermissionError-a u privremenim mapama; zadržan je odvojeni `...project-tests-restricted.log`, a ponovljeni testovi s pristupom tim mapama prošli su bez promjene implementacije.

## Ograničeni fizički pokušaj učitavanja

Pregledani izvorni init put registrira char uređaj i inicijalizira njegove objekte; ne registrira UVC konfiguraciju. Pokušan je samo insmod bez otvaranja video nodea i bez activation ioctl-a. Loader je odbio modul: **Unknown symbol __symbol_get**. Init/exit ciklus nije prošao.

Manifest i puni kernel log su u `artifacts/hardware/uvc-ptp-module-lifecycle-e0179`. `.ko` je prenesen samo u `/tmp_bt` uz byte-equal readback. `/proc/modules` prije i poslije je byte-equal i novi modul nije ostao učitan. Debugger PID703 odgovara. Nema USB promjene ni freeze ciklusa u ovom pokušaju.

Utvrđeno je da je __symbol_get u stvarnoj **GPL-only** export tablici, iako mu ime i adresa postoje u kallsyms. Ranija provjera prisutnosti imena nije provjeravala klasu izvoza. Ne smije se proglašavati da svi postojeći simboli automatski znače loadability. Ispravak i uspješan fizički init/exit nastavljaju se u E0180.
