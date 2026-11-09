# E0163: Native USB backend i stvarna EP0 grana u offline provjeri

Datum: 2026-11-08. Nastavak E0162. Nema pristupa fizičkoj kameri.

## Implementirani kernel wrapperi

`tools/native_camera/uvc_ptp_native_backend.{c,h}` daje stvarnu implementaciju
ops tablice za zajedničku sesiju, vezanu na provjereni a6400 kernel:

| Operacija | Native put |
|---|---|
| Disconnect | gadget ops pullup(0), setup_disconnect602b9464 |
| Controller stop/state | usb_gcw_stop602bd834, get_gcw_state602bd450 |
| Controller start | usb_gcw_start602bd7f8 |
| EP0 enable/setup | 602b05fc, 602b2b40, native EP0 descriptor604e4e24 |
| Driver register/unregister | 602b8610 / 602b8560 |
| Descriptor save/free | 602bc550 / 602bc3e4 |

Backend čita actual singleton gc iz6051b17c, provjerava odabrane originalne
instrukcije kritičnih funkcija i četiri originalna descriptor BL mjesta.
To je parcijalni live instruction guard, ne puni live kernel hash.
Offline test i dalje SHA-provjerava cijeli originalni kernel.

Caller i dalje mora osigurati serialization native USB mode promjena i
trajanje source/session/backend objekata. Backend nije gotov kernel modul,
ne instalira vlastiti unload guard i nije sam pokrenut na kameri.

## Zaustavljanje i obnova

setup_disconnect nema pouzdan C integer status; wrapper ga tretira kao void.
Nakon njega zahtijeva config74=0, nula vlastitih descriptor/bridge korisnika,
STOP dovršen i nijedan active driver record. Obilazak native registra je
ograničen na64 čvora. Zatim potvrđuje stop return i GCW state1.

Resume provjerava stopped stanje i mode0/1, potvrđuje start rezultat i novo
stanje2/3, validira EP0 out/in owner pointere, izvršava dva native enable
poziva s provjerom rezultata, arm SETUP i pullup(1), pa active flag.
Void arm poziv nije dokaz fizičke TRB obrade ili Windows spajanja.

Register/unregister dopušteni su samo za UVC config1/interface1/2 dok je
kontroler stopped. Privremeno se uklanja flags bit2 i potpuno vraća prethodna
vrijednost. Registar se čita prije/nakon operacija: register mora dodati
jedan točan descriptor, unregister ga mora ukloniti. Originalni PTP0 se
ne predaje tim operacijama.

Native unregister VRAĆA int, i to0 ili -16 u originalnom kodu. Wrapper ga
čuva. Bridge dosad ignorira unregister rezultat, pa je session ops proširen
`check_error` callbackom: native guard/unregister/free greška zadržava
session/source prije descriptor free-a ili proglašavanja releasable stanja.

Save wrapper postavlja stvarni current-thread address limit na KERNEL_DS i
obnavlja ga i pri native erroru. Zahtijeva gc+6c=0, što priprema ownership
lease. Free dopušta samo zabilježenu installed kopiju, različitu od originala
i sourcea. Nema slijepog oslobađanja nepoznate tablice.

## EP0 povezivanje

Četiri originalna BL mjesta:958c(device),95ac(qualifier),95cc(config/other),
95e0(string), sva u602bxxxx stranici. Backend unaprijed potvrđuje sve
originalne instrukcije i signed ARM BL doseg/alignment prije bilo kojeg
zapisa. Promjene/readback prati hook maskom. Izvodi native instruction-cache
flush s ARM barijerama. Unbind provjerava sva mjesta prije obnove; odbija
nepoznat tuđi patch umjesto da ga prepiše i potvrđuje originalni readback.

Dispatch potvrđuje gc i točan native EP0 request buffer, prati svoje
in-flight korisnike i poziva jedinstveni descriptor reply s kapacitetom512.
Taj kapacitet vezan je na originalni g_bind allocation na602b844c..847c:
cache allocation, eksplicitni512-byte trace argument i spremanje u request[0].
Ne izvodi se pretpostavka na temelju JPEG ili video DMA kapaciteta.

## Što je provjereno, a što je test double

Builder sada ima `--native-backend`, povezuje backend sa session/bridge/
lease/adapter/descriptor kodom i postavlja offline ELF na5f800000 radi
realističnog BL dosega. Nema unresolved importa.

Kompajlirani backend STVARNO izvršava fingerprint provjere, target pointer
pozive, flag/address-limit guardove, registry readback, branch izračun,
upis/obnovu/readback četiri instrukcije te session integraciju.

U offline memoriji stvarno je izvršena patched BL instrukcija na602b95cc
-> kompajlirani descriptor_dispatch -> jedinstveni reply -> ORIGINALNI Sony
serializer/memcpy -> povrat na602b95d0 s ispravnim173-byte outputom.
Ti serializeri nisu zamijenjeni host implementacijom.

Ali kernel/hardware učinci target operacija (pullup, stop/state, native
register/save/free/EP0 enable/setup i cache-flush učinak) IZRIČITI su boundary
DOUBLEOVI. Oni oponašaju registry/allocation rezultate za test MOD wrappera,
ne dokazuju stvarni allocator, MMIO, cache ili physical USB acknowledgement.
Writability kernel hook stranice također je eksplicitni offline fixture.
Izvršavanje ne završava fizičkom enumeracijom ili senzorskim streamom.

Testovi uključuju registraciju samo UVC-a uz očuvan PTP sentinel, točan
KERNEL_DS i njegovu obnovu, skriveni originalni root, conflict/code guardove,
no-partial-write bind preflight, stvarni patched-BL output, obnovu svih četiri
originalnih instrukcija, free samo nove kopije, save error rollback i
unregister error koji ne dopušta descriptor free.
147 kumulativnih kontrola prolazi (prethodnih120 i27 native-backend kontrola).
Puni projektni runtime nije mijenjan; prethodnih605 testova iz E0162 nije
ponavljano nakon ovih izoliranih ARM provjera.

Artefakti:
`artifacts/native/uvc-ptp-native-backend-e0163/manifest.json`, offline povezani
ELF i `artifacts/uvc-ptp-native-backend-e0163-build.log`.
Izvorni ugovori:
`artifacts/analysis/uvc-native-backend-contract-e0163/original-native-contract.txt`.

```
python -m tools.research.build_uvc_ptp_descriptor_lease --native-backend --input-dir artifacts/native/uvc-ptp-lease-input-e0161 --output-dir artifacts/native/uvc-ptp-native-backend-e0163
```

## Preostalo

Treba izraditi stvarni kernel-module entry/exit i lifetime zaštitu, povezati
točno verificirani reference wire1/2 + endpoint82 MOD i allocator, riješiti
serialization s native USB mode workerom, svježe verificirati target i
izvesti bounded fizički register/EP0/restore pokus prije prijenosa kadrova.
Host Sony UVC detekcija s PID0caa i native JPEG/DMM producer ostaju otvoreni.

Nema camera uploadova, modula, feeder procesa, promjene USB načina, SD ili
trajnih zapisa. Ovo nije dokaz fizičkog UVC+PTP rada.
