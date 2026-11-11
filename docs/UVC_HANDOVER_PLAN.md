# Sony ILCE-6400: nastavak izvornog JPEG → UVC toka

## Cilj i ograničenja

Povezati izvorne kadrove senzora s već potvrđenim UVC Bulk IN transportom za CinemaHUD: MJPEG 1280×720 pri 30 FPS.

- Komunicirati isključivo na hrvatskom.
- Sve zapise i payloadove na kameri ograničiti na RAM `/tmp_bt`. Bez SD/NAND/Backup/preload/boot izmjena.
- Zadržati Microsoft inbox `usbvideo.sys`; bez zamjene Windows drivera.
- Očuvati svih 599 testova emulatora. Ne pokretati podagente bez izričitog zahtjeva.
- Ne predstavljati testnu sliku, prolazak testova ili statičku analizu kao prikaz senzora.

## Obvezno pročitati

1. `AGENTS.MD` — najnoviji zapis E0144 ima prednost pred povijesnim stanjima.
2. `docs/evidence/0144-native-jpeg-receiver-ownership-and-dma-allocation.md`.
3. `docs/evidence/0143-uvc-720p-test-transport-and-30fps-verified.md`.
4. Za referentni producer i prethodne granice: E0134 i E0133.

## Posljednje provjereno fizičko stanje

- Mass Storage debugger PID703 dostupan; prvo ponovno provjeriti stanje.
- Eksperimentalni UVC modul **uklonjen**, nema aktivne UVC sesije, observera ni hooka.
- Nije potreban preventivni restart kamere.
- Nisu poslane JPEG konfiguracijske poruke ni GET_JPEG; stvarni kadar senzora još nije preuzet.
- Završni testovi: 599/599, 14,500 s; 53 ARM kontrole mosta i 10 originalnih kontrola JPEG reda prolaze.

## Što već radi

E0143 potvrđuje PnP bez Code10, Bulk IN endpoint 0x81, izvršavanje izvornog START callbacka, dekodiran 1280×720 MJPEG kadar i 180 primljenih kadrova pri 29,9592 FPS. CinemaHUD HTTP monitor prihvatio je tok. Izvor je bila **statična testna JPEG slika**; testni server je zaustavljen.

A6400 START već šalje `(speed, count, array)`. Broj endpointa je samo donji bajt r2; gornji bajtovi nisu broj. Modul očekuje gadgetcoreov omotač, čiji +0x24 pokazuje na sirovi endpoint iz `*(dwc+0xdc)`. Ne zamijeniti omotač sirovim pokazivačem. Most provjerava Bulk IN 0x81 i prati sučelje za STOP.

## Ključna korekcija memorije

Referentni argument `0x50e` je **DMM UnitType**, ne 1294 KB. A6400 izvorni DMM odgovor je -3/handleFFFF: tip nije definiran. Povijesni fiksni prozor na PA20000000 nije dokaz vlasništva ili izvorne alokacije.

`build_uvc_composite_module` sada zadano zadržava izvorni DMM alokator i vidljivo odbijanje. Fiksni prozor dostupan je samo uz `--experimental-fixed-buffer`; ne koristiti ga za nastavak izvornog toka.

Odvojena MOD politika `--coherent-buffer-allocation` koristi stvarni kernelov `dma_alloc_coherent`/`dma_free_coherent` i ispravno mapiranje dobivenog CPU pokazivača. Završnih 256 KiB prošlo je tri fizička open/close ciklusa s različitim PA i potvrđenim oslobađanjem. Veći zahtjevi nailaze na fragmentaciju. To je **samo provjera životnog ciklusa**, bez streaminga i bez dokaza dovoljnog kapaciteta za proizvoljne 720p JPEG kadrove.

**Ne pokretati stari feeder s fiksnim adresama protiv ovog alokatora.** Najprije dodati upit stvarne adrese/kapaciteta i provjere veličine svakog odredišnog slota.

## Izvorni JPEG prijamnik

Koristiti trenutačnu kamerinu sliku:

`artifacts/hardware/av-cam-camera-original.bin`

SHA-256: `dd8f8d0cc74ad4b70100e5728cf8b159b5155e7fb50eaf1147b99c9054740209`, ORIL baza `0x635c6000`. Razlikuje se od paketnog firmwarea; ne prenositi adrese pretpostavljenim pomakom.

- `ScalarInfraAsyncMain` na `0x63a90c38` prima na `0x0167046a`; kod i relevantni podaci podudaraju se s fizičkom kamerom.
- Vanjski SET_PATH ide na `0x01670464`; njegovu sinkronu pretvorbu u internu poruku još treba dovršiti. Interni OPEN koristi halfword+2=0x8120 i JPEG selektor +0xc=0x30/0x31. Nije ista poruka kao vanjski zahtjev.
- GET_JPEG predikat: halfword+2=0x0100, byte+0xf=0x20. GET_INFO koristi byte+0xf=0x10.
- GET_JPEG handler `0x63a91a3c` preuzima READY ručke, bira najnoviji kadar prema 24-bitnom brojaču i oslobađa preostale stare kadrove. Dohvat mijenja vlasništvo.
- JPEG objekt: slot `0x645c629c` → posljednje opaženo `0x643c3708`; red od 12×12 bajtova na +0xf4. Posljednji nezamrznuti snimak: svi EMPTY/state1, handleFFFF, size0; stage pokazuje na idle `0x643c3ad0`. Ponovno provjeriti prije uporabe.
- Odgovor sadrži veličinu zaokruženu na jedinice od 128 bajtova i dodatno polje 0x274. DMM značenje tog polja još potvrditi.
- Izvorni JPEG OPEN `0x63a918c0` pokušava alocirati DMM tip0x276 uz ponavljanja i dvosekundna čekanja koja mogu trajati vrlo dugo. Ne pozivati bez provjere resursa i povratnog postupka.
- Decompilacija preparation helpera ima bad-instruction/PIC upozorenja: **nije dokaz prihvaćenih dimenzija ili granica kodera**.
- `libInfraStreamingServer.so` nije učitan u posljednjim mapama PID149; ne koristiti povijesne RAM adrese tog servisa.

## Preporučeni redoslijed nastavka

1. Provjeriti debugger i stanje modula; sačuvati nova opažanja odvojeno od E0144.
2. Implementirati eksplicitan MOD upit stvarnog DMA kapaciteta/adresa. Dodati per-slot provjere, uključujući 12-bajtno UVC zaglavlje. Odbiti prevelik kadar prije DMA pristupa; ne skraćivati ga i ne izmišljati uspjeh.
3. Dovršiti vanjski/sinkroni SET_PATH prijamnik, polja dimenzija i kapaciteta iz originalnih instrukcija. Provjeriti resurse za tip0x276 i povratak u prethodno stanje prije fizičkog OPEN-a.
4. Dovršiti DMM otvaranje, fizičku adresu/kapacitet, zatvaranje i oslobađanje svih vraćenih ručki prema originalnom slijedu. Provjeriti i putanje pogreške/isteka vremena.
5. Preuzeti **jedan** izvorni JPEG uz potpuno čišćenje. Provjeriti SOI/EOI, SOF dimenzije i stvarnu duljinu unutar potvrđenog kapaciteta. Bez stalnog toka dok taj ciklus nije potvrđen.
6. Povezati producer s UVC-om: `WaitVideoReadCmp` prije `UpdateVideoBufEvt`, razdvojeni izvor/odredište, apsolutni monotoni rokovi. Ponovno izmjeriti FPS i promjenu sadržaja stvarnih kadrova; prethodnih 29,96 FPS vrijedi samo za testnu sliku.
7. Potvrditi CinemaHUD i uredan STOP/povratak u Mass Storage; sačuvati dokaze i pokrenuti svih 599 testova.

## Alati i artefakti

- `tools/research/oril_scalar_elf_view.py`: byte-preserving ELF prikaz odabranih ORIL područja za analizu; nije kamerin izvršni payload.
- `tools/research/rea_oril_scalar_batch.py`: provjerava porijeklo, hashove i bajtove sekcija prije REA/WSL analize. Standardni firmware-only launcher nije oslabljen.
- `tools/research/scalar_jpeg_buffer_probe.py`: 10 kontrola izvornih Thumb helpera; pozitivna stanja su eksplicitni fixturei.
- `artifacts/hardware/uvc-native-source-e0144/`: fizički snimci, OSAL/DMM izvještaji, logovi i manifest.
- `artifacts/tools/rea/oril-*e0144*`: analize prijamnika i vlasništva. Sačuvani neuspjeli batch nije završeni dokaz.
- Fizički testirani DMA modul: `artifacts/native/uvc-owned-dma-256k-e0144/usbg_video_a6400.ko`, 40196 bajtova, SHA-256 `c9bbb01584874aa76ddce18dfa704d8bbced64a3b573e75806c9cc52efd0de45`.

`/proc/osal/uipc` treba čitati u istom otvorenom toku, npr. `cat` u `/tmp_bt`, pa dohvatiti običnu datoteku. Ponovno otvaranje uz byte-offset preskače njegove interne faze.

## Osnovne naredbe

```powershell
py -3.12 tools/camera_debugger.py info
py -3.12 -m unittest discover -s tests
py -3.12 -m tools.research.scalar_jpeg_buffer_probe
py -3.12 -m tools.research.build_uvc_composite_module --output-dir artifacts/native/NOVI-NAZIV --coherent-buffer-allocation
```

Zadnja naredba samo gradi modul. Ne podrazumijeva provjeren streaming, kapacitet ni odobrenje za stare fiksne feeder adrese. Nastaviti unutar već odobrenog RAM opsega, bez rutinskih potvrda i bez tvrdnji koje prelaze dokaze.
