# E0182 — Zadržavanje native rezervacije kroz cijelu sesiju

Datum: 2026-11-08. Nastavak korisnikovih izmjena E0181. Ovaj korak nema pristupa ili zapisa na kameru; kandidat nije prenesen ni učitan.

## Pregled E0181

Zadržana je integracija mode gate-a i native ioctl omotača koju je korisnik dodao u E0181. Njegov fizički init/exit test i receipts ostaju neizmijenjeni. Uočen je dodatni problem životnog vijeka: shared_ioctl i shared_release oslobađali su native guard nakon svakog poziva, uključujući povratak iz uspješnog pokretanja sesije ili neuspjelog čišćenja.

U budućem stvarno objavljenom native wrapperu to bi dopustilo izvornoj naredbi e203/e204 da ponovno uđe između MOD ioctl-a dok su zajednički deskriptori još aktivni ili zadržani. Dosadašnji per-call testovi nisu provjeravali taj interval. Ovo nije opažena fizička utrka: wrapper još nije postavljen na kernel slot.

## Dopuna implementacije

`tools/native_camera/uvc_ptp_module_shim.c` sada razlikuje dvije svrhe:

- `control_gate` serijalizira pojedinačne MOD ioctl/release ulaze;
- `native_reserved` prati rezervaciju native_guard-a kroz cijelo trajanje sesije.

Prvi MOD ulaz preuzme native rezervaciju ako nema izvornog poziva. Sljedeći MOD ulazi mogu je ponovno koristiti pod lokalnom zaštitom, pa je STOP moguć i dok native guard ostaje HELD. Izvorni ulazi kroz wrapper odbijaju se između poziva dok je sesija ACTIVE ili HELD.

Rezervacija se oslobađa tek kada session_releasable vrati true, nema self-pina i backend više nema gc vlasništvo. Nepotpuno čišćenje ili pogreška guard release-a zadržava rezervaciju. Stvarni kod greške više se ne zamjenjuje generičkim busy rezultatom. Izgubljena/neusklađena rezervacija odbija daljnje MOD operacije prije hardware/callback poziva.

Registracijski hookovi dodatno zahtijevaju aktivan MOD control ulaz i vlastitu native rezervaciju.

## Aktivacija zahtijeva stvarno povezan ulaz

Prije INIT naredbe 0x4038e000 provjerava se da native fops slot 0x604e5098 doista pokazuje na `a6400_uvc_native_gadgetcore_ioctl`. Ako je još izvorni 0x602b8844 ili neki drugi cilj, INIT vraća -ENODEV (-19) **prije** izvornog core ioctl-a. Registracijski hook ponavlja provjeru.

To je nužan uvjet, ne postupak postavljanja ili dokaz quiescence-a. Ovaj kod ne zapisuje taj kernel slot. Ne tvrdi se da samo jednaki pointer rješava stare VFS ulaze, owner lifetime ili izravne kernel callbackove.

## Kandidat i provjere

Izgrađen je `artifacts/native/uvc-ptp-module-e0182/usbg_video_a6400_shared_candidate.ko`, **60708 bajtova**, SHA-256 **280af3755079e0c2fcddfa1b3e16c9a80dcb020076ea86b612989b4abe1e534d**. Zadržano je 49 uvoza i provjera normalnih/GPL export klasa; izvorni init/exit i tri dokumentirane promjene donorskih instrukcija ostaju provjereni.

Prošireni `tools/research/audit_uvc_ptp_module.py` sada ima **48 prolaznih provjera** (E0181: 33). Nove provjere pokrivaju:

- odbijanje INIT-a prije stvarne native rute i oslobađanje idle rezervacije nakon odbijanja;
- ACTIVE sesiju koja ostaje HELD između MOD ioctl-a;
- sljedeći status i STOP ulaz koji mogu ponovno koristiti vlastitu rezervaciju;
- odbijanje istovremenog MOD poziva i izvornog native ioctl-a;
- izgubljenu rezervaciju bez oslobađanja self-pina;
- HELD/cleanup pogreške koje ne otpuštaju native zaštitu;
- oslobađanje tek nakon eksplicitnog dovršenog-cleanup fixturea;
- propagaciju i zadržavanje guard release greške.

ACTIVE/HELD/IDLE su izričiti typed fixturei; izvorni core ioctl/release i native gadgetcore ioctl u ovom auditu su recorders. Kernel route slot u testu također je fixture, ne stvarni hook. Test uklanjanja faulta nije fizički oporavak. Izvršava se stvarni prevedeni MOD kod, ali ne originalni native hardware teardown.

Manifest: `artifacts/analysis/uvc-ptp-module-e0182/manifest.json`; zapis: `artifacts/uvc-ptp-module-e0182-audit.log`. Svih **605 projektnih testova** prolazi u **18,871 s** (`artifacts/uvc-ptp-module-e0182-project-tests.log`).

## Trenutačna granica

Kandidat nije fizički aktiviran, a korisnikov E0181 init/exit dokaz ne proglašava se dokazom ove nove sesijske putanje. Sigurno postavljanje native omotača, završetak EP0/gadget callbackova, zajednička enumeracija i povratak na izvorni PC Remote ostaju otvoreni. Senzorski UVC s istodobnim PTP kontrolama još nije potvrđen. Kameru ostaviti u Mass Storageu do pripreme tog testa.
