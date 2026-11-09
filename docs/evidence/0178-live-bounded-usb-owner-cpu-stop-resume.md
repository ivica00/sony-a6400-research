# E0178 — Fizički ograničeno zaustavljanje i nastavak CPU dretava USB vlasnika

Datum: 2026-11-08. Kamera ostaje u Mass Storage načinu. Debugger PID703 dostupan. Nema učitavanja zajedničkog modula, USB promjene, hooka, aplikacijskog poziva ili zapisa u memoriju Sonyjeve aplikacije. Novi payloadi i logovi samo su u `/tmp_bt`.

## Alat i izgradnja

`tools/native_camera/native_usb_freeze_probe.c` koristi postojeći `native_freeze.h`, ranije fizički provjeren na PID149, i postojeći Sony libc/startup toolchain. Reproducibilni builder je `tools/research/build_native_usb_freeze_probe.py`. Alat zahtijeva `--capture-once`; bez argumenta samo ispisuje preflight i vraća 2.

Konačni ELF: `artifacts/native/uvc-ptp-freeze-e0178-fixed/native_usb_freeze_probe.elf`, **6796 bajtova**, SHA-256 `04953d3bba73841700889e49125d50ce191aef8f3a59c791432bd216ae90368b`. Interpreter je `/lib/ld-linux.so.3`, jedina DT_NEEDED ovisnost libc.so.6; povezivanje koristi zadržanu Sony libc.

Alat enumerira i priključi sve PID149 dretve, ponovno provjeri skup, očita PTRACE_GETREGS unutar ukupnog 2000 ms ograničenja te odmah odvoji sve priključene dretve. Ispis pojedinačnih registara ide **nakon** nastavka svih dretava. Svaki očitani CPSR mora označavati user mode. To su spremljeni user registri, ne kernel stackovi.

Prvi fizički preflight nije pokrenuo freeze: vratio je 2, ali stdout nije bio ispražnjen prije custom startup SYS_exit, pa je host guard odbio nastavak. Taj pokušaj ostaje arhiviran u `artifacts/hardware/uvc-ptp-freeze-e0178`. Dodan je eksplicitni fflush i u preflight i error izlaz; nije ponovljen neuspjeli freeze jer freeze tada nije ni započeo.

## Fizički rezultat

Konačni ELF prenesen je na zaseban timestamp put u `/tmp_bt` uz byte-equal readback. Preflight je ispravno ispisao `freeze=0`, nakon čega je izvršen jedan capture ciklus:

```
FREEZE threads=175 attached=175 resumed=175 result=0 elapsed_ms=1346
END result=0 captured=175 expected=175 saved_user_regs_only=1
```

Sačuvano je svih 175 register zapisa. Svi CPSR-i imaju user mode, a svih 175 PC-eva pripada izvršivim rasponima prethodno očitanih stvarnih maps. Nije korišten hostov rekonstruirani CPU okvir niti lažni thread ID.

Host run status=0, flags=0; puni log ima 11926 bajtova, SHA-256 `5462bb489e906a4daef584ec186b3ea244bc3e28e3918c4a62b3068e7a8e3011`, bez truncationa. Finalni `/proc/149/status` ima TracerPid=0. Debugger odgovara prije i nakon capturea.

Ponovljeni native owner inventory **nakon** freeze ciklusa potvrđuje isti skup OWNER/TASK zapisa kao prije: jedan gadgetcore vlasnik PID149/FD85, 175 dretava, errors=0. Time je fizički potvrđen povratak ovog CPU capture ciklusa, bez USB konfiguracijske promjene.

Artefakti: `artifacts/hardware/uvc-ptp-freeze-e0178-fixed/{manifest.json,freeze.log,status-before.txt,status-after.txt,debugger-before.txt,debugger-after.txt,owners-after-freeze.log,post-freeze-manifest.json,register-map-analysis.json}`. Build manifest uključuje hash izvora, native_freeze.h, startup-a, Sony libc i ELF-a.

## Precizan opseg dokaza

Potvrđeno je da se opaženi proces koji drži gadgetcore može u ovom stanju kratko potpuno zaustaviti i nastaviti uz potpune receipts. Nije potvrđeno da ta činjenica sama iscrpljuje već započete kernel ioctl pozive: spremljeni user PC nije dokaz potpunog kernel stacka. Kernel worker, IRQ, DMA i EP0/gadget callbackovi nisu zaustavljeni ovim postupkom.

Zato E0178 ne proglašava samu zamjenu fops pokazivača sigurnom i ne daje potvrdu za aktivaciju PTP/UVC-a. Potreban je poseban ugovor za postavljanje omotača i završetak kernel callbackova. Kamera ostaje u Mass Storageu, nema aktivnog observer/hooka ili ptrace priključka. Zajednički modul E0164 i dalje nije učitan; test PC Remote + UVC/PTP još nije spreman.
