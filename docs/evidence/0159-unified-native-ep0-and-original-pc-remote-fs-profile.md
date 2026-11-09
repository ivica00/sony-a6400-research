# E0159: Jedinstveni native EP0 i originalni PC Remote Full Speed profil

Datum: 2026-11-08. Nastavak E0158. Bez fizičkog pristupa kameri u ovom koraku.

## Izvorni a6400 FS dokaz

U originalnoj a6400 libInfraUsbCmn.so, SHA-256
5338bafbb545ebc223fac15c9253a41ac9fe49c01fe32c73af40c3fb50eec0a6,
dinamički simbol `remotepc_interface_desc` ima VA1ae34 i veličinu24.
Tri native interface grupe upućuju na HS/FS/SS alternate zapise.

Verificirano stvarnim pointer lancem i točnim bajtovima:

| Profil | Group VA | Alternate VA | Endpoint array VA |
|---|---|---|---|
| HS | 1ae34 | 1adf8 | 1ae4c |
| FS | 1ae3c | 1ae0c | 1ae88 |

Oba originalna alternatea imaju class/subclass/protocol06/01/01, alternate0
i tri endpointa. HS: 81 Bulk512, 02 Bulk512, 83 Interrupt32/interval7.
FS: 81 Bulk64, 02 Bulk64, 83 Interrupt32/interval10. Native byte5 endpoint
zapisa također je sačuvan (HS2/FS1). Po svih60 endpoint array bajtova
kompajliranog kandidata jednako je originalnom profilu za odgovarajuću brzinu.
Ovo je dokaz iz statičke firmware datoteke, ne čitanje živih library bajtova.

Originalna `remotepc_desc_tbl` metadata sadrži generički/stari PID0641,
različit od fizičkog 0caa. Zato metadata nije slijepo kopirana: VID/PID,
bcdDevice i stringovi ostaju stvarno očitani podaci iz E0158.

## MOD politika brzine

Kandidat je proširen vlastitom FS konfiguracijom, sučeljem, alternateom i
endpointima. Pri HS-u izlaže PTP0 + UVC1/2. Pri FS-u izlaže samo PTP0 i ne
oglašava UVC video. To je izričita MOD politika, ne originalna Sony odluka
ili fizički dokazana automatska promjena načina rada. FS endpoint parametri
su originalni; atributi/potrošnja konfiguracije prate prethodno očitani
kandidat 80/fa. Native stringovi i device identitet pripadaju istom objektu.

## Jedinstveni descriptor reply

`a6400_uvc_ptp_candidate_descriptor_reply` u
`tools/native_camera/uvc_ptp_descriptors.{c,h}` sada obrađuje:

- Device (1), configuration (2), string/language (3).
- Device qualifier (6).
- Other-speed configuration (7).

Poziva originalne Sony make_device_desc, make_config_desc,
make_string_desc i make_device_qualifier_desc (602bbfec), te originalni
memcpy. Koristi lokalni puni request i512-byte staging, pa kopira samo
traženi prefiks nakon potvrde očekivane duljine. Time i stringovi, čiji
originalni serializer piše cijeli opis prije skraćivanja povratne duljine,
ne mogu preliti mali caller output.

HS configuration ima173 bajta (PTP+UVC+IAD), FS39 (PTP-only). Other-speed
HS zahtjev vraća FS39/type7; FS zahtjev HS173/type7 s video IAD-om.
Originalni serializer proizvodi type7, koji se privremeno normalizira na
type2 samo u lokalnom stagingu radi postojećeg IAD validatora i zatim vraća
na7. Nativni caller setup nije promijenjen.

Qualifier za oba profila:
`0a 06 00 02 ef 02 01 40 01 00`. Obje brzine imaju jednu konfiguraciju.
SuperSpeed se odbija jer zajednički SS profil nije implementiran.

Prije originalnog serializera validiraju se vlastita HS/FS pointer stabla,
brojevi alternateova/endpointa, bounded extra blokovi i owned stringovi.
Prihvaćaju se samo standardni GET_DESCRIPTOR zahtjevi za podržane indekse,
jezik0409, aktualnu brzinu2(FS) ili3(HS). Nepodržan descriptor/jezik/index,
tuđa tablica, nedovoljan output i alias setup/tree buffera odbijaju se.
Caller mora držati topologiju stabilnom tijekom poziva; nema live locka.

## Provjere

`build_uvc_ptp_descriptor_candidate` izvršava stvarni kompajlirani reply
put i originalne Sony funkcije do povratka. Kernel je nepromjenjiv tijekom
izvršavanja i code/write guardovi ostaju aktivni. Memorija gadgetcorea,
brzina, EP0, caller objekti i stack eksplicitni su izvanmrežni predlošci.
Ni jedan service/callback povrat nije izmišljen.

511 kumulativnih kontrola prolazi (uključuju prethodne254). Za obje brzine
testirani su device/config/qualifier/other-speed i string0..3, svaki za
wLength0,9,65535. Potvrđeni su povratna duljina, bajtovi, netaknuti output
izvan povratne duljine, nepromijenjeni setup i vlastito stablo. Negativni
slučajevi uključuju unsupported type/string/jezik, premali output i SS.
To nisu511 fizičkih testova niti dokaz Windows povezivanja drivera.

Artefakti:
`artifacts/native/uvc-ptp-unified-ep0-e0159/manifest.json`, samostalan ARM ELF
i `unified-2-*`/`unified-3-*` raw odgovori, gdje2=FS,3=HS. Raniji artefakti
nisu prepisani. Postojeći live module builder i EP0 hook nisu promijenjeni.

## Preostalo

EP0 callback integration i stvarni device-group binding još nisu dokazani.
Treba povezati ovo owned stablo, UVC reference MOD i endpoint selector uz
zadržani originalni PTP driver, te provjeriti registraciju/STOP/unregister i
rollback. Native JPEG/DMM ownership i senzorski UVC kadrovi ostaju otvoreni.
Staging rješava duljinu odgovora, ali ne lifetime cijelog modula ili native
EP0 completiona. Host detekcija mora podržati planirani Sony UVC interface
uz PID0caa umjesto pretpostavke0322.

Nema camera uploadova, učitanog zajedničkog modula, feeder procesa, promjene
USB načina, SD ili trajnih zapisa. Fizički zajednički UVC+PTP nije potvrđen.
