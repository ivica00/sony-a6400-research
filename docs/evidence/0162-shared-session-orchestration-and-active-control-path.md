# E0162: Povezana shared sesija, registracija i kontrolni put

Datum: 2026-11-08. Nastavak E0161. Nema pristupa kameri u ovom koraku.

## Povezani kandidat

`tools/native_camera/uvc_ptp_session.{c,h}` povezuje postojeći bridge,
endpoint82 selector, descriptor validator i ownership lease u zajednički
ARM postupak. Hardverski backend nije implementiran u ovoj datoteci.

Begin preflight zahtijeva:

- Izvornu native PC Remote HS tablicu: 054c:0caa, device class0, jedna
  konfiguracija/sučelje0, PTP06/01/01, kanali81/02/83 s parametrima E0153.
- Verificirani kandidat i reference sučelja1/2, config1, START/STOP/CLASS.
- Caller-verificirani reference MOD za wire1/2 + video82. Sam session helper
  ne verificira callback code hash; to mora osigurati modul/builder.
- Caller serialization i pinned source/reference/ops lifetime.

Zatim izvodi redom: quiesce -> bridge prepare -> shadow register1/2 ->
native descriptor lease install/validate -> EP0 bind -> resume.
Sve operacije moraju dati stvarne rezultate u budućem hardverskom backendu.
Originalni PTP descriptor nije argument nijedne register/unregister operacije.

End izvodi: quiesce -> provjera bridge started/in-flight nula -> EP0 unbind
-> unregister2/1/bridge retire -> native descriptor free/restore -> obnova
originalnih flags/mode -> resume. Ako resume može biti parcijalan, za novi
pokušaj ponovno zahtijeva quiesce. EP0 unbind mora biti idempotentan i nakon
neuspjelog/partial bind pokušaja.

## Pogreške i zadržavanje memorije

Svaka greška nakon prve izmjene ide kroz isti obrnuti cleanup put. Greške
quiesce/unbind/restore/resume ostavljaju HELD stanje. In-flight ili started
bridge također blokira oslobađanje: backend ack sam ne predstavlja dokaz
da su native korisnici povučeni. Lease quarantine ne otpušta template.

`session_releasable` zahtijeva IDLE, nema pending stop/prepared/registered/
hook stanja, nema bridge magic/in-flight korisnika i prazan lease. Ovo je
API za buduću module-unload zaštitu, ne već instaliran unload hook.

## Što je stvarno izvršeno

Builder `build_uvc_ptp_descriptor_lease --session` povezuje pet produkcijskih
ARM C komponenti i malu eksplicitnu fixture pomoć. Nema neriješenih importa.
Stvarno se izvršavaju kompajlirani session/bridge/lease/validator/selector.

Controller quiesce/resume, EP0 bind/unbind, driver register/unregister,
descriptor save/free i reference callbackovi su IZRIČITI RECORD DOUBLEOVI.
Oni dokazuju redoslijed i MOD state ugovor, ne fizičke kernel acknowledgeove.
Svaki neovisni negativni test resetira fixture; to nije recovery na kameri.

Kroz ACTIVE stanje dodatno je izravno pozvan stvarni descriptor_reply nad
instaliranim neovisnim copy fixtureom. Originalni Sony serializer/memcpy
vratio je173-bajtni HS konfiguracijski odgovor. To nije dokaz da je live EP0
hook instaliran: bind je i dalje recorder.

Stvarni kompajlirani bridge usmjerio je wire1/2 class zahtjeve s entity2 na
reference recorder uz isti setup pointer. Za START je sessionov stvarni
selector dobio eksplicitne DWC/raw/wrapper fixturee i proslijedio upravo
wrapper endpointa82, uz originalni low-byte packed count ugovor. Nije
submitan USB zahtjev. Testni STOP eksplicitno poziva bridge quiesce prije
cleanup testa; ne predstavlja native controller drain.

## Rezultati

120 kumulativnih kontrola prolazi: prethodne73 ownership i47 novih povezanog
postupka. Uključuju dva ciklusa, strogi redoslijed, registraciju samo1/2,
obrnut unregister2/1, nepromijenjen originalni PTP graph, neuspjeh drugog
registera/savea/binda/resumea, held retry, zabranu cleanup-a pri in-flight,
quarantine bez free-a te preflight odbijanje drugog USB moda i legacy0/1.

Ulazni originalni PC Remote graph u provjeri neovisni je fixture izveden iz
verificiranog native formata/parametara; nije kopija živog kernel heapa.
Kroz testove se ne simulira uspješan native allocator kao dokaz firmwarea.
Puni projektni skup također prolazi:605 testova u14.896s; log je
`artifacts/uvc-ptp-session-e0162-project-tests.log`.

Artefakti: `artifacts/native/uvc-ptp-session-e0162/manifest.json` i povezani
`descriptor-lease.elf` (offline izvršni ELF, nije kernel modul), build log
`artifacts/uvc-ptp-session-e0162-build.log`.

```
python -m tools.research.build_uvc_ptp_descriptor_lease --session --input-dir artifacts/native/uvc-ptp-lease-input-e0161 --output-dir artifacts/native/uvc-ptp-session-e0162
```

## Sljedeća granica

Nedostaju stvarni backend wrapperi za disconnect/controller stop/drain,
address-limit save/free, flags guard pri native registeru, EP0 hook s
readbackom i reconnect. Tek s njima se ovaj redoslijed može provjeriti kao
fizička sesija; ne zamijeniti ih recorderima i nazvati to kompatibilnošću.
Native producer/DMM/JPEG prijenos i Windows zajedničko nabrajanje također
nisu dokazani. Kamera, SD i trajna memorija nisu mijenjani.
