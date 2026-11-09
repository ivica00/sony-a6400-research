# E0153: PC Remote kanali i izvorni PTP ugovor

Datum: 2026-11-08. Nastavak E0152 nakon korisnikovog prijelaza u PC Remote.

## Fizičko očitanje

Windows WPD enumeracija pronašla je Sony `054c:0caa`, serijski broj
CF93603BE631. Windows PnP potvrđuje ILCE-6400, klasu WPD, status OK.
Libusb pod tim upravljačkim programom nije izlistao uređaj. Prazan rezultat
`pc-remote-usb-descriptors.json` nije dokaz odsutnosti kamere.

Novi alat `tools.research.capture_sony_usb_hub` čita standardne deskriptore
kroz Windows USB hub bez zamjene upravljačkog programa. Koristi samo
GET_NODE_INFORMATION, GET_NODE_CONNECTION_INFORMATION_EX i
GET_DESCRIPTOR_FROM_NODE_CONNECTION; nema resetiranja, claimanja sučelja
ili postavljanja konfiguracije. Microsoft opis tog pristupa:
https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/usbioctl/ni-usbioctl-ioctl_usb_get_descriptor_from_node_connection

Sačuvan izvorni rezultat:
`artifacts/hardware/uvc-ptp-coexistence-e0152/pc-remote-hub-descriptors.json`.
Jedna konfiguracija, sučelje 0 klase 06/01/01, ukupno 39 bajtova:

| Funkcija | Adresa | Tip | Max packet | Interval |
|---|---|---|---|---|
| PTP ulazni podaci | 0x81 | Bulk | 512 | 0 |
| PTP izlazni podaci/naredbe | 0x02 | Bulk | 512 | 0 |
| PTP događaji | 0x83 | Interrupt | 32 | 7 |

To potvrđuje stvarni konflikt sadašnjeg UVC Bulk IN 0x81 s PC Remote PTP-om.

## Izvorni ARM ugovor

`tools.research.probe_ptp_endpoint_contract` provjerava SHA-256 izvornog
usbg_stillimage.ko `d4843c6abac908881ef5a96fd570fb345f766fff9ee562413f5f63e9cc7e0ff9`.
Tri originalna ravna ARM odsječka iz core_cb_start upisuju 0x81, 0x02 i 0x83
u zahtjeve na pomacima +14, +1c i +24. Zaustavljaju se prije poziva alokatora.
Scratch registri i memorija eksplicitni su testni predlošci; nije simuliran
uspješan alokator niti izvršen cijeli START. Podudarnost s fizičkim
deskriptorima nije dokaz jednakosti svih živih bajtova modula.

Osam dodatnih originalnih ARM provjera funkcije dwc3_wIndex_to_dep pokazuje
mapiranje 0x81 -> dwc+dc, 0x02 -> +e0, 0x83 -> +ec, 0x84 -> +f4, te povrat
nule za neaktivan endpoint. Kernel SHA-256 provjeren prema ranijem ugovoru.
Slotovi i enabled zastavice eksplicitni su predlošci. Lookup 0x84 nije dokaz
da je taj endpoint fizički alociran, slobodan ili podržan kontrolerom.

Rezultati svih 11 provjera:
`artifacts/hardware/uvc-ptp-coexistence-e0152/ptp-original-arm-controls.json`.

## Stvarni senzorski kadrovi kroz PTP

Sony SDIO handshake vratio je 2001 za sva četiri koraka, ExtDeviceInfo 136
bajtova. Prvi ograničeni niz imao je četiri prazna početna pokušaja i šest
JPEG kadrova. Drugi niz dobio je deset kadrova bez praznih pokušaja, svi
1024x680, s različitim SHA-256 vrijednostima, oko 101 KB po kadru.
Trajanje drugog kratkog niza 0.294 s nije mjerenje održivog FPS-a.

Sačuvani su oba izvještaja i prvi uspješan kadar drugog niza:
`pc-remote-sensor-capture.json`, `pc-remote-sensor-capture-warm.json`,
`pc-remote-sensor-frame.jpg` u gornjem direktoriju. Slika vizualno pregledana:
stvarni stol, ambalaža, kabeli i zvučnik; nije testni uzorak.
Nije testirana promjena ekspozicije ili snimanja. Ovo je PTP, ne UVC.

## Posljedice za implementaciju

Sačuvati PTP sučelje 0 i adrese 81/02/83. Predložena radna topologija jest
UVC VideoControl 1 i VideoStreaming 2, s posebnim Bulk IN endpointom.
0x84 je kandidat za provjeru, ne odobrena fizička konfiguracija.
Sadašnji modul ima i audio sučelja te IAD injekciju koja očekuje četiri
sučelja; to se mora izričito preraditi, zajedno s VC/VS međureferencama,
callback interface routingom i Windows povezivanjem WPD/usbvideo drivera.
Sadašnji START bridge također je vezan za dwc+dc i adresu 81; promjena
samo USB deskriptora ne može biti dovoljna.

Preostaje dokazati kapacitet i raspoloživost kontrolera, izraditi zajedničku
tablicu deskriptora i callback lifecycle s povratom u PC Remote, zatim vezati
originalni proizvođač JPEG-a uz dokazano vlasništvo. Ne resetirati aktivni
shooting SET_PATH/DMM Rule 5/0 postojećim MSC feederom. Dimenzije 1024x680
ne smiju se slati kao da su oglašenih 1280x720.

## Provjere i završno stanje

Pet provjera parsera prolazi: stvarni deskriptor i odbijanje truncation,
nulte duljine, pogrešnog broja endpointa i pogrešnog broja sučelja.
Svih 11 novih originalnih ARM kontrola prolazi. Prethodni puni skup 600
testova iz E0152 nije ponovno izvođen jer se postojeći runtime nije mijenjao.
Nije učitan UVC modul, pokrenut feeder, promijenjen USB način ili pisano na
kameru, SD ili trajnu memoriju. Kamera je ostavljena u PC Remote načinu.
Istovremeni fizički UVC+PTP rad i dalje nije dokazan.
