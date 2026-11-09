# E0155: UVC/PTP adapter zahtjeva i endpoint 82

Datum: 2026-11-08. Nastavak E0154; kompatibilnost sa Sonyjevim host
programima nije cilj. Sve promjene u ovom koraku su izvanmrežne.

## Izvorne prepreke

Originalni referentni usbg_video.ko SHA-256
d385a051bf01b0e5ea37412623ae85cfe3cda76ab0d11e61d111994ca9fbf4fb:

- core_cb_class na .text+17b0 zove helper na +1390. Za GET zahtjev A1 helper
  čita wIndex, prvo odvaja high-byte entity ID, zatim low-byte interface.
  Interface 0 ulazi u VC put, nenulti interface u VS put. Bez adaptera
  novo VC sučelje 1 pogrešno ulazi u VS. To je potvrđeno originalnim ARM
  odsječkom, ne samo tumačenjem disasembliranja.
- core_cb_start na +10f0 na +116c izvodi `mvn r2,#0x7e`, zatim na +1174
  upisuje byte 81 u native request tag na extended-context+18. Promjena
  samo USB deskriptora/endpoint wrappera ne mijenja ovaj tag.

## Implementacija zasebnih adapter dijelova

`tools/native_camera/uvc_ptp_adapter.{c,h}` nisu povezani s aktivnim bridgeom.

`a6400_uvc_ptp_translate_setup` prima caller-owned 8-byte wire i output
buffere te točan wire shadow (1 ili 2). Za class/interface 21/A1 zahtjeve
prevodi isključivo wIndex low-byte 1->0 ili 2->1. High-byte entity ID ostaje
isti, kao i bRequest, selector, length i smjer. PTP interface 0, pogrešan
shadow, standard/vendor/endpoint recipient, null i preklapajući bufferi
odbijaju se prije bilo kojeg zapisa. Izvorni zahtjev se ne mijenja.

Caller mora dokazati trajanje output buffera za native callback/completion.
Ovaj API to sam ne rješava. Nema stack-buffer prosljeđivanja u live driver
niti pretpostavke da native kod nikad zadržava pointer.

`a6400_uvc_ptp_select_endpoint` za planirani HS profil zahtijeva:

- Native dwc, native listu i low-byte count 1..16 (padding gornjih bajtova
  nije count, prema ranijem fizičkom ugovoru).
- Raw endpoint iz dwc+e4 (0x82 prema originalnom DWC lookup ugovoru),
  enabled bit u raw+4c, i raw descriptor 7/5/82/Bulk/maxpacket512.
- Točno jedan gadgetcore wrapper s wrapper+24 jednakim tom raw endpointu.

Nula, pogrešan PTP kanal 81/83, interrupt, pogrešna veličina, pogrešan
wrapper te duplikat/dvosmisleno vlasništvo vraćaju nulu. Funkcija ne alocira
endpoint i ne dokazuje legitimnost pointera; mora ih dobiti iz provjerenog
kernel START ugovora. U provjeri su svi ti objekti eksplicitni predlošci.

## Izričita MOD izmjena START taga

Builder čuva originalni modul i proizvodi odvojeni
`reference-endpoint82.offline.o`. Prije izmjene provjerava cijeli SHA i
točne bajtove instrukcije na .text+116c (`7e20e0e3`). Mijenja ih u
`7d20e0e3` (`mvn r2,#0x7d`). U cijeloj datoteci razlikuje se točno jedan
bajt, na file offsetu 11a0. Relokacije i ostali bajtovi ostaju isti.

Originalni odsječak upisuje 81; izričito izmijenjeni odsječak upisuje 82.
Nijedan nije izvršen kroz cijeli START. Registri/request memorija eksplicitni
su predlošci i zaustavljanje je prije daljnjih native poziva.

SHA-256 izmijenjenog offline objekta:
4e45ec555d284ce5686babbd4a56dcfcbb073e71dc2ffdd2de606a290a2a3307.
To nije kompletan povezan modul i ne smije se učitati kao gotov UVC+PTP mod.

## Provjere

`tools.research.build_uvc_ptp_adapter` gradi samostalan ARM ELF bez
neriješenih importa. Izvršava stvarni kompajlirani adapter, izvorne ARM
classification odsječke i zaseban MOD odsječak. Referentni kod je
write-protected tijekom izvršavanja; host ga između usporednih pokretanja
izričito mijenja samo za dokumentirani MOD test i invalidira code cache.
Code/write guardovi ograničavaju izvršavanje i zapise.

55 provjera prolazi, uključujući entity ID očuvanje, originalni VC/VS put,
odbijanja bez zapisa, originalni count low-byte, endpoint identity/descriptor
negativne slučajeve i jednobajtnu MOD usporedbu. GET classification završava
prije alokatora/queueing; SET_CUR test potvrđuje samo transformirane bajtove.
Nema izmišljenih uspješnih firmware allocator ili callback povrata.

```
python -m tools.research.build_uvc_ptp_adapter --output-dir artifacts/native/uvc-ptp-adapter-e0155
```

Rezultati i hashovi: `artifacts/native/uvc-ptp-adapter-e0155/manifest.json`.
Postojeći live bridge i builder modula nisu mijenjani. Prethodnih 605
projektnih testova iz E0154 nije ponavljano jer novi izolirani dijelovi nisu
povezani s postojećim runtimeom.

## Preostalo prije kamere

Potrebno je dokazati setup-buffer lifetime/completion i vezati novi wire
shadow routing bez promjene reference lifetime ugovora. Još nije provedeno
zajedničko PTP/UVC gadgetcore register/stop/unregister niti rollback u PC
Remote, FS konfiguracija/Windows grouping, ili native JPEG/DMM ownership.
Postojeći bridge uspoređuje cijeli wIndex s interface brojem, što odbija
entity high-byte; njega treba izričito prilagoditi pri integraciji, uz ove
kontrole. Ne povezivati adapter kao da samo njegovo postojanje to rješava.

U ovom koraku nema pristupa kameri, uploadova, modula, feeder procesa,
promjene USB načina ili SD/trajnih zapisa. Fizički UVC+PTP nije dokazan.
