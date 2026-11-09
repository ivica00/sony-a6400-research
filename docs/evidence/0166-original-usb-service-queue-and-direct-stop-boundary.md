# E0166 — Izvorni USB red poruka i zaseban izravni stop

Datum: 2026-11-08. Nema pristupa kameri ni promjene produkcijskog modula. Nastavak E0165.

## Dokazani put pokretanja

Novi `tools/research/probe_uvc_ptp_service_queue.py` izvršava izvorna Thumb tijela u originalnoj a6400 `libInfraUsbCmn.so`, SHA-256 `5338bafbb545ebc223fac15c9253a41ac9fe49c01fe32c73af40c3fb50eec0a6`.

Izvorni `CUsbSvc::start_gadget` (0x9ed9) stvara 32-bajtnu poruku i predaje je kroz `CUsb::request` (0x848b). Potvrđeni su polja poruke: object+0, callback+8, user+12, byte argument+16, completion+20. Callback je originalni `CUsbSvc::createGadget` na 0xbbc5, dobiven kroz stvarnu ELF relokaciju; nije izmišljeni callback za test.

`CUsb::request` zaključava this+0x40, izvršava originalni `que_push` (0x8433), signalizira this+0x58 i otključava. Ring koristi buffer+0x14, byte head+0x18, tail+0x19 i capacity+0x1a; slot je 32 bajta. Originalni push kopira svih 32 bajta i povećava tail s kružnim povratkom. Pun red vraća 12 bez promjene sadržaja.

Izvorni `CUsb::proc_service` (0x8529) pod istom zaštitom poziva originalni `que_pop` (0x8501), povećava head i otključava **prije** poziva callbacka iz slot+8. Na granici callbacka r0 pokazuje stvarni slot u fixture ringu, a zabilježeno stanje mutex zamjene je otključano.

To je dokaz izvornog rasporeda instrukcija i rada reda na eksplicitnim podacima. Nije dokaz stvarnog raspoređivanja dretava, broja radnih dretava niti mogućnosti sigurnog ubacivanja MOD poruke u fizički aktivnu uslugu. `createGadget` nije izvršen; tu pokus staje.

## Stop ne mora prolaziti kroz taj red

Izvorni javni `CUsbSvc::stop` (0x9e01) provjerava handle na this+0x9c (gadget) odnosno this+0xa0 (host) i stanje this+0x98. Za gadget handle i stanje 3 postavlja stanje 4 i **izravno** poziva `stop_gadget` preko PLT 0x81ac. U ovom tijelu nema zahtjeva redu ni provjere identiteta radne dretve. Pokus provjerava argumente, očuvane indekse reda, pogrešan handle (11) i pogrešno stanje (6), te staje prije stop_gadget.

Ovo ne dokazuje da stvarni vanjski pozivatelj radi konkurentno s workerom. Dokazuje da sama izvedba reda i mutex this+0x40 nisu dovoljni kao univerzalni ugovor za sve ulaze. Osim toga, mutex se otključava prije createGadget callbacka. Držati ga preko naše transakcije značilo bi promijeniti izvorni ugovor, uz još nedokazane posljedice.

## Točno razrješenje PLT-a

Probe za devet korištenih odredišta računa GOT iz stvarnih ARM add/add/ldr instrukcija PLT stavke i povezuje ga s `.rel.plt`. Ne koristi stalni razmak stavki. Tako se automatski provjeravaju request, que_push/pop, pthread lock/unlock, condition signal, getpid, cancellation i stop_gadget. E0165 pogrešna oznaka port_init za 0x7b10 ispravljena je u samom dokumentu: pravo odredište je request.

## Provjere

**35 provjera prolazi**: 9 odredišta PLT-a, originalna poruka, red i worker, prazan/pun red i kružni povratak te izravni stop i negativni ulazi. Rezultati i hash samog probea nalaze se u `artifacts/analysis/uvc-ptp-service-queue-e0166/manifest.json`; zapis pokretanja je `artifacts/uvc-ptp-service-queue-e0166.log`.

Pthread, zapisivanje, getpid i cancellation izričite su servisne zamjene; GC/objekt, ring, stack i indeksi izričiti fixture podaci. Guard odbija neočekivano izvršavanje i zapise izvan dozvoljenih fixture regija. Nijedan hardverski servis, modul loader, originalni createGadget ni stop_gadget nije izvršen.

Produkcijski kod nije mijenjan pa nisu ponavljani svi projektni testovi; prethodnih 605 prolaznih testova iz E0164 ostaje posljednja puna regresija. E0164 kandidat ostaje `physical_test_ready:false`. Sljedeće treba pratiti vanjske pozivatelje CUsbSvc::stop/start i njihove životne vijekove ili dokazati zajedničku zaštitu svih kernel ulaza. UVC senzorski tok s istodobnom PTP kontrolom ostaje nepotvrđen na kameri.
