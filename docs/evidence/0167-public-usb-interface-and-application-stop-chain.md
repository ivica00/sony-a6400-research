# E0167 — Javna USB tablica i poziv zaustavljanja iz aplikacije

Datum: 2026-11-08. Offline nastavak E0166; bez pristupa kameri i bez promjene E0164 modula.

## Izvršena tijela i izvori

`tools/research/probe_uvc_ptp_public_api.py` izvršava originalni prefix `usbif_initialize`, javni stop adapter, `CUsbSvc::stop` i `UsbIfWrapper::doStop`. Nema hostovih zamjena njihovih grananja ili tablice funkcija.

| Izvor | SHA-256 |
|---|---|
| a6400 libInfraUsbCmn.so | 5338bafbb545ebc223fac15c9253a41ac9fe49c01fe32c73af40c3fb50eec0a6 |
| a6400 libUsbControl.so | 70cd5742fde9eea78c60905e4015531b4c3ab2668d2cb85c934531f451f1211f |

Initializer prefix 0xd7d9..0xd86c alocira kontekst 0xc4 i servis 0x128, postavlja context+0x3c=service te popunjava 15 pokazivača javnog API-ja. Pokus staje prije preostale inicijalizacije. Alokator, constructor servisa, memset i trace/log servisi izričite su zamjene. Uspješna potpuna inicijalizacija, registracija ili životni vijek objekta nisu dokazani.

Važni stvarno upisani slotovi:

| Pomak konteksta | Originalna funkcija (Thumb) |
|---|---|
| +0x08 | 0xd551, javni start adapter |
| +0x0c | 0xd37d, javni stop adapter |
| +0x3c | pokazivač CUsbSvc, nije funkcija |

Potpuna tablica zadržana je u manifestu pokusa. Ovo su lokalne ELF adrese, ne adrese trenutačno učitane biblioteke na kameri.

## Stvarni lanac zaustavljanja

Na eksplicitnim fixture objektima i handleu 13 izvršen je slijed:

`libUsbControl::UsbIfWrapper::doStop` (0x13325) → context slot+0x0c → originalni javni adapter (0xd37d) → originalni `CUsbSvc::stop` (0x9e01) → granica prije `stop_gadget` (PLT 0x81ac).

Javni adapter stvara izvorni 12-bajtni completion payload: service, korisnikov completion callback, DID. Zatim predaje CUsbSvc::stop argumente service/DID/payload/12 i vlastiti completion adapter 0xd471. `CUsbSvc::stop` promijeni stanje 3 u 4 i izravno proslijedi stop_gadget argumente service/payload/12/0xd471. Nijedan request redu ili lock servis ne poziva se u tom izvršenom lancu.

Za doStop glavni aplikacijski singleton cell na relativnom 0x1eac4 eksplicitno je zadan fixtureom. Biblioteka je mapirana na zasebnu bazu; originalni PIC kod učita cell, pozove slot+0x0c i izračuna vlastiti callback na relativnom 0x12de5. Točna completion adresa i sadržaj payload-a provjereni su. Completion callback, oslobađanje payload-a i fizički stop nisu izvršeni.

Ova provjera proširuje E0166 s javnog servisa na stvarnu aplikacijsku biblioteku. **Ne dokazuje** da viši pozivatelj radi konkurentno niti da nema vanjske zaštite. Nije opravdano dodati mutex samo oko našeg kernel ulaza i proglasiti sve izvorne pozive pokrivenima.

## PLT i viši pozivatelj

Novi zajednički `tools/research/arm_plt.py` dekodira stvarne ARM add/add/ldr riječi i relokacije, uključujući rotirane neposredne vrijednosti. libUsbControl koristi oblik ADD immediate 20 ROR 20 (=0x14000), dok je raniji kod proučavan na drugom obliku. Stalni razmak PLT stavki ili zbrajanje Capstone prvog immediate operanda bez rotacije nisu valjani postupci.

Točno razrješavanje odredišta u aplikacijskoj biblioteci identificira:

- 0x99f8: `UsbIfWrapper::doSyncStartStop`;
- 0x9fac: `osal_dynamic_id`;
- 0x9904: `osal_rcv_msg_tmo`;
- 0x9e04 / 0xa1ac: `doStart` / `doStop`;
- 0x97c8: `usbif_initialize`.

Statički pregled doSyncStartStop 0x13341 pokazuje kreiranje privremenog OSAL ID-a (0x29/0xca), odabir doStart/doStop i čekanje odgovora. To tijelo još nije izvršeno u pokusu; čekanje odgovora samo po sebi nije dokaz međusobnog isključivanja. Taj sloj, callback 0x12de5 i svi pozivatelji ostaju sljedeća granica.

## Provjere i stanje

22 nove provjere prolaze u `artifacts/analysis/uvc-ptp-public-api-e0167/manifest.json`, uz hash probea i obje biblioteke. Prethodni probe reda ponovno prolazi svih 35 provjera nakon prelaska na zajednički resolver PLT-a. Oba probea imaju granice izvršavanja i zapisa, eksplicitne fixture objekte i servisne zamjene; nema fizičkog USB pokusa.

Produkcijski C modul nije mijenjan. Zadnja puna projektna regresija ostaje 605 testova iz E0164. Nisu dokazani zajednička zaštita svih USB ulaza, fizička enumeracija PTP/UVC kombinacije, povratak konfiguracije nakon prekida ni stvarni senzorski UVC tok. E0164 ostaje `physical_test_ready:false`.
