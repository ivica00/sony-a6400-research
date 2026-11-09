# E0180 — Ispravak reference modula i uspješan fizički init/exit

Datum: 2026-11-08. Kamera ostaje u Mass Storageu. Svi novi payload/log zapisi na kameri samo u `/tmp_bt`.

## Uklonjena nedostupna ovisnost

E0179 loader odbio je __symbol_get jer pripada GPL-only kernel export tablici, a donor modul nema GPL-kompatibilnu license oznaku. Oznaka licence donora **nije mijenjana** i nema izravnog poziva GPL-only funkcije preko hardkodirane adrese.

Novi `tools/native_camera/uvc_module_self_ref.{c,h}` implementira ciljani native module-get inline ugovor i koristi normalno izvezeni module_put za otpuštanje. File-operations owner i dalje je __this_module. Get se smije pozivati samo iz već module-owned file operacije, kada je modul LIVE.

Iz originalnog kernel koda provjereni su thread_info preempt counter+4 i CPU+0x14 te module refptr+0x138. Get privremeno onemogući preemption kroz native count ugovor, provjeri LIVE, broj CPU-a, pointer i overflow, poveća lokalni per-CPU increment count, obnovi preempt count i po potrebi zove normalno izvezeni preempt_schedule. Tri native instruction guards vezuju layout na ciljnu verziju. To nije generički Linux struct module layout.

Ovaj MOD kod **ne poziva** __symbol_get. Uvozi module_put, preempt_schedule, __per_cpu_offset i nr_cpu_ids; svi su u normalnoj tablici izvoza. Legacy anchor/self-export uklonjen je iz shim-a. Cleanup i dalje zadržava referencu dok sesija nije potpuno očišćena.

## Izvršna provjera reference

`tools/research/build_uvc_module_self_ref.py` prevodi helper i izvršava ga zajedno sa **stvarnim originalnim module_put tijelom**, uz eksplicitne module/thread_info/per-CPU fixture podatke. **17 provjera prolazi**: CPU0/1, otpuštanje na drugom CPU-u, LIVE/COMING/GOING, null storage, overflow, očuvanje nested preemption counta i reschedule redoslijed. Scheduler je izričiti recorder, nije emulirano stvarno raspoređivanje.

Manifest: `artifacts/native/uvc-module-self-ref-e0180/manifest.json`. Fizički init/exit ispod ne aktivira sesiju, pa se sam self-get još ne tvrdi fizički izvršenim.

## Export provjera sada razlikuje klase

Novi `tools/research/kernel_export_contract.py` čita stvarne parove vrijednost/ime iz normalnog i GPL export raspona SHA-provjerenog originalnog kernela. Builder odbija GPL-only uvoze koji nisu dostupni stvarnoj license metapodatkovnoj oznaci. Podržava i DATA izvoze koje samo tekstualni kallsyms inventar nije sadržavao. Headers novih C dijelova također su uključeni u build hash manifest.

To zamjenjuje raniju nedovoljnu provjeru samo prisutnosti imena. Ispravljeni kandidat ima **49 uvoza**; nema __symbol_get/__symbol_put i nema GPL-only kernel uvoza.

## Kandidat i provjere

`artifacts/native/uvc-ptp-module-e0180/usbg_video_a6400_shared_candidate.ko`:

- **58728 bajtova**;
- SHA-256 **adba4ea1e435c018de1a4f41fa0c7010ee249621e9bc8332b3ebc99807ad3917**;
- točan native vermagic, izvorni init/exit očuvani;
- **30** module guard/strukturnih ARM provjera prolazi;
- **605** projektnih testova prolazi u **15,199 s**.

Native backend promjena E0179 ostaje obuhvaćena njegovih 155 provjera. Nisu izmišljeni novi projektni testovi koji bi samo preslikavali implementaciju.

## Uspješan fizički ciklus bez USB aktivacije

Kandidat je prenesen na timestamp put u `/tmp_bt` uz byte-equal readback. `insmod` vratio je 0. `/proc/modules` potvrdio je:

```
usbg_video 46090 0 - Live 0x5f57f000 (P)
```

Video node nije otvoren, nije izvršen activation ioctl, nije registrirana zajednička konfiguracija niti pokrenut feeder. Zatim je `rmmod usbg_video` vratio 0. Završni `/proc/modules` byte-equal je početnom: novi modul nije ostao učitan.

Debugger PID703 odgovara prije i nakon ciklusa. Finalni PID149 status: sleeping, TracerPid=0, Threads=175. Kamera ostaje u Mass Storageu. Fizički receipts i kernel log: `artifacts/hardware/uvc-ptp-module-lifecycle-e0180`.

## Što sada jest i nije spremno

Potvrđeno je stvarno učitavanje i uklanjanje ovog kernel kandidata. Time je zatvorena loader/import prepreka koja se nije mogla dokazati samim offline provjerama.

Zajednička enumeracija PC Remote + UVC/PTP još nije isprobana. Mode gate/izvorni ioctl omotač E0174/E0175 još nisu postavljeni na native ulaz, a aktivni native gadget/EP0 callback drain i povratak zajedničke sesije ostaju otvoreni. Build zato i dalje zadržava `physical_test_ready:false` za **aktivaciju zajedničkog načina**, unatoč zasebno uspješnom init/exit testu. Nema senzorskog UVC ili kontrole tijekom streama.
