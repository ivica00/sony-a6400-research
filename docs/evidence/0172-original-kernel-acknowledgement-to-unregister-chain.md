# E0172 — Izvorna kernel potvrda do završnog uklanjanja callbacka

Datum: 2026-11-08. Offline nastavak E0171. Nema pristupa fizičkoj kameri ni izmjene produkcijskog modula.

## Nova izvršena granica

`tools/research/probe_uvc_ptp_kernel_unregister.py --acknowledgement` sada izvršava originalni `__k_4u_wait_cb` na .text+0xe8c, originalni lookup reda na .text+0x2330, `finish_callback` na .text+0x4154 i originalni nastavak obrade praznog reda na .text+0x2d10, uz ranije provjerene wait/wake/unregister/free_cb funkcije.

Izvor ostaje a6400 osal_uipc.ko SHA-256 `3743275bc964a2804b80cde4f589f60876b795fbeeccd3cbf2c18a0da2dc8567`. Primijenjene su izvorne ELF relokacije. Odluke i promjene callback counta nisu hostove zamjene.

## Cijeli provjereni slijed

1. Originalni unregister helper za callback koji izvršava druga dretva postavlja retire oznaku, registrira stack waiter i staje prije schedule. Sačuvan je stvarni emulirani CPU kontekst čekatelja.
2. Na odvojenom stogu originalni kernel wait_cb primi 16-bajtni ulaz. User-copy je izričita zamjena; sadržaj, per-worker owner i trenutni task eksplicitni su fixture podaci.
3. Originalni kod veže worker slot uz task, uzima prethodni callback i poruku iz per-worker slota te čisti prethodni callback slot **prije** završne obrade.
4. Za provjereni asinkroni callback originalni finish_callback kroz stvarni lookup na fixture queue ID-u 13 pronalazi red, smanjuje active count 1→0 i poziva originalni wake helper.
5. Wake helper uklanja waiter, briše njegov callback pointer i poziva wake_up_process za čekatelja (servisna zamjena). Registracija i dalje nije oslobođena dok čekatelj ne nastavi.
6. Acknowledgment dretva staje na schedule dok čeka novi posao iz praznog reda. Nakon obnove CPU konteksta čekatelja originalni unregister nastavi, originalni free_cb smanji allocation counter, preda blok finalnom allocator-u (izričita zamjena) i izbriše registrirani slot.

Za razliku od pozitivnog completion fixturea E0171, novi acknowledgment slučaj **ne postavlja active count na nulu hostovim zapisom**. To radi originalni finish_callback. User callback sam nije izvršen u ovom kernel pokusu; per-worker pending slot izričiti je početni fixture. E0170 zasebno dokazuje izvorni korisnički povratak callbacka do sljedećeg wait ioctl-a.

## Identitet workera

Provjeren je i negativni put:

- Ako je slot već vezan uz drugi task pointer, wait_cb vraća -EINVAL (-22), bez čišćenja pending callbacka ili promjene counta.
- Indeks 4 odbija se s -EINVAL; izvorna provjera dopušta indekse 0..3. Callback ostaje pending i aktivan.

To daje konkretan kernel ugovor za vezanje izvršitelja. Ne dokazuje fizički TID, broj trenutačnih workera niti identitet njihova procesa na spojenoj kameri.

## Provjere i precizni opseg

**40 provjera prolazi**, uključujući ranijih 26 i 14 dodatnih za acknowledgment lanac i negativne ulaze. Manifest: `artifacts/analysis/uvc-ptp-ack-e0172/manifest.json`; zapis: `artifacts/uvc-ptp-ack-e0172.log`. Osnovni način bez acknowledgment opcije ponovno prolazi svih 26 provjera; sintaksa probea provjerena je.

Provjeren profil je asinkroni callback, prazan red za sljedeći posao i isključena queue zastavica koja uključuje dodatno oslobađanje poruke. `finish_callback` putovi za druge profile, vlasništvo nad porukama, stvarne brave, raspoređivač, copy servisi i konačni allocator nisu dokazani. Lock/unlock, schedule granice i wake_up_process ostaju eksplicitni servisi; ne tvrdi se fizička konkurentnost ili uspješna kamera transakcija.

## Posljedica i sljedeći korak

Za ovaj profil sigurna granica OSAL uklanjanja iz druge dretve jest **acknowledgment prethodnog callbacka, wake čekatelja i uspješan povratak čekatelja**, uz očuvane resurse tijekom čekanja i pri prekidu. Sam izlazak korisničke callback funkcije ili slanje statusa nije dovoljan zamjenski signal.

Ovaj OSAL ugovor ne smije se automatski primijeniti na gadgetcore/EP0 callbackove. Zajednički modul E0164 koristi druge callbackove i još nema dokazano zajedničko usklađivanje s izvornim promjenama USB načina. Sljedeća integracijska odluka treba povezati potvrđenu glavnu USB dretvu, njezine izravne stop ulaze i trajanje EP0/gadget callbackova; nije potrebno dalje nagađati OSAL završetak ovog profila.

Modul ostaje neučitan i `physical_test_ready:false`. Produkcijski kod nije mijenjan; zadnja puna projektna regresija ostaje 605 testova E0164. Istodobni senzorski UVC i PTP na kameri ostaju nedovršeni.
