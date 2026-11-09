# E0154: Nativni kandidat UVC+PTP i izvorni Sony serializer

Datum: 2026-11-08.

## Korisnikov cilj

Kompatibilnost sa Sonyjevim desktop programima nije zahtjev. Cilj je UVC
video uz izvorni PTP/PC Remote protokol za buduće vlastite open-source
programe. To ne uklanja potrebu za aktivnim originalnim Sony PTP driverom,
sensorom, native callbackovima i vlasništvom memorije.

## Implementacija

Dodani `tools/native_camera/uvc_ptp_descriptors.{c,h}` implementiraju zaseban
ARM32 kandidat tablice u izvornom Sony formatu: speed entry 16 bajtova,
configuration 24, interface 8, alternate 20 i endpoint 20. Veličine su
zaštićene compile-time provjerama.

Kandidat nije povezan s fizičkim modulom i ne izvodi registraciju niti
promjenu USB veze. Popunjen je samo High Speed profil. Nema deklarirane
Full/Super Speed podrške; to ostaje prepreka prije primjene.

| Sučelje | Funkcija | Kanali |
|---|---|---|
| 0 | Originalni PTP 06/01/01 | 81 Bulk IN, 02 Bulk OUT, 83 Interrupt IN |
| 1 | UVC VideoControl | bez endpointa |
| 2 | UVC VideoStreaming | 82 Bulk IN, 512 bajtova |

0x82 nije izložen u fizički očitanom PC Remote rasporedu. Raniji kandidat
0x84 zamijenjen je s 0x82: originalni dwc3_gadget_init pokreće
dwc3_gadget_init_hw_endpoints s brojem IN endpointa iz dwc+2f2; taj helper
konstruira indekse redom od nule (`r7`). Izlaganje 0x83 uz taj inicijalizator
snažno upućuje da prethodni IN endpoint 0x82 postoji. Ovo je zaključak iz
statičkog koda i deskriptora, ne očitanje živog slota, alokacijski rezultat,
slobodan TRB/FIFO kapacitet ili fizički UVC prijenos na 0x82.

VideoControl i VideoStreaming class-specific blokovi dolaze iz izvorne
ZV-E10 libInfraUsbCmn.so. Promijenjena su točno dva bajta: VC baInterfaceNr
1->2 i VS bEndpointAddress 81->82. Izvorni profil ostaje 1280x720/30;
nije time dokazan senzorski UVC 720p30. Audio nije uključen u ovaj kandidat.

Posebna ARM funkcija umeće video IAD prije sučelja 1. Prvo validira cijeli
lanac, duljinu, kapacitet i jedinstveno mjesto umetanja. Odbija ponovljeno
umetanje i ne mijenja buffer pri odbijanju. Prima potpuno serijaliziranu
konfiguraciju; u budućem live wrapperu mora se pozvati prije skraćivanja na
hostov wLength. Nije dopušteno pozvati je nad već skraćenim header odgovorom.

## Originalni serializer izvršen do povratka

`tools.research.build_uvc_ptp_descriptor_candidate` gradi samostalan ARM ELF,
bez neriješenih importa. Zatim stvarno izvršava njegov init i IAD funkciju,
te originalni a6400 make_config_desc na 602bbc54 i memcpy na 60258b80.
Nema host zamjene serializera/memcpyja niti lažnog uspješnog firmware povrata.
Kernel je write-protected. Izvršavanje je ograničeno na te originalne
funkcije i kompajlirani kandidat; zapisi samo na deklarirani kandidat,
output i stack. Gadgetcore, speed=3, caller-owned tree i zahtjevi eksplicitni
su izvanmrežni predlošci, ne snimka aktivnog kontrolera.

Provjereni identiteti:

- a6400 kernel SHA-256: 12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707.
- ZV-E10 libInfraUsbCmn.so SHA-256: af830315ce51c38b010995f2147d556286364323734f64b877fcc3bb1a916c02.

24 provjere prolaze, uključujući originalni povrat cijele konfiguracije,
9-byte header, 17-byte i zero-length zahtjeve, jedinstvene endpoint adrese,
jednakost PTP interface/endpoint bajtova s fizičkim PC Remote očitanjem,
točno ograničene izmjene originalnih VC/VS blokova, ispravan IAD i odbijanja
bez parcijalnih zapisa. IAD povećava konfiguraciju sa 165 na 173 bajta.

Artefakti: `artifacts/native/uvc-ptp-descriptors-e0154/`:

- `candidate.elf`: izvanmrežni ARM kandidat, nije kernel modul.
- `sony-serialized-before-iad.bin`: originalni serializer output, 165 bajtova.
- `uvc-ptp-hs-config.bin`: nakon kompajlirane ARM IAD funkcije, 173 bajta.
- `manifest.json`: svih 24 provjera, hashovi, granice dokaza i konfiguracija.

Izgradnja:

```
python -m tools.research.build_uvc_ptp_descriptor_candidate --output-dir artifacts/native/uvc-ptp-descriptors-e0154
```

## Fizički PC Remote ugovor i granica deploya

GetDeviceInfo 1001 vratio je 2001 i ILCE-6400. Oglašene vendor operacije:
9201, 9202, 9205, 9207, 9209. Nisu oglašene 9280/9281, koje postojeći
debugger transport koristi u MTP-u. Odsutnost u popisu nije sama dokaz
da poziv nikad ne radi, ali nije opravdano pretpostaviti da debugger nakon
MSC->PC Remote prijelaza ostaje dostupan. Nijedan 9280/9281 poziv nije poslan.
Sačuvani raw DeviceInfo i JSON u
`artifacts/hardware/uvc-ptp-coexistence-e0152/pc-remote-device-info.*`.

Kandidat još nije spreman za učitavanje. Treba:

- Vezati UVC wire sučelja 1/2 na reference callbackove koji očekuju stari
  raspored; posebno provjeriti wIndex/entity ID i vijek zahtjeva.
- Promijeniti fizički START endpoint bridge s hardkodiranog 81/dwc+dc na
  provjereni 82/dwc+e4, uz native wrapper identitet i descriptor guardove.
- Očuvati originalni PTP driver u zajedničkoj gadgetcore konfiguraciji,
  implementirati registraciju i teardown s povratom u PC Remote.
- Riješiti Full Speed odgovor, device descriptor/Windows grouping, EP0
  puni odgovor prije IAD/truncation i readback/oporavak bez izgubljenog debuggera.
- Vezati stvarne native JPEG kadrove uz DMM vlasništvo i dimenzije profila.

Nema testa fizičke enumeracije zajedničkog uređaja niti UVC+PTP prijenosa.

## Provjere i završno stanje

Puni skup: 605 testova prošlo u 18.685 s. Dodatno 24 izvanmrežne ARM kontrole
prošle. Završno hub očitanje `pc-remote-after-e0154.json` potvrđuje isti Sony
054c:0caa i iste izvorne PC Remote deskriptore, bez grešaka. Nema camera
uploadova, modula, feeder procesa, promjene USB načina, SD/trajnih zapisa.
