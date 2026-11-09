# E0152: Granica zajedničkog UVC videa i Sony PC Remote upravljanja

Datum: 2026-11-08.

## Opseg i fizički nalaz

Korisnik traži UVC video uz zadržano Sony PC Remote upravljanje. Kamera je,
prema korisniku i očitanim deskriptorima, spojena u Mass Storage načinu.
Postojeći debugger odgovara. Očitanje `/proc/modules` pokazalo je učitane
`usbg_storage` i `usbg_stillimage`, bez `usbg_video_a6400`. Sama prisutnost
stillimage modula ne dokazuje aktivno PC Remote sučelje.

`tools.research.capture_sony_usb_layout` očitao je standardne USB deskriptore
bez promjene konfiguracije, preuzimanja sučelja, PTP sesije ili resetiranja.
Rezultat: `artifacts/hardware/uvc-ptp-coexistence-e0152/host-usb-descriptors.json`.
Sony VID/PID 054c:0ca8, jedna konfiguracija, jedno sučelje 0 klase 08/06/50,
Bulk IN 0x81 i Bulk OUT 0x02, oba max-packet 512. Nema izloženog PTP sučelja.
WPD enumeracija Sony uređaja vratila je prazan popis, što odgovara MSC stanju.
Windows Get-PnpDevice provjera nije uspjela zbog odbijenog pristupa; zaključak
o načinu temelji se na uspješnom libusb očitanju, ne na toj provjeri.

## Granica sadašnjeg UVC modula

`a6400_uvc_commit_descriptors` u `tools/native_camera/uvc_composite_shim.c`
prekida USB vezu, zaustavlja gcw, mijenja tablicu deskriptora i pokreće
single-function konfiguraciju (`desc_arg.is_dual=0`). Zatim ponovno spaja USB.
To je zamjena USB konfiguracije; naziv composite ne dokazuje UVC+PTP.
Postojeći UVC bridge očekuje Bulk IN 0x81 (E0142), koji sada koristi MSC.
To dokazuje konflikt pri naivnom dodavanju MSC-a postojećem UVC-u, ali još
ne dokazuje konflikt s PC Remote endpointima: njih tek treba očitati.

E0150 dokazuje prijenos testnog uzorka kroz Sony UVC. Ne dokazuje senzor.
E0151 bilježi stvarni senzor preko PTP-a 1024x680. To nije dokaz UVC senzora,
istovremene PTP kontrole niti 1280x720 senzorskog UVC-a.
E0149 fizički dokazuje prazan JPEG prsten u ispitanom MSC stanju; uzrok
potpune ISP/senzor standby politike ostaje tumačenje, a ne zasebno mjerenje.

## Ispravak lažne potvrde upravljanja

`/api/control` u CinemaHUD-u prethodno je mijenjao samo hostov `camera_state`
i vraćao uspjeh bez Sony naredbe. Sada vraća HTTP 501 i `applied:false`,
bez promjene stanja. Status objavljuje da upravljanje nije dostupno.
REC više lokalno ne pali oznaku snimanja niti prikazuje potvrdu početka.
Klijent prikazuje stvarnu grešku odgovora. Postojeće početne ekspozicijske
vrijednosti ostaju neprovjereni podaci prikaza; nisu telemetrija kamere.

HTTP regresijska provjera za ISO, REC i pokušaj promjene oznake dostupnosti
potvrdila je odbijanje i nepromijenjeno stanje. Nije korištena fizička kamera
za tu provjeru i nije dokazana nijedna Sony write naredba.

## Sljedeći fizički korak

U PC Remote načinu ponoviti čitanje:

```
python -m tools.research.capture_sony_usb_layout --output artifacts/hardware/uvc-ptp-coexistence-e0152/pc-remote-usb-descriptors.json
```

Zatim dokazati izvorni stillimage callback/endpoint ugovor i slobodne kanale
kontrolera, prije izrade zajedničke tablice UVC+PTP i promjene bridgea.
Sačuvati Sony shooting stanje i vlasništvo memorije. Postojeći sensor feeder
bezuvjetno postavlja Rule 5, resetira SET_PATH te pri završetku vraća Rule 0;
to nije provjeren ugovor za kameru koja već snima u PC Remote načinu.
Ne pokretati ga u tom stanju bez rješavanja vlasništva i obnavljanja prethodnog
stanja. Također treba provjeriti stvarne dimenzije JPEG-a prema UVC profilu.

U ovom koraku nije učitan modul, pokrenut feeder, promijenjen USB način niti
pisano na kameru, SD ili trajnu memoriju. UVC+PTP zajednički rad nije dovršen.

## Regresijska provjera

`python -m unittest discover -s tests`: svih 600 testova prošlo u 17.185 s.
Prvi pokušaj imao je četiri greške pristupa privremenim datotekama; isti skup
ponovljen s potrebnim pristupom prošao je bez greške. Ove provjere ne dokazuju
fizički zajednički UVC/PTP rad ni fizički pristup SD kartici.
