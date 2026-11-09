# E0171 — Izvorno uklanjanje callbacka: čekanje, prekid i vlastiti poziv

Datum: 2026-11-08. Offline nastavak E0170. Nema pristupa fizičkoj kameri, učitavanja modula ni izmjene produkcijskog modula.

## Izvršeni izvorni ARM kod

`tools/research/probe_uvc_ptp_kernel_unregister.py` učitava izvorne allocatable ELF sekcije a6400 osal_uipc.ko (SHA-256 `3743275bc964a2804b80cde4f589f60876b795fbeeccd3cbf2c18a0da2dc8567`) i primjenjuje njegove ABS32/CALL relokacije. Nepoznate relokacije u tim sekcijama odbijaju se. Ne mijenja tijela funkcija niti izvodi module init.

Izvršeni su originalni unregister helper na .text+0x2f3c, wait helper na .text+0x27a0, wake helper na .text+0x28e0 te `free_cb` na .text+0x2b24. Konačni `free_fblock`, lock/unlock i wake_up_process izričite su servisne zamjene. `schedule` je granica zaustavljanja, ne simulirani raspoređivač.

Queue, callback, trenutni task/TID, callback TID, brojači i signal flags eksplicitni su fixture podaci. Guardovi ograničavaju izvršenje na navedena originalna tijela i zapise na fixture/izvorne writable sekcije.

## Različiti ugovori uklanjanja

| Slučaj | Izvorno ponašanje potvrđeno u pokusu |
|---|---|
| Callback nije aktivan, count=0 | Postavi retire bit, ne čeka, pozove originalni free_cb i obriše registrirani slot. |
| Aktivan callback druge dretve | Postavi retire bit, upiše waiter na stog, otpusti zaštite i dođe do schedule prije oslobađanja. Registrirani slot ostaje očuvan. |
| Aktivan callback iste dretve/TID-a | Wait helper vrati 0 bez čekanja. Unregister pozove free_cb i obriše slot iako fixture active count ostaje 1. |

Originalni free_cb smanjuje globalni brojač putem stvarnog LDREX/STREX slijeda i predaje callback u free_fblock. U pokusu je provjeren 3→2 za neaktivni i self slučaj. Konačno ponašanje allocator-a nije izvršeno; ne tvrdi se da je fizički nastao use-after-free. Ali uspješan return sam po sebi očito nije univerzalni dokaz da callback više ne radi.

## Dovršetak druge dretve

Nakon zaustavljanja na schedule pokus eksplicitno postavlja count=0 kao **vanjsku completion fixture promjenu**, ne kao dokaz izvršenja finish_callback. Na drugom stogu izvršava se originalni wake helper: on provjeri count, ukloni odgovarajući waiter, očisti njegov callback pointer i pozove wake_up_process za čekajući task.

Zatim se obnavlja spremljeni CPU kontekst točno nakon schedule. Originalni wait/unregister kod nastavi, vrati 0, pozove free_cb i obriše slot. Konačni free dolazi tek nakon izvornog wake puta. Stog i lokalni registri čekatelja nisu zamijenjeni hostovom aproksimacijom.

Wake helper s count=1 ne uklanja waiter i ne zove wake_up_process. To je zasebno provjereno.

## Prekinuto čekanje

Uz eksplicitni signal-pending fixture nakon schedule, wait helper sam uklanja svoj stogovni waiter, briše retire bit i vraća -1021 (0xfffffc03). Unregister ne oslobađa callback niti briše aktivni registrirani slot. Native globalni allocation counter ostaje 3. Pozivatelj mora sačuvati resurse i odraditi ugovor ponovnog pokušaja; ne smije taj povratak tretirati kao završeno čišćenje.

## Posljedica za mod

OSAL callback registracije ne smijemo smatrati završenima samo zato što je unregister vratio uspjeh iz vlastitog callback konteksta. Budući upravljački put treba završno uklanjanje i oslobađanje obaviti iz odvojenog konteksta, provjeriti aktivne pozive te zadržati resurse nakon prekinutog čekanja. Ovo je OSAL ugovor; ne zamjenjuje zasebnu provjeru gadgetcore/EP0 callbackova E0164 niti samo po sebi rješava usklađivanje svih USB promjena.

## Rezultati i daljnja granica

**26 provjera prolazi**. Manifest: `artifacts/analysis/uvc-ptp-unregister-e0171/manifest.json`; zapis: `artifacts/uvc-ptp-unregister-e0171.log`. Pokus je prošao i provjeru Python sintakse.

Još nisu izvršeni originalni kernel wait_cb acknowledgment i finish_callback, stvarne brave, raspoređivanje ni konačni allocator. Sljedeće treba povezati per-worker acknowledgment nakon korisničkog callbacka s originalnim finish_callback i wake putem. E0164 modul ostaje neučitan i `physical_test_ready:false`; produkcijski kod nije promijenjen, pa 605 testova iz E0164 ostaje zadnja puna regresija.
