# E0177 — Fizički USB vlasnik i provjereno stanje izvorne usluge

Datum: 2026-11-08. Korisnik prebacio kameru u Mass Storage. Postojeći debugger PID703 ponovno dostupan kao root. Zajednički PTP/UVC modul nije prenesen ni učitan. Svi novi payload/log zapisi na kameri ostaju u `/tmp_bt`.

## Popis vlasnika na kameri

Novi `tools/research/capture_uvc_ptp_owner_inventory.py` prenosi samo mali read-only alat, provjerava byte-equal readback, izvrši ga uz zapis u `/tmp_bt` i arhivira njegov puni izlaz na host. Ne zamjenjuje USB konfiguraciju i ne zaustavlja grupu dretava.

Prvi pokušaj arhiviran je u `artifacts/hardware/uvc-ptp-live-owners-e0177`: alat E0176 pogrešno je koristio broj 0x10000 za O_DIRECTORY. Na ARM-u je to druga zastavica, pa je open `/proc` odbijen i alat završio `proc_unavailable`/exit3. Nije bio valjan popis vlasnika. Prethodni fixture audit koristio je istu pogrešnu pretpostavku i nije dokazao stvarni kernel ABI zastavice.

Ispravak koristi izvorni cross-target `<asm/fcntl.h>` i `O_RDONLY|O_DIRECTORY` (ARM 0x4000). Ispravljeni alat ima 3376 bajtova, SHA-256 `6302bf9333e0cb2032771b0f4b1abfe4fac40bea85a44d0684990ae17ba4ef83`. Nova izgradnja: `artifacts/native/uvc-ptp-owner-inventory-e0177/uvc_ptp_owner_inventory`; ispravljeni offline audit ponovno prolazi 23 provjere.

Prvo uspješno fizičko očitanje u 13:08:57 UTC i ponovljeno očitanje daju iste OWNER/TASK zapise:

- character uređaj 242:1 (`usb/gadgetcore`) drži **PID149, FD85**;
- vlasnik ima **175 dretava**;
- oba završetka: owners=1, threads=175, errors=0;
- oba loga arhivirana su bez truncationa.

To su dvije opažajne snimke, ne atomarna potvrda nepostojanja novih vlasnika ili već započetih syscallova. Detalji: `artifacts/hardware/uvc-ptp-live-owners-e0177-corrected/{manifest.json,repeat-manifest.json,owners.log,owners-repeat.log}`.

## Stvarne dretve i čekanja

Pročitani su comm/wchan za svih 175 dretava. OSAL proxy TID150/151/152/156 sva četiri pokazuju `__k_4u_wait_cb`. UsbControl imena imaju TID323/650/651/818/821; TID650 čeka u `usb_event_read`, ostali opaženi UsbControl u `futex_wait_queue_me`.

Imena nisu sama po sebi dokaz određenog C++ objekta ili jedinstvenog izvršitelja. `/proc/149/task/<tid>/syscall` i `/stack` na ovoj kameri vraćaju ENOENT; svih 18 neuspjelih read-only pokušaja zadržano je u `kernel-waits-manifest.json`. Nema zaključka da je kernel stack time pregledan.

## Izvorne biblioteke i live objekt

Prva whole-file hash provjera zaustavila je daljnje čitanje jer se hashovi stvarnih `/usr/lib` biblioteka razlikuju od izdvojenih datoteka. Stvarne datoteke zatim su očitane i sačuvane prije nastavka:

| Biblioteka | Stvarni SHA-256 |
|---|---|
| libUsbControl.so | b5cea9d2c92a0b0810353900871fa2806ca3064aa5d8cf3ca7db5ddb6f3940e2 |
| libInfraUsbCmn.so | 733acef066e3e3691f7258e7416b638a7960d99b70f27e85ddc4daad2b5ecef2 |

Sekcijska usporedba pokazuje jednaku adresu i byte-equal sadržaj **svih allocatable sekcija**, uključujući .text, .plt, .rodata, .data i relokacije; među uspoređenim sadržajima razlikuje se .comment. Whole-file hashovi nisu proglašeni jednakima. Odabrana dinamička imena i tijela doStop/doSyncStartStop/doInitialize te CUsbSvc::stop/usbif_initialize zasebno su uspoređena. Nije korišten generički pomak između različitih izdanja.

Na temelju stvarnih maps/ELF PT_LOAD ugovora dobivene su baze libUsbControl=0x04857000 i libInfraUsbCmn=0x04161000. Bounded debugger memory read usporedio je stvarno doStop tijelo s datotekom prije čitanja podataka. Svaka adresa i veličina podataka provjerena je prema čitljivim maps rasponima.

Opaženo je:

| Polje | Vrijednost |
|---|---|
| pending completion queue | 0 |
| javni USB interface objekt | 0x001f09f8 |
| CUsbSvc objekt | 0x00056e28 |
| izvorni start/stop pokazivači | 0x0416e551 / 0x0416e37d |
| CUsbSvc gadgetcore FD (+0x90) | **85**, jednako FD inventaru |
| service state (+0x98) | 3 |
| gadget/host handle | 0 / 0xffffffff |

Izvorni service state 3 i pending queue 0 opaženi su u odvojenim kratkim čitanjima. Nisu dokaz da su svi kernel ulazi ili EP0 callbackovi ispražnjeni. Debugger memory read privremeno koristi ptrace na pojedinoj čitanoj dretvi; nema grupnog CPU freezea ni zapisa u aplikacijsku memoriju. Finalni status potvrđuje da ptrace nije ostao priključen.

## Završno stanje i sljedeći korak

Kamera je u Mass Storage načinu, debugger PID703 ostaje responzivan. `/proc/version` potvrđuje 3.0.27_nl-rt106+ SMP PREEMPT RT; sačuvani `/proc/modules` ne sadrži novi zajednički UVC kandidat. Artefakti, biblioteke, stvarni podaci i finalni status nalaze se u mapi uspješnog capturea.

Sada postoji fizički dokaz koji proces drži gadgetcore i koji mu izvorni objekt pripada. Sljedeći korak je ograničena provjera potpunog zaustavljanja tih ulaza i njihova nastavka prije postavljanja omotača, uz zasebnu granicu za kernel/gadget callbackove. E0164 ostaje `physical_test_ready:false`; nije testirana zajednička enumeracija, kamera kontrola tijekom UVC-a niti senzorski UVC tok.
