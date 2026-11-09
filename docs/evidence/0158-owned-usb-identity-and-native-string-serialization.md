# E0158: Puni HS identitet i vlastita memorija USB stringova

Datum: 2026-11-08. Nastavak E0157.

## Fizičko čitanje, bez promjene veze

`capture_sony_usb_hub --strings` proširen je čitanjem stvarnih stringova
na indeksima navedenim u originalnom device descriptoru. Očitan je isti
Sony 054c:0caa, PTP konfiguracija nepromijenjena, LANGID 0409. Proizvođač
Sony, proizvod ILCE-6400 i stvarni serijski broj CF93603BE631 sačuvani su
zajedno s raw UTF-16LE deskriptorima, ne izvedeni iz Windows friendly namea.

Rezultat:
`artifacts/hardware/uvc-ptp-coexistence-e0152/pc-remote-identity-e0158.json`.
Nijedan USB reset, konfiguracijski zapis ili kamera upload nije izveden.

## Native table i vlasništvo

`uvc_ptp_descriptors.{c,h}` kandidat sada sadrži punih 88 početnih bajtova
Sony descriptor tablea: tri speed entryja po 16 i 40 bajtova metadata.
Offset configuration objekta iza njih provjeren je compile-time assertom.
Jezični i string entryji imaju izvorni ABI od 8 bajtova.

`a6400_uvc_ptp_candidate_identity` validira capture format prije zapisa,
kopira VID/PID/bcdDevice i originalne UTF-16LE payloadove u caller-owned
kandidat. String pointeri i jezična tablica upućuju u taj isti objekt.
Zadržavanje originalne tablice nakon prijelaza nije potrebno radi stringova.
Kandidat mora ostati živ do potpunog povlačenja svih native korisnika.

Trenutno je podržan točno dokazani izvor: indeksi 1/2/3, jedan LANGID 0409,
do 64 payload bajta po stringu. Ostali rasporedi nisu generički prihvaćeni.
Neispravan device/string format, neparna duljina i prevelik payload odbijaju
se bez promjene objekta.

Device identitet zadržava VID/PID 054c:0caa, bcdDevice0200 i tri stvarna
stringa. Za eksperimentalni zajednički HS uređaj class/subclass/protocol
postavljeni su na EF/02/01 uz postojeći video IAD. To je MOD deklaracija
kompozitnog uređaja, ne dokaz Windows driver bindinga. Nije dodijeljen ili
izmišljen novi USB VID/PID.

## Izvorni Sony serializeri

Izvršeni su do povratka:

- make_device_desc 602bb988.
- make_string_desc 602bc0cc.
- make_config_desc 602bbc54 i memcpy 60258b80 iz prethodnog ugovora.

Originalni kernel SHA-256 i referentna library identity ostaju verificirani.
Nema host zamjene za ove funkcije. Code/write guardovi ograničavaju
izvršavanje i zapise. Gadgetcore, HS stanje, EP0 maxpacket64 i memorija
caller objekata eksplicitni su izvanmrežni predlošci, ne live kernel dump.

Nakon identity init-a izvorni capture bufferi u provjernoj memoriji brišu se
na nulu. Native string serializer i dalje vraća originalne stringove iz
kandidatove vlastite memorije. Sam kandidat se tijekom serijalizacije ne
mijenja. Iz iste pune tablice config reply vraća istih 173 bajta.

Važan izvorni ugovor: make_string_desc zapisuje puni string pa samo skraćuje
povratnu duljinu. Provjera zato dopušta puni privremeni buffer; live EP0
integracija mora ga stagingirati i zatim kopirati odgovarajući prefiks,
kao što već radi config reply. Ne proslijediti mali caller buffer izravno
originalnom string serializeru uz mali wLength.

## Rezultati

254 izvanmrežne kontrole prolaze: uključene ranije 172 i dodatne provjere
HS device identiteta, language/string odgovora, kratkih zahtjeva, owned-data
trajanja, unsupported jezika/indeksa, očuvanja konfiguracije i odbijanja bez
mutacije. To nisu fizički USB transfer testovi. Pet testova postojećeg hub
configuration parsera također prolazi. Puni projektni skup nije ponavljan
nakon E0156 jer novi dijelovi nisu povezani s postojećim runtimeom.

`artifacts/native/uvc-ptp-identity-e0158/` sadrži samostalan ARM ELF,
manifest s hashovima te stvarne outpute native serijalizera:

- native-hs-device-descriptor.bin.
- native-string-0.bin (LANGID), native-string-1/2/3.bin.
- native-ep0-reply-9.bin i native-ep0-reply-173.bin.

## Preostala integracija

Ovo je verificiran HS device/config/string kandidat, nije bootabilni niti
učitani UVC+PTP modul. Nedostaju live EP0 hook i staging za device/string
odgovore, FS/other-speed/qualifier ugovor, zajednički gadgetcore
register/stop/unregister i rollback te native JPEG/DMM producer.

Zadržani PID0caa znači da postojeći host UVC auto-launcher koji traži samo
PID0322 nije dovoljan za budući shared uređaj. Detekciju treba povezati s
provjerenim Sony UVC interface identitetom, uz zadržavanje zaštite od drugih
web kamera. Ta promjena još nije provedena. Kompatibilnost sa Sonyjevim
desktop programima ostaje izvan zahtjeva.

Fizičko Windows nabrajanje zajedničkog uređaja, driver grouping, UVC video
i istovremene PTP kontrole ostaju nepotvrđeni. Kamera je pri fizičkom
očitanju bila u PC Remoteu; ovaj korak nije promijenio taj način, SD, trajnu
memoriju ili aktivne module.
