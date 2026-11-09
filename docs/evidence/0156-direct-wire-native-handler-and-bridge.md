# E0156: Izvorni setup pointer kroz bridge i modificirani UVC handler

Datum: 2026-11-08. Nastavak E0155. Nema fizičkog učitavanja.

## Odluka o trajanju zahtjeva

Umjesto povezivanja kopirajućeg setup adaptera odabran je zaseban, precizno
ograničen MOD referentnog UVC drivera koji izravno razumije wire sučelja 1/2.
Time se ne stvara novi setup buffer ni dodatni pointer koji bi native EP0
completion mogao koristiti nakon isteka. Originalni setup pointer, sadržaj
zahtjeva i postojeće native trajanje ostaju isti. Ovo ne dokazuje native
EP0 completion/teardown u zajedničkoj fizičkoj konfiguraciji.

## Dvije izričite MOD instrukcije

Originalna referenca usbg_video.ko vezana je na SHA-256
d385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb.

| Mjesto u .text | Original | MOD | Učinak |
|---|---|---|---|
| 116c | 7e20e0e3, mvn r2,#7e | 7d20e0e3, mvn r2,#7d | video request tag 81->82 |
| 13e8 | ff5015e2, ands r5,r5,#ff | 015055e2, subs r5,r5,#1 | VC wire1->native0, VS wire2->native1 |

Classifier instrukcija izvršava se tek nakon originalne provjere da je
wIndex high-byte/entity ID nula. Zato SUBS ne mijenja originalni entity put;
za entity!=0 originalna grana vodi na 16f8 prije MOD instrukcije.
PTP wire0 mora biti odbačen bridgeom prije UVC callbacka. Samostalno
pozivanje MOD handlera za nepodržana sučelja nije valjan ugovor.

Builder verificira cijeli originalni hash i obje originalne instrukcije.
U konačnom objektu razlikuju se točno tri bajta, file offsets 11a0, 141c i
141e. Nema drugih promjena, uključujući relokacije.

`artifacts/native/uvc-ptp-adapter-e0156/reference-wire12-endpoint82.offline.o`
SHA-256 e2244462fa4c604689113603953781b4ee25569b054d8bdc29b36d1af89c2da8.
Ovo je offline objekt, ne kompletan/deployable UVC+PTP modul.

## Ispravak bridgea

`tools/native_camera/uvc_callback_bridge.c` sada za interface-recipient
uspoređuje samo setup[4], tj. wIndex low byte, s brojem shadow sučelja.
setup[5] je UVC entity ID i ne smije uzrokovati pogrešno odbacivanje.
Izvorni a6400 dispatcher također koristi ldrb na request+4, na 602ba010.
Bridge ne prepisuje setup pointer niti setup podatke. Ostala registracija,
callback snapshot, in-flight i START/STOP logika ostaju nepromijenjeni.

Registracija shadow sučelja 1/2 već radi kroz postojeći descriptor ABI kada
reference interfaces vector sadrži 1/2. Izvanmrežne kontrole provjerile su
klasne zahtjeve za oba sučelja/entity 0 i 2, odbijanje PTP wire0 i pogrešnog
shadowa, START VS-a, ignoriranje tuđeg VC STOP-a i quiesce pri unregisteru.
Registracija/unregistracija u tim kontrolama koristi eksplicitne recordere,
ne fizički gadgetcore ack.

## Izvorni put, ne samo record callback

Proširen `tools.research.uvc_callback_bridge_probe` prima opcionalni
`--reference-wire-object`. Verificira MOD hash prema manifestu, originalni
SHA i jednake sve bajtove osim tri navedena.

Četiri zasebna CPU pokretanja izvršavaju:

1. Originalni a6400 dispatcher odsječak na 602ba05c.
2. Kompajlirani MOD bridge i njegov originalni request pointer.
3. Stvarni MOD referentni core_cb_class na .text+17b0.
4. Stvarni referentni classifier na +1390 s navedenom MOD instrukcijom.

VC wire1/entity0 staje na +1410; VS wire2/entity0 na +16a4; entity2 za oba
staje na +16f8. U sva četiri slučaja helper r6 jest izvorni setup pointer,
a svih osam bajtova zahtjeva ostaje jednako izvornom zahtjevu.

Zaustavljanje je prije alokatora, queueing i completion. Nije izmišljen
uspješan povrat native callbacka; ova četiri pokretanja namjerno ne završavaju
callback. Raniji lifecycle/rollback testovi i dalje imaju jasno označene
record callbackove. Ne predstavljaju fizički zajednički lifecycle.

## Rezultati

- 65 ARM adapter/MOD kontrola prolazi; uključene ranije 55 i deset novih.
- 91 bridge/dispatch kontrola prolazi; uključene ranije kontrole i dvadeset
  provjera četiri stvarna reference-entry puta.
- Puni projektni skup: 605 testova prolazi u 19.125 s.

Artefakti:

- `artifacts/native/uvc-ptp-adapter-e0156/manifest.json`.
- `artifacts/native/uvc-callback-bridge-e0156/manifest.json`.
- `artifacts/analysis/uvc-callback-reference-e0156-final/manifest.json`.

## Granica i nastavak

Kopirajući adapter iz E0155 ostaje izoliran i nije potreban za ovaj izravni
wire pristup. Riješen je dodatni problem trajanja koji bi on uveo, ali nisu
završeni native kontrolni prijenos ni životni ciklus cijelog zajedničkog
uređaja. Još treba povezati descriptor bundle, reference MOD, endpoint82
selector i shadow1/2 u zajedničku gadgetcore registraciju uz originalni PTP
driver, potvrditi EP0 puni odgovor/IAD/FS i rollback, te vezati native JPEG
proizvođač i DMA vlasništvo. Originalni PTP driver nije zamijenjen host kodom.

U ovom koraku nije pristupano kameri niti pisano na SD/trajnu memoriju.
Fizička enumeracija UVC+PTP, prijenos senzorskih UVC kadrova i stvarne PTP
promjene postavki ostaju nepotvrđeni.
