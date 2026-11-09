# E0165 — Izvorna USB active oznaka nije zaštita cijele transakcije

Datum: 2026-11-08. Nema pristupa kameri, prijenosa ni zapisa. Kandidat E0164 ostaje nepromijenjen i nije spreman za fizički pokus.

## Izvršeni izvorni kod

`tools/research/probe_uvc_ptp_native_serialization.py` SHA-provjerava originalni a6400 kernel (`12eeec829407595e28265f7d0db3b88c56f63a9f0fdd725c9c53c66a49643707`) i izvršava originalni `usb_gadgetcore_ioctl` na 0x602b8844 te originalne ARM atomske funkcije `_test_and_clear_bit` i `_test_and_set_bit`. Ne zamjenjuje njihove odluke hostovim kodom.

17 provjera prolazi. Rezultat: `artifacts/analysis/uvc-ptp-serialization-e0165/manifest.json`. GC, gadget, ops, stari root i dvije stogovne regije izričiti su fixture podaci. Get-speed servis je izričita zamjena. Pullup i save_desc_tbl su granice prije kojih se izvršavanje zaustavlja; kontroler i alokator se ne izvršavaju.

| Originalni put | Utvrđeni redoslijed |
|---|---|
| Commit 0x400ce203 | test_and_set_bit(2, gc+0x68); ako je već postavljen, -EBUSY; inače speed, save_desc_tbl, gcw_start, pullup(1) |
| Disconnect 0xe204 | test_and_clear_bit(2, gc+0x68); ako nije bio postavljen, povratak; inače pullup(0), setup_disconnect, gcw_stop, free_desc_tbl |

Ostali bitovi ostaju očuvani. Posebno: nakon brisanja active bita, a prije prvog pullup(0), gc+0x6c još pokazuje stari root. U izričitom pokusu preplitanja drugi poziv originalnog commit puta na zasebnom stogu prolazi test_and_set_bit, ponovno postavlja active i dolazi do save_desc_tbl sa starim rootom još prisutnim.

Ovo dokazuje da ova oznaka sama ne osigurava međusobno isključivanje cijelog postupka. Ne dokazuje da fizički Sonyjev raspoređivač ili pozivatelji stvarno dopuštaju taj raspored. Vanjsko usklađivanje ostaje otvoreno pitanje. Nije dopušteno proglasiti active bit mutexom ili ga koristiti kao rezervaciju tijekom naše cijele zamjene.

## Izvorni korisnički pozivatelj

Zadržana a6400 `libInfraUsbCmn.so`, SHA-256 `5338bafbb545ebc223fac15c9253a41ac9fe49c01fe32c73af40c3fb50eec0a6`, izvoz `CUsbSvc::stop_gadget` na Thumb 0x9c55:

- 0x9c62 priprema ioctl 0xe204, a 0x9c72 poziva ioctl PLT 0x7b20.
- 0x9c7a priprema ioctl 0xe202, a 0x9c80 opet poziva ioctl.
- Tek 0x9c84 priprema this+0xa4 i 0x9c8e poziva pthread_mutex_lock preko PLT 0x7b94.
- 0x9d34 poziva pthread_mutex_unlock preko PLT 0x7af4.

PLT odredišta utvrđena su iz njihovih stvarnih ARM add/add/ldr instrukcija i `.rel.plt`: GOT 0x1b950=ioctl, 0x1b974=pthread_mutex_lock, 0x1b944=pthread_mutex_unlock. Nije korištena pretpostavka da sve PLT stavke imaju isti razmak (Thumb interworking umetci to onemogućuju).

Disassembly je zadržan u `artifacts/analysis/uvc-ptp-serialization-e0165/original-userspace-callers.txt`. Završni literal pool u tom grubom ispisu nije dokaz izvršivog koda. Gore navedene upute nalaze se u stvarnom tijelu funkcije. Ispravak E0166: start_gadget 0x9ed9 predaje posao kroz **CUsb::request**, PLT 0x7b10 / GOT 0x1b94c. Ranija oznaka port_init bila je pogrešna jer je dobivena pretpostavkom stalnog razmaka PLT stavki, a ne stvarnim odredištem ove stavke. Njegov vanjski red poruka i radna dretva nisu izvršeni u E0165.

Mutex this+0xa4 ne obuhvaća navedeni disconnect ioctl u ovom tijelu. Ne smije se uzeti kao zajednička zaštita za kernel modul bez dokaza o vanjskom pozivatelju, životnom vijeku i svim drugim USB ulazima.

## Daljnji rad

Pratiti CUsb::request i red poruka CUsbSvc do stvarnog izvršitelja promjena (nastavak E0166). Utvrditi može li se zajednička konfiguracija postaviti kroz isti izvorni put ili treba zaštititi sve izvorne kernel ulaze. Samostalni mutex u našem modulu, active bit i spinlock gc+0x30 nisu zamjenjivi: posljednji štiti drukčije dijelove registra/callback podataka i ne smije se držati preko spavajućih operacija bez dokaza.

Nisu izvršeni novi projektni regresijski testovi jer produkcijski kandidat nije mijenjan. Prethodni rezultat E0164 ostaje 605 prolaznih testova. Novi probe prolazi svih 17 specifičnih provjera originalnog koda.
